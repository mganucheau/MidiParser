"""Crash-safe checkpoint for whole-computer MIDI scans."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_VERSION = 1
DEFAULT_DIR = Path.home() / ".midi_parser"
DEFAULT_CHECKPOINT_PATH = DEFAULT_DIR / "full_scan_checkpoint.json"
DEFAULT_COMPLETED_PATH = DEFAULT_DIR / "full_scan_completed.txt"


@dataclass
class FoundEntry:
    path: str
    relative: str
    root: str
    size_bytes: int = 0


@dataclass
class ClassifiedEntry:
    source: str
    relative: str
    filename: str
    category: str
    reason: str
    content_hash: str | None = None
    size_bytes: int = 0


@dataclass
class ScanCheckpoint:
    version: int = CHECKPOINT_VERSION
    root: str = "/"
    phase: str = "discover"  # discover | classify | done
    pending_dirs: list[str] = field(default_factory=list)
    found: list[FoundEntry] = field(default_factory=list)
    classified: list[ClassifiedEntry] = field(default_factory=list)
    walked: int = 0
    started_at: str = ""
    updated_at: str = ""
    # In-memory only (loaded from append log)
    completed_dirs: set[str] = field(default_factory=set, repr=False)

    def is_resumable(self) -> bool:
        return self.phase in {"discover", "classify"} and (
            bool(self.pending_dirs) or bool(self.found) or bool(self.classified)
        )


def checkpoint_dir() -> Path:
    override = os.environ.get("MIDI_PARSER_CHECKPOINT_DIR")
    return Path(override) if override else DEFAULT_DIR


def checkpoint_path() -> Path:
    override = os.environ.get("MIDI_PARSER_CHECKPOINT")
    return Path(override) if override else checkpoint_dir() / "full_scan_checkpoint.json"


def completed_path() -> Path:
    return checkpoint_dir() / "full_scan_completed.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_checkpoint(root: str | Path = "/") -> ScanCheckpoint:
    root_s = str(Path(root).resolve())
    return ScanCheckpoint(
        root=root_s,
        phase="discover",
        pending_dirs=[root_s],
        found=[],
        classified=[],
        walked=0,
        started_at=_now(),
        updated_at=_now(),
        completed_dirs=set(),
    )


def load_checkpoint(path: Path | None = None) -> ScanCheckpoint | None:
    target = path or checkpoint_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("version") != CHECKPOINT_VERSION:
        return None
    found = [FoundEntry(**e) for e in raw.get("found", [])]
    classified = [ClassifiedEntry(**e) for e in raw.get("classified", [])]
    completed: set[str] = set()
    comp = completed_path()
    if comp.is_file():
        try:
            for line in comp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    completed.add(line)
        except OSError:
            pass
    cp = ScanCheckpoint(
        version=CHECKPOINT_VERSION,
        root=raw.get("root", "/"),
        phase=raw.get("phase", "discover"),
        pending_dirs=list(raw.get("pending_dirs", [])),
        found=found,
        classified=classified,
        walked=int(raw.get("walked", 0)),
        started_at=raw.get("started_at", ""),
        updated_at=raw.get("updated_at", ""),
        completed_dirs=completed,
    )
    return cp if cp.is_resumable() or cp.phase == "done" else None


def save_checkpoint(
    cp: ScanCheckpoint,
    path: Path | None = None,
    *,
    new_completed: list[str] | None = None,
) -> None:
    target = path or checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    cp.updated_at = _now()
    payload = {
        "version": cp.version,
        "root": cp.root,
        "phase": cp.phase,
        "pending_dirs": cp.pending_dirs,
        "found": [asdict(e) for e in cp.found],
        "classified": [asdict(e) for e in cp.classified],
        "walked": cp.walked,
        "started_at": cp.started_at,
        "updated_at": cp.updated_at,
    }
    fd, tmp_name = tempfile.mkstemp(prefix="midi_scan_", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    if new_completed:
        comp = completed_path()
        with comp.open("a", encoding="utf-8") as f:
            for d in new_completed:
                f.write(d + "\n")
            f.flush()
            os.fsync(f.fileno())


def clear_checkpoint(path: Path | None = None) -> None:
    target = path or checkpoint_path()
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        completed_path().unlink(missing_ok=True)
    except OSError:
        pass
