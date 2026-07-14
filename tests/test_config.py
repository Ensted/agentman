from pathlib import Path

import agentman.config as config_mod
from agentman.config import Config, Project


def test_save_load_roundtrip_multiple_projects(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    cfg = Config(projects=[
        Project("home", "/home/morten"),
        Project("amd", "/home/morten/amd"),
        Project("mdu", "/home/morten/mdu"),
    ])
    cfg.save()

    loaded = Config.load()
    assert [p.name for p in loaded.projects] == ["home", "amd", "mdu"]
    assert [p.path for p in loaded.projects] == [
        "/home/morten", "/home/morten/amd", "/home/morten/mdu"
    ]


def test_dumps_produces_array_of_tables():
    cfg = Config(projects=[
        Project("a", "/a"),
        Project("b", "/b"),
    ])
    text = cfg.dumps()
    # Two [[projects]] entries — this was the KeyAlreadyPresent crash.
    assert text.count("[[projects]]") == 2
    assert 'name = "a"' in text
    assert 'name = "b"' in text


def test_add_project_persists(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    cfg = Config(projects=[Project("home", "/home/morten")])
    cfg.save()
    cfg.add_project("new", str(tmp_path))

    reloaded = Config.load()
    assert any(p.name == "new" for p in reloaded.projects)


def test_add_project_dedupes_by_resolved_path(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    target = tmp_path / "proj"
    target.mkdir()
    cfg = Config()
    cfg.add_project("proj", str(target))
    cfg.add_project("proj-again", str(target))  # same path, should be ignored

    assert len(cfg.projects) == 1


def test_remove_project_by_path(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    a, b = Project("a", "/a"), Project("b", "/b")
    cfg = Config(projects=[a, b])
    cfg.save()
    cfg.remove_project(a)

    reloaded = Config.load()
    assert [p.name for p in reloaded.projects] == ["b"]


def test_remove_project_distinguishes_same_name(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    # Two projects with the same display name but different paths.
    p1 = Project("build", "/one/build")
    p2 = Project("build", "/two/build")
    cfg = Config(projects=[p1, p2])
    cfg.remove_project(p1)

    assert [p.path for p in cfg.projects] == ["/two/build"]


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "nope.toml")
    assert Config.load().projects == []


def test_resolved_path_expands_user(monkeypatch):
    p = Project("h", "~/somedir")
    assert p.resolved_path == str(Path("~/somedir").expanduser().resolve())


def test_move_project_up(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    a, b, c = Project("a", "/a"), Project("b", "/b"), Project("c", "/c")
    cfg = Config(projects=[a, b, c])
    cfg.save()

    moved = cfg.move_project(b, -1)
    assert moved is True
    assert [p.name for p in cfg.projects] == ["b", "a", "c"]

    reloaded = Config.load()
    assert [p.name for p in reloaded.projects] == ["b", "a", "c"]


def test_move_project_down(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    a, b, c = Project("a", "/a"), Project("b", "/b"), Project("c", "/c")
    cfg = Config(projects=[a, b, c])
    cfg.save()

    moved = cfg.move_project(b, 1)
    assert moved is True
    assert [p.name for p in cfg.projects] == ["a", "c", "b"]


def test_move_project_at_boundary_is_noop():
    a, b = Project("a", "/a"), Project("b", "/b")
    cfg = Config(projects=[a, b])

    assert cfg.move_project(a, -1) is False
    assert cfg.move_project(b, 1) is False
    assert [p.name for p in cfg.projects] == ["a", "b"]


def test_move_project_unknown_is_noop():
    cfg = Config(projects=[Project("a", "/a")])
    assert cfg.move_project(Project("z", "/z"), -1) is False


def test_load_sorts_legacy_config_once(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    # A config.toml written before the projects_sorted flag existed.
    cfg_path.write_text(
        '[[projects]]\nname = "zeta"\npath = "/z"\n'
        '[[projects]]\nname = "alpha"\npath = "/a"\n'
    )

    loaded = Config.load()
    assert [p.name for p in loaded.projects] == ["alpha", "zeta"]
    assert loaded.projects_sorted is True

    # Manually re-order after the one-time sort; a later reload must
    # preserve it rather than re-sorting alphabetically again.
    loaded.move_project(loaded.projects[1], -1)
    reloaded = Config.load()
    assert [p.name for p in reloaded.projects] == ["zeta", "alpha"]


def test_add_project_inserts_alphabetically(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    cfg = Config(projects=[Project("alpha", "/a"), Project("zeta", "/z")])
    cfg.add_project("mid", str(tmp_path))

    assert [p.name for p in cfg.projects] == ["alpha", "mid", "zeta"]
