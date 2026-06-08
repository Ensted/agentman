from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _resumable_ids() -> set[str]:
    """Session IDs that have a transcript file, i.e. can actually be resumed.

    history.jsonl lists sessions that may have no transcript (claude --resume
    fails on those and the pane closes instantly), so we filter to real ones.
    """
    if not PROJECTS_DIR.exists():
        return set()
    return {f.stem for f in PROJECTS_DIR.glob("*/*.jsonl")}


@dataclass
class ClaudeSession:
    session_id: str
    project: str
    display: str
    timestamp: datetime
    tmux_name: str | None = field(default=None)  # set if a live tmux session exists


# Prompts that are commands/noise rather than a meaningful session title.
_NOISE_PROMPTS = {"exit", "quit", ":q", ":q!", "clear", "q", "stop"}
_PASTE_PLACEHOLDER = re.compile(r"^\[Pasted text[^\]]*\]$")


def clean_title(display: str) -> str:
    """Strip stray UI glyphs and collapse whitespace for a tidy one-line title."""
    text = display.replace("▎", " ")        # ▎ banner marker
    text = " ".join(text.split())                 # collapse newlines/runs
    return text.strip()


def _is_noise(display: str) -> bool:
    """True if a prompt is a command/noise, not a meaningful session title."""
    text = clean_title(display)
    if not text:
        return True
    if text.startswith("/"):                       # slash commands
        return True
    if _PASTE_PLACEHOLDER.match(text):             # bare "[Pasted text ...]"
        return True
    return text.lower() in _NOISE_PROMPTS


def _parse_ts(ts) -> datetime:
    # history.jsonl uses Unix epoch milliseconds (int).
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def load_sessions(project_path: str) -> list[ClaudeSession]:
    """Return Claude sessions for the given project path, newest first."""
    if not HISTORY_FILE.exists():
        return []

    canonical = str(Path(project_path).expanduser().resolve())

    # history.jsonl has one line PER PROMPT. Collapse to one entry per session,
    # keeping the first prompt as the display text and the latest timestamp.
    by_id: dict[str, ClaudeSession] = {}

    with HISTORY_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("project") != canonical:
                continue

            session_id = entry.get("sessionId", "")
            if not session_id:
                continue

            ts = _parse_ts(entry.get("timestamp", ""))
            display = entry.get("display", "(no description)")

            existing = by_id.get(session_id)
            if existing is None:
                by_id[session_id] = ClaudeSession(
                    session_id=session_id,
                    project=canonical,
                    display=display,
                    timestamp=ts,
                )
            else:
                if ts > existing.timestamp:
                    existing.timestamp = ts
                # Upgrade the title: prefer the first meaningful prompt over a
                # noise opener (slash commands, "exit", "clear", etc.).
                if _is_noise(existing.display) and not _is_noise(display):
                    existing.display = display

    # Drop sessions with no transcript file — they can't be resumed and would
    # just close the pane on open.
    resumable = _resumable_ids()
    by_id = {sid: s for sid, s in by_id.items() if sid in resumable}

    # Sessions whose only prompts were commands (exit, slash commands, bare
    # pastes) have no meaningful title — label them clearly. Otherwise tidy up.
    for s in by_id.values():
        if _is_noise(s.display):
            s.display = f"(untitled · {s.session_id[:8]})"
        else:
            s.display = clean_title(s.display)

    sessions = list(by_id.values())
    sessions.sort(key=lambda s: s.timestamp, reverse=True)
    return sessions


def relative_time(ts: datetime) -> str:
    now = datetime.now(tz=timezone.utc)
    diff = now - ts.astimezone(timezone.utc)
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    return ts.strftime("%b %d")
