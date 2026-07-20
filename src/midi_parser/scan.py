"""Recursive MIDI file discovery."""

from __future__ import annotations

from pathlib import Path

MIDI_SUFFIXES = {".mid", ".midi"}


def find_midi_files(source: Path | str) -> list[Path]:
    """
    Recursively find .mid / .midi files under source.

    Skips hidden directories (names starting with '.').
    Returns paths sorted by relative path string.
    """
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        return []

    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MIDI_SUFFIXES:
            continue
        # Skip anything under a hidden directory segment
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        found.append(path)

    found.sort(key=lambda p: str(p.relative_to(root)).lower())
    return found
