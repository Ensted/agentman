from __future__ import annotations
import os
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, ListView

from agentman import hooks
from agentman.config import Config, Project
from agentman.tmux import Tmux
from agentman.ui.project_list import ProjectList
from agentman.ui.session_panel import SessionPanel
from agentman.ui.dir_picker import DirPickerModal


def _resume_key(session_id: str) -> str:
    return f"s{session_id[:8]}"


class AgentManApp(App):
    CSS_PATH = "ui/styles.tcss"
    TITLE = "agentman"
    SUB_TITLE = "Claude sessions across projects"

    BINDINGS = [
        Binding("ctrl+q", "close_app", "Quit"),
        Binding("q", "close_app", "Quit", show=False),
        Binding("a", "add_project", "Add project"),
        Binding("d", "remove_project", "Remove project"),
        Binding("n", "new_session", "New session"),
        Binding("k", "kill_session", "Kill session"),
        Binding("o", "open_in_vscode", "Open in VS Code"),
        Binding("r", "refresh", "Refresh"),
        Binding("tab", "focus_next", "Switch panel", show=False),
    ]

    def __init__(self, has_workspace: bool = False) -> None:
        super().__init__()
        self._config = Config.load()
        self._tmux = Tmux()
        self._has_workspace = has_workspace
        self._open_session_id: str | None = None
        self._current_key: str | None = None
        self._new_counter = 0
        self._current_project: Project | None = None
        self._sessions_by_key: dict[str, str] = {}   # key -> resume session id
        self._launched_projects: dict[str, str] = {}  # key -> resolved project path
        self._notified_done: set[str] = set()          # id8s already flagged done

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield ProjectList(self._config)
            yield SessionPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#project-listview", ListView).focus()
        if self._has_workspace:
            try:
                hooks.install()
            except Exception:
                pass
            self.set_interval(3.0, self._poll_completions)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _running_id8s(self) -> set[str]:
        """8-char prefixes of resume sessions currently parked in background."""
        if not self._has_workspace:
            return set()
        return {k[1:] for k in self._tmux.running_keys() if k.startswith("s")}

    def _done_id8s(self) -> set[str]:
        """Background sessions that have finished a turn (completed work)."""
        if not self._has_workspace:
            return set()
        running = self._tmux.running_keys()
        out: set[str] = set()
        for key in running:
            if key == self._current_key:
                continue
            sid = self._sessions_by_key.get(key)
            if sid and hooks.is_done(sid):
                out.add(sid[:8])
        return out

    def _project_activity(self) -> dict[str, dict]:
        """Per-project counts of running launched sessions (+ any finished)."""
        act: dict[str, dict] = {}

        def bump(path: str, done: bool) -> None:
            a = act.setdefault(path, {"running": 0, "done": False})
            a["running"] += 1
            if done:
                a["done"] = True

        if not self._has_workspace:
            return act
        running = self._tmux.running_keys()
        for key in running:
            path = self._launched_projects.get(key)
            if not path:
                continue
            sid = self._sessions_by_key.get(key)
            bump(path, bool(sid and hooks.is_done(sid)))
        # The in-scope session is active too, but not a background window.
        if self._current_key and self._current_key in self._launched_projects:
            bump(self._launched_projects[self._current_key], False)
        return act

    def _reload_sessions(self, project: Project) -> None:
        self.query_one(SessionPanel).load_project(
            project, self._open_session_id, self._running_id8s(), self._done_id8s())
        self.query_one(ProjectList).update_activity(self._project_activity())

    def _poll_completions(self) -> None:
        done = self._done_id8s()
        newly = done - self._notified_done
        if newly:
            self.bell()
            self.sub_title = f"✓ {len(done)} background session(s) finished"
        elif not done and self._notified_done:
            self.sub_title = "Claude sessions across projects"
        self._notified_done = done
        if self._current_project:
            self._reload_sessions(self._current_project)
        else:
            self.query_one(ProjectList).update_activity(self._project_activity())

    # ── Project list events ──────────────────────────────────────────────────

    def on_project_list_highlighted(self, event: ProjectList.Highlighted) -> None:
        self._current_project = event.project
        self._reload_sessions(event.project)

    def on_project_list_activated(self, event: ProjectList.Activated) -> None:
        self._current_project = event.project
        self._reload_sessions(event.project)
        self.query_one("#session-listview", ListView).focus()

    def on_project_list_add_requested(self, event: ProjectList.AddRequested) -> None:
        self.action_add_project()

    def _on_dir_picked(self, path: Path | None) -> None:
        if path is None:
            return
        name = path.name or str(path)
        self._config.add_project(name=name, path=str(path))
        self.query_one(ProjectList).reload(self._config)

    # ── Session panel events ─────────────────────────────────────────────────

    def on_session_panel_open_requested(self, event: SessionPanel.OpenRequested) -> None:
        self._open(event.session.project, event.session.session_id)

    def on_session_panel_new_requested(self, event: SessionPanel.NewRequested) -> None:
        self._open(event.project.resolved_path, None)

    # ── Open / switch sessions ─────────────────────────────────────────────────

    def _open(self, project_path: str, session_id: str | None) -> None:
        if not Path(project_path).exists():
            self.bell()
            self.notify(f"Folder no longer exists: {project_path}", severity="error")
            return

        if not self._has_workspace:
            self._open_fallback(project_path, session_id)
            return

        if session_id is not None:
            key = _resume_key(session_id)
            self._sessions_by_key[key] = session_id
        else:
            self._new_counter += 1
            key = f"n{self._new_counter}"
        self._launched_projects[key] = project_path

        # Reset completion state for the session leaving scope (so a later
        # finish registers afresh) and the one entering scope.
        prev_id = self._sessions_by_key.get(self._current_key) if self._current_key else None
        if prev_id:
            hooks.clear_done(prev_id)
        if session_id:
            hooks.clear_done(session_id)
            self._notified_done.discard(session_id[:8])

        self._tmux.show_session(project_path, session_id, key, self._current_key)
        self._current_key = key
        self._open_session_id = session_id
        if self._current_project:
            self._reload_sessions(self._current_project)

    def _open_fallback(self, project_path: str, session_id: str | None) -> None:
        argv = ["claude"]
        if session_id:
            argv += ["--resume", session_id]
        env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        with self.suspend():
            subprocess.run(argv, cwd=project_path, env=env)

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_close_app(self) -> None:
        # Detach the whole tmux session: agentman closes from view but the
        # browser and every claude session keep running in the background.
        # Re-run `agentman` to come back. Without our layout, just exit.
        if self._has_workspace:
            self._tmux.detach()
        else:
            self.exit()

    def action_add_project(self) -> None:
        self.push_screen(DirPickerModal(), self._on_dir_picked)

    def action_remove_project(self) -> None:
        pl = self.query_one(ProjectList)
        project = pl.highlighted_project or self._current_project
        if project is None:
            return
        self._config.remove_project(project)
        pl.reload(self._config)
        sp = self.query_one(SessionPanel)
        remaining = pl.highlighted_project
        self._current_project = remaining
        if remaining is not None:
            self._reload_sessions(remaining)
        else:
            sp.clear()

    def action_new_session(self) -> None:
        if self._current_project:
            self._open(self._current_project.resolved_path, None)

    def action_kill_session(self) -> None:
        if not self._has_workspace:
            return
        session = self.query_one(SessionPanel).highlighted_session
        if session is None:
            return
        key = _resume_key(session.session_id)
        is_current = key == self._current_key
        self._tmux.kill(key, is_current)
        hooks.clear_done(session.session_id)
        self._sessions_by_key.pop(key, None)
        self._launched_projects.pop(key, None)
        self._notified_done.discard(session.session_id[:8])
        if is_current:
            self._current_key = None
            self._open_session_id = None
        if self._current_project:
            self._reload_sessions(self._current_project)

    def action_open_in_vscode(self) -> None:
        project = self._current_project
        if project is None:
            return
        path = project.resolved_path
        if not Path(path).exists():
            self.bell()
            self.notify(f"Folder no longer exists: {path}", severity="error")
            return
        try:
            subprocess.Popen(
                ["code", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.bell()
            self.notify("VS Code CLI ('code') not found on PATH", severity="error")
            return
        self.notify(f"Opening {project.name} in VS Code")

    def action_refresh(self) -> None:
        if self._current_project:
            self._reload_sessions(self._current_project)
