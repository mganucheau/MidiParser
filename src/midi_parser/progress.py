"""Overall task progress from multi-phase job updates."""

from __future__ import annotations

import math


PhasePlan = list[tuple[str, float]]


def plan_phases(
    job: str,
    *,
    reuse_scan: bool,
    remove_duplicates: bool,
) -> PhasePlan:
    """
    Return ordered (phase, weight) pairs that sum to 1.0 for the whole task.

    discover / classify / hash_dest / transfer cover Scan → Copy/Move/Parse/All.
    """
    if job == "Scan":
        return [("discover", 0.35), ("classify", 0.65)]

    if reuse_scan:
        if remove_duplicates:
            return [("hash_dest", 0.12), ("transfer", 0.88)]
        return [("transfer", 1.0)]

    # Full pipeline: discover + classify (+ optional dest hash) + transfer
    if remove_duplicates:
        return [
            ("discover", 0.18),
            ("classify", 0.32),
            ("hash_dest", 0.12),
            ("transfer", 0.38),
        ]
    return [
        ("discover", 0.22),
        ("classify", 0.38),
        ("transfer", 0.40),
    ]


def phase_fraction(current: int, total: int) -> float:
    """0–1 progress within a phase. total<=0 ⇒ asymptotic estimate from counts."""
    if total and total > 0:
        return max(0.0, min(1.0, current / total))
    if current <= 0:
        return 0.0
    # Discover walks an unknown tree — approach but never reach phase end.
    return min(0.97, 1.0 - math.exp(-current / 6000.0))


def normalize_phase(phase: str) -> str:
    if phase in {"collect", "collect_paused"}:
        return "transfer"
    return phase


def overall_progress(
    phases: PhasePlan,
    phase: str,
    current: int,
    total: int,
    *,
    floor: float = 0.0,
) -> float:
    """Map a phase update onto overall 0–1 progress (never below floor)."""
    if not phases:
        return max(floor, phase_fraction(current, total))

    phase = normalize_phase(phase)
    names = [name for name, _ in phases]
    if phase not in names:
        # Unknown / skipped phase — keep floor (monotonic caller handles this).
        return floor

    idx = names.index(phase)
    completed = sum(weight for _, weight in phases[:idx])
    weight = phases[idx][1]
    overall = completed + weight * phase_fraction(current, total)
    return max(floor, min(1.0, overall))
