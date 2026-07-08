# agentman

A terminal session manager for Claude Code. A sidebar lists your project
folders with the Claude sessions for the selected one stacked below. Open a
session and it runs beside the browser; switch to another and the first keeps
running in the background. Everything lives in one tmux session, so you can
detach and come back to it.

## Install

Use [pipx](https://pipx.pypa.io) — it installs agentman into its own isolated
venv and puts the `agentman` command on your PATH (no `--break-system-packages`):

```bash
pipx install --editable ~/agentman
```

`--editable` means code changes are picked up by the next `agentman --clean`.
(Plain `pip install --editable ~/agentman` inside a venv works too.)

## Run

```bash
agentman           # attach to the running session, or start a fresh one
agentman --clean   # kill the old session first, then start fresh
agentman --kill    # kill the running session and exit (don't start)
```

`--clean` is the easy way to pick up code changes during development; `--kill`
tears everything down (browser + all claude sessions in the session).

## Keys

| Key       | Action                                            |
|-----------|---------------------------------------------------|
| `↑` / `↓` | Navigate; highlighting a project loads its sessions |
| `Enter`   | Open the highlighted session (or jump to sessions) |
| `a`       | Add a project (directory picker)                  |
| `d`       | Remove: project from the view, or delete the highlighted session (asks first) |
| `n`       | New Claude session in the current project         |
| `k`       | Kill the highlighted session (in-scope or background) |
| `z`       | Fullscreen the open session (hides the sidebar)   |
| `o`       | Open the current project folder in VS Code        |
| `r`       | Refresh                                           |
| `Ctrl+Q`  | Close agentman (detach) — sessions keep running   |

`d` is context-sensitive and always asks for confirmation. On the project
list it only drops the project from agentman's view — it never touches the
folder or Claude's session history. On the session list it permanently
deletes that one session: kills it if running and removes its transcript.

`Ctrl+Q` detaches the whole tmux session: agentman closes from view and you
return to your shell, but the browser and every running Claude session stay
alive in the background. Run `agentman` again to re-attach right where you
left off.

`z` zooms the open session to the full terminal (the sidebar disappears).
Press `Ctrl+b z` inside the session to bring the sidebar back — it's plain
tmux pane zoom, so it also works the other way around.

Inside a session, detach from tmux with `Ctrl+b d` to return to agentman.

## How it works

agentman launches inside a tmux layout: the browser is always-visible on the
left, the in-scope session shows on the right, and other sessions keep running
in hidden background windows.

```
┌─ browser ──┬──── in-scope session ────┐
│ projects   │  claude — B              │
│ ·········· │                          │   A, C still running in
│ sessions   │                          │   background windows (not killed)
└────────────┴──────────────────────────┘
```

The browser sidebar stacks the project list on top and the sessions for the
selected project below it.

- **Projects** are folders, stored in `~/.config/agentman/config.toml`.
  Each row shows activity for sessions agentman launched: `●N` running in the
  background, `✓` when one has finished. A project whose folder no longer
  exists is shown as `(missing)` and won't launch.
- **Sessions** are Claude Code's own, read from `~/.claude/history.jsonl`,
  deduplicated to one entry per session. Only sessions with a saved transcript
  (resumable) are shown.
- Opening a session runs `claude --resume <id>` in the right pane. A new
  session (`n`) runs `claude --session-id <uuid>` with a freshly generated id,
  so agentman tracks it the same way and marks it `● open` once its first
  prompt lands.
- Switching to another session **parks the current one in its own background
  window** (via `break-pane`) so it keeps running, then brings the target in
  (`join-pane` if it was already running, else a fresh spawn).
- Markers: `● open` = in scope; `· running` = alive in the background;
  `✓ done` = a background session finished its work (see below).
- agentman never touches Claude's session data — it only launches and lists.

### Completion notifications

agentman registers a Claude Code **`Stop` hook** in `~/.claude/settings.json`
on first launch. When any claude session finishes a turn, the hook writes a
marker file under `~/.local/share/agentman/done/`. agentman polls these and,
when a *background* (not-in-scope) session finishes, marks it `✓ done` in the
list and rings the terminal bell. The marker clears when you bring that
session back into scope.

The hook is a one-line, idempotent addition that only writes a marker file —
it touches nothing else. To remove it, delete the agentman `Stop` entry from
`~/.claude/settings.json`.

Drag the pane divider (mouse enabled) to resize. If launched while already
inside another tmux session, it falls back to suspending and running claude
full-screen (no layout).

## Develop / test

Tests need `pytest` + `pytest-asyncio` (the `dev` extra). Use a venv:

```bash
cd ~/agentman
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```
