from __future__ import annotations
from pathlib import Path
from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label
from textual.containers import Vertical, Horizontal


class VisibleDirectoryTree(DirectoryTree):
    """DirectoryTree that hides dotfiles/dotfolders."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [path for path in paths if not path.name.startswith(".")]


class DirPickerModal(ModalScreen[Path | None]):
    """Directory picker modal. Returns selected Path or None on cancel."""

    DEFAULT_CSS = """
    DirPickerModal {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected: Path = Path.home()

    def compose(self) -> ComposeResult:
        with Vertical(id="dir-picker-dialog"):
            yield Label("Select project folder")
            yield VisibleDirectoryTree(str(Path.home()), id="dir-tree")
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

    def action_cancel(self) -> None:
        self.dismiss(None)
