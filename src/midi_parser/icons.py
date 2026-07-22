"""Stroke icons matching Midi Toolkit (UiAtoms Phosphor-style glyphs)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk


def _draw_icon(canvas: tk.Canvas, name: str, color: str, size: int = 16) -> None:
    canvas.delete("all")
    s = size * 0.38
    cx = size / 2
    cy = size / 2
    px = max(1.4, size * 0.09)

    if name == "folder":
        pts = [
            cx - s,
            cy + s * 0.7,
            cx - s,
            cy - s * 0.55,
            cx - s * 0.25,
            cy - s * 0.55,
            cx - s * 0.02,
            cy - s * 0.25,
            cx + s,
            cy - s * 0.25,
            cx + s,
            cy + s * 0.7,
        ]
        canvas.create_polygon(*pts, outline=color, fill="", width=px, joinstyle="round")
    elif name == "plus":
        canvas.create_line(
            cx - s * 0.85, cy, cx + s * 0.85, cy, fill=color, width=px, capstyle="round"
        )
        canvas.create_line(
            cx, cy - s * 0.85, cx, cy + s * 0.85, fill=color, width=px, capstyle="round"
        )
    elif name == "x":
        canvas.create_line(
            cx - s * 0.7,
            cy - s * 0.7,
            cx + s * 0.7,
            cy + s * 0.7,
            fill=color,
            width=px,
            capstyle="round",
        )
        canvas.create_line(
            cx - s * 0.7,
            cy + s * 0.7,
            cx + s * 0.7,
            cy - s * 0.7,
            fill=color,
            width=px,
            capstyle="round",
        )
    elif name == "more":
        d = s * 0.55
        gap = s * 1.05
        for i in (-1, 0, 1):
            canvas.create_oval(
                cx + i * gap - d * 0.5,
                cy - d * 0.5,
                cx + i * gap + d * 0.5,
                cy + d * 0.5,
                fill=color,
                outline="",
            )
    elif name == "sidebar-right":
        canvas.create_rectangle(
            cx - s,
            cy - s * 0.8,
            cx + s,
            cy + s * 0.8,
            outline=color,
            width=px,
        )
        x = cx + s * 0.3
        canvas.create_line(x, cy - s * 0.8, x, cy + s * 0.8, fill=color, width=px)
    else:
        canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=color, outline="")


class IconButton(ctk.CTkFrame):
    """Ghost icon button — Toolkit IconBtn (no pad/border when idle)."""

    def __init__(
        self,
        master,
        *,
        icon: str,
        command: Callable[[], None] | None = None,
        color: str,
        hover: str,
        bg: str,
        size: int = 28,
        glyph: int = 16,
    ) -> None:
        super().__init__(master, fg_color="transparent", width=size, height=size)
        self.grid_propagate(False)
        self._command = command
        self._color = color
        self._hover = hover
        self._glyph = glyph
        self._icon = icon
        self._bg = bg

        self._canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            highlightthickness=0,
            bd=0,
            bg=bg,
        )
        self._canvas.place(relx=0.5, rely=0.5, anchor="center")
        _draw_icon(self._canvas, icon, color, glyph)

        for w in (self, self._canvas):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def set_bg(self, color: str) -> None:
        self._bg = color
        self._canvas.configure(bg=color)

    def set_icon(self, icon: str, color: str | None = None) -> None:
        self._icon = icon
        if color:
            self._color = color
        _draw_icon(self._canvas, self._icon, self._color, self._glyph)

    def _click(self, _event=None) -> None:
        if self._command is not None:
            self._command()

    def _on_enter(self, _event=None) -> None:
        _draw_icon(self._canvas, self._icon, self._hover, self._glyph)

    def _on_leave(self, _event=None) -> None:
        _draw_icon(self._canvas, self._icon, self._color, self._glyph)


def section_label_text(title: str) -> str:
    """Letter-spaced uppercase like Midi Toolkit paintSectionLabel."""
    return " ".join(title.upper())


class MiniSwitch(ctk.CTkFrame):
    """Midi Toolkit MiniSwitch — caption · track · on/off (UiAtoms)."""

    def __init__(
        self,
        master,
        *,
        caption: str,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        bg: str,
        tx: str,
        tx2: str,
        tx3: str,
        acc: str,
        accent_ink: str,
        ctl: str,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._var = variable
        self._command = command
        self._bg = bg
        self._tx = tx
        self._tx2 = tx2
        self._tx3 = tx3
        self._acc = acc
        self._accent_ink = accent_ink
        self._ctl = ctl

        self.grid_columnconfigure(0, weight=1)

        self._cap = ctk.CTkLabel(
            self,
            text=caption,
            font=ctk.CTkFont(family="SF Pro Text", size=11),
            text_color=tx2,
            anchor="w",
        )
        self._cap.grid(row=0, column=0, sticky="w")
        self._cap.bind("<Button-1>", self._toggle)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")

        self._track = tk.Canvas(
            right, width=24, height=14, highlightthickness=0, bd=0, bg=bg
        )
        self._track.pack(side="left", padx=(7, 6))
        self._track.bind("<Button-1>", self._toggle)

        self._val = ctk.CTkLabel(
            right,
            text="off",
            font=ctk.CTkFont(family="SF Mono", size=11),
            text_color=tx3,
            anchor="w",
            width=24,
        )
        self._val.pack(side="left")
        self._val.bind("<Button-1>", self._toggle)

        self._var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _toggle(self, _event=None) -> None:
        self._var.set(not self._var.get())
        if self._command:
            self._command()

    def _paint(self) -> None:
        on = bool(self._var.get())
        self._track.delete("all")
        fill = self._acc if on else self._ctl
        self._track.create_oval(0, 0, 14, 14, fill=fill, outline="")
        self._track.create_oval(10, 0, 24, 14, fill=fill, outline="")
        self._track.create_rectangle(7, 0, 17, 14, fill=fill, outline="")
        kx = 12 if on else 2
        knob = self._accent_ink if on else "#ffffff"
        self._track.create_oval(kx, 2, kx + 10, 12, fill=knob, outline="")
        self._cap.configure(text_color=self._tx if on else self._tx2)
        self._val.configure(
            text="on" if on else "off",
            text_color=self._acc if on else self._tx3,
        )

    def set_bg(self, color: str) -> None:
        self._bg = color
        self._track.configure(bg=color)
