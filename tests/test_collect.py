"""Tests for fast MIDI collect (copy-only, no classify)."""

from __future__ import annotations

import errno
import shutil
from pathlib import Path

import pytest

from midi_parser.collect import _filter_dirnames, collect_midi
from midi_parser.scan import ScanCancelled


def _write_midi(path: Path, payload: bytes = b"MThd-fake") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_collect_copies_flat_and_skips_non_midi(tmp_path: Path) -> None:
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    _write_midi(src / "a" / "kick.mid", b"kick")
    _write_midi(src / "b" / "bass.midi", b"bass")
    (src / "readme.txt").write_text("nope")

    stats = collect_midi(src, dest)

    assert stats.found == 2
    assert stats.copied == 2
    assert stats.errors == 0
    assert (dest / "kick.mid").read_bytes() == b"kick"
    assert (dest / "bass.midi").read_bytes() == b"bass"
    assert not (dest / "readme.txt").exists()


def test_collect_collision_safe_names(tmp_path: Path) -> None:
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    _write_midi(src / "one" / "loop.mid", b"one")
    _write_midi(src / "two" / "loop.mid", b"two")

    stats = collect_midi(src, dest)

    assert stats.copied == 2
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["loop.mid", "loop_1.mid"]
    bodies = {p.read_bytes() for p in dest.iterdir()}
    assert bodies == {b"one", b"two"}


def test_collect_rerun_copies_again_unique_name(tmp_path: Path) -> None:
    """No hashing — re-run copies again with a collision-safe name."""
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    _write_midi(src / "x" / "clip.mid", b"same")

    first = collect_midi(src, dest)
    second = collect_midi(src, dest)

    assert first.copied == 1
    assert second.copied == 1
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["clip.mid", "clip_1.mid"]


def test_collect_does_not_walk_into_dest(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dest = root / "dump"
    _write_midi(root / "outer.mid", b"outer")
    dest.mkdir(parents=True)
    _write_midi(dest / "already.mid", b"inside")

    stats = collect_midi(root, dest)

    assert stats.found == 1
    assert stats.copied == 1
    assert (dest / "outer.mid").read_bytes() == b"outer"
    assert (dest / "already.mid").read_bytes() == b"inside"


def test_filter_skips_volumes_at_root(tmp_path: Path) -> None:
    dest = tmp_path / "dump"
    dest.mkdir()
    names = ["Users", "Volumes", "Applications", "System"]
    _filter_dirnames("/", names, dest_root=dest, skip_volumes=True)
    assert "Volumes" not in names
    assert "System" not in names
    assert "Users" in names
    assert "Applications" in names


def test_collect_cancel(tmp_path: Path) -> None:
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    for i in range(5):
        _write_midi(src / f"f{i}.mid", bytes([i]))

    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    with pytest.raises(ScanCancelled):
        collect_midi(src, dest, should_cancel=cancel)


def test_collect_retries_after_enospc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    _write_midi(src / "a.mid", b"payload-data")

    attempts = {"n": 0}
    real_copy = shutil.copy2

    def flaky(src_path: Path, dst_path: Path, *args: object, **kwargs: object) -> object:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy(src_path, dst_path, *args, **kwargs)

    monkeypatch.setattr("midi_parser.collect.shutil.copy2", flaky)

    stats = collect_midi(src, dest, space_poll_seconds=0.05)

    assert stats.copied == 1
    assert stats.space_pauses == 1
    assert attempts["n"] == 2
    assert (dest / "a.mid").read_bytes() == b"payload-data"


def test_collect_enospc_cancel_while_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "library"
    dest = tmp_path / "dump"
    _write_midi(src / "a.mid", b"x" * 100)

    def always_full(*_a: object, **_k: object) -> object:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("midi_parser.collect.shutil.copy2", always_full)
    monkeypatch.setattr("midi_parser.collect.disk_free_bytes", lambda _p: 0)

    ticks = {"n": 0}

    def cancel() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 8

    with pytest.raises(ScanCancelled):
        collect_midi(src, dest, should_cancel=cancel, space_poll_seconds=0.05)

    assert not any(dest.glob("*.mid"))
