from __future__ import annotations
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Label, ListView, ListItem

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

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, config: Config) -> None:
        super().__init__(id="left")
        self._config = config
        self._activity: dict[str, dict] = {}
        self._spinner_frame: int = 0
        self._filter: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-title-bar"):
            yield Label("Projects")
            add = Button("+", id="btn-add-project", classes="add-btn")
            add.can_focus = False
            yield add
        inp = Input(id="project-filter", placeholder="filter projects…")
        inp.display = False
        yield inp
        yield ListView(id="project-listview")

    def on_mount(self) -> None:
        self._refresh_list()

    def _label_for(self, project: Project) -> str:
        if not Path(project.resolved_path).exists():
            return f"{project.name}  (missing)"
        act = self._activity.get(project.resolved_path)
        if not act or not act.get("open"):
            return project.name
        if act.get("bg_working"):
            badge = self._SPINNER[self._spinner_frame % len(self._SPINNER)]
        elif act.get("done"):
            badge = "●"
        else:
            badge = "○"
        return f"{project.name}  {badge}"

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

    def move_highlighted(self, delta: int) -> None:
        lv = self.query_one("#project-listview", ListView)
        idx = lv.index
        if idx is None:
            return
        project = self.highlighted_project
        if project is None:
            return
        if self._config.move_project(project, delta):
            self._refresh_list()
            lv.index = idx + delta

    def update_activity(self, activity: dict[str, dict]) -> None:
        """Store new activity and refresh badges in place."""
        self._activity = activity
        self._apply_labels()

    def tick_spinner(self) -> None:
        """Advance the spinner frame and redraw only if there are bg_working sessions."""
        self._spinner_frame += 1
        if any(a.get("bg_working") for a in self._activity.values()):
            self._apply_labels()

    def _apply_labels(self) -> None:
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
