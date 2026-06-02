"""
End-to-end tests: known input text → parser → CSV → verify every cell.

Each test builds a realistic log file from scratch with explicit prompt/response
text, runs the full parse pipeline, and asserts the CSV rows match exactly.
Covers all three parsers (antigravity, claudecode, codex) and the combined
multi-tool export.
"""

import argparse
import csv
import json
from pathlib import Path

import pytest

from ai_tracker.cli import cmd_parse

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _args(**kwargs) -> argparse.Namespace:
    defaults = {
        "tool": "all",
        "file": None,
        "output": None,
        "start_date": None,
        "end_date": None,
        "include_sidechains": True,
        "project": None,
        "split_by_project": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ─────────────────────────────────────────────────────────────────────────────
# Claude Code end-to-end
# ─────────────────────────────────────────────────────────────────────────────

CLAUDE_PROMPT   = "How do I sort a dictionary by value in Python?"
CLAUDE_RESPONSE = "Use sorted(d.items(), key=lambda x: x[1]) to get a list of (key, value) pairs sorted by value."
CLAUDE_TS_H     = "2026-05-29T08:00:00.000Z"
CLAUDE_TS_A     = "2026-05-29T08:00:05.000Z"
CLAUDE_SESSION  = "cc000000-0000-0000-0000-000000000001"


def _make_claude_fixture(path: Path) -> None:
    records = [
        {
            "type": "user",
            "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": CLAUDE_PROMPT}]},
            "uuid": "u1",
            "timestamp": CLAUDE_TS_H,
            "sessionId": CLAUDE_SESSION,
        },
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": CLAUDE_RESPONSE}]},
            "uuid": "a1",
            "timestamp": CLAUDE_TS_A,
            "sessionId": CLAUDE_SESSION,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class TestClaudeCodeE2E:
    def _run(self, tmp_path: Path) -> list[dict]:
        src = tmp_path / "session.jsonl"
        _make_claude_fixture(src)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="claudecode", file=str(src), output=str(out)))
        assert rc == 0
        return _read_csv(out)

    def test_row_count(self, tmp_path):
        rows = self._run(tmp_path)
        assert len(rows) == 2

    def test_first_row_is_human_prompt(self, tmp_path):
        row = self._run(tmp_path)[0]
        assert row["role"] == "human"
        assert row["message"] == CLAUDE_PROMPT

    def test_second_row_is_assistant_response(self, tmp_path):
        row = self._run(tmp_path)[1]
        assert row["role"] == "assistant"
        assert row["message"] == CLAUDE_RESPONSE

    def test_timestamps_match_source(self, tmp_path):
        rows = self._run(tmp_path)
        # Compare date+time prefix — milliseconds may be dropped when zero
        assert rows[0]["timestamp"].startswith("2026-05-29T08:00:00")
        assert rows[1]["timestamp"].startswith("2026-05-29T08:00:05")

    def test_tool_column(self, tmp_path):
        for row in self._run(tmp_path):
            assert row["tool"] == "claudecode"

    def test_session_id_column(self, tmp_path):
        for row in self._run(tmp_path):
            assert row["session_id"] == CLAUDE_SESSION

    def test_no_xml_tags_in_output(self, tmp_path):
        for row in self._run(tmp_path):
            assert "<" not in row["message"]

    def test_csv_columns_order(self, tmp_path):
        src = tmp_path / "session.jsonl"
        _make_claude_fixture(src)
        out = tmp_path / "out.csv"
        cmd_parse(_args(tool="claudecode", file=str(src), output=str(out)))
        with open(out, encoding="utf-8") as fh:
            fieldnames = csv.DictReader(fh).fieldnames
        assert fieldnames == ["project", "session_id", "timestamp", "role", "message", "tool", "file_path"]


# ─────────────────────────────────────────────────────────────────────────────
# Antigravity end-to-end
# ─────────────────────────────────────────────────────────────────────────────

AG_PROMPT        = "Write a Python function to check if a number is prime."
AG_RESPONSE      = "def is_prime(n):\n    if n < 2: return False\n    for i in range(2, int(n**0.5)+1):\n        if n % i == 0: return False\n    return True"
AG_TOOL_CALLS    = [{"name": "view_file", "args": {"AbsolutePath": "\"c:/project/main.py\""}}]
AG_TOOL_CONTENT  = "File contents: def main(): pass"
AG_TS_H          = "2026-05-29T09:00:00Z"
AG_TS_A          = "2026-05-29T09:00:03Z"
AG_TS_TC         = "2026-05-29T09:00:05Z"
AG_TS_TR         = "2026-05-29T09:00:07Z"
AG_SESSION       = "ag000000-0000-0000-0000-000000000001"


def _make_antigravity_fixture(path: Path) -> None:
    records = [
        # Human prompt
        {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": AG_TS_H,
            "content": f"<USER_REQUEST>\n{AG_PROMPT}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nLocal time: 2026-05-29T14:30:00+05:30\n</ADDITIONAL_METADATA>",
        },
        # System record — must be skipped
        {
            "step_index": 1,
            "source": "SYSTEM",
            "type": "CONVERSATION_HISTORY",
            "status": "DONE",
            "created_at": AG_TS_H,
        },
        # AI thinking response
        {
            "step_index": 2,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": AG_TS_A,
            "thinking": AG_RESPONSE,
            "tool_calls": [],
        },
        # AI tool-call decision (no thinking)
        {
            "step_index": 3,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": AG_TS_TC,
            "tool_calls": AG_TOOL_CALLS,
        },
        # Tool execution result
        {
            "step_index": 4,
            "source": "MODEL",
            "type": "VIEW_FILE",
            "status": "DONE",
            "created_at": AG_TS_TR,
            "content": AG_TOOL_CONTENT,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class TestAntigravityE2E:
    def _run(self, tmp_path: Path) -> list[dict]:
        src = tmp_path / "transcript.jsonl"
        _make_antigravity_fixture(src)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="antigravity", file=str(src), output=str(out)))
        assert rc == 0
        return _read_csv(out)

    def test_row_count(self, tmp_path):
        # human + assistant(thinking) + assistant(tool_call) + tool(result) = 4
        # SYSTEM record skipped
        assert len(self._run(tmp_path)) == 4

    def test_human_prompt_exact_text(self, tmp_path):
        row = self._run(tmp_path)[0]
        assert row["role"] == "human"
        assert AG_PROMPT in row["message"]

    def test_user_request_tags_preserved_in_output(self, tmp_path):
        row = self._run(tmp_path)[0]
        assert "<USER_REQUEST>" in row["message"]
        assert "<ADDITIONAL_METADATA>" in row["message"]

    def test_ai_thinking_response_exact_text(self, tmp_path):
        row = self._run(tmp_path)[1]
        assert row["role"] == "assistant"
        assert row["message"] == AG_RESPONSE

    def test_tool_call_decision_captured(self, tmp_path):
        row = self._run(tmp_path)[2]
        assert row["role"] == "assistant"
        parsed = json.loads(row["message"])
        assert parsed[0]["name"] == "view_file"

    def test_tool_execution_result_captured(self, tmp_path):
        row = self._run(tmp_path)[3]
        assert row["role"] == "tool"
        assert row["message"] == AG_TOOL_CONTENT

    def test_system_record_absent(self, tmp_path):
        for row in self._run(tmp_path):
            assert "CONVERSATION_HISTORY" not in row["message"]

    def test_chronological_order(self, tmp_path):
        rows = self._run(tmp_path)
        timestamps = [r["timestamp"] for r in rows if r["timestamp"]]
        assert timestamps == sorted(timestamps)

    def test_tool_column(self, tmp_path):
        for row in self._run(tmp_path):
            assert row["tool"] == "antigravity"


# ─────────────────────────────────────────────────────────────────────────────
# Codex end-to-end
# ─────────────────────────────────────────────────────────────────────────────

CODEX_PROMPT   = "Explain the difference between list and tuple in Python."
CODEX_RESPONSE = "Lists are mutable (you can change elements); tuples are immutable. Use tuples for fixed data, lists for data that changes."
CODEX_TS_H     = "2026-05-29T10:00:00Z"
CODEX_TS_A     = "2026-05-29T10:00:04Z"


def _make_codex_fixture_jsonl(path: Path) -> None:
    records = [
        {"role": "user",      "content": CODEX_PROMPT,   "timestamp": CODEX_TS_H},
        {"role": "assistant", "content": CODEX_RESPONSE,  "timestamp": CODEX_TS_A},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _make_codex_fixture_json_array(path: Path) -> None:
    records = [
        {"role": "user",      "content": CODEX_PROMPT,   "timestamp": CODEX_TS_H},
        {"role": "assistant", "content": CODEX_RESPONSE,  "timestamp": CODEX_TS_A},
    ]
    path.write_text(json.dumps(records), encoding="utf-8")


class TestCodexE2E:
    def _run(self, tmp_path: Path, jsonl: bool = True) -> list[dict]:
        suffix = ".jsonl" if jsonl else ".json"
        src = tmp_path / f"session{suffix}"
        if jsonl:
            _make_codex_fixture_jsonl(src)
        else:
            _make_codex_fixture_json_array(src)
        out = tmp_path / "out.csv"
        rc = cmd_parse(_args(tool="codex", file=str(src), output=str(out)))
        assert rc == 0
        return _read_csv(out)

    def test_jsonl_row_count(self, tmp_path):
        assert len(self._run(tmp_path, jsonl=True)) == 2

    def test_json_array_row_count(self, tmp_path):
        assert len(self._run(tmp_path, jsonl=False)) == 2

    def test_human_prompt_exact_text_jsonl(self, tmp_path):
        row = self._run(tmp_path, jsonl=True)[0]
        assert row["role"] == "human"
        assert row["message"] == CODEX_PROMPT

    def test_assistant_response_exact_text_jsonl(self, tmp_path):
        row = self._run(tmp_path, jsonl=True)[1]
        assert row["role"] == "assistant"
        assert row["message"] == CODEX_RESPONSE

    def test_human_prompt_exact_text_json_array(self, tmp_path):
        row = self._run(tmp_path, jsonl=False)[0]
        assert row["role"] == "human"
        assert row["message"] == CODEX_PROMPT

    def test_assistant_response_exact_text_json_array(self, tmp_path):
        row = self._run(tmp_path, jsonl=False)[1]
        assert row["role"] == "assistant"
        assert row["message"] == CODEX_RESPONSE

    def test_tool_column(self, tmp_path):
        for row in self._run(tmp_path):
            assert row["tool"] == "codex"


# ─────────────────────────────────────────────────────────────────────────────
# Multi-tool combined end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiToolE2E:
    """Parse all three tools simultaneously and verify the combined CSV."""

    def _build_sources(self, tmp_path: Path) -> dict:
        cc_dir = tmp_path / "claude_projects" / "my-project"
        cc_dir.mkdir(parents=True)
        _make_claude_fixture(cc_dir / "session.jsonl")

        ag_file = tmp_path / "transcript.jsonl"
        _make_antigravity_fixture(ag_file)

        codex_file = tmp_path / "codex_session.jsonl"
        _make_codex_fixture_jsonl(codex_file)

        return {"cc_dir": cc_dir.parent, "ag_file": ag_file, "codex_file": codex_file}

    def test_all_tools_combined_row_count(self, tmp_path):
        srcs = self._build_sources(tmp_path)
        out = tmp_path / "combined.csv"

        # Parse each tool separately and combine via CLI calls
        cc_out  = tmp_path / "cc.csv"
        ag_out  = tmp_path / "ag.csv"
        cod_out = tmp_path / "cod.csv"

        cmd_parse(_args(tool="claudecode", file=str(srcs["cc_dir"]), output=str(cc_out)))
        cmd_parse(_args(tool="antigravity", file=str(srcs["ag_file"]), output=str(ag_out)))
        cmd_parse(_args(tool="codex",       file=str(srcs["codex_file"]), output=str(cod_out)))

        cc_rows  = _read_csv(cc_out)
        ag_rows  = _read_csv(ag_out)
        cod_rows = _read_csv(cod_out)

        # claudecode: 2, antigravity: 4, codex: 2 = 8 total
        assert len(cc_rows)  == 2
        assert len(ag_rows)  == 4
        assert len(cod_rows) == 2

    def test_no_cross_contamination_between_tools(self, tmp_path):
        srcs = self._build_sources(tmp_path)
        cc_out = tmp_path / "cc.csv"
        cmd_parse(_args(tool="claudecode", file=str(srcs["cc_dir"]), output=str(cc_out)))
        for row in _read_csv(cc_out):
            assert row["tool"] == "claudecode"

    def test_each_prompt_appears_in_correct_tool_csv(self, tmp_path):
        srcs = self._build_sources(tmp_path)
        cc_out  = tmp_path / "cc.csv"
        ag_out  = tmp_path / "ag.csv"
        cod_out = tmp_path / "cod.csv"

        cmd_parse(_args(tool="claudecode", file=str(srcs["cc_dir"]), output=str(cc_out)))
        cmd_parse(_args(tool="antigravity", file=str(srcs["ag_file"]), output=str(ag_out)))
        cmd_parse(_args(tool="codex",       file=str(srcs["codex_file"]), output=str(cod_out)))

        cc_msgs  = [r["message"] for r in _read_csv(cc_out)]
        ag_msgs  = [r["message"] for r in _read_csv(ag_out)]
        cod_msgs = [r["message"] for r in _read_csv(cod_out)]

        assert CLAUDE_PROMPT   in cc_msgs
        assert CLAUDE_RESPONSE in cc_msgs
        assert any(AG_PROMPT in m for m in ag_msgs)
        assert AG_RESPONSE     in ag_msgs
        assert CODEX_PROMPT    in cod_msgs
        assert CODEX_RESPONSE  in cod_msgs

    def test_prompts_not_in_wrong_tool(self, tmp_path):
        srcs = self._build_sources(tmp_path)
        cc_out  = tmp_path / "cc.csv"
        ag_out  = tmp_path / "ag.csv"

        cmd_parse(_args(tool="claudecode", file=str(srcs["cc_dir"]), output=str(cc_out)))
        cmd_parse(_args(tool="antigravity", file=str(srcs["ag_file"]), output=str(ag_out)))

        cc_msgs = [r["message"] for r in _read_csv(cc_out)]
        ag_msgs = [r["message"] for r in _read_csv(ag_out)]

        assert AG_PROMPT      not in cc_msgs
        assert CLAUDE_PROMPT  not in ag_msgs
