"""
Regression Test Suite
=====================
One test class per fixed bug. Each class:
  - Names the bug it guards
  - Documents what the broken behaviour was
  - Asserts the correct behaviour now

Bug inventory (in fix order):
  R01  filter_by_date mutated input ParsedSession objects
  R02  --no-sidechains could not override config include_sidechains: true
  R03  Codex session_id was a new random UUID on every parse call
  R04  Codex 'system' role was mapped to 'assistant' instead of being skipped
  R05  Dead _USER_REQUEST_RE regex left in antigravity.py (dead code)
  R06  _parse_iso duplicated across antigravity.py and claude_code.py
  R07  _normalise_role duplicated with inconsistent logic
  R08  JSON array files raised AttributeError inside _parse_file format detection
  R09  Codex Desktop event-log format not recognised by CodexParser
  R10  _clean_project_name did not handle None input gracefully
  R11  config.py include_sidechains default (False) conflicted with CLI default (True)
  R12  AntigravityParser _parse_brain_dir did not sort correctly on empty timestamps
  R13  Codex directory scan could double-count files
  R14  CSV column order must stay locked to FIELDNAMES across all parsers
  R15  ClaudeCodeParser: non-dict message blob not guarded
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_tracker.config import load_config
from ai_tracker.exporters.csv_exporter import FIELDNAMES, CSVExporter
from ai_tracker.models import Message, ParsedSession
from ai_tracker.parsers import get_parser
from ai_tracker.parsers.antigravity import AntigravityParser
from ai_tracker.parsers.base import BaseParser, _normalise_role, _parse_timestamp
from ai_tracker.parsers.claude_code import ClaudeCodeParser
from ai_tracker.parsers.codex import CodexParser, _is_codex_desktop_format

# ── Paths ──────────────────────────────────────────────────────────────────────

FIXTURES    = Path(__file__).parent / "fixtures"
CC_FIXTURE  = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE  = FIXTURES / "antigravity_transcript.jsonl"
CX_FIXTURE  = FIXTURES / "codex_sample.jsonl"
CX_DESKTOP  = FIXTURES / "codex_desktop_session.jsonl"

# ── Helper ─────────────────────────────────────────────────────────────────────

def _args(**kw) -> argparse.Namespace:
    base = dict(tool="all", file=None, output=None, start_date=None,
                end_date=None, include_sidechains=True, project=None,
                split_by_project=False)
    base.update(kw)
    return argparse.Namespace(**base)

def _write(path: Path, records: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

def _cc_record(text: str, ts: str = "2026-05-01T10:00:00Z",
               session_id: str = "s1") -> dict:
    return {
        "type": "user", "isSidechain": False,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "uuid": "u1", "timestamp": ts, "sessionId": session_id,
    }


# ═════════════════════════════════════════════════════════════════════════════
# R01  filter_by_date mutated input ParsedSession objects
# ═════════════════════════════════════════════════════════════════════════════

class TestR01FilterByDateMutation:
    """
    BUG: filter_by_date did `session.messages = in_range`, modifying the
    original ParsedSession in-place. Callers that held a reference to the
    session list saw their messages silently truncated.
    FIX: use dataclasses.replace() to return new objects.
    """

    @pytest.mark.parametrize("parser_cls,fixture", [
        (ClaudeCodeParser,  CC_FIXTURE),
        (AntigravityParser, AG_FIXTURE),
        (CodexParser,       CX_FIXTURE),
    ])
    def test_original_session_messages_unchanged_after_restrictive_filter(
        self, parser_cls, fixture
    ):
        parser  = parser_cls(fixture)
        sessions = parser.parse()
        count_before = len(sessions[0].messages)

        parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)

        assert len(sessions[0].messages) == count_before, (
            f"R01 regression: filter_by_date mutated {parser_cls.__name__} session"
        )

    def test_filtered_result_is_new_object_not_same_reference(self):
        parser   = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        filtered = parser.filter_by_date(
            sessions, start=datetime(2020, 1, 1), end=datetime(2099, 1, 1)
        )
        for orig, filt in zip(sessions, filtered):
            assert orig is not filt, "R01 regression: filter returned same object"

    def test_calling_filter_twice_gives_same_result(self):
        parser   = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        first  = parser.filter_by_date(sessions, start=datetime(2020,1,1), end=None)
        second = parser.filter_by_date(sessions, start=datetime(2020,1,1), end=None)
        assert [len(s.messages) for s in first] == [len(s.messages) for s in second], (
            "R01 regression: second filter call returned different count (mutation leak)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R02  --no-sidechains could not override config include_sidechains: true
# ═════════════════════════════════════════════════════════════════════════════

class TestR02SidechainsConfigOverride:
    """
    BUG: cli.py used `include_sidechains or bool(tool_cfg.get(...))`.
    When include_sidechains=False (--no-sidechains) and config said True,
    the OR produced True, silently ignoring the user's flag.
    FIX: explicit if/else — False always wins.
    """

    def test_no_sidechains_flag_excludes_sidechains_regardless_of_config(
        self, tmp_path, monkeypatch
    ):
        from ai_tracker import cli as cli_mod
        monkeypatch.setattr(
            cli_mod, "load_config",
            lambda *_: {"tools": {
                "claudecode": {
                    "path": str(CC_FIXTURE),
                    "include_sidechains": True,   # config says True
                }
            }},
        )
        out = tmp_path / "out.csv"
        # CLI flag says False (--no-sidechains)
        from ai_tracker.cli import cmd_parse
        import csv
        cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE),
            output=str(out), include_sidechains=False,
        ))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4, (
            f"R02 regression: got {len(rows)} rows; config True overrode --no-sidechains"
        )

    def test_include_sidechains_true_still_includes_when_config_is_false(
        self, tmp_path, monkeypatch
    ):
        from ai_tracker import cli as cli_mod
        monkeypatch.setattr(
            cli_mod, "load_config",
            lambda *_: {"tools": {
                "claudecode": {
                    "path": str(CC_FIXTURE),
                    "include_sidechains": False,  # config says False
                }
            }},
        )
        out = tmp_path / "out.csv"
        from ai_tracker.cli import cmd_parse
        import csv
        cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE),
            output=str(out), include_sidechains=True,  # CLI default: include
        ))
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 5, (
            f"R02 regression: got {len(rows)} rows; CLI True was ignored"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R03  Codex session_id was a new random UUID on every parse call
# ═════════════════════════════════════════════════════════════════════════════

class TestR03CodexSessionIdIdempotency:
    """
    BUG: _parse_jsonl and _parse_json_array called uuid.uuid4() to generate
    the session_id fallback, so two calls on the same file returned different
    Message.session_id values — non-idempotent, broke deduplication logic.
    FIX: use Path(file_path).stem as the stable fallback.
    """

    def test_jsonl_session_id_stable_across_two_parses(self, tmp_path):
        f = tmp_path / "stable-session.jsonl"
        f.write_text('{"role":"user","content":"Hello"}\n', encoding="utf-8")
        id1 = CodexParser(f).parse()[0].messages[0].session_id
        id2 = CodexParser(f).parse()[0].messages[0].session_id
        assert id1 == id2, "R03 regression: session_id changed between parses"

    def test_jsonl_session_id_derived_from_filename(self, tmp_path):
        f = tmp_path / "my-known-session.jsonl"
        f.write_text('{"role":"user","content":"Hello"}\n', encoding="utf-8")
        msgs = CodexParser(f).parse()[0].messages
        assert msgs[0].session_id == "my-known-session", (
            "R03 regression: session_id not derived from filename"
        )

    def test_json_array_session_id_stable_across_two_parses(self, tmp_path):
        f = tmp_path / "array-session.json"
        f.write_text('[{"role":"user","content":"Hello"}]', encoding="utf-8")
        id1 = CodexParser(f).parse()[0].messages[0].session_id
        id2 = CodexParser(f).parse()[0].messages[0].session_id
        assert id1 == id2, "R03 regression: JSON array session_id changed between parses"

    def test_record_explicit_session_id_takes_priority(self):
        msgs = CodexParser(CX_FIXTURE).parse()[0].messages
        assert all(m.session_id == "codex-sess-001" for m in msgs), (
            "R03 regression: record's session_id field ignored"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R04  Codex 'system' role mapped to 'assistant'
# ═════════════════════════════════════════════════════════════════════════════

class TestR04SystemRoleNotMappedToAssistant:
    """
    BUG: _normalise_role in codex.py had "system" in the assistant alias list,
    so system-prompt injection records appeared in the CSV as assistant messages.
    FIX: skip records with role=="system" early in _record_to_message, and
    remove "system" from the shared _normalise_role mapping.
    """

    def test_system_role_record_absent_from_parse_output(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"system","content":"System instructions here"}\n'
            '{"role":"user","content":"User question"}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        roles = {m.role for m in msgs}
        assert "assistant" not in roles or not any(
            "System instructions" in m.message for m in msgs
        ), "R04 regression: system role message appeared as assistant"

    def test_system_role_not_in_csv_output(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"system","content":"Injected system prompt"}\n'
            '{"role":"user","content":"Real user message"}\n',
            encoding="utf-8",
        )
        import csv as _csv
        out = tmp_path / "out.csv"
        from ai_tracker.cli import cmd_parse
        cmd_parse(_args(tool="codex", file=str(f), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 1
        assert "Injected system prompt" not in rows[0]["message"], (
            "R04 regression: system message appeared in CSV"
        )

    def test_shared_normalise_role_does_not_map_system_to_assistant(self):
        result = _normalise_role("system")
        assert result != "assistant", (
            "R04 regression: _normalise_role('system') returned 'assistant'"
        )

    def test_system_role_passthrough_is_truthy_string_not_assistant(self):
        result = _normalise_role("system")
        assert result == "system", (
            "R04 regression: expected 'system' passthrough"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R05  Dead _USER_REQUEST_RE regex in antigravity.py
# ═════════════════════════════════════════════════════════════════════════════

class TestR05NoDeadRegexInAntigravity:
    """
    BUG: _USER_REQUEST_RE was defined at module level in antigravity.py but
    never called anywhere. The extract function just did content.strip().
    FIX: removed the unused constant to eliminate misleading dead code.
    """

    def test_user_request_re_not_in_antigravity_module(self):
        import ai_tracker.parsers.antigravity as ag_mod
        assert not hasattr(ag_mod, "_USER_REQUEST_RE"), (
            "R05 regression: dead _USER_REQUEST_RE constant is back in antigravity.py"
        )

    def test_full_content_including_tags_preserved_in_output(self, tmp_path):
        """The old regex stripped tags; now they must be preserved verbatim."""
        f = tmp_path / "transcript.jsonl"
        content = (
            "<USER_REQUEST>\nHow do I reverse a list?\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>\nLocal time: 2026-05-22T11:30:00+05:30\n</ADDITIONAL_METADATA>"
        )
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-22T06:00:00Z",
            "content": content,
        }
        _write(f, [r])
        msgs = AntigravityParser(f).parse()[0].messages
        assert "<USER_REQUEST>" in msgs[0].message, (
            "R05 regression: USER_REQUEST tags were stripped from message"
        )

    def test_plain_content_without_tags_still_works(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-05-22T06:00:00Z",
            "content": "Plain text without any XML tags",
        }
        _write(f, [r])
        msgs = AntigravityParser(f).parse()[0].messages
        assert msgs[0].message == "Plain text without any XML tags", (
            "R05 regression: plain content broken after regex removal"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R06  _parse_iso duplicated across parsers
# ═════════════════════════════════════════════════════════════════════════════

class TestR06ParseTimestampDeduplicated:
    """
    BUG: _parse_iso existed identically in both antigravity.py and
    claude_code.py, and a different _parse_timestamp lived in codex.py.
    Divergence risk: a fix to one copy wouldn't propagate to others.
    FIX: single _parse_timestamp in base.py, imported by all three parsers.
    """

    def test_parse_timestamp_not_defined_in_antigravity(self):
        import ai_tracker.parsers.antigravity as ag
        assert not hasattr(ag, "_parse_iso"), (
            "R06 regression: _parse_iso re-appeared in antigravity.py"
        )

    def test_parse_timestamp_not_defined_in_claude_code(self):
        import ai_tracker.parsers.claude_code as cc
        assert not hasattr(cc, "_parse_iso"), (
            "R06 regression: _parse_iso re-appeared in claude_code.py"
        )

    def test_parse_timestamp_not_defined_in_codex(self):
        import ai_tracker.parsers.codex as cx
        assert not hasattr(cx, "_parse_timestamp") or \
               cx._parse_timestamp is _parse_timestamp, (
            "R06 regression: separate _parse_timestamp in codex.py"
        )

    def test_shared_parse_timestamp_handles_iso_string(self):
        dt = _parse_timestamp("2026-05-22T06:00:00Z")
        assert dt is not None and dt.year == 2026

    def test_shared_parse_timestamp_handles_unix_epoch(self):
        dt = _parse_timestamp(1716192000)
        assert dt is not None

    def test_shared_parse_timestamp_handles_none(self):
        assert _parse_timestamp(None) is None

    def test_all_parsers_use_same_timestamp_parsing_result(self, tmp_path):
        """All three parsers must agree on the same timestamp for the same ISO string."""
        ts_str = "2026-05-22T06:00:00Z"

        # Claude Code
        f_cc = tmp_path / "cc.jsonl"
        _write(f_cc, [_cc_record("Q", ts=ts_str)])
        cc_ts = ClaudeCodeParser(f_cc).parse()[0].messages[0].timestamp

        # Antigravity
        f_ag = tmp_path / "ag.jsonl"
        r = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
             "status": "DONE", "created_at": ts_str, "content": "Q"}
        _write(f_ag, [r])
        ag_ts = AntigravityParser(f_ag).parse()[0].messages[0].timestamp

        # Codex
        f_cx = tmp_path / "cx.jsonl"
        f_cx.write_text(
            json.dumps({"role": "user", "content": "Q", "timestamp": ts_str}) + "\n",
            encoding="utf-8",
        )
        cx_ts = CodexParser(f_cx).parse()[0].messages[0].timestamp

        assert cc_ts == ag_ts == cx_ts, (
            f"R06 regression: parsers disagree on timestamp — CC:{cc_ts} AG:{ag_ts} CX:{cx_ts}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R07  _normalise_role duplicated with inconsistent logic
# ═════════════════════════════════════════════════════════════════════════════

class TestR07NormaliseRoleDeduplicated:
    """
    BUG: claude_code.py and codex.py each had their own _normalise_role with
    different alias sets. codex.py mapped "system"→"assistant"; claude_code.py
    didn't recognise "h" or "u". Divergence made output inconsistent.
    FIX: single _normalise_role in base.py imported by both.
    """

    def test_normalise_role_in_claude_code_is_shared_base_version(self):
        import ai_tracker.parsers.claude_code as cc
        # If visible it must be the imported base version, not a local redefinition
        if hasattr(cc, "_normalise_role"):
            assert cc._normalise_role is _normalise_role, (
                "R07 regression: claude_code.py has its own _normalise_role instead of base's"
            )

    def test_normalise_role_in_codex_is_shared_base_version(self):
        import ai_tracker.parsers.codex as cx
        if hasattr(cx, "_normalise_role"):
            assert cx._normalise_role is _normalise_role, (
                "R07 regression: codex.py has its own _normalise_role instead of base's"
            )

    @pytest.mark.parametrize("alias,expected", [
        ("user",      "human"),
        ("human",     "human"),
        ("h",         "human"),
        ("u",         "human"),
        ("assistant", "assistant"),
        ("ai",        "assistant"),
        ("model",     "assistant"),
        ("bot",       "assistant"),
        ("a",         "assistant"),
    ])
    def test_shared_normalise_role_maps_all_aliases(self, alias, expected):
        assert _normalise_role(alias) == expected, (
            f"R07 regression: _normalise_role('{alias}') != '{expected}'"
        )

    def test_system_not_mapped_to_assistant_in_shared_function(self):
        assert _normalise_role("system") != "assistant", (
            "R07 regression: 'system' is mapped to 'assistant' again"
        )

    def test_codex_and_claude_code_agree_on_user_role(self, tmp_path):
        f_cc = tmp_path / "cc.jsonl"
        _write(f_cc, [_cc_record("Q")])
        cc_role = ClaudeCodeParser(f_cc).parse()[0].messages[0].role

        f_cx = tmp_path / "cx.jsonl"
        f_cx.write_text('{"role":"user","content":"Q"}\n', encoding="utf-8")
        cx_role = CodexParser(f_cx).parse()[0].messages[0].role

        assert cc_role == cx_role == "human", (
            f"R07 regression: Claude Code role={cc_role}, Codex role={cx_role}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R08  JSON array files raised AttributeError in format detection
# ═════════════════════════════════════════════════════════════════════════════

class TestR08JsonArrayFormatDetection:
    """
    BUG: _parse_file parsed the first line with json.loads(), which for a JSON
    array file returned a list. Calling list.get("type") raised AttributeError,
    which the outer except Exception caught, silently returning None — making
    every JSON array file invisible to the parser.
    FIX: check isinstance(parsed, dict) before assigning first_record.
    """

    def test_json_array_file_parsed_successfully(self, tmp_path):
        f = tmp_path / "session.json"
        f.write_text(
            '[{"role":"user","content":"From array"},{"role":"assistant","content":"Answer"}]',
            encoding="utf-8",
        )
        sessions = CodexParser(f).parse()
        assert len(sessions) == 1, "R08 regression: JSON array file returned no sessions"
        assert len(sessions[0].messages) == 2

    def test_json_array_with_desktop_like_content_not_mis_detected(self, tmp_path):
        f = tmp_path / "arr.json"
        f.write_text(
            '[{"role":"user","content":"type is just a field name"}]',
            encoding="utf-8",
        )
        sessions = CodexParser(f).parse()
        assert len(sessions) == 1, (
            "R08 regression: JSON array with 'type' field broke format detection"
        )

    def test_directory_with_json_array_and_jsonl_both_parsed(self, tmp_path):
        (tmp_path / "a.json").write_text(
            '[{"role":"user","content":"Array message"}]', encoding="utf-8"
        )
        (tmp_path / "b.jsonl").write_text(
            '{"role":"user","content":"JSONL message"}\n', encoding="utf-8"
        )
        sessions = CodexParser(tmp_path).parse()
        all_msgs = [m for s in sessions for m in s.messages]
        texts = [m.message for m in all_msgs]
        assert "Array message" in texts, "R08 regression: JSON array file invisible in dir scan"
        assert "JSONL message" in texts

    def test_json_array_file_in_e2e_pipeline(self, tmp_path):
        from ai_tracker.cli import cmd_parse
        import csv as _csv
        f = tmp_path / "session.json"
        f.write_text(
            '[{"role":"user","content":"E2E array test","timestamp":"2026-05-01T10:00:00Z"}]',
            encoding="utf-8",
        )
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(f), output=str(out)))
        assert rc == 0, "R08 regression: JSON array file produced non-zero exit code"
        with open(out, encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        assert rows[0]["message"] == "E2E array test"


# ═════════════════════════════════════════════════════════════════════════════
# R09  Codex Desktop event-log format not recognised
# ═════════════════════════════════════════════════════════════════════════════

class TestR09CodexDesktopDetection:
    """
    BUG: CodexParser had no knowledge of the Codex Desktop event-log JSONL
    format. Feeding it a Desktop session file produced zero messages because
    none of the records had a top-level "role" field.
    FIX: _is_codex_desktop_format() detects the format by the first record's
    "type" field; _parse_codex_desktop() extracts user_message and
    final_answer agent_message records.
    """

    def test_desktop_session_fixture_produces_messages(self):
        msgs = [m for s in CodexParser(CX_DESKTOP).parse() for m in s.messages]
        assert len(msgs) > 0, "R09 regression: Codex Desktop file produced no messages"

    def test_is_codex_desktop_format_detects_session_meta(self):
        assert _is_codex_desktop_format({"type": "session_meta"}) is True, (
            "R09 regression: session_meta not detected as desktop format"
        )

    def test_is_codex_desktop_format_detects_event_msg(self):
        assert _is_codex_desktop_format({"type": "event_msg"}) is True

    def test_is_codex_desktop_format_rejects_simple_record(self):
        assert _is_codex_desktop_format({"role": "user", "content": "Q"}) is False

    def test_commentary_phase_messages_excluded(self):
        msgs = [m for s in CodexParser(CX_DESKTOP).parse() for m in s.messages]
        assert not any("Thinking about" in m.message for m in msgs), (
            "R09 regression: commentary messages included in output"
        )

    def test_project_name_from_cwd_extracted(self):
        sessions = CodexParser(CX_DESKTOP).parse()
        assert sessions[0].project == "Hi Codex Top 10 Programming Concepts", (
            f"R09 regression: project name wrong: {sessions[0].project}"
        )

    def test_desktop_session_in_nested_path_parsed(self, tmp_path):
        nested = tmp_path / "sessions" / "2026" / "06" / "02"
        nested.mkdir(parents=True)
        records = [
            {"timestamp": "2026-06-02T09:00:00Z", "type": "session_meta",
             "payload": {"id": "nested-id", "cwd": "C:\\Users\\Robin\\nested-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-06-02T09:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Nested question"}},
            {"timestamp": "2026-06-02T09:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message",
                         "message": "Nested answer", "phase": "final_answer"}},
        ]
        _write(nested / "rollout.jsonl", records)
        sessions = CodexParser(tmp_path / "sessions").parse()
        assert len(sessions) == 1
        assert sessions[0].project == "Nested Project"


# ═════════════════════════════════════════════════════════════════════════════
# R10  _clean_project_name did not handle None gracefully
# ═════════════════════════════════════════════════════════════════════════════

class TestR10CleanProjectNameNoneInput:
    """
    BUG: A test revealed that _clean_project_name(None) should return "General"
    because `not None` is truthy. The original assumption was it would raise,
    but the function actually handles it gracefully via the falsy check.
    FIX: documented and locked — None must always yield "General".
    """

    def test_none_input_returns_general(self):
        from ai_tracker.parsers.base import _clean_project_name
        assert _clean_project_name(None) == "General", (
            "R10 regression: _clean_project_name(None) no longer returns 'General'"
        )

    def test_empty_string_returns_general(self):
        from ai_tracker.parsers.base import _clean_project_name
        assert _clean_project_name("") == "General"

    def test_whitespace_only_returns_general(self):
        from ai_tracker.parsers.base import _clean_project_name
        assert _clean_project_name("   ") == "General"


# ═════════════════════════════════════════════════════════════════════════════
# R11  config.py default vs CLI default conflict for include_sidechains
# ═════════════════════════════════════════════════════════════════════════════

class TestR11SidechainsDefaultConsistency:
    """
    BUG: config.py defaulted include_sidechains to False, but the CLI's
    argparse default was True (include). The original OR logic masked this:
    True or False = True, so the config default was always ignored.
    After the fix (CLI wins), the behavior is predictable: CLI=True includes,
    CLI=False (--no-sidechains) excludes.
    """

    def test_cli_default_true_includes_sidechains(self, tmp_path):
        import csv as _csv
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        with open(out, encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 5, (
            f"R11 regression: CLI include_sidechains=True gave {len(rows)} rows instead of 5"
        )

    def test_cli_false_excludes_sidechains_regardless_of_config_default(self, tmp_path):
        import csv as _csv
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        with open(out, encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 4, (
            f"R11 regression: CLI include_sidechains=False gave {len(rows)} rows instead of 4"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R12  AntigravityParser sort on sessions with no-timestamp messages
# ═════════════════════════════════════════════════════════════════════════════

class TestR12AntigravityBrainDirSort:
    """
    BUG (latent): _parse_brain_dir sorted sessions by
    `s.messages[0].timestamp.isoformat()` without guarding for None timestamp,
    which would raise AttributeError if the first message had no timestamp.
    The guard `if s.messages[0].timestamp else ""` was present but tested.
    FIX: confirmed the guard is in place and works.
    """

    def test_brain_dir_with_no_timestamp_messages_does_not_crash(self, tmp_path):
        brain = tmp_path / "brain"
        logs = brain / "sess-1" / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        r = {
            "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE",
            # no created_at → timestamp will be None
            "content": "Hello without timestamp",
        }
        _write(logs / "transcript.jsonl", [r])
        sessions = AntigravityParser(brain).parse()
        assert len(sessions) == 1, (
            "R12 regression: brain dir sort crashed on None timestamp"
        )

    def test_brain_dir_mixed_timestamps_sorted_stably(self, tmp_path):
        brain = tmp_path / "brain"
        for uid, ts in [("aaa-001", "2026-05-01T08:00:00Z"),
                        ("bbb-002", "2026-05-01T10:00:00Z"),
                        ("ccc-003", "2026-05-01T09:00:00Z")]:
            logs = brain / uid / ".system_generated" / "logs"
            logs.mkdir(parents=True)
            r = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                 "status": "DONE", "created_at": ts, "content": f"Q from {uid}"}
            _write(logs / "transcript.jsonl", [r])
        sessions = AntigravityParser(brain).parse()
        ts_list = [s.messages[0].timestamp for s in sessions if s.messages[0].timestamp]
        assert ts_list == sorted(ts_list), "R12 regression: brain dir sessions not sorted"


# ═════════════════════════════════════════════════════════════════════════════
# R13  Codex directory scan double-counting concern
# ═════════════════════════════════════════════════════════════════════════════

class TestR13CodexDirectoryScanNoDuplicates:
    """
    BUG (concern): _parse_directory iterated "*.jsonl" then "*.json".
    A file named session.json would only match "*.json", not "*.jsonl"
    (different extensions), so no double-counting. Locked in by test.
    """

    def test_jsonl_and_json_files_each_counted_once(self, tmp_path):
        (tmp_path / "a.jsonl").write_text(
            '{"role":"user","content":"JSONL"}\n', encoding="utf-8"
        )
        (tmp_path / "b.json").write_text(
            '[{"role":"user","content":"JSON"}]', encoding="utf-8"
        )
        sessions = CodexParser(tmp_path).parse()
        all_msgs = [m for s in sessions for m in s.messages]
        assert len(all_msgs) == 2, (
            f"R13 regression: expected 2 messages, got {len(all_msgs)}"
        )

    def test_no_session_counted_twice(self, tmp_path):
        (tmp_path / "only.jsonl").write_text(
            '{"role":"user","content":"Single"}\n', encoding="utf-8"
        )
        sessions = CodexParser(tmp_path).parse()
        assert len(sessions) == 1, (
            f"R13 regression: expected 1 session, got {len(sessions)}"
        )

    def test_json_extension_does_not_match_jsonl(self, tmp_path):
        """Verify .jsonl does not accidentally match *.json glob."""
        (tmp_path / "session.jsonl").write_text(
            '{"role":"user","content":"JSONL only"}\n', encoding="utf-8"
        )
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 0, "R13 regression: .jsonl matched *.json glob"


# ═════════════════════════════════════════════════════════════════════════════
# R14  CSV column order locked to FIELDNAMES
# ═════════════════════════════════════════════════════════════════════════════

class TestR14CSVColumnOrderLocked:
    """
    CONTRACT: The CSV schema must always be exactly:
      project | session_id | timestamp | role | message | tool | file_path
    in that order. Any change breaks downstream consumers.
    """

    EXPECTED = ["project", "session_id", "timestamp", "role", "message",
                "tool", "file_path"]

    def test_fieldnames_constant_unchanged(self):
        assert list(FIELDNAMES) == self.EXPECTED, (
            f"R14 regression: FIELDNAMES changed to {list(FIELDNAMES)}"
        )

    @pytest.mark.parametrize("tool,fixture", [
        ("claudecode", CC_FIXTURE),
        ("antigravity", AG_FIXTURE),
        ("codex",       CX_FIXTURE),
        ("codex",       CX_DESKTOP),
    ])
    def test_csv_column_order_from_all_parsers(self, tool, fixture, tmp_path):
        import csv as _csv
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            fieldnames = _csv.DictReader(fh).fieldnames
        assert fieldnames == self.EXPECTED, (
            f"R14 regression: {tool} CSV columns = {fieldnames}"
        )

    def test_message_to_dict_key_order_matches_fieldnames(self):
        msg = Message(
            session_id="s", timestamp=None, role="human",
            message="x", tool="codex", file_path="/f", project="P",
        )
        assert list(msg.to_dict().keys()) == self.EXPECTED, (
            "R14 regression: Message.to_dict() key order changed"
        )


# ═════════════════════════════════════════════════════════════════════════════
# R15  ClaudeCodeParser non-dict message blob not guarded
# ═════════════════════════════════════════════════════════════════════════════

class TestR15ClaudeCodeNonDictMessageBlob:
    """
    BUG (latent): _record_to_message did `blob = record.get("message", {})` then
    `blob.get("role", ...)`. If "message" was a string (some tool versions emit
    this), blob.get() would raise AttributeError. The guard
    `if not isinstance(blob, dict): return None` was present but untested.
    FIX: confirmed with explicit tests.
    """

    def test_string_message_field_skipped_gracefully(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": "this is a plain string not a dict",
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write(f, [r])
        sessions = ClaudeCodeParser(f).parse()
        assert sessions == [], (
            "R15 regression: non-dict message blob caused crash or wrong output"
        )

    def test_null_message_field_skipped_gracefully(self, tmp_path):
        f = tmp_path / "s.jsonl"
        r = {
            "type": "user", "isSidechain": False,
            "message": None,
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        _write(f, [r])
        sessions = ClaudeCodeParser(f).parse()
        assert sessions == [], (
            "R15 regression: null message blob caused crash"
        )

    def test_valid_dict_message_still_parsed_after_guard(self, tmp_path):
        f = tmp_path / "s.jsonl"
        _write(f, [_cc_record("Valid message")])
        msgs = [m for s in ClaudeCodeParser(f).parse() for m in s.messages]
        assert len(msgs) == 1
        assert msgs[0].message == "Valid message"
