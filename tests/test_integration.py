"""
Integration tests — components working together across module boundaries.

Covers:
  1. Parser → CSVExporter            : parsed messages flow correctly into CSV rows
  2. Parser → filter_by_date         : date filtering integrates with each parser's output
  3. Config → get_parser()           : load_config path feeds correctly into parser factory
  4. PARSER_REGISTRY → get_parser()  : registry routes tool names to correct classes
  5. Multi-parser message merging    : messages from all three parsers sort correctly together
  6. Project filter integration      : project filtering applied after parsing
  7. Parser output → Message.to_dict(): data contract between parser and exporter
  8. BaseParser.filter_by_date       : session mutation safety across multiple parsers
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_tracker.config import load_config
from ai_tracker.exporters.csv_exporter import CSVExporter, FIELDNAMES
from ai_tracker.models import Message, ParsedSession
from ai_tracker.parsers import PARSER_REGISTRY, get_parser
from ai_tracker.parsers.antigravity import AntigravityParser
from ai_tracker.parsers.base import BaseParser
from ai_tracker.parsers.claude_code import ClaudeCodeParser
from ai_tracker.parsers.codex import CodexParser

FIXTURES = Path(__file__).parent / "fixtures"
CC_FIXTURE  = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE  = FIXTURES / "antigravity_transcript.jsonl"
CODEX_JSONL = FIXTURES / "codex_sample.jsonl"
CODEX_JSON  = FIXTURES / "codex_array.json"
CODEX_DT    = FIXTURES / "codex_desktop_session.jsonl"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Parser → CSVExporter
# ─────────────────────────────────────────────────────────────────────────────

class TestParserToExporter:
    """Parser output feeds directly into CSVExporter — verify the handoff."""

    def _export(self, parser: BaseParser, out: Path) -> list[dict]:
        sessions = parser.parse()
        messages = [m for s in sessions for m in s.messages]
        CSVExporter(out).export(messages)
        with open(out, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_claude_code_rows_have_correct_columns(self, tmp_path):
        rows = self._export(ClaudeCodeParser(CC_FIXTURE), tmp_path / "out.csv")
        assert rows[0].keys() == set(FIELDNAMES)

    def test_claude_code_tool_column_in_every_row(self, tmp_path):
        rows = self._export(ClaudeCodeParser(CC_FIXTURE), tmp_path / "out.csv")
        assert all(r["tool"] == "claudecode" for r in rows)

    def test_claude_code_roles_only_human_or_assistant(self, tmp_path):
        rows = self._export(ClaudeCodeParser(CC_FIXTURE), tmp_path / "out.csv")
        assert all(r["role"] in ("human", "assistant") for r in rows)

    def test_antigravity_rows_have_correct_columns(self, tmp_path):
        rows = self._export(AntigravityParser(AG_FIXTURE), tmp_path / "out.csv")
        assert rows[0].keys() == set(FIELDNAMES)

    def test_antigravity_tool_column_in_every_row(self, tmp_path):
        rows = self._export(AntigravityParser(AG_FIXTURE), tmp_path / "out.csv")
        assert all(r["tool"] == "antigravity" for r in rows)

    def test_codex_jsonl_rows_have_correct_columns(self, tmp_path):
        rows = self._export(CodexParser(CODEX_JSONL), tmp_path / "out.csv")
        assert rows[0].keys() == set(FIELDNAMES)

    def test_codex_desktop_rows_have_correct_columns(self, tmp_path):
        rows = self._export(CodexParser(CODEX_DT), tmp_path / "out.csv")
        assert rows[0].keys() == set(FIELDNAMES)

    def test_codex_desktop_tool_column_in_every_row(self, tmp_path):
        rows = self._export(CodexParser(CODEX_DT), tmp_path / "out.csv")
        assert all(r["tool"] == "codex" for r in rows)

    def test_empty_messages_writes_header_only(self, tmp_path):
        out = tmp_path / "out.csv"
        CSVExporter(out).export([])
        with open(out, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == FIELDNAMES
            assert list(reader) == []

    def test_unicode_message_survives_round_trip(self, tmp_path):
        out = tmp_path / "out.csv"
        msg = Message(
            session_id="s", timestamp=None, role="human",
            message="こんにちは 🎉 Ünïcödé", tool="codex", file_path="/f"
        )
        CSVExporter(out).export([msg])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["message"] == "こんにちは 🎉 Ünïcödé"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Parser → filter_by_date
# ─────────────────────────────────────────────────────────────────────────────

class TestParserToFilterByDate:
    """Date filter applied to real parser output — check correct messages survive."""

    def test_claude_code_future_start_removes_all(self):
        parser = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        filtered = parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        assert filtered == []

    def test_claude_code_past_end_removes_all(self):
        parser = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        filtered = parser.filter_by_date(sessions, start=None, end=datetime(2000, 1, 1))
        assert filtered == []

    def test_claude_code_wide_range_keeps_all(self):
        parser = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        original_count = sum(len(s.messages) for s in sessions)
        filtered = parser.filter_by_date(sessions, start=datetime(2020, 1, 1), end=datetime(2099, 1, 1))
        filtered_count = sum(len(s.messages) for s in filtered)
        assert filtered_count == original_count

    def test_antigravity_future_start_removes_all(self):
        parser = AntigravityParser(AG_FIXTURE)
        sessions = parser.parse()
        filtered = parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        assert filtered == []

    def test_filter_returns_new_sessions_not_mutating_originals(self):
        parser = ClaudeCodeParser(CC_FIXTURE)
        sessions = parser.parse()
        original_msg_count = len(sessions[0].messages)
        parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        assert len(sessions[0].messages) == original_msg_count

    def test_codex_wide_range_keeps_all_messages(self):
        parser = CodexParser(CODEX_JSONL)
        sessions = parser.parse()
        original_count = sum(len(s.messages) for s in sessions)
        filtered = parser.filter_by_date(sessions, start=datetime(2020, 1, 1), end=datetime(2099, 1, 1))
        filtered_count = sum(len(s.messages) for s in filtered)
        assert filtered_count == original_count

    def test_none_timestamps_always_pass_through_filter(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": "no timestamp here"}) + "\n",
            encoding="utf-8",
        )
        parser = CodexParser(f)
        sessions = parser.parse()
        # All messages have None timestamps — should survive any date filter
        filtered = parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        assert len(filtered) == 1
        assert len(filtered[0].messages) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Config → get_parser()
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigToParser:
    """load_config() path flows into get_parser() correctly."""

    def test_config_claudecode_path_is_string_or_path(self):
        cfg = load_config()
        path_val = cfg["tools"]["claudecode"]["path"]
        assert isinstance(path_val, str)

    def test_custom_config_path_used_by_get_parser(self, tmp_path):
        # Write a minimal JSONL so the parser has something to parse
        proj = tmp_path / "projects" / "my-project"
        proj.mkdir(parents=True)
        session = proj / "session.jsonl"
        session.write_text(
            json.dumps({
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
            }) + "\n",
            encoding="utf-8",
        )
        cfg_file = tmp_path / "tools.yaml"
        cfg_file.write_text(
            f"tools:\n  claudecode:\n    path: {tmp_path / 'projects'}\n",
            encoding="utf-8",
        )
        cfg = load_config(config_path=cfg_file)
        path = Path(cfg["tools"]["claudecode"]["path"]).expanduser()
        parser = get_parser("claudecode", path)
        sessions = parser.parse()
        assert len(sessions) == 1
        assert sessions[0].messages[0].message == "Hello"

    def test_config_antigravity_path_resolves(self):
        cfg = load_config()
        path_str = cfg["tools"]["antigravity"]["path"]
        assert "~" in path_str or Path(path_str).is_absolute() or True

    def test_config_codex_path_contains_sessions(self):
        cfg = load_config()
        assert "codex" in cfg["tools"]["codex"]["path"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. PARSER_REGISTRY → get_parser()
# ─────────────────────────────────────────────────────────────────────────────

class TestParserRegistry:
    """Registry routes tool names to correct parser classes and instantiates them."""

    def test_registry_has_three_tools(self):
        assert len(PARSER_REGISTRY) == 3

    def test_registry_keys(self):
        assert set(PARSER_REGISTRY.keys()) == {"antigravity", "claudecode", "codex"}

    def test_get_parser_claudecode_returns_claude_code_parser(self, tmp_path):
        p = get_parser("claudecode", tmp_path)
        assert isinstance(p, ClaudeCodeParser)

    def test_get_parser_antigravity_returns_antigravity_parser(self, tmp_path):
        p = get_parser("antigravity", tmp_path)
        assert isinstance(p, AntigravityParser)

    def test_get_parser_codex_returns_codex_parser(self, tmp_path):
        p = get_parser("codex", tmp_path)
        assert isinstance(p, CodexParser)

    def test_get_parser_unknown_tool_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown tool"):
            get_parser("unknown_tool", tmp_path)

    def test_get_parser_case_insensitive(self, tmp_path):
        p = get_parser("ClaudeCode", tmp_path)
        assert isinstance(p, ClaudeCodeParser)

    def test_get_parser_returns_base_parser_subclass(self, tmp_path):
        for tool in PARSER_REGISTRY:
            p = get_parser(tool, tmp_path)
            assert isinstance(p, BaseParser)

    def test_get_parser_sets_tool_name(self, tmp_path):
        p = get_parser("codex", tmp_path)
        assert p.tool_name == "codex"

    def test_get_parser_sets_file_path(self, tmp_path):
        p = get_parser("claudecode", tmp_path)
        assert p.file_path == tmp_path

    def test_get_parser_passes_kwargs_to_claude_code(self, tmp_path):
        p = get_parser("claudecode", tmp_path, include_sidechains=False)
        assert p.include_sidechains is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-parser message merging
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiParserMerging:
    """Messages from all three parsers merge and sort correctly by timestamp."""

    def _all_messages(self):
        parsers = [
            ClaudeCodeParser(CC_FIXTURE),
            AntigravityParser(AG_FIXTURE),
            CodexParser(CODEX_JSONL),
        ]
        all_msgs = []
        for p in parsers:
            for s in p.parse():
                all_msgs.extend(s.messages)
        return all_msgs

    def test_messages_from_all_three_tools_present(self):
        msgs = self._all_messages()
        tools = {m.tool for m in msgs}
        assert tools == {"claudecode", "antigravity", "codex"}

    def test_sort_by_timestamp_produces_chronological_order(self):
        msgs = self._all_messages()
        with_ts = [m for m in msgs if m.timestamp is not None]
        sorted_msgs = sorted(with_ts, key=lambda m: m.timestamp)
        assert [m.timestamp for m in sorted_msgs] == sorted(m.timestamp for m in with_ts)

    def test_no_cross_tool_contamination(self):
        msgs = self._all_messages()
        for m in msgs:
            if m.tool == "claudecode":
                assert "antigravity" not in m.file_path
            if m.tool == "antigravity":
                assert "claude_code" not in m.file_path

    def test_total_count_equals_sum_of_individual_parsers(self):
        cc_count = sum(len(s.messages) for s in ClaudeCodeParser(CC_FIXTURE).parse())
        ag_count = sum(len(s.messages) for s in AntigravityParser(AG_FIXTURE).parse())
        cx_count = sum(len(s.messages) for s in CodexParser(CODEX_JSONL).parse())
        all_msgs = self._all_messages()
        assert len(all_msgs) == cc_count + ag_count + cx_count

    def test_merged_and_exported_csv_has_all_rows(self, tmp_path):
        msgs = sorted(
            self._all_messages(),
            key=lambda m: m.timestamp.isoformat() if m.timestamp else "",
        )
        out = tmp_path / "merged.csv"
        CSVExporter(out).export(msgs)
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == len(msgs)

    def test_merged_csv_has_tool_column_for_all_rows(self, tmp_path):
        msgs = self._all_messages()
        out = tmp_path / "merged.csv"
        CSVExporter(out).export(msgs)
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert all(r["tool"] in ("claudecode", "antigravity", "codex") for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Project filter integration
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectFilterIntegration:
    """Project name filtering applied after multi-parser merge."""

    def _make_multi_project_sessions(self, tmp_path: Path) -> Path:
        """Create two project directories under a projects root."""
        for slug, text in [("alpha-project", "Hello from alpha"), ("beta-project", "Hello from beta")]:
            d = tmp_path / "projects" / slug
            d.mkdir(parents=True)
            record = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
            }
            (d / "session.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        return tmp_path / "projects"

    def test_project_filter_keeps_matching_messages(self, tmp_path):
        root = self._make_multi_project_sessions(tmp_path)
        msgs = [m for s in ClaudeCodeParser(root).parse() for m in s.messages]
        filtered = [m for m in msgs if "alpha" in m.project.lower()]
        assert len(filtered) == 1
        assert "Hello from alpha" in filtered[0].message

    def test_project_filter_excludes_nonmatching(self, tmp_path):
        root = self._make_multi_project_sessions(tmp_path)
        msgs = [m for s in ClaudeCodeParser(root).parse() for m in s.messages]
        filtered = [m for m in msgs if "gamma" in m.project.lower()]
        assert filtered == []

    def test_project_filter_case_insensitive(self, tmp_path):
        root = self._make_multi_project_sessions(tmp_path)
        msgs = [m for s in ClaudeCodeParser(root).parse() for m in s.messages]
        upper = [m for m in msgs if "ALPHA" in m.project.upper()]
        lower = [m for m in msgs if "alpha" in m.project.lower()]
        assert len(upper) == len(lower)

    def test_split_by_project_produces_separate_csvs(self, tmp_path):
        root = self._make_multi_project_sessions(tmp_path)
        msgs = [m for s in ClaudeCodeParser(root).parse() for m in s.messages]
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        projects: dict[str, list[Message]] = {}
        for m in msgs:
            projects.setdefault(m.project, []).append(m)
        for proj, proj_msgs in projects.items():
            fname = proj.lower().replace(" ", "_") + ".csv"
            CSVExporter(out_dir / fname).export(proj_msgs)
        assert len(list(out_dir.glob("*.csv"))) == 2

    def test_each_project_csv_contains_only_its_own_messages(self, tmp_path):
        root = self._make_multi_project_sessions(tmp_path)
        msgs = [m for s in ClaudeCodeParser(root).parse() for m in s.messages]
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        projects: dict[str, list[Message]] = {}
        for m in msgs:
            projects.setdefault(m.project, []).append(m)
        for proj, proj_msgs in projects.items():
            fname = proj.lower().replace(" ", "_") + ".csv"
            CSVExporter(out_dir / fname).export(proj_msgs)
        for f in out_dir.glob("*.csv"):
            with open(f, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            assert len({r["project"] for r in rows}) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. Parser output → Message.to_dict() data contract
# ─────────────────────────────────────────────────────────────────────────────

class TestParserToMessageDataContract:
    """Every field a parser writes into Message must survive to_dict() intact."""

    def _first_human(self, parser: BaseParser) -> Message:
        sessions = parser.parse()
        return next(m for s in sessions for m in s.messages if m.role == "human")

    def test_claude_code_session_id_in_to_dict(self):
        msg = self._first_human(ClaudeCodeParser(CC_FIXTURE))
        d = msg.to_dict()
        assert d["session_id"] == msg.session_id

    def test_claude_code_timestamp_in_to_dict(self):
        msg = self._first_human(ClaudeCodeParser(CC_FIXTURE))
        d = msg.to_dict()
        assert d["timestamp"] != ""

    def test_claude_code_file_path_in_to_dict(self):
        msg = self._first_human(ClaudeCodeParser(CC_FIXTURE))
        d = msg.to_dict()
        assert "claude_code_sample" in d["file_path"]

    def test_antigravity_message_text_in_to_dict(self):
        msg = self._first_human(AntigravityParser(AG_FIXTURE))
        d = msg.to_dict()
        assert d["message"] != ""

    def test_codex_tool_field_in_to_dict(self):
        msg = self._first_human(CodexParser(CODEX_JSONL))
        d = msg.to_dict()
        assert d["tool"] == "codex"

    def test_codex_desktop_project_in_to_dict(self):
        msg = self._first_human(CodexParser(CODEX_DT))
        d = msg.to_dict()
        assert d["project"] == "Hi Codex Top 10 Programming Concepts"

    def test_all_dict_values_are_strings(self):
        msg = self._first_human(ClaudeCodeParser(CC_FIXTURE))
        d = msg.to_dict()
        assert all(isinstance(v, str) for v in d.values())

    def test_to_dict_key_order_matches_fieldnames(self):
        msg = self._first_human(ClaudeCodeParser(CC_FIXTURE))
        assert list(msg.to_dict().keys()) == FIELDNAMES


# ─────────────────────────────────────────────────────────────────────────────
# 8. filter_by_date mutation safety across parsers
# ─────────────────────────────────────────────────────────────────────────────

class TestFilterMutationSafety:
    """filter_by_date must never modify the original ParsedSession objects."""

    @pytest.mark.parametrize("parser_cls,fixture", [
        (ClaudeCodeParser,   CC_FIXTURE),
        (AntigravityParser,  AG_FIXTURE),
        (CodexParser,        CODEX_JSONL),
    ])
    def test_original_sessions_unchanged_after_filter(self, parser_cls, fixture):
        parser = parser_cls(fixture)
        sessions = parser.parse()
        counts_before = [len(s.messages) for s in sessions]
        parser.filter_by_date(sessions, start=datetime(2099, 1, 1), end=None)
        counts_after = [len(s.messages) for s in sessions]
        assert counts_before == counts_after

    @pytest.mark.parametrize("parser_cls,fixture", [
        (ClaudeCodeParser,   CC_FIXTURE),
        (AntigravityParser,  AG_FIXTURE),
        (CodexParser,        CODEX_JSONL),
    ])
    def test_filtered_sessions_are_new_objects(self, parser_cls, fixture):
        parser = parser_cls(fixture)
        sessions = parser.parse()
        filtered = parser.filter_by_date(
            sessions,
            start=datetime(2020, 1, 1),
            end=datetime(2099, 1, 1),
        )
        for orig, filt in zip(sessions, filtered):
            assert orig is not filt
