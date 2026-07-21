"""Fast collect: copy MIDI files into one folder without classifying."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

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

# Extra headroom beyond the file size before treating disk as "enough space"
_SPACE_MARGIN = 64 * 1024


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


def _content_hash(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _dest_hashes(dest_root: Path) -> set[str]:
    """SHA-256 digests of MIDI already in the dump folder (for re-run skip)."""
    seen: set[str] = set()
    try:
        for entry in dest_root.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in MIDI_SUFFIXES:
                continue
            digest = _content_hash(entry)
            if digest:
                seen.add(digest)
    except OSError:
        pass
    return seen


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
    # Some platforms put errno only on args
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
    """
    Block until ``dest_root`` has at least ``needed`` free bytes, or cancel.

    Raises ScanCancelled if should_cancel becomes true.
    """
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
        # Short sleeps so Halt stays responsive
        slept = 0.0
        while slept < poll_seconds:
            if should_cancel and should_cancel():
                raise ScanCancelled()
            time.sleep(0.25)
            slept += 0.25


def _copy_with_space_retry(
    src: Path,
    dest_root: Path,
    filename: str,
    *,
    stats: CollectStats,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    poll_seconds: float,
) -> bool:
    """
    Copy ``src`` into ``dest_root`` with collision-safe naming.

    On disk-full, pauses until space returns and retries the same file.
    Returns True if copied, False if a non-space error occurred.
    """
    needed = _file_size(src) + _SPACE_MARGIN
    while True:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        target = _unique_dest(dest_root, filename)
        try:
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


def collect_midi(
    roots: Path | str | list[Path | str],
    dest: Path | str,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    space_poll_seconds: float = 2.0,
) -> CollectStats:
    """
    Walk roots for .mid / .midi and copy each into ``dest`` (flat folder).

    No classification or MIDI parsing. Collision-safe names; skips when dest
    already holds identical content (SHA-256). Does not walk into ``dest``.

    If the destination volume runs out of space, the collect **pauses** and
    automatically **resumes** when enough free space is available (Halt cancels).
    """
    dest_root = Path(dest).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    walk_roots = _normalize_roots(roots)
    if not walk_roots:
        raise ValueError("No valid source roots to collect from")

    stats = CollectStats()
    last_report = 0
    known_hashes = _dest_hashes(dest_root)

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
                    f"Collecting… walked {stats.walked:,} paths, "
                    f"found {stats.found:,}, copied {stats.copied:,}"
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
                    message=f"Collecting under {root}…",
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

            kept: list[str] = []
            for name in dirnames:
                if name.startswith(".") or name in _SKIP_DIR_NAMES:
                    continue
                child = Path(dirpath) / name
                try:
                    if _is_under(child, dest_root) or child.resolve() == dest_root:
                        continue
                except OSError:
                    pass
                kept.append(name)
            dirnames[:] = kept

            stats.walked += 1 + len(filenames)
            report(dirpath)

            try:
                current = Path(dirpath)
                if _is_under(current, dest_root) or current.resolve() == dest_root:
                    dirnames.clear()
                    continue
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
                    resolved = path.resolve()
                    if resolved == dest_root or _is_under(resolved, dest_root):
                        continue
                except OSError:
                    stats.errors += 1
                    continue

                stats.found += 1
                digest = _content_hash(path)
                if digest and digest in known_hashes:
                    stats.skipped += 1
                    continue

                ok = _copy_with_space_retry(
                    path,
                    dest_root,
                    name,
                    stats=stats,
                    progress=progress,
                    should_cancel=should_cancel,
                    poll_seconds=space_poll_seconds,
                )
                if ok:
                    stats.copied += 1
                    if digest:
                        known_hashes.add(digest)
                else:
                    stats.errors += 1

                if progress and stats.found % 25 == 0:
                    progress(
                        ProgressUpdate(
                            phase="collect",
                            message=(
                                f"Collecting… walked {stats.walked:,} paths, "
                                f"found {stats.found:,}, copied {stats.copied:,}"
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
                    f"Collect done — copied {stats.copied:,} of {stats.found:,} MIDI "
                    f"(skipped {stats.skipped:,}, errors {stats.errors:,})"
                ),
                current=stats.walked,
                total=0,
                detail=str(dest_root),
            )
        )
    return stats
