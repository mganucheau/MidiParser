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
from midi_parser.checkpoint import (
    ClassifiedEntry,
    ScanCheckpoint,
    save_checkpoint,
)
from midi_parser.scan import (
    ProgressCallback,
    ProgressUpdate,
    ScanCancelled,
    discover_with_checkpoint,
    find_midi_files_with_roots,
)

CancelCallback = Callable[[], bool]
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
    size_bytes: int = 0


def file_content_hash(path: Path | str) -> str:
    """SHA-256 of file bytes (identical MIDI content → same hash)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def classify_file(
    path: Path,
    *,
    relative: str | None = None,
    source_root: Path | None = None,
    size_bytes: int | None = None,
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

    size = size_bytes if size_bytes is not None else _file_size(path)

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
            size_bytes=size,
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
        size_bytes=size,
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
    should_cancel: CancelCallback | None = None,
) -> list[FileResult]:
    """Scan one or more source roots and classify every MIDI file.

    Raises ScanCancelled if should_cancel returns True.
    """
    entries = find_midi_files_with_roots(
        sources,
        should_cancel=should_cancel,
        progress=progress,
    )
    results: list[FileResult] = []
    total = len(entries)
    for i, (path, _root, relative) in enumerate(entries, start=1):
        if should_cancel and should_cancel():
            raise ScanCancelled()
        if progress:
            progress(
                ProgressUpdate(
                    phase="classify",
                    message=f"Classifying {i:,} / {total:,}",
                    current=i,
                    total=total,
                    detail=str(path),
                )
            )
        results.append(classify_file(path, relative=relative))
    if remove_duplicates:
        mark_duplicates(results)
    return results


def _results_from_classified(entries: list[ClassifiedEntry]) -> list[FileResult]:
    return [
        FileResult(
            source=Path(e.source),
            relative=e.relative,
            filename=e.filename,
            category=e.category,
            reason=e.reason,
            content_hash=e.content_hash,
            size_bytes=e.size_bytes,
        )
        for e in entries
    ]


def classify_with_checkpoint(
    checkpoint: ScanCheckpoint,
    progress: ProgressCallback | None = None,
    *,
    remove_duplicates: bool = False,
    should_cancel: CancelCallback | None = None,
    save_every: int = 25,
) -> list[FileResult]:
    """
    Full-computer scan: resume discovery then classify, checkpointing as it goes.
    """
    if checkpoint.phase == "discover":
        discover_with_checkpoint(
            checkpoint,
            should_cancel=should_cancel,
            progress=progress,
        )

    done_paths = {e.source for e in checkpoint.classified}
    results = _results_from_classified(checkpoint.classified)
    pending = [e for e in checkpoint.found if e.path not in done_paths]
    total = len(checkpoint.found)
    done = len(results)
    since_save = 0

    for entry in pending:
        if should_cancel and should_cancel():
            save_checkpoint(checkpoint)
            raise ScanCancelled()

        done += 1
        path = Path(entry.path)
        if progress:
            progress(
                ProgressUpdate(
                    phase="classify",
                    message=f"Classifying {done:,} / {total:,}",
                    current=done,
                    total=max(total, 1),
                    detail=entry.path,
                )
            )
        result = classify_file(
            path,
            relative=entry.relative,
            size_bytes=entry.size_bytes,
        )
        results.append(result)
        checkpoint.classified.append(
            ClassifiedEntry(
                source=str(result.source),
                relative=result.relative,
                filename=result.filename,
                category=result.category,
                reason=result.reason,
                content_hash=result.content_hash,
                size_bytes=result.size_bytes,
            )
        )
        since_save += 1
        if since_save >= save_every:
            save_checkpoint(checkpoint)
            since_save = 0

    checkpoint.phase = "done"
    save_checkpoint(checkpoint)

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


def total_size_bytes(
    results: list[FileResult],
    *,
    exclude_duplicates: bool = False,
) -> int:
    total = 0
    for r in results:
        if exclude_duplicates and r.is_duplicate:
            continue
        total += r.size_bytes
    return total


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


def existing_dest_hashes(
    dest_root: Path,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> dict[str, str]:
    """
    Hash MIDI files already in dest category folders.

    Used so Remove duplicates skips content already present from a prior session.
    """
    hashes: dict[str, str] = {}
    root = Path(dest_root)
    if not root.is_dir():
        return hashes
    n = 0
    for category in CATEGORIES:
        folder = root / category
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if should_cancel and should_cancel():
                raise ScanCancelled()
            if not path.is_file() or path.suffix.lower() not in {".mid", ".midi"}:
                continue
            n += 1
            if progress and n % 25 == 0:
                progress(
                    ProgressUpdate(
                        phase="hash_dest",
                        message=f"Checking existing library… {n:,} files",
                        current=n,
                        total=0,
                        detail=str(path),
                    )
                )
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
    should_cancel: CancelCallback | None = None,
) -> tuple[list[FileResult], dict[str, int]]:
    """
    Classify (if needed) and copy/move files into dest/<Category>/.

    Existing destination category folders are reused (only missing ones are
    created). Never deletes destination contents.

    When remove_duplicates is True, skips content already in the destination
    and later source duplicates with the same hash.

    Raises ScanCancelled if should_cancel returns True.
    """
    dest_root = Path(dest).expanduser().resolve()

    if results is None:
        results = classify_all(
            sources,
            progress=progress,
            remove_duplicates=False,
            should_cancel=should_cancel,
        )

    existing = (
        existing_dest_hashes(
            dest_root,
            progress=progress,
            should_cancel=should_cancel,
        )
        if remove_duplicates
        else {}
    )
    if remove_duplicates:
        mark_duplicates(results, existing_hashes=existing)
    else:
        _clear_duplicate_marks(results)

    needed = {r.category for r in results if not (remove_duplicates and r.is_duplicate)}
    if not dry_run:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        dest_root.mkdir(parents=True, exist_ok=True)
        _ensure_category_dirs(dest_root, needed)

    total = len(results)
    transferred = 0
    for i, result in enumerate(results, start=1):
        if should_cancel and should_cancel():
            raise ScanCancelled()

        if remove_duplicates and result.is_duplicate:
            result.dest = None
            if progress:
                progress(
                    ProgressUpdate(
                        phase="transfer",
                        message=f"Transfer {i:,} / {total:,} (skip duplicate)",
                        current=i,
                        total=total,
                        detail=result.relative,
                    )
                )
            continue

        folder = dest_root / result.category
        if dry_run and not folder.exists():
            target = folder / result.filename
            if target.exists():
                target = _unique_dest(folder, result.filename)
            result.dest = target
            if progress:
                progress(
                    ProgressUpdate(
                        phase="transfer",
                        message=f"Dry run {i:,} / {total:,}",
                        current=i,
                        total=total,
                        detail=result.relative,
                    )
                )
            continue

        if not dry_run:
            folder.mkdir(parents=True, exist_ok=True)
        target = _unique_dest(folder, result.filename)
        result.dest = target
        if not dry_run:
            _transfer(result.source, target, mode)
            transferred += 1
        if progress:
            verb = "Moving" if mode == "move" else "Copying"
            if dry_run:
                verb = "Dry run"
            progress(
                ProgressUpdate(
                    phase="transfer",
                    message=f"{verb} {i:,} / {total:,}",
                    current=i,
                    total=total,
                    detail=str(target),
                )
            )

    return results, count_by_category(results, exclude_duplicates=remove_duplicates)
