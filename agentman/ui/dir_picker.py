from __future__ import annotations
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label
from textual.containers import Vertical, Horizontal


class DirPickerModal(ModalScreen[Path | None]):
    """Directory picker modal. Returns selected Path or None on cancel."""

    DEFAULT_CSS = """
    DirPickerModal {
        align: center middle;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._selected: Path = Path.home()

    def compose(self) -> ComposeResult:
        with Vertical(id="dir-picker-dialog"):
            yield Label("Select project folder")
            yield DirectoryTree(str(Path.home()), id="dir-tree")
            with Horizontal(id="dir-picker-buttons"):
                yield Button("Add", variant="primary", id="btn-add")
                yield Button("Cancel", id="btn-cancel")

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._selected = event.path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            self.dismiss(self._selected)
        else:
            self.dismiss(None)
