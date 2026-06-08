from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.widgets import Button, Label, ListView, ListItem

from agentman.claude_sessions import ClaudeSession, load_sessions, relative_time
from agentman.config import Project


class SessionPanel(Vertical):
    """Right panel: Claude sessions for the selected project."""

    class OpenRequested(Message):
        def __init__(self, session: ClaudeSession) -> None:
            super().__init__()
            self.session = session

    class NewRequested(Message):
        def __init__(self, project: Project) -> None:
            super().__init__()
            self.project = project

    def __init__(self) -> None:
        super().__init__(id="right")
        self._project: Project | None = None
        self._sessions: list[ClaudeSession] = []
        self._open_session_id: str | None = None
        self._running_id8s: set[str] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-title-bar"):
            yield Label("Sessions", id="session-title")
            add = Button("+", id="btn-new-session", classes="add-btn")
            add.can_focus = False
            yield add
        yield ListView(id="session-listview")

    def load_project(self, project: Project, open_session_id: str | None = None,
                     running_id8s: set[str] | None = None) -> None:
        self._project = project
        self._open_session_id = open_session_id
        self._running_id8s = running_id8s or set()
        self.query_one("#session-title", Label).update(f"Sessions: {project.name}")
        self._sessions = load_sessions(project.resolved_path)
        self._rebuild()

    def clear(self) -> None:
        """Reset the panel when no project is selected."""
        self._project = None
        self._sessions = []
        self.query_one("#session-title", Label).update("Sessions")
        self.query_one("#session-listview", ListView).clear()

    def _rebuild(self) -> None:
        lv = self.query_one("#session-listview", ListView)
        lv.clear()

        if not self._sessions:
            lv.append(ListItem(Label("No sessions yet. Press + to start one.",
                                     classes="empty-hint")))
            return

        for session in self._sessions:
            age = relative_time(session.timestamp)
            if session.session_id == self._open_session_id:
                badge = "  ● open"
            elif session.session_id[:8] in self._running_id8s:
                badge = "  · running"
            else:
                badge = ""
            label = f"{session.display[:50]}  ({age}){badge}"
            item = ListItem(Label(label))
            item.data = session  # type: ignore[attr-defined]
            lv.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        session = getattr(event.item, "data", None)
        if session:
            self.post_message(self.OpenRequested(session))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-session" and self._project:
            self.post_message(self.NewRequested(self._project))
