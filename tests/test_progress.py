"""Tests for overall task progress mapping."""

from __future__ import annotations

from midi_parser.progress import overall_progress, phase_fraction, plan_phases


def test_scan_plan() -> None:
    phases = plan_phases("Scan", reuse_scan=False, remove_duplicates=False)
    assert abs(sum(w for _, w in phases) - 1.0) < 1e-9
    assert phases[0][0] == "discover"
    assert phases[-1][0] == "classify"


def test_copy_and_move_are_fast_collect() -> None:
    assert plan_phases("Copy", reuse_scan=True, remove_duplicates=False) == [
        ("collect", 1.0)
    ]
    assert plan_phases("Move", reuse_scan=False, remove_duplicates=True) == [
        ("collect", 1.0)
    ]


def test_parse_pipeline_advances_across_phases() -> None:
    phases = plan_phases("Parse", reuse_scan=False, remove_duplicates=False)
    discover = overall_progress(phases, "discover", 3000, 0)
    classify_start = overall_progress(phases, "classify", 0, 100, floor=discover)
    classify_mid = overall_progress(phases, "classify", 50, 100, floor=classify_start)
    transfer_end = overall_progress(phases, "transfer", 100, 100, floor=classify_mid)
    assert 0 < discover < 0.22
    assert classify_start >= discover
    assert classify_mid > classify_start
    assert transfer_end == 1.0


def test_collect_phase_maps_for_copy() -> None:
    phases = plan_phases("Copy", reuse_scan=False, remove_duplicates=False)
    mid = overall_progress(phases, "collect", 3000, 0)
    assert 0 < mid < 1.0


def test_phase_fraction_known_total() -> None:
    assert phase_fraction(25, 100) == 0.25
    assert phase_fraction(0, 0) == 0.0
