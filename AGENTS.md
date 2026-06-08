# AGENTS.md — agentman

A terminal session manager for Claude Code. Browse project folders, see each
project's resumable Claude sessions, and run them in a tmux layout where one
session is in scope (beside an always-visible browser sidebar) and the rest
keep running in the background.

## Run / develop / test

```bash
pipx install --editable ~/agentman      # isolated venv, on PATH, editable
agentman            # attach to running session, or start fresh
agentman --clean    # kill old session, then start fresh  (use this after code changes)
agentman --kill     # kill the session and exit
# tests (use a venv): python -m venv .venv && . .venv/bin/activate
#                     pip install -e '.[dev]' && pytest
```

Editable install → any *new* `agentman` process runs current code, but a
running browser keeps old code in memory. `--clean` is the dev reload.

## Architecture

The browser (Textual app, `agentman --inner`) runs in **tmux pane 0.0** — a
narrow always-visible sidebar. The in-scope Claude session runs in **pane
0.1** to its right. Other launched sessions are parked in their own background
**windows** named `am-<key>`, still running.

- **Switching sessions** (`tmux.py: show_session`): `break-pane -d` parks the
  current session into `am-<prev_key>` (keeps running), then `join-pane` pulls
  the target back (or `spawn` if new). One session in scope, others alive.
- **key scheme**: every session is keyed `s<id8>` (first 8 chars of its id).
  New sessions get a generated UUID via `claude --session-id`, so they're
  tracked exactly like resumed ones.
- **Completion**: a Stop hook in `~/.claude/settings.json` (installed by
  `hooks.py`) writes `~/.local/share/agentman/done/<id>` on each turn end.
  The 3s poll flags finished background sessions `✓ done` + rings the bell.

### Files

- `main.py` — click CLI (`--inner/--clean/--kill`); bootstrap-vs-attach.
- `app.py` — `AgentManApp` (Textual): bindings, actions, the 3s poll.
- `tmux.py` — `Tmux` dataclass: the hybrid layout. Command builders are pure
  staticmethods returning argv; effectful methods call an **injectable**
  `runner`/`capture` (so they're unit-testable without real tmux).
- `claude_sessions.py` — reads `~/.claude/history.jsonl`; dedup, titles, filter.
- `config.py` — `~/.config/agentman/config.toml` (project list).
- `hooks.py` — Stop-hook install + `is_done`/`clear_done`.
- `ui/` — `project_list.py`, `session_panel.py`, `dir_picker.py`, `styles.tcss`.

### State / paths

- Config: `~/.config/agentman/config.toml`
- Done markers: `~/.local/share/agentman/done/<session_id>`
- Hook helper: `~/.local/share/agentman/stop-hook.py`
- tmux session name: `agentman`

## Gotchas (learned the hard way — don't re-discover)

- **Never name a Textual Widget method `_render`** — it overrides an internal
  that must return a Visual; returning None gives a cryptic
  `'NoneType' has no attribute 'render_strips'` crash. (Cost hours.)
- `history.jsonl` has **one line per prompt**, not per session → dedupe by
  `sessionId`. Timestamps are **epoch milliseconds**, not ISO.
- Only sessions with a **transcript file** in `~/.claude/projects/*/<id>.jsonl`
  are resumable; others make `claude --resume` exit instantly. Filter them out.
- Sessions whose only prompts were commands (`exit`, `/model`, bare pastes)
  have no real title → labelled `(untitled · <id8>)`.
- `tmux` `automatic-rename`/`allow-rename` must be **off** or our `am-<key>`
  window names get clobbered and we can't find background sessions.
- A closed-claude pane is destroyed by tmux → the poll clears in-scope state
  when `workspace_exists()` is false, and `show_session` recreates the pane if
  missing.
- The poll updates badges **in place** (`session_panel.refresh_markers` /
  `project_list.update_activity`) — a full clear+rebuild every 3s flickers.
- Headless `ListView` does not auto-highlight; set `lv.index = 0`.
- `claude --settings <file>` may *replace* rather than merge — so we merge the
  Stop hook into `~/.claude/settings.json` directly instead.

## Conventions

- Everything gets a test. tmux command *shapes* are unit-tested via the fake
  runner; tmux *mechanics* (break/join keeping processes alive, detach, naming)
  are validated against real tmux when behaviour can't be asserted in a unit.
- `tests/conftest.py` redirects all `hooks` paths to a temp dir so the suite
  never touches the real `~/.claude/settings.json` or share dir.

## Open items / ideas (not yet done)

- `/` to fuzzy-filter the project list (most-wanted next).
- Make the Stop-hook install **opt-in** rather than auto on first launch
  (it edits global `~/.claude/settings.json`).
- "Kill all background sessions" command.
