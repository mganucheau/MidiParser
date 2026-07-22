"""Tests for transfer job checkpoints."""

from __future__ import annotations

from pathlib import Path

from midi_parser.job_checkpoint import (
    clear_job_checkpoint,
    file_result_from_dict,
    file_result_to_dict,
    load_job_checkpoint,
    new_job_checkpoint,
    save_job_checkpoint,
)
from midi_parser.organize import FileResult


def test_job_checkpoint_roundtrip(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "job.json"
    monkeypatch.setenv("MIDI_PARSER_JOB_CHECKPOINT", str(path))

    results = [
        FileResult(
            source=Path("/src/a.mid"),
            relative="a.mid",
            filename="a.mid",
            category="Drums",
            reason="name",
            size_bytes=12,
        )
    ]
    cp = new_job_checkpoint(
        job="Move",
        transfer_mode="move",
        sources=["/src"],
        dest="/dest",
        remove_duplicates=False,
        results=results,
        transferred=[],
    )
    save_job_checkpoint(cp, path)
    loaded = load_job_checkpoint(path)
    assert loaded is not None
    assert loaded.job == "Move"
    assert loaded.transfer_mode == "move"
    assert len(loaded.results) == 1
    restored = file_result_from_dict(loaded.results[0])
    assert restored.filename == "a.mid"
    assert restored.category == "Drums"
    assert file_result_to_dict(restored)["source"] == "/src/a.mid"

    clear_job_checkpoint(path)
    assert load_job_checkpoint(path) is None
