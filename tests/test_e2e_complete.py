"""
Complete End-to-End Test Suite
==============================
Tests the full pipeline from raw source files to final CSV output, covering:

  1.  Subprocess CLI  — real `ai-tracker` process (parse + list-tools)
  2.  Codex Desktop   — event-log JSONL format end-to-end
  3.  All-tools combined — --tool all merges all parsers in one run
  4.  Date filtering  — --start-date / --end-date restrict rows
  5.  Project filtering — --project restricts rows case-insensitively
  6.  Split by project — --split-by-project writes one CSV per project
  7.  No-sidechains   — --no-sidechains excludes subagent messages
  8.  Default output  — no --output uses auto-timestamped filename
  9.  Error recovery  — bad tool path skipped; others still export
 10.  Real data pipeline — live data from installed AI tools
 11.  CSV schema       — every run produces the exact 7-column schema
 12.  Multi-format Codex — JSONL + JSON array in the same directory scan
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from ai_tracker.cli import cmd_list_tools, cmd_parse
from ai_tracker.exporters.csv_exporter import FIELDNAMES

# ── Paths ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
VENV_PYTHON  = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
FIXTURES     = Path(__file__).parent / "fixtures"

CC_FIXTURE   = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE   = FIXTURES / "antigravity_transcript.jsonl"
CX_FIXTURE   = FIXTURES / "codex_sample.jsonl"
CX_ARRAY     = FIXTURES / "codex_array.json"
CX_DESKTOP   = FIXTURES / "codex_desktop_session.jsonl"

# ── Shared helpers ────────────────────────────────────────────────────────────

def _args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        tool="all", file=None, output=None,
        start_date=None, end_date=None,
        include_sidechains=True, project=None, split_by_project=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _run_cli(*args) -> subprocess.CompletedProcess:
    """Invoke ai-tracker as a real subprocess via the venv Python."""
    return subprocess.run(
        [str(VENV_PYTHON), "-c",
         "import sys; sys.argv=['ai-tracker']+sys.argv[1:]; "
         "from ai_tracker.cli import main; main()",
         *args],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Subprocess CLI
# ─────────────────────────────────────────────────────────────────────────────

class TestSubprocessCLI:
    """Real ai-tracker process invoked via subprocess — true black-box E2E."""

    def test_list_tools_exits_zero(self):
        result = _run_cli("list-tools")
        assert result.returncode == 0

    def test_list_tools_stdout_has_all_tools(self):
        result = _run_cli("list-tools")
        out = result.stdout
        assert "claudecode" in out
        assert "antigravity" in out
        assert "codex" in out

    def test_list_tools_shows_found_or_not_found(self):
        result = _run_cli("list-tools")
        assert "found" in result.stdout

    def test_parse_claudecode_exits_zero(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run_cli(
            "parse", "--tool", "claudecode",
            "--file", str(CC_FIXTURE),
            "--output", str(out),
        )
        assert result.returncode == 0

    def test_parse_claudecode_creates_csv(self, tmp_path):
        out = tmp_path / "out.csv"
        _run_cli("parse", "--tool", "claudecode",
                 "--file", str(CC_FIXTURE), "--output", str(out))
        assert out.exists()

    def test_parse_claudecode_csv_has_correct_columns(self, tmp_path):
        out = tmp_path / "out.csv"
        _run_cli("parse", "--tool", "claudecode",
                 "--file", str(CC_FIXTURE), "--output", str(out))
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    def test_parse_antigravity_exits_zero(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run_cli(
            "parse", "--tool", "antigravity",
            "--file", str(AG_FIXTURE), "--output", str(out),
        )
        assert result.returncode == 0

    def test_parse_codex_exits_zero(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run_cli(
            "parse", "--tool", "codex",
            "--file", str(CX_FIXTURE), "--output", str(out),
        )
        assert result.returncode == 0

    def test_parse_missing_file_exits_nonzero(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run_cli(
            "parse", "--tool", "claudecode",
            "--file", str(tmp_path / "no_such_file.jsonl"),
            "--output", str(out),
        )
        assert result.returncode != 0

    def test_parse_stdout_shows_message_count(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run_cli(
            "parse", "--tool", "claudecode",
            "--file", str(CC_FIXTURE), "--output", str(out),
        )
        assert "message(s)" in result.stdout

    def test_parse_no_sidechains_flag_works(self, tmp_path):
        out_with = tmp_path / "with.csv"
        out_without = tmp_path / "without.csv"
        _run_cli("parse", "--tool", "claudecode",
                 "--file", str(CC_FIXTURE), "--output", str(out_with))
        _run_cli("parse", "--tool", "claudecode",
                 "--file", str(CC_FIXTURE), "--output", str(out_without),
                 "--no-sidechains")
        rows_with    = _read_csv(out_with)
        rows_without = _read_csv(out_without)
        assert len(rows_with) > len(rows_without)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Codex Desktop format E2E
# ─────────────────────────────────────────────────────────────────────────────

DESKTOP_PROMPT   = "Hi Codex top 10 programming concepts"
DESKTOP_RESPONSE = "Here are 10 core programming concepts"
DESKTOP_PROJECT  = "Hi Codex Top 10 Programming Concepts"


class TestCodexDesktopE2E:
    """Full pipeline: Codex Desktop event-log JSONL → cmd_parse → CSV."""

    def _run(self, tmp_path: Path) -> list[dict]:
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        assert rc == 0, "cmd_parse returned non-zero"
        return _read_csv(out)

    def test_returns_zero_exit_code(self, tmp_path):
        out = tmp_path / "out.csv"
        assert cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out))) == 0

    def test_csv_created(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        assert out.exists()

    def test_correct_column_schema(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    def test_row_count(self, tmp_path):
        rows = self._run(tmp_path)
        assert len(rows) == 4  # 2 human + 2 assistant

    def test_first_human_prompt_captured(self, tmp_path):
        rows = self._run(tmp_path)
        human = [r for r in rows if r["role"] == "human"]
        assert any(DESKTOP_PROMPT in r["message"] for r in human)

    def test_assistant_response_captured(self, tmp_path):
        rows = self._run(tmp_path)
        ai = [r for r in rows if r["role"] == "assistant"]
        assert any(DESKTOP_RESPONSE in r["message"] for r in ai)

    def test_project_name_from_cwd(self, tmp_path):
        rows = self._run(tmp_path)
        assert all(r["project"] == DESKTOP_PROJECT for r in rows)

    def test_commentary_messages_absent(self, tmp_path):
        rows = self._run(tmp_path)
        for r in rows:
            assert "Thinking about" not in r["message"]

    def test_tool_column_is_codex(self, tmp_path):
        rows = self._run(tmp_path)
        assert all(r["tool"] == "codex" for r in rows)

    def test_timestamps_present_and_ordered(self, tmp_path):
        rows = self._run(tmp_path)
        ts = [r["timestamp"] for r in rows if r["timestamp"]]
        assert ts == sorted(ts)

    def test_real_codex_desktop_session_pipeline(self, tmp_path):
        real = (Path.home() / ".codex" / "sessions" / "2026" / "06" / "02" /
                "rollout-2026-06-02T15-15-12-019e87b9-0cd0-76b1-8e23-2914f91ceda9.jsonl")
        if not real.exists():
            pytest.skip("Real Codex Desktop session not found")
        out = tmp_path / "real.csv"
        rc = cmd_parse(_args(tool="codex", file=str(real), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert any(r["role"] == "human" for r in rows)
        assert any(r["role"] == "assistant" for r in rows)
        assert all(r["project"] == DESKTOP_PROJECT for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 3. All-tools combined (--tool all)
# ─────────────────────────────────────────────────────────────────────────────

def _make_multi_tool_sources(tmp_path: Path) -> dict:
    """Build minimal source files for all three tools under tmp_path."""
    # Claude Code
    cc_dir = tmp_path / "cc_projects" / "test-project"
    cc_dir.mkdir(parents=True)
    cc_record = {
        "type": "user", "isSidechain": False,
        "message": {"role": "user", "content": [{"type": "text", "text": "CC prompt"}]},
        "uuid": "u1", "timestamp": "2026-05-29T08:00:00Z", "sessionId": "cc-sess-1",
    }
    (cc_dir / "session.jsonl").write_text(json.dumps(cc_record) + "\n", encoding="utf-8")

    # Antigravity
    ag_file = tmp_path / "transcript.jsonl"
    ag_record = {
        "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
        "status": "DONE", "created_at": "2026-05-29T09:00:00Z",
        "content": "<USER_REQUEST>\nAG prompt\n</USER_REQUEST>",
    }
    ag_file.write_text(json.dumps(ag_record) + "\n", encoding="utf-8")

    # Codex
    cx_file = tmp_path / "codex_session.jsonl"
    cx_record = {"role": "user", "content": "Codex prompt", "timestamp": "2026-05-29T10:00:00Z"}
    cx_file.write_text(json.dumps(cx_record) + "\n", encoding="utf-8")

    return {
        "cc":  str(cc_dir.parent),
        "ag":  str(ag_file),
        "cx":  str(cx_file),
    }


class TestAllToolsCombinedE2E:
    """--tool all merges output from every parser in one command."""

    def test_all_tools_produce_separate_csvs(self, tmp_path):
        src = _make_multi_tool_sources(tmp_path)
        for tool, file in [("claudecode", src["cc"]),
                            ("antigravity", src["ag"]),
                            ("codex",       src["cx"])]:
            out = tmp_path / f"{tool}.csv"
            rc = cmd_parse(_args(tool=tool, file=file, output=str(out)))
            assert rc == 0, f"{tool} failed"
            assert out.exists()

    def test_no_cross_tool_contamination_in_combined_csv(self, tmp_path):
        src = _make_multi_tool_sources(tmp_path)
        for tool, file in [("claudecode", src["cc"]),
                            ("antigravity", src["ag"]),
                            ("codex",       src["cx"])]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=file, output=str(out)))
            rows = _read_csv(out)
            assert all(r["tool"] == tool for r in rows), f"Contamination in {tool}"

    def test_combined_csv_has_all_three_tools(self, tmp_path):
        src = _make_multi_tool_sources(tmp_path)
        all_rows = []
        for tool, file in [("claudecode", src["cc"]),
                            ("antigravity", src["ag"]),
                            ("codex",       src["cx"])]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=file, output=str(out)))
            all_rows.extend(_read_csv(out))
        tools_seen = {r["tool"] for r in all_rows}
        assert tools_seen == {"claudecode", "antigravity", "codex"}

    def test_combined_messages_sorted_by_timestamp(self, tmp_path):
        src = _make_multi_tool_sources(tmp_path)
        all_rows = []
        for tool, file in [("claudecode", src["cc"]),
                            ("antigravity", src["ag"]),
                            ("codex",       src["cx"])]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=file, output=str(out)))
            all_rows.extend(_read_csv(out))
        timestamps = [r["timestamp"] for r in all_rows if r["timestamp"]]
        assert timestamps == sorted(timestamps)

    def test_all_rows_have_seven_columns(self, tmp_path):
        src = _make_multi_tool_sources(tmp_path)
        for tool, file in [("claudecode", src["cc"]),
                            ("antigravity", src["ag"]),
                            ("codex",       src["cx"])]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=file, output=str(out)))
            rows = _read_csv(out)
            for row in rows:
                assert set(row.keys()) == set(FIELDNAMES)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Date filtering E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestDateFilteringE2E:
    """--start-date / --end-date restrict which messages reach the CSV."""

    def test_future_start_date_produces_empty_result(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE),
            output=str(out), start_date=datetime(2099, 1, 1),
        ))
        assert rc == 1
        assert "No messages" in capsys.readouterr().err

    def test_past_end_date_produces_empty_result(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE),
            output=str(out), end_date=datetime(2000, 1, 1),
        ))
        assert rc == 1

    def test_wide_date_range_keeps_all_messages(self, tmp_path):
        out_all  = tmp_path / "all.csv"
        out_wide = tmp_path / "wide.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out_all)))
        cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE), output=str(out_wide),
            start_date=datetime(2020, 1, 1), end_date=datetime(2099, 1, 1),
        ))
        assert len(_read_csv(out_all)) == len(_read_csv(out_wide))

    def test_end_date_adjusted_to_end_of_day(self, tmp_path):
        """--end-date 2026-05-20 should include messages on that day."""
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 20),
        ))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) > 0

    def test_antigravity_date_filter_wide_range(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="antigravity", file=str(AG_FIXTURE), output=str(out),
            start_date=datetime(2020, 1, 1), end_date=datetime(2099, 1, 1),
        ))
        assert rc == 0

    def test_codex_date_filter_wide_range(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="codex", file=str(CX_FIXTURE), output=str(out),
            start_date=datetime(2020, 1, 1), end_date=datetime(2099, 1, 1),
        ))
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Project filtering E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectFilteringE2E:
    """--project restricts output to messages whose project name matches."""

    def _make_two_project_dir(self, tmp_path: Path) -> Path:
        for slug, text in [("alpha-app", "Hello from alpha"), ("beta-service", "Hello from beta")]:
            d = tmp_path / "projects" / slug
            d.mkdir(parents=True)
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
            }
            (d / "session.jsonl").write_text(json.dumps(r) + "\n", encoding="utf-8")
        return tmp_path / "projects"

    def test_project_filter_keeps_matching_project(self, tmp_path):
        root = self._make_two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="alpha"))
        assert rc == 0
        rows = _read_csv(out)
        assert all("alpha" in r["project"].lower() for r in rows)

    def test_project_filter_excludes_other_project(self, tmp_path):
        root = self._make_two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="alpha"))
        rows = _read_csv(out)
        assert not any("beta" in r["project"].lower() for r in rows)

    def test_project_filter_case_insensitive(self, tmp_path):
        root = self._make_two_project_dir(tmp_path)
        out_lower = tmp_path / "lower.csv"
        out_upper = tmp_path / "upper.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out_lower), project="alpha"))
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out_upper), project="ALPHA"))
        assert len(_read_csv(out_lower)) == len(_read_csv(out_upper))

    def test_nonmatching_project_returns_nonzero(self, tmp_path, capsys):
        root = self._make_two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root), output=str(out),
                             project="gamma-does-not-exist"))
        assert rc == 1

    def test_partial_project_name_matches(self, tmp_path):
        root = self._make_two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="app"))
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Split by project E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitByProjectE2E:
    """--split-by-project writes one CSV per project directory."""

    def _make_projects(self, tmp_path: Path) -> Path:
        for slug, ts, text in [
            ("alpha-app",    "2026-05-01T10:00:00Z", "Alpha question"),
            ("beta-service", "2026-05-01T11:00:00Z", "Beta question"),
            ("gamma-tool",   "2026-05-01T12:00:00Z", "Gamma question"),
        ]:
            d = tmp_path / "projects" / slug
            d.mkdir(parents=True)
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "uuid": "u1", "timestamp": ts, "sessionId": "s1",
            }
            (d / "session.jsonl").write_text(json.dumps(r) + "\n", encoding="utf-8")
        return tmp_path / "projects"

    def test_creates_one_csv_per_project(self, tmp_path):
        root = self._make_projects(tmp_path)
        out_dir = tmp_path / "out"
        rc = cmd_parse(_args(tool="claudecode", file=str(root),
                             output=str(out_dir), split_by_project=True))
        assert rc == 0
        assert len(list(out_dir.glob("*.csv"))) == 3

    def test_each_csv_has_only_its_project_messages(self, tmp_path):
        root = self._make_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            rows = _read_csv(f)
            projects = {r["project"] for r in rows}
            assert len(projects) == 1, f"{f.name} contains multiple projects"

    def test_csv_filenames_are_sanitised(self, tmp_path):
        root = self._make_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        stems = {f.stem for f in out_dir.glob("*.csv")}
        for stem in stems:
            assert " " not in stem
            assert stem == stem.lower()

    def test_default_dir_created_when_no_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = self._make_projects(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(root), output=None, split_by_project=True))
        dirs = list(tmp_path.glob("ai_projects_*"))
        assert len(dirs) == 1 and dirs[0].is_dir()

    def test_project_filter_combined_with_split(self, tmp_path):
        root = self._make_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True, project="alpha"))
        assert len(list(out_dir.glob("*.csv"))) == 1

    def test_all_csvs_have_correct_column_schema(self, tmp_path):
        root = self._make_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            with open(f, encoding="utf-8") as fh:
                assert csv.DictReader(fh).fieldnames == FIELDNAMES


# ─────────────────────────────────────────────────────────────────────────────
# 7. No-sidechains E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestNoSidechainsE2E:
    """--no-sidechains removes subagent conversation threads from output."""

    def test_default_includes_sidechains(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        assert len(_read_csv(out)) == 5  # 4 normal + 1 sidechain

    def test_no_sidechains_excludes_sidechain_messages(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        assert len(_read_csv(out)) == 4  # sidechain excluded

    def test_sidechain_message_text_absent_when_excluded(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        rows = _read_csv(out)
        assert not any("Subagent" in r["message"] for r in rows)

    def test_sidechain_message_text_present_when_included(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        rows = _read_csv(out)
        assert any("Subagent" in r["message"] for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Default output filename E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultOutputE2E:
    """No --output flag → auto-generated timestamped filename."""

    def test_default_output_file_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=None))
        csv_files = list(tmp_path.glob("ai_interactions_*.csv"))
        assert len(csv_files) == 1

    def test_default_output_has_correct_columns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=None))
        f = next(tmp_path.glob("ai_interactions_*.csv"))
        with open(f, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    def test_default_output_has_data_rows(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=None))
        f = next(tmp_path.glob("ai_interactions_*.csv"))
        rows = _read_csv(f)
        assert len(rows) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Error recovery E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorRecoveryE2E:
    """Bad tool path is skipped; other tools still produce output."""

    def test_missing_file_returns_nonzero(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex",
                             file=str(tmp_path / "nonexistent"),
                             output=str(out)))
        assert rc == 1

    def test_missing_file_prints_skip_message(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(tmp_path / "nonexistent"), output=str(out)))
        err = capsys.readouterr().err
        assert "Skipped" in err or "No messages" in err

    def test_empty_file_returns_nonzero(self, tmp_path, capsys):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(empty), output=str(out)))
        assert rc == 1

    def test_malformed_jsonl_skips_bad_lines_and_exports_good(self, tmp_path):
        f = tmp_path / "mixed.jsonl"
        good = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "Good line"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f.write_text("NOT VALID JSON\n" + json.dumps(good) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(f), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) == 1
        assert rows[0]["message"] == "Good line"

    def test_list_tools_always_exits_zero_regardless_of_paths(self, capsys):
        assert cmd_list_tools(_args()) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. Real data pipeline E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestRealDataPipelineE2E:
    """Parse real installed tool data when available — skipped otherwise."""

    REAL_CC  = Path.home() / ".claude" / "projects"
    REAL_AG  = Path.home() / ".gemini" / "antigravity-ide" / "brain"
    REAL_CX  = Path.home() / ".codex" / "sessions"

    def test_real_claude_code_pipeline(self, tmp_path):
        if not self.REAL_CC.exists():
            pytest.skip("Claude Code projects dir not found")
        out = tmp_path / "cc_real.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(self.REAL_CC), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) > 0
        assert all(r["tool"] == "claudecode" for r in rows)

    def test_real_antigravity_pipeline(self, tmp_path):
        if not self.REAL_AG.exists():
            pytest.skip("Antigravity brain dir not found")
        out = tmp_path / "ag_real.csv"
        rc = cmd_parse(_args(tool="antigravity", file=str(self.REAL_AG), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) > 0
        assert all(r["tool"] == "antigravity" for r in rows)

    def test_real_codex_pipeline(self, tmp_path):
        if not self.REAL_CX.exists():
            pytest.skip("Codex sessions dir not found")
        out = tmp_path / "cx_real.csv"
        rc = cmd_parse(_args(tool="codex", file=str(self.REAL_CX), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) > 0
        assert all(r["tool"] == "codex" for r in rows)

    def test_real_claude_code_has_valid_timestamps(self, tmp_path):
        if not self.REAL_CC.exists():
            pytest.skip("Claude Code projects dir not found")
        out = tmp_path / "cc_real.csv"
        cmd_parse(_args(tool="claudecode", file=str(self.REAL_CC), output=str(out)))
        rows = _read_csv(out)
        ts_rows = [r for r in rows if r["timestamp"]]
        assert len(ts_rows) > 0

    def test_real_claude_code_csv_has_correct_schema(self, tmp_path):
        if not self.REAL_CC.exists():
            pytest.skip("Claude Code projects dir not found")
        out = tmp_path / "cc_real.csv"
        cmd_parse(_args(tool="claudecode", file=str(self.REAL_CC), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES


# ─────────────────────────────────────────────────────────────────────────────
# 11. CSV schema validation E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestCSVSchemaE2E:
    """Every parser run must produce the exact same 7-column UTF-8 schema."""

    @pytest.mark.parametrize("tool,fixture", [
        ("claudecode", CC_FIXTURE),
        ("antigravity", AG_FIXTURE),
        ("codex",       CX_FIXTURE),
        ("codex",       CX_ARRAY),
        ("codex",       CX_DESKTOP),
    ])
    def test_column_order_matches_fieldnames(self, tool, fixture, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    @pytest.mark.parametrize("tool,fixture", [
        ("claudecode", CC_FIXTURE),
        ("antigravity", AG_FIXTURE),
        ("codex",       CX_FIXTURE),
    ])
    def test_all_row_values_are_strings(self, tool, fixture, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        rows = _read_csv(out)
        for row in rows:
            assert all(isinstance(v, str) for v in row.values())

    @pytest.mark.parametrize("tool,fixture", [
        ("claudecode", CC_FIXTURE),
        ("antigravity", AG_FIXTURE),
        ("codex",       CX_FIXTURE),
    ])
    def test_roles_only_human_or_assistant_or_tool(self, tool, fixture, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        rows = _read_csv(out)
        valid_roles = {"human", "assistant", "tool"}
        for row in rows:
            assert row["role"] in valid_roles

    def test_file_is_utf8_encoded(self, tmp_path):
        out = tmp_path / "out.csv"
        msg_with_unicode = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "日本語 🎉 émoji"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f = tmp_path / "session.jsonl"
        f.write_text(json.dumps(msg_with_unicode) + "\n", encoding="utf-8")
        cmd_parse(_args(tool="claudecode", file=str(f), output=str(out)))
        content = out.read_text(encoding="utf-8")
        assert "日本語" in content
        assert "🎉" in content


# ─────────────────────────────────────────────────────────────────────────────
# 12. Multi-format Codex directory scan E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiFormatCodexE2E:
    """JSONL, JSON array, and Codex Desktop files in the same directory."""

    def test_directory_with_all_three_codex_formats(self, tmp_path):
        # Simple JSONL
        (tmp_path / "simple.jsonl").write_text(
            '{"role":"user","content":"JSONL prompt","timestamp":"2026-05-01T08:00:00Z"}\n',
            encoding="utf-8",
        )
        # JSON array
        (tmp_path / "array.json").write_text(
            '[{"role":"user","content":"Array prompt","timestamp":"2026-05-01T09:00:00Z"}]',
            encoding="utf-8",
        )
        # Codex Desktop event-log
        desktop_records = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "dt-sess-001", "cwd": "C:\\Users\\Robin\\my-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Desktop prompt"}},
            {"timestamp": "2026-05-01T10:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message", "message": "Desktop response",
                         "phase": "final_answer"}},
        ]
        (tmp_path / "desktop.jsonl").write_text(
            "\n".join(json.dumps(r) for r in desktop_records) + "\n", encoding="utf-8"
        )

        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(tmp_path), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        messages = [r["message"] for r in rows]
        assert any("JSONL prompt" in m for m in messages)
        assert any("Array prompt" in m for m in messages)
        assert any("Desktop prompt" in m for m in messages)

    def test_codex_directory_total_row_count(self, tmp_path):
        (tmp_path / "a.jsonl").write_text(
            '{"role":"user","content":"Q1"}\n{"role":"assistant","content":"A1"}\n',
            encoding="utf-8",
        )
        (tmp_path / "b.json").write_text(
            '[{"role":"user","content":"Q2"},{"role":"assistant","content":"A2"}]',
            encoding="utf-8",
        )
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(tmp_path), output=str(out)))
        rows = _read_csv(out)
        assert len(rows) == 4

    def test_codex_desktop_in_nested_sessions_dir(self, tmp_path):
        """Simulate ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl structure."""
        nested = tmp_path / "sessions" / "2026" / "06" / "02"
        nested.mkdir(parents=True)
        desktop_records = [
            {"timestamp": "2026-06-02T09:00:00Z", "type": "session_meta",
             "payload": {"id": "nested-sess-001",
                         "cwd": "C:\\Users\\Robin\\nested-test-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-06-02T09:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Nested prompt"}},
            {"timestamp": "2026-06-02T09:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message",
                         "message": "Nested response", "phase": "final_answer"}},
        ]
        (nested / "rollout-2026-06-02T09-00-00-nested-sess-001.jsonl").write_text(
            "\n".join(json.dumps(r) for r in desktop_records) + "\n", encoding="utf-8"
        )
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(tmp_path / "sessions"), output=str(out)))
        assert rc == 0
        rows = _read_csv(out)
        assert len(rows) == 2
        assert rows[0]["project"] == "Nested Test Project"
        assert rows[0]["message"] == "Nested prompt"
        assert rows[1]["message"] == "Nested response"
