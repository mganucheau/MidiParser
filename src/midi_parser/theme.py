"""Cupertino design tokens mirrored from Midi Toolkit (MidiBrowser DesignSystem)."""

from __future__ import annotations

from dataclasses import dataclass

# Kind chip colours (same in light/dark) — MidiBrowser DesignSystem.cpp
KIND_COLORS = {
    "Drums": "#4a9df5",
    "Bass": "#a35ce8",
    "Lead": "#18b8a5",  # keys/melody
    "Chords": "#18b8a5",
    "Arp": "#f0842c",  # perc-adjacent warm accent
    "Unknown": "#727278",
}


@dataclass(frozen=True)
class Palette:
    bg: str
    chrome: str
    side: str
    panel: str
    rollchrome: str
    hl: str
    tx: str
    tx2: str
    tx3: str
    acc: str
    acc_hover: str
    selsoft: str
    ctl: str
    ctlb: str
    field: str
    rowalt: str
    note: str
    stron: str
    winbrd: str
    hover: str
    danger: str
    danger_hover: str
    accent_ink: str


LIGHT = Palette(
    bg="#ececee",
    chrome="#e9e8ea",
    side="#e2e1e6",
    panel="#f9f9fa",
    rollchrome="#f2f2f4",
    hl="#d0d0d4",
    tx="#141416",
    tx2="#48484e",
    tx3="#727278",
    acc="#0068e0",
    acc_hover="#0056bf",
    selsoft="#d6e7fb",
    ctl="#ffffff",
    ctlb="#ccccd0",
    field="#ffffff",
    rowalt="#f0f0f2",
    note="#1f7ef2",
    stron="#e0a800",
    winbrd="#c8c8cc",
    hover="#e8e8ea",
    danger="#8B3A3A",
    danger_hover="#6E2E2E",
    accent_ink="#ffffff",
)

DARK = Palette(
    bg="#28282b",
    chrome="#333336",
    side="#2b2b2f",
    panel="#1f1f22",
    rollchrome="#232326",
    hl="#3a3a40",
    tx="#f2f2f5",
    tx2="#b3b3ba",
    tx3="#7d7d85",
    acc="#0a84ff",
    acc_hover="#409cff",
    selsoft="#1a3a5c",
    ctl="#3b3b40",
    ctlb="#4a4a50",
    field="#2e2e32",
    rowalt="#252528",
    note="#3f9bff",
    stron="#f5b400",
    winbrd="#404045",
    hover="#323236",
    danger="#8B3A3A",
    danger_hover="#6E2E2E",
    accent_ink="#28282b",
)

# Metrics from MidiBrowser Theme / DesignSystem
TOOLBAR_H = 52
SIDEBAR_W = 220
COUNTS_W = 188
PAD = 12
GRID = 8
RADIUS_CORNER = 10
RADIUS_CHIP = 6
RADIUS_CONTROL = 5
BTN_H = 28
LIST_ROW_H = 26

FONT_UI = ("SF Pro Text", "Helvetica Neue", "Avenir Next", "Segoe UI")
FONT_DISPLAY = ("SF Pro Display", "SF Pro Text", "Helvetica Neue", "Segoe UI")


def font(size: float, *, bold: bool = False):
    """Return a CTkFont using the Midi Toolkit SF Pro stack."""
    import customtkinter as ctk

    family = FONT_DISPLAY[0] if size >= 20 else FONT_UI[0]
    return ctk.CTkFont(
        family=family,
        size=int(round(size)),
        weight="bold" if bold else "normal",
    )


def resolve_palette(appearance: str | None = None) -> Palette:
    """appearance: 'light' | 'dark' | 'system' | None."""
    import customtkinter as ctk

    mode = appearance or ctk.get_appearance_mode()
    if mode == "System":
        # customtkinter reports Light/Dark after resolution via get_appearance_mode
        # which may still say System — fall back to light Cupertino default
        try:
            import darkdetect

            mode = "Dark" if darkdetect.isDark() else "Light"
        except Exception:
            mode = "Light"
    return DARK if str(mode).lower().startswith("dark") else LIGHT
