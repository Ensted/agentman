import json
import os
import subprocess
import sys
import time

import agentman.hooks as hooks


def _commands(settings: dict, event: str) -> list[str]:
    return [h["command"] for grp in settings["hooks"][event] for h in grp["hooks"]]


def _run_helper(src: str, tmp_path, payload: dict) -> subprocess.CompletedProcess:
    """Run a helper script with its base dir redirected to tmp_path."""
    script = src.replace(
        'Path.home() / ".local" / "share" / "agentman"',
        f'__import__("pathlib").Path({str(tmp_path)!r})',
    )
    return subprocess.run(
        [sys.executable, "-c", script], input=json.dumps(payload), text=True)


def test_install_registers_all_hooks():
    hooks.install()
    assert hooks.HELPER.exists()
    assert hooks.WORKING_HELPER.exists()
    assert hooks.SESSION_END_HELPER.exists()
    settings = json.loads(hooks.SETTINGS.read_text())
    assert any(str(hooks.HELPER) in c for c in _commands(settings, "Stop"))
    assert any(str(hooks.WORKING_HELPER) in c for c in _commands(settings, "UserPromptSubmit"))
    assert any(str(hooks.WORKING_HELPER) in c for c in _commands(settings, "PreToolUse"))
    assert any(str(hooks.SESSION_END_HELPER) in c for c in _commands(settings, "SessionEnd"))


def test_install_is_idempotent():
    hooks.install()
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    for event, helper in (
        ("Stop", hooks.HELPER),
        ("UserPromptSubmit", hooks.WORKING_HELPER),
        ("PreToolUse", hooks.WORKING_HELPER),
        ("SessionEnd", hooks.SESSION_END_HELPER),
    ):
        assert len([c for c in _commands(settings, event) if str(helper) in c]) == 1


def test_install_preserves_existing_settings():
    hooks.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hooks.SETTINGS.write_text(json.dumps({"theme": "dark", "hooks": {
        "Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "/some/other/hook"}]}]}}))
    hooks.install()
    settings = json.loads(hooks.SETTINGS.read_text())
    assert settings["theme"] == "dark"
    stop_cmds = _commands(settings, "Stop")
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


def test_is_working_ignores_transcript_when_no_marker():
    """A transcript newer than the done marker must NOT mean working.

    Claude Code appends to the transcript after the Stop hook fires (hook
    records, draft-prompt persistence), so transcript mtime says nothing
    about an in-flight turn. Only the working marker does.
    """
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    hooks.DONE_DIR.mkdir(parents=True, exist_ok=True)
    (hooks.DONE_DIR / "sess-3").write_text("")
    time.sleep(0.01)
    (proj / "sess-3.jsonl").write_text("{}")  # written after Stop
    assert hooks.is_working("sess-3") is False


def test_is_working_stale_marker_is_dead_turn():
    """Marker + transcript both quiet past STALE_AFTER_S → interrupted turn."""
    hooks.WORKING_DIR.mkdir(parents=True, exist_ok=True)
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    marker = hooks.WORKING_DIR / "sess-4"
    transcript = proj / "sess-4.jsonl"
    marker.touch()
    transcript.write_text("{}")
    old = time.time() - hooks.STALE_AFTER_S - 60
    os.utime(marker, (old, old))
    os.utime(transcript, (old, old))
    assert hooks.is_working("sess-4") is False
    assert not marker.exists()  # self-healed


def test_is_working_old_marker_fresh_transcript_still_working():
    """A long turn keeps writing the transcript even if the marker is old."""
    hooks.WORKING_DIR.mkdir(parents=True, exist_ok=True)
    proj = hooks._CLAUDE_PROJECTS / "projhash"
    proj.mkdir(parents=True, exist_ok=True)
    marker = hooks.WORKING_DIR / "sess-5"
    marker.touch()
    old = time.time() - hooks.STALE_AFTER_S - 60
    os.utime(marker, (old, old))
    (proj / "sess-5.jsonl").write_text("{}")  # fresh transcript write
    assert hooks.is_working("sess-5") is True


def test_stop_hook_clears_working_marker(tmp_path):
    """The Stop helper script should write done and remove the working marker."""
    (tmp_path / "done").mkdir()
    (tmp_path / "working").mkdir()
    (tmp_path / "working" / "s123").touch()

    result = _run_helper(hooks.HELPER_SRC, tmp_path, {"session_id": "s123"})
    assert result.returncode == 0
    assert (tmp_path / "done" / "s123").exists()
    assert not (tmp_path / "working" / "s123").exists()


def test_working_hook_marks_working_and_clears_done(tmp_path):
    """UserPromptSubmit/PreToolUse helper: touch working, drop stale done."""
    (tmp_path / "done").mkdir()
    (tmp_path / "done" / "s123").write_text("")

    result = _run_helper(hooks.WORKING_HELPER_SRC, tmp_path, {"session_id": "s123"})
    assert result.returncode == 0
    assert (tmp_path / "working" / "s123").exists()
    assert not (tmp_path / "done" / "s123").exists()


def test_session_end_hook_removes_all_markers(tmp_path):
    (tmp_path / "done").mkdir()
    (tmp_path / "working").mkdir()
    (tmp_path / "done" / "s123").write_text("")
    (tmp_path / "working" / "s123").touch()

    result = _run_helper(hooks.SESSION_END_HELPER_SRC, tmp_path, {"session_id": "s123"})
    assert result.returncode == 0
    assert not (tmp_path / "done" / "s123").exists()
    assert not (tmp_path / "working" / "s123").exists()
