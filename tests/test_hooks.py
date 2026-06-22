import json

import agentman.hooks as hooks


def test_install_registers_stop_and_pretool_hooks():
    hooks.install()
    assert hooks.HELPER.exists()
    assert hooks.WORKING_HELPER.exists()
    settings = json.loads(hooks.SETTINGS.read_text())
    stop_cmds = [h["command"] for grp in settings["hooks"]["Stop"] for h in grp["hooks"]]
    pretool_cmds = [h["command"] for grp in settings["hooks"]["PreToolUse"] for h in grp["hooks"]]
    assert any(str(hooks.HELPER) in c for c in stop_cmds)
    assert any(str(hooks.WORKING_HELPER) in c for c in pretool_cmds)


def test_install_is_idempotent():
    hooks.install()
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    stop_cmds = [h["command"] for grp in settings["hooks"]["Stop"] for h in grp["hooks"]]
    pretool_cmds = [h["command"] for grp in settings["hooks"]["PreToolUse"] for h in grp["hooks"]]
    assert len([c for c in stop_cmds if str(hooks.HELPER) in c]) == 1
    assert len([c for c in pretool_cmds if str(hooks.WORKING_HELPER) in c]) == 1


def test_install_preserves_existing_settings():
    hooks.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hooks.SETTINGS.write_text(json.dumps({"theme": "dark", "hooks": {
        "Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "/some/other/hook"}]}]}}))
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    assert settings["theme"] == "dark"
    stop_cmds = [h["command"] for grp in settings["hooks"]["Stop"] for h in grp["hooks"]]
    assert "/some/other/hook" in stop_cmds       # existing hook kept
    assert any(str(hooks.HELPER) in c for c in stop_cmds)  # ours added


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


def test_is_working_and_clear():
    hooks.WORKING_DIR.mkdir(parents=True, exist_ok=True)
    (hooks.WORKING_DIR / "sess-2").touch()
    assert hooks.is_working("sess-2") is True
    hooks.clear_working("sess-2")
    assert hooks.is_working("sess-2") is False
    hooks.clear_working("sess-2")  # idempotent, no error


def test_is_working_no_spinner_without_done_marker():
    """No done marker (fresh or just-opened session) → never a false positive."""
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "sess-3.jsonl").write_text("{}")  # transcript exists but no done marker
    assert hooks.is_working("sess-3") is False


def test_is_working_not_working_when_done_newer():
    """Transcript older than done marker means the turn already completed."""
    import time as _time
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    transcript = proj / "sess-4.jsonl"
    transcript.write_text("{}")
    _time.sleep(0.01)
    hooks.DONE_DIR.mkdir(parents=True, exist_ok=True)
    (hooks.DONE_DIR / "sess-4").write_text("")
    assert hooks.is_working("sess-4") is False


def test_is_working_new_prompt_after_done():
    """Transcript newer than done marker means a new prompt is in-flight."""
    import time as _time
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    hooks.DONE_DIR.mkdir(parents=True, exist_ok=True)
    (hooks.DONE_DIR / "sess-5").write_text("")
    _time.sleep(0.01)
    (proj / "sess-5.jsonl").write_text("{}")
    assert hooks.is_working("sess-5") is True


def test_stop_hook_clears_working_marker(tmp_path):
    """The Stop helper script should write done and remove the working marker."""
    import subprocess, sys
    done_dir = tmp_path / "done"
    working_dir = tmp_path / "working"
    done_dir.mkdir(); working_dir.mkdir()
    (working_dir / "s123").touch()

    script = hooks.HELPER_SRC.replace(
        'Path.home() / ".local" / "share" / "agentman"',
        f'__import__("pathlib").Path({str(tmp_path)!r})',
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"session_id": "s123"}),
        text=True,
    )
    assert result.returncode == 0
    assert (done_dir / "s123").exists()
    assert not (working_dir / "s123").exists()
