# Contributing Guide — Adding New Parsers

This guide explains how to extend `ai-tracker` with support for a new AI IDE tool.

---

## Overview

Each tool is supported by one parser class that inherits from `BaseParser`. Adding a new tool requires:

1. Create `ai_tracker/parsers/<toolname>.py` with your parser class
2. Register it in `ai_tracker/parsers/__init__.py`
3. Add default path and settings in `ai_tracker/config.py`
4. Write tests in `tests/test_<toolname>_parser.py`
5. Add a fixture file in `tests/fixtures/`

---

## Step 1 — Write the parser

Create `ai_tracker/parsers/mytool.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..models import Message, ParsedSession
from .base import BaseParser


class MyToolParser(BaseParser):
    """Parser for MyTool session files stored at ~/.mytool/"""

    def __init__(self, file_path: Path, tool_name: str = "mytool") -> None:
        super().__init__(file_path, tool_name)

    def parse(self) -> List[ParsedSession]:
        self._validate_file()                    # raises FileNotFoundError if missing
        if self.file_path.is_dir():
            return self._parse_directory(self.file_path)
        session = self._parse_file(self.file_path)
        return [session] if session else []

    def _parse_directory(self, directory: Path) -> List[ParsedSession]:
        sessions: List[ParsedSession] = []
        for f in sorted(directory.rglob("*.json")):
            session = self._parse_file(f)
            if session:
                sessions.append(session)
        return sessions

    def _parse_file(self, file_path: Path) -> Optional[ParsedSession]:
        messages: List[Message] = []

        # --- read and parse the file ---
        # Map each record to a Message; return None for unparseable files

        if not messages:
            return None

        return ParsedSession(
            session_id=file_path.stem,
            tool=self.tool_name,
            file_path=str(file_path),
            messages=messages,
        )
```

### Rules for `parse()`

- Must call `self._validate_file()` first — this raises `FileNotFoundError` if the path is missing. The CLI catches this and prints a skip notice.
- Must return `List[ParsedSession]` — an empty list is fine if there is no data.
- Wrap file I/O in `try/except OSError` so a single unreadable file does not abort the run.
- Wrap per-record parsing in `try/except` so a malformed record does not abort the file.
- Return `None` (not an empty `ParsedSession`) for files that contain no extractable messages — the caller filters out `None`.

### Role normalisation

Use exactly `"human"` or `"assistant"` for the `role` field in `Message`. Map the tool's native role names at parse time:

```python
role_map = {
    "user": "human",
    "human": "human",
    "assistant": "assistant",
    "ai": "assistant",
    "model": "assistant",
}
role = role_map.get(raw_role.lower(), raw_role.lower())
```

---

## Step 2 — Register the parser

Edit `ai_tracker/parsers/__init__.py`:

```python
from .mytool import MyToolParser          # add import

PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    "antigravity": AntigravityParser,
    "claudecode":  ClaudeCodeParser,
    "codex":       CodexParser,
    "mytool":      MyToolParser,           # add entry
}
```

The tool name you use as the key (`"mytool"`) is the value users pass to `--tool mytool`. It also becomes the `tool` field on every `Message` the parser produces.

---

## Step 3 — Add the default path

Edit `ai_tracker/config.py`:

```python
DEFAULT_TOOL_PATHS: Dict[str, Path] = {
    "antigravity": _HOME / ".gemini" / "antigravity-ide" / "brain",
    "claudecode":  _HOME / ".claude" / "projects",
    "codex":       _HOME / ".codex",
    "mytool":      _HOME / ".mytool",       # add entry
}

_DEFAULT_CONFIG: Dict[str, Any] = {
    "tools": {
        # ... existing tools ...
        "mytool": {
            "path": str(DEFAULT_TOOL_PATHS["mytool"]),
            "parser": "mytool",
        },
    }
}
```

---

## Step 4 — Write tests

Create `tests/test_mytool_parser.py`. At minimum, cover:

- **Happy path**: a fixture file with known content produces the expected `Message` objects
- **Role extraction**: `role` is `"human"` or `"assistant"`, not the raw value
- **Text extraction**: `message` field contains the right text
- **Timestamps**: parsed correctly; `None` if missing
- **Skipped records**: tool-only or system records produce no `Message`
- **Empty file**: returns an empty list, not an error
- **Missing path**: raises `FileNotFoundError`
- **Directory mode**: multiple files are all discovered

### Fixture files

Put static sample files in `tests/fixtures/`. Name them clearly:

```
tests/fixtures/mytool_sample.json
tests/fixtures/mytool_empty.json
```

Use real-format samples (copy a real file, strip sensitive content). Do not mock the file system — the tests should exercise the actual reading and parsing code.

### Test structure example

```python
import pytest
from pathlib import Path
from ai_tracker.parsers.mytool import MyToolParser

FIXTURES = Path(__file__).parent / "fixtures"


class TestMyToolParserSingleFile:
    def setup_method(self):
        self.parser = MyToolParser(FIXTURES / "mytool_sample.json")
        self.sessions = self.parser.parse()
        self.messages = [m for s in self.sessions for m in s.messages]

    def test_finds_messages(self):
        assert len(self.messages) > 0

    def test_roles_are_normalised(self):
        roles = {m.role for m in self.messages}
        assert roles.issubset({"human", "assistant"})

    def test_tool_name(self):
        assert all(m.tool == "mytool" for m in self.messages)


class TestMyToolParserMissingFile:
    def test_raises_file_not_found(self):
        parser = MyToolParser(Path("/nonexistent/path"))
        with pytest.raises(FileNotFoundError):
            parser.parse()
```

---

## Step 5 — Update documentation

- Add the new tool to the `PARSER_REGISTRY` table in [docs/api_reference.md](api_reference.md)
- Add a description of what it reads and the file format in [docs/README.md](README.md)
- Add an entry to [CHANGELOG.md](../CHANGELOG.md)

---

## Running the tests

```powershell
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
$env:PYTHONPATH = "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT"
& $py -m pytest tests -v
```

All existing tests must continue to pass after your addition.
