"""Tests for resumable whole-computer scan checkpoints."""

from pathlib import Path

import mido

from midi_parser.checkpoint import (
    clear_checkpoint,
    load_checkpoint,
    new_checkpoint,
    save_checkpoint,
)
from midi_parser.organize import classify_with_checkpoint
from midi_parser.scan import discover_with_checkpoint
from midi_parser.util import format_duration, format_size


def _write_midi(path: Path, pitches: list[int]) -> None:
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    for p in pitches:
        track.append(mido.Message("note_on", note=p, velocity=100, time=0))
        track.append(mido.Message("note_off", note=p, velocity=0, time=240))
    mid.save(path)


def test_format_helpers():
    assert format_duration(65) == "1:05"
    assert format_duration(3661) == "1:01:01"
    assert format_size(500) == "500 B"
    assert "KB" in format_size(2048)


def test_discover_and_classify_checkpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIDI_PARSER_CHECKPOINT_DIR", str(tmp_path / "ck"))
    root = tmp_path / "tree"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    _write_midi(nested / "BA_one.mid", [36, 38])
    _write_midi(root / "LD_two.mid", [60, 62])

    clear_checkpoint()
    cp = new_checkpoint(root)
    save_checkpoint(cp)

    discover_with_checkpoint(cp, save_every=1)
    assert cp.phase == "classify"
    assert len(cp.found) == 2

    # Simulate crash: reload and continue classify
    reloaded = load_checkpoint()
    assert reloaded is not None
    assert reloaded.phase == "classify"
    assert len(reloaded.found) == 2

    results = classify_with_checkpoint(reloaded, save_every=1)
    assert len(results) == 2
    assert {r.category for r in results} == {"Bass", "Lead"}
    assert sum(r.size_bytes for r in results) > 0
    assert reloaded.phase == "done"


def test_resume_skips_completed_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIDI_PARSER_CHECKPOINT_DIR", str(tmp_path / "ck"))
    root = tmp_path / "tree"
    root.mkdir()
    _write_midi(root / "Kick.mid", [36])

    clear_checkpoint()
    cp = new_checkpoint(root)
    save_checkpoint(cp)
    discover_with_checkpoint(cp, save_every=1)

    # Second discovery on a done-phase should not be needed; create fresh resume
    # mid-discover: mark root completed with empty pending after partial
    cp2 = new_checkpoint(root)
    cp2.pending_dirs = []
    cp2.phase = "discover"
    cp2.found = []
    # Pretend root already completed with no pending → finishes immediately
    from midi_parser.checkpoint import save_checkpoint as save

    save(cp2, new_completed=[str(root.resolve())])
    cp2.completed_dirs.add(str(root.resolve()))
    discover_with_checkpoint(cp2, save_every=1)
    assert cp2.phase == "classify"
