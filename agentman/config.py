from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
import tomlkit


CONFIG_PATH = Path.home() / ".config" / "agentman" / "config.toml"


@dataclass
class Project:
    name: str
    path: str

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
            Project(name=p["name"], path=p["path"])
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
            aot.append(t)
        doc["projects"] = aot
        return tomlkit.dumps(doc)

    def add_project(self, name: str, path: str) -> None:
        if any(p.resolved_path == str(Path(path).expanduser().resolve())
               for p in self.projects):
            return  # already present
        self.projects.append(Project(name=name, path=path))
        self.save()

    def remove_project(self, project: Project) -> None:
        """Remove a project from the config (does not touch the folder)."""
        target = project.resolved_path
        self.projects = [p for p in self.projects if p.resolved_path != target]
        self.save()
