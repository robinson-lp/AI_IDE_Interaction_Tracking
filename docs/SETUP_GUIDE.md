# AI Interaction Tracker — Simple Setup Guide

> Track every prompt and AI response from Claude Code, Antigravity, and Codex — automatically exported to CSV.

---

## What This Tool Does

Every time you chat with an AI in your IDE, the conversation is saved to a log file on your disk.
This tool reads those log files and exports them into a clean, structured CSV file you can open in Excel.

**No internet. No API keys. No installation of extra software.**

---

## Requirements

| Requirement | Details |
|---|---|
| Python | 3.10 or higher |
| Operating System | Windows 10 / 11 |
| AI IDE | Claude Code, Antigravity, or Codex (at least one) |

---

## Step 1 — Install

Open PowerShell and run these two commands once:

```powershell
cd "C:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
.venv\Scripts\pip.exe install -e .
```

**Verify the install worked:**

```powershell
ai-tracker list-tools
```

You should see:

```
Tool             Status       Path
----------------------------------------------------------------------
  antigravity    [found    ]  C:\Users\Robin\.gemini\antigravity-ide\brain
  claudecode     [found    ]  C:\Users\Robin\.claude\projects
  codex          [found    ]  C:\Users\Robin\.codex
```

`[found]` means the tool is installed and has conversation data ready to export.

---

## Step 2 — Your First Export

Export everything from all tools into one CSV:

```powershell
ai-tracker parse --tool all -o my_interactions.csv
```

**What you will see:**

```
  [antigravity] 477 message(s) parsed.
  [claudecode]  821 message(s) parsed.
  [codex]         0 message(s) parsed.

Exported 1298 message(s) -> my_interactions.csv
```

Open `my_interactions.csv` in Excel — that's it.

---

## Step 3 — Understand the CSV

Each row is one message — either something you typed or the AI's reply.

| Column | What it means | Example |
|---|---|---|
| `project` | Which project the conversation belongs to | `Sparq` |
| `session_id` | Unique ID for that conversation | `b65bda2b-bc85-...` |
| `timestamp` | Exact date and time | `2026-05-18T09:22:28` |
| `role` | Who spoke | `human` / `assistant` / `tool` |
| `message` | The full text — never cut short | `How do I sort a dict?` |
| `tool` | Which AI IDE was used | `claudecode` / `antigravity` |
| `file_path` | Where the log file lives on disk | `C:\Users\Robin\.claude\...` |

**What each role means:**

- `human` — A prompt you typed
- `assistant` — The AI's response
- `tool` — A background action the AI took (reading a file, listing a folder, running a command)

---

## All Available Commands

### Check which tools have data

```powershell
ai-tracker list-tools
```

### Export everything

```powershell
ai-tracker parse --tool all -o output.csv
```

### Export one tool only

```powershell
ai-tracker parse --tool claudecode  -o claude.csv
ai-tracker parse --tool antigravity -o antigravity.csv
ai-tracker parse --tool codex       -o codex.csv
```

### Filter by date

```powershell
# Today only
ai-tracker parse --tool all --start-date 2026-06-01 --end-date 2026-06-01 -o today.csv

# A full month
ai-tracker parse --tool all --start-date 2026-05-01 --end-date 2026-05-31 -o may.csv

# From a specific date onwards
ai-tracker parse --tool all --start-date 2026-05-25 -o recent.csv
```

### Filter by project name

```powershell
# Exact project
ai-tracker parse --tool all --project "Sparq" -o sparq.csv

# Partial match (case-insensitive)
ai-tracker parse --tool all --project "tracking" -o tracking.csv
```

### Split into one file per project

```powershell
ai-tracker parse --tool all --split-by-project -o projects/
```

This creates a folder called `projects/` with one CSV per project:

```
projects/
  sparq.csv
  ai_tracking_system_python_script.csv
  ai_interaction_tracking_system.csv
  ai_prompt_tracker.csv
  general.csv
```

### Exclude Claude Code subagent threads

```powershell
ai-tracker parse --tool claudecode --no-sidechains -o main_only.csv
```

### Combine multiple filters

```powershell
ai-tracker parse --tool all --project "Sparq" --start-date 2026-05-01 --end-date 2026-05-31 --split-by-project -o sparq_may/
```

---

## How Session IDs Work

Each conversation gets a unique ID that comes directly from the IDE — the tracker never makes one up.

| Tool | Where the session ID comes from |
|---|---|
| **Claude Code** | The `.jsonl` filename under `~/.claude/projects/` |
| **Antigravity** | The UUID folder name under `~/.gemini/antigravity-ide/brain/` |
| **Codex** | A field inside the session file |

This means re-running the export tomorrow gives the same session IDs — the CSV is stable and consistent over time.

---

## How Projects Are Detected

The tool automatically figures out which project each conversation belongs to.

| Tool | How it finds the project name |
|---|---|
| **Claude Code** | Reads the project folder name from the file path |
| **Antigravity** | Scans the transcript for `Active Document:` or workspace paths in the metadata |
| **Codex** | Reads the project folder name from the file path |

Raw folder names like `c--Users-Robin-AI-TRACKING-SYSTEM-PYTHON-SCRIPT` are automatically cleaned to `Ai Tracking System Python Script`.

---

## Latency — How Fresh is the Data?

| Tool | Delay after you send a message |
|---|---|
| Claude Code | ~0.2 seconds |
| Antigravity | ~2–3 seconds |

The parser reads what is on disk at the moment you run the command. The currently active message (being typed right now) will not appear until it is complete and flushed to disk.

---

## Troubleshooting

**`ai-tracker` not recognized as a command**

Run with the full venv path instead:
```powershell
cd "C:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
.venv\Scripts\python.exe -m ai_tracker.cli parse --tool all -o output.csv
```

**Tool shows `[not found]`**

The tool is either not installed or has never been used. Start a conversation in that IDE first, then re-run `ai-tracker list-tools`.

**No messages found**

Check the date filter — `--end-date` covers the full day automatically. Also verify the tool path with `list-tools`.

**CSV opens with garbled characters in Excel**

Open Excel → Data → From Text/CSV → select the file → choose UTF-8 encoding.

**Run tests to check everything is working**

```powershell
.venv\Scripts\pytest.exe tests/ -v
```

Expected result: `128 passed`

---

## Quick Reference Card

```
SETUP
  cd "C:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
  .venv\Scripts\pip.exe install -e .

CHECK
  ai-tracker list-tools

EXPORT
  ai-tracker parse --tool all -o output.csv
  ai-tracker parse --tool claudecode -o claude.csv
  ai-tracker parse --tool antigravity -o antigravity.csv

FILTER BY DATE
  ai-tracker parse --tool all --start-date 2026-06-01 -o today.csv
  ai-tracker parse --tool all --start-date 2026-05-01 --end-date 2026-05-31 -o may.csv

FILTER BY PROJECT
  ai-tracker parse --tool all --project "Sparq" -o sparq.csv

SPLIT BY PROJECT
  ai-tracker parse --tool all --split-by-project -o projects/
```
