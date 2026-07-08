"""Activity and completion detection via Claude Code hooks.

Four hooks are registered in ~/.claude/settings.json:
  UserPromptSubmit → writes a "working" marker the moment a prompt is sent.
  PreToolUse       → re-touches the working marker on every tool call, so a
                     long turn keeps its marker fresh (used by the stale check).
  Stop             → clears the working marker and writes a "done" marker.
  SessionEnd       → removes both markers when the session exits.

agentman polls these markers to show accurate per-project activity indicators.

The Stop hook does not fire when a turn is interrupted (Escape), which would
leave the working marker stuck forever. is_working() therefore treats a marker
as dead once both it and the session transcript have gone quiet.
"""
from __future__ import annotations
import json
import shutil
import sys
import time
from pathlib import Path


SHARE_DIR = Path.home() / ".local" / "share" / "agentman"
DONE_DIR = SHARE_DIR / "done"
WORKING_DIR = SHARE_DIR / "working"
HELPER = SHARE_DIR / "stop-hook.py"
WORKING_HELPER = SHARE_DIR / "pretool-hook.py"
SESSION_END_HELPER = SHARE_DIR / "session-end-hook.py"
SETTINGS = Path.home() / ".claude" / "settings.json"
_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# A working marker is trusted only while it or the transcript is recent.
# Both go quiet together only when a turn died without its Stop hook
# (interrupt, crash) — or during a single very long silent tool call, in
# which case the next tool/Stop event revives the state anyway.
STALE_AFTER_S = 10 * 60

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

# UserPromptSubmit + PreToolUse hook: mark session as actively working.
WORKING_HELPER_SRC = '''\
#!/usr/bin/env python3
# agentman working hook (UserPromptSubmit + PreToolUse): a turn is in flight.
import sys, json
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = data.get("session_id")
if sid:
    base = Path.home() / ".local" / "share" / "agentman"
    d = base / "working"
    d.mkdir(parents=True, exist_ok=True)
    (d / sid).touch()
    try:
        (base / "done" / sid).unlink()
    except FileNotFoundError:
        pass
sys.exit(0)
'''

# SessionEnd hook: the session is gone, drop its markers.
SESSION_END_HELPER_SRC = '''\
#!/usr/bin/env python3
# agentman SessionEnd hook: clean up markers for the exiting session.
import sys, json
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = data.get("session_id")
if sid:
    base = Path.home() / ".local" / "share" / "agentman"
    for sub in ("working", "done"):
        try:
            (base / sub / sid).unlink()
        except FileNotFoundError:
            pass
sys.exit(0)
'''


def _cmd(helper: Path) -> str:
    python = shutil.which("python3") or sys.executable
    return f"{python} {helper}"


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
    """Write helpers and merge all hooks into user settings (idempotent)."""
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    for helper, src in (
        (HELPER, HELPER_SRC),
        (WORKING_HELPER, WORKING_HELPER_SRC),
        (SESSION_END_HELPER, SESSION_END_HELPER_SRC),
    ):
        helper.write_text(src)
        helper.chmod(0o755)

    settings: dict = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text() or "{}")
        except json.JSONDecodeError:
            return  # don't risk clobbering an unparseable settings file

    hooks_cfg = settings.setdefault("hooks", {})
    changed = _merge_hook(hooks_cfg, "Stop", HELPER, _cmd(HELPER))
    changed |= _merge_hook(hooks_cfg, "UserPromptSubmit", WORKING_HELPER, _cmd(WORKING_HELPER))
    changed |= _merge_hook(hooks_cfg, "PreToolUse", WORKING_HELPER, _cmd(WORKING_HELPER))
    changed |= _merge_hook(hooks_cfg, "SessionEnd", SESSION_END_HELPER, _cmd(SESSION_END_HELPER))

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
    marker = WORKING_DIR / session_id
    try:
        last = marker.stat().st_mtime
    except FileNotFoundError:
        return False
    matches = list(_CLAUDE_PROJECTS.glob(f"*/{session_id}.jsonl"))
    if matches:
        last = max(last, matches[0].stat().st_mtime)
    if time.time() - last > STALE_AFTER_S:
        clear_working(session_id)  # dead turn (interrupt/crash); self-heal
        return False
    return True


def clear_working(session_id: str) -> None:
    try:
        (WORKING_DIR / session_id).unlink()
    except FileNotFoundError:
        pass
