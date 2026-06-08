from __future__ import annotations
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable


SESSION = "agentman"
BROWSER_WIDTH = 44          # columns for the always-visible browser sidebar


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv)


def _run_capture(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


@dataclass
class Tmux:
    """tmux orchestration for the hybrid layout.

    Window 0 holds the browser (left pane, always visible). The in-scope claude
    session occupies the right pane. Switching pushes the current session into
    its own background window (still running) and pulls the target back in.
    """

    runner: Callable[[list[str]], object] = field(default=_run)
    capture: Callable[[list[str]], object] = field(default=_run_capture)

    # ── environment ──────────────────────────────────────────────────────────

    @staticmethod
    def inside() -> bool:
        return bool(os.environ.get("TMUX"))

    # ── command builders (pure) ────────────────────────────────────────────────

    @staticmethod
    def bootstrap_cmds(self_exe: str) -> list[list[str]]:
        """Build the session: a single browser pane, plus the options we rely on."""
        return [
            ["tmux", "new-session", "-d", "-s", SESSION, self_exe, "--inner"],
            ["tmux", "set-option", "-t", SESSION, "mouse", "on"],
            # Keep our window names (am-<key>) stable so we can find bg sessions.
            ["tmux", "set-option", "-t", SESSION, "automatic-rename", "off"],
            ["tmux", "set-option", "-t", SESSION, "allow-rename", "off"],
            ["tmux", "attach-session", "-t", SESSION],
        ]

    @staticmethod
    def _claude_command(session_id: str | None, resume: bool = True) -> str:
        if session_id and resume:
            claude = f"claude --resume {shlex.quote(session_id)}"
        elif session_id:                       # new session with a known id
            claude = f"claude --session-id {shlex.quote(session_id)}"
        else:
            claude = "claude"
        # Suppress Claude Code's startup announcement banner in our panes.
        claude = f"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 {claude}"
        shell = os.environ.get("SHELL", "bash")
        return f"{shell} -lc {shlex.quote(claude)}"

    @staticmethod
    def bg_window(key: str) -> str:
        return f"am-{key}"

    @staticmethod
    def list_panes_cmd() -> list[str]:
        return ["tmux", "list-panes", "-t", f"{SESSION}:0", "-F", "#{pane_index}"]

    @staticmethod
    def list_windows_cmd() -> list[str]:
        return ["tmux", "list-windows", "-t", SESSION, "-F", "#{window_name}"]

    @staticmethod
    def stash_cmd(key: str) -> list[str]:
        """Push the in-scope session (right pane) into its own bg window, running."""
        return ["tmux", "break-pane", "-d", "-n", Tmux.bg_window(key),
                "-s", f"{SESSION}:0.1"]

    @staticmethod
    def join_cmd(key: str) -> list[str]:
        """Pull a backgrounded session back beside the browser."""
        return ["tmux", "join-pane", "-h",
                "-s", f"{Tmux.bg_window(key)}.0", "-t", f"{SESSION}:0.0"]

    @staticmethod
    def spawn_cmd(project_path: str, session_id: str | None,
                  resume: bool = True) -> list[str]:
        """Start a fresh claude in a new right pane next to the browser."""
        return ["tmux", "split-window", "-h", "-t", f"{SESSION}:0.0",
                "-c", project_path, Tmux._claude_command(session_id, resume)]

    @staticmethod
    def select_workspace_cmd() -> list[str]:
        return ["tmux", "select-pane", "-t", f"{SESSION}:0.1"]

    @staticmethod
    def has_session_cmd() -> list[str]:
        return ["tmux", "has-session", "-t", SESSION]

    @staticmethod
    def detach_cmd() -> list[str]:
        return ["tmux", "detach-client", "-s", SESSION]

    @staticmethod
    def kill_session_cmd() -> list[str]:
        return ["tmux", "kill-session", "-t", SESSION]

    @staticmethod
    def kill_workspace_cmd() -> list[str]:
        return ["tmux", "kill-pane", "-t", f"{SESSION}:0.1"]

    @staticmethod
    def kill_bg_cmd(key: str) -> list[str]:
        return ["tmux", "kill-window", "-t", Tmux.bg_window(key)]

    @staticmethod
    def browser_width_cmd() -> list[str]:
        return ["tmux", "resize-pane", "-t", f"{SESSION}:0.0", "-x", str(BROWSER_WIDTH)]

    # ── effectful operations ───────────────────────────────────────────────────

    def bootstrap_and_attach(self, self_exe: str) -> None:
        for cmd in self.bootstrap_cmds(self_exe):
            self.runner(cmd)

    def session_running(self) -> bool:
        result = self.capture(self.has_session_cmd())
        return getattr(result, "returncode", 1) == 0

    def kill_session(self) -> bool:
        """Kill the whole agentman session (and everything in it). Returns
        True if there was a session to kill."""
        if not self.session_running():
            return False
        self.runner(self.kill_session_cmd())
        return True

    def detach(self) -> None:
        """Detach the whole session — browser and all claude sessions keep running."""
        self.runner(self.detach_cmd())

    def kill(self, key: str, is_current: bool) -> None:
        """Kill a session: the in-scope pane, or a backgrounded session's window."""
        if is_current:
            self.runner(self.kill_workspace_cmd())
        else:
            self.runner(self.kill_bg_cmd(key))

    def _window_names(self) -> list[str]:
        result = self.capture(self.list_windows_cmd())
        if getattr(result, "returncode", 1) != 0:
            return []
        return result.stdout.split()

    def workspace_exists(self) -> bool:
        """True if the right pane (in-scope session) is present in window 0."""
        result = self.capture(self.list_panes_cmd())
        if getattr(result, "returncode", 1) != 0:
            return False
        return "1" in result.stdout.split()

    def window_exists(self, name: str) -> bool:
        return name in self._window_names()

    def running_keys(self) -> set[str]:
        """Keys of sessions currently parked in background windows."""
        return {w[len("am-"):] for w in self._window_names() if w.startswith("am-")}

    def show_session(self, project_path: str, session_id: str | None,
                     new_key: str, prev_key: str | None,
                     resume: bool = True) -> None:
        # Already in scope — just focus it.
        if new_key == prev_key and self.workspace_exists():
            self.runner(self.select_workspace_cmd())
            return
        # Park the current session in its own window (keeps running).
        if prev_key is not None and self.workspace_exists():
            self.runner(self.stash_cmd(prev_key))
        # Bring the target in: reuse its bg window if it exists, else spawn fresh.
        if self.window_exists(self.bg_window(new_key)):
            self.runner(self.join_cmd(new_key))
        else:
            self.runner(self.spawn_cmd(project_path, session_id, resume))
        self.runner(self.select_workspace_cmd())
        self.runner(self.browser_width_cmd())


def relaunch_in_tmux() -> None:
    """Attach to a running agentman session, or build the layout from scratch."""
    t = Tmux()
    if t.session_running():
        subprocess.run(["tmux", "attach-session", "-t", SESSION])
    else:
        t.bootstrap_and_attach(sys.argv[0])
