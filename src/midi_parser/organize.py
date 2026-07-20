"""Classify MIDI files and copy them into category folders."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from midi_parser import CATEGORIES
from midi_parser.assess import assess_file
from midi_parser.name_hints import category_from_name
from midi_parser.scan import find_midi_files

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class FileResult:
    source: Path
    relative: str
    filename: str
    category: str
    reason: str  # "name" | "content" | "unknown" | "duplicate"
    dest: Path | None = None
    content_hash: str | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None  # relative path of the kept original


def file_content_hash(path: Path | str) -> str:
    """SHA-256 of file bytes (identical MIDI content → same hash)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_file(path: Path, source_root: Path) -> FileResult:
    """Classify one MIDI file using name hints then content assessment."""
    try:
        relative = str(path.relative_to(source_root))
    except ValueError:
        relative = path.name

    try:
        digest = file_content_hash(path)
    except OSError:
        digest = None

    hint = category_from_name(path.name)
    if hint is not None:
        return FileResult(
            source=path,
            relative=relative,
            filename=path.name,
            category=hint,
            reason="name",
            content_hash=digest,
        )

    category = assess_file(path)
    reason = "unknown" if category == "Unknown" else "content"
    return FileResult(
        source=path,
        relative=relative,
        filename=path.name,
        category=category,
        reason=reason,
        content_hash=digest,
    )


def mark_duplicates(results: list[FileResult]) -> list[FileResult]:
    """
    Mark later files with the same content hash as duplicates of the first.

    First occurrence (scan order) is kept. Duplicates keep their category for
    display but set is_duplicate / reason='duplicate'.
    """
    seen: dict[str, str] = {}  # hash → relative of keeper
    for result in results:
        # Reset prior marks so re-running is idempotent
        if result.reason == "duplicate":
            result.reason = "content"
        result.is_duplicate = False
        result.duplicate_of = None

        digest = result.content_hash
        if not digest:
            continue
        if digest in seen:
            result.is_duplicate = True
            result.duplicate_of = seen[digest]
            result.reason = "duplicate"
        else:
            seen[digest] = result.relative
    return results


def classify_all(
    source: Path | str,
    progress: ProgressCallback | None = None,
    *,
    remove_duplicates: bool = False,
) -> list[FileResult]:
    """Scan source and classify every MIDI file."""
    root = Path(source).expanduser().resolve()
    files = find_midi_files(root)
    results: list[FileResult] = []
    total = len(files)
    for i, path in enumerate(files, start=1):
        if progress:
            progress(i, total, path.name)
        results.append(classify_file(path, root))
    if remove_duplicates:
        mark_duplicates(results)
    return results


def count_by_category(
    results: list[FileResult],
    *,
    exclude_duplicates: bool = False,
) -> dict[str, int]:
    """Return counts for every category (including zeros)."""
    counts = {c: 0 for c in CATEGORIES}
    for r in results:
        if exclude_duplicates and r.is_duplicate:
            continue
        counts[r.category] = counts.get(r.category, 0) + 1
    return counts


def duplicate_count(results: list[FileResult]) -> int:
    return sum(1 for r in results if r.is_duplicate)


def _unique_dest(folder: Path, filename: str) -> Path:
    """Avoid overwriting: stem.mid, stem_1.mid, stem_2.mid, …"""
    dest = folder / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 1
    while True:
        candidate = folder / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def organize(
    source: Path | str,
    dest: Path | str,
    *,
    dry_run: bool = False,
    remove_duplicates: bool = False,
    results: list[FileResult] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[FileResult], dict[str, int]]:
    """
    Classify (if needed) and copy files into dest/<Category>/.

    When remove_duplicates is True, only the first file with a given content
    hash is copied; later duplicates are skipped.

    Returns (results with dest filled, counts of copied/kept files).
    """
    source_root = Path(source).expanduser().resolve()
    dest_root = Path(dest).expanduser().resolve()

    if results is None:
        results = classify_all(
            source_root,
            progress=progress,
            remove_duplicates=remove_duplicates,
        )
    elif remove_duplicates:
        mark_duplicates(results)
    else:
        for result in results:
            if not (result.is_duplicate or result.reason == "duplicate"):
                continue
            result.is_duplicate = False
            result.duplicate_of = None
            hint = category_from_name(result.filename)
            if hint is not None:
                result.reason = "name"
            elif result.category == "Unknown":
                result.reason = "unknown"
            else:
                result.reason = "content"

    if not dry_run:
        for category in CATEGORIES:
            (dest_root / category).mkdir(parents=True, exist_ok=True)

    total = len(results)
    for i, result in enumerate(results, start=1):
        if progress:
            progress(i, total, result.filename)

        if remove_duplicates and result.is_duplicate:
            result.dest = None
            continue

        folder = dest_root / result.category
        target = _unique_dest(folder, result.filename)
        result.dest = target
        if not dry_run:
            shutil.copy2(result.source, target)

    return results, count_by_category(results, exclude_duplicates=remove_duplicates)
