"""Tests for the Antigravity IDE session parser (transcript.jsonl / overview.txt)."""

import json
from pathlib import Path

import pytest

from ai_tracker.parsers.antigravity import AntigravityParser, _project_name_from_antigravity_path

FIXTURES = Path(__file__).parent / "fixtures"
TRANSCRIPT = FIXTURES / "antigravity_transcript.jsonl"


# ─────────────────────────────────────────────────────────────────────────────
# Single-file parsing (transcript.jsonl passed directly)
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleFileMode:
    def _parse(self):
        return AntigravityParser(TRANSCRIPT).parse()

    def test_returns_one_session(self):
        assert len(self._parse()) == 1

    def test_tool_name(self):
        assert self._parse()[0].tool == "antigravity"

    def test_extracts_two_human_messages(self):
        msgs = self._parse()[0].messages
        human = [m for m in msgs if m.role == "human"]
        assert len(human) == 2

    def test_extracts_three_ai_assistant_messages(self):
        # 2 with thinking text + 1 tool-call-only PLANNER_RESPONSE
        msgs = self._parse()[0].messages
        ai = [m for m in msgs if m.role == "assistant"]
        assert len(ai) == 3

    def test_total_message_count(self):
        # 2 human + 3 assistant (2 thinking + 1 tool-call) + 1 tool result = 6
        # SYSTEM records (CONVERSATION_HISTORY, KNOWLEDGE_ARTIFACTS) are still skipped
        assert len(self._parse()[0].messages) == 6

    def test_human_request_text_extracted(self):
        msgs = self._parse()[0].messages
        human_texts = [m.message for m in msgs if m.role == "human"]
        assert any("reverse a list" in t for t in human_texts)

    def test_user_request_tags_stripped(self):
        msgs = self._parse()[0].messages
        # <USER_REQUEST> wrapper tags must be stripped — only the inner text is kept
        human_msgs = [m for m in msgs if m.role == "human"]
        assert human_msgs, "Expected at least one human message"
        assert not any("<USER_REQUEST>" in m.message for m in human_msgs)
        assert not any("</USER_REQUEST>" in m.message for m in human_msgs)

    def test_ai_thinking_text_extracted(self):
        msgs = self._parse()[0].messages
        ai_texts = [m.message for m in msgs if m.role == "assistant"]
        assert any("[::-1]" in t for t in ai_texts)

    def test_tool_call_planner_response_captured(self):
        # step_index 4 has tool_calls but no thinking — must be captured as assistant
        msgs = self._parse()[0].messages
        ai_texts = [m.message for m in msgs if m.role == "assistant"]
        assert any("list_dir" in t for t in ai_texts)

    def test_tool_result_records_captured(self):
        # step_index 5 is a LIST_DIRECTORY result — must appear with role="tool"
        msgs = self._parse()[0].messages
        tool_msgs = [m for m in msgs if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "files found" in tool_msgs[0].message

    def test_system_records_skipped(self):
        # CONVERSATION_HISTORY and KNOWLEDGE_ARTIFACTS must not appear
        msgs = self._parse()[0].messages
        for m in msgs:
            assert "CONVERSATION_HISTORY" not in m.message

    def test_timestamps_parsed(self):
        msgs = self._parse()[0].messages
        assert all(m.timestamp is not None for m in msgs)

    def test_file_path_recorded(self):
        msgs = self._parse()[0].messages
        assert all("antigravity_transcript" in m.file_path for m in msgs)


# ─────────────────────────────────────────────────────────────────────────────
# Brain directory scanning (session UUID subdirectories)
# ─────────────────────────────────────────────────────────────────────────────

class TestBrainDirectoryMode:
    def _make_brain(self, tmp_path: Path, sessions: dict) -> Path:
        """Build a fake brain directory with one session folder per UUID."""
        brain = tmp_path / "brain"
        for session_id, filename in sessions.items():
            logs = brain / session_id / ".system_generated" / "logs"
            logs.mkdir(parents=True)
            (logs / filename).write_text(
                TRANSCRIPT.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return brain

    def test_scans_all_session_dirs(self, tmp_path):
        brain = self._make_brain(tmp_path, {
            "aaaa0000-0000-0000-0000-000000000001": "transcript.jsonl",
            "bbbb0000-0000-0000-0000-000000000002": "transcript.jsonl",
        })
        sessions = AntigravityParser(brain).parse()
        assert len(sessions) == 2

    def test_session_id_from_dir_name(self, tmp_path):
        brain = self._make_brain(tmp_path, {
            "cccc0000-0000-0000-0000-000000000003": "transcript.jsonl",
        })
        session = AntigravityParser(brain).parse()[0]
        assert session.session_id == "cccc0000-0000-0000-0000-000000000003"

    def test_accepts_overview_txt_filename(self, tmp_path):
        brain = self._make_brain(tmp_path, {
            "dddd0000-0000-0000-0000-000000000004": "overview.txt",
        })
        sessions = AntigravityParser(brain).parse()
        assert len(sessions) == 1
        assert len(sessions[0].messages) == 6

    def test_skips_dirs_with_no_log_file(self, tmp_path):
        brain = tmp_path / "brain"
        empty_session = brain / "eeee0000-0000-0000-0000-000000000005"
        empty_session.mkdir(parents=True)
        sessions = AntigravityParser(brain).parse()
        assert sessions == []

    def test_empty_brain_dir_returns_no_sessions(self, tmp_path):
        brain = tmp_path / "brain"
        brain.mkdir()
        sessions = AntigravityParser(brain).parse()
        assert sessions == []


# ─────────────────────────────────────────────────────────────────────────────
# Real files on disk
# ─────────────────────────────────────────────────────────────────────────────

class TestRealAntigravityData:
    REAL_BRAIN = Path.home() / ".gemini" / "antigravity-ide" / "brain"

    def test_real_brain_dir_found(self):
        assert self.REAL_BRAIN.exists(), (
            f"Antigravity IDE brain dir not found: {self.REAL_BRAIN}"
        )

    def test_real_sessions_parse_without_error(self):
        if not self.REAL_BRAIN.exists():
            pytest.skip("Antigravity IDE not installed")
        sessions = AntigravityParser(self.REAL_BRAIN).parse()
        assert len(sessions) > 0

    def test_real_messages_have_human_role(self):
        if not self.REAL_BRAIN.exists():
            pytest.skip("Antigravity IDE not installed")
        sessions = AntigravityParser(self.REAL_BRAIN).parse()
        all_msgs = [m for s in sessions for m in s.messages]
        human_msgs = [m for m in all_msgs if m.role == "human"]
        assert len(human_msgs) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            AntigravityParser(tmp_path / "nonexistent").parse()

    def test_no_user_request_tag_falls_back_to_full_content(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        f.write_text(
            json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-22T06:00:00Z",
                "content": "Plain text prompt without tags",
            }) + "\n",
            encoding="utf-8",
        )
        session = AntigravityParser(f, tool_name="antigravity").parse()
        assert session[0].messages[0].message == "Plain text prompt without tags"

    def test_empty_transcript_returns_no_sessions(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        f.write_text("", encoding="utf-8")
        assert AntigravityParser(f).parse() == []

    def test_extracts_project_name_from_user_request_metadata(self, tmp_path):
        f = tmp_path / "transcript.jsonl"
        f.write_text(
            json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-22T06:00:00Z",
                "content": "<USER_REQUEST>\nHow do I reverse a list?\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nActive Document: c:\\Users\\Robin\\my-web-backend-project\\app.py\n</ADDITIONAL_METADATA>",
            }) + "\n",
            encoding="utf-8",
        )
        sessions = AntigravityParser(f).parse()
        assert len(sessions) == 1
        assert sessions[0].project == "My Web Backend Project"
        assert sessions[0].messages[0].project == "My Web Backend Project"


# ─────────────────────────────────────────────────────────────────────────────
# Path-based project name fallback (_project_name_from_antigravity_path)
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectNameFromAntigravityPath:
    """Unit tests for the path-based fallback that mirrors Claude Code's strategy.

    These tests use hard-coded fake absolute paths so that pytest's tmp_path
    prefix does not bleed non-system directory names into the search.
    """

    def test_standard_brain_path_returns_general(self):
        # Standard layout has no project component — fallback should yield General
        log_file = Path(
            r"C:\Users\Robin\.gemini\antigravity-ide\brain"
            r"\a1b2c3d4-0000-0000-0000-000000000000"
            r"\.system_generated\logs\transcript.jsonl"
        )
        assert _project_name_from_antigravity_path(log_file) == "General"

    def test_project_folder_between_brain_and_uuid_is_extracted(self):
        # Non-standard layout: brain/<project>/<uuid>/... — project name should be found
        log_file = Path(
            r"C:\Users\Robin\.gemini\antigravity-ide\brain\my-cool-app"
            r"\a1b2c3d4-0000-0000-0000-000000000000"
            r"\.system_generated\logs\transcript.jsonl"
        )
        assert _project_name_from_antigravity_path(log_file) == "My Cool App"

    def test_project_folder_above_gemini_is_extracted(self):
        # Custom brain_dir inside a project folder: C:\Users\Robin\MyProject\.gemini\...
        log_file = Path(
            r"C:\Users\Robin\MyProject\.gemini\antigravity-ide\brain"
            r"\a1b2c3d4-0000-0000-0000-000000000000"
            r"\.system_generated\logs\transcript.jsonl"
        )
        assert _project_name_from_antigravity_path(log_file) == "Myproject"

    def test_uuid_alone_returns_general(self):
        # Only system dirs and a UUID in the path — should return General
        log_file = Path(
            r"C:\brain\a1b2c3d4-0000-0000-0000-000000000000"
            r"\.system_generated\logs\transcript.jsonl"
        )
        assert _project_name_from_antigravity_path(log_file) == "General"

    def test_underscored_project_name_is_titled(self):
        log_file = Path(
            r"C:\Users\Robin\.gemini\antigravity-ide\brain\data_pipeline_project"
            r"\a1b2c3d4-0000-0000-0000-000000000000"
            r"\.system_generated\logs\transcript.jsonl"
        )
        assert _project_name_from_antigravity_path(log_file) == "Data Pipeline Project"

    def test_fallback_used_when_no_metadata_in_message(self, tmp_path):
        # Parser falls back to path when message content has no path metadata
        session_dir = (
            tmp_path / ".gemini" / "antigravity-ide" / "brain" / "ai-tracker-tool"
            / "a1b2c3d4-0000-0000-0000-000000000000" / ".system_generated" / "logs"
        )
        session_dir.mkdir(parents=True)
        transcript = session_dir / "transcript.jsonl"
        transcript.write_text(
            json.dumps({
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-06-01T10:00:00Z",
                "content": "<USER_REQUEST>\nHow does this work?\n</USER_REQUEST>",
            }) + "\n" +
            json.dumps({
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-06-01T10:00:05Z",
                "content": "Here is how it works.",
            }) + "\n",
            encoding="utf-8",
        )
        sessions = AntigravityParser(transcript).parse()
        assert len(sessions) == 1
        assert sessions[0].project == "Ai Tracker Tool"

