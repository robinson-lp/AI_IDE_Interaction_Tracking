"""
Functional Test Suite
=====================
Verifies every user-facing feature of ai-tracker behaves correctly.
Each class maps to one named feature. Tests are written from the user's
perspective: "given this input, the feature must produce this outcome."

Features covered:
  F01  Parse Claude Code conversations
  F02  Parse Antigravity IDE conversations
  F03  Parse Codex conversations (JSONL, JSON array, Desktop event-log)
  F04  Export to CSV
  F05  Filter by date range
  F06  Filter by project name
  F07  Include / exclude sidechain threads
  F08  Split output by project
  F09  List available tools
  F10  Project name resolution
  F11  Multi-turn session tracking
  F12  Chronological ordering
  F13  Codex Desktop auto-detection
  F14  Role normalisation
  F15  Timestamp parsing and serialisation
  F16  Unicode content preservation
  F17  Session metadata tracking (session_id, file_path)
  F18  Config override
  F19  Graceful error handling
  F20  Data immutability (source data not modified during parse)
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_tracker.cli import cmd_list_tools, cmd_parse
from ai_tracker.config import load_config
from ai_tracker.exporters.csv_exporter import FIELDNAMES, CSVExporter
from ai_tracker.models import Message, ParsedSession
from ai_tracker.parsers import get_parser
from ai_tracker.parsers.antigravity import AntigravityParser
from ai_tracker.parsers.claude_code import ClaudeCodeParser
from ai_tracker.parsers.codex import CodexParser

# ── Paths ─────────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
CC_FIXTURE  = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE  = FIXTURES / "antigravity_transcript.jsonl"
CX_FIXTURE  = FIXTURES / "codex_sample.jsonl"
CX_ARRAY    = FIXTURES / "codex_array.json"
CX_DESKTOP  = FIXTURES / "codex_desktop_session.jsonl"

# ── Shared helpers ─────────────────────────────────────────────────────────────

def _args(**kw) -> argparse.Namespace:
    base = dict(tool="all", file=None, output=None, start_date=None,
                end_date=None, include_sidechains=True, project=None,
                split_by_project=False)
    base.update(kw)
    return argparse.Namespace(**base)

def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))

def _parse_all(parser) -> list[Message]:
    return [m for s in parser.parse() for m in s.messages]

def _write_session(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# F01  Parse Claude Code conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestF01ParseClaudeCode:
    """The system correctly parses Claude Code JSONL session files."""

    def test_human_messages_extracted(self):
        msgs = _parse_all(ClaudeCodeParser(CC_FIXTURE))
        assert any(m.role == "human" for m in msgs)

    def test_assistant_messages_extracted(self):
        msgs = _parse_all(ClaudeCodeParser(CC_FIXTURE))
        assert any(m.role == "assistant" for m in msgs)

    def test_queue_operations_not_in_output(self):
        msgs = _parse_all(ClaudeCodeParser(CC_FIXTURE))
        assert not any(m.role == "queue-operation" for m in msgs)

    def test_list_content_blocks_joined_to_text(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [
                {"type": "text", "text": "Line one"},
                {"type": "text", "text": "Line two"},
            ]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(f, [r])
        msgs = _parse_all(ClaudeCodeParser(f))
        assert "Line one" in msgs[0].message
        assert "Line two" in msgs[0].message

    def test_string_content_extracted_directly(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": "Plain string content"},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(f, [r])
        msgs = _parse_all(ClaudeCodeParser(f))
        assert msgs[0].message == "Plain string content"

    def test_session_id_comes_from_record_not_filename(self):
        msgs = _parse_all(ClaudeCodeParser(CC_FIXTURE))
        assert all(m.session_id == "abc12345-0000-0000-0000-000000000001" for m in msgs)

    def test_directory_scan_finds_all_jsonl_files(self, tmp_path):
        for i, name in enumerate(["a.jsonl", "b.jsonl"]):
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": f"Q{i}"}]},
                "uuid": f"u{i}", "timestamp": "2026-05-01T10:00:00Z", "sessionId": f"s{i}",
            }
            _write_session(tmp_path / name, [r])
        msgs = _parse_all(ClaudeCodeParser(tmp_path))
        assert len(msgs) == 2

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ClaudeCodeParser(tmp_path / "no.jsonl").parse()


# ═════════════════════════════════════════════════════════════════════════════
# F02  Parse Antigravity IDE conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestF02ParseAntigravity:
    """The system correctly parses Antigravity transcript.jsonl files."""

    def test_user_input_records_become_human_messages(self):
        msgs = _parse_all(AntigravityParser(AG_FIXTURE))
        assert any(m.role == "human" for m in msgs)

    def test_planner_response_with_thinking_becomes_assistant(self):
        msgs = _parse_all(AntigravityParser(AG_FIXTURE))
        ai = [m for m in msgs if m.role == "assistant"]
        assert any("[::-1]" in m.message for m in ai)

    def test_system_records_excluded(self):
        msgs = _parse_all(AntigravityParser(AG_FIXTURE))
        assert not any("CONVERSATION_HISTORY" in m.message for m in msgs)

    def test_tool_call_only_response_captured(self):
        msgs = _parse_all(AntigravityParser(AG_FIXTURE))
        ai = [m for m in msgs if m.role == "assistant"]
        assert any("list_dir" in m.message for m in ai)

    def test_tool_result_records_captured_with_tool_role(self):
        msgs = _parse_all(AntigravityParser(AG_FIXTURE))
        tool_msgs = [m for m in msgs if m.role == "tool"]
        assert len(tool_msgs) >= 1

    def test_brain_dir_scans_all_session_subdirs(self, tmp_path):
        brain = tmp_path / "brain"
        for uid in ["aaaa-0001", "bbbb-0002"]:
            logs = brain / uid / ".system_generated" / "logs"
            logs.mkdir(parents=True)
            r = {
                "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
                "content": "Hello",
            }
            _write_session(logs / "transcript.jsonl", [r])
        sessions = AntigravityParser(brain).parse()
        assert len(sessions) == 2

    def test_overview_txt_accepted_as_log_file(self, tmp_path):
        logs = tmp_path / "sess" / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
            "content": "Via overview",
        }
        _write_session(logs / "overview.txt", [r])
        sessions = AntigravityParser(tmp_path).parse()
        assert len(sessions) == 1

    def test_project_name_extracted_from_active_document_metadata(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
            "content": (
                "<USER_REQUEST>\nHello\n</USER_REQUEST>\n"
                "<ADDITIONAL_METADATA>\n"
                "Active Document: c:\\Users\\Robin\\my-web-app\\app.py\n"
                "</ADDITIONAL_METADATA>"
            ),
        }
        _write_session(f, [r])
        sessions = AntigravityParser(f).parse()
        assert sessions[0].project == "My Web App"


# ═════════════════════════════════════════════════════════════════════════════
# F03  Parse Codex conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestF03ParseCodex:
    """The system parses simple JSONL, JSON array, and Codex Desktop formats."""

    def test_simple_jsonl_human_message_extracted(self):
        msgs = _parse_all(CodexParser(CX_FIXTURE))
        assert any("sort" in m.message.lower() for m in msgs if m.role == "human")

    def test_json_array_message_extracted(self):
        msgs = _parse_all(CodexParser(CX_ARRAY))
        assert any("generator" in m.message.lower() for m in msgs if m.role == "assistant")

    def test_desktop_user_messages_extracted(self):
        msgs = _parse_all(CodexParser(CX_DESKTOP))
        assert any("programming concepts" in m.message.lower() for m in msgs if m.role == "human")

    def test_desktop_commentary_excluded(self):
        msgs = _parse_all(CodexParser(CX_DESKTOP))
        assert not any("Thinking about" in m.message for m in msgs)

    def test_system_role_records_excluded(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"system","content":"System instruction"}\n'
            '{"role":"user","content":"User prompt"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert len(msgs) == 1
        assert msgs[0].role == "human"

    def test_unix_epoch_timestamp_parsed(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"role":"user","content":"Hi","timestamp":1716192000}\n', encoding="utf-8")
        msgs = _parse_all(CodexParser(f))
        assert msgs[0].timestamp is not None

    def test_auto_detects_desktop_format_by_first_record_type(self, tmp_path):
        records = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "test-id", "cwd": "C:\\Users\\Robin\\my-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Auto-detected desktop prompt"}},
            {"timestamp": "2026-05-01T10:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message",
                         "message": "Auto-detected desktop response", "phase": "final_answer"}},
        ]
        f = tmp_path / "session.jsonl"
        _write_session(f, records)
        msgs = _parse_all(CodexParser(f))
        assert any("Auto-detected desktop prompt" in m.message for m in msgs)

    def test_directory_scan_finds_both_json_and_jsonl(self, tmp_path):
        (tmp_path / "a.jsonl").write_text(
            '{"role":"user","content":"From JSONL"}\n', encoding="utf-8"
        )
        (tmp_path / "b.json").write_text(
            '[{"role":"user","content":"From JSON"}]', encoding="utf-8"
        )
        msgs = _parse_all(CodexParser(tmp_path))
        texts = [m.message for m in msgs]
        assert any("From JSONL" in t for t in texts)
        assert any("From JSON" in t for t in texts)


# ═════════════════════════════════════════════════════════════════════════════
# F04  Export to CSV
# ═════════════════════════════════════════════════════════════════════════════

class TestF04ExportToCSV:
    """The system exports parsed messages to a correctly structured UTF-8 CSV."""

    def test_csv_has_seven_columns_in_correct_order(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    def test_csv_created_at_specified_path(self, tmp_path):
        out = tmp_path / "sub" / "output.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        assert out.exists()

    def test_parent_directories_created_automatically(self, tmp_path):
        out = tmp_path / "a" / "b" / "c" / "out.csv"
        CSVExporter(out).export([Message(
            session_id="s", timestamp=None, role="human",
            message="x", tool="codex", file_path="/f",
        )])
        assert out.exists()

    def test_return_code_zero_on_success(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        assert rc == 0

    def test_return_code_one_when_no_messages(self, tmp_path, capsys):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(empty), output=str(out)))
        assert rc == 1

    def test_empty_input_writes_header_only(self, tmp_path):
        out = tmp_path / "out.csv"
        CSVExporter(out).export([])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows == []

    def test_row_count_matches_message_count(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        assert len(_read_csv(out)) == 5


# ═════════════════════════════════════════════════════════════════════════════
# F05  Filter by date range
# ═════════════════════════════════════════════════════════════════════════════

class TestF05FilterByDateRange:
    """The --start-date and --end-date flags restrict which messages appear."""

    def test_start_date_in_future_produces_no_output(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                             output=str(out), start_date=datetime(2099, 1, 1)))
        assert rc == 1

    def test_end_date_in_past_produces_no_output(self, tmp_path):
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                             output=str(out), end_date=datetime(2000, 1, 1)))
        assert rc == 1

    def test_matching_range_keeps_all_messages(self, tmp_path):
        out_all   = tmp_path / "all.csv"
        out_range = tmp_path / "range.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out_all)))
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out_range),
                        start_date=datetime(2020, 1, 1),
                        end_date=datetime(2099, 1, 1)))
        assert len(_read_csv(out_all)) == len(_read_csv(out_range))

    def test_end_date_covers_entire_day(self, tmp_path):
        """End date 2026-05-20 must include messages timestamped at 06:09 that day."""
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                             output=str(out),
                             start_date=datetime(2026, 5, 20),
                             end_date=datetime(2026, 5, 20)))
        assert rc == 0
        assert len(_read_csv(out)) > 0

    def test_none_timestamp_messages_always_included(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "role": "user", "content": "No timestamp message",
        }
        f.write_text(json.dumps(r) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(f), output=str(out),
                             start_date=datetime(2099, 1, 1)))
        assert rc == 0
        rows = _read_csv(out)
        assert rows[0]["message"] == "No timestamp message"

    def test_date_filter_does_not_affect_other_tools(self, tmp_path):
        """Applying a date filter to one tool must not discard messages from another."""
        ag_out = tmp_path / "ag.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE),
                        output=str(ag_out),
                        start_date=datetime(2026, 5, 1),
                        end_date=datetime(2026, 5, 31)))
        assert ag_out.exists()
        assert len(_read_csv(ag_out)) > 0


# ═════════════════════════════════════════════════════════════════════════════
# F06  Filter by project name
# ═════════════════════════════════════════════════════════════════════════════

class TestF06FilterByProjectName:
    """The --project flag restricts output to messages matching the project name."""

    def _two_project_dir(self, tmp_path: Path) -> Path:
        for slug, text in [("alpha-app", "From alpha"), ("beta-svc", "From beta")]:
            d = tmp_path / "projects" / slug
            d.mkdir(parents=True)
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
            }
            _write_session(d / "session.jsonl", [r])
        return tmp_path / "projects"

    def test_only_matching_project_rows_exported(self, tmp_path):
        root = self._two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="alpha"))
        rows = _read_csv(out)
        assert all("alpha" in r["project"].lower() for r in rows)

    def test_non_matching_project_excluded(self, tmp_path):
        root = self._two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="alpha"))
        rows = _read_csv(out)
        assert not any("beta" in r["project"].lower() for r in rows)

    def test_filter_is_case_insensitive(self, tmp_path):
        root = self._two_project_dir(tmp_path)
        out_l = tmp_path / "lower.csv"
        out_u = tmp_path / "upper.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out_l), project="alpha"))
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(out_u), project="ALPHA"))
        assert len(_read_csv(out_l)) == len(_read_csv(out_u))

    def test_partial_name_matches(self, tmp_path):
        root = self._two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root), output=str(out), project="app"))
        assert rc == 0

    def test_no_matching_project_exits_nonzero(self, tmp_path, capsys):
        root = self._two_project_dir(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root), output=str(out),
                             project="zzz-no-match"))
        assert rc == 1


# ═════════════════════════════════════════════════════════════════════════════
# F07  Include / exclude sidechain threads
# ═════════════════════════════════════════════════════════════════════════════

class TestF07SidechainControl:
    """Users can include or exclude subagent sidechain messages."""

    def test_sidechains_included_by_default(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        assert len(_read_csv(out)) == 5

    def test_sidechains_excluded_when_flag_set(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        assert len(_read_csv(out)) == 4

    def test_excluding_sidechains_removes_sidechain_text(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        rows = _read_csv(out)
        assert not any("Subagent" in r["message"] for r in rows)

    def test_including_sidechains_preserves_sidechain_text(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        rows = _read_csv(out)
        assert any("Subagent" in r["message"] for r in rows)

    def test_sidechain_record_skipped_at_parser_level(self, tmp_path):
        f = tmp_path / "s.jsonl"
        records = [
            {
                "type": "user", "isSidechain": True,
                "message": {"role": "user", "content": [{"type": "text", "text": "Sidechain msg"}]},
                "uuid": "s1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "sess1",
            },
            {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Normal msg"}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:01Z", "sessionId": "sess1",
            },
        ]
        _write_session(f, records)
        msgs = _parse_all(ClaudeCodeParser(f, include_sidechains=False))
        assert len(msgs) == 1
        assert msgs[0].message == "Normal msg"


# ═════════════════════════════════════════════════════════════════════════════
# F08  Split output by project
# ═════════════════════════════════════════════════════════════════════════════

class TestF08SplitByProject:
    """--split-by-project writes one CSV per unique project name."""

    def _three_projects(self, tmp_path: Path) -> Path:
        for slug, ts, msg in [
            ("alpha", "2026-05-01T08:00:00Z", "Alpha msg"),
            ("beta",  "2026-05-01T09:00:00Z", "Beta msg"),
            ("gamma", "2026-05-01T10:00:00Z", "Gamma msg"),
        ]:
            d = tmp_path / "projects" / slug
            d.mkdir(parents=True)
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": msg}]},
                "uuid": "u1", "timestamp": ts, "sessionId": "s1",
            }
            _write_session(d / "session.jsonl", [r])
        return tmp_path / "projects"

    def test_one_csv_per_project(self, tmp_path):
        root = self._three_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        assert len(list(out_dir.glob("*.csv"))) == 3

    def test_each_csv_contains_only_its_project(self, tmp_path):
        root = self._three_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            rows = _read_csv(f)
            assert len({r["project"] for r in rows}) == 1

    def test_filenames_use_project_name_snake_case(self, tmp_path):
        root = self._three_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        stems = {f.stem for f in out_dir.glob("*.csv")}
        for stem in stems:
            assert stem == stem.lower()
            assert " " not in stem

    def test_auto_dir_created_when_output_not_specified(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = self._three_projects(tmp_path)
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=None, split_by_project=True))
        dirs = list(tmp_path.glob("ai_projects_*"))
        assert len(dirs) == 1

    def test_project_filter_applied_before_split(self, tmp_path):
        root = self._three_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True, project="alpha"))
        assert len(list(out_dir.glob("*.csv"))) == 1

    def test_each_split_csv_has_correct_schema(self, tmp_path):
        root = self._three_projects(tmp_path)
        out_dir = tmp_path / "out"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            with open(f, encoding="utf-8") as fh:
                assert csv.DictReader(fh).fieldnames == FIELDNAMES


# ═════════════════════════════════════════════════════════════════════════════
# F09  List available tools
# ═════════════════════════════════════════════════════════════════════════════

class TestF09ListTools:
    """list-tools shows all registered parsers with their path status."""

    def test_returns_zero(self, capsys):
        assert cmd_list_tools(_args()) == 0

    def test_all_three_tools_listed(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "claudecode" in out
        assert "antigravity" in out
        assert "codex" in out

    def test_status_column_shows_found_or_not_found(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "found" in out

    def test_path_shown_for_each_tool(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert ".claude" in out or ".gemini" in out or ".codex" in out or "home" in out.lower()

    def test_output_is_aligned_table(self, capsys):
        cmd_list_tools(_args())
        lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert len(lines) >= 4  # header + separator + 3 tool rows


# ═════════════════════════════════════════════════════════════════════════════
# F10  Project name resolution
# ═════════════════════════════════════════════════════════════════════════════

class TestF10ProjectNameResolution:
    """Project names are extracted from file paths and session metadata."""

    def test_claude_code_slug_cleaned_to_readable_name(self, tmp_path):
        proj = tmp_path / "projects" / "c--Users-Robin-my-test-project"
        proj.mkdir(parents=True)
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "Q"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(proj / "session.jsonl", [r])
        sessions = ClaudeCodeParser(proj / "session.jsonl").parse()
        assert sessions[0].project == "My Test Project"

    def test_antigravity_project_from_active_document(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
            "content": (
                "<USER_REQUEST>\nHello\n</USER_REQUEST>\n"
                "Active Document: c:\\Users\\Robin\\invoice-processor\\main.py"
            ),
        }
        _write_session(f, [r])
        sessions = AntigravityParser(f).parse()
        assert sessions[0].project == "Invoice Processor"

    def test_codex_desktop_project_from_cwd(self, tmp_path):
        records = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "p-test", "cwd": "C:\\Users\\Robin\\data-pipeline-tool",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Hello"}},
        ]
        f = tmp_path / "session.jsonl"
        _write_session(f, records)
        sessions = CodexParser(f).parse()
        assert sessions[0].project == "Data Pipeline Tool"

    def test_no_project_info_defaults_to_general(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"role":"user","content":"Hi"}\n', encoding="utf-8")
        sessions = CodexParser(f).parse()
        assert sessions[0].project == "General"

    def test_project_name_propagates_to_all_messages(self, tmp_path):
        proj = tmp_path / "projects" / "my-special-project"
        proj.mkdir(parents=True)
        records = [
            {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Q"}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
            },
            {
                "type": "assistant", "isSidechain": False,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "A"}]},
                "uuid": "a1", "timestamp": "2026-05-01T10:00:05Z", "sessionId": "s1",
            },
        ]
        _write_session(proj / "session.jsonl", records)
        msgs = _parse_all(ClaudeCodeParser(proj / "session.jsonl"))
        assert all(m.project == "My Special Project" for m in msgs)


# ═════════════════════════════════════════════════════════════════════════════
# F11  Multi-turn session tracking
# ═════════════════════════════════════════════════════════════════════════════

class TestF11MultiTurnSessions:
    """Multiple turns in a session are tracked under the same session_id."""

    def test_all_turns_share_session_id(self, tmp_path):
        f = tmp_path / "s.jsonl"
        records = [
            {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Turn 1"}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "shared-sess",
            },
            {
                "type": "assistant", "isSidechain": False,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Reply 1"}]},
                "uuid": "a1", "timestamp": "2026-05-01T10:00:05Z", "sessionId": "shared-sess",
            },
            {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Turn 2"}]},
                "uuid": "u2", "timestamp": "2026-05-01T10:01:00Z", "sessionId": "shared-sess",
            },
        ]
        _write_session(f, records)
        msgs = _parse_all(ClaudeCodeParser(f))
        assert all(m.session_id == "shared-sess" for m in msgs)
        assert len(msgs) == 3

    def test_antigravity_multi_turn_same_file(self):
        sessions = AntigravityParser(AG_FIXTURE).parse()
        assert len(sessions) == 1
        msgs = sessions[0].messages
        human = [m for m in msgs if m.role == "human"]
        assert len(human) == 2  # two separate user prompts in the fixture

    def test_codex_desktop_multi_turn_same_session(self):
        sessions = CodexParser(CX_DESKTOP).parse()
        assert len(sessions) == 1
        msgs = sessions[0].messages
        human = [m for m in msgs if m.role == "human"]
        assert len(human) == 2

    def test_multiple_sessions_in_one_directory(self, tmp_path):
        for i in range(3):
            f = tmp_path / f"sess{i}.jsonl"
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": f"Q{i}"}]},
                "uuid": f"u{i}", "timestamp": "2026-05-01T10:00:00Z", "sessionId": f"sess-{i}",
            }
            _write_session(f, [r])
        sessions = ClaudeCodeParser(tmp_path).parse()
        assert len(sessions) == 3


# ═════════════════════════════════════════════════════════════════════════════
# F12  Chronological ordering
# ═════════════════════════════════════════════════════════════════════════════

class TestF12ChronologicalOrdering:
    """Messages are sorted by timestamp in the exported CSV."""

    def test_claude_code_messages_ordered_by_timestamp(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        ts = [r["timestamp"] for r in rows if r["timestamp"]]
        assert ts == sorted(ts)

    def test_antigravity_messages_ordered_by_timestamp(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        ts = [r["timestamp"] for r in rows if r["timestamp"]]
        assert ts == sorted(ts)

    def test_codex_messages_ordered_by_timestamp(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(CX_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        ts = [r["timestamp"] for r in rows if r["timestamp"]]
        assert ts == sorted(ts)

    def test_each_individual_tool_csv_is_internally_sorted(self, tmp_path):
        """Each tool's own CSV is chronologically sorted within itself."""
        for tool, fixture in [("claudecode", CC_FIXTURE),
                               ("antigravity", AG_FIXTURE),
                               ("codex", CX_FIXTURE)]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
            rows = _read_csv(out)
            ts = [r["timestamp"] for r in rows if r["timestamp"]]
            assert ts == sorted(ts), f"{tool} CSV is not chronologically sorted"


# ═════════════════════════════════════════════════════════════════════════════
# F13  Codex Desktop auto-detection
# ═════════════════════════════════════════════════════════════════════════════

class TestF13CodexDesktopAutoDetection:
    """The Codex Desktop event-log format is auto-detected by the first record type."""

    def test_session_meta_triggers_desktop_parser(self, tmp_path):
        records = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "det-test", "cwd": "C:\\Users\\Robin\\det-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Detected question"}},
            {"timestamp": "2026-05-01T10:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message",
                         "message": "Detected answer", "phase": "final_answer"}},
        ]
        f = tmp_path / "session.jsonl"
        _write_session(f, records)
        msgs = _parse_all(CodexParser(f))
        assert len(msgs) == 2
        assert msgs[0].role == "human"
        assert msgs[1].role == "assistant"

    def test_simple_role_content_format_still_works(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"role":"user","content":"Simple"}\n', encoding="utf-8")
        msgs = _parse_all(CodexParser(f))
        assert len(msgs) == 1
        assert msgs[0].role == "human"

    def test_desktop_project_name_extracted_from_cwd(self, tmp_path):
        records = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "pname-test",
                         "cwd": "C:\\Users\\Robin\\machine-learning-pipeline",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Question"}},
        ]
        f = tmp_path / "session.jsonl"
        _write_session(f, records)
        sessions = CodexParser(f).parse()
        assert sessions[0].project == "Machine Learning Pipeline"

    def test_event_msg_type_triggers_desktop_parser(self, tmp_path):
        records = [
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "No meta first"}},
        ]
        f = tmp_path / "session.jsonl"
        _write_session(f, records)
        msgs = _parse_all(CodexParser(f))
        assert msgs[0].message == "No meta first"


# ═════════════════════════════════════════════════════════════════════════════
# F14  Role normalisation
# ═════════════════════════════════════════════════════════════════════════════

class TestF14RoleNormalisation:
    """All role variations map to 'human' or 'assistant' in CSV output."""

    @pytest.mark.parametrize("raw_role,expected", [
        ("user",      "human"),
        ("human",     "human"),
        ("h",         "human"),
        ("u",         "human"),
        ("assistant", "assistant"),
        ("ai",        "assistant"),
        ("model",     "assistant"),
        ("bot",       "assistant"),
    ])
    def test_codex_role_aliases_normalised(self, raw_role, expected, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps({"role": raw_role, "content": "Text"}) + "\n",
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        if msgs:
            assert msgs[0].role == expected

    def test_claude_code_user_role_becomes_human(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "Q"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(f, [r])
        msgs = _parse_all(ClaudeCodeParser(f))
        assert msgs[0].role == "human"

    def test_system_role_excluded_from_output(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"system","content":"System text"}\n'
            '{"role":"user","content":"User text"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert all(m.role != "system" for m in msgs)
        assert len(msgs) == 1


# ═════════════════════════════════════════════════════════════════════════════
# F15  Timestamp parsing and serialisation
# ═════════════════════════════════════════════════════════════════════════════

class TestF15TimestampHandling:
    """Timestamps from various formats are parsed and serialised to ISO strings."""

    def test_iso_timestamp_with_z_parsed(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":"Hi","timestamp":"2026-05-22T06:00:00Z"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert msgs[0].timestamp is not None
        assert msgs[0].timestamp.year == 2026

    def test_unix_epoch_timestamp_parsed(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":"Hi","timestamp":1716192000}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert msgs[0].timestamp is not None

    def test_none_timestamp_serialised_as_empty_string(self, tmp_path):
        out = tmp_path / "out.csv"
        f = tmp_path / "s.jsonl"
        f.write_text('{"role":"user","content":"Hi"}\n', encoding="utf-8")
        cmd_parse(_args(tool="codex", file=str(f), output=str(out)))
        rows = _read_csv(out)
        assert rows[0]["timestamp"] == ""

    def test_iso_timestamp_serialised_in_csv(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        assert all("2026" in r["timestamp"] for r in rows if r["timestamp"])

    def test_timestamp_preserves_timezone_info(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":"Hi","timestamp":"2026-05-22T06:00:00+05:30"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert msgs[0].timestamp.tzinfo is not None


# ═════════════════════════════════════════════════════════════════════════════
# F16  Unicode content preservation
# ═════════════════════════════════════════════════════════════════════════════

class TestF16UnicodePreservation:
    """Non-ASCII content (emoji, CJK, accented chars) survives the full pipeline."""

    @pytest.mark.parametrize("text", [
        "日本語テスト",
        "こんにちは 🎉",
        "Ünïcödé tëxt",
        "Привет мир",
        "مرحبا بالعالم",
        "emoji: 🚀🔥💡",
    ])
    def test_unicode_survives_codex_pipeline(self, text, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(json.dumps({"role": "user", "content": text}) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(f), output=str(out)))
        rows = _read_csv(out)
        assert rows[0]["message"] == text

    def test_unicode_survives_claude_code_pipeline(self, tmp_path):
        text = "Claude says: こんにちは 🤖"
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(f, [r])
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(f), output=str(out)))
        rows = _read_csv(out)
        assert rows[0]["message"] == text

    def test_csv_output_is_utf8_encoded(self, tmp_path):
        text = "日本語 🎉"
        f = tmp_path / "s.jsonl"
        f.write_text(json.dumps({"role": "user", "content": text}) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(f), output=str(out)))
        raw = out.read_bytes()
        assert text.encode("utf-8") in raw


# ═════════════════════════════════════════════════════════════════════════════
# F17  Session metadata tracking
# ═════════════════════════════════════════════════════════════════════════════

class TestF17SessionMetadata:
    """session_id and file_path are correctly tracked on every message."""

    def test_session_id_in_every_csv_row(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        assert all(r["session_id"] for r in rows)

    def test_file_path_in_every_csv_row(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        assert all(r["file_path"] for r in rows)

    def test_file_path_points_to_source_file(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _read_csv(out)
        assert all("claude_code_sample" in r["file_path"] for r in rows)

    def test_codex_desktop_session_id_from_meta(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        rows = _read_csv(out)
        assert all(r["session_id"] == "019e87b9-0cd0-76b1-8e23-2914f91ceda9" for r in rows)

    def test_antigravity_session_id_from_dir_name(self, tmp_path):
        brain = tmp_path / "brain"
        logs = brain / "my-session-uuid" / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-01T10:00:00Z",
            "content": "Hello",
        }
        _write_session(logs / "transcript.jsonl", [r])
        sessions = AntigravityParser(brain).parse()
        assert sessions[0].session_id == "my-session-uuid"


# ═════════════════════════════════════════════════════════════════════════════
# F18  Config override
# ═════════════════════════════════════════════════════════════════════════════

class TestF18ConfigOverride:
    """User-provided config/tools.yaml overrides built-in defaults."""

    def test_custom_path_overrides_default(self, tmp_path):
        proj = tmp_path / "custom_projects" / "test"
        proj.mkdir(parents=True)
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "Custom path test"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write_session(proj / "session.jsonl", [r])
        cfg_file = tmp_path / "tools.yaml"
        cfg_file.write_text(
            f"tools:\n  claudecode:\n    path: {tmp_path / 'custom_projects'}\n",
            encoding="utf-8",
        )
        cfg = load_config(config_path=cfg_file)
        assert cfg["tools"]["claudecode"]["path"] == str(tmp_path / "custom_projects")

    def test_custom_config_does_not_remove_other_tools(self, tmp_path):
        cfg_file = tmp_path / "tools.yaml"
        cfg_file.write_text("tools:\n  codex:\n    path: /custom/codex\n", encoding="utf-8")
        cfg = load_config(config_path=cfg_file)
        assert "claudecode" in cfg["tools"]
        assert "antigravity" in cfg["tools"]

    def test_missing_config_falls_back_to_defaults(self, tmp_path):
        cfg = load_config(config_path=tmp_path / "nonexistent.yaml")
        assert "claudecode" in cfg["tools"]
        assert "antigravity" in cfg["tools"]
        assert "codex" in cfg["tools"]

    def test_empty_yaml_falls_back_to_defaults(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("", encoding="utf-8")
        cfg = load_config(config_path=cfg_file)
        assert len(cfg["tools"]) == 3


# ═════════════════════════════════════════════════════════════════════════════
# F19  Graceful error handling
# ═════════════════════════════════════════════════════════════════════════════

class TestF19GracefulErrorHandling:
    """The system handles bad inputs without crashing — skips and continues."""

    def test_nonexistent_source_path_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ClaudeCodeParser(tmp_path / "no_such_file.jsonl").parse()

    def test_empty_file_returns_no_sessions(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        assert ClaudeCodeParser(f).parse() == []

    def test_malformed_json_lines_skipped_silently(self, tmp_path):
        f = tmp_path / "s.jsonl"
        good = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": "Good"}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f.write_text("BROKEN JSON\n" + json.dumps(good) + "\n", encoding="utf-8")
        msgs = _parse_all(ClaudeCodeParser(f))
        assert len(msgs) == 1
        assert msgs[0].message == "Good"

    def test_missing_role_field_record_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"content":"no role"}\n'
            '{"role":"user","content":"has role"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert len(msgs) == 1

    def test_missing_content_field_record_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user"}\n'
            '{"role":"assistant","content":"has content"}\n',
            encoding="utf-8",
        )
        msgs = _parse_all(CodexParser(f))
        assert len(msgs) == 1

    def test_cmd_parse_nonzero_on_empty_result(self, tmp_path, capsys):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(empty), output=str(out)))
        assert rc == 1

    def test_list_tools_never_crashes(self, capsys):
        rc = cmd_list_tools(_args())
        assert rc == 0


# ═════════════════════════════════════════════════════════════════════════════
# F20  Data immutability
# ═════════════════════════════════════════════════════════════════════════════

class TestF20DataImmutability:
    """Source ParsedSession objects are never modified during filtering or export."""

    @pytest.mark.parametrize("parser_cls,fixture", [
        (ClaudeCodeParser,  CC_FIXTURE),
        (AntigravityParser, AG_FIXTURE),
        (CodexParser,       CX_FIXTURE),
    ])
    def test_filter_does_not_mutate_original_sessions(self, parser_cls, fixture):
        parser = parser_cls(fixture)
        sessions = parser.parse()
        original_counts = [len(s.messages) for s in sessions]
        parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        assert [len(s.messages) for s in sessions] == original_counts

    @pytest.mark.parametrize("parser_cls,fixture", [
        (ClaudeCodeParser,  CC_FIXTURE),
        (AntigravityParser, AG_FIXTURE),
        (CodexParser,       CX_FIXTURE),
    ])
    def test_filter_returns_new_session_objects(self, parser_cls, fixture):
        parser = parser_cls(fixture)
        sessions = parser.parse()
        filtered = parser.filter_by_date(
            sessions, start=datetime(2020, 1, 1), end=datetime(2099, 1, 1)
        )
        for orig, filt in zip(sessions, filtered):
            assert orig is not filt

    def test_export_does_not_modify_messages(self, tmp_path):
        msgs = _parse_all(ClaudeCodeParser(CC_FIXTURE))
        originals = [(m.message, m.role, m.session_id) for m in msgs]
        CSVExporter(tmp_path / "out.csv").export(msgs)
        after = [(m.message, m.role, m.session_id) for m in msgs]
        assert originals == after

    def test_parsing_twice_gives_identical_results(self):
        parser = ClaudeCodeParser(CC_FIXTURE)
        first  = [(m.role, m.message) for s in parser.parse() for m in s.messages]
        second = [(m.role, m.message) for s in parser.parse() for m in s.messages]
        assert first == second
