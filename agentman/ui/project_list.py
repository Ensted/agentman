from __future__ import annotations
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.widgets import Button, Label, ListView, ListItem

from agentman.config import Config, Project


class ProjectList(Vertical):
    """Left panel: list of configured projects with activity indicators."""

    class Highlighted(Message):
        def __init__(self, project: Project) -> None:
            super().__init__()
            self.project = project

    class Activated(Message):
        def __init__(self, project: Project) -> None:
            super().__init__()
            self.project = project

    class AddRequested(Message):
        pass

    def __init__(self, config: Config) -> None:
        super().__init__(id="left")
        self._config = config
        self._activity: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-title-bar"):
            yield Label("Projects")
            add = Button("+", id="btn-add-project", classes="add-btn")
            add.can_focus = False
            yield add
        yield ListView(id="project-listview")

    def on_mount(self) -> None:
        self._refresh_list()

    def _label_for(self, project: Project) -> str:
        if not Path(project.resolved_path).exists():
            return f"{project.name}  (missing)"
        act = self._activity.get(project.resolved_path)
        if not act:
            return project.name
        parts = [project.name]
        if act.get("running"):
            parts.append(f"●{act['running']}")
        if act.get("done"):
            parts.append("✓")
        return "  ".join(parts)

    def _refresh_list(self) -> None:
        lv = self.query_one("#project-listview", ListView)
        lv.clear()
        for project in self._config.projects:
            item = ListItem(Label(self._label_for(project)))
            item.data = project  # type: ignore[attr-defined]
            lv.append(item)
        if self._config.projects:
            lv.index = 0

    def reload(self, config: Config) -> None:
        self._config = config
        self._refresh_list()

    def update_activity(self, activity: dict[str, dict]) -> None:
        """Update per-project badges in place, preserving the cursor."""
        self._activity = activity
        lv = self.query_one("#project-listview", ListView)
        for item in lv.children:
            project = getattr(item, "data", None)
            if project is None:
                continue
            try:
                item.query_one(Label).update(self._label_for(project))
            except Exception:
                pass

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
