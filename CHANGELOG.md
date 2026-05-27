# Changelog

All notable changes to this project are documented here.

---

## [0.1.0] — 2026-05-27

### Phase 1 — Python File Parser for AI IDE Tools (initial release)

#### Added

- **Antigravity IDE parser** (`ai_tracker/parsers/antigravity.py`)
  - Scans `~/.gemini/antigravity-ide/brain/` for UUID session directories
  - Reads `transcript.jsonl` or `overview.txt` per session
  - Extracts user prompts from `<USER_REQUEST>` XML tags
  - Extracts AI reasoning from `thinking` field of `PLANNER_RESPONSE` records
  - Skips tool-call-only records, system context, and tool result records
  - Two-step fallback for tag stripping when closing tag is absent in very long prompts

- **Claude Code parser** (`ai_tracker/parsers/claude_code.py`)
  - Scans `~/.claude/projects/` recursively for `*.jsonl` session files
  - Handles both plain-string and list-of-blocks content format
  - Skips `queue-operation`, `attachment`, `system`, and sidechain records by default
  - `include_sidechains` flag to include subagent threads

- **Codex parser** (`ai_tracker/parsers/codex.py`)
  - Scans `~/.codex/` for `*.json` and `*.jsonl` files
  - Auto-detects JSON array vs JSONL format per file
  - Accepts both Unix epoch and ISO 8601 timestamps

- **Data models** (`ai_tracker/models.py`)
  - `Message` dataclass with `to_dict()` serialisation
  - `ParsedSession` dataclass grouping messages per session

- **CSV exporter** (`ai_tracker/exporters/csv_exporter.py`)
  - UTF-8 output with fixed column order
  - Creates parent directories automatically

- **CLI** (`ai_tracker/cli.py`)
  - `parse` subcommand with `--tool`, `--output`, `--file`, `--start-date`, `--end-date`, `--include-sidechains`
  - `list-tools` subcommand showing path status for each tool
  - Fail-soft: skips unavailable tools and continues

- **Configuration system** (`ai_tracker/config.py`, `config/tools.yaml`)
  - YAML overrides merged over built-in defaults
  - `~` expansion at runtime via `.expanduser()`

- **PowerShell wrapper** (`ai-tracker.ps1`)
  - Points to pgAdmin's bundled Python on this machine

- **Test suite** — 47 tests across 3 files, all passing
  - `tests/test_antigravity_parser.py` — 23 tests including live data integration tests
  - `tests/test_claude_code_parser.py` — 15 tests
  - `tests/test_csv_exporter.py` — 9 tests

- **Documentation** (`docs/`)
  - `README.md` — full technical reference (16 sections)
  - `user_guide.md` — end-to-end user guide
  - `architecture.md` — system design and data flow
  - `api_reference.md` — public API for all classes and functions
  - `contributing.md` — guide for adding new parsers

- **Scripts** (`scripts/`)
  - `verify_parsers.py` — live diagnostic summary of all parsers

#### Fixed

- `config.py`: moved `import copy` to module level (was inside `_deep_copy()` function body)
- `cli.py`: added `.expanduser()` to path resolution in both `_gather_messages()` and `cmd_list_tools()` so `~` in YAML paths is resolved correctly
- Antigravity tag stripping: added fallback for sessions where the `<USER_REQUEST>` closing tag is absent due to very long prompt content
- Claude Code parser: `test_session_has_correct_id` renamed — session ID on `ParsedSession` is correctly the file stem, while `Message.session_id` comes from the `sessionId` field in each record

#### Project structure

```
ai_tracker/          Core Python package
config/              YAML configuration
docs/                Documentation
scripts/             Utility scripts
tests/               Test suite + fixtures
ai-tracker.ps1       Windows run wrapper
pyproject.toml       Package definition
```

---

## Planned — Phase 2

Chrome Extension to capture conversations from web-based AI tools (ChatGPT, Claude.ai, Gemini). Will produce CSV output using the same six-column schema defined in Phase 1.
