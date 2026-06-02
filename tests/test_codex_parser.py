"""Tests for the OpenAI Codex session parser."""

import json
from pathlib import Path

import pytest

from ai_tracker.parsers.codex import CodexParser

FIXTURES = Path(__file__).parent / "fixtures"
JSONL_SAMPLE = FIXTURES / "codex_sample.jsonl"
ARRAY_SAMPLE = FIXTURES / "codex_array.json"
DESKTOP_SAMPLE = FIXTURES / "codex_desktop_session.jsonl"


class TestCodexParserJSONL:
    def test_returns_one_session(self):
        sessions = CodexParser(JSONL_SAMPLE).parse()
        assert len(sessions) == 1

    def test_tool_name(self):
        assert CodexParser(JSONL_SAMPLE).parse()[0].tool == "codex"

    def test_message_count(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        assert len(msgs) == 2

    def test_roles_normalised(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        assert {m.role for m in msgs} == {"human", "assistant"}

    def test_human_message_text(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        human = [m for m in msgs if m.role == "human"]
        assert any("sort" in m.message.lower() for m in human)

    def test_assistant_message_text(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        ai = [m for m in msgs if m.role == "assistant"]
        assert any("sorted" in m.message for m in ai)

    def test_timestamps_parsed(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        assert all(m.timestamp is not None for m in msgs)

    def test_file_path_recorded(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        assert all("codex_sample" in m.file_path for m in msgs)

    def test_session_id_from_record(self):
        msgs = CodexParser(JSONL_SAMPLE).parse()[0].messages
        assert all(m.session_id == "codex-sess-001" for m in msgs)


class TestCodexParserJSONArray:
    def test_returns_one_session(self):
        sessions = CodexParser(ARRAY_SAMPLE).parse()
        assert len(sessions) == 1

    def test_tool_name(self):
        assert CodexParser(ARRAY_SAMPLE).parse()[0].tool == "codex"

    def test_message_count(self):
        msgs = CodexParser(ARRAY_SAMPLE).parse()[0].messages
        assert len(msgs) == 2

    def test_roles_normalised(self):
        msgs = CodexParser(ARRAY_SAMPLE).parse()[0].messages
        assert {m.role for m in msgs} == {"human", "assistant"}

    def test_assistant_message_text(self):
        msgs = CodexParser(ARRAY_SAMPLE).parse()[0].messages
        ai = [m for m in msgs if m.role == "assistant"]
        assert any("generator" in m.message.lower() for m in ai)

    def test_timestamps_parsed(self):
        msgs = CodexParser(ARRAY_SAMPLE).parse()[0].messages
        assert all(m.timestamp is not None for m in msgs)


class TestCodexParserDirectory:
    def test_parses_jsonl_and_json_in_dir(self, tmp_path):
        (tmp_path / "session1.jsonl").write_text(
            '{"role":"user","content":"Q1"}\n{"role":"assistant","content":"A1"}\n',
            encoding="utf-8",
        )
        (tmp_path / "session2.json").write_text(
            '[{"role":"user","content":"Q2"},{"role":"assistant","content":"A2"}]',
            encoding="utf-8",
        )
        sessions = CodexParser(tmp_path).parse()
        assert len(sessions) == 2
        assert sum(len(s.messages) for s in sessions) == 4

    def test_empty_dir_returns_no_sessions(self, tmp_path):
        assert CodexParser(tmp_path).parse() == []

    def test_session_id_from_filename(self, tmp_path):
        (tmp_path / "my-session.jsonl").write_text(
            '{"role":"user","content":"Hi"}\n',
            encoding="utf-8",
        )
        session = CodexParser(tmp_path).parse()[0]
        assert session.session_id == "my-session"


class TestCodexParserMissing:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CodexParser(tmp_path / "nonexistent.jsonl").parse()


class TestCodexParserEdgeCases:
    def test_unix_timestamp_integer(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":"Hello","timestamp":1716192000}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert msgs[0].timestamp is not None

    def test_empty_file_returns_no_sessions(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("", encoding="utf-8")
        assert CodexParser(f).parse() == []

    def test_record_missing_role_is_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"content":"no role here"}\n'
            '{"role":"user","content":"valid"}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert len(msgs) == 1
        assert msgs[0].role == "human"

    def test_record_missing_content_is_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user"}\n'
            '{"role":"assistant","content":"has content"}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"

    def test_content_as_text_block_list(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"user","content":[{"type":"text","text":"List content here"}]}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert msgs[0].message == "List content here"

    def test_malformed_json_line_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            'not valid json\n'
            '{"role":"user","content":"good line"}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert len(msgs) == 1

    def test_system_role_record_is_skipped(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"role":"system","content":"You are a helpful assistant."}\n'
            '{"role":"user","content":"Hello"}\n',
            encoding="utf-8",
        )
        msgs = CodexParser(f).parse()[0].messages
        assert len(msgs) == 1
        assert msgs[0].role == "human"

    def test_parse_is_idempotent(self, tmp_path):
        f = tmp_path / "my-session.jsonl"
        f.write_text('{"role":"user","content":"Hi"}\n', encoding="utf-8")
        id_first  = CodexParser(f).parse()[0].messages[0].session_id
        id_second = CodexParser(f).parse()[0].messages[0].session_id
        assert id_first == id_second == "my-session"


class TestCodexDesktopFormat:
    """Tests for the Codex Desktop event-log JSONL format."""

    def _parse(self):
        return CodexParser(DESKTOP_SAMPLE).parse()

    def test_returns_one_session(self):
        assert len(self._parse()) == 1

    def test_tool_name(self):
        assert self._parse()[0].tool == "codex"

    def test_message_count(self):
        # 2 user_message + 2 agent_message(final_answer) = 4; commentary skipped
        msgs = self._parse()[0].messages
        assert len(msgs) == 4

    def test_roles_normalised(self):
        roles = {m.role for m in self._parse()[0].messages}
        assert roles == {"human", "assistant"}

    def test_human_message_count(self):
        msgs = self._parse()[0].messages
        assert len([m for m in msgs if m.role == "human"]) == 2

    def test_assistant_message_count(self):
        msgs = self._parse()[0].messages
        assert len([m for m in msgs if m.role == "assistant"]) == 2

    def test_first_human_message_text(self):
        msgs = self._parse()[0].messages
        human = [m for m in msgs if m.role == "human"]
        assert "programming concepts" in human[0].message.lower()

    def test_first_assistant_response_text(self):
        msgs = self._parse()[0].messages
        ai = [m for m in msgs if m.role == "assistant"]
        assert "programming" in ai[0].message.lower()

    def test_commentary_messages_excluded(self):
        msgs = self._parse()[0].messages
        for m in msgs:
            assert "Thinking about" not in m.message

    def test_project_name_from_cwd(self):
        session = self._parse()[0]
        assert session.project == "Hi Codex Top 10 Programming Concepts"

    def test_messages_carry_project_name(self):
        msgs = self._parse()[0].messages
        assert all(m.project == "Hi Codex Top 10 Programming Concepts" for m in msgs)

    def test_session_id_from_session_meta(self):
        session = self._parse()[0]
        assert session.session_id == "codex_desktop_session"  # ParsedSession uses filename stem

    def test_message_session_id_from_meta(self):
        msgs = self._parse()[0].messages
        assert all(m.session_id == "019e87b9-0cd0-76b1-8e23-2914f91ceda9" for m in msgs)

    def test_timestamps_parsed(self):
        msgs = self._parse()[0].messages
        assert all(m.timestamp is not None for m in msgs)

    def test_real_codex_desktop_session(self):
        """Parse the real session file the user provided."""
        real_file = Path.home() / ".codex" / "sessions" / "2026" / "06" / "02" / (
            "rollout-2026-06-02T15-15-12-019e87b9-0cd0-76b1-8e23-2914f91ceda9.jsonl"
        )
        if not real_file.exists():
            import pytest
            pytest.skip("Real Codex Desktop session file not found")
        sessions = CodexParser(real_file).parse()
        assert len(sessions) == 1
        msgs = sessions[0].messages
        human = [m for m in msgs if m.role == "human"]
        ai = [m for m in msgs if m.role == "assistant"]
        assert len(human) >= 1
        assert len(ai) >= 1
        assert sessions[0].project == "Hi Codex Top 10 Programming Concepts"
