from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import tomlkit


CONFIG_PATH = Path.home() / ".config" / "agentman" / "config.toml"


@dataclass
class Project:
    name: str
    path: str
    added_at: str = ""

    @property
    def resolved_path(self) -> str:
        return str(Path(self.path).expanduser().resolve())


@dataclass
class Config:
    projects: list[Project] = field(default_factory=list)

    @classmethod
    def load(cls) -> Config:
        if not CONFIG_PATH.exists():
            return cls()
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        projects = [
            Project(name=p["name"], path=p["path"], added_at=p.get("added_at", ""))
            for p in data.get("projects", [])
        ]
        return cls(projects=projects)

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(self.dumps())

    def dumps(self) -> str:
        doc = tomlkit.document()
        aot = tomlkit.aot()
        for project in self.projects:
            t = tomlkit.table()
            t["name"] = project.name
            t["path"] = project.path
            t["added_at"] = project.added_at
            aot.append(t)
        doc["projects"] = aot
        return tomlkit.dumps(doc)

    def add_project(self, name: str, path: str) -> None:
        if any(p.resolved_path == str(Path(path).expanduser().resolve())
               for p in self.projects):
            return  # already present
        self.projects.append(Project(
            name=name, path=path, added_at=datetime.now().isoformat()))
        self.save()

    def remove_project(self, project: Project) -> None:
        """Remove a project from the config (does not touch the folder)."""
        target = project.resolved_path
        self.projects = [p for p in self.projects if p.resolved_path != target]
        self.save()

    def move_project(self, project: Project, delta: int) -> bool:
        """Shift project by delta (-1 up, +1 down). Returns True if it moved."""
        target = project.resolved_path
        idx = next((i for i, p in enumerate(self.projects) if p.resolved_path == target), -1)
        new_idx = idx + delta
        if idx == -1 or not (0 <= new_idx < len(self.projects)):
            return False
        self.projects[idx], self.projects[new_idx] = self.projects[new_idx], self.projects[idx]
        self.save()
        return True

    def sort_projects(self, key: str, reverse: bool = False) -> None:
        """Explicitly sort by 'name' or 'added_at'. User-triggered, not automatic."""
        sort_key = (lambda p: p.name.casefold()) if key == "name" else (lambda p: p.added_at)
        self.projects.sort(key=sort_key, reverse=reverse)
        self.save()
