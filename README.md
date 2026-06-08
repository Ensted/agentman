# agentman

A terminal session manager for Claude Code. Projects on the left, their Claude
sessions on the right. Pick a folder, see its sessions, open one — each runs in
its own tmux session so it survives detaching and closing the terminal.

## Install

```bash
pip install --break-system-packages -e ~/ws/agentman
```

## Run

```bash
agentman
```

## Keys

| Key       | Action                                            |
|-----------|---------------------------------------------------|
| `↑` / `↓` | Navigate; highlighting a project loads its sessions |
| `Enter`   | Open the highlighted session (or jump to sessions) |
| `a`       | Add a project (directory picker)                  |
| `d`       | Remove the highlighted project from the view      |
| `n`       | New Claude session in the current project         |
| `r`       | Refresh                                           |
| `Ctrl+Q`  | Close agentman (detach) — sessions keep running   |

Removing a project (`d`) only drops it from agentman's list — it never
touches the folder or Claude's session history.

`Ctrl+Q` detaches the whole tmux session: agentman closes from view and you
return to your shell, but the browser and every running Claude session stay
alive in the background. Run `agentman` again to re-attach right where you
left off.

Inside a session, detach from tmux with `Ctrl+b d` to return to agentman.

## How it works

agentman launches inside a tmux layout: the browser is always-visible on the
left, the in-scope session shows on the right, and other sessions keep running
in hidden background windows.

```
┌─ browser ─┬──── in-scope session ────┐
│ projects  │  claude — B              │
│ sessions  │                          │   A, C still running in
└───────────┴──────────────────────────┘   background windows (not killed)
```

- **Projects** are folders, stored in `~/.config/agentman/config.toml`.
- **Sessions** are Claude Code's own, read from `~/.claude/history.jsonl`,
  deduplicated to one entry per session. Only sessions with a saved transcript
  (resumable) are shown.
- Opening a session runs `claude --resume <id>` in the right pane. Switching to
  another session **parks the current one in its own background window** (via
  `break-pane`) so it keeps running, then brings the target in (`join-pane` if
  it was already running, else a fresh spawn).
- Markers: `● open` = in scope; `· running` = alive in the background.
- `n` starts a fresh `claude` in the current project.
- agentman never touches Claude's session data — it only launches and lists.

Drag the pane divider (mouse enabled) to resize. If launched while already
inside another tmux session, it falls back to suspending and running claude
full-screen (no layout).

## Develop / test

```bash
pip install --break-system-packages -e ~/ws/agentman[dev]
cd ~/ws/agentman && python -m pytest
```
