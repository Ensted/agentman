import json

import pytest

import agentman.config as config_mod
import agentman.claude_sessions as cs
import agentman.hooks as hooks
from agentman.app import AgentManApp
from agentman.config import Config, Project
from agentman.ui.project_list import ProjectList
from agentman.ui.session_panel import SessionPanel


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)

    # Real project folders so the missing-folder guard doesn't reject them.
    alpha = tmp_path / "alpha"; alpha.mkdir()
    beta = tmp_path / "beta"; beta.mkdir()
    apath, bpath = str(alpha.resolve()), str(beta.resolve())
    Config(projects=[Project("alpha", apath), Project("beta", bpath)]).save()

    rows = [
        {"sessionId": "a1", "project": apath, "display": "alpha work", "timestamp": 5000},
        {"sessionId": "a2", "project": apath, "display": "more alpha", "timestamp": 6000},
        {"sessionId": "b1", "project": bpath, "display": "beta work", "timestamp": 7000},
    ]
    hist = tmp_path / "history.jsonl"
    hist.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(cs, "HISTORY_FILE", hist)

    # Transcript files so the sessions count as resumable.
    proj = tmp_path / "projects" / "x"
    proj.mkdir(parents=True)
    for r in rows:
        (proj / f"{r['sessionId']}.jsonl").write_text("{}")
    monkeypatch.setattr(cs, "PROJECTS_DIR", tmp_path / "projects")


async def test_app_highlighting_project_loads_its_sessions(seeded):
    app = AgentManApp(has_workspace=False)
    async with app.run_test() as pilot:
        pl = app.query_one(ProjectList)
        pl.post_message(ProjectList.Highlighted(app._config.projects[0]))
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        assert sp._project.name == "alpha"
        assert {s.session_id for s in sp._sessions} == {"a1", "a2"}

        pl.post_message(ProjectList.Highlighted(app._config.projects[1]))
        await pilot.pause()
        assert sp._project.name == "beta"
        assert {s.session_id for s in sp._sessions} == {"b1"}


async def test_activating_project_focuses_session_list(seeded):
    app = AgentManApp(has_workspace=False)
    async with app.run_test() as pilot:
        pl = app.query_one(ProjectList)
        pl.post_message(ProjectList.Activated(app._config.projects[0]))
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        assert sp._project.name == "alpha"
        assert app.query_one("#session-listview").has_focus


async def test_remove_project_drops_it_from_view_and_config(seeded):
    from textual.widgets import ListView
    app = AgentManApp(has_workspace=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        pl = app.query_one(ProjectList)
        lv = app.query_one("#project-listview", ListView)
        lv.index = 0
        await pilot.pause()
        first = pl.highlighted_project
        assert first is not None
        await app.run_action("remove_project")
        await pilot.pause()
        names = [p.name for p in app._config.projects]
        assert first.name not in names

    # Persisted to disk too.
    from agentman.config import Config
    assert first.name not in [p.name for p in Config.load().projects]


async def test_ctrl_q_detaches_when_in_workspace(seeded, monkeypatch):
    detached = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "detach", lambda: detached.append(True))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.run_action("close_app")
        await pilot.pause()
    assert detached == [True]  # session detached, not torn down


async def test_ctrl_q_exits_when_no_workspace(seeded, monkeypatch):
    exited = []
    app = AgentManApp(has_workspace=False)
    monkeypatch.setattr(app, "exit", lambda *a, **k: exited.append(True))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.run_action("close_app")
        await pilot.pause()
    assert exited == [True]  # plain exit, no tmux session to detach


async def test_completion_detection_flags_background_session(seeded, monkeypatch):
    app = AgentManApp(has_workspace=True)
    # A launched session parked in the background, with a different one in scope.
    monkeypatch.setattr(app._tmux, "running_keys", lambda: {"sbgid1234"})
    monkeypatch.setattr(hooks, "is_done", lambda sid: sid == "bgid1234-full")
    bells = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app._sessions_by_key = {"sbgid1234": "bgid1234-full"}
        app._current_key = "sother567"
        monkeypatch.setattr(app, "bell", lambda: bells.append(1))
        app._poll_completions()
        await pilot.pause()
        assert "bgid1234" in app._done_id8s()   # flagged done
        assert bells == [1]                       # notified once
        assert "finished" in app.sub_title


async def test_new_session_gets_known_id_and_is_marked_open(seeded, monkeypatch):
    calls = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "show_session",
                        lambda path, sid, key, prev, resume: calls.append((sid, resume)))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        app.query_one(ProjectList).post_message(
            ProjectList.Highlighted(app._config.projects[0]))
        await pilot.pause()
        app.query_one(SessionPanel).post_message(
            SessionPanel.NewRequested(app._config.projects[0]))
        await pilot.pause()
    sid, resume = calls[0]
    assert resume is False                 # launched with --session-id, not --resume
    assert sid and sid == app._open_session_id   # known id, marked as the open one
    assert app._current_key == f"s{sid[:8]}"


async def test_inscope_state_clears_when_pane_closes(seeded, monkeypatch):
    app = AgentManApp(has_workspace=True)
    # Pretend a session is in scope, then its claude pane is gone.
    monkeypatch.setattr(app._tmux, "workspace_exists", lambda: False)
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._current_key = "sa2"
        app._open_session_id = "a2"
        app._poll_completions()
        await pilot.pause()
    assert app._open_session_id is None
    assert app._current_key is None


async def test_open_missing_folder_is_blocked(seeded, monkeypatch):
    calls = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "show_session",
                        lambda *a: calls.append(a))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._open("/definitely/not/here", "sid")
        await pilot.pause()
    assert calls == []   # refused to launch in a missing folder


def test_project_activity_counts(seeded, monkeypatch):
    app = AgentManApp(has_workspace=True)
    app._launched_projects = {"sAAA": "/p1", "sBBB": "/p1", "sCCC": "/p2"}
    app._sessions_by_key = {"sAAA": "idA", "sBBB": "idB", "sCCC": "idC"}
    app._current_key = "sAAA"   # in scope, belongs to /p1
    monkeypatch.setattr(app._tmux, "running_keys", lambda: {"sBBB", "sCCC"})
    monkeypatch.setattr(hooks, "is_done", lambda sid: sid == "idB")

    act = app._project_activity()
    assert act["/p1"] == {"running": 2, "done": True}   # sAAA (scope) + sBBB (bg, done)
    assert act["/p2"] == {"running": 1, "done": False}


async def test_kill_background_session(seeded, monkeypatch):
    from textual.widgets import ListView
    killed = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "kill", lambda key, cur: killed.append((key, cur)))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        sp.load_project(app._config.projects[0])
        await pilot.pause()
        app.query_one("#session-listview", ListView).index = 0  # highlight a2
        await pilot.pause()
        await app.run_action("kill_session")
        await pilot.pause()
    assert killed == [("sa2", False)]   # background kill (not the in-scope one)


async def test_kill_current_session(seeded, monkeypatch):
    from textual.widgets import ListView
    killed = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "kill", lambda key, cur: killed.append((key, cur)))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        sp.load_project(app._config.projects[0])
        await pilot.pause()
        app.query_one("#session-listview", ListView).index = 0
        await pilot.pause()
        app._current_key = "sa2"      # a2 is the in-scope session
        app._open_session_id = "a2"
        await app.run_action("kill_session")
        await pilot.pause()
        assert killed == [("sa2", True)]
        assert app._current_key is None and app._open_session_id is None


async def test_open_in_vscode_launches_code(seeded, monkeypatch):
    import agentman.app as appmod
    launched = []
    monkeypatch.setattr(appmod.subprocess, "Popen",
                        lambda argv, **k: launched.append(argv))
    app = AgentManApp(has_workspace=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ProjectList).post_message(
            ProjectList.Highlighted(app._config.projects[0]))
        await pilot.pause()
        await app.run_action("open_in_vscode")
        await pilot.pause()
    apath = app._config.projects[0].resolved_path
    assert launched == [["code", apath]]


async def test_open_in_vscode_noop_without_project(seeded, monkeypatch):
    import agentman.app as appmod
    launched = []
    monkeypatch.setattr(appmod.subprocess, "Popen",
                        lambda argv, **k: launched.append(argv))
    app = AgentManApp(has_workspace=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._current_project = None
        await app.run_action("open_in_vscode")
        await pilot.pause()
    assert launched == []


async def test_open_session_shows_via_tmux(seeded, monkeypatch):
    calls = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "show_session",
                        lambda path, sid, key, prev, resume: calls.append(
                            (path, sid, key, prev, resume)))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        app.query_one(ProjectList).post_message(
            ProjectList.Highlighted(app._config.projects[0]))
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        sp.post_message(SessionPanel.OpenRequested(sp._sessions[0]))
        await pilot.pause()

    # newest-first -> a2; keyed by resume prefix; resuming an existing session.
    apath = app._config.projects[0].resolved_path
    assert calls == [(apath, "a2", "sa2", None, True)]
    assert app._open_session_id == "a2"
    assert app._current_key == "sa2"


async def test_switching_sessions_passes_previous_key(seeded, monkeypatch):
    calls = []
    app = AgentManApp(has_workspace=True)
    monkeypatch.setattr(app._tmux, "show_session",
                        lambda path, sid, key, prev, resume: calls.append((sid, key, prev)))
    monkeypatch.setattr(app._tmux, "running_keys", lambda: set())
    async with app.run_test() as pilot:
        app.query_one(ProjectList).post_message(
            ProjectList.Highlighted(app._config.projects[0]))
        await pilot.pause()
        sp = app.query_one(SessionPanel)
        sp.post_message(SessionPanel.OpenRequested(sp._sessions[0]))  # a2
        await pilot.pause()
        sp.post_message(SessionPanel.OpenRequested(sp._sessions[1]))  # a1
        await pilot.pause()

    # Second open carries the first session's key as `prev` (so it gets parked).
    assert calls[0] == ("a2", "sa2", None)
    assert calls[1] == ("a1", "sa1", "sa2")
