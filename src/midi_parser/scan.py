"""Recursive MIDI file discovery."""

from __future__ import annotations

from pathlib import Path

MIDI_SUFFIXES = {".mid", ".midi"}


def _normalize_roots(sources: Path | str | list[Path | str]) -> list[Path]:
    if isinstance(sources, (str, Path)):
        raw = [sources]
    else:
        raw = list(sources)
    roots: list[Path] = []
    seen: set[Path] = set()
    for item in raw:
        root = Path(item).expanduser().resolve()
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        roots.append(root)
    return roots


def find_midi_files(source: Path | str) -> list[Path]:
    """
    Recursively find .mid / .midi files under source.

    Skips hidden directories (names starting with '.').
    Returns paths sorted by relative path string.
    """
    return [path for path, _root, _rel in find_midi_files_with_roots(source)]


def find_midi_files_with_roots(
    sources: Path | str | list[Path | str],
) -> list[tuple[Path, Path, str]]:
    """
    Find MIDI files under one or more source roots.

    Returns list of (absolute_path, source_root, display_relative).
    With multiple roots, display_relative is ``RootName/relative/path``.
    """
    roots = _normalize_roots(sources)
    multi = len(roots) > 1
    found: list[tuple[Path, Path, str]] = []

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in MIDI_SUFFIXES:
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            rel_str = str(rel)
            if multi:
                display = f"{root.name}/{rel_str}"
            else:
                display = rel_str
            found.append((path, root, display))

    found.sort(key=lambda item: item[2].lower())
    return found
