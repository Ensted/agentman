from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class SortModal(ModalScreen[tuple[str, bool] | None]):
    """Pick a sort key + direction for the projects list. Returns (key, reverse)."""

    DEFAULT_CSS = """
    SortModal {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    _CHOICES = {
        "btn-name-asc": ("name", False),
        "btn-name-desc": ("name", True),
        "btn-date-asc": ("added_at", False),
        "btn-date-desc": ("added_at", True),
    }

    def compose(self) -> ComposeResult:
        with Vertical(id="sort-dialog"):
            yield Label("Sort projects by", id="sort-question")
            with Horizontal(id="sort-name-buttons"):
                yield Button("Name ↑", id="btn-name-asc")
                yield Button("Name ↓", id="btn-name-desc")
            with Horizontal(id="sort-date-buttons"):
                yield Button("Date added ↑", id="btn-date-asc")
                yield Button("Date added ↓", id="btn-date-desc")
            with Horizontal(id="sort-cancel-buttons"):
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self._CHOICES.get(event.button.id or ""))

    def action_cancel(self) -> None:
        self.dismiss(None)
