"""Classify MIDI files and copy/move them into category folders."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from midi_parser import CATEGORIES
from midi_parser.assess import assess_file
from midi_parser.name_hints import category_from_name
from midi_parser.scan import find_midi_files_with_roots

ProgressCallback = Callable[[int, int, str], None]
TransferMode = Literal["copy", "move"]


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


def classify_file(
    path: Path,
    *,
    relative: str | None = None,
    source_root: Path | None = None,
) -> FileResult:
    """Classify one MIDI file using name hints then content assessment."""
    if relative is None:
        if source_root is not None:
            try:
                relative = str(path.relative_to(source_root))
            except ValueError:
                relative = path.name
        else:
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


def mark_duplicates(
    results: list[FileResult],
    *,
    existing_hashes: dict[str, str] | None = None,
) -> list[FileResult]:
    """
    Mark later files with the same content hash as duplicates of the first.

    ``existing_hashes`` maps content hash → label for files already in the
    destination (so a new session won't re-add the same content).
    """
    seen: dict[str, str] = dict(existing_hashes or {})
    for result in results:
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
    sources: Path | str | list[Path | str],
    progress: ProgressCallback | None = None,
    *,
    remove_duplicates: bool = False,
) -> list[FileResult]:
    """Scan one or more source roots and classify every MIDI file."""
    entries = find_midi_files_with_roots(sources)
    results: list[FileResult] = []
    total = len(entries)
    for i, (path, _root, relative) in enumerate(entries, start=1):
        if progress:
            progress(i, total, path.name)
        results.append(classify_file(path, relative=relative))
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


def _ensure_category_dirs(dest_root: Path, categories: Iterable[str]) -> None:
    """Create only missing category folders; never wipe existing ones."""
    for category in categories:
        folder = dest_root / category
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)


def existing_dest_hashes(dest_root: Path) -> dict[str, str]:
    """
    Hash MIDI files already in dest category folders.

    Used so Remove duplicates skips content already present from a prior session.
    """
    hashes: dict[str, str] = {}
    root = Path(dest_root)
    if not root.is_dir():
        return hashes
    for category in CATEGORIES:
        folder = root / category
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".mid", ".midi"}:
                continue
            try:
                digest = file_content_hash(path)
            except OSError:
                continue
            if digest not in hashes:
                rel = f"{category}/{path.name}"
                hashes[digest] = rel
    return hashes


def _clear_duplicate_marks(results: list[FileResult]) -> None:
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


def _transfer(src: Path, dest: Path, mode: TransferMode) -> None:
    if mode == "move":
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(src, dest)


def organize(
    sources: Path | str | list[Path | str],
    dest: Path | str,
    *,
    dry_run: bool = False,
    remove_duplicates: bool = False,
    mode: TransferMode = "copy",
    results: list[FileResult] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[FileResult], dict[str, int]]:
    """
    Classify (if needed) and copy/move files into dest/<Category>/.

    Existing destination category folders are reused (only missing ones are
    created). Never deletes destination contents.

    When remove_duplicates is True, skips content already in the destination
    and later source duplicates with the same hash.
    """
    dest_root = Path(dest).expanduser().resolve()

    if results is None:
        results = classify_all(
            sources,
            progress=progress,
            remove_duplicates=False,
        )

    existing = existing_dest_hashes(dest_root) if remove_duplicates else {}
    if remove_duplicates:
        mark_duplicates(results, existing_hashes=existing)
    else:
        _clear_duplicate_marks(results)

    needed = {r.category for r in results if not (remove_duplicates and r.is_duplicate)}
    if not dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)
        _ensure_category_dirs(dest_root, needed)

    total = len(results)
    for i, result in enumerate(results, start=1):
        if progress:
            progress(i, total, result.filename)

        if remove_duplicates and result.is_duplicate:
            result.dest = None
            continue

        folder = dest_root / result.category
        if dry_run and not folder.exists():
            # Preview path without creating folders
            target = folder / result.filename
            if target.exists():
                target = _unique_dest(folder, result.filename)
            result.dest = target
            continue

        if not dry_run:
            folder.mkdir(parents=True, exist_ok=True)
        target = _unique_dest(folder, result.filename)
        result.dest = target
        if not dry_run:
            _transfer(result.source, target, mode)

    return results, count_by_category(results, exclude_duplicates=remove_duplicates)
