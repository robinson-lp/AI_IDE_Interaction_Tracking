"""
Smoke Test Suite
================
Fast sanity checks that run after every build to confirm the system
is alive and the critical path is functional. These are NOT exhaustive —
they verify the application can start, imports resolve, core components
initialize, and one full pipeline run produces output.

If any smoke test fails, do not proceed to deeper test layers.

Categories:
  S01  Module imports
  S02  Core component initialization
  S03  Parser smoke — each parser can parse its fixture
  S04  Exporter smoke
  S05  CLI smoke — commands respond
  S06  Config smoke
  S07  Full pipeline smoke — source file → CSV in one shot
  S08  Real data smoke — live data sanity check
"""

import argparse
import csv
from pathlib import Path

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURES   = Path(__file__).parent / "fixtures"
CC_SAMPLE  = FIXTURES / "claude_code_sample.jsonl"
AG_SAMPLE  = FIXTURES / "antigravity_transcript.jsonl"
CX_SAMPLE  = FIXTURES / "codex_sample.jsonl"
CX_DESKTOP = FIXTURES / "codex_desktop_session.jsonl"

REAL_CC = Path.home() / ".claude"  / "projects"
REAL_AG = Path.home() / ".gemini"  / "antigravity-ide" / "brain"
REAL_CX = Path.home() / ".codex"   / "sessions"

# ── Helper ────────────────────────────────────────────────────────────────────

def _args(**kw) -> argparse.Namespace:
    base = dict(tool="all", file=None, output=None, start_date=None,
                end_date=None, include_sidechains=True, project=None,
                split_by_project=False)
    base.update(kw)
    return argparse.Namespace(**base)


# ═════════════════════════════════════════════════════════════════════════════
# S01  Module imports
# ═════════════════════════════════════════════════════════════════════════════

class TestS01ModuleImports:
    """Every package module must import without error."""

    def test_import_ai_tracker(self):
        import ai_tracker
        assert ai_tracker.__version__ == "0.1.0"

    def test_import_models(self):
        from ai_tracker.models import Message, ParsedSession
        assert Message and ParsedSession

    def test_import_config(self):
        from ai_tracker.config import load_config, DEFAULT_TOOL_PATHS
        assert load_config and DEFAULT_TOOL_PATHS

    def test_import_cli(self):
        from ai_tracker.cli import main, cmd_parse, cmd_list_tools
        assert main and cmd_parse and cmd_list_tools

    def test_import_parser_registry(self):
        from ai_tracker.parsers import PARSER_REGISTRY, get_parser
        assert PARSER_REGISTRY and get_parser

    def test_import_base_parser(self):
        from ai_tracker.parsers.base import (
            BaseParser, _clean_project_name,
            _normalise_role, _parse_timestamp, _in_range,
        )
        assert BaseParser

    def test_import_antigravity_parser(self):
        from ai_tracker.parsers.antigravity import AntigravityParser
        assert AntigravityParser

    def test_import_claude_code_parser(self):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser, _extract_text
        assert ClaudeCodeParser and _extract_text

    def test_import_codex_parser(self):
        from ai_tracker.parsers.codex import (
            CodexParser, _is_codex_desktop_format, _project_name_from_path,
        )
        assert CodexParser

    def test_import_csv_exporter(self):
        from ai_tracker.exporters.csv_exporter import CSVExporter, FIELDNAMES
        assert CSVExporter and FIELDNAMES


# ═════════════════════════════════════════════════════════════════════════════
# S02  Core component initialization
# ═════════════════════════════════════════════════════════════════════════════

class TestS02ComponentInitialization:
    """Key objects can be instantiated and have expected attributes."""

    def test_message_can_be_created(self):
        from ai_tracker.models import Message
        msg = Message(
            session_id="s1", timestamp=None, role="human",
            message="Hello", tool="claudecode", file_path="/f",
        )
        assert msg.role == "human"
        assert msg.project == "General"

    def test_parsed_session_can_be_created(self):
        from ai_tracker.models import ParsedSession
        s = ParsedSession(session_id="s1", tool="codex", file_path="/f")
        assert s.messages == []
        assert s.project == "General"

    def test_claude_code_parser_instantiates(self, tmp_path):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        p = ClaudeCodeParser(tmp_path)
        assert p.tool_name == "claudecode"

    def test_antigravity_parser_instantiates(self, tmp_path):
        from ai_tracker.parsers.antigravity import AntigravityParser
        p = AntigravityParser(tmp_path)
        assert p.tool_name == "antigravity"

    def test_codex_parser_instantiates(self, tmp_path):
        from ai_tracker.parsers.codex import CodexParser
        p = CodexParser(tmp_path)
        assert p.tool_name == "codex"

    def test_csv_exporter_instantiates(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        e = CSVExporter(tmp_path / "out.csv")
        assert e.output_path.suffix == ".csv"

    def test_parser_registry_has_three_entries(self):
        from ai_tracker.parsers import PARSER_REGISTRY
        assert len(PARSER_REGISTRY) == 3
        assert set(PARSER_REGISTRY.keys()) == {"antigravity", "claudecode", "codex"}

    def test_get_parser_factory_works(self, tmp_path):
        from ai_tracker.parsers import get_parser
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        p = get_parser("claudecode", tmp_path)
        assert isinstance(p, ClaudeCodeParser)

    def test_fieldnames_has_seven_columns(self):
        from ai_tracker.exporters.csv_exporter import FIELDNAMES
        assert len(FIELDNAMES) == 7
        assert FIELDNAMES[0] == "project"
        assert FIELDNAMES[-1] == "file_path"


# ═════════════════════════════════════════════════════════════════════════════
# S03  Parser smoke — each parser can parse its fixture
# ═════════════════════════════════════════════════════════════════════════════

class TestS03ParserSmoke:
    """Each parser produces at least one message from its test fixture."""

    def test_claude_code_parser_returns_messages(self):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        sessions = ClaudeCodeParser(CC_SAMPLE).parse()
        msgs = [m for s in sessions for m in s.messages]
        assert len(msgs) > 0, "ClaudeCodeParser returned no messages"

    def test_claude_code_parser_has_human_and_assistant(self):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        msgs = [m for s in ClaudeCodeParser(CC_SAMPLE).parse() for m in s.messages]
        roles = {m.role for m in msgs}
        assert "human"     in roles
        assert "assistant" in roles

    def test_antigravity_parser_returns_messages(self):
        from ai_tracker.parsers.antigravity import AntigravityParser
        sessions = AntigravityParser(AG_SAMPLE).parse()
        msgs = [m for s in sessions for m in s.messages]
        assert len(msgs) > 0, "AntigravityParser returned no messages"

    def test_antigravity_parser_has_human_role(self):
        from ai_tracker.parsers.antigravity import AntigravityParser
        msgs = [m for s in AntigravityParser(AG_SAMPLE).parse() for m in s.messages]
        assert any(m.role == "human" for m in msgs)

    def test_codex_jsonl_parser_returns_messages(self):
        from ai_tracker.parsers.codex import CodexParser
        sessions = CodexParser(CX_SAMPLE).parse()
        msgs = [m for s in sessions for m in s.messages]
        assert len(msgs) > 0, "CodexParser (JSONL) returned no messages"

    def test_codex_desktop_parser_returns_messages(self):
        from ai_tracker.parsers.codex import CodexParser
        sessions = CodexParser(CX_DESKTOP).parse()
        msgs = [m for s in sessions for m in s.messages]
        assert len(msgs) > 0, "CodexParser (Desktop) returned no messages"

    def test_codex_desktop_excludes_commentary(self):
        from ai_tracker.parsers.codex import CodexParser
        msgs = [m for s in CodexParser(CX_DESKTOP).parse() for m in s.messages]
        assert not any("Thinking about" in m.message for m in msgs)

    def test_all_parsers_set_tool_name(self):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        from ai_tracker.parsers.antigravity import AntigravityParser
        from ai_tracker.parsers.codex import CodexParser
        for cls, fixture, expected in [
            (ClaudeCodeParser,  CC_SAMPLE,  "claudecode"),
            (AntigravityParser, AG_SAMPLE,  "antigravity"),
            (CodexParser,       CX_SAMPLE,  "codex"),
        ]:
            sessions = cls(fixture).parse()
            assert sessions[0].tool == expected, \
                f"{cls.__name__} tool_name wrong: {sessions[0].tool}"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        with pytest.raises(FileNotFoundError):
            ClaudeCodeParser(tmp_path / "no_such.jsonl").parse()


# ═════════════════════════════════════════════════════════════════════════════
# S04  Exporter smoke
# ═════════════════════════════════════════════════════════════════════════════

class TestS04ExporterSmoke:
    """CSVExporter writes a valid file."""

    def test_exporter_creates_file(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        out = tmp_path / "out.csv"
        CSVExporter(out).export([
            Message(session_id="s", timestamp=None, role="human",
                    message="Hi", tool="codex", file_path="/f")
        ])
        assert out.exists()

    def test_exporter_writes_header(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter, FIELDNAMES
        out = tmp_path / "out.csv"
        CSVExporter(out).export([])
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES

    def test_exporter_writes_one_row(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        out = tmp_path / "out.csv"
        CSVExporter(out).export([
            Message(session_id="s", timestamp=None, role="human",
                    message="Hello", tool="claudecode", file_path="/f")
        ])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["message"] == "Hello"

    def test_exporter_returns_row_count(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import CSVExporter
        from ai_tracker.models import Message
        out = tmp_path / "out.csv"
        msgs = [Message(session_id="s", timestamp=None, role="human",
                        message=f"M{i}", tool="codex", file_path="/f")
                for i in range(5)]
        count = CSVExporter(out).export(msgs)
        assert count == 5


# ═════════════════════════════════════════════════════════════════════════════
# S05  CLI smoke — commands respond correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestS05CLISmoke:
    """CLI entry points are callable and return expected exit codes."""

    def test_list_tools_exits_zero(self, capsys):
        from ai_tracker.cli import cmd_list_tools
        rc = cmd_list_tools(_args())
        assert rc == 0

    def test_list_tools_names_all_three_tools(self, capsys):
        from ai_tracker.cli import cmd_list_tools
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "claudecode"  in out
        assert "antigravity" in out
        assert "codex"       in out

    def test_parse_claudecode_exits_zero(self, tmp_path):
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(CC_SAMPLE), output=str(out)))
        assert rc == 0

    def test_parse_antigravity_exits_zero(self, tmp_path):
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="antigravity", file=str(AG_SAMPLE), output=str(out)))
        assert rc == 0

    def test_parse_codex_exits_zero(self, tmp_path):
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(CX_SAMPLE), output=str(out)))
        assert rc == 0

    def test_parse_missing_file_exits_nonzero(self, tmp_path, capsys):
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode",
                             file=str(tmp_path / "no_such.jsonl"),
                             output=str(out)))
        assert rc != 0

    def test_parse_stdout_confirms_export(self, tmp_path, capsys):
        from ai_tracker.cli import cmd_parse
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_SAMPLE), output=str(out)))
        out_text = capsys.readouterr().out
        assert "Exported" in out_text


# ═════════════════════════════════════════════════════════════════════════════
# S06  Config smoke
# ═════════════════════════════════════════════════════════════════════════════

class TestS06ConfigSmoke:
    """Configuration system loads and exposes expected structure."""

    def test_load_config_returns_dict(self):
        from ai_tracker.config import load_config
        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_config_has_tools_section(self):
        from ai_tracker.config import load_config
        assert "tools" in load_config()

    def test_config_has_all_three_tools(self):
        from ai_tracker.config import load_config
        tools = load_config()["tools"]
        assert "claudecode"  in tools
        assert "antigravity" in tools
        assert "codex"       in tools

    def test_each_tool_has_path(self):
        from ai_tracker.config import load_config
        tools = load_config()["tools"]
        for name, cfg in tools.items():
            assert "path" in cfg, f"Tool {name!r} has no path in config"

    def test_default_tool_paths_defined(self):
        from ai_tracker.config import DEFAULT_TOOL_PATHS
        assert len(DEFAULT_TOOL_PATHS) == 3
        assert all(isinstance(p, Path) for p in DEFAULT_TOOL_PATHS.values())

    def test_config_returns_independent_copies(self):
        from ai_tracker.config import load_config
        cfg1 = load_config()
        cfg2 = load_config()
        cfg1["tools"]["codex"]["path"] = "/mutated"
        assert cfg2["tools"]["codex"]["path"] != "/mutated"


# ═════════════════════════════════════════════════════════════════════════════
# S07  Full pipeline smoke — source file → parsed → CSV
# ═════════════════════════════════════════════════════════════════════════════

class TestS07FullPipelineSmoke:
    """One complete run per tool: fixture file → parser → exporter → CSV on disk."""

    def _run(self, tool: str, fixture: Path, tmp_path: Path) -> list[dict]:
        from ai_tracker.cli import cmd_parse
        out = tmp_path / f"{tool}.csv"
        rc = cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        assert rc == 0,          f"Pipeline failed for {tool} (rc={rc})"
        assert out.exists(),     f"No CSV produced for {tool}"
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) > 0,   f"Empty CSV for {tool}"
        return rows

    def test_claude_code_full_pipeline(self, tmp_path):
        rows = self._run("claudecode", CC_SAMPLE, tmp_path)
        assert all(r["tool"] == "claudecode" for r in rows)
        assert {r["role"] for r in rows} >= {"human", "assistant"}

    def test_antigravity_full_pipeline(self, tmp_path):
        rows = self._run("antigravity", AG_SAMPLE, tmp_path)
        assert all(r["tool"] == "antigravity" for r in rows)
        assert any(r["role"] == "human" for r in rows)

    def test_codex_jsonl_full_pipeline(self, tmp_path):
        rows = self._run("codex", CX_SAMPLE, tmp_path)
        assert all(r["tool"] == "codex" for r in rows)

    def test_codex_desktop_full_pipeline(self, tmp_path):
        rows = self._run("codex", CX_DESKTOP, tmp_path)
        assert all(r["tool"] == "codex" for r in rows)
        assert any(r["role"] == "human"     for r in rows)
        assert any(r["role"] == "assistant" for r in rows)

    def test_csv_schema_correct_in_every_pipeline(self, tmp_path):
        from ai_tracker.exporters.csv_exporter import FIELDNAMES
        from ai_tracker.cli import cmd_parse
        for tool, fixture in [("claudecode", CC_SAMPLE),
                               ("antigravity", AG_SAMPLE),
                               ("codex",       CX_SAMPLE)]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
            with open(out, encoding="utf-8") as fh:
                assert csv.DictReader(fh).fieldnames == FIELDNAMES, \
                    f"Wrong schema in {tool} pipeline"

    def test_all_pipelines_complete_under_five_seconds(self, tmp_path):
        import time
        from ai_tracker.cli import cmd_parse
        start = time.perf_counter()
        for tool, fixture in [("claudecode", CC_SAMPLE),
                               ("antigravity", AG_SAMPLE),
                               ("codex",       CX_SAMPLE),
                               ("codex",       CX_DESKTOP)]:
            out = tmp_path / f"{tool}2.csv"
            cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, \
            f"Smoke pipelines took {elapsed:.2f}s — too slow for a smoke test"


# ═════════════════════════════════════════════════════════════════════════════
# S08  Real data smoke — live data sanity check
# ═════════════════════════════════════════════════════════════════════════════

class TestS08RealDataSmoke:
    """Quick check that real installed tools produce at least one parseable session."""

    def test_real_claude_code_produces_sessions(self, tmp_path):
        if not REAL_CC.exists():
            pytest.skip("Claude Code not installed")
        from ai_tracker.parsers.claude_code import ClaudeCodeParser
        sessions = ClaudeCodeParser(REAL_CC).parse()
        assert len(sessions) > 0, "No Claude Code sessions found"
        msgs = [m for s in sessions for m in s.messages]
        assert any(m.role == "human" for m in msgs)

    def test_real_antigravity_produces_sessions(self, tmp_path):
        if not REAL_AG.exists():
            pytest.skip("Antigravity not installed")
        from ai_tracker.parsers.antigravity import AntigravityParser
        sessions = AntigravityParser(REAL_AG).parse()
        assert len(sessions) > 0, "No Antigravity sessions found"

    def test_real_codex_produces_sessions(self, tmp_path):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed")
        from ai_tracker.parsers.codex import CodexParser
        sessions = CodexParser(REAL_CX).parse()
        assert len(sessions) > 0, "No Codex sessions found"

    def test_real_claude_code_csv_valid(self, tmp_path):
        if not REAL_CC.exists():
            pytest.skip("Claude Code not installed")
        from ai_tracker.cli import cmd_parse
        from ai_tracker.exporters.csv_exporter import FIELDNAMES
        out = tmp_path / "real_cc.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(REAL_CC), output=str(out)))
        assert rc == 0
        with open(out, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == FIELDNAMES
            rows = list(reader)
        assert len(rows) > 0

    def test_real_codex_csv_valid(self, tmp_path):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed")
        from ai_tracker.cli import cmd_parse
        from ai_tracker.exporters.csv_exporter import FIELDNAMES
        out = tmp_path / "real_cx.csv"
        rc = cmd_parse(_args(tool="codex", file=str(REAL_CX), output=str(out)))
        assert rc == 0
        with open(out, encoding="utf-8") as fh:
            assert csv.DictReader(fh).fieldnames == FIELDNAMES
