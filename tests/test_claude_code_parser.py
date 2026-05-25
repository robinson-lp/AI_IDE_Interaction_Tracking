"""Tests for the Claude Code JSONL parser."""

from pathlib import Path

import pytest

from ai_tracker.parsers.claude_code import ClaudeCodeParser

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "claude_code_sample.jsonl"


class TestClaudeCodeParserSingleFile:
    def _parser(self, include_sidechains: bool = False) -> ClaudeCodeParser:
        return ClaudeCodeParser(SAMPLE, include_sidechains=include_sidechains)

    def test_returns_one_session(self):
        sessions = self._parser().parse()
        assert len(sessions) == 1

    def test_message_session_id_from_record(self):
        # ParsedSession.session_id comes from the filename stem (UUID when real);
        # each Message.session_id is overridden from the record's sessionId field.
        messages = self._parser().parse()[0].messages
        assert all(m.session_id == "abc12345-0000-0000-0000-000000000001" for m in messages)

    def test_tool_name_set_on_session(self):
        session = self._parser().parse()[0]
        assert session.tool == "claudecode"

    def test_skips_queue_operations(self):
        messages = self._parser().parse()[0].messages
        types = {m.role for m in messages}
        # queue-operation records carry no role; they must be absent
        assert "queue-operation" not in types

    def test_correct_message_count_without_sidechains(self):
        # 4 real messages (2 human + 2 assistant); 1 sidechain should be skipped
        messages = self._parser(include_sidechains=False).parse()[0].messages
        assert len(messages) == 4

    def test_roles_normalised(self):
        messages = self._parser().parse()[0].messages
        roles = {m.role for m in messages}
        assert roles == {"human", "assistant"}

    def test_human_message_text(self):
        messages = self._parser().parse()[0].messages
        human_texts = [m.message for m in messages if m.role == "human"]
        assert any("reverse a list" in t for t in human_texts)

    def test_assistant_message_text(self):
        messages = self._parser().parse()[0].messages
        ai_texts = [m.message for m in messages if m.role == "assistant"]
        assert any("[::-1]" in t for t in ai_texts)

    def test_timestamps_parsed(self):
        messages = self._parser().parse()[0].messages
        assert all(m.timestamp is not None for m in messages)

    def test_timestamps_ordered(self):
        messages = self._parser().parse()[0].messages
        ts = [m.timestamp for m in messages]
        assert ts == sorted(ts)

    def test_include_sidechains(self):
        messages = self._parser(include_sidechains=True).parse()[0].messages
        assert len(messages) == 5

    def test_file_path_recorded(self):
        messages = self._parser().parse()[0].messages
        assert all(str(SAMPLE) in m.file_path for m in messages)


class TestClaudeCodeParserMissingFile:
    def test_raises_file_not_found(self, tmp_path):
        parser = ClaudeCodeParser(tmp_path / "nonexistent.jsonl")
        with pytest.raises(FileNotFoundError):
            parser.parse()


class TestClaudeCodeParserDirectory:
    def test_parses_all_jsonl_in_dir(self, tmp_path):
        # Write two minimal JSONL session files
        for i, fname in enumerate(["sess-a.jsonl", "sess-b.jsonl"]):
            (tmp_path / fname).write_text(
                '{"type":"user","isSidechain":false,"message":{"role":"user","content":[{"type":"text","text":"Q"}]},'
                f'"uuid":"u{i}","timestamp":"2026-05-01T10:00:00Z","sessionId":"sess-{i}"}}' + "\n" +
                '{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"A"}]},'
                f'"uuid":"a{i}","timestamp":"2026-05-01T10:00:05Z","sessionId":"sess-{i}"}}' + "\n",
                encoding="utf-8",
            )
        sessions = ClaudeCodeParser(tmp_path).parse()
        assert len(sessions) == 2
        total_msgs = sum(len(s.messages) for s in sessions)
        assert total_msgs == 4

    def test_skips_subagents_dir(self, tmp_path):
        subagents = tmp_path / "subagents"
        subagents.mkdir()
        (subagents / "agent-001.jsonl").write_text(
            '{"type":"user","isSidechain":true,"message":{"role":"user","content":[{"type":"text","text":"Sub"}]},'
            '"uuid":"s1","timestamp":"2026-05-01T10:00:00Z","sessionId":"sub-sess"}' + "\n",
            encoding="utf-8",
        )
        sessions = ClaudeCodeParser(tmp_path, include_sidechains=False).parse()
        assert sessions == []
