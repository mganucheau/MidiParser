"""Fast collect: copy MIDI files into one folder without classifying."""

from __future__ import annotations

import errno
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from midi_parser.scan import (
    MIDI_SUFFIXES,
    CancelCallback,
    ProgressCallback,
    ProgressUpdate,
    ScanCancelled,
    _SKIP_DIR_NAMES,
    _normalize_roots,
)
from midi_parser.util import format_size

TransferMode = Literal["copy", "move"]

# Extra headroom beyond the file size before treating disk as "enough space"
_SPACE_MARGIN = 64 * 1024

# Top-level dirs under / to skip (network mounts, system noise)
_SKIP_ROOT_DIR_NAMES = frozenset(
    {
        "Volumes",  # NAS / external — dominates runtime; skip by default
        "System",
        "private",
        "dev",
        "net",
        "home",  # macOS automount stub
        "cores",
    }
)


@dataclass
class CollectStats:
    """Totals from a collect pass."""

    walked: int = 0
    found: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0
    space_pauses: int = 0


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


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _is_no_space(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    code = getattr(exc, "errno", None)
    if code in (errno.ENOSPC, errno.EDQUOT):
        return True
    if exc.args and exc.args[0] in (errno.ENOSPC, errno.EDQUOT):
        return True
    msg = str(exc).lower()
    return "no space" in msg or "not enough space" in msg or "disk quota" in msg


def disk_free_bytes(path: Path) -> int:
    """Free bytes on the volume containing ``path`` (0 if unknown)."""
    try:
        st = os.statvfs(path)
        return int(st.f_bavail) * int(st.f_frsize)
    except OSError:
        return 0


def _file_size(path: Path) -> int:
    try:
        return max(0, path.stat().st_size)
    except OSError:
        return 0


def _cleanup_partial(target: Path) -> None:
    try:
        if target.is_file():
            target.unlink()
    except OSError:
        pass


def _wait_for_space(
    dest_root: Path,
    needed: int,
    *,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    poll_seconds: float = 2.0,
) -> None:
    """Block until ``dest_root`` has enough free bytes, or cancel."""
    need = max(needed, 1)
    while True:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        free = disk_free_bytes(dest_root)
        if free >= need:
            if progress:
                progress(
                    ProgressUpdate(
                        phase="collect",
                        message=(
                            f"Space available ({format_size(free)} free) — resuming…"
                        ),
                        detail=str(dest_root),
                    )
                )
            return
        if progress:
            progress(
                ProgressUpdate(
                    phase="collect_paused",
                    message=(
                        f"Paused — need {format_size(need)} free, "
                        f"have {format_size(free)}. Free space to resume "
                        f"(or Halt to stop)."
                    ),
                    current=0,
                    total=0,
                    detail=str(dest_root),
                )
            )
        slept = 0.0
        while slept < poll_seconds:
            if should_cancel and should_cancel():
                raise ScanCancelled()
            time.sleep(0.25)
            slept += 0.25


def _transfer_with_space_retry(
    src: Path,
    dest_root: Path,
    filename: str,
    *,
    mode: TransferMode,
    stats: CollectStats,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    poll_seconds: float,
) -> bool:
    """Copy or move ``src`` into ``dest_root``; pause/retry on disk full."""
    needed = _file_size(src) + _SPACE_MARGIN
    while True:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        target = _unique_dest(dest_root, filename)
        try:
            if mode == "move":
                shutil.move(str(src), str(target))
            else:
                shutil.copy2(src, target)
            return True
        except OSError as exc:
            _cleanup_partial(target)
            if not _is_no_space(exc):
                return False
            stats.space_pauses += 1
            _wait_for_space(
                dest_root,
                needed,
                progress=progress,
                should_cancel=should_cancel,
                poll_seconds=poll_seconds,
            )


def _filter_dirnames(
    dirpath: str,
    dirnames: list[str],
    *,
    dest_root: Path,
    skip_volumes: bool,
) -> None:
    """Mutate dirnames in-place for os.walk pruning."""
    at_fs_root = dirpath.rstrip("/") == "" or dirpath == "/"
    kept: list[str] = []
    for name in dirnames:
        if name.startswith(".") or name in _SKIP_DIR_NAMES:
            continue
        if skip_volumes and name == "Volumes":
            continue
        if skip_volumes and at_fs_root and name in _SKIP_ROOT_DIR_NAMES:
            continue
        child = Path(dirpath) / name
        try:
            if _is_under(child, dest_root) or child.resolve() == dest_root:
                continue
        except OSError:
            pass
        kept.append(name)
    dirnames[:] = kept


def collect_midi(
    roots: Path | str | list[Path | str],
    dest: Path | str,
    *,
    mode: TransferMode = "copy",
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    space_poll_seconds: float = 2.0,
    skip_volumes: bool = True,
) -> CollectStats:
    """
    Walk roots for ``.mid`` / ``.midi`` by extension and copy/move into ``dest``.

    No classification, no content hashing — extension match + transfer only.
    Collision-safe names. Skips ``/Volumes`` (and other noisy root dirs) by
    default. Does not walk into ``dest``.

    If the destination runs out of space, pauses until free space returns.
    """
    dest_root = Path(dest).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    walk_roots = _normalize_roots(roots)
    if not walk_roots:
        raise ValueError("No valid source roots to collect from")

    stats = CollectStats()
    last_report = 0
    dest_prefix = str(dest_root) + os.sep
    verb = "Moving" if mode == "move" else "Copying"
    done_verb = "moved" if mode == "move" else "copied"

    def report(detail: str) -> None:
        nonlocal last_report
        if not progress:
            return
        if last_report != 0 and stats.walked - last_report < 200:
            return
        last_report = stats.walked
        progress(
            ProgressUpdate(
                phase="collect",
                message=(
                    f"{verb}… walked {stats.walked:,} paths, "
                    f"found {stats.found:,}, {done_verb} {stats.copied:,}"
                ),
                current=stats.walked,
                total=0,
                detail=detail,
            )
        )

    for root in walk_roots:
        if progress:
            progress(
                ProgressUpdate(
                    phase="collect",
                    message=f"{verb} under {root}…",
                    detail=str(root),
                )
            )

        for dirpath, dirnames, filenames in os.walk(
            root,
            topdown=True,
            onerror=lambda _err: None,
            followlinks=False,
        ):
            if should_cancel and should_cancel():
                raise ScanCancelled()

            # Bail out if we somehow entered Volumes or dest
            if skip_volumes and (
                dirpath == "/Volumes" or dirpath.startswith("/Volumes/")
            ):
                dirnames.clear()
                continue
            if dirpath == str(dest_root) or dirpath.startswith(dest_prefix):
                dirnames.clear()
                continue

            _filter_dirnames(
                dirpath,
                dirnames,
                dest_root=dest_root,
                skip_volumes=skip_volumes,
            )

            stats.walked += 1 + len(filenames)
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
                    if not path.is_file() or path.is_symlink():
                        continue
                except OSError:
                    stats.errors += 1
                    continue

                stats.found += 1
                ok = _transfer_with_space_retry(
                    path,
                    dest_root,
                    name,
                    mode=mode,
                    stats=stats,
                    progress=progress,
                    should_cancel=should_cancel,
                    poll_seconds=space_poll_seconds,
                )
                if ok:
                    stats.copied += 1
                else:
                    stats.errors += 1

                if progress and stats.found % 25 == 0:
                    progress(
                        ProgressUpdate(
                            phase="collect",
                            message=(
                                f"{verb}… walked {stats.walked:,} paths, "
                                f"found {stats.found:,}, {done_verb} {stats.copied:,}"
                            ),
                            current=stats.walked,
                            total=0,
                            detail=str(path),
                        )
                    )

    if progress:
        progress(
            ProgressUpdate(
                phase="collect",
                message=(
                    f"Done — {done_verb} {stats.copied:,} of {stats.found:,} MIDI "
                    f"(errors {stats.errors:,})"
                ),
                current=stats.walked,
                total=max(stats.walked, 1),
                detail=str(dest_root),
            )
        )
    return stats
