"""Activity and completion detection via Claude Code hooks.

Two hooks are registered in ~/.claude/settings.json:
  PreToolUse → writes a "working" marker when a turn starts processing.
  Stop       → clears the working marker and writes a "done" marker when done.

agentman polls these markers to show accurate per-project activity indicators.
"""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path


SHARE_DIR = Path.home() / ".local" / "share" / "agentman"
DONE_DIR = SHARE_DIR / "done"
WORKING_DIR = SHARE_DIR / "working"
HELPER = SHARE_DIR / "stop-hook.py"
WORKING_HELPER = SHARE_DIR / "pretool-hook.py"
SETTINGS = Path.home() / ".claude" / "settings.json"
_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Stop hook: clear working marker, write done marker.
HELPER_SRC = '''\
#!/usr/bin/env python3
# agentman Stop hook: record turn completion and clear the working marker.
import sys, json
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = data.get("session_id")
if sid:
    base = Path.home() / ".local" / "share" / "agentman"
    done = base / "done"
    done.mkdir(parents=True, exist_ok=True)
    (done / sid).write_text("")
    try:
        (base / "working" / sid).unlink()
    except FileNotFoundError:
        pass
sys.exit(0)
'''

# PreToolUse hook: write working marker when processing begins.
WORKING_HELPER_SRC = '''\
#!/usr/bin/env python3
# agentman PreToolUse hook: mark session as actively working.
import sys, json
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = data.get("session_id")
if sid:
    d = Path.home() / ".local" / "share" / "agentman" / "working"
    d.mkdir(parents=True, exist_ok=True)
    (d / sid).touch()
sys.exit(0)
'''


def _hook_command() -> str:
    python = shutil.which("python3") or sys.executable
    return f"{python} {HELPER}"


def _working_command() -> str:
    python = shutil.which("python3") or sys.executable
    return f"{python} {WORKING_HELPER}"


def _merge_hook(hooks_cfg: dict, event: str, helper_path: Path, cmd: str) -> bool:
    """Add a hook entry for `event` if not already present. Returns True if added."""
    entries = hooks_cfg.setdefault(event, [])
    already = any(
        str(helper_path) in h.get("command", "")
        for group in entries
        for h in group.get("hooks", [])
    )
    if already:
        return False
    entries.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
    return True


def install() -> None:
    """Write helpers and merge both hooks into user settings (idempotent)."""
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    HELPER.write_text(HELPER_SRC)
    HELPER.chmod(0o755)
    WORKING_HELPER.write_text(WORKING_HELPER_SRC)
    WORKING_HELPER.chmod(0o755)

    settings: dict = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text() or "{}")
        except json.JSONDecodeError:
            return  # don't risk clobbering an unparseable settings file

    hooks_cfg = settings.setdefault("hooks", {})
    changed = _merge_hook(hooks_cfg, "Stop", HELPER, _hook_command())
    changed |= _merge_hook(hooks_cfg, "PreToolUse", WORKING_HELPER, _working_command())

    if changed:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def is_done(session_id: str) -> bool:
    return (DONE_DIR / session_id).exists()


def clear_done(session_id: str) -> None:
    try:
        (DONE_DIR / session_id).unlink()
    except FileNotFoundError:
        pass


def is_working(session_id: str) -> bool:
    if (WORKING_DIR / session_id).exists():
        return True
    # Fallback: if a done marker exists and the transcript is newer, a new
    # prompt is in-flight before PreToolUse has fired yet.
    # We only trust the transcript mtime when there is a done marker to
    # compare against — that's the only safe baseline (set at turn end by the
    # Stop hook). Without a done marker we can't tell "prompt submitted but no
    # tool called yet" from "session just resumed and Claude is loading".
    done_file = DONE_DIR / session_id
    if not done_file.exists():
        return False
    matches = list(_CLAUDE_PROJECTS.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return False
    return matches[0].stat().st_mtime > done_file.stat().st_mtime


def clear_working(session_id: str) -> None:
    try:
        (WORKING_DIR / session_id).unlink()
    except FileNotFoundError:
        pass
