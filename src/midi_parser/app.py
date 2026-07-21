"""CustomTkinter desktop UI — Cupertino shell matching Midi Toolkit."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from midi_parser import CATEGORIES
from midi_parser.checkpoint import clear_checkpoint, load_checkpoint
from midi_parser.collect import CollectStats, collect_midi
from midi_parser.name_hints import category_from_name
from midi_parser.organize import (
    FileResult,
    ScanCancelled,
    classify_all,
    classify_with_checkpoint,
    count_by_category,
    duplicate_count,
    mark_duplicates,
    organize,
    total_size_bytes,
)
from midi_parser.scan import ProgressUpdate, start_full_computer_checkpoint
from midi_parser.theme import (
    BTN_H,
    COUNTS_W,
    KIND_COLORS,
    LIST_ROW_H,
    PAD,
    RADIUS_CHIP,
    RADIUS_CONTROL,
    RADIUS_CORNER,
    SIDEBAR_W,
    TOOLBAR_H,
    font,
    resolve_palette,
)
from midi_parser.util import format_duration, format_size


class MidiOrganizerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MIDI Organizer")
        self.geometry("1100x720")
        self.minsize(920, 600)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.pal = resolve_palette()
        self.configure(fg_color=self.pal.bg)

        self._results: list[FileResult] = []
        self._busy = False
        self._sources: list[str] = []
        self._cancel_event = threading.Event()
        self._discover_pulse = 0.05
        self._timer_start: float | None = None
        self._timer_job: str | None = None
        self._using_checkpoint = False

        self._build()
        self._style_tree()
        self._refresh_resume_button()

    # ── Shell ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        p = self.pal
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_body()
        self._build_status()

    def _build_toolbar(self) -> None:
        p = self.pal
        bar = ctk.CTkFrame(
            self,
            fg_color=p.chrome,
            height=TOOLBAR_H,
            corner_radius=0,
            border_width=0,
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        # Left: app name (Midi Toolkit style)
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=PAD, pady=10)
        ctk.CTkLabel(
            left,
            text="MIDI Organizer",
            font=font(13, bold=True),
            text_color=p.tx2,
        ).pack(side="left")
        ctk.CTkLabel(
            left,
            text="  ·  Toolkit",
            font=font(12),
            text_color=p.tx3,
        ).pack(side="left")

        # Center actions
        mid = ctk.CTkFrame(bar, fg_color="transparent")
        mid.grid(row=0, column=1, sticky="n", pady=11)

        self.scan_btn = self._primary_btn(mid, "Scan", self._on_scan, width=88)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.halt_btn = self._danger_btn(mid, "Halt", self._on_halt, width=72)
        self.halt_btn.pack(side="left", padx=(0, 6))
        self.halt_btn.configure(state="disabled")
        self.org_btn = self._secondary_btn(mid, "Organize", self._on_organize, width=96)
        self.org_btn.pack(side="left", padx=(0, 12))

        self.mode_var = tk.StringVar(value="copy")
        self.mode_seg = ctk.CTkSegmentedButton(
            mid,
            values=["Copy", "Move"],
            command=self._on_mode_change,
            height=BTN_H,
            font=font(11, bold=True),
            selected_color=p.acc,
            selected_hover_color=p.acc_hover,
            unselected_color=p.ctl,
            unselected_hover_color=p.hover,
            text_color=p.tx,
            fg_color=p.ctl,
            corner_radius=RADIUS_CHIP,
        )
        self.mode_seg.set("Copy")
        self.mode_seg.pack(side="left", padx=(0, 12))

        self.dry_run_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            mid,
            text="Dry run",
            variable=self.dry_run_var,
            font=font(11),
            text_color=p.tx2,
            fg_color=p.acc,
            hover_color=p.acc_hover,
            border_color=p.ctlb,
            checkmark_color=p.accent_ink,
            corner_radius=RADIUS_CONTROL,
            width=20,
            height=20,
        ).pack(side="left", padx=(0, 10))

        self.dedupe_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            mid,
            text="Remove duplicates",
            variable=self.dedupe_var,
            command=self._on_dedupe_toggle,
            font=font(11),
            text_color=p.tx2,
            fg_color=p.acc,
            hover_color=p.acc_hover,
            border_color=p.ctlb,
            checkmark_color=p.accent_ink,
            corner_radius=RADIUS_CONTROL,
            width=20,
            height=20,
        ).pack(side="left")

        # Right: timer
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=PAD)
        ctk.CTkLabel(
            right,
            text="ELAPSED",
            font=font(10, bold=True),
            text_color=p.tx3,
        ).pack(side="left", padx=(0, 8))
        self.timer_var = tk.StringVar(value="0:00")
        ctk.CTkLabel(
            right,
            textvariable=self.timer_var,
            font=font(13, bold=True),
            text_color=p.tx,
            width=64,
            anchor="e",
        ).pack(side="left")

        # Hairline under toolbar
        ctk.CTkFrame(self, fg_color=p.hl, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="sew"
        )

    def _build_body(self) -> None:
        p = self.pal
        body = ctk.CTkFrame(self, fg_color=p.bg, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_main(body)
        self._build_counts(body)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        side = ctk.CTkFrame(
            parent,
            fg_color=p.side,
            width=SIDEBAR_W,
            corner_radius=0,
            border_width=0,
        )
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(2, weight=1)

        # SOURCES section
        ctk.CTkLabel(
            side,
            text="SOURCES",
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 6))

        list_wrap = ctk.CTkFrame(
            side,
            fg_color=p.panel,
            corner_radius=RADIUS_CORNER,
            border_width=1,
            border_color=p.hl,
        )
        list_wrap.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0, 8))
        list_wrap.grid_columnconfigure(0, weight=1)

        self.source_list = tk.Listbox(
            list_wrap,
            height=8,
            activestyle="none",
            selectmode=tk.EXTENDED,
            exportselection=False,
            font=("SF Pro Text", 11),
            bg=p.panel,
            fg=p.tx,
            selectbackground=p.acc,
            selectforeground=p.accent_ink,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
        self.source_list.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        src_btns = ctk.CTkFrame(side, fg_color="transparent")
        src_btns.grid(row=2, column=0, sticky="new", padx=PAD)
        src_btns.grid_columnconfigure((0, 1), weight=1)

        self._ghost_btn(src_btns, "Add", self._add_source).grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4)
        )
        self._ghost_btn(src_btns, "Remove", self._remove_sources).grid(
            row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 4)
        )
        self._ghost_btn(src_btns, "Clear", self._clear_sources).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 4)
        )
        self.scan_computer_btn = self._secondary_btn(
            src_btns, "Scan Computer", self._on_scan_computer
        )
        self.scan_computer_btn.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))
        self.collect_btn = self._secondary_btn(
            src_btns, "Collect MIDI…", self._on_collect_midi
        )
        self.collect_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.resume_btn = self._secondary_btn(src_btns, "Resume Scan", self._on_resume_scan)
        self.resume_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.resume_btn.configure(state="disabled")

        # DESTINATION
        ctk.CTkFrame(side, fg_color=p.hl, height=1, corner_radius=0).grid(
            row=3, column=0, sticky="ew", padx=PAD, pady=(4, 8)
        )
        ctk.CTkLabel(
            side,
            text="DESTINATION",
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", padx=PAD, pady=(0, 6))

        dest_row = ctk.CTkFrame(side, fg_color="transparent")
        dest_row.grid(row=5, column=0, sticky="ew", padx=PAD, pady=(0, PAD))
        dest_row.grid_columnconfigure(0, weight=1)
        self.dest_var = tk.StringVar()
        self.dest_entry = ctk.CTkEntry(
            dest_row,
            textvariable=self.dest_var,
            height=BTN_H,
            font=font(11),
            fg_color=p.field,
            border_color=p.ctlb,
            text_color=p.tx,
            corner_radius=RADIUS_CORNER,
            placeholder_text="Choose folder…",
        )
        self.dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._ghost_btn(dest_row, "Browse", self._browse_dest, width=72).grid(row=0, column=1)

    def _build_main(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        main = ctk.CTkFrame(
            parent,
            fg_color=p.panel,
            corner_radius=0,
            border_width=0,
        )
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(main, fg_color=p.panel, height=36, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(10, 0))
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="RESULTS",
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.summary_var = tk.StringVar(value="0 files · 0 B")
        ctk.CTkLabel(
            header,
            textvariable=self.summary_var,
            font=font(12, bold=True),
            text_color=p.tx,
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        table_frame = ctk.CTkFrame(
            main,
            fg_color=p.panel,
            corner_radius=RADIUS_CORNER,
            border_width=1,
            border_color=p.hl,
        )
        table_frame.grid(row=1, column=0, sticky="nsew", padx=PAD, pady=(6, PAD))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        cols = ("filename", "category", "reason", "size", "relative")
        self.tree = ttk.Treeview(
            table_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("filename", text="Filename")
        self.tree.heading("category", text="Kind")
        self.tree.heading("reason", text="Reason")
        self.tree.heading("size", text="Size")
        self.tree.heading("relative", text="Path")
        self.tree.column("filename", width=200, stretch=True)
        self.tree.column("category", width=80, stretch=False, anchor="center")
        self.tree.column("reason", width=120, stretch=False)
        self.tree.column("size", width=72, stretch=False, anchor="e")
        self.tree.column("relative", width=280, stretch=True)

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        scroll.grid(row=0, column=1, sticky="ns", pady=1)

    def _build_counts(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        panel = ctk.CTkFrame(
            parent,
            fg_color=p.rollchrome,
            width=COUNTS_W,
            corner_radius=0,
            border_width=0,
        )
        panel.grid(row=0, column=2, sticky="nsw")
        panel.grid_propagate(False)

        # Hairline on left edge
        ctk.CTkFrame(panel, fg_color=p.hl, width=1, corner_radius=0).place(x=0, y=0, relheight=1)

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        ctk.CTkLabel(
            inner,
            text="COUNTS",
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        self.count_labels: dict[str, ctk.CTkLabel] = {}
        self.kind_dots: dict[str, ctk.CTkFrame] = {}
        for cat in CATEGORIES:
            row = ctk.CTkFrame(inner, fg_color="transparent", height=LIST_ROW_H)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            dot = ctk.CTkFrame(
                row,
                width=8,
                height=8,
                corner_radius=2,
                fg_color=KIND_COLORS.get(cat, p.tx3),
            )
            dot.pack(side="left", padx=(0, 8), pady=9)
            ctk.CTkLabel(
                row,
                text=cat,
                font=font(12),
                text_color=p.tx,
                anchor="w",
            ).pack(side="left")
            lbl = ctk.CTkLabel(
                row,
                text="0",
                font=font(12, bold=True),
                text_color=p.tx2,
                anchor="e",
            )
            lbl.pack(side="right")
            self.count_labels[cat] = lbl

        ctk.CTkFrame(inner, fg_color=p.hl, height=1, corner_radius=0).pack(
            fill="x", pady=(12, 10)
        )

        for label, attr, bold in (
            ("Total", "total_label", True),
            ("Size", "size_label", False),
            ("Duplicates", "dup_label", False),
        ):
            row = ctk.CTkFrame(inner, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row,
                text=label,
                font=font(12, bold=bold),
                text_color=p.tx if bold else p.tx2,
                anchor="w",
            ).pack(side="left")
            lbl = ctk.CTkLabel(
                row,
                text="0" if label != "Size" else "0 B",
                font=font(12, bold=bold),
                text_color=p.tx if bold else p.tx2,
                anchor="e",
            )
            lbl.pack(side="right")
            setattr(self, attr, lbl)

    def _build_status(self) -> None:
        p = self.pal
        bot = ctk.CTkFrame(self, fg_color=p.chrome, corner_radius=0, height=64)
        bot.grid(row=2, column=0, sticky="ew")
        bot.grid_propagate(False)
        bot.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(bot, fg_color=p.hl, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="ew"
        )

        inner = ctk.CTkFrame(bot, fg_color="transparent")
        inner.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(8, 8))
        inner.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(
            inner,
            height=6,
            corner_radius=3,
            progress_color=p.acc,
            fg_color=p.hl,
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)

        self.status_var = tk.StringVar(
            value="Add sources, Collect MIDI… (fast dump), or Scan to classify."
        )
        ctk.CTkLabel(
            inner,
            textvariable=self.status_var,
            font=font(11),
            text_color=p.tx2,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.detail_var = tk.StringVar(value="")
        ctk.CTkLabel(
            inner,
            textvariable=self.detail_var,
            font=font(10),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(1, 0))

    # ── Styled controls ──────────────────────────────────────────────────────

    def _primary_btn(self, parent, text, command, width=100):
        p = self.pal
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BTN_H,
            font=font(11, bold=True),
            fg_color=p.acc,
            hover_color=p.acc_hover,
            text_color=p.accent_ink,
            corner_radius=RADIUS_CHIP,
        )

    def _secondary_btn(self, parent, text, command, width=100):
        p = self.pal
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BTN_H,
            font=font(11, bold=True),
            fg_color=p.ctl,
            hover_color=p.hover,
            text_color=p.tx,
            border_width=1,
            border_color=p.ctlb,
            corner_radius=RADIUS_CHIP,
        )

    def _ghost_btn(self, parent, text, command, width=0):
        p = self.pal
        kwargs = {"width": width} if width else {}
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=BTN_H,
            font=font(11, bold=True),
            fg_color=p.ctl,
            hover_color=p.hover,
            text_color=p.tx2,
            border_width=1,
            border_color=p.ctlb,
            corner_radius=RADIUS_CHIP,
            **kwargs,
        )

    def _danger_btn(self, parent, text, command, width=80):
        p = self.pal
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BTN_H,
            font=font(11, bold=True),
            fg_color=p.danger,
            hover_color=p.danger_hover,
            text_color="#ffffff",
            corner_radius=RADIUS_CHIP,
        )

    def _style_tree(self) -> None:
        p = self.pal
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview",
            background=p.panel,
            fieldbackground=p.panel,
            foreground=p.tx,
            rowheight=LIST_ROW_H,
            font=("SF Pro Text", 12),
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Treeview.Heading",
            background=p.rollchrome,
            foreground=p.tx3,
            font=("SF Pro Text", 10, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", p.acc)],
            foreground=[("selected", p.accent_ink)],
        )
        style.map("Treeview.Heading", background=[("active", p.hover)])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ── Source / dest helpers ────────────────────────────────────────────────

    def _on_mode_change(self, value: str) -> None:
        self.mode_var.set(value.lower())

    def _sync_source_list(self) -> None:
        self.source_list.delete(0, tk.END)
        for path in self._sources:
            self.source_list.insert(tk.END, path)

    def _add_source(self) -> None:
        path = filedialog.askdirectory(title="Add source folder")
        if not path:
            return
        resolved = str(Path(path).expanduser().resolve())
        if resolved not in self._sources:
            self._sources.append(resolved)
            self._sync_source_list()
            self._results = []
            self.status_var.set(f"Added source ({len(self._sources)} total).")

    def _remove_sources(self) -> None:
        selected = list(self.source_list.curselection())
        if not selected:
            return
        for index in reversed(selected):
            del self._sources[index]
        self._sync_source_list()
        self._results = []
        self.status_var.set(f"{len(self._sources)} source folder(s).")

    def _clear_sources(self) -> None:
        self._sources.clear()
        self._sync_source_list()
        self._results = []
        self.status_var.set("Sources cleared.")

    def _browse_dest(self) -> None:
        path = filedialog.askdirectory(title="Select destination folder")
        if path:
            self.dest_var.set(path)

    def _refresh_resume_button(self) -> None:
        cp = load_checkpoint()
        can = bool(cp and cp.is_resumable() and not self._busy)
        self.resume_btn.configure(state="normal" if can else "disabled")
        if can and cp is not None:
            self.detail_var.set(
                f"Checkpoint: {cp.phase}, {len(cp.found):,} MIDI found, "
                f"{len(cp.classified):,} classified"
            )

    # ── Timer / busy ─────────────────────────────────────────────────────────

    def _start_timer(self) -> None:
        self._timer_start = time.monotonic()
        self.timer_var.set("0:00")
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
        self._tick_timer()

    def _tick_timer(self) -> None:
        if self._timer_start is None:
            return
        elapsed = time.monotonic() - self._timer_start
        self.timer_var.set(format_duration(elapsed))
        self._timer_job = self.after(250, self._tick_timer)

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        if self._timer_start is not None:
            elapsed = time.monotonic() - self._timer_start
            self.timer_var.set(format_duration(elapsed))
        self._timer_start = None

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.scan_btn.configure(state=state)
        self.org_btn.configure(state=state)
        self.scan_computer_btn.configure(state=state)
        self.collect_btn.configure(state=state)
        self.halt_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.resume_btn.configure(state="disabled")
            self._start_timer()
        else:
            self._stop_timer()
            self._refresh_resume_button()

    def _on_halt(self) -> None:
        if not self._busy:
            return
        self._cancel_event.set()
        self.status_var.set("Halting…")
        self.halt_btn.configure(state="disabled")

    def _update_progress(self, update: ProgressUpdate) -> None:
        def ui() -> None:
            if update.total and update.total > 0:
                self.progress.set(min(1.0, update.current / update.total))
            else:
                self._discover_pulse = 0.05 + ((self._discover_pulse + 0.03) % 0.35)
                self.progress.set(self._discover_pulse)
            self.status_var.set(update.message)
            detail = update.detail
            if len(detail) > 120:
                detail = "…" + detail[-119:]
            self.detail_var.set(detail)

        self.after(0, ui)

    def _fill_table(self, results: list[FileResult]) -> None:
        exclude = self.dedupe_var.get()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(results):
            reason = r.reason
            if r.is_duplicate and r.duplicate_of:
                reason = f"duplicate → {r.duplicate_of}"
            tag = "alt" if i % 2 else "base"
            self.tree.insert(
                "",
                "end",
                values=(
                    r.filename,
                    r.category,
                    reason,
                    format_size(r.size_bytes),
                    r.relative,
                ),
                tags=(tag, r.category),
            )
        p = self.pal
        self.tree.tag_configure("base", background=p.panel)
        self.tree.tag_configure("alt", background=p.rowalt)

        counts = count_by_category(results, exclude_duplicates=exclude)
        shown = [r for r in results if not (exclude and r.is_duplicate)]
        n_files = len(shown)
        size = total_size_bytes(results, exclude_duplicates=exclude)
        self.summary_var.set(f"{n_files:,} files · {format_size(size)}")
        for cat, lbl in self.count_labels.items():
            lbl.configure(text=str(counts.get(cat, 0)))
        self.total_label.configure(text=str(sum(counts.values())))
        self.size_label.configure(text=format_size(size))
        self.dup_label.configure(text=str(duplicate_count(results) if exclude else 0))

    def _on_dedupe_toggle(self) -> None:
        if not self._results or self._busy:
            return
        if self.dedupe_var.get():
            mark_duplicates(self._results)
        else:
            for result in self._results:
                if result.is_duplicate or result.reason == "duplicate":
                    result.is_duplicate = False
                    result.duplicate_of = None
                    hint = category_from_name(result.filename)
                    if hint is not None:
                        result.reason = "name"
                    elif result.category == "Unknown":
                        result.reason = "unknown"
                    else:
                        result.reason = "content"
        self._fill_table(self._results)
        dups = duplicate_count(self._results)
        if self.dedupe_var.get() and dups:
            kept = len(self._results) - dups
            self.status_var.set(
                f"{len(self._results)} file(s), {dups} duplicate(s) (will keep {kept})."
            )
        else:
            self.status_var.set(f"{len(self._results)} MIDI file(s).")

    def _begin_job(self, status: str, *, using_checkpoint: bool = False) -> None:
        self._cancel_event.clear()
        self._using_checkpoint = using_checkpoint
        self._set_busy(True)
        self._discover_pulse = 0.05
        self.status_var.set(status)
        self.detail_var.set("")
        self.progress.set(0)

    # ── Scan / organize (logic unchanged) ────────────────────────────────────

    def _on_scan(self) -> None:
        if self._busy:
            return
        if not self._sources:
            self.status_var.set("Add at least one source folder.")
            return
        missing = [p for p in self._sources if not Path(p).is_dir()]
        if missing:
            self.status_var.set(f"Invalid source: {missing[0]}")
            return

        if len(self._sources) == 1 and Path(self._sources[0]).resolve() == Path("/"):
            self._start_checkpoint_scan(resume=False)
            return

        self._begin_job("Scanning…")
        sources = list(self._sources)
        remove_duplicates = self.dedupe_var.get()

        def work() -> None:
            try:
                results = classify_all(
                    sources,
                    progress=self._update_progress,
                    remove_duplicates=remove_duplicates,
                    should_cancel=self._cancel_event.is_set,
                )
            except ScanCancelled:
                self.after(0, lambda: self._scan_done([], cancelled=True))
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self.after(0, lambda e=err: self._scan_done([], error=e))
                return
            self.after(0, lambda r=results: self._scan_done(r))

        threading.Thread(target=work, daemon=True).start()

    def _on_scan_computer(self) -> None:
        if self._busy:
            return
        existing = load_checkpoint()
        if existing and existing.is_resumable():
            resume = messagebox.askyesnocancel(
                "Checkpoint found",
                "A previous whole-computer scan can be resumed.\n\n"
                "Yes = Resume\nNo = Start fresh (overwrite checkpoint)\nCancel = Abort",
            )
            if resume is None:
                return
            if resume:
                self._start_checkpoint_scan(resume=True)
                return
        else:
            ok = messagebox.askokcancel(
                "Scan Computer",
                "Scan the entire computer from / and classify every MIDI file.\n\n"
                "This parses each file and can take many hours.\n"
                "For a fast dump into one folder, use Collect MIDI… instead.\n\n"
                "Progress is saved so you can Halt and Resume.",
            )
            if not ok:
                return
        self._start_checkpoint_scan(resume=False)

    def _on_collect_midi(self) -> None:
        if self._busy:
            return
        ok = messagebox.askokcancel(
            "Collect MIDI",
            "Copy all MIDI files from this computer (/) into one folder.\n\n"
            "Does not classify — walk + copy only (much faster).\n"
            "If the disk fills up, collect pauses and resumes when space is free "
            "(Halt to stop).\n"
            "Afterward, Add that folder as a source and Scan to sort.",
        )
        if not ok:
            return
        dest = filedialog.askdirectory(title="Choose folder to collect MIDI into")
        if not dest:
            return
        dest_resolved = str(Path(dest).expanduser().resolve())
        self._begin_job(f"Collecting MIDI into {dest_resolved}…")

        def work() -> None:
            try:
                stats = collect_midi(
                    "/",
                    dest_resolved,
                    progress=self._update_progress,
                    should_cancel=self._cancel_event.is_set,
                )
            except ScanCancelled:
                self.after(
                    0,
                    lambda: self._collect_done(None, cancelled=True, dest=dest_resolved),
                )
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self.after(
                    0,
                    lambda e=err: self._collect_done(None, error=e, dest=dest_resolved),
                )
                return
            self.after(
                0,
                lambda s=stats: self._collect_done(s, dest=dest_resolved),
            )

        threading.Thread(target=work, daemon=True).start()

    def _collect_done(
        self,
        stats: CollectStats | None,
        *,
        dest: str,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        self._set_busy(False)
        self.progress.set(0)
        elapsed = self.timer_var.get()
        if error:
            self.status_var.set(f"Collect failed: {error}")
            self.detail_var.set("")
            messagebox.showerror("Collect failed", error)
            return
        if cancelled:
            self.status_var.set(f"Collect halted.  ({elapsed})")
            self.detail_var.set(dest)
            return
        assert stats is not None
        msg = (
            f"Collected {stats.copied:,} MIDI "
            f"(found {stats.found:,}, skipped {stats.skipped:,}, "
            f"errors {stats.errors:,})  ({elapsed})"
        )
        self.status_var.set(msg)
        self.detail_var.set(dest)
        add = messagebox.askyesno(
            "Collect complete",
            f"{msg}\n\nDestination:\n{dest}\n\n"
            "Add this folder as a source so you can Scan and Organize?",
        )
        if add and dest not in self._sources:
            self._sources.append(dest)
            self._sync_source_list()
            self.status_var.set(f"{msg} — added as source.")

    def _on_resume_scan(self) -> None:
        if self._busy:
            return
        cp = load_checkpoint()
        if not cp or not cp.is_resumable():
            self.status_var.set("No resumable checkpoint found.")
            self._refresh_resume_button()
            return
        self._start_checkpoint_scan(resume=True)

    def _start_checkpoint_scan(self, *, resume: bool) -> None:
        if resume:
            cp = load_checkpoint()
            if not cp or not cp.is_resumable():
                self.status_var.set("No resumable checkpoint found.")
                return
        else:
            clear_checkpoint()
            cp = start_full_computer_checkpoint("/")

        if "/" not in self._sources:
            self._sources = ["/"]
            self._sync_source_list()

        self._begin_job(
            "Resuming whole-computer scan…" if resume else "Scanning whole computer from /…",
            using_checkpoint=True,
        )
        remove_duplicates = self.dedupe_var.get()

        def work() -> None:
            try:
                results = classify_with_checkpoint(
                    cp,
                    progress=self._update_progress,
                    remove_duplicates=remove_duplicates,
                    should_cancel=self._cancel_event.is_set,
                )
            except ScanCancelled:
                self.after(0, lambda: self._scan_done([], cancelled=True, checkpointed=True))
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self.after(
                    0,
                    lambda e=err: self._scan_done([], error=e, checkpointed=True),
                )
                return
            self.after(
                0,
                lambda r=results: self._scan_done(r, checkpointed=True, finished=True),
            )

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(
        self,
        results: list[FileResult],
        error: str | None = None,
        *,
        cancelled: bool = False,
        checkpointed: bool = False,
        finished: bool = False,
    ) -> None:
        self._set_busy(False)
        self._cancel_event.clear()
        elapsed = self.timer_var.get()
        if cancelled:
            msg = "Halted."
            if checkpointed or self._using_checkpoint:
                msg += " Progress saved — click Resume Scan to continue."
            self.status_var.set(f"{msg}  ({elapsed})")
            self.detail_var.set("")
            self.progress.set(0)
            self._refresh_resume_button()
            return
        if error:
            self.status_var.set(f"Scan failed: {error}  ({elapsed})")
            self.detail_var.set("")
            self.progress.set(0)
            self._refresh_resume_button()
            return
        self._results = results
        self._fill_table(results)
        self.progress.set(1)
        self.detail_var.set("")
        if finished:
            clear_checkpoint()
        dups = duplicate_count(results)
        n_src = len(self._sources)
        src_note = f" from {n_src} source(s)" if n_src > 1 else ""
        size = format_size(total_size_bytes(results, exclude_duplicates=self.dedupe_var.get()))
        if self.dedupe_var.get() and dups:
            kept = len(results) - dups
            self.status_var.set(
                f"Scan complete — {len(results):,} file(s){src_note}, "
                f"{dups} duplicate(s) (will keep {kept}), {size}  ({elapsed})"
            )
        else:
            self.status_var.set(
                f"Scan complete — {len(results):,} MIDI file(s){src_note}, "
                f"{size}  ({elapsed})"
            )
        self._refresh_resume_button()

    def _on_organize(self) -> None:
        if self._busy:
            return
        if not self._sources and not self._results:
            self.status_var.set("Add at least one source folder (or finish a scan).")
            return
        if self._sources:
            missing = [p for p in self._sources if not Path(p).is_dir()]
            if missing:
                self.status_var.set(f"Invalid source: {missing[0]}")
                return
        dest = self.dest_var.get().strip()
        if not dest:
            self.status_var.set("Choose a destination folder.")
            return
        dest_path = Path(dest)
        if not dest_path.exists():
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.status_var.set(f"Cannot create destination: {exc}")
                return
        if not dest_path.is_dir():
            self.status_var.set("Destination must be a folder.")
            return

        dry_run = self.dry_run_var.get()
        remove_duplicates = self.dedupe_var.get()
        mode = self.mode_var.get() if self.mode_var.get() in {"copy", "move"} else "copy"
        action = "Dry run" if dry_run else ("Moving" if mode == "move" else "Copying")
        self._begin_job(f"{action}…")
        sources = list(self._sources) if self._sources else ["/"]
        prior = list(self._results) if self._results else None

        def work() -> None:
            try:
                results, counts = organize(
                    sources,
                    dest,
                    dry_run=dry_run,
                    remove_duplicates=remove_duplicates,
                    mode=mode,  # type: ignore[arg-type]
                    results=prior,
                    progress=self._update_progress,
                    should_cancel=self._cancel_event.is_set,
                )
            except ScanCancelled:
                self.after(0, lambda: self._organize_done([], {}, cancelled=True))
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self.after(0, lambda e=err: self._organize_done([], {}, error=e))
                return
            self.after(
                0,
                lambda r=results, c=counts, d=dry_run, rd=remove_duplicates, m=mode: self._organize_done(
                    r,
                    c,
                    dry_run=d,
                    remove_duplicates=rd,
                    mode=m,
                ),
            )

        threading.Thread(target=work, daemon=True).start()

    def _organize_done(
        self,
        results: list[FileResult],
        counts: dict[str, int],
        *,
        dry_run: bool = False,
        remove_duplicates: bool = False,
        mode: str = "copy",
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        self._set_busy(False)
        self._cancel_event.clear()
        elapsed = self.timer_var.get()
        if cancelled:
            self.status_var.set(f"Halted.  ({elapsed})")
            self.detail_var.set("")
            self.progress.set(0)
            return
        if error:
            self.status_var.set(f"Organize failed: {error}  ({elapsed})")
            self.detail_var.set("")
            self.progress.set(0)
            return
        self._results = results
        self._fill_table(results)
        self.progress.set(1)
        self.detail_var.set("")
        parts = [f"{c}: {counts.get(c, 0)}" for c in CATEGORIES]
        if dry_run:
            verb = "Dry run"
        elif mode == "move":
            verb = "Moved"
        else:
            verb = "Copied"
        dups = duplicate_count(results) if remove_duplicates else 0
        dup_note = f"  |  Skipped duplicates: {dups}" if dups else ""
        size = format_size(total_size_bytes(results, exclude_duplicates=remove_duplicates))
        self.status_var.set(
            f"{verb} — {', '.join(parts)}  |  Total: {sum(counts.values())} "
            f"({size}){dup_note}  ({elapsed})"
        )


def run_app() -> None:
    app = MidiOrganizerApp()
    app.mainloop()
