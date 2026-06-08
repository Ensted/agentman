import json

import agentman.hooks as hooks


def test_install_registers_stop_hook_and_helper():
    hooks.install()
    assert hooks.HELPER.exists()
    settings = json.loads(hooks.SETTINGS.read_text())
    stop = settings["hooks"]["Stop"]
    cmds = [h["command"] for grp in stop for h in grp["hooks"]]
    assert any(str(hooks.HELPER) in c for c in cmds)


def test_install_is_idempotent():
    hooks.install()
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    stop = settings["hooks"]["Stop"]
    cmds = [h["command"] for grp in stop for h in grp["hooks"]]
    ours = [c for c in cmds if str(hooks.HELPER) in c]
    assert len(ours) == 1


def test_install_preserves_existing_settings():
    hooks.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hooks.SETTINGS.write_text(json.dumps({"theme": "dark", "hooks": {
        "Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "/some/other/hook"}]}]}}))
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    assert settings["theme"] == "dark"
    cmds = [h["command"] for grp in settings["hooks"]["Stop"] for h in grp["hooks"]]
    assert "/some/other/hook" in cmds            # existing hook kept
    assert any(str(hooks.HELPER) in c for c in cmds)  # ours added


def test_install_skips_unparseable_settings():
    hooks.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hooks.SETTINGS.write_text("{ not valid json")
    hooks.install()  # must not raise or clobber
    assert hooks.SETTINGS.read_text() == "{ not valid json"


def test_is_done_and_clear():
    hooks.DONE_DIR.mkdir(parents=True, exist_ok=True)
    (hooks.DONE_DIR / "sess-1").write_text("")
    assert hooks.is_done("sess-1") is True
    hooks.clear_done("sess-1")
    assert hooks.is_done("sess-1") is False
    hooks.clear_done("sess-1")  # idempotent, no error
