from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import ParsedSession


class BaseParser(ABC):
    """Abstract base for all IDE session file parsers."""

    def __init__(self, file_path: Path, tool_name: str) -> None:
        self.file_path = Path(file_path)
        self.tool_name = tool_name

    @abstractmethod
    def parse(self) -> List[ParsedSession]:
        """Parse source file(s) and return all discovered sessions."""
        ...

    def _validate_file(self) -> None:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Source not found: {self.file_path}")

    def filter_by_date(
        self,
        sessions: List[ParsedSession],
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> List[ParsedSession]:
        """Return sessions that have at least one message within [start, end]."""
        if not (start or end):
            return sessions

        filtered: List[ParsedSession] = []
        for session in sessions:
            in_range = [m for m in session.messages if _in_range(m.timestamp, start, end)]
            if in_range:
                filtered.append(replace(session, messages=in_range))
        return filtered


def _in_range(
    ts: Optional[datetime],
    start: Optional[datetime],
    end: Optional[datetime],
) -> bool:
    if ts is None:
        return True
    if start and ts.replace(tzinfo=None) < start.replace(tzinfo=None):
        return False
    if end and ts.replace(tzinfo=None) > end.replace(tzinfo=None):
        return False
    return True


def _parse_timestamp(value: object) -> Optional[datetime]:
    """Parse an ISO 8601 string or Unix epoch int/float into a datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _normalise_role(role: str) -> str:
    r = role.lower().strip()
    if r in ("human", "user", "h", "u"):
        return "human"
    if r in ("ai", "assistant", "model", "bot", "a"):
        return "assistant"
    return r


def _clean_project_name(name: str) -> str:
    """Normalize project directory names or slugs into clean titles."""
    if not name:
        return "General"
    
    cleaned = name.strip()
    
    # Strip common system prefix directories from tools like Claude Code (e.g. c--Users-Robin-xxx)
    if "--" in cleaned:
        parts = cleaned.split("--")
        if len(parts) > 1:
            cleaned = parts[-1]
            
    # Check for username / Users / home prefix patterns to remove them
    slug_parts = cleaned.split("-")
    if len(slug_parts) > 2:
        if slug_parts[0].lower() == "users":
            slug_parts = slug_parts[2:]
            cleaned = "-".join(slug_parts)
        elif len(slug_parts) > 3 and slug_parts[0].lower() == "c" and slug_parts[1].lower() == "users":
            slug_parts = slug_parts[3:]
            cleaned = "-".join(slug_parts)
        elif slug_parts[0].lower() == "home":
            slug_parts = slug_parts[2:]
            cleaned = "-".join(slug_parts)
            
    # Replace hyphens and underscores with spaces, strip, and capitalize each word
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    cleaned = " ".join(cleaned.split()) # clean up extra whitespaces
    
    return cleaned.title() if cleaned else "General"

