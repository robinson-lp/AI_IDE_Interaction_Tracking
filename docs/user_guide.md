# User Guide — AI Interaction Tracking System

> **Phase 1: Python File Parser for AI IDE Tools**

This guide walks you through installing, configuring, and running `ai-tracker` to export your AI IDE conversation history to CSV.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Your First Run](#3-your-first-run)
4. [Commands](#4-commands)
5. [Filtering by Date](#5-filtering-by-date)
6. [Configuration](#6-configuration)
7. [Understanding the CSV Output](#7-understanding-the-csv-output)
8. [Supported Tools](#8-supported-tools)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

- **Python 3.10 or higher**
- Windows 10 / 11 (PowerShell 5.1+)
- At least one supported AI IDE tool installed and used (Antigravity, Claude Code, or Codex)

> **Note for this machine:** Python is available via pgAdmin's bundled interpreter at  
> `C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe`  
> The included `ai-tracker.ps1` wrapper uses this path automatically.

---

## 2. Installation

Open PowerShell and navigate to the project folder:

```powershell
cd "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
```

Install the package and its dependency (PyYAML):

```powershell
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
& $py -m pip install -e . --user
```

Verify the installation:

```powershell
.\ai-tracker.ps1 list-tools
```

You should see a table listing `antigravity`, `claudecode`, and `codex` with `found` or `not found` next to each.

---

## 3. Your First Run

Check which tools have data on your machine:

```powershell
.\ai-tracker.ps1 list-tools
```

Export everything to a CSV file:

```powershell
.\ai-tracker.ps1 parse --tool all --output my_interactions.csv
```

Open `my_interactions.csv` in Excel or any spreadsheet application to see all your AI conversations.

---

## 4. Commands

### `list-tools`

Shows which tools are configured and whether their session data directories exist on disk.

```powershell
.\ai-tracker.ps1 list-tools
```

Example output:

```
Tool             Status       Path
----------------------------------------------------------------------
  antigravity    [found    ]  C:\Users\Robin\.gemini\antigravity-ide\brain
  claudecode     [found    ]  C:\Users\Robin\.claude\projects
  codex          [not found]  C:\Users\Robin\.codex
```

---

### `parse`

Parses session files and writes a CSV file.

```powershell
.\ai-tracker.ps1 parse [options]
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--tool` | | `all` | Which tool to parse: `antigravity`, `claudecode`, `codex`, or `all` |
| `--output` | `-o` | `ai_interactions_<timestamp>.csv` | Output CSV file path |
| `--file` | `-f` | *(tool default)* | Override the source file or directory for the chosen tool |
| `--start-date` | | *(none)* | Include messages on or after this date (`YYYY-MM-DD`) |
| `--end-date` | | *(none)* | Include messages up to this date (`YYYY-MM-DD`) |
| `--include-sidechains` | | `false` | (Claude Code only) Also include subagent / sidechain threads |

#### Common examples

```powershell
# Export all tools to a single CSV
.\ai-tracker.ps1 parse --tool all --output all_interactions.csv

# Export Claude Code only
.\ai-tracker.ps1 parse --tool claudecode --output claude.csv

# Export Antigravity only
.\ai-tracker.ps1 parse --tool antigravity --output antigravity.csv

# Export Claude Code for a specific month
.\ai-tracker.ps1 parse --tool claudecode --start-date 2026-05-01 --end-date 2026-05-31 --output may.csv

# Parse a single specific file instead of the default directory
.\ai-tracker.ps1 parse --tool antigravity --file "C:\Users\Robin\.gemini\antigravity-ide\brain\128e495f-...\...\transcript.jsonl" --output session.csv

# Include Claude Code subagent threads (excluded by default)
.\ai-tracker.ps1 parse --tool claudecode --include-sidechains --output full.csv
```

---

## 5. Filtering by Date

Use `--start-date` and/or `--end-date` to limit results to a specific time window.

```powershell
# Everything from May 2026 onwards
.\ai-tracker.ps1 parse --tool all --start-date 2026-05-01 --output from_may.csv

# A specific week
.\ai-tracker.ps1 parse --tool all --start-date 2026-05-20 --end-date 2026-05-26 --output week.csv
```

Date format: `YYYY-MM-DD` (e.g. `2026-05-01`).

Messages without a timestamp are always included.

---

## 6. Configuration

Default data paths are built in for each tool:

| Tool | Default Path |
|---|---|
| Antigravity | `~/.gemini/antigravity-ide/brain/` |
| Claude Code | `~/.claude/projects/` |
| Codex | `~/.codex/` |

`~` expands to `C:\Users\Robin` on this machine.

To override any path or setting without changing the code, edit [config/tools.yaml](../config/tools.yaml):

```yaml
tools:
  antigravity:
    path: ~/.gemini/antigravity-ide/brain

  claudecode:
    path: ~/.claude/projects
    include_sidechains: false   # true = always include subagent threads

  codex:
    path: ~/.codex
```

Changes take effect immediately — no restart needed.

---

## 7. Understanding the CSV Output

Each row in the CSV represents one message (one human prompt or one AI response).

| Column | Description | Example |
|---|---|---|
| `session_id` | UUID identifying the session | `412a0856-1411-4a2f-900c-772ff7a42970` |
| `timestamp` | When the message was recorded (ISO 8601) | `2026-05-20T06:09:37.467000+00:00` |
| `role` | `human` or `assistant` | `human` |
| `message` | Full text of the prompt or response | `How do I reverse a list in Python?` |
| `tool` | Which IDE tool produced the message | `claudecode` |
| `file_path` | Absolute path of the source file | `C:\Users\Robin\.claude\projects\...\session.jsonl` |

Messages from all tools are combined in a single file when `--tool all` is used, sorted in the order they were parsed.

---

## 8. Supported Tools

### Antigravity IDE

Reads JSONL transcripts from `~/.gemini/antigravity-ide/brain/`. Each session is stored in a UUID-named subdirectory. Both `transcript.jsonl` and `overview.txt` are supported.

Only real user prompts and readable AI thinking are extracted. Internal steps (tool calls, directory listings, file reads, system context) are skipped.

### Claude Code

Reads JSONL session files from `~/.claude/projects/`. Each project has its own subdirectory with one file per session. Subagent threads are excluded by default; use `--include-sidechains` to include them.

### Codex (OpenAI)

Reads session files from `~/.codex/`. Both JSON arrays and JSONL formats are supported. This parser is implemented and ready but has not been tested locally because no Codex data exists on this machine — it will activate automatically when Codex CLI is installed.

---

## 9. Troubleshooting

**`list-tools` shows `not found` for a tool**

The tool's data directory does not exist on this machine. This is expected if you have not installed or used that tool. The parser will be skipped and the others will still run.

**`No messages found. Nothing exported.`**

All tool directories either do not exist or contain no parseable session files. Run `list-tools` first to confirm which paths are found.

**CSV is missing data from a specific session**

- Run `list-tools` to confirm the directory is found.
- Try passing the session path directly with `--file` to isolate it.
- The file may use an unsupported format — check the raw file content.

**Test suite**

To confirm the parsers are working correctly:

```powershell
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
$env:PYTHONPATH = "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
& $py -m pytest tests -v
```

**Live parser verification**

To print a live summary of all detected sessions without writing a CSV:

```powershell
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
$projectDir = "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
& $py -c "import sys; sys.path.insert(0, r'$projectDir'); exec(open(r'$projectDir\scripts\verify_parsers.py').read())"
```
