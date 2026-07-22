"""CustomTkinter desktop UI — Midi Toolkit Cupertino shell."""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from midi_parser import CATEGORIES
from midi_parser.icons import IconButton, MiniSwitch, section_label_text
from midi_parser.job_checkpoint import (
    JobCheckpoint,
    clear_job_checkpoint,
    file_result_from_dict,
    file_result_to_dict,
    load_job_checkpoint,
    new_job_checkpoint,
    save_job_checkpoint,
)
from midi_parser.name_hints import category_from_name
from midi_parser.organize import (
    FileResult,
    ScanCancelled,
    classify_all,
    count_by_category,
    duplicate_count,
    mark_duplicates,
    organize,
    total_size_bytes,
)
from midi_parser.progress import PhasePlan, overall_progress, plan_phases
from midi_parser.scan import ProgressUpdate
from midi_parser.session import SessionState, load_session, save_session
from midi_parser.theme import (
    BODY_PAD_T,
    COUNTS_W,
    DANGER,
    HEADER_TO_ROWS,
    ICON_COL,
    KIND_COLORS,
    LIST_HEADER_H,
    LIST_ROW_H,
    PAD,
    PAD_V,
    PATH_ROW_H,
    RADIUS_CHIP,
    ROW_ICON_GAP,
    ROW_PAD_X,
    SECTION_GAP,
    SIDEBAR_ROW_H,
    SIDEBAR_SECTION_H,
    SIDEBAR_W,
    TOOLBAR_H,
    font,
    resolve_palette,
)
from midi_parser.util import format_duration, format_size

log = logging.getLogger(__name__)

JOB_MODES = ("Scan", "Copy", "Move", "Parse", "All")
TRANSFER_JOBS = frozenset({"Copy", "Move", "Parse", "All"})
# Treeview dies / freezes on huge inserts — show a capped preview.
MAX_TABLE_ROWS = 2_500
PROGRESS_UI_MIN_INTERVAL = 0.08  # seconds between coalesced UI paints


class MidiOrganizerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MIDI Organizer")
        self.geometry("1120x740")
        self.minsize(900, 580)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.pal = resolve_palette()
        self.configure(fg_color=self.pal.bg)

        self._results: list[FileResult] = []
        self._busy = False
        self._sources: list[str] = []
        self._dest: str | None = None
        self._cancel_event = threading.Event()
        self._discover_pulse = 0.05
        self._timer_start: float | None = None
        self._timer_job: str | None = None
        self._counts_open = True
        self._active_job: str | None = None
        self._job_cp: JobCheckpoint | None = None
        self._transferred: list[str] = []
        self._transfer_save_every = 50
        self._progress_current = 0
        self._progress_total = 0
        self._overall_ratio = 0.0
        self._job_phases: PhasePlan = []
        self._pending_resume: JobCheckpoint | None = None
        self._progress_lock = threading.Lock()
        self._latest_progress: ProgressUpdate | None = None
        self._progress_flush_scheduled = False
        self._last_progress_paint = 0.0

        self._build()
        self._style_tree()
        self._restore_session()
        self._refresh_path_lists()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_resume_button()

    # ── Shell ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_body()
        self._build_status()

    def _build_toolbar(self) -> None:
        """Chrome: title + counts sidebar toggle (elapsed lives in status)."""
        p = self.pal
        bar = ctk.CTkFrame(self, fg_color=p.chrome, height=TOOLBAR_H, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(
            bar,
            text="MIDI Organizer",
            font=font(13, bold=True),
            text_color=p.tx2,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD)

        self.counts_toggle = IconButton(
            bar,
            icon="sidebar-right",
            command=self._toggle_counts,
            color=p.tx2,
            hover=p.acc,
            bg=p.chrome,
            size=28,
            glyph=16,
        )
        self.counts_toggle.grid(row=0, column=1, sticky="e", padx=PAD)

        ctk.CTkFrame(self, fg_color=p.hl, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="sew"
        )

    def _build_body(self) -> None:
        p = self.pal
        self.body = ctk.CTkFrame(self, fg_color=p.bg, corner_radius=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(1, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self._build_sidebar(self.body)
        self._build_main(self.body)
        self._build_counts(self.body)

    def _section_header(self, parent, title: str, on_add) -> ctk.CTkFrame:
        p = self.pal
        head = ctk.CTkFrame(parent, fg_color="transparent", height=SIDEBAR_SECTION_H + 6)
        head.grid_propagate(False)
        head.grid_columnconfigure(0, weight=1)
        head.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text=section_label_text(title),
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        btn = IconButton(
            head,
            icon="plus",
            command=on_add,
            color=p.acc,
            hover=p.acc_hover,
            bg=p.side,
            size=22,
            glyph=14,
        )
        btn.grid(row=0, column=1, sticky="e")
        return head

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        side = ctk.CTkFrame(parent, fg_color=p.side, width=SIDEBAR_W, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(9, weight=1)

        ctk.CTkFrame(side, fg_color=p.ctlb, width=1, corner_radius=0).place(
            relx=1.0, x=-1, y=0, relheight=1
        )

        pad = PAD

        src_head = self._section_header(side, "Sources", self._add_source)
        src_head.grid(
            row=0, column=0, sticky="ew", padx=pad, pady=(BODY_PAD_T, HEADER_TO_ROWS)
        )

        self.sources_list = ctk.CTkFrame(side, fg_color="transparent")
        self.sources_list.grid(
            row=1, column=0, sticky="ew", padx=pad - ROW_PAD_X, pady=(0, SECTION_GAP)
        )
        self.sources_list.grid_columnconfigure(0, weight=1)

        dest_head = self._section_header(side, "Destination", self._add_destination)
        dest_head.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, HEADER_TO_ROWS))

        self.dest_list = ctk.CTkFrame(side, fg_color="transparent")
        self.dest_list.grid(
            row=3, column=0, sticky="ew", padx=pad - ROW_PAD_X, pady=(0, SECTION_GAP)
        )
        self.dest_list.grid_columnconfigure(0, weight=1)

        task_head = ctk.CTkFrame(side, fg_color="transparent", height=SIDEBAR_SECTION_H)
        task_head.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, HEADER_TO_ROWS))
        task_head.grid_propagate(False)
        ctk.CTkLabel(
            task_head,
            text=section_label_text("Task"),
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).pack(side="left")

        self.job_var = tk.StringVar(value="Scan")
        self.job_menu = ctk.CTkOptionMenu(
            side,
            values=list(JOB_MODES),
            variable=self.job_var,
            command=self._on_job_changed,
            height=30,
            font=font(12),
            dropdown_font=font(12),
            fg_color=p.ctl,
            button_color=p.ctl,
            button_hover_color=p.hover,
            text_color=p.tx,
            dropdown_fg_color=p.ctl,
            dropdown_hover_color=p.hover,
            dropdown_text_color=p.tx,
            corner_radius=RADIUS_CHIP,
            anchor="w",
        )
        self.job_menu.grid(row=5, column=0, sticky="ew", padx=pad, pady=(0, SECTION_GAP))

        self.dedupe_var = tk.BooleanVar(value=False)
        self.dedupe_switch = MiniSwitch(
            side,
            caption="Remove duplicates",
            variable=self.dedupe_var,
            command=self._on_dedupe_toggle,
            bg=p.side,
            tx=p.tx,
            tx2=p.tx2,
            tx3=p.tx3,
            acc=p.acc,
            accent_ink=p.accent_ink,
            ctl=p.ctlb,
        )
        self.dedupe_switch.grid(
            row=6, column=0, sticky="ew", padx=pad, pady=(0, SECTION_GAP)
        )

        actions = ctk.CTkFrame(side, fg_color="transparent")
        actions.grid(row=7, column=0, sticky="ew", padx=pad, pady=(0, 6))
        actions.grid_columnconfigure((0, 1), weight=1)

        self.start_btn = ctk.CTkButton(
            actions,
            text="Start",
            command=self._on_start,
            height=30,
            font=font(12, bold=True),
            fg_color=p.ctl,
            hover_color=p.hover,
            text_color=p.tx,
            border_width=1,
            border_color=p.ctlb,
            corner_radius=7,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.stop_btn = ctk.CTkButton(
            actions,
            text="Stop",
            command=self._on_halt,
            height=30,
            font=font(12, bold=True),
            fg_color=p.ctl,
            hover_color=p.hover,
            text_color=p.tx2,
            border_width=1,
            border_color=p.ctlb,
            corner_radius=7,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.resume_btn = ctk.CTkButton(
            side,
            text="Resume",
            command=self._on_resume,
            height=30,
            font=font(12, bold=True),
            fg_color=p.acc,
            hover_color=p.acc_hover,
            text_color=p.accent_ink,
            corner_radius=7,
        )
        self.resume_btn.grid(row=8, column=0, sticky="ew", padx=pad, pady=(0, PAD_V))
        self.resume_btn.grid_remove()

    def _build_main(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        main = ctk.CTkFrame(parent, fg_color=p.panel, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(main, fg_color=p.rollchrome, height=LIST_HEADER_H, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)
        header.grid_rowconfigure(0, weight=1)
        ctk.CTkFrame(header, fg_color=p.hl, height=1, corner_radius=0).place(
            relx=0, rely=1.0, relwidth=1, y=-1
        )

        ctk.CTkLabel(
            header,
            text="RESULTS",
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD)
        self.summary_var = tk.StringVar(value="0 files · 0 B")
        ctk.CTkLabel(
            header,
            textvariable=self.summary_var,
            font=font(11, bold=True),
            text_color=p.tx2,
            anchor="e",
        ).grid(row=0, column=2, sticky="e", padx=PAD)

        table_frame = ctk.CTkFrame(main, fg_color=p.panel, corner_radius=0)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        cols = ("filename", "category", "size", "relative")
        self.tree = ttk.Treeview(
            table_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("filename", text="Name")
        self.tree.heading("category", text="Kind")
        self.tree.heading("size", text="Size")
        self.tree.heading("relative", text="Path")
        self.tree.column("filename", width=240, stretch=True)
        self.tree.column("category", width=88, stretch=False, anchor="w")
        self.tree.column("size", width=72, stretch=False, anchor="e")
        self.tree.column("relative", width=300, stretch=True)

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _build_counts(self, parent: ctk.CTkFrame) -> None:
        p = self.pal
        self.counts_panel = ctk.CTkFrame(
            parent, fg_color=p.rollchrome, width=COUNTS_W, corner_radius=0
        )
        self.counts_panel.grid(row=0, column=2, sticky="nsw")
        self.counts_panel.grid_propagate(False)
        ctk.CTkFrame(self.counts_panel, fg_color=p.hl, width=1, corner_radius=0).place(
            x=0, y=0, relheight=1
        )

        inner = ctk.CTkFrame(self.counts_panel, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=PAD, pady=BODY_PAD_T)

        ctk.CTkLabel(
            inner,
            text=section_label_text("Counts"),
            font=font(10, bold=True),
            text_color=p.tx3,
            anchor="w",
        ).pack(fill="x", pady=(0, HEADER_TO_ROWS + 4))

        self.count_labels: dict[str, ctk.CTkLabel] = {}
        for cat in CATEGORIES:
            row = ctk.CTkFrame(inner, fg_color="transparent", height=SIDEBAR_ROW_H)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)
            chip = ctk.CTkFrame(
                row,
                width=7,
                height=7,
                corner_radius=2,
                fg_color=KIND_COLORS.get(cat, p.tx3),
            )
            chip.pack(side="left", padx=(ROW_PAD_X, 8), pady=11)
            ctk.CTkLabel(row, text=cat, font=font(12), text_color=p.tx, anchor="w").pack(
                side="left"
            )
            lbl = ctk.CTkLabel(
                row, text="0", font=font(12, bold=True), text_color=p.tx2, anchor="e"
            )
            lbl.pack(side="right", padx=(0, ROW_PAD_X))
            self.count_labels[cat] = lbl

        ctk.CTkFrame(inner, fg_color=p.hl, height=1, corner_radius=0).pack(
            fill="x", pady=(SECTION_GAP, 10)
        )
        for label, attr, bold in (
            ("Total", "total_label", True),
            ("Size", "size_label", False),
            ("Duplicates", "dup_label", False),
        ):
            row = ctk.CTkFrame(inner, fg_color="transparent", height=SIDEBAR_ROW_H - 4)
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                row,
                text=label,
                font=font(12, bold=bold),
                text_color=p.tx if bold else p.tx2,
                anchor="w",
            ).pack(side="left", padx=(ROW_PAD_X, 0))
            lbl = ctk.CTkLabel(
                row,
                text="0" if label != "Size" else "0 B",
                font=font(12, bold=bold),
                text_color=p.tx if bold else p.tx2,
                anchor="e",
            )
            lbl.pack(side="right", padx=(0, ROW_PAD_X))
            setattr(self, attr, lbl)

    def _build_status(self) -> None:
        p = self.pal
        bot = ctk.CTkFrame(self, fg_color=p.chrome, corner_radius=0, height=88)
        bot.grid(row=2, column=0, sticky="ew")
        bot.grid_propagate(False)
        bot.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(bot, fg_color=p.hl, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="ew"
        )
        inner = ctk.CTkFrame(bot, fg_color="transparent")
        inner.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(10, 16))
        inner.grid_columnconfigure(1, weight=1)

        self.timer_var = tk.StringVar(value="0:00")
        ctk.CTkLabel(
            inner,
            textvariable=self.timer_var,
            font=font(12, bold=True),
            text_color=p.tx,
            width=52,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.progress = ctk.CTkProgressBar(
            inner, height=6, corner_radius=3, progress_color=p.acc, fg_color=p.hl
        )
        self.progress.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.progress.set(0)

        self.progress_pct = tk.StringVar(value="")
        ctk.CTkLabel(
            inner,
            textvariable=self.progress_pct,
            font=font(10, bold=True),
            text_color=p.tx3,
            width=110,
            anchor="e",
        ).grid(row=0, column=2, sticky="e")

        self.status_var = tk.StringVar(value="Add a source, choose a task, then Start.")
        ctk.CTkLabel(
            inner, textvariable=self.status_var, font=font(11), text_color=p.tx2, anchor="w"
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.detail_var = tk.StringVar(value="")
        ctk.CTkLabel(
            inner, textvariable=self.detail_var, font=font(10), text_color=p.tx3, anchor="w"
        ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 0))

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

    # ── Path lists ───────────────────────────────────────────────────────────

    def _path_row(self, parent, path: str, on_remove, row: int) -> None:
        p = self.pal
        fr = ctk.CTkFrame(parent, fg_color="transparent", height=PATH_ROW_H)
        fr.grid(row=row, column=0, sticky="ew", pady=2)
        fr.grid_propagate(False)
        fr.grid_columnconfigure(1, weight=1)
        fr.grid_rowconfigure(0, weight=1)

        icon = IconButton(
            fr,
            icon="folder",
            command=None,
            color=p.acc,
            hover=p.acc,
            bg=p.side,
            size=ICON_COL + 4,
            glyph=14,
        )
        icon.grid(row=0, column=0, sticky="", padx=(ROW_PAD_X, ROW_ICON_GAP))

        name = Path(path).name or path
        ctk.CTkLabel(
            fr, text=name, font=font(12), text_color=p.tx2, anchor="w"
        ).grid(row=0, column=1, sticky="ew")

        xbtn = IconButton(
            fr,
            icon="x",
            command=on_remove,
            color=DANGER,
            hover=p.danger_hover,
            bg=p.side,
            size=22,
            glyph=12,
        )
        xbtn.grid(row=0, column=2, sticky="", padx=(0, ROW_PAD_X))

    def _refresh_path_lists(self) -> None:
        p = self.pal
        for child in self.sources_list.winfo_children():
            child.destroy()
        if not self._sources:
            ctk.CTkLabel(
                self.sources_list,
                text="No sources",
                font=font(11),
                text_color=p.tx3,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=ROW_PAD_X, pady=6)
        else:
            for i, path in enumerate(self._sources):
                self._path_row(
                    self.sources_list, path, lambda idx=i: self._remove_source_at(idx), i
                )

        for child in self.dest_list.winfo_children():
            child.destroy()
        if not self._dest:
            ctk.CTkLabel(
                self.dest_list,
                text="No destination",
                font=font(11),
                text_color=p.tx3,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=ROW_PAD_X, pady=4)
        else:
            self._path_row(self.dest_list, self._dest, self._clear_destination, 0)

    def _toggle_counts(self) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 100:
            w = 1120
        if self._counts_open:
            self.counts_panel.grid_remove()
            self._counts_open = False
            self.counts_toggle.set_icon("more", self.pal.tx2)
            self.geometry(f"{max(700, w - COUNTS_W)}x{h}")
            self.minsize(700, 580)
        else:
            self.counts_panel.grid(row=0, column=2, sticky="nsw")
            self._counts_open = True
            self.counts_toggle.set_icon("sidebar-right", self.pal.tx2)
            self.geometry(f"{w + COUNTS_W}x{h}")
            self.minsize(900, 580)

    def _folder_label(self, path: str) -> str:
        return Path(path).name or path

    def _session_state(self) -> SessionState:
        return SessionState(
            sources=list(self._sources),
            dest=self._dest,
            job=self.job_var.get() if hasattr(self, "job_var") else "Scan",
            remove_duplicates=(
                bool(self.dedupe_var.get()) if hasattr(self, "dedupe_var") else False
            ),
        )

    def _save_session(self) -> None:
        try:
            save_session(self._session_state())
        except OSError:
            log.exception("Failed to save session")

    def _restore_session(self) -> None:
        """Reload sources/destination/prefs; prefer session, fall back to job checkpoint."""
        state = load_session()
        cp = load_job_checkpoint()

        sources = list(state.sources) or (list(cp.sources) if cp else [])
        dest = state.dest or (cp.dest if cp else None)
        job = state.job
        if job not in JOB_MODES:
            job = cp.job if cp and cp.job in JOB_MODES else "Scan"
        dedupe = state.remove_duplicates
        if cp is not None:
            # Interrupted job owns task prefs so Resume matches what was running.
            if cp.job in JOB_MODES:
                job = cp.job
            dedupe = cp.remove_duplicates
            if not sources:
                sources = list(cp.sources)
            if not dest:
                dest = cp.dest

        self._sources = sources
        self._dest = dest
        self.job_var.set(job)
        self.dedupe_var.set(dedupe)

        if cp is not None and cp.results:
            try:
                self._results = [file_result_from_dict(d) for d in cp.results]
                self._fill_table(self._results)
            except Exception:
                log.exception("Failed to restore interrupted results")

        self._save_session()

    def _on_job_changed(self, _value: str | None = None) -> None:
        if not self._busy:
            self._save_session()

    def _add_source(self) -> None:
        if self._busy:
            return
        path = filedialog.askdirectory(title="Add source folder")
        if not path:
            return
        resolved = str(Path(path).expanduser().resolve())
        if resolved not in self._sources:
            self._sources.append(resolved)
            self._results = []
            self._refresh_path_lists()
            self._save_session()
            self.status_var.set(f"Added {self._folder_label(resolved)}")
            self.detail_var.set(resolved)

    def _remove_source_at(self, index: int) -> None:
        if self._busy or index < 0 or index >= len(self._sources):
            return
        removed = self._sources.pop(index)
        self._results = []
        self._refresh_path_lists()
        self._save_session()
        self.status_var.set(f"Removed {self._folder_label(removed)}")
        self.detail_var.set("")

    def _add_destination(self) -> None:
        if self._busy:
            return
        path = filedialog.askdirectory(title="Choose destination folder")
        if not path:
            return
        self._dest = str(Path(path).expanduser().resolve())
        self._refresh_path_lists()
        self._save_session()
        self.status_var.set(f"Destination: {self._folder_label(self._dest)}")
        self.detail_var.set(self._dest)

    def _clear_destination(self) -> None:
        if self._busy:
            return
        self._dest = None
        self._refresh_path_lists()
        self._save_session()
        self.status_var.set("Destination cleared.")
        self.detail_var.set("")

    # ── Timer / busy / progress ──────────────────────────────────────────────

    def _start_timer(self) -> None:
        self._timer_start = time.monotonic()
        self.timer_var.set("0:00")
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
        self._tick_timer()

    def _tick_timer(self) -> None:
        if self._timer_start is None:
            return
        self.timer_var.set(format_duration(time.monotonic() - self._timer_start))
        self._update_eta_label()
        self._timer_job = self.after(250, self._tick_timer)

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        if self._timer_start is not None:
            self.timer_var.set(format_duration(time.monotonic() - self._timer_start))
        self._timer_start = None

    def _eta_text(self) -> str:
        ratio = self._overall_ratio
        if self._timer_start is None or ratio < 0.02:
            return ""
        elapsed = time.monotonic() - self._timer_start
        if elapsed < 0.75:
            return ""
        remaining = elapsed * (1.0 - ratio) / ratio
        return f"~{format_duration(remaining)} left"

    def _update_eta_label(self) -> None:
        if not self._busy and self._overall_ratio <= 0:
            self.progress_pct.set("")
            return
        pct = f"{int(self._overall_ratio * 100)}%"
        eta = self._eta_text()
        self.progress_pct.set(f"{pct} · {eta}" if eta else pct)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.start_btn.configure(state=state)
        self.job_menu.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")
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
        self.status_var.set("Stopping…")
        self.stop_btn.configure(state="disabled")

    def _on_close(self) -> None:
        self._save_session()
        if self._busy:
            self._cancel_event.set()
            self._persist_job_checkpoint()
            # Give the worker a moment to finish its cancel path
            self.after(400, self.destroy)
            return
        self.destroy()

    def _update_progress(self, update: ProgressUpdate) -> None:
        """Coalesce worker progress onto the UI thread (avoids Tk queue blow-up)."""
        with self._progress_lock:
            self._latest_progress = update
            if self._progress_flush_scheduled:
                return
            self._progress_flush_scheduled = True
        self.after(0, self._flush_progress)

    def _flush_progress(self) -> None:
        with self._progress_lock:
            latest = self._latest_progress
            self._progress_flush_scheduled = False
        if latest is None:
            return
        now = time.monotonic()
        wait = PROGRESS_UI_MIN_INTERVAL - (now - self._last_progress_paint)
        if wait > 0:
            with self._progress_lock:
                if not self._progress_flush_scheduled:
                    self._progress_flush_scheduled = True
                    self.after(int(wait * 1000) + 1, self._flush_progress)
            return

        self._last_progress_paint = now
        try:
            self._progress_current = latest.current
            self._progress_total = latest.total
            ratio = overall_progress(
                self._job_phases,
                latest.phase,
                latest.current,
                latest.total,
                floor=self._overall_ratio,
            )
            # Keep the bar monotonic for the whole task (Scan → transfer).
            self._overall_ratio = max(self._overall_ratio, ratio)
            self.progress.set(self._overall_ratio)
            self._update_eta_label()
            self.status_var.set(latest.message)
            detail = latest.detail
            if len(detail) > 140:
                detail = "…" + detail[-139:]
            self.detail_var.set(detail)
        except tk.TclError:
            log.exception("Progress UI update failed")

        with self._progress_lock:
            if self._latest_progress is not latest and not self._progress_flush_scheduled:
                self._progress_flush_scheduled = True
                self.after(0, self._flush_progress)

    def _begin_job(
        self,
        status: str,
        job: str,
        *,
        reuse_scan: bool = False,
        resume_done: int = 0,
        resume_total: int = 0,
    ) -> None:
        self._cancel_event.clear()
        self._active_job = job
        self._progress_current = 0
        self._progress_total = 0
        self._job_phases = plan_phases(
            job,
            reuse_scan=reuse_scan,
            remove_duplicates=self.dedupe_var.get(),
        )
        if resume_total > 0 and resume_done > 0:
            self._overall_ratio = min(0.99, resume_done / resume_total)
        else:
            self._overall_ratio = 0.0
        self._set_busy(True)
        self._discover_pulse = 0.08
        self.status_var.set(status)
        self.detail_var.set("")
        self.progress.set(self._overall_ratio)
        self._update_eta_label()

    def _fill_table(self, results: list[FileResult]) -> None:
        exclude = self.dedupe_var.get()
        self.tree.delete(*self.tree.get_children())
        p = self.pal
        display = [r for r in results if not (exclude and r.is_duplicate)]
        capped = display[:MAX_TABLE_ROWS]
        try:
            for i, r in enumerate(capped):
                tag = "alt" if i % 2 else "base"
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        r.filename,
                        r.category,
                        format_size(r.size_bytes),
                        r.relative,
                    ),
                    tags=(tag, r.category),
                )
            self.tree.tag_configure("base", background=p.panel)
            self.tree.tag_configure("alt", background=p.rowalt)
            for cat, color in KIND_COLORS.items():
                self.tree.tag_configure(cat, foreground=color)
        except tk.TclError:
            log.exception("Results table update failed")

        counts = count_by_category(results, exclude_duplicates=exclude)
        size = total_size_bytes(results, exclude_duplicates=exclude)
        summary = f"{len(display):,} files · {format_size(size)}"
        if len(display) > MAX_TABLE_ROWS:
            summary += f"  (showing first {MAX_TABLE_ROWS:,})"
        self.summary_var.set(summary)
        for cat, lbl in self.count_labels.items():
            lbl.configure(text=str(counts.get(cat, 0)))
        self.total_label.configure(text=str(sum(counts.values())))
        self.size_label.configure(text=format_size(size))
        self.dup_label.configure(text=str(duplicate_count(results) if exclude else 0))

    def _on_dedupe_toggle(self) -> None:
        self._save_session()
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

    # ── Job checkpoint / resume ──────────────────────────────────────────────

    def _transfer_mode_for(self, job: str) -> str:
        return "move" if job == "Move" else "copy"

    def _init_job_checkpoint(
        self,
        job: str,
        results: list[FileResult],
        *,
        transferred: list[str] | None = None,
    ) -> None:
        assert self._dest is not None
        self._transferred = list(transferred or [])
        self._job_cp = new_job_checkpoint(
            job=job,
            transfer_mode=self._transfer_mode_for(job),
            sources=list(self._sources),
            dest=self._dest,
            remove_duplicates=self.dedupe_var.get(),
            results=results,
            transferred=self._transferred,
        )
        save_job_checkpoint(self._job_cp)

    def _on_file_transferred(self, result: FileResult) -> None:
        key = str(result.source)
        self._transferred.append(key)
        if self._job_cp is None:
            return
        # Only persist the transferred list frequently — rewriting full results
        # every N files can balloon disk I/O and OOM on large libraries.
        self._job_cp.transferred = list(self._transferred)
        if len(self._transferred) % self._transfer_save_every == 0:
            try:
                save_job_checkpoint(self._job_cp)
            except OSError:
                log.exception("Failed to save job checkpoint")

    def _persist_job_checkpoint(self) -> None:
        if self._job_cp is None:
            return
        self._job_cp.transferred = list(self._transferred)
        if self._results:
            self._job_cp.results = [file_result_to_dict(r) for r in self._results]
        try:
            save_job_checkpoint(self._job_cp)
        except OSError:
            pass

    def _clear_active_checkpoint(self) -> None:
        self._job_cp = None
        self._transferred = []
        clear_job_checkpoint()
        self._refresh_resume_button()

    def _refresh_resume_button(self) -> None:
        cp = load_job_checkpoint()
        self._pending_resume = cp
        if cp is not None and not self._busy:
            self.resume_btn.configure(text="Resume", state="normal")
            self.resume_btn.grid()
            done = len(cp.transferred)
            total = len(cp.results)
            self.status_var.set(
                f"Interrupted {cp.job} — {done:,}/{total:,} done. Press Resume to continue."
            )
        else:
            self.resume_btn.grid_remove()

    def _on_resume(self) -> None:
        if self._busy:
            return
        cp = load_job_checkpoint()
        if cp is None:
            self._refresh_resume_button()
            return
        self._sources = list(cp.sources)
        self._dest = cp.dest
        self.dedupe_var.set(cp.remove_duplicates)
        self.job_var.set(cp.job)
        results = [file_result_from_dict(d) for d in cp.results]
        self._results = results
        self._fill_table(results)
        self._refresh_path_lists()
        self._save_session()
        if cp.job == "Move" and not self._confirm_move():
            return
        self._run_transfer_job(
            cp.job,
            prior=results,
            skip_sources=list(cp.transferred),
            resume_from=cp,
        )

    # ── Start / modes ────────────────────────────────────────────────────────

    def _require_sources(self) -> bool:
        if not self._sources:
            self.status_var.set("Add at least one source folder.")
            return False
        missing = [p for p in self._sources if not Path(p).is_dir()]
        if missing:
            self.status_var.set(f"Invalid source: {missing[0]}")
            return False
        return True

    def _require_dest(self) -> bool:
        if not self._dest:
            self.status_var.set("Add a destination folder.")
            return False
        dest_path = Path(self._dest)
        if not dest_path.exists():
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.status_var.set(f"Cannot create destination: {exc}")
                return False
        if not dest_path.is_dir():
            self.status_var.set("Destination must be a folder.")
            return False
        return True

    def _confirm_move(self) -> bool:
        return bool(
            messagebox.askyesno(
                "Confirm Move",
                "Move all MIDI files out of the source folders into the "
                "destination?\n\n"
                "This relocates the originals — they will no longer be in "
                "the source folders. Prefer Copy if you want to keep them.",
                icon="warning",
                default="no",
            )
        )

    def _on_start(self) -> None:
        if self._busy:
            return
        mode = self.job_var.get()
        if mode == "Scan":
            self._run_scan()
        elif mode in TRANSFER_JOBS:
            if mode == "Move" and not self._confirm_move():
                return
            clear_job_checkpoint()
            self._run_transfer_job(mode)
        else:
            self._run_scan()

    def _run_scan(self) -> None:
        if not self._require_sources():
            return
        self._begin_job("Scanning…", "Scan", reuse_scan=False)
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
                self.after(0, lambda: self._job_done(cancelled=True))
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self.after(0, lambda e=err: self._job_done(error=e))
                return
            self.after(0, lambda r=results: self._scan_finished(r))

        threading.Thread(target=work, daemon=True).start()

    def _run_transfer_job(
        self,
        job: str,
        *,
        prior: list[FileResult] | None = None,
        skip_sources: list[str] | None = None,
        resume_from: JobCheckpoint | None = None,
    ) -> None:
        if not self._require_sources() or not self._require_dest():
            return
        assert self._dest is not None

        transfer_mode = self._transfer_mode_for(job)
        # Reuse completed scan for Copy/Move/Parse unless All (full pipeline)
        if prior is not None:
            results_arg: list[FileResult] | None = prior
        elif job == "All":
            results_arg = None
        elif self._results:
            results_arg = list(self._results)
        else:
            results_arg = None

        reuse_scan = results_arg is not None
        verb = "Moving" if transfer_mode == "move" else "Copying"
        if reuse_scan:
            status = f"{verb} from scan…"
        else:
            status = f"Scanning then {verb.lower()}…"
        if resume_from is not None:
            status = f"Resuming {job}…"

        skip = list(skip_sources or [])
        resume_total = len(results_arg) if results_arg is not None else 0
        self._begin_job(
            status,
            job,
            reuse_scan=reuse_scan,
            resume_done=len(skip),
            resume_total=resume_total,
        )
        sources = list(self._sources)
        dest = self._dest
        remove_duplicates = self.dedupe_var.get()

        if results_arg is not None:
            self._init_job_checkpoint(job, results_arg, transferred=skip)
        else:
            # Checkpoint after classify inside worker
            self._job_cp = None
            self._transferred = list(skip)

        def work() -> None:
            try:
                local_prior = results_arg
                if local_prior is None:
                    local_prior = classify_all(
                        sources,
                        progress=self._update_progress,
                        remove_duplicates=False,
                        should_cancel=self._cancel_event.is_set,
                    )
                    self._results = local_prior
                    self._init_job_checkpoint(job, local_prior, transferred=skip)

                def on_xfer(r: FileResult) -> None:
                    if not self._results:
                        self._results = local_prior or []
                    self._on_file_transferred(r)

                results, counts = organize(
                    sources,
                    dest,
                    dry_run=False,
                    remove_duplicates=remove_duplicates,
                    mode=transfer_mode,  # type: ignore[arg-type]
                    results=local_prior,
                    skip_sources=skip,
                    on_transferred=on_xfer,
                    progress=self._update_progress,
                    should_cancel=self._cancel_event.is_set,
                )
            except ScanCancelled:
                self._persist_job_checkpoint()
                self.after(0, lambda: self._job_done(cancelled=True, resumable=True))
                return
            except Exception as exc:  # noqa: BLE001
                self._persist_job_checkpoint()
                err = str(exc)
                self.after(0, lambda e=err: self._job_done(error=e, resumable=True))
                return
            self.after(
                0,
                lambda r=results, c=counts: self._transfer_finished(r, c, job=job),
            )

        threading.Thread(target=work, daemon=True).start()

    def _job_done(
        self,
        *,
        error: str | None = None,
        cancelled: bool = False,
        resumable: bool = False,
    ) -> None:
        self._set_busy(False)
        self._cancel_event.clear()
        self._active_job = None
        elapsed = self.timer_var.get()
        if cancelled:
            self.status_var.set(f"Stopped.  ({elapsed})")
            self.progress.set(0)
            self.progress_pct.set("")
            if resumable:
                self._refresh_resume_button()
            return
        if error:
            self.status_var.set(f"Failed: {error}  ({elapsed})")
            self.progress.set(0)
            self.progress_pct.set("")
            if resumable:
                self._refresh_resume_button()
            messagebox.showerror("MIDI Organizer", error)

    def _scan_finished(self, results: list[FileResult]) -> None:
        self._set_busy(False)
        self._cancel_event.clear()
        self._active_job = None
        elapsed = self.timer_var.get()
        self._results = results
        self._fill_table(results)
        self._overall_ratio = 1.0
        self.progress.set(1)
        self.progress_pct.set("100%")
        self.detail_var.set("")
        size = format_size(
            total_size_bytes(results, exclude_duplicates=self.dedupe_var.get())
        )
        dups = duplicate_count(results)
        if self.dedupe_var.get() and dups:
            kept = len(results) - dups
            self.status_var.set(
                f"Scan complete — {len(results):,} file(s), "
                f"{dups} duplicate(s) (will keep {kept}), {size}  ({elapsed})"
            )
        else:
            self.status_var.set(
                f"Scan complete — {len(results):,} MIDI file(s), {size}  ({elapsed})"
            )

    def _transfer_finished(
        self,
        results: list[FileResult],
        counts: dict[str, int],
        *,
        job: str,
    ) -> None:
        self._clear_active_checkpoint()
        self._set_busy(False)
        self._cancel_event.clear()
        self._active_job = None
        elapsed = self.timer_var.get()
        self._results = results
        self._fill_table(results)
        self._overall_ratio = 1.0
        self.progress.set(1)
        self.progress_pct.set("100%")
        self.detail_var.set("")
        parts = [f"{c}: {counts.get(c, 0)}" for c in CATEGORIES]
        size = format_size(
            total_size_bytes(results, exclude_duplicates=self.dedupe_var.get())
        )
        verb = "Move" if job == "Move" else job
        self.status_var.set(
            f"{verb} complete — {', '.join(parts)}  |  Total: {sum(counts.values())} "
            f"({size})  ({elapsed})"
        )


def run_app() -> None:
    app = MidiOrganizerApp()
    app.mainloop()
