"""Recursive MIDI file discovery."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from midi_parser.checkpoint import (
    FoundEntry,
    ScanCheckpoint,
    new_checkpoint,
    save_checkpoint,
)

MIDI_SUFFIXES = {".mid", ".midi"}
CancelCallback = Callable[[], bool]

# Directory names to skip while walking (keeps root/home scans from stalling forever)
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".Trash",
        ".Spotlight-V100",
        ".fseventsd",
        ".DocumentRevisions-V100",
        ".TemporaryItems",
        "node_modules",
        "__pycache__",
        "Pods",
        "DerivedData",
        "Caches",
        "cache",
        "Cache",
    }
)


class ScanCancelled(Exception):
    """Raised when a scan or organize operation is halted by the user."""


@dataclass
class ProgressUpdate:
    """Live progress for UI status / progress bar."""

    phase: str  # discover | classify | hash_dest | transfer
    message: str
    current: int = 0
    total: int = 0  # 0 => indeterminate
    detail: str = ""


ProgressCallback = Callable[[ProgressUpdate], None]


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


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def find_midi_files(source: Path | str) -> list[Path]:
    """
    Recursively find .mid / .midi files under source.

    Skips hidden directories (names starting with '.').
    Returns paths sorted by relative path string.
    """
    return [path for path, _root, _rel in find_midi_files_with_roots(source)]


def find_midi_files_with_roots(
    sources: Path | str | list[Path | str],
    *,
    should_cancel: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
) -> list[tuple[Path, Path, str]]:
    """
    Find MIDI files under one or more source roots.

    Returns list of (absolute_path, source_root, display_relative).
    With multiple roots, display_relative is ``RootName/relative/path``.

    Raises ScanCancelled if should_cancel returns True mid-walk.
    """
    roots = _normalize_roots(sources)
    multi = len(roots) > 1
    found: list[tuple[Path, Path, str]] = []
    walked = 0
    last_report = 0

    def report(detail: str) -> None:
        nonlocal last_report
        if not progress:
            return
        if last_report != 0 and walked - last_report < 200:
            return
        last_report = walked
        progress(
            ProgressUpdate(
                phase="discover",
                message=(
                    f"Discovering… walked {walked:,} paths, "
                    f"found {len(found):,} MIDI"
                ),
                current=walked,
                total=0,
                detail=detail,
            )
        )

    for root in roots:
        if progress:
            progress(
                ProgressUpdate(
                    phase="discover",
                    message=f"Discovering under {root}…",
                    detail=str(root),
                )
            )

        for dirpath, dirnames, filenames in os.walk(
            root,
            topdown=True,
            onerror=lambda err: None,
            followlinks=False,
        ):
            if should_cancel and should_cancel():
                raise ScanCancelled()

            kept: list[str] = []
            for name in dirnames:
                if name.startswith("."):
                    continue
                if name in _SKIP_DIR_NAMES:
                    continue
                kept.append(name)
            dirnames[:] = kept

            walked += 1 + len(filenames)
            report(dirpath)

            try:
                current = Path(dirpath)
                rel_dir = current.relative_to(root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel_dir.parts):
                dirnames.clear()
                continue

            for name in filenames:
                if should_cancel and should_cancel():
                    raise ScanCancelled()
                suffix = Path(name).suffix.lower()
                if suffix not in MIDI_SUFFIXES:
                    continue
                path = current / name
                try:
                    if not path.is_file():
                        continue
                except OSError:
                    continue
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    continue
                rel_str = str(rel)
                display = f"{root.name}/{rel_str}" if multi else rel_str
                found.append((path, root, display))

    if progress:
        progress(
            ProgressUpdate(
                phase="discover",
                message=f"Discovery done — {len(found):,} MIDI in {walked:,} paths",
                current=walked,
                total=0,
                detail="",
            )
        )

    found.sort(key=lambda item: item[2].lower())
    return found


def discover_with_checkpoint(
    checkpoint: ScanCheckpoint,
    *,
    should_cancel: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
    save_every: int = 100,
) -> ScanCheckpoint:
    """
    Resumable discovery using an explicit directory stack + checkpoint file.

    Mutates and periodically saves ``checkpoint``. Sets phase to ``classify``
    when discovery finishes.
    """
    root = Path(checkpoint.root)
    completed = set(checkpoint.completed_dirs)
    pending = list(checkpoint.pending_dirs)
    if not pending and checkpoint.phase == "discover":
        pending = [str(root)]
        checkpoint.pending_dirs = pending

    found_paths = {e.path for e in checkpoint.found}
    dirs_since_save = 0
    batch_completed: list[str] = []
    last_report_walked = checkpoint.walked

    def report(detail: str) -> None:
        nonlocal last_report_walked
        if not progress:
            return
        if (
            last_report_walked != 0
            and checkpoint.walked - last_report_walked < 200
            and dirs_since_save != 0
        ):
            return
        last_report_walked = checkpoint.walked
        progress(
            ProgressUpdate(
                phase="discover",
                message=(
                    f"Discovering… walked {checkpoint.walked:,} paths, "
                    f"found {len(checkpoint.found):,} MIDI "
                    f"(pending dirs {len(pending):,})"
                ),
                current=checkpoint.walked,
                total=0,
                detail=detail,
            )
        )

    while pending:
        if should_cancel and should_cancel():
            checkpoint.pending_dirs = pending
            save_checkpoint(checkpoint, new_completed=batch_completed)
            raise ScanCancelled()

        dirpath = pending.pop()
        if dirpath in completed:
            continue

        try:
            with os.scandir(dirpath) as it:
                entries = list(it)
        except OSError:
            completed.add(dirpath)
            batch_completed.append(dirpath)
            continue

        child_dirs: list[str] = []
        file_count = 0
        for entry in entries:
            try:
                name = entry.name
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if name.startswith(".") or name in _SKIP_DIR_NAMES:
                        continue
                    child = str(Path(dirpath) / name)
                    if child not in completed:
                        child_dirs.append(child)
                elif entry.is_file(follow_symlinks=False):
                    file_count += 1
                    suffix = Path(name).suffix.lower()
                    if suffix not in MIDI_SUFFIXES:
                        continue
                    path = Path(dirpath) / name
                    try:
                        path_s = str(path.resolve())
                    except OSError:
                        path_s = str(path)
                    if path_s in found_paths:
                        continue
                    try:
                        rel = str(path.relative_to(root))
                    except ValueError:
                        rel = name
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = _file_size(path)
                    checkpoint.found.append(
                        FoundEntry(
                            path=path_s,
                            relative=rel,
                            root=str(root),
                            size_bytes=size,
                        )
                    )
                    found_paths.add(path_s)
            except OSError:
                continue

        pending.extend(reversed(child_dirs))
        completed.add(dirpath)
        batch_completed.append(dirpath)
        checkpoint.walked += 1 + file_count
        dirs_since_save += 1
        report(dirpath)

        if dirs_since_save >= save_every:
            checkpoint.pending_dirs = pending
            save_checkpoint(checkpoint, new_completed=batch_completed)
            batch_completed = []
            dirs_since_save = 0

    checkpoint.pending_dirs = []
    checkpoint.phase = "classify"
    checkpoint.found.sort(key=lambda e: e.relative.lower())
    save_checkpoint(checkpoint, new_completed=batch_completed)

    if progress:
        progress(
            ProgressUpdate(
                phase="discover",
                message=(
                    f"Discovery done — {len(checkpoint.found):,} MIDI "
                    f"in {checkpoint.walked:,} paths"
                ),
                current=checkpoint.walked,
                total=0,
                detail="",
            )
        )
    return checkpoint


def start_full_computer_checkpoint(root: str | Path = "/") -> ScanCheckpoint:
    """Create a fresh whole-computer scan checkpoint."""
    cp = new_checkpoint(root)
    save_checkpoint(cp)
    return cp
