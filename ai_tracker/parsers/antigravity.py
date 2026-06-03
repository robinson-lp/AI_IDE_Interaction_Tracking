from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from ..models import Message, ParsedSession
from .base import BaseParser, _clean_project_name, _parse_timestamp

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
        sessions.sort(key=lambda s: s.messages[0].timestamp.isoformat() if s.messages[0].timestamp else "")
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
        records: List[dict] = []
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                        records.append(record)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return None

        if not records:
            return None

        project_name = self._extract_project_name(records)

        messages: List[Message] = []
        for record in records:
            msg = self._record_to_message(record, session_id, str(log_file), project_name)
            if msg:
                messages.append(msg)

        if not messages:
            return None

        return ParsedSession(
            session_id=session_id,
            tool=self.tool_name,
            file_path=str(log_file),
            project=project_name,
            messages=messages,
        )

    def _extract_project_name(self, records: List[dict]) -> str:
        """Scan session records for active workspace or document metadata to determine the project name."""
        for record in records:
            if record.get("source") == _HUMAN_SOURCE and record.get("type") == _HUMAN_TYPE:
                content = record.get("content", "")
                
                # Option A: Look for user workspace mapping:
                # e.g. "c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT -> robinson-lp/AI-TRACKING-SYSTEM-PYTHON-SCRIPT"
                m_workspace = re.search(r"(\w:\\[^\n->]+?)\s*->\s*[^/\n]+/([\w-]+)", content)
                if m_workspace:
                    return _clean_project_name(m_workspace.group(2))
                
                # Option B: Look for Active Document:
                # e.g. "Active Document: c:\Users\Robin\AI TRACKING SYSTEM PYTHON SCRIPT\tests\test_antigravity_greeting.py"
                m_doc = re.search(r"Active Document:\s*(\w:\\[^\n]+)", content)
                if m_doc:
                    doc_path = Path(m_doc.group(1).strip())
                    parts = doc_path.parts
                    if len(parts) > 3 and parts[1].lower() == "users":
                        return _clean_project_name(parts[3])
                
                # Option C: General windows folder fallback for any Users\username\Folder path
                m_users = re.search(r"\w:\\Users\\[^\\]+\\([^\\]+)", content)
                if m_users:
                    return _clean_project_name(m_users.group(1))
                    
        return "General"

    def _record_to_message(
        self, record: dict, session_id: str, file_path: str, project_name: str = "General"
    ) -> Optional[Message]:
        source = record.get("source", "")
        rtype = record.get("type", "")
        ts = _parse_timestamp(record.get("created_at"))

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
                project=project_name,
            )

        # AI response — PLANNER_RESPONSE with thinking text or content
        if source == _AI_SOURCE and rtype == _AI_TYPE:
            content = record.get("content", "")
            if content.strip():
                return Message(
                    session_id=session_id,
                    timestamp=ts,
                    role="assistant",
                    message=content,
                    tool=self.tool_name,
                    file_path=file_path,
                    project=project_name,
                )
            
            thinking = record.get("thinking", "")
            if thinking.strip():
                return Message(
                    session_id=session_id,
                    timestamp=ts,
                    role="assistant",
                    message=thinking,
                    tool=self.tool_name,
                    file_path=file_path,
                    project=project_name,
                )
            # AI decided to invoke tools — capture the decision verbatim
            tool_calls = record.get("tool_calls", [])
            if tool_calls:
                return Message(
                    session_id=session_id,
                    timestamp=ts,
                    role="assistant",
                    message=json.dumps(tool_calls),
                    tool=self.tool_name,
                    file_path=file_path,
                    project=project_name,
                )
            return None

        # Tool execution results (LIST_DIRECTORY, VIEW_FILE, RUN_COMMAND, etc.)
        if source == _AI_SOURCE:
            content = record.get("content", "")
            if content:
                return Message(
                    session_id=session_id,
                    timestamp=ts,
                    role="tool",
                    message=content,
                    tool=self.tool_name,
                    file_path=file_path,
                    project=project_name,
                )

        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
_INJECTED_BLOCK_RE = re.compile(r"<[A-Z_]+(?:\s[^>]*)?>.*?</[A-Z_]+>\n?", re.DOTALL)


def _extract_user_request(content: str) -> str:
    """Extract only the text the user typed, stripping all injected metadata blocks."""
    m = _USER_REQUEST_RE.search(content)
    if m:
        return m.group(1).strip()
    # Fallback: strip all injected uppercase-tag blocks and return remainder
    return _INJECTED_BLOCK_RE.sub("", content).strip()
