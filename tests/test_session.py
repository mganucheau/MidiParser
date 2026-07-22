"""Tests for UI session persistence."""

from __future__ import annotations

from pathlib import Path

from midi_parser.session import SessionState, load_session, save_session


def test_session_roundtrip(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "session.json"
    monkeypatch.setenv("MIDI_PARSER_SESSION", str(path))

    state = SessionState(
        sources=["/src/a", "/src/b"],
        dest="/dest",
        job="Move",
        remove_duplicates=True,
    )
    save_session(state, path)
    loaded = load_session(path)
    assert loaded.sources == ["/src/a", "/src/b"]
    assert loaded.dest == "/dest"
    assert loaded.job == "Move"
    assert loaded.remove_duplicates is True


def test_missing_session_defaults(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "missing.json"
    monkeypatch.setenv("MIDI_PARSER_SESSION", str(path))
    loaded = load_session(path)
    assert loaded.sources == []
    assert loaded.dest is None
    assert loaded.job == "Scan"
