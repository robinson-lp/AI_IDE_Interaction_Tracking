from __future__ import annotations

from pathlib import Path
from typing import Dict, Type

from .antigravity import AntigravityParser
from .base import BaseParser
from .claude_code import ClaudeCodeParser
from .codex import CodexParser

PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    "antigravity": AntigravityParser,
    "claudecode": ClaudeCodeParser,
    "codex": CodexParser,
}


def get_parser(tool: str, file_path: Path, **kwargs: object) -> BaseParser:
    """Instantiate the correct parser for the given tool name."""
    cls = PARSER_REGISTRY.get(tool.lower())
    if cls is None:
        raise ValueError(
            f"Unknown tool: {tool!r}. Available: {sorted(PARSER_REGISTRY)}"
        )
    return cls(file_path=file_path, tool_name=tool, **kwargs)
