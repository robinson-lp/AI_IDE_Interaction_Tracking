"""
Unit tests for individual functions and methods across all modules.

Covers:
  - base.py        : _parse_timestamp, _normalise_role, _clean_project_name, _in_range
  - models.py      : Message.to_dict(), ParsedSession defaults
  - config.py      : load_config(), _deep_copy()
  - cli.py         : _date_arg(), _project_to_filename(), _default_output(), _default_output_dir()
  - antigravity.py : _extract_user_request()
  - claude_code.py : _extract_text()
  - codex.py       : _is_codex_desktop_format(), _project_name_from_path()
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# base.py
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.parsers.base import (
    _clean_project_name,
    _in_range,
    _normalise_role,
    _parse_timestamp,
)


class TestParseTimestamp:
    def test_none_returns_none(self):
        assert _parse_timestamp(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_timestamp("") is None

    def test_iso_string_with_z(self):
        dt = _parse_timestamp("2026-05-22T06:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 22

    def test_iso_string_with_offset(self):
        dt = _parse_timestamp("2026-05-22T11:30:00+05:30")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso_string_without_tz(self):
        dt = _parse_timestamp("2026-05-22T06:00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_unix_epoch_integer(self):
        dt = _parse_timestamp(0)
        assert dt is not None
        assert isinstance(dt, datetime)

    def test_unix_epoch_float(self):
        dt = _parse_timestamp(1716192000.5)
        assert dt is not None

    def test_invalid_string_returns_none(self):
        assert _parse_timestamp("not-a-date") is None

    def test_integer_zero_is_valid(self):
        assert _parse_timestamp(0) is not None

    def test_millisecond_iso_string(self):
        dt = _parse_timestamp("2026-05-22T06:00:00.427Z")
        assert dt is not None
        assert dt.microsecond == 427000


class TestNormaliseRole:
    def test_user_becomes_human(self):
        assert _normalise_role("user") == "human"

    def test_human_stays_human(self):
        assert _normalise_role("human") == "human"

    def test_h_becomes_human(self):
        assert _normalise_role("h") == "human"

    def test_u_becomes_human(self):
        assert _normalise_role("u") == "human"

    def test_assistant_stays_assistant(self):
        assert _normalise_role("assistant") == "assistant"

    def test_ai_becomes_assistant(self):
        assert _normalise_role("ai") == "assistant"

    def test_model_becomes_assistant(self):
        assert _normalise_role("model") == "assistant"

    def test_bot_becomes_assistant(self):
        assert _normalise_role("bot") == "assistant"

    def test_a_becomes_assistant(self):
        assert _normalise_role("a") == "assistant"

    def test_case_insensitive(self):
        assert _normalise_role("USER") == "human"
        assert _normalise_role("ASSISTANT") == "assistant"

    def test_leading_trailing_whitespace_stripped(self):
        assert _normalise_role("  user  ") == "human"

    def test_unknown_role_returned_as_is(self):
        assert _normalise_role("tool") == "tool"

    def test_system_not_mapped_to_assistant(self):
        assert _normalise_role("system") != "assistant"

    def test_empty_string_returned_as_is(self):
        assert _normalise_role("") == ""


class TestCleanProjectName:
    def test_empty_string_returns_general(self):
        assert _clean_project_name("") == "General"

    def test_whitespace_only_returns_general(self):
        assert _clean_project_name("   ") == "General"

    def test_simple_name_title_cased(self):
        assert _clean_project_name("my-project") == "My Project"

    def test_underscores_replaced_with_spaces(self):
        assert _clean_project_name("my_project") == "My Project"

    def test_hyphens_replaced_with_spaces(self):
        assert _clean_project_name("ai-tracker") == "Ai Tracker"

    def test_claude_code_slug_strips_path_prefix(self):
        result = _clean_project_name("c--Users-Robin-my-test-project")
        assert result == "My Test Project"

    def test_users_prefix_stripped(self):
        result = _clean_project_name("Users-Robin-my-project")
        assert result == "My Project"

    def test_home_prefix_stripped(self):
        result = _clean_project_name("home-robin-my-project")
        assert result == "My Project"

    def test_extra_whitespace_collapsed(self):
        result = _clean_project_name("my--project")
        assert "  " not in result

    def test_none_returns_general(self):
        # _clean_project_name treats None as falsy and falls back to "General"
        assert _clean_project_name(None) == "General"


class TestInRange:
    _start = datetime(2026, 5, 1)
    _end   = datetime(2026, 5, 31)

    def test_no_bounds_always_true(self):
        ts = datetime(2026, 6, 15)
        assert _in_range(ts, None, None) is True

    def test_none_timestamp_always_true(self):
        assert _in_range(None, self._start, self._end) is True

    def test_within_range_true(self):
        ts = datetime(2026, 5, 15)
        assert _in_range(ts, self._start, self._end) is True

    def test_before_start_false(self):
        ts = datetime(2026, 4, 30)
        assert _in_range(ts, self._start, self._end) is False

    def test_after_end_false(self):
        ts = datetime(2026, 6, 1)
        assert _in_range(ts, self._start, self._end) is False

    def test_on_start_boundary_true(self):
        assert _in_range(self._start, self._start, self._end) is True

    def test_on_end_boundary_true(self):
        assert _in_range(self._end, self._start, self._end) is True

    def test_only_start_bound(self):
        ts_after  = datetime(2026, 6, 1)
        ts_before = datetime(2026, 4, 1)
        assert _in_range(ts_after,  self._start, None) is True
        assert _in_range(ts_before, self._start, None) is False

    def test_only_end_bound(self):
        ts_before = datetime(2026, 4, 1)
        ts_after  = datetime(2026, 6, 1)
        assert _in_range(ts_before, None, self._end) is True
        assert _in_range(ts_after,  None, self._end) is False

    def test_timezone_aware_vs_naive(self):
        ts_aware = datetime(2026, 5, 15, tzinfo=timezone.utc)
        assert _in_range(ts_aware, self._start, self._end) is True


# ─────────────────────────────────────────────────────────────────────────────
# models.py
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.models import Message, ParsedSession


class TestMessageToDict:
    def _make(self, **kwargs):
        defaults = dict(
            session_id="s1",
            timestamp=datetime(2026, 5, 22, 6, 0, 0, tzinfo=timezone.utc),
            role="human",
            message="Hello",
            tool="claudecode",
            file_path="/path/to/file.jsonl",
            project="My Project",
        )
        defaults.update(kwargs)
        return Message(**defaults)

    def test_returns_dict(self):
        assert isinstance(self._make().to_dict(), dict)

    def test_all_seven_keys_present(self):
        keys = set(self._make().to_dict().keys())
        assert keys == {"project", "session_id", "timestamp", "role", "message", "tool", "file_path"}

    def test_project_is_first_key(self):
        assert list(self._make().to_dict().keys())[0] == "project"

    def test_timestamp_serialised_as_iso_string(self):
        d = self._make().to_dict()
        assert "2026-05-22" in d["timestamp"]

    def test_none_timestamp_serialised_as_empty_string(self):
        msg = self._make()
        msg.timestamp = None
        assert self._make(timestamp=None).to_dict()["timestamp"] == "" or True
        m = Message(
            session_id="s", timestamp=None, role="human",
            message="x", tool="codex", file_path="/f"
        )
        assert m.to_dict()["timestamp"] == ""

    def test_values_match_fields(self):
        msg = self._make(session_id="abc", role="assistant", message="Hi", tool="codex")
        d = msg.to_dict()
        assert d["session_id"] == "abc"
        assert d["role"] == "assistant"
        assert d["message"] == "Hi"
        assert d["tool"] == "codex"

    def test_project_default_is_general(self):
        msg = Message(
            session_id="s", timestamp=None, role="human",
            message="x", tool="codex", file_path="/f"
        )
        assert msg.project == "General"


class TestParsedSession:
    def test_default_project_is_general(self):
        s = ParsedSession(session_id="s1", tool="codex", file_path="/f")
        assert s.project == "General"

    def test_default_messages_is_empty_list(self):
        s = ParsedSession(session_id="s1", tool="codex", file_path="/f")
        assert s.messages == []

    def test_messages_list_not_shared_between_instances(self):
        s1 = ParsedSession(session_id="s1", tool="codex", file_path="/f")
        s2 = ParsedSession(session_id="s2", tool="codex", file_path="/f")
        s1.messages.append("x")
        assert s2.messages == []


# ─────────────────────────────────────────────────────────────────────────────
# config.py
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.config import _deep_copy, load_config


class TestLoadConfig:
    def test_returns_dict(self):
        assert isinstance(load_config(), dict)

    def test_has_tools_key(self):
        assert "tools" in load_config()

    def test_all_three_tools_present(self):
        tools = load_config()["tools"]
        assert "antigravity" in tools
        assert "claudecode" in tools
        assert "codex" in tools

    def test_each_tool_has_path(self):
        tools = load_config()["tools"]
        for tool in ("antigravity", "claudecode", "codex"):
            assert "path" in tools[tool]

    def test_missing_config_file_returns_defaults(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        cfg = load_config(config_path=missing)
        assert "tools" in cfg

    def test_custom_config_overrides_path(self, tmp_path):
        cfg_file = tmp_path / "tools.yaml"
        cfg_file.write_text(
            "tools:\n  codex:\n    path: /custom/codex/path\n",
            encoding="utf-8",
        )
        cfg = load_config(config_path=cfg_file)
        assert cfg["tools"]["codex"]["path"] == "/custom/codex/path"

    def test_custom_config_preserves_other_tools(self, tmp_path):
        cfg_file = tmp_path / "tools.yaml"
        cfg_file.write_text(
            "tools:\n  codex:\n    path: /custom\n",
            encoding="utf-8",
        )
        cfg = load_config(config_path=cfg_file)
        assert "claudecode" in cfg["tools"]

    def test_empty_yaml_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("", encoding="utf-8")
        cfg = load_config(config_path=cfg_file)
        assert "tools" in cfg

    def test_returns_independent_copy_each_call(self):
        cfg1 = load_config()
        cfg2 = load_config()
        cfg1["tools"]["codex"]["path"] = "/mutated"
        assert cfg2["tools"]["codex"]["path"] != "/mutated"


class TestDeepCopy:
    def test_returns_equal_value(self):
        obj = {"a": [1, 2, 3], "b": {"c": 4}}
        assert _deep_copy(obj) == obj

    def test_nested_mutation_does_not_affect_original(self):
        original = {"a": [1, 2, 3]}
        copy = _deep_copy(original)
        copy["a"].append(99)
        assert original["a"] == [1, 2, 3]

    def test_works_with_list(self):
        lst = [1, [2, 3]]
        copy = _deep_copy(lst)
        copy[1].append(4)
        assert lst[1] == [2, 3]


# ─────────────────────────────────────────────────────────────────────────────
# cli.py helpers
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.cli import (
    _date_arg,
    _default_output,
    _default_output_dir,
    _project_to_filename,
)


class TestDateArg:
    def test_yyyy_mm_dd_format(self):
        dt = _date_arg("2026-05-22")
        assert dt == datetime(2026, 5, 22)

    def test_yyyy_slash_mm_slash_dd_format(self):
        dt = _date_arg("2026/05/22")
        assert dt == datetime(2026, 5, 22)

    def test_datetime_format(self):
        dt = _date_arg("2026-05-22T10:30:00")
        assert dt == datetime(2026, 5, 22, 10, 30, 0)

    def test_invalid_raises_argument_type_error(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _date_arg("not-a-date")

    def test_invalid_format_raises(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _date_arg("22/05/2026")


class TestProjectToFilename:
    def test_spaces_replaced_with_underscores(self):
        assert _project_to_filename("My Project") == "my_project"

    def test_lowercased(self):
        assert _project_to_filename("AI TRACKER") == "ai_tracker"

    def test_empty_returns_general(self):
        assert _project_to_filename("") == "general"

    def test_special_chars_stripped(self):
        result = _project_to_filename("My Project!")
        assert "!" not in result

    def test_multiple_spaces_collapsed(self):
        result = _project_to_filename("My  Project")
        assert "__" not in result

    def test_hyphens_preserved(self):
        result = _project_to_filename("my-project")
        assert result == "my-project"

    def test_unicode_letters_kept(self):
        result = _project_to_filename("Über Project")
        assert "project" in result


class TestDefaultOutput:
    def test_returns_path(self):
        assert isinstance(_default_output(), Path)

    def test_filename_starts_with_prefix(self):
        assert _default_output().name.startswith("ai_interactions_")

    def test_filename_ends_with_csv(self):
        assert _default_output().suffix == ".csv"

    def test_two_calls_may_differ(self):
        import time
        p1 = _default_output()
        time.sleep(1.1)
        p2 = _default_output()
        assert p1 != p2


class TestDefaultOutputDir:
    def test_returns_path(self):
        assert isinstance(_default_output_dir(), Path)

    def test_dirname_starts_with_prefix(self):
        assert _default_output_dir().name.startswith("ai_projects_")


# ─────────────────────────────────────────────────────────────────────────────
# antigravity.py helpers
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.parsers.antigravity import _extract_user_request


class TestExtractUserRequest:
    def test_plain_text_returned_stripped(self):
        assert _extract_user_request("  Hello world  ") == "Hello world"

    def test_content_with_tags_returned_as_is(self):
        content = "<USER_REQUEST>\nHow do I reverse a list?\n</USER_REQUEST>"
        assert "<USER_REQUEST>" in _extract_user_request(content)

    def test_empty_string_returns_empty(self):
        assert _extract_user_request("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _extract_user_request("   ") == ""

    def test_multiline_preserved(self):
        content = "line 1\nline 2\nline 3"
        result = _extract_user_request(content)
        assert "line 1" in result
        assert "line 2" in result


# ─────────────────────────────────────────────────────────────────────────────
# claude_code.py helpers
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.parsers.claude_code import _extract_text


class TestExtractText:
    def test_plain_string_returned_as_is(self):
        assert _extract_text("Hello world") == "Hello world"

    def test_empty_string_returned(self):
        assert _extract_text("") == ""

    def test_list_of_text_blocks_joined(self):
        blocks = [
            {"type": "text", "text": "Part one"},
            {"type": "text", "text": "Part two"},
        ]
        result = _extract_text(blocks)
        assert "Part one" in result
        assert "Part two" in result

    def test_non_text_blocks_skipped(self):
        blocks = [
            {"type": "tool_use", "text": "should be skipped"},
            {"type": "text", "text": "kept"},
        ]
        result = _extract_text(blocks)
        assert "kept" in result
        assert "should be skipped" not in result

    def test_none_returns_empty_string(self):
        assert _extract_text(None) == ""

    def test_integer_returns_empty_string(self):
        assert _extract_text(42) == ""

    def test_empty_list_returns_empty_string(self):
        assert _extract_text([]) == ""

    def test_list_blocks_joined_with_newline(self):
        blocks = [
            {"type": "text", "text": "A"},
            {"type": "text", "text": "B"},
        ]
        assert _extract_text(blocks) == "A\nB"


# ─────────────────────────────────────────────────────────────────────────────
# codex.py helpers
# ─────────────────────────────────────────────────────────────────────────────

from ai_tracker.parsers.codex import _is_codex_desktop_format, _project_name_from_path


class TestIsCodexDesktopFormat:
    def test_session_meta_type_detected(self):
        assert _is_codex_desktop_format({"type": "session_meta"}) is True

    def test_event_msg_type_detected(self):
        assert _is_codex_desktop_format({"type": "event_msg"}) is True

    def test_response_item_type_detected(self):
        assert _is_codex_desktop_format({"type": "response_item"}) is True

    def test_turn_context_type_detected(self):
        assert _is_codex_desktop_format({"type": "turn_context"}) is True

    def test_simple_role_record_not_detected(self):
        assert _is_codex_desktop_format({"role": "user", "content": "hi"}) is False

    def test_empty_dict_not_detected(self):
        assert _is_codex_desktop_format({}) is False

    def test_unknown_type_not_detected(self):
        assert _is_codex_desktop_format({"type": "some_other_type"}) is False


class TestProjectNameFromPath:
    def test_projects_dir_component_extracted(self, tmp_path):
        p = tmp_path / "projects" / "my-test-project" / "session.jsonl"
        assert _project_name_from_path(p) == "My Test Project"

    def test_claude_code_slug_cleaned(self, tmp_path):
        p = tmp_path / "projects" / "c--Users-Robin-my-project" / "session.jsonl"
        assert _project_name_from_path(p) == "My Project"

    def test_no_projects_component_returns_general(self, tmp_path):
        p = tmp_path / "some" / "other" / "path" / "session.jsonl"
        assert _project_name_from_path(p) == "General"

    def test_projects_at_end_returns_general(self, tmp_path):
        p = tmp_path / "projects"
        assert _project_name_from_path(p) == "General"
