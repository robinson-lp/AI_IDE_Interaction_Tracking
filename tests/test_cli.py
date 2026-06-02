"""Tests for the ai-tracker CLI commands."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from ai_tracker.cli import _project_to_filename, cmd_list_tools, cmd_parse

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
        "include_sidechains": True,
        "project": None,
        "split_by_project": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_project_sessions(root: Path, slugs: list[str], text: str = "Q") -> None:
    """Write one minimal JSONL session file per project slug under root/projects/<slug>/."""
    for slug in slugs:
        d = root / slug
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "type": "user",
            "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": f"{text} from {slug}"}]},
            "uuid": "u1",
            "timestamp": "2026-05-01T10:00:00Z",
            "sessionId": "sess-1",
        }
        (d / "session.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


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
        assert fieldnames == ["project", "session_id", "timestamp", "role", "message", "tool", "file_path"]

    def test_csv_rows_match_parsed_count(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 5  # 2 human + 2 assistant + 1 sidechain (included by default)

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

    def test_no_sidechains_excludes_sidechain_messages(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            include_sidechains=False,
        ))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4  # sidechain excluded → only 4 normal messages

    def test_no_sidechains_flag_wins_over_config(self, tmp_path, monkeypatch):
        """--no-sidechains (False) must not be overridden by config include_sidechains: true."""
        from ai_tracker import cli as cli_mod
        monkeypatch.setattr(
            cli_mod, "load_config",
            lambda *_: {
                "tools": {"claudecode": {"path": str(CC_FIXTURE), "include_sidechains": True}}
            },
        )
        out = tmp_path / "out.csv"
        # CLI flag include_sidechains=False (--no-sidechains) must exclude sidechains
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out), include_sidechains=False))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # 4 normal messages only — sidechain excluded despite config saying True
        assert len(rows) == 4


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
        assert len(rows) == 5  # 4 normal + 1 sidechain (included by default)

    def test_project_filter_includes_only_matching(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            project="General",
        ))
        assert rc == 0
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 5  # 4 normal + 1 sidechain, all project=General

    def test_project_filter_excludes_nonmatching(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(
            tool="claudecode",
            file=str(CC_FIXTURE),
            output=str(out),
            project="NonmatchingProject",
        ))
        assert rc == 1

    def test_date_filter_does_not_mutate_original_sessions(self, tmp_path):
        """filter_by_date must not modify the messages list on the original ParsedSession."""
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        from datetime import datetime, timezone
        parser = ClaudeCodeParser(CC_FIXTURE)
        sessions_before = parser.parse()
        original_count = len(sessions_before[0].messages)
        # Apply a restrictive filter that removes all messages
        parser.filter_by_date(sessions_before, start=datetime(2030, 1, 1, tzinfo=timezone.utc), end=None)
        # Original session must be untouched
        assert len(sessions_before[0].messages) == original_count



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


# ─────────────────────────────────────────────────────────────────────────────
# parse — split by project
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitByProject:
    def test_creates_one_csv_per_project(self, tmp_path):
        projects = tmp_path / "projects"
        _make_project_sessions(projects, ["alpha", "beta"])
        out_dir = tmp_path / "out"
        rc = cmd_parse(_args(tool="claudecode", file=str(projects), output=str(out_dir), split_by_project=True))
        assert rc == 0
        assert len(list(out_dir.glob("*.csv"))) == 2

    def test_each_csv_contains_only_its_project_messages(self, tmp_path):
        projects = tmp_path / "projects"
        _make_project_sessions(projects, ["alpha", "beta"])
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(projects), output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            with open(f, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            # Each project has exactly 1 message
            assert len(rows) == 1
            # All rows share the same project value
            projects_in_file = {r["project"] for r in rows}
            assert len(projects_in_file) == 1

    def test_filenames_are_sanitized_project_names(self, tmp_path):
        projects = tmp_path / "projects"
        _make_project_sessions(projects, ["my-cool-project"])
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(projects), output=str(out_dir), split_by_project=True))
        stems = {f.stem for f in out_dir.glob("*.csv")}
        assert _project_to_filename("My Cool Project") in stems

    def test_default_output_dir_created_when_no_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        projects = tmp_path / "projects"
        _make_project_sessions(projects, ["alpha"])
        cmd_parse(_args(tool="claudecode", file=str(projects), output=None, split_by_project=True))
        dirs = list(tmp_path.glob("ai_projects_*"))
        assert len(dirs) == 1 and dirs[0].is_dir()

    def test_project_filter_combined_with_split(self, tmp_path):
        projects = tmp_path / "projects"
        _make_project_sessions(projects, ["alpha", "beta"])
        out_dir = tmp_path / "out"
        # filter to only "alpha" then split — should produce exactly 1 file
        cmd_parse(_args(
            tool="claudecode",
            file=str(projects),
            output=str(out_dir),
            split_by_project=True,
            project="alpha",
        ))
        assert len(list(out_dir.glob("*.csv"))) == 1

    def test_project_to_filename_sanitizes_spaces_and_case(self):
        assert _project_to_filename("AI Tracking System") == "ai_tracking_system"
        assert _project_to_filename("My Cool Project") == "my_cool_project"
        assert _project_to_filename("") == "general"
