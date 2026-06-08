from __future__ import annotations
import os
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, ListView

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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ProjectList(self._config)
            yield SessionPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#project-listview", ListView).focus()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _running_id8s(self) -> set[str]:
        """8-char prefixes of resume sessions currently parked in background."""
        if not self._has_workspace:
            return set()
        return {k[1:] for k in self._tmux.running_keys() if k.startswith("s")}

    def _reload_sessions(self, project: Project) -> None:
        self.query_one(SessionPanel).load_project(
            project, self._open_session_id, self._running_id8s())

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
        if not self._has_workspace:
            self._open_fallback(project_path, session_id)
            return

        if session_id is not None:
            key = _resume_key(session_id)
        else:
            self._new_counter += 1
            key = f"n{self._new_counter}"

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

    def action_refresh(self) -> None:
        if self._current_project:
            self._reload_sessions(self._current_project)
