# AI Interaction Tracking System — Phase 1 Documentation

> **Scope:** Python File Parser for AI IDE Tools  
> **Status:** Complete and verified  
> **Python:** 3.10+  
> **Tests:** 47 / 47 passing

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Problem It Solves](#2-problem-it-solves)
3. [Project Structure](#3-project-structure)
4. [How to Run](#4-how-to-run)
5. [CSV Output Schema](#5-csv-output-schema)
6. [Data Models](#6-data-models-modelspy)
7. [Configuration System](#7-configuration-system-configpy--configtoolsyaml)
8. [Parser Architecture](#8-parser-architecture)
9. [Antigravity Parser](#9-antigravity-parser-parsernantigravitypy)
10. [Claude Code Parser](#10-claude-code-parser-parsersclaude_codepy)
11. [Codex Parser](#11-codex-parser-parserscodexpy)
12. [CSV Exporter](#12-csv-exporter-exporterscsv_exporterpy)
13. [CLI Reference](#13-cli-reference-clipy)
14. [Test Suite](#14-test-suite)
15. [Live Results](#15-live-results)
16. [Phase 2 Scope](#16-phase-2-scope-not-yet-implemented)

---

## 1. What This Project Does

This is a command-line tool that reads conversation history files written to disk by AI IDE tools, parses every prompt and response, and exports them as a structured CSV file.

You run one command and get a clean spreadsheet of every AI interaction you have ever had in your IDE — who said what, when, in which session, and from which tool.

**No API keys. No internet. No browser automation. Reads local files only.**

---

## 2. Problem It Solves

The development team uses three AI IDE tools — **Antigravity**, **Claude Code**, and **Codex** — but none of them provide a built-in way to export conversation history. There is no way to:

- Review what was asked of the AI during a session
- Audit AI-assisted decisions after the fact
- Track which tool was used for which task
- Analyse prompt quality over time

Each tool does, however, write its session data to local files on disk. This project reads those files and produces a single, structured CSV that covers all tools.

---

## 3. Project Structure

```
AI TRACKING SYSTEM PYTHON SCRIPT/
│
├── ai_tracker/                     Core Python package
│   ├── __init__.py                 Package version
│   ├── models.py                   Data classes: Message, ParsedSession
│   ├── config.py                   Default paths + YAML config loader
│   ├── cli.py                      Command-line interface
│   │
│   ├── parsers/
│   │   ├── __init__.py             Parser registry + get_parser() factory
│   │   ├── base.py                 Abstract base class + date filter
│   │   ├── antigravity.py          Antigravity IDE transcript parser
│   │   ├── claude_code.py          Claude Code JSONL parser
│   │   └── codex.py                Codex JSON/JSONL parser
│   │
│   └── exporters/
│       ├── __init__.py
│       └── csv_exporter.py         UTF-8 CSV writer
│
├── tests/
│   ├── fixtures/
│   │   ├── antigravity_transcript.jsonl    Sample Antigravity session
│   │   └── claude_code_sample.jsonl        Sample Claude Code session
│   ├── test_antigravity_parser.py          23 tests
│   ├── test_claude_code_parser.py          15 tests
│   └── test_csv_exporter.py               9 tests
│
├── config/
│   └── tools.yaml                  Override tool paths and settings
│
├── docs/
│   └── README.md                   This file
│
├── ai-tracker.ps1                  PowerShell run wrapper
├── verify_parsers.py               Live verification script
├── pyproject.toml                  Package definition
└── IMPLEMENTATION.md               Implementation summary
```

---

## 4. How to Run

### Open PowerShell and navigate to the project

```powershell
cd "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
```

### Available commands

```powershell
# Check which tools have data on disk
.\ai-tracker.ps1 list-tools

# Export all tools into one CSV
.\ai-tracker.ps1 parse --tool all --output all_interactions.csv

# Export Antigravity only
.\ai-tracker.ps1 parse --tool antigravity --output antigravity.csv

# Export Claude Code only
.\ai-tracker.ps1 parse --tool claudecode --output claude.csv

# Filter by date range
.\ai-tracker.ps1 parse --tool claudecode --start-date 2026-05-01 --output may.csv

# Parse a specific file directly
.\ai-tracker.ps1 parse --tool antigravity --file "C:\path\to\transcript.jsonl" --output out.csv

# Include Claude Code subagent threads (excluded by default)
.\ai-tracker.ps1 parse --tool claudecode --include-sidechains --output full.csv
```

### Run the test suite

```powershell
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
$env:PYTHONPATH = "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
& $py -m pytest tests -v
```

---

## 5. CSV Output Schema

Every row in the output CSV represents one message — either a human prompt or an AI response.

| Column | Type | Description | Example |
|---|---|---|---|
| `session_id` | string | Unique ID for the session (UUID) | `412a0856-1411-4a2f-900c-772ff7a42970` |
| `timestamp` | ISO 8601 | Date and time the message was sent | `2026-05-22T06:02:38+00:00` |
| `role` | string | Who sent the message | `human` or `assistant` |
| `message` | string | Full text of the prompt or response | `How do I reverse a list in Python?` |
| `tool` | string | Which IDE tool produced the message | `antigravity`, `claudecode`, `codex` |
| `file_path` | string | Absolute path of the source file | `C:\Users\Robin\.claude\projects\...\session.jsonl` |

---

## 6. Data Models (`models.py`)

Two dataclasses carry all data through the system.

### `Message`

Represents a single conversation turn — one human prompt or one AI response.

```python
@dataclass
class Message:
    session_id: str           # UUID of the session this message belongs to
    timestamp: Optional[datetime]  # When the message was sent
    role: str                 # "human" or "assistant"
    message: str              # Full text content
    tool: str                 # "antigravity" | "claudecode" | "codex"
    file_path: str            # Source file path (for audit trail)
```

`to_dict()` serialises the message to a flat dictionary matching the CSV column order.

### `ParsedSession`

Groups all messages that belong to one development session together.

```python
@dataclass
class ParsedSession:
    session_id: str           # UUID matching the session directory or filename
    tool: str                 # Which tool produced this session
    file_path: str            # Source file path
    messages: List[Message]   # All messages in chronological order
```

---

## 7. Configuration System (`config.py` + `config/tools.yaml`)

### Default paths

The system knows where each tool stores its data by default:

| Tool | Default Path |
|---|---|
| Antigravity | `~/.gemini/antigravity-ide/brain/` |
| Claude Code | `~/.claude/projects/` |
| Codex | `~/.codex/` |

`~` expands to `C:\Users\Robin` on your machine.

### Overriding paths

Edit `config/tools.yaml` to change any path without touching the code:

```yaml
tools:
  antigravity:
    path: ~/.gemini/antigravity-ide/brain

  claudecode:
    path: ~/.claude/projects
    include_sidechains: false   # true = also export subagent threads

  codex:
    path: ~/.codex
```

### How it works

`load_config()` reads the YAML file and merges it over the built-in defaults. If `tools.yaml` does not exist, the defaults are used. All `~` paths are expanded with `.expanduser()` at runtime.

---

## 8. Parser Architecture

All parsers share a common design through the abstract `BaseParser` class.

### `BaseParser` (abstract)

Every parser inherits from this class. It provides:

- `file_path` and `tool_name` stored on every instance
- `_validate_file()` — raises `FileNotFoundError` if the source does not exist
- `filter_by_date(sessions, start, end)` — filters messages to a date range, timezone-aware

The one method every parser must implement:

```python
@abstractmethod
def parse(self) -> List[ParsedSession]:
    ...
```

### Parser registry

`parsers/__init__.py` maintains a dictionary that maps tool names to parser classes:

```python
PARSER_REGISTRY = {
    "antigravity": AntigravityParser,
    "claudecode":  ClaudeCodeParser,
    "codex":       CodexParser,
}
```

The `get_parser(tool, file_path, **kwargs)` factory function looks up the right class and instantiates it. The CLI uses this to avoid knowing about individual parser classes directly.

---

## 9. Antigravity Parser (`parsers/antigravity.py`)

### What it reads

Antigravity IDE writes one UUID-named directory per session under:

```
C:\Users\Robin\.gemini\antigravity-ide\brain\
    <session-uuid>\
        .system_generated\
            logs\
                transcript.jsonl   ← full step-by-step log
                overview.txt       ← filtered summary (same format)
```

The parser is given the `brain/` directory and scans every session folder automatically.

### File format

Both `transcript.jsonl` and `overview.txt` are JSONL files — one JSON object per line. Each object represents one step in the session:

```json
{
  "step_index": 0,
  "source": "USER_EXPLICIT",
  "type": "USER_INPUT",
  "status": "DONE",
  "created_at": "2026-05-22T06:02:38Z",
  "content": "<USER_REQUEST>\nHow do I reverse a list?\n</USER_REQUEST>\n<ADDITIONAL_METADATA>..."
}
```

```json
{
  "step_index": 3,
  "source": "MODEL",
  "type": "PLANNER_RESPONSE",
  "status": "DONE",
  "created_at": "2026-05-22T06:02:41Z",
  "thinking": "You can reverse a list using [::-1] or list.reverse()...",
  "tool_calls": [...]
}
```

### What gets extracted

| Record type | Condition | Extracted as |
|---|---|---|
| `source=USER_EXPLICIT, type=USER_INPUT` | Always | `role=human` — text inside `<USER_REQUEST>` tags |
| `source=MODEL, type=PLANNER_RESPONSE` | Only when `thinking` field is present | `role=assistant` — the thinking text |
| Everything else | — | Skipped |

Records that are skipped:
- `SYSTEM` records (`CONVERSATION_HISTORY`, `KNOWLEDGE_ARTIFACTS`) — these are system context injected into the model, not real messages
- `PLANNER_RESPONSE` records without a `thinking` field — these are pure tool-call steps (list_dir, view_file, run_command) with no readable AI text
- All tool result records (`LIST_DIRECTORY`, `VIEW_FILE`, `CODE_ACTION`, `RUN_COMMAND`)

### Tag stripping

The `content` field of `USER_INPUT` records contains embedded XML tags used internally by Antigravity:

```
<USER_REQUEST>
How do I reverse a list?
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-05-22T11:30:00+05:30.
...
</ADDITIONAL_METADATA>
```

The parser extracts only the clean prompt text using:
1. Regex match for `<USER_REQUEST>...</USER_REQUEST>` (covers most cases)
2. Fallback: strips the opening tag and cuts at the next XML block if the closing tag is missing (handles very long prompts that are truncated in the file)

### Session discovery flow

```
brain/ directory
  └── for each UUID subdirectory
        └── look for .system_generated/logs/transcript.jsonl
            if not found → look for .system_generated/logs/overview.txt
            if neither found → skip this session directory
            if found → parse the JSONL file line by line
```

---

## 10. Claude Code Parser (`parsers/claude_code.py`)

### What it reads

Claude Code writes one JSONL file per session under:

```
C:\Users\Robin\.claude\projects\
    <project-slug>\
        <session-uuid>.jsonl          ← main conversation
        <session-uuid>\
            subagents\
                agent-<id>.jsonl      ← subagent threads (skipped by default)
```

### File format

Each line in the `.jsonl` file is one session event:

```json
{
  "type": "user",
  "isSidechain": false,
  "sessionId": "412a0856-1411-4a2f-900c-772ff7a42970",
  "timestamp": "2026-05-20T06:09:37.467Z",
  "message": {
    "role": "user",
    "content": [
      { "type": "text", "text": "How do I reverse a list in Python?" }
    ]
  }
}
```

```json
{
  "type": "assistant",
  "isSidechain": false,
  "sessionId": "412a0856-1411-4a2f-900c-772ff7a42970",
  "timestamp": "2026-05-20T06:09:40.123Z",
  "message": {
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [
      { "type": "text", "text": "You can use `[::-1]` or `list.reverse()`." }
    ]
  }
}
```

### What gets extracted

| Record `type` | `isSidechain` | Result |
|---|---|---|
| `user` | `false` | Extracted as `role=human` |
| `assistant` | `false` | Extracted as `role=assistant` |
| `user` or `assistant` | `true` | Skipped by default (include with `--include-sidechains`) |
| `queue-operation` | any | Skipped |
| `attachment` | any | Skipped |
| `system` | any | Skipped |

### Content extraction

The `content` field of a message can be either a plain string or a list of typed blocks. The parser handles both:

```python
# Plain string
"content": "Hello"  →  "Hello"

# List of blocks — only "text" type blocks are joined
"content": [
    { "type": "text",  "text": "First part" },
    { "type": "image", ... },       ← skipped
    { "type": "text",  "text": "Second part" }
]  →  "First part Second part"
```

### Session ID

The session ID is taken from the `sessionId` field inside each JSON record, which always matches the `.jsonl` filename. If the filename is not a valid UUID (e.g. a test fixture), the stem is used as-is.

### Sidechain filtering

Subagent (sidechain) conversations live inside `<session-id>/subagents/` directories. These are separate threads spawned by the main session. By default the parser skips any `.jsonl` file whose path contains the word `subagents`. Pass `--include-sidechains` to include them.

---

## 11. Codex Parser (`parsers/codex.py`)

### Status

Implemented and ready. No Codex session data was found on this machine (`~/.codex/` does not exist), so it has not been tested against real files. It will activate automatically when Codex CLI is installed and used.

### What it reads

Codex CLI is expected to write session data under `~/.codex/`. The parser handles two formats:

- **JSONL** — one JSON object per line (detected when the first line starts and ends with `{` `}`)
- **JSON array** — a single file containing a list of message objects

### Expected record schema

```json
{ "role": "user",      "content": "...", "timestamp": "..." }
{ "role": "assistant", "content": "...", "timestamp": "..." }
```

Both Unix epoch timestamps (integer) and ISO 8601 strings are accepted.

---

## 12. CSV Exporter (`exporters/csv_exporter.py`)

### What it does

Takes a flat list of `Message` objects and writes them to a UTF-8 CSV file.

```python
exporter = CSVExporter(Path("output.csv"))
count = exporter.export(messages)   # returns number of rows written
```

### Column order

The exporter always writes columns in this fixed order, matching the proposal schema:

```
session_id, timestamp, role, message, tool, file_path
```

### Details

- Output encoding is UTF-8 — handles any Unicode in prompts (including emoji, CJK, etc.)
- Parent directories are created automatically if they do not exist
- Timestamps are written as ISO 8601 strings; missing timestamps are written as empty string
- A header row is always written, even for an empty message list

---

## 13. CLI Reference (`cli.py`)

The command-line interface has two subcommands.

### `list-tools`

Shows which tools are configured and whether their data directories exist on disk.

```powershell
.\ai-tracker.ps1 list-tools
```

Output:
```
Tool             Status       Path
----------------------------------------------------------------------
  antigravity    [found    ]  C:\Users\Robin\.gemini\antigravity-ide\brain
  claudecode     [found    ]  C:\Users\Robin\.claude\projects
  codex          [not found]  C:\Users\Robin\.codex
```

### `parse`

Parses one or all tools and exports to CSV.

```powershell
.\ai-tracker.ps1 parse [options]
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--tool` | | `all` | `antigravity`, `claudecode`, `codex`, or `all` |
| `--output` | `-o` | `ai_interactions_<timestamp>.csv` | Output CSV file path |
| `--file` | `-f` | *(tool default)* | Override source file or directory |
| `--start-date` | | *(none)* | Include messages from this date onwards (YYYY-MM-DD) |
| `--end-date` | | *(none)* | Include messages up to this date (YYYY-MM-DD) |
| `--include-sidechains` | | `false` | Include Claude Code subagent threads |

### Internal flow

```
cli.py
  └── cmd_parse()
        └── for each tool:
              └── _gather_messages()
                    ├── load_config()           read tools.yaml
                    ├── resolve path            expanduser()
                    ├── get_parser()            look up registry
                    ├── parser.parse()          read files
                    └── parser.filter_by_date() apply date range
        └── CSVExporter.export()                write CSV
```

---

## 14. Test Suite

**47 tests — all passing** (Python 3.13, pytest 9.0.3)

### `test_antigravity_parser.py` — 23 tests

| Class | What is tested |
|---|---|
| `TestSingleFileMode` | Single `transcript.jsonl` file: correct message count, role extraction, `<USER_REQUEST>` tag stripping, tool-only records skipped, system records skipped, timestamps, file path |
| `TestBrainDirectoryMode` | Directory scanning: multiple sessions found, session ID from dir name, `overview.txt` accepted, missing log files skipped, empty directory |
| `TestRealAntigravityData` | Live tests against real `~/.gemini/antigravity-ide/brain/` data |
| `TestEdgeCases` | Missing path, no `<USER_REQUEST>` tag fallback, empty file |

### `test_claude_code_parser.py` — 15 tests

| Class | What is tested |
|---|---|
| `TestClaudeCodeParserSingleFile` | Session ID from record, tool name, queue-operation skipped, correct count without sidechains, role normalisation, human text, AI text, timestamps ordered, sidechain inclusion, file path |
| `TestClaudeCodeParserMissingFile` | FileNotFoundError raised |
| `TestClaudeCodeParserDirectory` | All JSONL files found, subagents dir skipped |

### `test_csv_exporter.py` — 9 tests

Output file created, parent dirs created, row count returned, header row present, all columns written, multiple messages, empty list writes header only, null timestamp as empty string, Unicode preserved.

---

## 15. Live Results

Verified against real data on this machine:

| Tool | Sessions | Messages |
|---|---|---|
| Antigravity IDE | 5 | 8 |
| Claude Code | 6 | 448 |
| **Total** | **11** | **456** |

Sample Antigravity sessions captured:

| Session | First human prompt |
|---|---|
| `128e495f` | *"analys the document and create an implementation plan"* |
| `6ca88f3c` | *"I have installed an extension called claude prompt tracker..."* |
| `89fe38cd` | *"Craete a documenation for antigravity workflow..."* |
| `d056af45` | *"Analyze this complete project thoroughly and set it up to run..."* |
| `e42a658e` | *"explain the complete implented codebase"* |

---

## 16. Phase 2 Scope (Not Yet Implemented)

Phase 2 will be a Chrome Extension that captures conversations from web-based AI tools: ChatGPT, Claude.ai, and Gemini. It will produce CSV output using the same six-column schema defined in Phase 1.

Key differences from Phase 1:
- Runs inside the browser as a trusted user-installed extension
- Captures messages from the rendered DOM as they appear
- Injects timestamps at the moment a human message is sent
- Provides a one-click Export button in the extension popup
- Targets `chrome.openai.com`, `claude.ai`, and `gemini.google.com`
