from __future__ import annotations
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _transcripts() -> dict[str, Path]:
    """Map session id → transcript file. Only these sessions can be resumed.

    history.jsonl lists sessions that may have no transcript (claude --resume
    fails on those and the pane closes instantly), so we filter to real ones.
    """
    if not PROJECTS_DIR.exists():
        return {}
    return {f.stem: f for f in PROJECTS_DIR.glob("*/*.jsonl")}


_TITLE_MARKER = b'"ai-title"'
_TITLE_BLOCK = 64 * 1024
_title_cache: dict[str, tuple[float, str | None]] = {}  # path -> (mtime, title)


def ai_title(transcript: Path) -> str | None:
    """Claude Code's own name for the session (its latest ai-title record)."""
    try:
        mtime = transcript.stat().st_mtime
    except OSError:
        return None
    cached = _title_cache.get(str(transcript))
    if cached and cached[0] == mtime:
        return cached[1]
    title = _find_last_title(transcript)
    _title_cache[str(transcript)] = (mtime, title)
    return title


def _parse_title_line(line: bytes) -> str | None:
    try:
        entry = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(entry, dict) or entry.get("type") != "ai-title":
        return None
    title = entry.get("aiTitle")
    return title if isinstance(title, str) and title.strip() else None


def _find_last_title(transcript: Path) -> str | None:
    # ai-title records are re-appended throughout the session, so the newest
    # one sits near the end — scan backwards in blocks, not the whole file.
    # The marker bytes can also occur inside ordinary message content, so each
    # candidate line is parsed and verified before we accept it.
    try:
        with transcript.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            buf = b""
            while True:
                start = max(0, end - _TITLE_BLOCK)
                f.seek(start)
                buf = f.read(end - start) + buf
                pos = len(buf)
                while (idx := buf.rfind(_TITLE_MARKER, 0, pos)) != -1:
                    nl = buf.rfind(b"\n", 0, idx)
                    if nl == -1 and start > 0:
                        break  # line begins before the buffer; read more first
                    line_end = buf.find(b"\n", idx)
                    if line_end == -1:
                        line_end = len(buf)
                    title = _parse_title_line(buf[nl + 1:line_end])
                    if title:
                        return title
                    pos = nl + 1  # not a title record; keep scanning backwards
                if start == 0:
                    return None
                end = start
    except OSError:
        return None


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
    transcripts = _transcripts()
    by_id = {sid: s for sid, s in by_id.items() if sid in transcripts}

    # Prefer the name Claude Code itself gave the session. Fall back to the
    # first meaningful prompt; sessions with neither (only slash commands,
    # bare pastes, etc.) get a clear placeholder.
    for s in by_id.values():
        title = ai_title(transcripts[s.session_id])
        if title:
            s.display = clean_title(title)
        elif _is_noise(s.display):
            s.display = f"(untitled · {s.session_id[:8]})"
        else:
            s.display = clean_title(s.display)

    sessions = list(by_id.values())
    sessions.sort(key=lambda s: s.timestamp, reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    """Permanently delete a session's transcript and per-session data.

    Sessions without a transcript are dropped from listings, so this also
    removes it from the UI. Returns True if anything was deleted.
    """
    removed = False
    for transcript in PROJECTS_DIR.glob(f"*/{session_id}.jsonl"):
        try:
            transcript.unlink()
            removed = True
        except OSError:
            continue
        extra = transcript.with_suffix("")  # <sid>/ dir: subagents, tool results
        if extra.is_dir():
            shutil.rmtree(extra, ignore_errors=True)
    return removed


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
