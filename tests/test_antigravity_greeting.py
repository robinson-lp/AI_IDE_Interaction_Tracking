"""Tests for the Antigravity IDE parser handling simple greeting prompts."""

import json
from pathlib import Path
from ai_tracker.parsers.antigravity import AntigravityParser


def test_antigravity_greeting_prompt(tmp_path: Path):
    # 1. Arrange: Create a temporary transcript.jsonl with a simple greeting prompt
    transcript_file = tmp_path / "transcript.jsonl"
    
    greeting_record = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-05-26T06:00:00Z",
        "content": "<USER_REQUEST>\nHello antigravity! Hope you are doing well.\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nLocal time: 2026-05-26T11:30:00+05:30\n</ADDITIONAL_METADATA>"
    }
    
    response_record = {
        "step_index": 1,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": "DONE",
        "created_at": "2026-05-26T06:00:02Z",
        "thinking": "Hello! I am doing great, thank you. How can I help you with your coding today?",
        "tool_calls": []
    }
    
    # Write the lines as JSONL
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(greeting_record) + "\n")
        f.write(json.dumps(response_record) + "\n")
        
    # 2. Act: Parse using AntigravityParser
    parser = AntigravityParser(transcript_file, tool_name="antigravity")
    sessions = parser.parse()
    
    # 3. Assert: Verify the greeting session and messages are parsed correctly
    assert len(sessions) == 1
    session = sessions[0]
    assert session.tool == "antigravity"
    assert len(session.messages) == 2
    
    # Verify Human Greeting Message
    human_msg = session.messages[0]
    assert human_msg.role == "human"
    assert "Hello antigravity! Hope you are doing well." in human_msg.message
    assert human_msg.timestamp.isoformat() == "2026-05-26T06:00:00+00:00"
    
    # Verify Assistant Response Message
    assistant_msg = session.messages[1]
    assert assistant_msg.role == "assistant"
    assert assistant_msg.message == "Hello! I am doing great, thank you. How can I help you with your coding today?"
    assert assistant_msg.timestamp.isoformat() == "2026-05-26T06:00:02+00:00"
