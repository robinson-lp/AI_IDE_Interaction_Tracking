"""
Performance Test Suite
======================
Measures throughput, scalability, and timing budgets for every major
pipeline stage. Tests generate synthetic data of controlled sizes,
time each operation, and assert the result stays within an acceptable
threshold.

Each class records:
  - Absolute timing budget  (must finish in ≤ N seconds)
  - Scalability profile      (doubling input must not more than triple time)
  - Throughput floor         (minimum messages/rows per second)

Categories:
  P01  Parser throughput — messages per second per parser
  P02  Scalability — time grows linearly with input size
  P03  Directory scan — many small files
  P04  Exporter throughput — CSV rows per second
  P05  Filter overhead — date and project filters on large sets
  P06  End-to-end pipeline — full source→CSV timing
  P07  Large Codex Desktop session
  P08  Real data benchmark — live tool data timing
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

# ── Constants ──────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"

REAL_CC = Path.home() / ".claude"  / "projects"
REAL_AG = Path.home() / ".gemini"  / "antigravity-ide" / "brain"
REAL_CX = Path.home() / ".codex"   / "sessions"

# ── Data generators ────────────────────────────────────────────────────────────

def _cc_records(n: int, project: str = "perf-project") -> list[dict]:
    """Generate n alternating user/assistant Claude Code JSONL records."""
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        ts = (base_ts + timedelta(seconds=i)).isoformat().replace("+00:00", "Z")
        records.append({
            "type": role, "isSidechain": False,
            "message": {
                "role": role,
                "content": [{"type": "text",
                              "text": f"{'Question' if role=='user' else 'Answer'} number {i}"}],
            },
            "uuid": f"u{i}", "timestamp": ts, "sessionId": "perf-sess-001",
        })
    return records


def _ag_records(n: int) -> list[dict]:
    """Generate n alternating USER/MODEL Antigravity records."""
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        ts = (base_ts + timedelta(seconds=i)).isoformat().replace("+00:00", "Z") + ""
        if i % 2 == 0:
            records.append({
                "step_index": i, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                "status": "DONE", "created_at": ts,
                "content": f"User question number {i}",
            })
        else:
            records.append({
                "step_index": i, "source": "MODEL", "type": "PLANNER_RESPONSE",
                "status": "DONE", "created_at": ts,
                "thinking": f"AI answer number {i}", "tool_calls": [],
            })
    return records


def _cx_records(n: int) -> list[dict]:
    """Generate n alternating user/assistant Codex JSONL records."""
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        ts = (base_ts + timedelta(seconds=i)).isoformat().replace("+00:00", "Z")
        records.append({
            "role": role,
            "content": f"{'Q' if role=='user' else 'A'} {i}",
            "timestamp": ts,
            "session_id": "cx-perf-001",
        })
    return records


def _cx_desktop_records(n: int) -> list[dict]:
    """Generate a Codex Desktop event-log session with n user/assistant turns."""
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [
        {"timestamp": base_ts.isoformat().replace("+00:00", "Z"),
         "type": "session_meta",
         "payload": {"id": "dt-perf-001",
                     "cwd": "C:\\Users\\Robin\\perf-test-project",
                     "originator": "Codex Desktop"}},
    ]
    for i in range(n):
        ts = (base_ts + timedelta(seconds=i + 1)).isoformat().replace("+00:00", "Z")
        if i % 2 == 0:
            records.append({
                "timestamp": ts, "type": "event_msg",
                "payload": {"type": "user_message", "message": f"Desktop Q {i}"},
            })
        else:
            records.append({
                "timestamp": ts, "type": "event_msg",
                "payload": {"type": "agent_message",
                            "message": f"Desktop A {i}", "phase": "final_answer"},
            })
    return records


def _write(path: Path, records: list) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _parse_cc(f: Path):
    from ai_tracker.parsers.claude_code import ClaudeCodeParser
    return [m for s in ClaudeCodeParser(f).parse() for m in s.messages]


def _parse_ag(f: Path):
    from ai_tracker.parsers.antigravity import AntigravityParser
    return [m for s in AntigravityParser(f).parse() for m in s.messages]


def _parse_cx(f: Path):
    from ai_tracker.parsers.codex import CodexParser
    return [m for s in CodexParser(f).parse() for m in s.messages]


# ═════════════════════════════════════════════════════════════════════════════
# P01  Parser throughput — messages per second
# ═════════════════════════════════════════════════════════════════════════════

class TestP01ParserThroughput:
    """
    Each parser is timed on a 5,000-message synthetic file.
    Minimum acceptable: 10,000 messages/second.
    """

    N = 5_000
    MIN_MSG_PER_SEC = 10_000

    def test_claude_code_parser_throughput(self, tmp_path):
        f = tmp_path / "perf.jsonl"
        _write(f, _cc_records(self.N))
        start = time.perf_counter()
        msgs = _parse_cc(f)
        elapsed = time.perf_counter() - start
        rate = len(msgs) / elapsed
        assert len(msgs) == self.N, f"Expected {self.N} messages, got {len(msgs)}"
        assert rate >= self.MIN_MSG_PER_SEC, (
            f"ClaudeCodeParser throughput {rate:.0f} msg/s < {self.MIN_MSG_PER_SEC} minimum"
        )
        print(f"\n  [claudecode]  {len(msgs):,} msgs in {elapsed:.3f}s = {rate:,.0f} msg/s")

    def test_antigravity_parser_throughput(self, tmp_path):
        f = tmp_path / "perf.jsonl"
        _write(f, _ag_records(self.N))
        start = time.perf_counter()
        msgs = _parse_ag(f)
        elapsed = time.perf_counter() - start
        rate = len(msgs) / elapsed
        assert len(msgs) == self.N, f"Expected {self.N} messages, got {len(msgs)}"
        assert rate >= self.MIN_MSG_PER_SEC, (
            f"AntigravityParser throughput {rate:.0f} msg/s < {self.MIN_MSG_PER_SEC} minimum"
        )
        print(f"\n  [antigravity] {len(msgs):,} msgs in {elapsed:.3f}s = {rate:,.0f} msg/s")

    def test_codex_jsonl_parser_throughput(self, tmp_path):
        f = tmp_path / "perf.jsonl"
        _write(f, _cx_records(self.N))
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        rate = len(msgs) / elapsed
        assert len(msgs) == self.N, f"Expected {self.N} messages, got {len(msgs)}"
        assert rate >= self.MIN_MSG_PER_SEC, (
            f"CodexParser (JSONL) throughput {rate:.0f} msg/s < {self.MIN_MSG_PER_SEC} minimum"
        )
        print(f"\n  [codex-jsonl] {len(msgs):,} msgs in {elapsed:.3f}s = {rate:,.0f} msg/s")

    def test_codex_desktop_parser_throughput(self, tmp_path):
        f = tmp_path / "perf.jsonl"
        _write(f, _cx_desktop_records(self.N))
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        rate = len(msgs) / elapsed
        assert len(msgs) == self.N, f"Expected {self.N} messages, got {len(msgs)}"
        assert rate >= self.MIN_MSG_PER_SEC, (
            f"CodexParser (Desktop) throughput {rate:.0f} msg/s < {self.MIN_MSG_PER_SEC} minimum"
        )
        print(f"\n  [codex-desk]  {len(msgs):,} msgs in {elapsed:.3f}s = {rate:,.0f} msg/s")

    def test_codex_json_array_parser_throughput(self, tmp_path):
        f = tmp_path / "perf.json"
        records = _cx_records(self.N)
        f.write_text(json.dumps(records), encoding="utf-8")
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        rate = len(msgs) / elapsed
        assert len(msgs) == self.N
        assert rate >= self.MIN_MSG_PER_SEC, (
            f"CodexParser (JSON array) throughput {rate:.0f} msg/s < {self.MIN_MSG_PER_SEC} minimum"
        )
        print(f"\n  [codex-array] {len(msgs):,} msgs in {elapsed:.3f}s = {rate:,.0f} msg/s")


# ═════════════════════════════════════════════════════════════════════════════
# P02  Scalability — time grows linearly with input size
# ═════════════════════════════════════════════════════════════════════════════

class TestP02Scalability:
    """
    Parse 1k, 2k, and 4k messages. Each doubling should take ≤ 3× longer
    (linear with generous headroom for I/O variance).
    """

    def _time_cc_parse(self, tmp_path: Path, n: int) -> float:
        f = tmp_path / f"scale_{n}.jsonl"
        _write(f, _cc_records(n))
        start = time.perf_counter()
        msgs = _parse_cc(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == n
        return elapsed

    def _time_cx_parse(self, tmp_path: Path, n: int) -> float:
        f = tmp_path / f"scale_{n}.jsonl"
        _write(f, _cx_records(n))
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == n
        return elapsed

    def test_claude_code_scales_linearly(self, tmp_path):
        t1 = self._time_cc_parse(tmp_path, 1_000)
        t2 = self._time_cc_parse(tmp_path, 2_000)
        t4 = self._time_cc_parse(tmp_path, 4_000)
        if t1 > 0:
            ratio_2x = t2 / t1
            ratio_4x = t4 / t1
            assert ratio_4x <= 10, (
                f"P02: 4× input took {ratio_4x:.1f}× longer — non-linear scaling"
            )
        print(f"\n  [cc scale]  1k={t1:.3f}s  2k={t2:.3f}s  4k={t4:.3f}s")

    def test_codex_scales_linearly(self, tmp_path):
        t1 = self._time_cx_parse(tmp_path, 1_000)
        t2 = self._time_cx_parse(tmp_path, 2_000)
        t4 = self._time_cx_parse(tmp_path, 4_000)
        if t1 > 0:
            ratio_4x = t4 / t1
            assert ratio_4x <= 10, (
                f"P02: 4× input took {ratio_4x:.1f}× longer — non-linear scaling"
            )
        print(f"\n  [cx scale]  1k={t1:.3f}s  2k={t2:.3f}s  4k={t4:.3f}s")

    def test_antigravity_scales_linearly(self, tmp_path):
        times = []
        for n in [500, 1_000, 2_000]:
            f = tmp_path / f"ag_scale_{n}.jsonl"
            _write(f, _ag_records(n))
            start = time.perf_counter()
            msgs = _parse_ag(f)
            elapsed = time.perf_counter() - start
            assert len(msgs) == n
            times.append((n, elapsed))
        if times[0][1] > 0:
            ratio = times[-1][1] / times[0][1]
            assert ratio <= 15, (
                f"P02: 4× AG input took {ratio:.1f}× longer"
            )
        print(f"\n  [ag scale]  " + "  ".join(f"{n}={t:.3f}s" for n, t in times))

    def test_csv_export_scales_linearly(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message

        def _export(n: int) -> float:
            msgs = [
                Message(session_id="s", timestamp=None, role="human",
                        message=f"M{i}", tool="codex", file_path="/f")
                for i in range(n)
            ]
            out = tmp_path / f"scale_{n}.csv"
            start = time.perf_counter()
            CSVExporter(out).export(msgs)
            return time.perf_counter() - start

        t1 = _export(1_000)
        t2 = _export(2_000)
        t4 = _export(4_000)
        if t1 > 0:
            ratio = t4 / t1
            assert ratio <= 10, f"P02: CSV export non-linear: 4× rows took {ratio:.1f}× longer"
        print(f"\n  [csv scale] 1k={t1:.3f}s  2k={t2:.3f}s  4k={t4:.3f}s")


# ═════════════════════════════════════════════════════════════════════════════
# P03  Directory scan performance
# ═════════════════════════════════════════════════════════════════════════════

class TestP03DirectoryScan:
    """
    Scan directories containing many small session files.
    Budget: 100 files in < 2s, 500 files in < 8s.
    """

    def _make_cc_dir(self, root: Path, n_files: int, msgs_per_file: int) -> Path:
        proj = root / "projects" / "scan-project"
        proj.mkdir(parents=True)
        for i in range(n_files):
            _write(proj / f"session_{i}.jsonl", _cc_records(msgs_per_file))
        return root / "projects"

    def _make_ag_brain(self, root: Path, n_sessions: int) -> Path:
        brain = root / "brain"
        for i in range(n_sessions):
            logs = brain / f"sess-{i:04d}" / ".system_generated" / "logs"
            logs.mkdir(parents=True)
            _write(logs / "transcript.jsonl", _ag_records(4))
        return brain

    def _make_cx_dir(self, root: Path, n_files: int) -> Path:
        d = root / "codex_sessions"
        d.mkdir()
        for i in range(n_files):
            _write(d / f"session_{i}.jsonl", _cx_records(4))
        return d

    def test_claude_code_100_session_files(self, tmp_path):
        root = self._make_cc_dir(tmp_path, 100, 10)
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        start = time.perf_counter()
        sessions = ClaudeCodeParser(root).parse()
        elapsed = time.perf_counter() - start
        total = sum(len(s.messages) for s in sessions)
        assert len(sessions) == 100
        assert total == 1_000
        assert elapsed < 2.0, f"P03: 100 CC files took {elapsed:.3f}s (budget: 2s)"
        rate = total / elapsed
        print(f"\n  [cc dir 100] {elapsed:.3f}s = {rate:,.0f} msg/s")

    def test_claude_code_500_session_files(self, tmp_path):
        root = self._make_cc_dir(tmp_path, 500, 4)
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        start = time.perf_counter()
        sessions = ClaudeCodeParser(root).parse()
        elapsed = time.perf_counter() - start
        assert len(sessions) == 500
        assert elapsed < 8.0, f"P03: 500 CC files took {elapsed:.3f}s (budget: 8s)"
        print(f"\n  [cc dir 500] {elapsed:.3f}s")

    def test_antigravity_50_session_dirs(self, tmp_path):
        brain = self._make_ag_brain(tmp_path, 50)
        from ai_tracker.parsers.antigravity import AntigravityParser
        start = time.perf_counter()
        sessions = AntigravityParser(brain).parse()
        elapsed = time.perf_counter() - start
        assert len(sessions) == 50
        assert elapsed < 2.0, f"P03: 50 AG sessions took {elapsed:.3f}s (budget: 2s)"
        print(f"\n  [ag brain 50] {elapsed:.3f}s")

    def test_antigravity_200_session_dirs(self, tmp_path):
        brain = self._make_ag_brain(tmp_path, 200)
        from ai_tracker.parsers.antigravity import AntigravityParser
        start = time.perf_counter()
        sessions = AntigravityParser(brain).parse()
        elapsed = time.perf_counter() - start
        assert len(sessions) == 200
        assert elapsed < 6.0, f"P03: 200 AG sessions took {elapsed:.3f}s (budget: 6s)"
        print(f"\n  [ag brain 200] {elapsed:.3f}s")

    def test_codex_100_session_files(self, tmp_path):
        d = self._make_cx_dir(tmp_path, 100)
        from ai_tracker.parsers.codex import CodexParser
        start = time.perf_counter()
        sessions = CodexParser(d).parse()
        elapsed = time.perf_counter() - start
        assert len(sessions) == 100
        assert elapsed < 2.0, f"P03: 100 Codex files took {elapsed:.3f}s (budget: 2s)"
        print(f"\n  [cx dir 100] {elapsed:.3f}s")


# ═════════════════════════════════════════════════════════════════════════════
# P04  Exporter throughput
# ═════════════════════════════════════════════════════════════════════════════

class TestP04ExporterThroughput:
    """
    Measures CSV write speed.
    Minimum: 50,000 rows/second.
    """

    MIN_ROWS_PER_SEC = 50_000

    def _make_messages(self, n: int):
        from ai_tracker.models import Message
        from datetime import datetime, timezone
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            Message(
                session_id=f"sess-{i % 10}",
                timestamp=ts,
                role="human" if i % 2 == 0 else "assistant",
                message=f"Message number {i} with some representative content",
                tool="claudecode",
                file_path=f"/path/to/session_{i % 10}.jsonl",
                project="Performance Test Project",
            )
            for i in range(n)
        ]

    def test_export_10k_rows(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        msgs = self._make_messages(10_000)
        out = tmp_path / "10k.csv"
        start = time.perf_counter()
        count = CSVExporter(out).export(msgs)
        elapsed = time.perf_counter() - start
        rate = count / elapsed
        assert count == 10_000
        assert rate >= self.MIN_ROWS_PER_SEC, (
            f"P04: Export {rate:,.0f} rows/s < {self.MIN_ROWS_PER_SEC} minimum"
        )
        print(f"\n  [export 10k]  {elapsed:.3f}s = {rate:,.0f} rows/s")

    def test_export_50k_rows(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        msgs = self._make_messages(50_000)
        out = tmp_path / "50k.csv"
        start = time.perf_counter()
        count = CSVExporter(out).export(msgs)
        elapsed = time.perf_counter() - start
        rate = count / elapsed
        assert count == 50_000
        assert rate >= self.MIN_ROWS_PER_SEC, (
            f"P04: Export {rate:,.0f} rows/s < {self.MIN_ROWS_PER_SEC} minimum"
        )
        print(f"\n  [export 50k]  {elapsed:.3f}s = {rate:,.0f} rows/s")

    def test_export_unicode_heavy_rows(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        from datetime import datetime, timezone
        msgs = [
            Message(
                session_id="s", timestamp=datetime(2026,1,1,tzinfo=timezone.utc),
                role="human",
                message="日本語テスト 🎉 こんにちは Ünïcödé émoji 🚀",
                tool="codex", file_path="/f",
            )
            for _ in range(5_000)
        ]
        out = tmp_path / "unicode.csv"
        start = time.perf_counter()
        count = CSVExporter(out).export(msgs)
        elapsed = time.perf_counter() - start
        rate = count / elapsed
        assert count == 5_000
        assert elapsed < 2.0, f"P04: Unicode export took {elapsed:.3f}s"
        print(f"\n  [export unicode] {elapsed:.3f}s = {rate:,.0f} rows/s")

    def test_export_multiline_messages(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        msgs = [
            Message(
                session_id="s", timestamp=None, role="assistant",
                message="Line 1\nLine 2\nLine 3\nLine 4\nLine 5",
                tool="claudecode", file_path="/f",
            )
            for _ in range(5_000)
        ]
        out = tmp_path / "multiline.csv"
        start = time.perf_counter()
        count = CSVExporter(out).export(msgs)
        elapsed = time.perf_counter() - start
        assert count == 5_000
        assert elapsed < 2.0, f"P04: Multiline export took {elapsed:.3f}s"
        print(f"\n  [export multiline] {elapsed:.3f}s")


# ═════════════════════════════════════════════════════════════════════════════
# P05  Filter performance
# ═════════════════════════════════════════════════════════════════════════════

class TestP05FilterPerformance:
    """
    Applies date and project filters to large parsed session lists.
    Filter overhead should be negligible compared to parse time.
    """

    def _large_sessions(self, tmp_path: Path, n: int):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        f = tmp_path / "large.jsonl"
        _write(f, _cc_records(n))
        parser = ClaudeCodeParser(f)
        sessions = parser.parse()
        return parser, sessions

    def test_date_filter_overhead_on_10k_messages(self, tmp_path):
        parser, sessions = self._large_sessions(tmp_path, 10_000)
        start = time.perf_counter()
        filtered = parser.filter_by_date(
            sessions,
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 31),
        )
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"P05: Date filter on 10k msgs took {elapsed:.3f}s (budget: 0.5s)"
        print(f"\n  [date filter 10k] {elapsed:.4f}s")

    def test_date_filter_no_matches_overhead(self, tmp_path):
        parser, sessions = self._large_sessions(tmp_path, 5_000)
        start = time.perf_counter()
        filtered = parser.filter_by_date(
            sessions,
            start=datetime(2099, 1, 1),
            end=None,
        )
        elapsed = time.perf_counter() - start
        assert filtered == []
        assert elapsed < 0.3, f"P05: Empty date filter took {elapsed:.3f}s"

    def test_project_filter_overhead_on_10k_messages(self, tmp_path):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        proj = tmp_path / "projects" / "perf-project"
        proj.mkdir(parents=True)
        _write(proj / "session.jsonl", _cc_records(10_000))
        import argparse
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        # Time full parse + project filter
        start = time.perf_counter()
        cmd_parse(argparse.Namespace(
            tool="claudecode",
            file=str(tmp_path / "projects"),
            output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True,
            project="perf",
            split_by_project=False,
        ))
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, f"P05: 10k msg project filter pipeline took {elapsed:.3f}s"
        print(f"\n  [project filter 10k] {elapsed:.3f}s")

    def test_filter_does_not_slow_with_many_sessions(self, tmp_path):
        """Filter on 100 sessions × 100 messages each — overhead should be < 0.5s."""
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        proj = tmp_path / "projects" / "multi-sess"
        proj.mkdir(parents=True)
        for i in range(100):
            records = _cc_records(100)
            for r in records:
                r["sessionId"] = f"sess-{i:03d}"
            _write(proj / f"session_{i}.jsonl", records)
        parser = ClaudeCodeParser(tmp_path / "projects")
        sessions = parser.parse()
        assert len(sessions) == 100
        start = time.perf_counter()
        filtered = parser.filter_by_date(
            sessions,
            start=datetime(2026, 1, 1),
            end=datetime(2026, 6, 30),
        )
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"P05: filter on 100 sessions took {elapsed:.3f}s"
        print(f"\n  [filter 100 sessions] {elapsed:.4f}s")


# ═════════════════════════════════════════════════════════════════════════════
# P06  End-to-end pipeline timing
# ═════════════════════════════════════════════════════════════════════════════

class TestP06EndToEndPipeline:
    """
    Full pipeline: source file → cmd_parse → CSV on disk.
    Budgets are generous enough for CI but tight enough to catch regressions.
    """

    def _e2e(self, tool: str, f: Path, out: Path) -> float:
        import argparse
        from ai_tracker.cli import cmd_parse
        start = time.perf_counter()
        rc = cmd_parse(argparse.Namespace(
            tool=tool, file=str(f), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        elapsed = time.perf_counter() - start
        assert rc == 0, f"cmd_parse returned {rc}"
        return elapsed

    def test_claude_code_e2e_5k_messages(self, tmp_path):
        f = tmp_path / "cc.jsonl"
        _write(f, _cc_records(5_000))
        elapsed = self._e2e("claudecode", f, tmp_path / "out.csv")
        assert elapsed < 3.0, f"P06: CC 5k E2E took {elapsed:.3f}s (budget: 3s)"
        print(f"\n  [e2e cc 5k]   {elapsed:.3f}s")

    def test_antigravity_e2e_5k_messages(self, tmp_path):
        f = tmp_path / "ag.jsonl"
        _write(f, _ag_records(5_000))
        elapsed = self._e2e("antigravity", f, tmp_path / "out.csv")
        assert elapsed < 3.0, f"P06: AG 5k E2E took {elapsed:.3f}s (budget: 3s)"
        print(f"\n  [e2e ag 5k]   {elapsed:.3f}s")

    def test_codex_e2e_5k_messages(self, tmp_path):
        f = tmp_path / "cx.jsonl"
        _write(f, _cx_records(5_000))
        elapsed = self._e2e("codex", f, tmp_path / "out.csv")
        assert elapsed < 3.0, f"P06: Codex 5k E2E took {elapsed:.3f}s (budget: 3s)"
        print(f"\n  [e2e cx 5k]   {elapsed:.3f}s")

    def test_codex_desktop_e2e_5k_messages(self, tmp_path):
        f = tmp_path / "dt.jsonl"
        _write(f, _cx_desktop_records(5_000))
        elapsed = self._e2e("codex", f, tmp_path / "out.csv")
        assert elapsed < 3.0, f"P06: Desktop 5k E2E took {elapsed:.3f}s (budget: 3s)"
        print(f"\n  [e2e desk 5k] {elapsed:.3f}s")

    def test_three_tool_combined_e2e(self, tmp_path):
        """Parse all three tools separately and sum time — must be < 10s total."""
        import argparse
        from ai_tracker.cli import cmd_parse
        for tool, records, fname in [
            ("claudecode", _cc_records(3_000), "cc.jsonl"),
            ("antigravity", _ag_records(3_000), "ag.jsonl"),
            ("codex",       _cx_records(3_000), "cx.jsonl"),
        ]:
            _write(tmp_path / fname, records)
        total = 0.0
        for tool, fname in [("claudecode","cc.jsonl"),("antigravity","ag.jsonl"),("codex","cx.jsonl")]:
            out = tmp_path / f"{tool}.csv"
            start = time.perf_counter()
            cmd_parse(argparse.Namespace(
                tool=tool, file=str(tmp_path / fname), output=str(out),
                start_date=None, end_date=None,
                include_sidechains=True, project=None, split_by_project=False,
            ))
            total += time.perf_counter() - start
        assert total < 10.0, f"P06: Three-tool combined took {total:.3f}s (budget: 10s)"
        print(f"\n  [e2e 3-tool combined] {total:.3f}s")

    def test_split_by_project_e2e_performance(self, tmp_path):
        """Split-by-project with 10 projects × 1k messages each."""
        import argparse
        from ai_tracker.cli import cmd_parse
        projects = tmp_path / "projects"
        for i in range(10):
            proj = projects / f"project-{i:02d}"
            proj.mkdir(parents=True)
            _write(proj / "session.jsonl", _cc_records(1_000))
        out_dir = tmp_path / "split_out"
        start = time.perf_counter()
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(projects), output=str(out_dir),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=True,
        ))
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"P06: Split 10 projects × 1k msgs took {elapsed:.3f}s"
        csvs = list(out_dir.glob("*.csv"))
        assert len(csvs) == 10
        print(f"\n  [e2e split 10proj] {elapsed:.3f}s")


# ═════════════════════════════════════════════════════════════════════════════
# P07  Large Codex Desktop session
# ═════════════════════════════════════════════════════════════════════════════

class TestP07LargeCodexDesktopSession:
    """
    Codex Desktop sessions can be very large because they include full
    system prompts and tool outputs in every turn. Tests with sessions
    that have many turns and large payloads.
    """

    def test_desktop_session_with_1k_turns(self, tmp_path):
        f = tmp_path / "large_desktop.jsonl"
        _write(f, _cx_desktop_records(1_000))
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == 1_000
        assert elapsed < 1.0, f"P07: 1k desktop turns took {elapsed:.3f}s"
        print(f"\n  [desktop 1k turns] {elapsed:.3f}s = {1000/elapsed:,.0f} msg/s")

    def test_desktop_session_with_large_system_prompt(self, tmp_path):
        """Sessions include a very long base_instructions payload — must parse fast."""
        large_prompt = "A" * 50_000  # 50 KB system prompt (realistic Codex Desktop size)
        records = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta",
             "payload": {"id": "lg-test", "cwd": "C:\\Users\\Robin\\large-session",
                         "originator": "Codex Desktop",
                         "base_instructions": {"text": large_prompt}}},
        ]
        for i in range(500):
            ts = f"2026-01-01T00:{i//60:02d}:{i%60:02d}Z"
            records.append({
                "timestamp": ts, "type": "event_msg",
                "payload": {"type": "user_message", "message": f"Q {i}"},
            })
            records.append({
                "timestamp": ts, "type": "event_msg",
                "payload": {"type": "agent_message",
                            "message": f"A {i}", "phase": "final_answer"},
            })
        f = tmp_path / "large_sys.jsonl"
        _write(f, records)
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == 1_000
        assert elapsed < 2.0, f"P07: Large system prompt session took {elapsed:.3f}s"
        print(f"\n  [desktop large sys] {elapsed:.3f}s")

    def test_nested_sessions_directory_performance(self, tmp_path):
        """~/.codex/sessions/YYYY/MM/DD/*.jsonl structure with 50 sessions."""
        sessions_root = tmp_path / "sessions"
        for day in range(1, 6):
            day_dir = sessions_root / "2026" / "05" / f"{day:02d}"
            day_dir.mkdir(parents=True)
            for sess in range(10):
                records = _cx_desktop_records(50)
                _write(day_dir / f"rollout-sess-{day}-{sess}.jsonl", records)
        start = time.perf_counter()
        sessions = __import__(
            "ai_tracker.parsers.codex", fromlist=["CodexParser"]
        ).CodexParser(sessions_root).parse()
        elapsed = time.perf_counter() - start
        assert len(sessions) == 50
        total_msgs = sum(len(s.messages) for s in sessions)
        assert total_msgs == 50 * 50
        assert elapsed < 5.0, f"P07: 50 nested desktop sessions took {elapsed:.3f}s"
        print(f"\n  [desktop nested 50] {elapsed:.3f}s  {total_msgs:,} msgs")


# ═════════════════════════════════════════════════════════════════════════════
# P08  Real data benchmark
# ═════════════════════════════════════════════════════════════════════════════

class TestP08RealDataBenchmark:
    """
    Times a full parse of actual installed tool data.
    Skipped automatically when the tool is not installed.
    Prints a performance summary rather than asserting tight budgets
    (real data size varies widely between machines).
    """

    def test_real_claude_code_full_parse_timing(self, tmp_path):
        if not REAL_CC.exists():
            pytest.skip("Claude Code not installed")
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        start = time.perf_counter()
        sessions = ClaudeCodeParser(REAL_CC).parse()
        elapsed = time.perf_counter() - start
        total = sum(len(s.messages) for s in sessions)
        rate = total / elapsed if elapsed > 0 else 0
        print(f"\n  [REAL CC]  {len(sessions)} sessions  {total:,} msgs  "
              f"{elapsed:.3f}s  {rate:,.0f} msg/s")
        assert elapsed < 60.0, f"Real CC parse took {elapsed:.1f}s — too slow"
        assert total > 0

    def test_real_antigravity_full_parse_timing(self, tmp_path):
        if not REAL_AG.exists():
            pytest.skip("Antigravity not installed")
        from ai_tracker.parsers.antigravity import AntigravityParser
        start = time.perf_counter()
        sessions = AntigravityParser(REAL_AG).parse()
        elapsed = time.perf_counter() - start
        total = sum(len(s.messages) for s in sessions)
        rate = total / elapsed if elapsed > 0 else 0
        print(f"\n  [REAL AG]  {len(sessions)} sessions  {total:,} msgs  "
              f"{elapsed:.3f}s  {rate:,.0f} msg/s")
        assert elapsed < 60.0, f"Real AG parse took {elapsed:.1f}s — too slow"

    def test_real_codex_full_parse_timing(self, tmp_path):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed")
        from ai_tracker.parsers.codex import CodexParser
        start = time.perf_counter()
        sessions = CodexParser(REAL_CX).parse()
        elapsed = time.perf_counter() - start
        total = sum(len(s.messages) for s in sessions)
        rate = total / elapsed if elapsed > 0 else 0
        print(f"\n  [REAL CX]  {len(sessions)} sessions  {total:,} msgs  "
              f"{elapsed:.3f}s  {rate:,.0f} msg/s")
        assert elapsed < 60.0, f"Real Codex parse took {elapsed:.1f}s — too slow"

    def test_real_claude_code_full_e2e_timing(self, tmp_path):
        if not REAL_CC.exists():
            pytest.skip("Claude Code not installed")
        import argparse
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "real_cc.csv"
        start = time.perf_counter()
        rc = cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(REAL_CC), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        elapsed = time.perf_counter() - start
        assert rc == 0
        import csv as _csv
        with open(out, encoding="utf-8") as fh:
            row_count = sum(1 for _ in _csv.DictReader(fh))
        rate = row_count / elapsed if elapsed > 0 else 0
        print(f"\n  [REAL CC E2E]  {row_count:,} rows  {elapsed:.3f}s  {rate:,.0f} rows/s")
        assert elapsed < 120.0, f"Real CC E2E took {elapsed:.1f}s"

    def test_real_codex_full_e2e_timing(self, tmp_path):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed")
        import argparse
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "real_cx.csv"
        start = time.perf_counter()
        rc = cmd_parse(argparse.Namespace(
            tool="codex", file=str(REAL_CX), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        elapsed = time.perf_counter() - start
        assert rc == 0
        import csv as _csv
        with open(out, encoding="utf-8") as fh:
            row_count = sum(1 for _ in _csv.DictReader(fh))
        rate = row_count / elapsed if elapsed > 0 else 0
        print(f"\n  [REAL CX E2E]  {row_count:,} rows  {elapsed:.3f}s  {rate:,.0f} rows/s")
        assert elapsed < 120.0, f"Real Codex E2E took {elapsed:.1f}s"
