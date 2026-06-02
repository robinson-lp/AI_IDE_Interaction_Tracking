"""
User Acceptance Testing (UAT)
==============================
Simulates real end-user workflows from start to finish.
Each class is a named user scenario — written from the perspective of
a developer, researcher, or team lead who is using ai-tracker in their
daily workflow.

Scenarios:
  UAT-01  First-time user checks what tools are available
  UAT-02  Developer exports a week of Claude Code conversations
  UAT-03  Developer exports Antigravity IDE conversations
  UAT-04  Developer exports Codex Desktop conversations
  UAT-05  Researcher exports everything from all tools in one file
  UAT-06  Team lead gets one CSV per project for team review
  UAT-07  Developer narrows output to a single project
  UAT-08  Developer filters conversations to a specific date range
  UAT-09  Developer excludes subagent noise from the export
  UAT-10  Developer verifies the audit trail (session_id + file_path)
  UAT-11  Developer handles a mixed-format Codex session directory
  UAT-12  Developer re-runs export to verify idempotency
  UAT-13  Developer runs on a machine where one tool is not installed
  UAT-14  Power user chains project filter + date filter + split
  UAT-15  Researcher validates CSV for import into Excel / analytics tool
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from ai_tracker.cli import cmd_list_tools, cmd_parse
from ai_tracker.exporters.csv_exporter import FIELDNAMES

# ── Paths ─────────────────────────────────────────────────────────────────────

FIXTURES    = Path(__file__).parent / "fixtures"
CC_FIXTURE  = FIXTURES / "claude_code_sample.jsonl"
AG_FIXTURE  = FIXTURES / "antigravity_transcript.jsonl"
CX_FIXTURE  = FIXTURES / "codex_sample.jsonl"
CX_DESKTOP  = FIXTURES / "codex_desktop_session.jsonl"

REAL_CC  = Path.home() / ".claude"  / "projects"
REAL_AG  = Path.home() / ".gemini"  / "antigravity-ide" / "brain"
REAL_CX  = Path.home() / ".codex"   / "sessions"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _args(**kw) -> argparse.Namespace:
    base = dict(tool="all", file=None, output=None, start_date=None,
                end_date=None, include_sidechains=True, project=None,
                split_by_project=False)
    base.update(kw)
    return argparse.Namespace(**base)

def _csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))

def _cc_session(tmp_path: Path, slug: str, messages: list[tuple[str, str, str]]) -> Path:
    """Write a Claude Code project directory with one session."""
    proj = tmp_path / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    records = []
    for i, (role, text, ts) in enumerate(messages):
        records.append({
            "type": role, "isSidechain": False,
            "message": {"role": role, "content": [{"type": "text", "text": text}]},
            "uuid": f"u{i}", "timestamp": ts, "sessionId": f"sess-{slug}",
        })
    f = proj / "session.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return tmp_path / "projects"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-01  First-time user checks what tools are available
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT01ListAvailableTools:
    """
    Scenario: Robin has just installed ai-tracker. Before running anything
    she wants to confirm which AI tools are detected on her machine and
    whether the expected data directories exist.

    She runs: ai-tracker list-tools
    """

    def test_command_completes_without_error(self, capsys):
        rc = cmd_list_tools(_args())
        assert rc == 0, "list-tools should always succeed"

    def test_output_names_all_three_supported_tools(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "claudecode"  in out, "Claude Code not listed"
        assert "antigravity" in out, "Antigravity not listed"
        assert "codex"       in out, "Codex not listed"

    def test_output_shows_whether_each_path_exists(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "found" in out, "Status column missing from output"

    def test_output_shows_data_paths(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        # At least one of the known home sub-paths should appear
        has_path = any(d in out for d in [".claude", ".gemini", ".codex", "Users"])
        assert has_path, "No data paths shown in list-tools output"

    def test_real_claude_code_found_on_this_machine(self, capsys):
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        if REAL_CC.exists():
            assert "claudecode" in out and "found" in out
        else:
            pytest.skip("Claude Code not installed on this machine")

    def test_real_antigravity_found_on_this_machine(self, capsys):
        if not REAL_AG.exists():
            pytest.skip("Antigravity not installed on this machine")
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "antigravity" in out

    def test_real_codex_found_on_this_machine(self, capsys):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed on this machine")
        cmd_list_tools(_args())
        out = capsys.readouterr().out
        assert "codex" in out


# ═════════════════════════════════════════════════════════════════════════════
# UAT-02  Developer exports a week of Claude Code conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT02ExportClaudeCodeConversations:
    """
    Scenario: Robin wants to review all her Claude Code conversations from
    this week. She points ai-tracker at her projects directory and exports
    to a CSV she can open in Excel.

    She runs: ai-tracker parse --tool claudecode --output week.csv
    """

    def test_export_produces_a_csv_file(self, tmp_path):
        out = tmp_path / "week.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        assert out.exists(), "No CSV file created"

    def test_csv_contains_human_and_assistant_messages(self, tmp_path):
        out = tmp_path / "week.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        roles = {r["role"] for r in rows}
        assert "human"     in roles, "No human messages in export"
        assert "assistant" in roles, "No assistant messages in export"

    def test_all_rows_tagged_as_claudecode(self, tmp_path):
        out = tmp_path / "week.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        assert all(r["tool"] == "claudecode" for r in rows)

    def test_timestamps_are_present_and_readable(self, tmp_path):
        out = tmp_path / "week.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        rows_with_ts = [r for r in rows if r["timestamp"]]
        assert len(rows_with_ts) > 0, "No timestamps found in export"
        # Each timestamp must start with a 4-digit year
        assert all(r["timestamp"][:4].isdigit() for r in rows_with_ts)

    def test_messages_are_in_chronological_order(self, tmp_path):
        out = tmp_path / "week.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        ts = [r["timestamp"] for r in rows if r["timestamp"]]
        assert ts == sorted(ts), "Exported messages are not in time order"

    def test_real_claude_code_data_exported(self, tmp_path):
        if not REAL_CC.exists():
            pytest.skip("Claude Code not installed")
        out = tmp_path / "real_cc.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(REAL_CC), output=str(out)))
        assert rc == 0
        rows = _csv(out)
        assert len(rows) > 0, "No messages exported from real Claude Code data"
        assert all(r["tool"] == "claudecode" for r in rows)


# ═════════════════════════════════════════════════════════════════════════════
# UAT-03  Developer exports Antigravity IDE conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT03ExportAntigravityConversations:
    """
    Scenario: Robin uses Antigravity IDE for coding assistance. She wants to
    export all her sessions to review what problems she asked about and how
    the AI responded.

    She runs: ai-tracker parse --tool antigravity --output antigravity.csv
    """

    def test_export_produces_csv(self, tmp_path):
        out = tmp_path / "antigravity.csv"
        rc = cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        assert rc == 0 and out.exists()

    def test_user_prompts_appear_as_human_messages(self, tmp_path):
        out = tmp_path / "antigravity.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        rows = _csv(out)
        human = [r for r in rows if r["role"] == "human"]
        assert len(human) >= 1, "No human messages in Antigravity export"

    def test_ai_thinking_captured_as_assistant(self, tmp_path):
        out = tmp_path / "antigravity.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        rows = _csv(out)
        ai = [r for r in rows if r["role"] == "assistant"]
        assert len(ai) >= 1, "No assistant messages in Antigravity export"

    def test_system_noise_not_in_export(self, tmp_path):
        out = tmp_path / "antigravity.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        rows = _csv(out)
        for row in rows:
            assert "CONVERSATION_HISTORY" not in row["message"], \
                "System context leaked into export"

    def test_all_rows_tagged_as_antigravity(self, tmp_path):
        out = tmp_path / "antigravity.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out)))
        rows = _csv(out)
        assert all(r["tool"] == "antigravity" for r in rows)

    def test_real_antigravity_data_exported(self, tmp_path):
        if not REAL_AG.exists():
            pytest.skip("Antigravity not installed")
        out = tmp_path / "real_ag.csv"
        rc = cmd_parse(_args(tool="antigravity", file=str(REAL_AG), output=str(out)))
        assert rc == 0
        rows = _csv(out)
        assert len(rows) > 0, "No messages from real Antigravity data"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-04  Developer exports Codex Desktop conversations
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT04ExportCodexConversations:
    """
    Scenario: Robin uses Codex Desktop for quick coding questions. She wants
    to export those sessions. Codex stores event-log JSONL files under
    ~/.codex/sessions/ — ai-tracker must auto-detect this format.

    She runs: ai-tracker parse --tool codex --output codex.csv
    """

    def test_codex_desktop_format_exported_successfully(self, tmp_path):
        out = tmp_path / "codex.csv"
        rc = cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        assert rc == 0 and out.exists()

    def test_user_prompts_captured(self, tmp_path):
        out = tmp_path / "codex.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        rows = _csv(out)
        human = [r for r in rows if r["role"] == "human"]
        assert len(human) >= 1

    def test_ai_final_answers_captured(self, tmp_path):
        out = tmp_path / "codex.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        rows = _csv(out)
        ai = [r for r in rows if r["role"] == "assistant"]
        assert len(ai) >= 1

    def test_intermediate_commentary_excluded(self, tmp_path):
        out = tmp_path / "codex.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        rows = _csv(out)
        assert not any("Thinking about" in r["message"] for r in rows), \
            "Commentary messages leaked into export"

    def test_project_name_readable(self, tmp_path):
        out = tmp_path / "codex.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out)))
        rows = _csv(out)
        projects = {r["project"] for r in rows}
        assert all(p != "" for p in projects), "Project column empty"
        assert not any(p.startswith("C:\\") for p in projects), \
            "Raw path appeared as project name"

    def test_real_codex_sessions_exported(self, tmp_path):
        if not REAL_CX.exists():
            pytest.skip("Codex not installed")
        out = tmp_path / "real_cx.csv"
        rc = cmd_parse(_args(tool="codex", file=str(REAL_CX), output=str(out)))
        assert rc == 0
        rows = _csv(out)
        assert len(rows) > 0
        assert all(r["tool"] == "codex" for r in rows)


# ═════════════════════════════════════════════════════════════════════════════
# UAT-05  Researcher exports everything from all tools in one file
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT05ExportAllToolsInOneFile:
    """
    Scenario: Robin is doing a monthly review. She wants one single CSV with
    every AI interaction she had — Claude Code, Antigravity, and Codex —
    sorted by time, so she can see her complete interaction history.

    She runs three separate parse commands and reviews the results.
    """

    def _export_all(self, tmp_path: Path) -> dict[str, list[dict]]:
        results = {}
        for tool, fixture in [("claudecode", CC_FIXTURE),
                               ("antigravity", AG_FIXTURE),
                               ("codex", CX_FIXTURE)]:
            out = tmp_path / f"{tool}.csv"
            cmd_parse(_args(tool=tool, file=str(fixture), output=str(out)))
            results[tool] = _csv(out)
        return results

    def test_all_three_tools_produce_output(self, tmp_path):
        results = self._export_all(tmp_path)
        for tool, rows in results.items():
            assert len(rows) > 0, f"No rows for {tool}"

    def test_no_tool_contaminates_another(self, tmp_path):
        results = self._export_all(tmp_path)
        for tool, rows in results.items():
            assert all(r["tool"] == tool for r in rows), \
                f"Cross-tool contamination in {tool} export"

    def test_each_csv_internally_chronological(self, tmp_path):
        results = self._export_all(tmp_path)
        for tool, rows in results.items():
            ts = [r["timestamp"] for r in rows if r["timestamp"]]
            assert ts == sorted(ts), f"{tool} rows not in time order"

    def test_total_message_count_across_all_tools(self, tmp_path):
        results = self._export_all(tmp_path)
        total = sum(len(rows) for rows in results.values())
        assert total >= 9, f"Expected at least 9 total messages, got {total}"

    def test_all_csvs_have_identical_column_schema(self, tmp_path):
        results = self._export_all(tmp_path)
        for tool, rows in results.items():
            assert rows[0].keys() == set(FIELDNAMES), \
                f"{tool} CSV has wrong columns: {list(rows[0].keys())}"

    def test_real_all_tools_combined(self, tmp_path):
        available = [(t, p) for t, p in [("claudecode", REAL_CC),
                                          ("antigravity", REAL_AG),
                                          ("codex",       REAL_CX)]
                     if p.exists()]
        if not available:
            pytest.skip("No real tool data found")
        for tool, path in available:
            out = tmp_path / f"{tool}.csv"
            rc = cmd_parse(_args(tool=tool, file=str(path), output=str(out)))
            assert rc == 0, f"Export failed for {tool}"
            rows = _csv(out)
            assert len(rows) > 0


# ═════════════════════════════════════════════════════════════════════════════
# UAT-06  Team lead gets one CSV per project for team review
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT06SplitExportByProject:
    """
    Scenario: Robin leads a team with multiple active projects. She wants
    to share a separate CSV with each project's AI interactions, so each
    team can review only their own sessions.

    She runs: ai-tracker parse --tool claudecode --split-by-project -o reviews/
    """

    def _three_project_dir(self, tmp_path: Path) -> Path:
        projects = {
            "invoice-app":    [("user", "How do I add tax calculations?",   "2026-05-01T08:00:00Z"),
                               ("assistant", "Use a tax_rate multiplier.", "2026-05-01T08:00:05Z")],
            "data-pipeline":  [("user", "How do I batch process files?",   "2026-05-01T09:00:00Z"),
                               ("assistant", "Use concurrent.futures.",   "2026-05-01T09:00:05Z")],
            "auth-service":   [("user", "How do I hash passwords?",        "2026-05-01T10:00:00Z"),
                               ("assistant", "Use bcrypt.",                "2026-05-01T10:00:05Z")],
        }
        for slug, msgs in projects.items():
            _cc_session(tmp_path, slug, msgs)
        return tmp_path / "projects"

    def test_one_csv_file_created_per_project(self, tmp_path):
        root = self._three_project_dir(tmp_path)
        out_dir = tmp_path / "reviews"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        assert len(list(out_dir.glob("*.csv"))) == 3

    def test_each_csv_contains_only_its_project(self, tmp_path):
        root = self._three_project_dir(tmp_path)
        out_dir = tmp_path / "reviews"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            rows = _csv(f)
            projects_in_file = {r["project"] for r in rows}
            assert len(projects_in_file) == 1, \
                f"{f.name} contains messages from multiple projects"

    def test_csv_filenames_are_project_names(self, tmp_path):
        root = self._three_project_dir(tmp_path)
        out_dir = tmp_path / "reviews"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        stems = {f.stem for f in out_dir.glob("*.csv")}
        assert "invoice_app"   in stems, "invoice-app CSV not found"
        assert "data_pipeline" in stems, "data-pipeline CSV not found"
        assert "auth_service"  in stems, "auth-service CSV not found"

    def test_every_project_has_both_roles(self, tmp_path):
        root = self._three_project_dir(tmp_path)
        out_dir = tmp_path / "reviews"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        for f in out_dir.glob("*.csv"):
            rows = _csv(f)
            roles = {r["role"] for r in rows}
            assert "human"     in roles, f"{f.name} missing human role"
            assert "assistant" in roles, f"{f.name} missing assistant role"

    def test_total_messages_preserved_across_all_csvs(self, tmp_path):
        root = self._three_project_dir(tmp_path)
        out_dir = tmp_path / "reviews"
        flat_out = tmp_path / "flat.csv"
        cmd_parse(_args(tool="claudecode", file=str(root), output=str(flat_out)))
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_dir), split_by_project=True))
        flat_count  = len(_csv(flat_out))
        split_count = sum(len(_csv(f)) for f in out_dir.glob("*.csv"))
        assert flat_count == split_count, \
            "Split-by-project lost or duplicated messages"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-07  Developer narrows output to a single project
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT07FilterToSingleProject:
    """
    Scenario: Robin is debugging an issue in her "AI Tracking System" project.
    She only wants conversations from that project, not everything else.

    She runs: ai-tracker parse --tool claudecode --project "tracking" -o tracking.csv
    """

    def _mixed_projects(self, tmp_path: Path) -> Path:
        for slug, text in [
            ("ai-tracking-system-python-script", "How do I parse JSONL in Python?"),
            ("invoice-app",  "How do I format currency?"),
            ("my-blog-site", "How do I add pagination?"),
        ]:
            _cc_session(tmp_path, slug,
                        [("user", text, "2026-05-01T10:00:00Z")])
        return tmp_path / "projects"

    def test_only_matching_project_in_output(self, tmp_path):
        root = self._mixed_projects(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out), project="tracking"))
        rows = _csv(out)
        assert all("tracking" in r["project"].lower() for r in rows)

    def test_other_projects_not_in_output(self, tmp_path):
        root = self._mixed_projects(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out), project="tracking"))
        rows = _csv(out)
        assert not any("invoice" in r["project"].lower() for r in rows)
        assert not any("blog"    in r["project"].lower() for r in rows)

    def test_filter_is_case_insensitive(self, tmp_path):
        root = self._mixed_projects(tmp_path)
        out_l = tmp_path / "lower.csv"
        out_u = tmp_path / "upper.csv"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_l), project="tracking"))
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out_u), project="TRACKING"))
        assert len(_csv(out_l)) == len(_csv(out_u))

    def test_partial_project_name_works(self, tmp_path):
        root = self._mixed_projects(tmp_path)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(root),
                             output=str(out), project="python"))
        assert rc == 0

    def test_message_content_is_correct_project(self, tmp_path):
        root = self._mixed_projects(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(root),
                        output=str(out), project="tracking"))
        rows = _csv(out)
        assert any("JSONL" in r["message"] for r in rows), \
            "Expected tracking project message not found"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-08  Developer filters conversations to a specific date range
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT08FilterByDateRange:
    """
    Scenario: Robin wants only conversations from a specific sprint
    (May 20–26, 2026) to assess how much AI assistance was used that week.

    She runs: ai-tracker parse --start-date 2026-05-20 --end-date 2026-05-26 -o sprint.csv
    """

    def _sprint_sessions(self, tmp_path: Path) -> Path:
        proj = tmp_path / "projects" / "sprint-work"
        proj.mkdir(parents=True)
        records = [
            # Before sprint
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": [{"type": "text", "text": "Pre-sprint question"}]},
             "uuid": "u0", "timestamp": "2026-05-15T10:00:00Z", "sessionId": "s1"},
            # During sprint
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": [{"type": "text", "text": "Sprint day question"}]},
             "uuid": "u1", "timestamp": "2026-05-22T10:00:00Z", "sessionId": "s1"},
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Sprint day answer"}]},
             "uuid": "a1", "timestamp": "2026-05-22T10:00:05Z", "sessionId": "s1"},
            # After sprint
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": [{"type": "text", "text": "Post-sprint question"}]},
             "uuid": "u2", "timestamp": "2026-06-01T10:00:00Z", "sessionId": "s1"},
        ]
        (proj / "session.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )
        return tmp_path / "projects"

    def test_only_sprint_dates_in_output(self, tmp_path):
        root = self._sprint_sessions(tmp_path)
        out = tmp_path / "sprint.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 26),
        ))
        rows = _csv(out)
        for r in rows:
            if r["timestamp"]:
                assert "2026-05-2" in r["timestamp"], \
                    f"Out-of-sprint message included: {r['timestamp']}"

    def test_pre_sprint_messages_excluded(self, tmp_path):
        root = self._sprint_sessions(tmp_path)
        out = tmp_path / "sprint.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 26),
        ))
        rows = _csv(out)
        assert not any("Pre-sprint" in r["message"] for r in rows)

    def test_post_sprint_messages_excluded(self, tmp_path):
        root = self._sprint_sessions(tmp_path)
        out = tmp_path / "sprint.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 26),
        ))
        rows = _csv(out)
        assert not any("Post-sprint" in r["message"] for r in rows)

    def test_sprint_day_messages_included(self, tmp_path):
        root = self._sprint_sessions(tmp_path)
        out = tmp_path / "sprint.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 26),
        ))
        rows = _csv(out)
        assert any("Sprint day" in r["message"] for r in rows)

    def test_full_day_coverage_end_date(self, tmp_path):
        """Messages timestamped at any time on end_date must be included."""
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(CC_FIXTURE), output=str(out),
            start_date=datetime(2026, 5, 20),
            end_date=datetime(2026, 5, 20),
        ))
        rows = _csv(out)
        assert len(rows) > 0, "End-date full-day coverage failed"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-09  Developer excludes subagent noise from the export
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT09ExcludeSubagentNoise:
    """
    Scenario: Robin noticed that exported CSVs contain many short subagent
    messages from Claude Code's internal tool calls. She wants a clean export
    with only the main conversation, not the subagent chatter.

    She runs: ai-tracker parse --tool claudecode --no-sidechains -o clean.csv
    """

    def test_sidechain_messages_included_by_default(self, tmp_path):
        out = tmp_path / "with_sc.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=True))
        rows_with = _csv(out)
        assert any("Subagent" in r["message"] for r in rows_with), \
            "Expected sidechain message not found in default export"

    def test_no_sidechains_produces_cleaner_output(self, tmp_path):
        out_all   = tmp_path / "all.csv"
        out_clean = tmp_path / "clean.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out_all),   include_sidechains=True))
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out_clean), include_sidechains=False))
        assert len(_csv(out_clean)) < len(_csv(out_all)), \
            "--no-sidechains produced same count as default"

    def test_sidechain_text_absent_in_clean_export(self, tmp_path):
        out = tmp_path / "clean.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        rows = _csv(out)
        assert not any("Subagent" in r["message"] for r in rows), \
            "Sidechain text still present after --no-sidechains"

    def test_main_conversation_intact_after_sidechain_removal(self, tmp_path):
        out = tmp_path / "clean.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE),
                        output=str(out), include_sidechains=False))
        rows = _csv(out)
        roles = {r["role"] for r in rows}
        assert "human"     in roles, "Human messages removed along with sidechains"
        assert "assistant" in roles, "Assistant messages removed along with sidechains"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-10  Developer verifies the audit trail
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT10AuditTrail:
    """
    Scenario: Robin's team lead asks for traceability — for any row in the CSV,
    can Robin tell exactly which session file it came from and what the
    conversation ID is? This is needed for compliance and reproducibility.

    She inspects the session_id and file_path columns.
    """

    def test_every_row_has_session_id(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        assert all(r["session_id"].strip() for r in rows), \
            "Some rows missing session_id"

    def test_every_row_has_file_path(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        assert all(r["file_path"].strip() for r in rows), \
            "Some rows missing file_path"

    def test_file_path_points_to_actual_source(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        for r in rows:
            src = Path(r["file_path"])
            assert src.exists(), f"Source file no longer exists: {r['file_path']}"

    def test_session_id_consistent_within_session(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        # All rows from the same file should share the same session_id
        by_file: dict[str, set[str]] = {}
        for r in rows:
            by_file.setdefault(r["file_path"], set()).add(r["session_id"])
        for fp, sids in by_file.items():
            assert len(sids) == 1, \
                f"Multiple session_ids from single file {fp}: {sids}"

    def test_antigravity_session_id_is_uuid_dir_name(self, tmp_path):
        brain = tmp_path / "brain"
        uid = "aaaa0000-beef-cafe-dead-000000000001"
        logs = brain / uid / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        r = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
             "status": "DONE", "created_at": "2026-05-01T10:00:00Z", "content": "Q"}
        (logs / "transcript.jsonl").write_text(json.dumps(r) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="antigravity", file=str(brain), output=str(out)))
        rows = _csv(out)
        assert rows[0]["session_id"] == uid


# ═════════════════════════════════════════════════════════════════════════════
# UAT-11  Developer handles a mixed-format Codex session directory
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT11MixedFormatCodexDirectory:
    """
    Scenario: Robin's ~/.codex/sessions directory contains sessions created
    by different versions of Codex — some are simple JSONL, some JSON arrays,
    and some are the new Codex Desktop event-log format. She wants them all.

    She runs: ai-tracker parse --tool codex --output all_codex.csv
    """

    def _mixed_codex_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "codex_sessions"
        d.mkdir()

        # Simple JSONL
        (d / "simple.jsonl").write_text(
            '{"role":"user","content":"Simple question","timestamp":"2026-05-01T08:00:00Z"}\n'
            '{"role":"assistant","content":"Simple answer","timestamp":"2026-05-01T08:00:02Z"}\n',
            encoding="utf-8",
        )
        # JSON array
        (d / "array.json").write_text(
            '[{"role":"user","content":"Array question","timestamp":"2026-05-01T09:00:00Z"},'
            '{"role":"assistant","content":"Array answer","timestamp":"2026-05-01T09:00:02Z"}]',
            encoding="utf-8",
        )
        # Codex Desktop
        desktop = [
            {"timestamp": "2026-05-01T10:00:00Z", "type": "session_meta",
             "payload": {"id": "dt-123", "cwd": "C:\\Users\\Robin\\my-project",
                         "originator": "Codex Desktop"}},
            {"timestamp": "2026-05-01T10:00:01Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": "Desktop question"}},
            {"timestamp": "2026-05-01T10:00:05Z", "type": "event_msg",
             "payload": {"type": "agent_message",
                         "message": "Desktop answer", "phase": "final_answer"}},
        ]
        (d / "desktop.jsonl").write_text(
            "\n".join(json.dumps(r) for r in desktop) + "\n", encoding="utf-8"
        )
        return d

    def test_all_three_formats_present_in_output(self, tmp_path):
        src = self._mixed_codex_dir(tmp_path)
        out = tmp_path / "all_codex.csv"
        rc = cmd_parse(_args(tool="codex", file=str(src), output=str(out)))
        assert rc == 0
        rows = _csv(out)
        messages = [r["message"] for r in rows]
        assert any("Simple question"  in m for m in messages), "JSONL format missing"
        assert any("Array question"   in m for m in messages), "JSON array format missing"
        assert any("Desktop question" in m for m in messages), "Desktop format missing"

    def test_total_row_count_correct(self, tmp_path):
        src = self._mixed_codex_dir(tmp_path)
        out = tmp_path / "all_codex.csv"
        cmd_parse(_args(tool="codex", file=str(src), output=str(out)))
        rows = _csv(out)
        # simple(2) + array(2) + desktop(2) = 6
        assert len(rows) == 6, f"Expected 6 rows, got {len(rows)}"

    def test_all_rows_tagged_codex(self, tmp_path):
        src = self._mixed_codex_dir(tmp_path)
        out = tmp_path / "all_codex.csv"
        cmd_parse(_args(tool="codex", file=str(src), output=str(out)))
        rows = _csv(out)
        assert all(r["tool"] == "codex" for r in rows)


# ═════════════════════════════════════════════════════════════════════════════
# UAT-12  Developer re-runs export to verify idempotency
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT12IdempotentExports:
    """
    Scenario: Robin runs the export twice in a row, checks that the output
    is identical both times. This is important for reproducibility and to
    confirm there is no state leak between runs.
    """

    def test_claude_code_same_output_twice(self, tmp_path):
        out1 = tmp_path / "run1.csv"
        out2 = tmp_path / "run2.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out1)))
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out2)))
        assert _csv(out1) == _csv(out2), "Second run produced different output"

    def test_antigravity_same_output_twice(self, tmp_path):
        out1 = tmp_path / "run1.csv"
        out2 = tmp_path / "run2.csv"
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out1)))
        cmd_parse(_args(tool="antigravity", file=str(AG_FIXTURE), output=str(out2)))
        assert _csv(out1) == _csv(out2)

    def test_codex_same_output_twice(self, tmp_path):
        out1 = tmp_path / "run1.csv"
        out2 = tmp_path / "run2.csv"
        cmd_parse(_args(tool="codex", file=str(CX_FIXTURE), output=str(out1)))
        cmd_parse(_args(tool="codex", file=str(CX_FIXTURE), output=str(out2)))
        assert _csv(out1) == _csv(out2)

    def test_codex_desktop_same_output_twice(self, tmp_path):
        out1 = tmp_path / "run1.csv"
        out2 = tmp_path / "run2.csv"
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out1)))
        cmd_parse(_args(tool="codex", file=str(CX_DESKTOP), output=str(out2)))
        assert _csv(out1) == _csv(out2)

    def test_session_ids_stable_across_runs(self, tmp_path):
        out1 = tmp_path / "r1.csv"
        out2 = tmp_path / "r2.csv"
        cmd_parse(_args(tool="codex", file=str(CX_FIXTURE), output=str(out1)))
        cmd_parse(_args(tool="codex", file=str(CX_FIXTURE), output=str(out2)))
        ids1 = [r["session_id"] for r in _csv(out1)]
        ids2 = [r["session_id"] for r in _csv(out2)]
        assert ids1 == ids2, "Session IDs changed between runs"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-13  Developer runs on a machine where one tool is not installed
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT13MissingToolGracefulSkip:
    """
    Scenario: Robin runs ai-tracker on a colleague's machine where Codex
    is not installed. She expects the tool to skip Codex gracefully and
    still export Claude Code and Antigravity data, rather than crashing.
    """

    def test_missing_tool_path_produces_stderr_skip_message(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="codex",
            file=str(tmp_path / "nonexistent_codex_dir"),
            output=str(out),
        ))
        err = capsys.readouterr().err
        assert "Skipped" in err or "No messages" in err, \
            "No skip message in stderr for missing tool"

    def test_missing_tool_does_not_crash(self, tmp_path):
        out = tmp_path / "out.csv"
        # Should not raise an exception — just return non-zero
        try:
            rc = cmd_parse(_args(
                tool="codex",
                file=str(tmp_path / "nonexistent"),
                output=str(out),
            ))
            assert rc == 1
        except Exception as exc:
            pytest.fail(f"cmd_parse raised exception for missing tool: {exc}")

    def test_empty_file_handled_gracefully(self, tmp_path, capsys):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(empty), output=str(out)))
        assert rc == 1
        err = capsys.readouterr().err
        assert "No messages" in err

    def test_list_tools_succeeds_even_when_paths_missing(self, capsys):
        rc = cmd_list_tools(_args())
        assert rc == 0, "list-tools failed when some tool paths are missing"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-14  Power user chains project filter + date filter + split
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT14ChainedFiltersWithSplit:
    """
    Scenario: Robin wants a very specific export: only "invoice-app" conversations
    from May 2026, split into per-project files (even though there's only one
    project after filtering). This tests the full filter chain end-to-end.
    """

    def _multi_project_multi_date(self, tmp_path: Path) -> Path:
        sessions = [
            ("invoice-app", "2026-05-15T10:00:00Z", "May invoice question"),
            ("invoice-app", "2026-06-01T10:00:00Z", "June invoice question"),
            ("blog-site",   "2026-05-15T11:00:00Z", "May blog question"),
        ]
        root = tmp_path / "projects"
        for slug, ts, text in sessions:
            proj = root / slug
            proj.mkdir(parents=True, exist_ok=True)
            r = {
                "type": "user", "isSidechain": False,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "uuid": "u1", "timestamp": ts, "sessionId": f"s-{slug}",
            }
            session_path = proj / "session.jsonl"
            existing = session_path.read_text(encoding="utf-8") if session_path.exists() else ""
            session_path.write_text(existing + json.dumps(r) + "\n", encoding="utf-8")
        return root

    def test_project_and_date_filter_combined(self, tmp_path):
        root = self._multi_project_multi_date(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            project="invoice",
            start_date=datetime(2026, 5, 1),
            end_date=datetime(2026, 5, 31),
        ))
        rows = _csv(out)
        assert len(rows) == 1
        assert "May invoice" in rows[0]["message"]

    def test_june_message_excluded_by_date_filter(self, tmp_path):
        root = self._multi_project_multi_date(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            project="invoice",
            start_date=datetime(2026, 5, 1),
            end_date=datetime(2026, 5, 31),
        ))
        rows = _csv(out)
        assert not any("June" in r["message"] for r in rows)

    def test_blog_excluded_by_project_filter(self, tmp_path):
        root = self._multi_project_multi_date(tmp_path)
        out = tmp_path / "out.csv"
        cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out),
            project="invoice",
            start_date=datetime(2026, 5, 1),
            end_date=datetime(2026, 5, 31),
        ))
        rows = _csv(out)
        assert not any("blog" in r["message"].lower() for r in rows)

    def test_project_filter_and_split_combined(self, tmp_path):
        root = self._multi_project_multi_date(tmp_path)
        out_dir = tmp_path / "out"
        rc = cmd_parse(_args(
            tool="claudecode", file=str(root), output=str(out_dir),
            project="invoice", split_by_project=True,
        ))
        assert rc == 0
        csvs = list(out_dir.glob("*.csv"))
        assert len(csvs) == 1, \
            f"Expected 1 CSV after project filter + split, got {len(csvs)}"


# ═════════════════════════════════════════════════════════════════════════════
# UAT-15  Researcher validates CSV for Excel / analytics import
# ═════════════════════════════════════════════════════════════════════════════

class TestUAT15CSVReadyForAnalytics:
    """
    Scenario: Robin's team will import the CSV into Excel, Pandas, or a BI tool.
    She checks that the CSV is well-formed: correct headers, string values,
    no empty required fields, no broken encoding, correct column count,
    and no accidental BOM or line-ending issues.
    """

    def test_csv_has_exactly_seven_columns(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
        assert len(header) == 7, f"Expected 7 columns, got {len(header)}"

    def test_header_matches_expected_names(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            fieldnames = csv.DictReader(fh).fieldnames
        assert fieldnames == FIELDNAMES

    def test_no_bom_in_csv_file(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        raw = out.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), \
            "CSV has a UTF-8 BOM which breaks some parsers"

    def test_all_values_are_strings_not_none(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        for row in rows:
            for col, val in row.items():
                assert isinstance(val, str), \
                    f"Column {col!r} has non-string value: {val!r}"

    def test_required_columns_never_empty(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        required = ["session_id", "role", "message", "tool"]
        for row in rows:
            for col in required:
                assert row[col].strip(), f"Required column {col!r} is empty in row: {row}"

    def test_role_values_are_controlled_vocabulary(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        allowed_roles = {"human", "assistant", "tool"}
        for row in rows:
            assert row["role"] in allowed_roles, \
                f"Unexpected role value: {row['role']!r}"

    def test_tool_values_are_controlled_vocabulary(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        rows = _csv(out)
        for row in rows:
            assert row["tool"] in {"claudecode", "antigravity", "codex"}, \
                f"Unexpected tool value: {row['tool']!r}"

    def test_unicode_preserved_correctly_in_csv(self, tmp_path):
        f = tmp_path / "s.jsonl"
        text = "日本語テスト 🚀 émoji café"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f.write_text(json.dumps(r) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(f), output=str(out)))
        rows = _csv(out)
        assert rows[0]["message"] == text, \
            f"Unicode not preserved: got {rows[0]['message']!r}"

    def test_csv_parseable_by_standard_library_csv_reader(self, tmp_path):
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(CC_FIXTURE), output=str(out)))
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) > 0

    def test_multiline_message_does_not_break_csv(self, tmp_path):
        f = tmp_path / "s.jsonl"
        multiline = "Line one\nLine two\nLine three"
        r = {
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": multiline}]},
            "uuid": "u1", "timestamp": "2026-05-01T10:00:00Z", "sessionId": "s1",
        }
        f.write_text(json.dumps(r) + "\n", encoding="utf-8")
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(f), output=str(out)))
        rows = _csv(out)
        assert len(rows) == 1
        assert rows[0]["message"] == multiline
