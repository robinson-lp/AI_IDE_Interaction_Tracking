"""Quick verification script — prints a live summary of all parsers."""
from pathlib import Path

from ai_tracker.parsers.antigravity import AntigravityParser
from ai_tracker.parsers.claude_code import ClaudeCodeParser
from ai_tracker.parsers.codex import CodexParser

SEP = "=" * 62

# ── ANTIGRAVITY ──────────────────────────────────────────────────────────────
ag_brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
ag_sessions = AntigravityParser(ag_brain).parse()
ag_msgs = [m for s in ag_sessions for m in s.messages]

print(SEP)
print(f"ANTIGRAVITY  |  {len(ag_sessions)} sessions  |  {len(ag_msgs)} messages")
print(SEP)
for s in ag_sessions:
    human = [m for m in s.messages if m.role == "human"]
    ai    = [m for m in s.messages if m.role == "assistant"]
    print(f"  Session : {s.session_id}")
    print(f"  File    : {s.file_path}")
    print(f"  Messages: {len(s.messages)}  (human={len(human)}, assistant={len(ai)})")
    if human:
        ts = human[0].timestamp.isoformat() if human[0].timestamp else "no timestamp"
        print(f"  Sample  : [{ts}]")
        print(f"            {human[0].message[:90]!r}")
    print()

# ── CLAUDE CODE ──────────────────────────────────────────────────────────────
cc_dir = Path.home() / ".claude" / "projects"
cc_sessions = ClaudeCodeParser(cc_dir).parse()
cc_msgs = [m for s in cc_sessions for m in s.messages]

print(SEP)
print(f"CLAUDE CODE  |  {len(cc_sessions)} sessions  |  {len(cc_msgs)} messages")
print(SEP)
for s in cc_sessions[:5]:
    human = [m for m in s.messages if m.role == "human"]
    ai    = [m for m in s.messages if m.role == "assistant"]
    print(f"  Session : {s.session_id}")
    print(f"  Messages: {len(s.messages)}  (human={len(human)}, assistant={len(ai)})")
    if human:
        ts = human[0].timestamp.isoformat() if human[0].timestamp else "no timestamp"
        print(f"  First   : [{ts}]")
        print(f"            {human[0].message[:90]!r}")
    print()

if len(cc_sessions) > 5:
    remaining = sum(len(s.messages) for s in cc_sessions[5:])
    print(f"  ... {len(cc_sessions) - 5} more sessions  ({remaining} more messages)")

# ── CODEX ────────────────────────────────────────────────────────────────────
codex_dir = Path.home() / ".codex"
if codex_dir.exists():
    codex_sessions = CodexParser(codex_dir).parse()
    codex_msgs = [m for s in codex_sessions for m in s.messages]
    print(SEP)
    print(f"CODEX        |  {len(codex_sessions)} sessions  |  {len(codex_msgs)} messages")
    print(SEP)
    for s in codex_sessions[:5]:
        human = [m for m in s.messages if m.role == "human"]
        ai    = [m for m in s.messages if m.role == "assistant"]
        print(f"  Session : {s.session_id}")
        print(f"  Messages: {len(s.messages)}  (human={len(human)}, assistant={len(ai)})")
        if human:
            ts = human[0].timestamp.isoformat() if human[0].timestamp else "no timestamp"
            print(f"  First   : [{ts}]")
            print(f"            {human[0].message[:90]!r}")
        print()
    if len(codex_sessions) > 5:
        remaining = sum(len(s.messages) for s in codex_sessions[5:])
        print(f"  ... {len(codex_sessions) - 5} more sessions  ({remaining} more messages)")
else:
    codex_msgs = []
    print(SEP)
    print(f"CODEX        |  not found at {codex_dir}")
    print(SEP)

print()
print(SEP)
print(f"TOTAL  |  {len(ag_msgs) + len(cc_msgs) + len(codex_msgs)} messages across all tools")
print(SEP)
