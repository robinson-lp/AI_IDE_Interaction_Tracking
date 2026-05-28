from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import Message, ParsedSession
from .base import BaseParser

# Extracts text between <USER_REQUEST> tags in the content field
_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)

# Records to extract — everything else (SYSTEM, tool results) is skipped
_HUMAN_SOURCE = "USER_EXPLICIT"
_HUMAN_TYPE = "USER_INPUT"
_AI_SOURCE = "MODEL"
_AI_TYPE = "PLANNER_RESPONSE"


class AntigravityParser(BaseParser):
    """
    Parses Antigravity IDE session transcripts from:
      ~/.gemini/antigravity-ide/brain/<session-uuid>/.system_generated/logs/transcript.jsonl
      ~/.gemini/antigravity-ide/brain/<session-uuid>/.system_generated/logs/overview.txt

    Each session directory is a UUID folder.  The parser scans all session
    directories under the root brain path and reads whichever log file exists.

    Extracted records:
      - Human messages: source=USER_EXPLICIT, type=USER_INPUT
        → text inside <USER_REQUEST> tags
      - AI thinking:    source=MODEL, type=PLANNER_RESPONSE with a "thinking" field
        → the thinking text (readable AI reasoning)

    Tool-call-only PLANNER_RESPONSE records (no thinking field) are skipped
    as they represent intermediate agent steps, not readable responses.
    """

    _LOG_FILENAMES = ("transcript.jsonl", "overview.txt")

    def __init__(self, file_path: Path, tool_name: str = "antigravity") -> None:
        super().__init__(file_path, tool_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> List[ParsedSession]:
        self._validate_file()

        if self.file_path.is_dir():
            return self._parse_brain_dir(self.file_path)

        # Single file passed directly
        session = self._parse_log_file(self.file_path, self.file_path.parent.parent.name)
        return [session] if session else []

    # ------------------------------------------------------------------
    # Directory traversal
    # ------------------------------------------------------------------

    def _parse_brain_dir(self, brain_dir: Path) -> List[ParsedSession]:
        sessions: List[ParsedSession] = []
        for session_dir in sorted(brain_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            log_file = self._find_log_file(session_dir)
            if log_file is None:
                continue
            session = self._parse_log_file(log_file, session_dir.name)
            if session:
                sessions.append(session)
        return sessions

    def _find_log_file(self, session_dir: Path) -> Optional[Path]:
        logs_dir = session_dir / ".system_generated" / "logs"
        if not logs_dir.exists():
            return None
        for name in self._LOG_FILENAMES:
            candidate = logs_dir / name
            if candidate.exists():
                return candidate
        return None

    # ------------------------------------------------------------------
    # Log file parsing
    # ------------------------------------------------------------------

    def _parse_log_file(self, log_file: Path, session_id: str) -> Optional[ParsedSession]:
        messages: List[Message] = []
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg = self._record_to_message(record, session_id, str(log_file))
                    if msg:
                        messages.append(msg)
        except OSError:
            return None

        if not messages:
            return None

        return ParsedSession(
            session_id=session_id,
            tool=self.tool_name,
            file_path=str(log_file),
            messages=messages,
        )

    def _record_to_message(
        self, record: dict, session_id: str, file_path: str
    ) -> Optional[Message]:
        source = record.get("source", "")
        rtype = record.get("type", "")
        ts = _parse_iso(record.get("created_at"))

        # Human prompt
        if source == _HUMAN_SOURCE and rtype == _HUMAN_TYPE:
            text = _extract_user_request(record.get("content", ""))
            if not text:
                return None
            return Message(
                session_id=session_id,
                timestamp=ts,
                role="human",
                message=text,
                tool=self.tool_name,
                file_path=file_path,
            )

        # AI thinking (readable response — skip pure tool-call records)
        if source == _AI_SOURCE and rtype == _AI_TYPE:
            thinking = record.get("thinking", "")
            if not thinking.strip():
                return None
            return Message(
                session_id=session_id,
                timestamp=ts,
                role="assistant",
                message=thinking,
                tool=self.tool_name,
                file_path=file_path,
            )

        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_user_request(content: str) -> str:
    """Return clean user prompt text, stripping all XML-like metadata tags."""
    # Try full <USER_REQUEST>...</USER_REQUEST> match first
    m = _USER_REQUEST_RE.search(content)
    if m:
        return m.group(1).strip()

    # Fallback: strip the opening tag and cut at the next XML block or end
    text = re.sub(r"<USER_REQUEST>\s*", "", content)
    # Remove anything from <ADDITIONAL_METADATA>, <USER_SETTINGS_CHANGE>, etc.
    text = re.split(r"\s*<[A-Z_]+>", text)[0]
    return text.strip()


def _parse_iso(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
