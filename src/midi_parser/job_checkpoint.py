"""Crash-safe checkpoint for Copy / Move / Parse transfer jobs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from midi_parser.organize import FileResult

JOB_CHECKPOINT_VERSION = 1
DEFAULT_DIR = Path.home() / ".midi_parser"
DEFAULT_JOB_CHECKPOINT_PATH = DEFAULT_DIR / "job_checkpoint.json"


@dataclass
class JobCheckpoint:
    version: int = JOB_CHECKPOINT_VERSION
    job: str = "Copy"  # Copy | Move | Parse | All
    transfer_mode: str = "copy"  # copy | move
    sources: list[str] = field(default_factory=list)
    dest: str = ""
    remove_duplicates: bool = False
    results: list[dict] = field(default_factory=list)
    transferred: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""

    def is_resumable(self) -> bool:
        if self.job not in {"Copy", "Move", "Parse", "All"}:
            return False
        if not self.sources or not self.dest or not self.results:
            return False
        # Incomplete if some files still need transfer (transferred can be empty
        # if cancelled right as transfer began).
        return True


def job_checkpoint_dir() -> Path:
    override = os.environ.get("MIDI_PARSER_CHECKPOINT_DIR")
    return Path(override) if override else DEFAULT_DIR


def job_checkpoint_path() -> Path:
    override = os.environ.get("MIDI_PARSER_JOB_CHECKPOINT")
    return Path(override) if override else job_checkpoint_dir() / "job_checkpoint.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_result_to_dict(r: FileResult) -> dict:
    return {
        "source": str(r.source),
        "relative": r.relative,
        "filename": r.filename,
        "category": r.category,
        "reason": r.reason,
        "dest": str(r.dest) if r.dest is not None else None,
        "content_hash": r.content_hash,
        "is_duplicate": r.is_duplicate,
        "duplicate_of": r.duplicate_of,
        "size_bytes": r.size_bytes,
    }


def file_result_from_dict(d: dict) -> FileResult:
    dest = d.get("dest")
    return FileResult(
        source=Path(d["source"]),
        relative=d["relative"],
        filename=d["filename"],
        category=d["category"],
        reason=d["reason"],
        dest=Path(dest) if dest else None,
        content_hash=d.get("content_hash"),
        is_duplicate=bool(d.get("is_duplicate", False)),
        duplicate_of=d.get("duplicate_of"),
        size_bytes=int(d.get("size_bytes", 0)),
    )


def new_job_checkpoint(
    *,
    job: str,
    transfer_mode: str,
    sources: list[str],
    dest: str,
    remove_duplicates: bool,
    results: list[FileResult],
    transferred: list[str] | None = None,
) -> JobCheckpoint:
    return JobCheckpoint(
        version=JOB_CHECKPOINT_VERSION,
        job=job,
        transfer_mode=transfer_mode,
        sources=list(sources),
        dest=dest,
        remove_duplicates=remove_duplicates,
        results=[file_result_to_dict(r) for r in results],
        transferred=list(transferred or []),
        started_at=_now(),
        updated_at=_now(),
    )


def load_job_checkpoint(path: Path | None = None) -> JobCheckpoint | None:
    target = path or job_checkpoint_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("version") != JOB_CHECKPOINT_VERSION:
        return None
    cp = JobCheckpoint(
        version=JOB_CHECKPOINT_VERSION,
        job=str(raw.get("job", "")),
        transfer_mode=str(raw.get("transfer_mode", "copy")),
        sources=list(raw.get("sources", [])),
        dest=str(raw.get("dest", "")),
        remove_duplicates=bool(raw.get("remove_duplicates", False)),
        results=list(raw.get("results", [])),
        transferred=list(raw.get("transferred", [])),
        started_at=str(raw.get("started_at", "")),
        updated_at=str(raw.get("updated_at", "")),
    )
    return cp if cp.is_resumable() else None


def save_job_checkpoint(cp: JobCheckpoint, path: Path | None = None) -> None:
    target = path or job_checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    cp.updated_at = _now()
    payload = asdict(cp)
    fd, tmp_name = tempfile.mkstemp(
        prefix="midi_job_", suffix=".json", dir=str(target.parent)
    )
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


def clear_job_checkpoint(path: Path | None = None) -> None:
    target = path or job_checkpoint_path()
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass
