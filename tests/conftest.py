import pytest

import agentman.hooks as hooks


@pytest.fixture(autouse=True)
def _isolate_hooks(tmp_path, monkeypatch):
    """Redirect all hook file operations to a temp dir.

    Guarantees the test suite never reads or writes the real
    ~/.claude/settings.json or ~/.local/share/agentman paths.
    """
    share = tmp_path / "share-agentman"
    monkeypatch.setattr(hooks, "SHARE_DIR", share)
    monkeypatch.setattr(hooks, "DONE_DIR", share / "done")
    monkeypatch.setattr(hooks, "HELPER", share / "stop-hook.py")
    monkeypatch.setattr(hooks, "SETTINGS", tmp_path / "claude-settings.json")
