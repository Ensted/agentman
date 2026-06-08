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
        self._done_id8s: set[str] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-title-bar"):
            yield Label("Sessions", id="session-title")
            add = Button("+", id="btn-new-session", classes="add-btn")
            add.can_focus = False
            yield add
        yield ListView(id="session-listview")

    def load_project(self, project: Project, open_session_id: str | None = None,
                     running_id8s: set[str] | None = None,
                     done_id8s: set[str] | None = None) -> None:
        self._project = project
        self._open_session_id = open_session_id
        self._running_id8s = running_id8s or set()
        self._done_id8s = done_id8s or set()
        self.query_one("#session-title", Label).update(f"Sessions: {project.name}")
        self._sessions = load_sessions(project.resolved_path)
        self._rebuild()

    def refresh_markers(self, open_session_id: str | None,
                        running_id8s: set[str], done_id8s: set[str]) -> None:
        """Poll-time update: refresh badges in place (no flicker) and pick up
        added/removed sessions only when the set actually changed."""
        self._open_session_id = open_session_id
        self._running_id8s = running_id8s
        self._done_id8s = done_id8s
        if self._project is None:
            return
        new = load_sessions(self._project.resolved_path)
        if [s.session_id for s in new] == [s.session_id for s in self._sessions]:
            self._sessions = new
            self._apply_markers()
        else:
            self._sessions = new
            self._rebuild()

    @property
    def highlighted_session(self) -> ClaudeSession | None:
        lv = self.query_one("#session-listview", ListView)
        item = lv.highlighted_child
        return getattr(item, "data", None) if item else None

    def clear(self) -> None:
        """Reset the panel when no project is selected."""
        self._project = None
        self._sessions = []
        self.query_one("#session-title", Label).update("Sessions")
        self.query_one("#session-listview", ListView).clear()

    def _session_label(self, session: ClaudeSession) -> str:
        age = relative_time(session.timestamp)
        if session.session_id == self._open_session_id:
            badge = "  ● open"
        elif session.session_id[:8] in self._done_id8s:
            badge = "  ✓ done"
        elif session.session_id[:8] in self._running_id8s:
            badge = "  · running"
        else:
            badge = ""
        return f"{session.display[:50]}  ({age}){badge}"

    def _rebuild(self) -> None:
        lv = self.query_one("#session-listview", ListView)
        lv.clear()

        if not self._sessions:
            lv.append(ListItem(Label("No sessions yet. Press + to start one.",
                                     classes="empty-hint")))
            return

        for session in self._sessions:
            item = ListItem(Label(self._session_label(session)))
            item.data = session  # type: ignore[attr-defined]
            lv.append(item)

    def _apply_markers(self) -> None:
        """Update existing rows' labels in place — no clear/rebuild, no flicker."""
        lv = self.query_one("#session-listview", ListView)
        children = list(lv.children)
        if len(children) != len(self._sessions):
            self._rebuild()
            return
        for item, session in zip(children, self._sessions):
            try:
                item.query_one(Label).update(self._session_label(session))
            except Exception:
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        session = getattr(event.item, "data", None)
        if session:
            self.post_message(self.OpenRequested(session))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-session" and self._project:
            self.post_message(self.NewRequested(self._project))
