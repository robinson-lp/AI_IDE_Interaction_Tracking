# Architecture — AI Interaction Tracking System

---

## Overview

`ai-tracker` is a read-only CLI tool. It discovers session files written to disk by AI IDE tools, parses them into a normalized in-memory representation, and exports a flat CSV.

```
AI IDE tools (on disk)
    ↓
Parsers (per-tool)
    ↓
Normalized data model  →  CSV export
```

No network calls. No writes to source files. No database. The tool is stateless — every run re-reads the files from scratch.

---

## Directory Structure

```
ai_tracker/                   Core package
├── __init__.py               Version string
├── models.py                 Data classes: Message, ParsedSession
├── config.py                 Built-in defaults + YAML config loader
├── cli.py                    argparse entry point
├── parsers/
│   ├── __init__.py           PARSER_REGISTRY dict + get_parser() factory
│   ├── base.py               BaseParser ABC + date-filter helper
│   ├── antigravity.py        Antigravity IDE parser
│   ├── claude_code.py        Claude Code parser
│   └── codex.py              OpenAI Codex parser
└── exporters/
    ├── __init__.py
    └── csv_exporter.py       UTF-8 CSV writer

tests/
├── fixtures/                 Static JSONL files used by unit tests
├── test_antigravity_parser.py
├── test_claude_code_parser.py
└── test_csv_exporter.py

config/
└── tools.yaml                User-editable path overrides

scripts/
└── verify_parsers.py         Live diagnostic script

docs/                         This documentation
├── README.md                 Full technical reference
├── user_guide.md             End-to-end user guide (this machine)
├── architecture.md           This file
├── api_reference.md          Public API for all classes
└── contributing.md           How to add new parsers
```

---

## Data Flow

```
cmd_parse()
│
├─ load_config()                     Read config/tools.yaml (merge over defaults)
├─ end_date adjusted to 23:59:59     Ensures full-day coverage when date-only supplied
│
└─ for each tool:
    ├─ resolve path                  str → Path → .expanduser()
    ├─ get_parser(tool, path)        Registry lookup → instantiate parser class
    ├─ parser.parse()                Return List[ParsedSession] (sorted by first-message timestamp)
    ├─ parser.filter_by_date(...)    Optional date-range filter
    └─ flatten messages              session.messages for each session
│
├─ optional --project filter         Keep only messages whose project matches
├─ sort all_messages by timestamp    Global chronological order across all tools
│
└─ CSVExporter.export(all_messages)  Write UTF-8 CSV
```

### Message lifecycle

1. A raw JSON record is read from a source file
2. The parser resolves the **project name** for the session (see Session Categorization below)
3. The parser maps its fields to a `Message` dataclass instance (including `project`)
4. `Message` is appended to a `ParsedSession`
5. All sessions from all tools are flattened into one `List[Message]`, sorted globally by timestamp
6. `CSVExporter` calls `message.to_dict()` and writes each row

---

## Data Model

### `Message`

The atomic unit. One human prompt or one AI response.

```python
@dataclass
class Message:
    session_id: str            # UUID of the session
    timestamp: Optional[datetime]
    role: str                  # "human" | "assistant"
    message: str               # Full text content
    tool: str                  # "antigravity" | "claudecode" | "codex"
    file_path: str             # Absolute path of source file
    project: str               # Resolved project name (default: "General")
```

`to_dict()` serialises to a flat dict with `project` as the first key, matching the CSV column order.

### `ParsedSession`

A container grouping all messages from one session together.

```python
@dataclass
class ParsedSession:
    session_id: str
    tool: str
    file_path: str
    project: str               # Resolved project name (default: "General")
    messages: List[Message]
```

`ParsedSession` is used during parsing and date filtering but is never exported directly — the exporter works with the flattened `List[Message]`.

---

## Parser Design

### Abstract Base Class

All parsers inherit from `BaseParser` (ABC):

```python
class BaseParser(ABC):
    def __init__(self, file_path: Path, tool_name: str) -> None: ...

    @abstractmethod
    def parse(self) -> List[ParsedSession]: ...

    def _validate_file(self) -> None: ...         # raises FileNotFoundError
    def filter_by_date(...) -> List[ParsedSession]: ...
```

`base.py` also exports a shared helper used by all parsers:

```python
def _clean_project_name(name: str) -> str: ...
```

This normalises raw directory slugs (e.g. `c--Users-Robin-AI-TRACKING-SYSTEM-PYTHON-SCRIPT`) into human-readable project titles (e.g. `Ai Tracking System Python Script`) by stripping path prefixes, replacing hyphens/underscores with spaces, and applying title-case.

Adding a new parser is a matter of subclassing `BaseParser` and implementing `parse()`. Everything else (date filtering, path validation, project name cleaning, CSV export) is already provided.

### Parser Registry

`parsers/__init__.py` maps tool name strings to parser classes:

```python
PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    "antigravity": AntigravityParser,
    "claudecode":  ClaudeCodeParser,
    "codex":       CodexParser,
}
```

The `get_parser(tool, file_path, **kwargs)` factory instantiates the correct class. The CLI uses the registry to enumerate tools and route `--tool all` runs — it never imports individual parser classes directly.

---

## Configuration System

`load_config()` in `config.py` applies a two-level merge:

```
_DEFAULT_CONFIG   (hardcoded in config.py)
      ↓
  deep copy
      ↓
  + config/tools.yaml   (user overrides, if file exists)
      ↓
  merged config dict
```

Only keys present in `tools.yaml` are overwritten. Keys not mentioned keep their defaults. This means partial YAML files are safe — you can override just one tool's path without touching the others.

Paths from the config (which may contain `~`) are expanded with `.expanduser()` at the point of use in `cli.py`, not at load time. This allows the config dict to be serialised or inspected with the original `~` notation intact.

---

## Session Categorization by Project

Every `Message` and `ParsedSession` carries a `project` field that identifies which workspace or codebase the conversation was about. Each parser resolves this name differently based on what metadata is available in its source files.

### Claude Code

The project name is derived from the **file path** of the session JSONL file. Claude Code stores sessions under:

```
~/.claude/projects/<project-slug>/<session-uuid>.jsonl
```

The `<project-slug>` directory name is the raw slug Claude Code generates from the workspace path (e.g. `c--Users-Robin-AI-TRACKING-SYSTEM-PYTHON-SCRIPT`). The parser extracts this slug and passes it through `_clean_project_name()` to produce a readable title.

```python
parts = file_path.parts
idx = parts.index("projects")
project_name = _clean_project_name(parts[idx + 1])
```

### Antigravity IDE

Antigravity does not encode the project in the file path — all sessions live under the same `brain/` directory regardless of workspace. Instead, the parser scans the `<ADDITIONAL_METADATA>` block embedded in the first user message record of the session and applies three detection strategies in priority order:

| Priority | Strategy | Detected from |
|---|---|---|
| A | Workspace mapping | `C:\path\to\project -> username/repo-name` pattern |
| B | Active Document path | `Active Document: C:\Users\Robin\ProjectFolder\file.py` |
| C | General path fallback | Any `C:\Users\username\FolderName` pattern |

All three options pass the extracted name through `_clean_project_name()`. If none match, the session is assigned `"General"`.

```python
def _extract_project_name(self, records: List[dict]) -> str:
    for record in records:
        if source == USER_EXPLICIT and type == USER_INPUT:
            # Try Option A, B, C in order
            ...
    return "General"
```

### Codex

Uses the same file-path strategy as Claude Code — extracts the folder name immediately after a `projects/` directory component, if present. Otherwise falls back to `"General"`.

### `_clean_project_name()` — Normalization Rules

| Input slug | Output |
|---|---|
| `c--Users-Robin-AI-TRACKING-SYSTEM-PYTHON-SCRIPT` | `Ai Tracking System Python Script` |
| `AI-TRACKING-SYSTEM` | `Ai Tracking System` |
| `Users-Robin-my-project` → strips `Users-Robin-` prefix | `My Project` |
| `""` or unresolvable | `General` |

The function strips OS path prefixes (`c--`, `Users-<name>-`, `home-<name>-`), replaces hyphens and underscores with spaces, collapses extra whitespace, and applies `.title()`.

### CSV Column

The resolved project name appears as the **first column** in every exported CSV:

```
project | session_id | timestamp | role | message | tool | file_path
```

### CLI Filter

Use `--project` to export messages for a specific project only:

```powershell
ai-tracker parse --tool all --project "AI Tracking System Python Script" -o project.csv
```

The filter is case-insensitive and uses substring matching, so partial names work:

```powershell
ai-tracker parse --tool all --project "tracking" -o tracking.csv
```

---

## Date Filtering

`BaseParser.filter_by_date(sessions, start, end)` operates on the parsed in-memory list.

- A session is kept if at least one of its messages falls within the range
- Messages outside the range are removed from the session (not just the session itself)
- Messages with `timestamp=None` are always kept (no timestamp = no filter basis)
- Timezone-aware timestamps are compared after stripping timezone info with `.replace(tzinfo=None)` to avoid comparison errors between aware and naive datetimes

---

## Error Handling Strategy

The CLI uses a fail-soft strategy:

- `FileNotFoundError` for a tool: prints a skip notice to stderr, continues to the next tool
- Any other exception per tool: prints an error to stderr, sets the exit code to 1, but still exports whatever was collected
- If no messages are found at all: prints to stderr and exits with code 1

Individual parsers use `try/except` around file I/O and per-line JSON parsing so that one corrupt file or malformed line does not abort the entire run.

---

## Source File Formats

### Antigravity IDE (`transcript.jsonl` / `overview.txt`)

JSONL — one JSON object per line. Each object is one step in the agent loop.

Relevant fields:

| Field | Type | Notes |
|---|---|---|
| `source` | string | `USER_EXPLICIT` or `MODEL` or `SYSTEM` |
| `type` | string | `USER_INPUT`, `PLANNER_RESPONSE`, tool types, etc. |
| `content` | string | For user messages — contains `<USER_REQUEST>` XML wrapper |
| `thinking` | string | For model responses — readable AI reasoning text |
| `created_at` | ISO 8601 | Timestamp |

### Claude Code (`.jsonl` session files)

JSONL — one JSON object per line. Each object is one conversation event.

Relevant fields:

| Field | Type | Notes |
|---|---|---|
| `type` | string | `user`, `assistant`, `queue-operation`, `attachment`, `system` |
| `isSidechain` | boolean | True for subagent threads |
| `sessionId` | string | UUID matching the filename |
| `timestamp` | ISO 8601 | Timestamp |
| `message.content` | string or list | Text, or list of `{type, text}` blocks |

### Codex (`.json` / `.jsonl`)

Either a JSON array of records, or JSONL. The parser auto-detects by checking whether the first non-empty line starts with `[`.

Relevant fields: `role`, `content`, `timestamp`.

---

## Testing Strategy

The test suite uses static fixture files (not mocks of the file system) and real-data integration tests.

- `tests/fixtures/` contains real-format JSONL samples for each parser
- Unit tests run against fixtures only — fast, no real data needed
- `TestRealAntigravityData` in `test_antigravity_parser.py` runs against real `~/.gemini/antigravity-ide/brain/` data if the path exists; it is skipped automatically on machines where it does not

Tests are intentionally not mocked at the file system level. Reading an actual file tests the full parsing path including encoding handling, line splitting, and JSON parsing — the parts most likely to break on real data.
