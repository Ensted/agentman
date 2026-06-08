from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.widgets import Button, Label, ListView, ListItem

from agentman.config import Config, Project


class ProjectList(Vertical):
    """Left panel: list of configured projects."""

    class Highlighted(Message):
        """Cursor moved onto a project — load its sessions."""
        def __init__(self, project: Project) -> None:
            super().__init__()
            self.project = project

    class Activated(Message):
        """Project chosen (Enter/click) — move focus to its sessions."""
        def __init__(self, project: Project) -> None:
            super().__init__()
            self.project = project

    class AddRequested(Message):
        pass

    def __init__(self, config: Config) -> None:
        super().__init__(id="left")
        self._config = config

    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-title-bar"):
            yield Label("Projects")
            add = Button("+", id="btn-add-project", classes="add-btn")
            add.can_focus = False
            yield add
        yield ListView(id="project-listview")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv = self.query_one("#project-listview", ListView)
        lv.clear()
        for project in self._config.projects:
            item = ListItem(Label(project.name))
            item.data = project  # type: ignore[attr-defined]
            lv.append(item)
        if self._config.projects:
            lv.index = 0  # highlight the first project

    def reload(self, config: Config) -> None:
        self._config = config
        self._refresh_list()

    @property
    def highlighted_project(self) -> Project | None:
        lv = self.query_one("#project-listview", ListView)
        item = lv.highlighted_child
        return getattr(item, "data", None) if item else None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        project = getattr(event.item, "data", None)
        if project:
            self.post_message(self.Highlighted(project))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        project = getattr(event.item, "data", None)
        if project:
            self.post_message(self.Activated(project))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add-project":
            self.post_message(self.AddRequested())
