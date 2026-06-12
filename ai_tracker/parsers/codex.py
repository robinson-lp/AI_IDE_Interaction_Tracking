from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..models import Message, ParsedSession
from .base import BaseParser, _clean_project_name, _normalise_role, _parse_timestamp


class CodexParser(BaseParser):
    """
    Parser for OpenAI Codex local session files.

    Handles three distinct formats automatically:

    1. Codex Desktop event-log JSONL (~/.codex/sessions/YYYY/MM/DD/*.jsonl)
       First line type is "session_meta".  Extracts user prompts from
       event_msg/user_message records and final AI responses from
       event_msg/agent_message records with phase="final_answer".

    2. Simple JSONL (one {"role":..., "content":...} object per line)

    3. JSON array (a list of the same record objects)

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
            lines = []
            with open(file_path, "rb") as fh:
                for lineno, raw_bytes in enumerate(fh, 1):
                    try:
                        lines.append(raw_bytes.decode("utf-8"))
                    except UnicodeDecodeError:
                        logger.warning("Skipping line %d in %s: invalid UTF-8 bytes", lineno, file_path)
            content = "".join(lines)
        except OSError:
            return None

        first_nonempty = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")

        try:
            _parsed = json.loads(first_nonempty) if first_nonempty else {}
            first_record = _parsed if isinstance(_parsed, dict) else {}
        except json.JSONDecodeError:
            first_record = {}

        try:
            if _is_codex_desktop_format(first_record):
                messages, project_name = self._parse_codex_desktop(content, str(file_path))
            elif first_nonempty.startswith("["):
                project_name = _project_name_from_path(file_path)
                messages = self._parse_json_array(content, str(file_path), project_name)
            else:
                project_name = _project_name_from_path(file_path)
                messages = self._parse_jsonl(content, str(file_path), project_name)
        except Exception:
            return None

        if not messages:
            return None

        return ParsedSession(
            session_id=file_path.stem,
            tool=self.tool_name,
            file_path=str(file_path),
            project=project_name,
            messages=messages,
        )

    # ------------------------------------------------------------------
    # Codex Desktop event-log format
    # ------------------------------------------------------------------

    def _parse_codex_desktop(
        self, content: str, file_path: str
    ) -> Tuple[List[Message], str]:
        """Parse the Codex Desktop JSONL event-log format.

        Returns (messages, project_name).  Project name is extracted from the
        session_meta record's cwd field; messages come from event_msg records
        with type user_message or agent_message (final_answer phase only).
        """
        session_id = Path(file_path).stem
        project_name = "General"
        messages: List[Message] = []

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            record_type = record.get("type")
            payload = record.get("payload", {})
            ts = _parse_timestamp(record.get("timestamp"))

            if record_type == "session_meta":
                cwd = payload.get("cwd", "")
                if cwd:
                    project_name = _clean_project_name(Path(cwd).name)
                session_id = payload.get("id", session_id)
                continue

            if record_type != "event_msg":
                continue

            msg_type = payload.get("type")

            if msg_type == "user_message":
                text = payload.get("message", "").strip()
                if text:
                    messages.append(Message(
                        session_id=session_id,
                        timestamp=ts,
                        role="human",
                        message=text,
                        tool=self.tool_name,
                        file_path=file_path,
                        project=project_name,
                    ))

            elif msg_type == "agent_message" and payload.get("phase") == "final_answer":
                text = payload.get("message", "").strip()
                if text:
                    messages.append(Message(
                        session_id=session_id,
                        timestamp=ts,
                        role="assistant",
                        message=text,
                        tool=self.tool_name,
                        file_path=file_path,
                        project=project_name,
                    ))

        return messages, project_name

    # ------------------------------------------------------------------
    # Simple JSONL / JSON-array format
    # ------------------------------------------------------------------

    def _parse_jsonl(self, content: str, file_path: str, project_name: str = "General") -> List[Message]:
        session_id = Path(file_path).stem
        messages: List[Message] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = self._record_to_message(record, session_id, file_path, project_name)
            if msg:
                messages.append(msg)
        return messages

    def _parse_json_array(self, content: str, file_path: str, project_name: str = "General") -> List[Message]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
        records = data if isinstance(data, list) else [data]
        session_id = Path(file_path).stem
        messages: List[Message] = []
        for record in records:
            msg = self._record_to_message(record, session_id, file_path, project_name)
            if msg:
                messages.append(msg)
        return messages

    def _record_to_message(
        self, record: dict, session_id: str, file_path: str, project_name: str = "General"
    ) -> Optional[Message]:
        if not isinstance(record, dict):
            return None
        role = record.get("role", record.get("type", ""))
        if role.lower().strip() == "system":
            return None
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
            project=project_name,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _is_codex_desktop_format(first_record: dict) -> bool:
    """Return True if the file uses the Codex Desktop event-log format."""
    return first_record.get("type") in (
        "session_meta", "event_msg", "response_item", "turn_context"
    )


def _project_name_from_path(file_path: Path) -> str:
    """Extract a project name from the directory component after 'projects/', if present."""
    try:
        parts = file_path.parts
        if "projects" in parts:
            idx = parts.index("projects")
            if idx + 1 < len(parts):
                return _clean_project_name(parts[idx + 1])
    except Exception:
        pass
    return "General"
