# AI Interaction Tracking System (Phase 1)

`ai-tracker` is a localized Python CLI tool that automatically reads local development session files written to disk by popular AI IDE and terminal assistant tools. It parses their raw conversation histories, normalizes the roles, and exports them into a structured, unified UTF-8 CSV database.

**No API keys, no internet access, and no browser automation required.** It parses files that are already sitting on your disk.

---

## 🚀 Features

*   **100% Local & Private**: Operates entirely offline using your local system files.
*   **Multi-Tool Discovery**: Scans and parses sessions from:
    *   **Claude Code**: Extracts standard JSONL logs and supports including subagent/sidechain threads.
    *   **Antigravity-IDE**: Extracts user prompts and readable AI thinking from session transcripts.
    *   **OpenAI Codex**: Parses both JSON arrays and JSONL outputs.
*   **Standardized CSV Schema**: Merges histories into a canonical format ideal for auditing, usage tracking, and data analysis.
*   **Robust Date Filtering**: Filter logs by specific date ranges via the command line.
*   **Flexible Configurations**: Override default data paths and settings via `config/tools.yaml`.

---

## 📊 CSV Output Schema

Every exported row represents a single message turn (either a human prompt or an assistant response).

| Column | Description | Example |
|---|---|---|
| `session_id` | Unique UUID or identifier of the development session | `412a0856-1411-4a2f-900c-772ff7a42970` |
| `timestamp` | ISO 8601 UTC date and time the message was recorded | `2026-05-20T06:09:37.467000+00:00` |
| `role` | Speaker role (normalized to `human` or `assistant`) | `human` |
| `message` | The actual text of the prompt or response | `How do I reverse a list in Python?` |
| `tool` | The IDE tool source identifier | `claudecode` |
| `file_path` | Absolute path of the source session file for audit trailing | `C:\Users\Robin\.claude\projects\session.jsonl` |

---

## 🛠️ Installation

Ensure you have Python 3.10 or higher installed. From the repository root, install the package in editable mode:

```bash
pip install -e .
```

---

## 💻 How to Run

You can invoke the tracker in three different ways depending on your system setup:

### Method 1: Using the `ai-tracker` command directly
Once installed via `pip`, you can run the command anywhere:
```bash
ai-tracker parse --tool all --output interactions.csv
```
> [!TIP]
> **Windows/PowerShell Path Warning:**
> If you get an error saying `ai-tracker` is not recognized, your Python scripts folder is not in your environment's `PATH`. You can quickly add it to your current PowerShell session's path by running:
> ```powershell
> $env:PATH += ";C:\Users\Robin\AppData\Local\Python\pythoncore-3.14-64\Scripts"
> ```
> To make this permanent, add that directory to your Windows User Path environment variables.

### Method 2: Using standard Python Module execution (Always works)
If you do not want to configure your PATH, execute the entry point directly through Python:
```powershell
python -m ai_tracker.cli parse --tool all --output interactions.csv
```

### Method 3: Using the PowerShell Wrapper Script
For quick runs on Windows without relying on system-wide Python setups, use the included wrapper script (which points to the Python environment bundled with PostgreSQL/pgAdmin):
```powershell
.\ai-tracker.ps1 parse --tool all --output interactions.csv
```

---

## ⚙️ CLI Reference

### Available Commands

*   `list-tools`: Discover which supported AI tools currently have session logs saved on your local computer.
*   `parse`: Process local logs and write them to a CSV file.

### Parsing Arguments & Filters

| Flag | Short | Description |
|---|---|---|
| `--tool` | | `claudecode`, `antigravity`, `codex`, or `all` (default: `all`) |
| `--output` | `-o` | Output file path (default: `ai_interactions_<timestamp>.csv`) |
| `--file` | `-f` | Override the default source directory or file path for a specific tool |
| `--start-date` | | Include only messages on or after this date (`YYYY-MM-DD`) |
| `--end-date` | | Include only messages on or before this date (`YYYY-MM-DD`) |
| `--include-sidechains`| | (Claude Code only) Include nested subagent/sidechain logs |

### Examples

```powershell
# Check which tools have data logs on your machine
ai-tracker list-tools

# Export everything found to a file called daily_log.csv
ai-tracker parse --tool all -o daily_log.csv

# Export ONLY Claude Code sessions for the month of May 2026
ai-tracker parse --tool claudecode --start-date 2026-05-01 --end-date 2026-05-31 -o may_claude.csv

# Run on a custom local text file for Antigravity-IDE
ai-tracker parse --tool antigravity --file "C:\CustomPath\overview.txt" -o custom_antigravity.csv
```

---

## 🔧 Advanced Configuration

You can override default scanner folders and behaviour without changing any source code. Edit [config/tools.yaml](file:///c:/Users/Robin/AI%20TRACKING%20SYSTEM%20PYTHON%20SCRIPT/config/tools.yaml) to customize settings:

```yaml
tools:
  antigravity:
    path: ~/.gemini/antigravity-ide/brain
  
  claudecode:
    path: ~/.claude/projects
    include_sidechains: false   # Set to true to always parse subagents
    
  codex:
    path: ~/.codex
```

---

## 🧪 Verification and Testing

### Quick Diagnostics Script
To inspect a live summary of detected conversations without writing a CSV, run:
```powershell
python verify_parsers.py
```

### Running Unit Tests
If you would like to run the test suite, install `dev` packages and run `pytest`:
```bash
pip install -e ".[dev]"
pytest
```
