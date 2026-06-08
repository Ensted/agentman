"""Completion detection via a Claude Code `Stop` hook.

We register a tiny Stop hook in ~/.claude/settings.json. Every time a claude
session finishes a turn it writes a marker file keyed by session id. agentman
watches those markers to flag background sessions that have finished working.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path


SHARE_DIR = Path.home() / ".local" / "share" / "agentman"
DONE_DIR = SHARE_DIR / "done"
HELPER = SHARE_DIR / "stop-hook.py"
SETTINGS = Path.home() / ".claude" / "settings.json"

HELPER_SRC = '''\
#!/usr/bin/env python3
# agentman Stop hook: record session turn completion.
import sys, json
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = data.get("session_id")
if sid:
    d = Path.home() / ".local" / "share" / "agentman" / "done"
    d.mkdir(parents=True, exist_ok=True)
    (d / sid).write_text("")
sys.exit(0)
'''


def _hook_command() -> str:
    return f"{sys.executable} {HELPER}"


def install() -> None:
    """Write the helper and merge the Stop hook into user settings (idempotent)."""
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    HELPER.write_text(HELPER_SRC)
    HELPER.chmod(0o755)

    settings: dict = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text() or "{}")
        except json.JSONDecodeError:
            return  # don't risk clobbering an unparseable settings file

    cmd = _hook_command()
    hooks = settings.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    already = any(
        cmd in h.get("command", "")
        for group in stop
        for h in group.get("hooks", [])
    )
    if already:
        return

    stop.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def is_done(session_id: str) -> bool:
    return (DONE_DIR / session_id).exists()


def clear_done(session_id: str) -> None:
    try:
        (DONE_DIR / session_id).unlink()
    except FileNotFoundError:
        pass
