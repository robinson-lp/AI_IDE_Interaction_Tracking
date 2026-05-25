# AI Interaction Tracking System — Phase 1 Implementation

**Status:** Complete  
**Date:** May 2026  
**Scope:** Python File Parser for AI IDE Tools

---

## 1. Overview

Phase 1 implements a local Python CLI tool that reads session files written to disk by AI IDE tools, parses the conversation history, and exports a structured CSV of all AI interactions.

No API keys, no internet access, no browser automation required — it reads files the IDE tools have already written locally.

---

## 2. Tools Supported

| Tool | Data Found | Default Path |
|---|---|---|
| Claude Code | Yes | `~/.claude/projects/` |
| Antigravity | No (not installed) | `~/.gemini/antigravity/brain/overview.txt` |
| Codex | No (not installed) | `~/.codex/` |

Antigravity and Codex parsers are fully implemented and will activate automatically once those tools are installed and have session data on disk.

---

## 3. CSV Output Schema

Every exported row represents one message turn (one human prompt or one AI response).

| Column | Description | Example |
|---|---|---|
| `session_id` | Unique identifier for the session | `412a0856-1411-4a2f-900c-772ff7a42970` |
| `timestamp` | ISO 8601 date and time the message was sent | `2026-05-20T06:09:37.467000+00:00` |
| `role` | Speaker — `human` or `assistant` | `human` |
| `message` | Full text of the prompt or AI response | `How do I reverse a list in Python?` |
| `tool` | IDE tool that produced the message | `claudecode` |
| `file_path` | Absolute path of the source session file | `C:\Users\Robin\.claude\projects\...\session.jsonl` |

---

## 4. Project Structure

```
AI TRACKING SYSTEM PYTHON SCRIPT/
│
├── ai_tracker/                    # Main Python package
│   ├── __init__.py
│   ├── models.py                  # Message and ParsedSession dataclasses
│   ├── config.py                  # Tool paths and YAML config loader
│   ├── cli.py                     # Command-line interface (argparse)
│   │
│   ├── parsers/
│   │   ├── __init__.py            # Parser registry
│   │   ├── base.py                # Abstract BaseParser + date filter
│   │   ├── claude_code.py         # JSONL parser for ~/.claude/projects/
│   │   ├── antigravity.py         # Multi-format text parser for overview.txt
│   │   └── codex.py               # JSON/JSONL parser for ~/.codex/
│   │
│   └── exporters/
│       ├── __init__.py
│       └── csv_exporter.py        # UTF-8 CSV writer
│
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   ├── claude_code_sample.jsonl
│   │   ├── antigravity_colon.txt
│   │   ├── antigravity_bracket.txt
│   │   └── antigravity_timestamped.txt
│   ├── test_claude_code_parser.py  # 15 tests
│   ├── test_antigravity_parser.py  # 15 tests
│   └── test_csv_exporter.py        # 9 tests
│
├── config/
│   └── tools.yaml                 # Override tool paths and settings
│
├── ai-tracker.ps1                 # PowerShell wrapper script
├── pyproject.toml                 # Package definition and dependencies
└── IMPLEMENTATION.md              # This document
```

---

## 5. Parser Details

### 5.1 Claude Code Parser

**File:** `ai_tracker/parsers/claude_code.py`

Claude Code writes one `.jsonl` file per session under `~/.claude/projects/<project-slug>/`. Each line is a JSON event. The parser:

- Scans all `.jsonl` files recursively under the projects directory
- Skips non-conversation events (`queue-operation`, `attachment`, `system`)
- Skips subagent/sidechain threads by default (enable with `--include-sidechains`)
- Extracts `sessionId`, `timestamp`, `role`, and `content` from each event
- Handles content as either a plain string or a list of typed blocks

**JSONL record format observed:**
```json
{
  "type": "user",
  "isSidechain": false,
  "sessionId": "412a0856-...",
  "timestamp": "2026-05-20T06:09:37.467Z",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "How do I reverse a list?" }]
  }
}
```

### 5.2 Antigravity Parser

**File:** `ai_tracker/parsers/antigravity.py`

Antigravity's `overview.txt` format is not publicly documented. The parser attempts five formats in order and uses the first that matches:

| Priority | Format | Example |
|---|---|---|
| 1 | Colon-separated | `Human: ...` / `Assistant: ...` |
| 2 | Bracket blocks | `[Human]` / `[Assistant]` |
| 3 | Chevron style | `>>> Human` / `>>> Assistant` |
| 4 | JSONL | `{"role":"user","content":"..."}` |
| 5 | Alternating paragraphs | Even paragraphs = human, odd = assistant |

Timestamps in the format `[2026-05-20 09:00:00]` are automatically stripped from the message body and stored in the `timestamp` column.

### 5.3 Codex Parser

**File:** `ai_tracker/parsers/codex.py`

Handles both JSON array files and JSONL files. Supports role normalisation and Unix/ISO timestamp formats. Ready to activate when Codex session data is present at `~/.codex/`.

---

## 6. Configuration

Tool paths and settings can be overridden in `config/tools.yaml` without touching any code:

```yaml
tools:
  antigravity:
    path: ~/.gemini/antigravity/brain/overview.txt

  claudecode:
    path: ~/.claude/projects
    include_sidechains: false   # set true to include subagent threads

  codex:
    path: ~/.codex
```

---

## 7. CLI Reference

Run all commands from the project directory using the PowerShell wrapper:

```powershell
# Show which tools have data on disk
.\ai-tracker.ps1 list-tools

# Export all tools (skips missing ones automatically)
.\ai-tracker.ps1 parse --tool all --output interactions.csv

# Export Claude Code only
.\ai-tracker.ps1 parse --tool claudecode --output interactions.csv

# Filter by date range
.\ai-tracker.ps1 parse --tool claudecode --start-date 2026-05-01 --end-date 2026-05-31 --output may.csv

# Parse a specific file instead of the default path
.\ai-tracker.ps1 parse --tool antigravity --file "C:\path\to\overview.txt" --output ag.csv

# Include Claude Code subagent conversations
.\ai-tracker.ps1 parse --tool claudecode --include-sidechains --output full.csv
```

### CLI Flags

| Flag | Short | Description |
|---|---|---|
| `--tool` | | `antigravity`, `claudecode`, `codex`, or `all` |
| `--output` | `-o` | Output CSV file path |
| `--file` | `-f` | Override the default source file or directory |
| `--start-date` | | Filter messages from this date (YYYY-MM-DD) |
| `--end-date` | | Filter messages up to this date (YYYY-MM-DD) |
| `--include-sidechains` | | Include Claude Code subagent threads |

---

## 8. Test Results

**39 tests — all passing** (Python 3.13, pytest 9.0.3)

| Test file | Tests | Coverage |
|---|---|---|
| `test_claude_code_parser.py` | 15 | JSONL parsing, role normalisation, sidechain filtering, directory scanning, missing file handling |
| `test_antigravity_parser.py` | 15 | All 5 format detections, timestamp stripping, empty file, missing file, JSONL fallback |
| `test_csv_exporter.py` | 9 | File creation, directory creation, row count, headers, Unicode, null timestamps |

**Live run result:** 425 messages exported from real Claude Code sessions on disk.

---

## 9. How to Run

Python is not currently in the system PATH. Use the PowerShell wrapper which points directly to the available Python installation:

```powershell
cd "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
.\ai-tracker.ps1 parse --tool all --output interactions.csv
```

**To enable the plain `ai-tracker` command system-wide:**
1. Install Python 3.10+ from python.org (check "Add to PATH" during setup)
2. Run `pip install -e ".[dev]"` from the project directory
3. Use `ai-tracker parse --tool all --output interactions.csv` directly

---

## 10. Phase 2 — Not Yet Implemented

Phase 2 is a Chrome Extension for web-based AI tools (ChatGPT, Claude.ai, Gemini). It is scoped separately and will produce CSV output using the same schema defined above.

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Antigravity changes its file format | `config/tools.yaml` lets you update the path without code changes. Parser auto-detects format. |
| Claude Code changes its JSONL structure | Parser targets stable fields (`type`, `role`, `content`, `sessionId`, `timestamp`). Version-test when upgrading Claude Code. |
| Codex not yet observed on this machine | Parser is implemented and ready; will activate automatically when `~/.codex/` exists. |
| Antigravity file format unknown | Five-format auto-detection covers all common plain-text conversation layouts. |
