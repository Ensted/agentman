from types import SimpleNamespace

from agentman.tmux import Tmux, SESSION, BROWSER_WIDTH


class FakeRunner:
    def __init__(self, stdout="", returncode=0):
        self.calls = []
        self._stdout = stdout
        self._returncode = returncode

    def __call__(self, argv):
        self.calls.append(argv)
        return SimpleNamespace(stdout=self._stdout, returncode=self._returncode)


# ── command builders ──────────────────────────────────────────────────────────

def test_spawn_cmd_with_resume():
    cmd = Tmux.spawn_cmd("/home/morten/mdu", "abc-123")
    assert cmd[:2] == ["tmux", "split-window"]
    assert "-h" in cmd
    assert f"{SESSION}:0.0" in cmd
    assert "/home/morten/mdu" in cmd
    assert "claude --resume abc-123" in cmd[-1]
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1" in cmd[-1]


def test_spawn_cmd_fresh_session():
    cmd = Tmux.spawn_cmd("/home/morten/mdu", None)
    assert "claude --resume" not in cmd[-1]
    assert "claude" in cmd[-1]


def test_stash_and_join_use_bg_window_name():
    assert Tmux.bg_window("s12345678") == "am-s12345678"
    stash = Tmux.stash_cmd("s12345678")
    assert stash[:2] == ["tmux", "break-pane"]
    assert "-d" in stash and "am-s12345678" in stash
    assert f"{SESSION}:0.1" in stash
    join = Tmux.join_cmd("s12345678")
    assert join[:2] == ["tmux", "join-pane"]
    assert "am-s12345678.0" in join
    assert f"{SESSION}:0.0" in join


def test_bootstrap_disables_rename_and_enables_mouse():
    cmds = Tmux.bootstrap_cmds("/usr/bin/agentman")
    verbs = [c[1] for c in cmds]
    assert verbs[0] == "new-session"
    assert verbs[-1] == "attach-session"
    assert ["tmux", "set-option", "-t", SESSION, "mouse", "on"] in cmds
    assert ["tmux", "set-option", "-t", SESSION, "automatic-rename", "off"] in cmds
    assert ["tmux", "set-option", "-t", SESSION, "allow-rename", "off"] in cmds
    # The browser runs agentman --inner as pane 0.
    new = cmds[0]
    assert "/usr/bin/agentman" in new and "--inner" in new


# ── show_session orchestration ─────────────────────────────────────────────────

def test_show_first_session_spawns():
    runner = FakeRunner()
    capture = FakeRunner(stdout="", returncode=0)  # no windows, no panes
    Tmux(runner=runner, capture=capture).show_session("/p", "sid", "s12345678", None)
    verbs = [c[1] for c in runner.calls]
    assert "split-window" in verbs        # fresh spawn
    assert "break-pane" not in verbs      # nothing to stash
    assert runner.calls[-2] == ["tmux", "select-pane", "-t", f"{SESSION}:0.1"]
    assert runner.calls[-1] == ["tmux", "resize-pane", "-t", f"{SESSION}:0.0",
                                "-x", str(BROWSER_WIDTH)]


def test_show_switch_stashes_previous_and_spawns_new():
    runner = FakeRunner()
    # capture: workspace pane present, and no existing bg window for the target
    capture = FakeRunner(stdout="0\n1\n", returncode=0)
    t = Tmux(runner=runner, capture=capture)
    t.show_session("/p", "sidB", "sBBBBBBB", "sAAAAAAA")
    verbs = [c[1] for c in runner.calls]
    # previous session A is parked, then B is spawned fresh
    assert "break-pane" in verbs
    assert "split-window" in verbs
    stash = next(c for c in runner.calls if c[1] == "break-pane")
    assert "am-sAAAAAAA" in stash


def test_show_switch_rejoins_existing_background_session():
    runner = FakeRunner()
    # workspace present (0,1) AND target already parked as am-sBBBBBBB
    capture = FakeRunner(stdout="0\n1\nam-sBBBBBBB\nagentman\n", returncode=0)
    t = Tmux(runner=runner, capture=capture)
    t.show_session("/p", "sidB", "sBBBBBBB", "sAAAAAAA")
    verbs = [c[1] for c in runner.calls]
    assert "break-pane" in verbs          # stash A
    assert "join-pane" in verbs           # reuse B's window
    assert "split-window" not in verbs


def test_show_same_session_just_focuses():
    runner = FakeRunner()
    capture = FakeRunner(stdout="0\n1\n", returncode=0)
    t = Tmux(runner=runner, capture=capture)
    t.show_session("/p", "sid", "skey", "skey")
    assert runner.calls == [["tmux", "select-pane", "-t", f"{SESSION}:0.1"]]


# ── state queries ──────────────────────────────────────────────────────────────

def test_running_keys_parses_bg_windows():
    capture = FakeRunner(stdout="agentman\nam-s12345678\nam-n2\n", returncode=0)
    keys = Tmux(capture=capture).running_keys()
    assert keys == {"s12345678", "n2"}


def test_workspace_exists_true_when_pane_1_present():
    capture = FakeRunner(stdout="0\n1\n", returncode=0)
    assert Tmux(capture=capture).workspace_exists() is True


def test_workspace_exists_false_when_only_browser():
    capture = FakeRunner(stdout="0\n", returncode=0)
    assert Tmux(capture=capture).workspace_exists() is False


def test_detach_targets_the_session():
    runner = FakeRunner()
    Tmux(runner=runner).detach()
    assert runner.calls == [["tmux", "detach-client", "-s", SESSION]]


def test_session_running_reflects_has_session_returncode():
    assert Tmux(capture=FakeRunner(returncode=0)).session_running() is True
    assert Tmux(capture=FakeRunner(returncode=1)).session_running() is False
