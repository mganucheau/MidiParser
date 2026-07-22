"""Persist UI session (sources, destination, task prefs) across launches."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

SESSION_VERSION = 1
DEFAULT_DIR = Path.home() / ".midi_parser"
DEFAULT_SESSION_PATH = DEFAULT_DIR / "session.json"


@dataclass
class SessionState:
    version: int = SESSION_VERSION
    sources: list[str] = field(default_factory=list)
    dest: str | None = None
    job: str = "Scan"
    remove_duplicates: bool = False


def session_dir() -> Path:
    override = os.environ.get("MIDI_PARSER_CHECKPOINT_DIR")
    return Path(override) if override else DEFAULT_DIR


def session_path() -> Path:
    override = os.environ.get("MIDI_PARSER_SESSION")
    return Path(override) if override else session_dir() / "session.json"


def load_session(path: Path | None = None) -> SessionState:
    target = path or session_path()
    if not target.is_file():
        return SessionState()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SessionState()
    if raw.get("version") != SESSION_VERSION:
        return SessionState()
    dest = raw.get("dest")
    return SessionState(
        version=SESSION_VERSION,
        sources=[str(s) for s in raw.get("sources", []) if s],
        dest=str(dest) if dest else None,
        job=str(raw.get("job") or "Scan"),
        remove_duplicates=bool(raw.get("remove_duplicates", False)),
    )


def save_session(state: SessionState, path: Path | None = None) -> None:
    target = path or session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    fd, tmp_name = tempfile.mkstemp(
        prefix="midi_session_", suffix=".json", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
