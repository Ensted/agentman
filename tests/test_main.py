from click.testing import CliRunner

import agentman.main as main


def _wire(monkeypatch, *, has_session, inside=False):
    state = {"killed": 0, "relaunched": 0}

    class FakeTmux:
        @staticmethod
        def inside():
            return inside

        def kill_session(self):
            if has_session:
                state["killed"] += 1
                return True
            return False

    monkeypatch.setattr(main, "Tmux", FakeTmux)
    monkeypatch.setattr(main, "relaunch_in_tmux",
                        lambda: state.__setitem__("relaunched", state["relaunched"] + 1))
    return state


def test_kill_only_with_running_session(monkeypatch):
    state = _wire(monkeypatch, has_session=True)
    result = CliRunner().invoke(main.cli, ["--kill"])
    assert result.exit_code == 0
    assert state == {"killed": 1, "relaunched": 0}   # killed, did not start
    assert "Killed" in result.output


def test_kill_only_with_no_session(monkeypatch):
    state = _wire(monkeypatch, has_session=False)
    result = CliRunner().invoke(main.cli, ["--kill"])
    assert result.exit_code == 0
    assert state == {"killed": 0, "relaunched": 0}
    assert "No agentman session" in result.output


def test_clean_kills_then_starts(monkeypatch):
    state = _wire(monkeypatch, has_session=True, inside=False)
    result = CliRunner().invoke(main.cli, ["--clean"])
    assert result.exit_code == 0
    assert state == {"killed": 1, "relaunched": 1}   # killed old, started fresh


def test_default_starts_without_killing(monkeypatch):
    state = _wire(monkeypatch, has_session=True, inside=False)
    result = CliRunner().invoke(main.cli, [])
    assert result.exit_code == 0
    assert state == {"killed": 0, "relaunched": 1}
