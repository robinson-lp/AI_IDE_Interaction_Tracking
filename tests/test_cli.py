"""Tests for the ai-tracker CLI commands."""

import argparse
import csv
from datetime import datetime
from pathlib import Path

import pytest

from ai_tracker.cli import cmd_list_tools, cmd_parse

FIXTURES = Path(__file__).parent / "fixtures"
CC_FIXTURE = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE = FIXTURES / "antigravity_transcript.jsonl"


def _args(**kwargs) -> argparse.Namespace:
    defaults = {
        "tool": "all",
        "file": None,
        "output": None,
        "start_date": None,
        "end_date": None,
        "include_sidechains": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# list-tools
# ─────────────────────────────────────────────────────────────────────────────

class TestListTools:
    def test_returns_zero(self, capsys):
        assert cmd_list_tools(_args()) == 0

    def test_output_includes_all_tools(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "claudecode" in out
        assert "antigravity" in out
        assert "codex" in out

    def test_output_shows_status_column(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "found" in out or "not found" in out


# ─────────────────────────────────────────────────────────────────────────────
# parse — success paths
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSuccess:
    def test_returns_zero_on_success(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        assert rc == 0

    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        assert out.exists()

    def test_csv_has_correct_columns(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            fieldnames = csv.DictReader(fh).fieldnames
        assert fieldnames == ["session_id", "timestamp", "role", "message", "tool", "file_path"]

    def test_csv_rows_match_parsed_count(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4  # 2 human + 2 assistant from the fixture

    def test_tool_column_correct(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert all(r["tool"] == "claudecode" for r in rows)

    def test_roles_are_human_or_assistant(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert all(r["role"] in ("human", "assistant") for r in rows)

    def test_default_output_filename_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=None))
        csv_files = list(tmp_path.glob("ai_interactions_*.csv"))
        assert len(csv_files) == 1

    def test_include_sidechains_flag(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            include_sidechains=True,
        ))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 5  # 4 normal + 1 sidechain message


# ─────────────────────────────────────────────────────────────────────────────
# parse — date filtering
# ─────────────────────────────────────────────────────────────────────────────

class TestParseDateFilter:
    def test_start_date_excludes_all(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            start_date=datetime(2030, 1, 1),
        ))
        assert rc == 1
        assert "No messages" in capsys.readouterr().err

    def test_end_date_excludes_all(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            end_date=datetime(2020, 1, 1),
        ))
        assert rc == 1

    def test_date_range_passes_all(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            start_date=datetime(2026, 5, 1),
            end_date=datetime(2026, 5, 31),
        ))
        assert rc == 0
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4


# ─────────────────────────────────────────────────────────────────────────────
# parse — error/skip paths
# ─────────────────────────────────────────────────────────────────────────────

class TestParseErrors:
    def test_missing_tool_path_skipped_gracefully(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="codex",
            file=str(tmp_path / "no_such_dir"),
            output=str(out),
        ))
        assert rc == 1
        err = capsys.readouterr().err
        assert "Skipped" in err or "No messages" in err

    def test_returns_nonzero_when_no_messages(self, tmp_path, capsys):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(empty), output=str(out)))
        assert rc == 1
