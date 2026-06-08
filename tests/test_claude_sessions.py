import json
from datetime import datetime, timezone

import agentman.claude_sessions as cs
from agentman.claude_sessions import load_sessions, relative_time, _parse_ts


def _write_history(tmp_path, monkeypatch, rows, transcripts=True):
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(cs, "HISTORY_FILE", path)
    # Create transcript files so sessions count as resumable (unless opted out).
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True, exist_ok=True)
    if transcripts:
        for r in rows:
            sid = r.get("sessionId")
            if sid:
                (proj / f"{sid}.jsonl").write_text("{}")
    monkeypatch.setattr(cs, "PROJECTS_DIR", tmp_path / "projects")
    return path


def test_parse_epoch_milliseconds():
    dt = _parse_ts(1780917342569)
    assert dt.year == 2026
    assert dt.tzinfo is not None


def test_parse_iso_string():
    dt = _parse_ts("2026-06-08T12:00:00Z")
    assert dt.year == 2026


def test_parse_garbage_returns_min():
    assert _parse_ts(None) == datetime.min.replace(tzinfo=timezone.utc)
    assert _parse_ts("not-a-date") == datetime.min.replace(tzinfo=timezone.utc)


def test_dedupe_one_session_per_id(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "s1", "project": "/p", "display": "first prompt", "timestamp": 1000},
        {"sessionId": "s1", "project": "/p", "display": "second prompt", "timestamp": 2000},
        {"sessionId": "s1", "project": "/p", "display": "third prompt", "timestamp": 3000},
    ])
    sessions = load_sessions("/p")
    assert len(sessions) == 1
    # Title is the first prompt; timestamp is the latest activity.
    assert sessions[0].display == "first prompt"
    assert sessions[0].timestamp == _parse_ts(3000)


def test_slash_command_title_upgraded(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "s1", "project": "/p", "display": "/model", "timestamp": 1000},
        {"sessionId": "s1", "project": "/p", "display": "real work here", "timestamp": 2000},
    ])
    sessions = load_sessions("/p")
    assert sessions[0].display == "real work here"


def test_exit_title_upgraded_to_real_prompt(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "s1", "project": "/p", "display": "exit", "timestamp": 1000},
        {"sessionId": "s1", "project": "/p", "display": "actually do the thing", "timestamp": 2000},
    ])
    assert load_sessions("/p")[0].display == "actually do the thing"


def test_all_noise_gets_untitled_label(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "s1abc999", "project": "/p", "display": "/model", "timestamp": 1000},
        {"sessionId": "s1abc999", "project": "/p", "display": "exit", "timestamp": 2000},
    ])
    # No meaningful prompt exists — clean placeholder, not "exit" or "/model".
    title = load_sessions("/p")[0].display
    assert title.startswith("(untitled")
    assert "s1abc999"[:8] in title


def test_paste_placeholder_is_untitled(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "pp123456", "project": "/p",
         "display": "[Pasted text #1 +23 lines]", "timestamp": 1000},
    ])
    assert load_sessions("/p")[0].display.startswith("(untitled")


def test_title_glyphs_and_whitespace_cleaned(tmp_path, monkeypatch):
    from agentman.claude_sessions import clean_title
    assert clean_title("▎ Opus 4.8 is here!\n\n") == "Opus 4.8 is here!"
    assert clean_title("a\n\n  b   c") == "a b c"


def test_filters_by_project(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "a", "project": "/p1", "display": "x", "timestamp": 1000},
        {"sessionId": "b", "project": "/p2", "display": "y", "timestamp": 1000},
    ])
    assert [s.session_id for s in load_sessions("/p1")] == ["a"]
    assert [s.session_id for s in load_sessions("/p2")] == ["b"]


def test_sorted_newest_first(tmp_path, monkeypatch):
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "old", "project": "/p", "display": "o", "timestamp": 1000},
        {"sessionId": "new", "project": "/p", "display": "n", "timestamp": 9000},
    ])
    ids = [s.session_id for s in load_sessions("/p")]
    assert ids == ["new", "old"]


def test_skips_malformed_lines(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    path.write_text(
        '{"sessionId": "a", "project": "/p", "display": "ok", "timestamp": 1000}\n'
        "this is not json\n"
        "\n"
    )
    monkeypatch.setattr(cs, "HISTORY_FILE", path)
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / "a.jsonl").write_text("{}")
    monkeypatch.setattr(cs, "PROJECTS_DIR", tmp_path / "projects")
    assert len(load_sessions("/p")) == 1


def test_session_without_transcript_is_dropped(tmp_path, monkeypatch):
    # 'b' has no transcript file -> not resumable -> filtered out.
    _write_history(tmp_path, monkeypatch, [
        {"sessionId": "a", "project": "/p", "display": "real", "timestamp": 1000},
        {"sessionId": "b", "project": "/p", "display": "ghost", "timestamp": 2000},
    ], transcripts=False)
    proj = tmp_path / "projects" / "p"
    (proj / "a.jsonl").write_text("{}")  # only 'a' gets a transcript
    assert [s.session_id for s in load_sessions("/p")] == ["a"]


def test_missing_history_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "HISTORY_FILE", tmp_path / "nope.jsonl")
    assert load_sessions("/p") == []


def test_relative_time_buckets():
    now = datetime.now(tz=timezone.utc)
    from datetime import timedelta
    assert relative_time(now) == "just now"
    assert relative_time(now - timedelta(minutes=5)).endswith("m ago")
    assert relative_time(now - timedelta(hours=3)).endswith("h ago")
    assert relative_time(now - timedelta(days=1)) == "yesterday"
    assert relative_time(now - timedelta(days=5)).endswith("d ago")
