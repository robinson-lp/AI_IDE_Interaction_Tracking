# API Reference — ai_tracker

Public classes and functions available when using `ai_tracker` as a Python library.

---

## `ai_tracker.models`

### `Message`

```python
@dataclass
class Message:
    session_id: str
    timestamp: Optional[datetime]
    role: str
    message: str
    tool: str
    file_path: str
```

A single conversation turn — one human prompt or one AI response.

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | UUID of the session this message belongs to |
| `timestamp` | `Optional[datetime]` | When the message was sent; `None` if not available in the source file |
| `role` | `str` | `"human"` or `"assistant"` |
| `message` | `str` | Full text content |
| `tool` | `str` | Source tool identifier: `"antigravity"`, `"claudecode"`, `"codex"` |
| `file_path` | `str` | Absolute path of the source file — for audit tracing |

#### `Message.to_dict() -> dict`

Returns a flat dictionary with keys matching the CSV column order:

```python
{
    "session_id": str,
    "timestamp": str,   # ISO 8601 string, or "" if timestamp is None
    "role": str,
    "message": str,
    "tool": str,
    "file_path": str,
}
```

---

### `ParsedSession`

```python
@dataclass
class ParsedSession:
    session_id: str
    tool: str
    file_path: str
    messages: List[Message] = field(default_factory=list)
```

Groups all messages from one development session.

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | UUID of the session — typically the source filename stem or directory name |
| `tool` | `str` | Which tool produced this session |
| `file_path` | `str` | Absolute path of the source file |
| `messages` | `List[Message]` | All messages in parse order |

---

## `ai_tracker.parsers`

### `PARSER_REGISTRY`

```python
PARSER_REGISTRY: Dict[str, Type[BaseParser]]
```

Maps tool name strings to their parser classes:

```python
{
    "antigravity": AntigravityParser,
    "claudecode":  ClaudeCodeParser,
    "codex":       CodexParser,
}
```

---

### `get_parser`

```python
def get_parser(tool: str, file_path: Path, **kwargs) -> BaseParser
```

Factory function. Returns an instantiated parser for the given tool.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `tool` | `str` | Tool name — must be a key in `PARSER_REGISTRY` |
| `file_path` | `Path` | Path to the source file or directory |
| `**kwargs` | | Forwarded to the parser constructor (e.g. `include_sidechains=True` for Claude Code) |

**Raises**

- `ValueError` — if `tool` is not in `PARSER_REGISTRY`

**Example**

```python
from pathlib import Path
from ai_tracker.parsers import get_parser

parser = get_parser("claudecode", Path.home() / ".claude" / "projects")
sessions = parser.parse()
```

---

## `ai_tracker.parsers.base`

### `BaseParser`

```python
class BaseParser(ABC):
    def __init__(self, file_path: Path, tool_name: str) -> None
```

Abstract base class for all parsers.

#### Attributes

| Name | Type | Description |
|---|---|---|
| `file_path` | `Path` | Source file or directory to parse |
| `tool_name` | `str` | Tool identifier string |

#### `parse() -> List[ParsedSession]` *(abstract)*

Must be implemented by every parser subclass. Reads the source file(s) and returns all discovered sessions.

#### `filter_by_date(sessions, start, end) -> List[ParsedSession]`

```python
def filter_by_date(
    self,
    sessions: List[ParsedSession],
    start: Optional[datetime],
    end: Optional[datetime],
) -> List[ParsedSession]
```

Returns only sessions that have at least one message within `[start, end]`. Messages outside the range are removed from their session. Messages with `timestamp=None` are always kept.

Both `start` and `end` are optional. If both are `None`, the input list is returned unchanged.

#### `_validate_file() -> None`

Raises `FileNotFoundError` if `self.file_path` does not exist on disk.

---

## `ai_tracker.parsers.antigravity`

### `AntigravityParser`

```python
class AntigravityParser(BaseParser):
    def __init__(self, file_path: Path, tool_name: str = "antigravity") -> None
```

Parses Antigravity IDE session transcripts.

**Source path:** `~/.gemini/antigravity-ide/brain/`

Accepts either:
- A **directory** (the `brain/` root) — scans all UUID subdirectories automatically
- A **single file** (`transcript.jsonl` or `overview.txt`) — parses that file only

#### `parse() -> List[ParsedSession]`

Returns one `ParsedSession` per session directory that contains a log file with at least one extractable message.

**Extracted records:**

| Source | Type | Condition | Role |
|---|---|---|---|
| `USER_EXPLICIT` | `USER_INPUT` | Always | `human` |
| `MODEL` | `PLANNER_RESPONSE` | Only if `thinking` field is non-empty | `assistant` |

All other record types are skipped.

---

## `ai_tracker.parsers.claude_code`

### `ClaudeCodeParser`

```python
class ClaudeCodeParser(BaseParser):
    def __init__(
        self,
        file_path: Path,
        tool_name: str = "claudecode",
        include_sidechains: bool = False,
    ) -> None
```

Parses Claude Code JSONL session files.

**Source path:** `~/.claude/projects/`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `include_sidechains` | `bool` | `False` | When `False`, skips `.jsonl` files under any `subagents/` directory |

#### `parse() -> List[ParsedSession]`

Recursively finds all `*.jsonl` files under the source directory and parses each one.

**Extracted record types:**

| `type` field | `isSidechain` | Result |
|---|---|---|
| `user` | `False` | `role=human` |
| `assistant` | `False` | `role=assistant` |
| `user` or `assistant` | `True` | Skipped (unless `include_sidechains=True`) |
| `queue-operation`, `attachment`, `system` | any | Always skipped |

---

## `ai_tracker.parsers.codex`

### `CodexParser`

```python
class CodexParser(BaseParser):
    def __init__(self, file_path: Path, tool_name: str = "codex") -> None
```

Parses OpenAI Codex session files.

**Source path:** `~/.codex/`

Accepts either a single file or a directory. Auto-detects format per file:
- First non-empty line starts with `[` → JSON array
- Otherwise → JSONL (one object per line)

#### `parse() -> List[ParsedSession]`

Scans for `*.jsonl` and `*.json` files. Returns one `ParsedSession` per non-empty file.

**Expected record schema:**

```json
{ "role": "user", "content": "...", "timestamp": "..." }
```

Both Unix epoch timestamps (integer/float) and ISO 8601 strings are accepted in the `timestamp` field.

---

## `ai_tracker.exporters.csv_exporter`

### `CSVExporter`

```python
class CSVExporter:
    def __init__(self, output_path: Path) -> None
```

Writes a list of `Message` objects to a UTF-8 CSV file.

#### `export(messages: List[Message]) -> int`

Writes the CSV file and returns the number of rows written (excluding the header).

- Creates parent directories automatically if they do not exist
- Always writes a header row, even for an empty `messages` list
- Column order: `session_id`, `timestamp`, `role`, `message`, `tool`, `file_path`
- Encoding: UTF-8 (handles Unicode, emoji, CJK characters)

**Example**

```python
from pathlib import Path
from ai_tracker.exporters.csv_exporter import CSVExporter

exporter = CSVExporter(Path("output/interactions.csv"))
count = exporter.export(messages)
print(f"Wrote {count} rows")
```

---

## `ai_tracker.config`

### `load_config`

```python
def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]
```

Returns the merged configuration dictionary.

Reads `config/tools.yaml` (or `config_path` if provided) and merges it over `_DEFAULT_CONFIG`. If the YAML file does not exist, returns the defaults unchanged.

**Returns** a dict with structure:

```python
{
    "tools": {
        "antigravity": {"path": str, "parser": str},
        "claudecode":  {"path": str, "parser": str, "include_sidechains": bool},
        "codex":       {"path": str, "parser": str},
    }
}
```

### `DEFAULT_TOOL_PATHS`

```python
DEFAULT_TOOL_PATHS: Dict[str, Path]
```

Built-in default paths for each tool (before `~` expansion):

```python
{
    "antigravity": Path("~/.gemini/antigravity-ide/brain"),
    "claudecode":  Path("~/.claude/projects"),
    "codex":       Path("~/.codex"),
}
```

---

## `ai_tracker.cli`

The CLI is the primary interface. Functions below are documented for testing and programmatic use.

### `main() -> None`

Entry point. Parses `sys.argv`, dispatches to `cmd_parse` or `cmd_list_tools`, exits with the handler's return code.

### `cmd_parse(args: argparse.Namespace) -> int`

Runs the parse command. Returns `0` on success, `1` if any error occurred or no messages were found.

### `cmd_list_tools(args: argparse.Namespace) -> int`

Prints the tool status table. Always returns `0`.
