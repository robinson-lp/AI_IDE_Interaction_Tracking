from __future__ import annotations

from abc import ABC, abstractmethod
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
                session.messages = in_range
                filtered.append(session)
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
