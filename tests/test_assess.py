"""Tests for content-based MIDI assessment."""

from pathlib import Path

import mido
import pytest

from midi_parser.assess import MidiClip, NoteEvent, assess_clip, assess_file, parse_midi_file
from midi_parser.organize import classify_file, count_by_category, organize
from midi_parser.scan import find_midi_files


def _clip(notes: list[NoteEvent]) -> MidiClip:
    return MidiClip(name="test", file_path="/tmp/test.mid", notes=notes)


def _note(pitch: int, start: float, length: float = 1.0, channel: int = 1) -> NoteEvent:
    return NoteEvent(note_number=pitch, velocity=100, channel=channel, start_beat=start, length_beats=length)


def test_drums_channel_10():
    clip = _clip([_note(36, 0, channel=10), _note(38, 1, channel=10)])
    assert assess_clip(clip) == "Drums"


def test_bass_low_mean_pitch():
    clip = _clip([_note(36, 0), _note(38, 1), _note(40, 2)])
    assert assess_clip(clip) == "Bass"


def test_chords_high_polyphony():
    # Three simultaneous notes at each onset → frequent chords
    notes = [
        _note(60, 0, 2),
        _note(64, 0, 2),
        _note(67, 0, 2),
        _note(60, 2, 2),
        _note(64, 2, 2),
        _note(67, 2, 2),
    ]
    assert assess_clip(_clip(notes)) == "Chords"


def test_lead_melodic():
    clip = _clip([_note(60, 0, 1), _note(62, 1, 1), _note(64, 2, 1), _note(65, 3, 1)])
    assert assess_clip(clip) == "Lead"


def test_arp_pattern():
    # Monophonic short notes spanning > octave with stepwise motion
    pitches = [60, 64, 67, 72, 67, 64, 60, 64]
    notes = [_note(p, i * 0.25, 0.2) for i, p in enumerate(pitches)]
    assert assess_clip(_clip(notes)) == "Arp"


def test_empty_unknown():
    assert assess_clip(_clip([])) == "Unknown"


def _write_simple_midi(path: Path, pitches: list[int], channel: int = 0) -> None:
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    for i, p in enumerate(pitches):
        track.append(mido.Message("note_on", note=p, velocity=100, channel=channel, time=0 if i else 0))
        track.append(mido.Message("note_off", note=p, velocity=0, channel=channel, time=240))
    mid.save(path)


def test_parse_and_assess_file(tmp_path: Path):
    path = tmp_path / "low_bass.mid"
    _write_simple_midi(path, [36, 38, 40])
    clip = parse_midi_file(path)
    assert len(clip.notes) == 3
    assert assess_file(path) == "Bass"


def test_name_hint_beats_content(tmp_path: Path):
    # Content would be bass pitches, but name says Lead
    path = tmp_path / "LD_line.mid"
    _write_simple_midi(path, [36, 38, 40])
    result = classify_file(path, tmp_path)
    assert result.category == "Lead"
    assert result.reason == "name"


def test_scan_finds_nested(tmp_path: Path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    _write_simple_midi(nested / "x.mid", [60])
    (tmp_path / "skip.txt").write_text("nope")
    found = find_midi_files(tmp_path)
    assert len(found) == 1
    assert found[0].name == "x.mid"


def test_organize_copies(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    _write_simple_midi(src / "BA_deep.mid", [60, 62])  # name → Bass
    _write_simple_midi(src / "mystery.mid", [60, 62, 64, 65])  # content → Lead or Arp

    results, counts = organize(src, dst, dry_run=False)
    assert (dst / "Bass" / "BA_deep.mid").is_file()
    assert sum(counts.values()) == 2
    assert counts["Bass"] >= 1
    assert all(r.dest is not None for r in results)


def test_organize_dry_run(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _write_simple_midi(src / "Kick.mid", [60])
    results, counts = organize(src, dst, dry_run=True)
    assert counts["Drums"] == 1
    assert not any((dst / c).exists() for c in ("Drums", "Bass", "Lead", "Chords", "Arp", "Unknown"))
    assert results[0].dest is not None


def test_remove_duplicates_skips_identical_content(tmp_path: Path):
    from shutil import copy2

    from midi_parser.organize import classify_all, duplicate_count

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    a = src / "Kick_A.mid"
    b = src / "nested"
    b.mkdir()
    _write_simple_midi(a, [36, 38])
    copy2(a, b / "Kick_copy.mid")  # identical bytes, different path/name
    _write_simple_midi(src / "BA_unique.mid", [40, 41, 42])

    scanned = classify_all(src, remove_duplicates=True)
    assert len(scanned) == 3
    assert duplicate_count(scanned) == 1

    results, counts = organize(src, dst, remove_duplicates=True, results=scanned)
    assert sum(counts.values()) == 2
    assert duplicate_count(results) == 1
    copied = list(dst.rglob("*.mid"))
    assert len(copied) == 2
    skipped = [r for r in results if r.is_duplicate]
    assert len(skipped) == 1
    assert skipped[0].dest is None


def test_without_remove_duplicates_copies_all(tmp_path: Path):
    from shutil import copy2

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    a = src / "Kick_A.mid"
    _write_simple_midi(a, [36, 38])
    copy2(a, src / "Kick_B.mid")

    results, counts = organize(src, dst, remove_duplicates=False)
    assert sum(counts.values()) == 2
    assert len(list(dst.rglob("*.mid"))) == 2
    assert all(not r.is_duplicate for r in results)
