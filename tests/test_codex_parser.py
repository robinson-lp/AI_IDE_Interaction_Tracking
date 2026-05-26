"""Tests for the OpenAI Codex session parser."""

import json
from pathlib import Path

import pytest

from ai_tracker.parsers.codex import CodexParser

FIXTURES = Path(__file__).parent / "fixtures"
JSONL_SAMPLE = FIXTURES / "codex_sample.jsonl"
ARRAY_SAMPLE = FIXTURES / "codex_array.json"


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
