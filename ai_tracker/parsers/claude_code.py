from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import Message, ParsedSession
from .base import BaseParser, _clean_project_name


class ClaudeCodeParser(BaseParser):
    """
    Parses Claude Code session files stored under ~/.claude/projects/.

    Layout observed on disk:
      ~/.claude/projects/<project-slug>/
          <session-uuid>.jsonl          ← main conversation
          <session-uuid>/subagents/
              agent-<id>.jsonl          ← subagent (sidechain) threads

    Each JSONL line is one event.  Only "user" and "assistant" type records
    are extracted; queue-operation, attachment, and system events are skipped.
    Sidechain records (isSidechain: true) are skipped unless include_sidechains
    is True.
    """

    def __init__(
        self,
        file_path: Path,
        tool_name: str = "claudecode",
        include_sidechains: bool = True,
    ) -> None:
        super().__init__(file_path, tool_name)
        self.include_sidechains = include_sidechains

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> List[ParsedSession]:
        self._validate_file()
        if self.file_path.is_dir():
            return self._parse_projects_dir(self.file_path)
        if self.file_path.suffix == ".jsonl":
            session = self._parse_jsonl_file(self.file_path)
            return [session] if session else []
        raise ValueError(
            f"Expected a directory or .jsonl file, got: {self.file_path}"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_projects_dir(self, root: Path) -> List[ParsedSession]:
        sessions: List[ParsedSession] = []
        for jsonl_file in sorted(root.rglob("*.jsonl")):
            if not self.include_sidechains and "subagents" in jsonl_file.parts:
                continue
            session = self._parse_jsonl_file(jsonl_file)
            if session:
                sessions.append(session)
        sessions.sort(key=lambda s: s.messages[0].timestamp.isoformat() if s.messages[0].timestamp else "")
        return sessions

    def _parse_jsonl_file(self, file_path: Path) -> Optional[ParsedSession]:
        # Derive session_id from filename (UUID) when possible
        try:
            session_id = str(uuid.UUID(file_path.stem))
        except ValueError:
            session_id = file_path.stem

        # Extract project slug from file_path parts
        project_name = "General"
        try:
            parts = file_path.parts
            if "projects" in parts:
                idx = parts.index("projects")
                if idx + 1 < len(parts):
                    project_name = _clean_project_name(parts[idx + 1])
        except Exception:
            pass

        messages: List[Message] = []
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg = self._record_to_message(record, session_id, str(file_path), project_name)
                    if msg:
                        messages.append(msg)
        except OSError:
            return None

        if not messages:
            return None

        return ParsedSession(
            session_id=session_id,
            tool=self.tool_name,
            file_path=str(file_path),
            project=project_name,
            messages=messages,
        )

    def _record_to_message(
        self, record: dict, session_id: str, file_path: str, project_name: str = "General"
    ) -> Optional[Message]:
        if record.get("type") not in ("user", "assistant"):
            return None
        if not self.include_sidechains and record.get("isSidechain", False):
            return None

        blob = record.get("message", {})
        if not isinstance(blob, dict):
            return None

        role = blob.get("role", record.get("type", ""))
        text = _extract_text(blob.get("content", ""))
        if not text:
            return None

        return Message(
            session_id=record.get("sessionId", session_id),
            timestamp=_parse_iso(record.get("timestamp")),
            role=_normalise_role(role),
            message=text,
            tool=self.tool_name,
            file_path=file_path,
            project=project_name,
        )


# ------------------------------------------------------------------
# Helpers (module-level, reused by other parsers)
# ------------------------------------------------------------------

def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def _parse_iso(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _normalise_role(role: str) -> str:
    r = role.lower().strip()
    if r in ("human", "user"):
        return "human"
    if r in ("ai", "assistant", "model"):
        return "assistant"
    return r
