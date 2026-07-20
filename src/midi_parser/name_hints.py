"""Filename / title hint classification (Pass 1)."""

from __future__ import annotations

import re
from pathlib import Path

# Check order: Drums → Bass → Arp → Chords → Lead
_HINTS: list[tuple[str, frozenset[str]]] = [
    (
        "Drums",
        frozenset(
            {
                "kick",
                "snare",
                "hat",
                "hh",
                "clap",
                "perc",
                "drum",
                "drums",
                "groove",
                "beat",
                "break",
                "rim",
                "tom",
            }
        ),
    ),
    ("Bass", frozenset({"ba", "bass", "sub", "808"})),
    ("Arp", frozenset({"arp", "arpeggio", "arpeg"})),
    (
        "Chords",
        frozenset({"ch", "chord", "chords", "pad", "piano", "comp"}),
    ),
    (
        "Lead",
        frozenset(
            {
                "ld",
                "lead",
                "mel",
                "melody",
                "keys",
                "key",
                "synth",
                "pluck",
                "solo",
            }
        ),
    ),
]

_SPLIT = re.compile(r"[\s_\-.]+")


def tokens_from_name(name: str) -> list[str]:
    """Split a filename stem into lowercase tokens."""
    stem = Path(name).stem if "." in name else name
    return [t for t in _SPLIT.split(stem.lower()) if t]


def category_from_name(filename: str) -> str | None:
    """
    Return a category if the filename contains a known hint token, else None.

    First matching category in Drums → Bass → Arp → Chords → Lead wins.
    """
    tokens = set(tokens_from_name(filename))
    if not tokens:
        return None
    for category, hints in _HINTS:
        if tokens & hints:
            return category
    return None
