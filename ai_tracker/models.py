from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Message:
    """A single conversation turn — one human prompt or one AI response."""

    session_id: str
    timestamp: Optional[datetime]
    role: str       # "human" | "assistant"
    message: str
    tool: str       # "antigravity" | "claudecode" | "codex"
    file_path: str  # source file for audit trail

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "role": self.role,
            "message": self.message,
            "tool": self.tool,
            "file_path": self.file_path,
        }


@dataclass
class ParsedSession:
    """All messages belonging to a single development session."""

    session_id: str
    tool: str
    file_path: str
    messages: List[Message] = field(default_factory=list)
