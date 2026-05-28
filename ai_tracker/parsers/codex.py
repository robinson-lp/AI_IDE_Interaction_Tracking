from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import Message, ParsedSession
from .base import BaseParser


class CodexParser(BaseParser):
    """
    Parser for OpenAI Codex local session files.

    Codex CLI typically stores session data under ~/.codex/ in JSON or JSONL
    format.  This parser handles both:
      - JSONL files (one JSON object per line)
      - JSON array files (a list of message objects)

    The expected record schema is:
      { "role": "user"|"assistant", "content": "...", "timestamp": "..." }

    Override config/tools.yaml → tools.codex.path if the storage location
    differs in your Codex version.
    """

    def __init__(self, file_path: Path, tool_name: str = "codex") -> None:
        super().__init__(file_path, tool_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> List[ParsedSession]:
        self._validate_file()
        if self.file_path.is_dir():
            return self._parse_directory(self.file_path)
        session = self._parse_file(self.file_path)
        return [session] if session else []

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_directory(self, directory: Path) -> List[ParsedSession]:
        sessions: List[ParsedSession] = []
        for suffix in ("*.jsonl", "*.json"):
            for f in sorted(directory.rglob(suffix)):
                session = self._parse_file(f)
                if session:
                    sessions.append(session)
        return sessions

    def _parse_file(self, file_path: Path) -> Optional[ParsedSession]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # Find the first non-empty line to determine format.
        # JSON array files start with "["; everything else is treated as JSONL
        # (which silently skips malformed lines).
        first_nonempty = next(
            (ln.strip() for ln in content.splitlines() if ln.strip()), ""
        )
        try:
            if first_nonempty.startswith("["):
                messages = self._parse_json_array(content, str(file_path))
            else:
                messages = self._parse_jsonl(content, str(file_path))
        except Exception:
            return None

        if not messages:
            return None

        return ParsedSession(
            session_id=file_path.stem,
            tool=self.tool_name,
            file_path=str(file_path),
            messages=messages,
        )

    def _parse_jsonl(self, content: str, file_path: str) -> List[Message]:
        session_id = str(uuid.uuid4())
        messages: List[Message] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = self._record_to_message(record, session_id, file_path)
            if msg:
                messages.append(msg)
        return messages

    def _parse_json_array(self, content: str, file_path: str) -> List[Message]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
        records = data if isinstance(data, list) else [data]
        session_id = str(uuid.uuid4())
        messages: List[Message] = []
        for record in records:
            msg = self._record_to_message(record, session_id, file_path)
            if msg:
                messages.append(msg)
        return messages

    def _record_to_message(
        self, record: dict, session_id: str, file_path: str
    ) -> Optional[Message]:
        if not isinstance(record, dict):
            return None
        role = record.get("role", record.get("type", ""))
        content = record.get("content", record.get("text", record.get("message", "")))
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if not role or not content:
            return None
        return Message(
            session_id=record.get("session_id", session_id),
            timestamp=_parse_timestamp(record.get("timestamp", record.get("created_at"))),
            role=_normalise_role(role),
            message=str(content),
            tool=self.tool_name,
            file_path=file_path,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_timestamp(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalise_role(role: str) -> str:
    r = role.lower().strip()
    if r in ("human", "user", "h", "u"):
        return "human"
    if r in ("assistant", "ai", "model", "bot", "a", "system"):
        return "assistant"
    return r
