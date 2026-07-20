"""CustomTkinter desktop UI for the MIDI Organizer."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk

from midi_parser import CATEGORIES
from midi_parser.name_hints import category_from_name
from midi_parser.organize import (
    FileResult,
    ScanCancelled,
    classify_all,
    count_by_category,
    duplicate_count,
    mark_duplicates,
    organize,
)


class MidiOrganizerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MIDI Organizer")
        self.geometry("1000x720")
        self.minsize(860, 600)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self._results: list[FileResult] = []
        self._busy = False
        self._scanning = False
        self._sources: list[str] = []
        self._cancel_event = threading.Event()

        self._build()

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 8}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Sources (multi)
        src_frame = ctk.CTkFrame(self, fg_color="transparent")
        src_frame.grid(row=0, column=0, sticky="ew", **pad)
        src_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(src_frame, text="Sources", width=90, anchor="w").grid(
            row=0, column=0, sticky="nw"
        )

        list_wrap = ctk.CTkFrame(src_frame)
        list_wrap.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        list_wrap.grid_columnconfigure(0, weight=1)
        self.source_list = tk.Listbox(
            list_wrap,
            height=4,
            activestyle="dotbox",
            selectmode=tk.EXTENDED,
            exportselection=False,
            font=("SF Pro Text", 12),
        )
        self.source_list.grid(row=0, column=0, sticky="ew")
        src_scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.source_list.yview)
        self.source_list.configure(yscrollcommand=src_scroll.set)
        src_scroll.grid(row=0, column=1, sticky="ns")

        src_btns = ctk.CTkFrame(src_frame, fg_color="transparent")
        src_btns.grid(row=0, column=2, sticky="n")
        ctk.CTkButton(src_btns, text="Add", width=90, command=self._add_source).pack(pady=(0, 4))
        ctk.CTkButton(src_btns, text="Remove", width=90, command=self._remove_sources).pack(
            pady=(0, 4)
        )
        ctk.CTkButton(src_btns, text="Clear", width=90, command=self._clear_sources).pack()

        # Destination
        dst_frame = ctk.CTkFrame(self, fg_color="transparent")
        dst_frame.grid(row=1, column=0, sticky="ew", **pad)
        dst_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(dst_frame, text="Destination", width=90, anchor="w").grid(row=0, column=0)
        self.dest_var = tk.StringVar()
        ctk.CTkEntry(dst_frame, textvariable=self.dest_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8)
        )
        ctk.CTkButton(dst_frame, text="Browse", width=90, command=self._browse_dest).grid(
            row=0, column=2
        )

        # Actions
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=2, column=0, sticky="ew", **pad)
        self.scan_btn = ctk.CTkButton(act, text="Scan", width=100, command=self._on_scan)
        self.scan_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ctk.CTkButton(
            act,
            text="Stop Scan",
            width=100,
            fg_color="#8B3A3A",
            hover_color="#6E2E2E",
            command=self._on_stop_scan,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.org_btn = ctk.CTkButton(act, text="Organize", width=100, command=self._on_organize)
        self.org_btn.pack(side="left", padx=(0, 8))

        self.mode_var = tk.StringVar(value="copy")
        self.mode_seg = ctk.CTkSegmentedButton(
            act,
            values=["Copy", "Move"],
            command=self._on_mode_change,
        )
        self.mode_seg.set("Copy")
        self.mode_seg.pack(side="left", padx=(8, 0))

        self.dry_run_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(act, text="Dry run", variable=self.dry_run_var).pack(
            side="left", padx=(12, 0)
        )
        self.dedupe_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            act,
            text="Remove duplicates",
            variable=self.dedupe_var,
            command=self._on_dedupe_toggle,
        ).pack(side="left", padx=(12, 0))

        # Results + counts
        mid = ctk.CTkFrame(self)
        mid.grid(row=3, column=0, sticky="nsew", padx=16, pady=8)
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_columnconfigure(1, weight=0)
        mid.grid_rowconfigure(0, weight=1)

        table_frame = ctk.CTkFrame(mid)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24, font=("SF Pro Text", 12))
        style.configure("Treeview.Heading", font=("SF Pro Text", 12, "bold"))

        cols = ("filename", "category", "reason", "relative")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("filename", text="Filename")
        self.tree.heading("category", text="Category")
        self.tree.heading("reason", text="Reason")
        self.tree.heading("relative", text="Relative path")
        self.tree.column("filename", width=220, stretch=True)
        self.tree.column("category", width=90, stretch=False)
        self.tree.column("reason", width=140, stretch=False)
        self.tree.column("relative", width=300, stretch=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        counts = ctk.CTkFrame(mid, width=180)
        counts.grid(row=0, column=1, sticky="ns", padx=(4, 8), pady=8)
        counts.grid_propagate(False)
        ctk.CTkLabel(counts, text="Counts", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(12, 8)
        )
        self.count_labels: dict[str, ctk.CTkLabel] = {}
        for cat in CATEGORIES:
            row = ctk.CTkFrame(counts, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=cat, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(row, text="0", anchor="e")
            lbl.pack(side="right")
            self.count_labels[cat] = lbl
        ctk.CTkFrame(counts, height=1, fg_color=("gray70", "gray30")).pack(
            fill="x", padx=12, pady=8
        )
        total_row = ctk.CTkFrame(counts, fg_color="transparent")
        total_row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(total_row, text="Total", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.total_label = ctk.CTkLabel(total_row, text="0", font=ctk.CTkFont(weight="bold"))
        self.total_label.pack(side="right")
        dup_row = ctk.CTkFrame(counts, fg_color="transparent")
        dup_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(dup_row, text="Duplicates", anchor="w").pack(side="left")
        self.dup_label = ctk.CTkLabel(dup_row, text="0", anchor="e")
        self.dup_label.pack(side="right")

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        bot.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(bot)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.status_var = tk.StringVar(value="Add one or more source folders and click Scan.")
        ctk.CTkLabel(bot, textvariable=self.status_var, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(6, 0)
        )

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

    def _set_busy(self, busy: bool, *, scanning: bool = False) -> None:
        self._busy = busy
        self._scanning = scanning
        self.scan_btn.configure(state="disabled" if busy else "normal")
        self.org_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if scanning else "disabled")

    def _on_stop_scan(self) -> None:
        if not self._scanning:
            return
        self._cancel_event.set()
        self.status_var.set("Stopping scan…")
        self.stop_btn.configure(state="disabled")

    def _update_progress(self, current: int, total: int, name: str) -> None:
        def ui() -> None:
            frac = (current / total) if total else 0.0
            self.progress.set(frac)
            self.status_var.set(f"{current} / {total}: {name}")

        self.after(0, ui)

    def _fill_table(self, results: list[FileResult]) -> None:
        exclude = self.dedupe_var.get()
        self.tree.delete(*self.tree.get_children())
        for r in results:
            reason = r.reason
            if r.is_duplicate and r.duplicate_of:
                reason = f"duplicate → {r.duplicate_of}"
            self.tree.insert(
                "",
                "end",
                values=(r.filename, r.category, reason, r.relative),
            )
        counts = count_by_category(results, exclude_duplicates=exclude)
        for cat, lbl in self.count_labels.items():
            lbl.configure(text=str(counts.get(cat, 0)))
        self.total_label.configure(text=str(sum(counts.values())))
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

        self._cancel_event.clear()
        self._set_busy(True, scanning=True)
        self.status_var.set("Scanning…")
        self.progress.set(0)
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
                self.after(0, lambda: self._scan_done([], error=str(exc)))
                return
            self.after(0, lambda: self._scan_done(results))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(
        self,
        results: list[FileResult],
        error: str | None = None,
        *,
        cancelled: bool = False,
    ) -> None:
        self._set_busy(False)
        self._cancel_event.clear()
        if cancelled:
            self.status_var.set("Scan stopped.")
            self.progress.set(0)
            return
        if error:
            self.status_var.set(f"Scan failed: {error}")
            self.progress.set(0)
            return
        self._results = results
        self._fill_table(results)
        self.progress.set(1)
        dups = duplicate_count(results)
        n_src = len(self._sources)
        src_note = f" from {n_src} source(s)" if n_src > 1 else ""
        if self.dedupe_var.get() and dups:
            kept = len(results) - dups
            self.status_var.set(
                f"Scan complete — {len(results)} file(s){src_note}, {dups} duplicate(s) "
                f"(will keep {kept})."
            )
        else:
            self.status_var.set(f"Scan complete — {len(results)} MIDI file(s){src_note}.")

    def _on_organize(self) -> None:
        if self._busy:
            return
        if not self._sources:
            self.status_var.set("Add at least one source folder.")
            return
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
        self._set_busy(True)
        action = "Dry run" if dry_run else ("Moving" if mode == "move" else "Copying")
        self.status_var.set(f"{action}…")
        self.progress.set(0)
        sources = list(self._sources)
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
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._organize_done([], {}, error=str(exc)))
                return
            self.after(
                0,
                lambda: self._organize_done(
                    results,
                    counts,
                    dry_run=dry_run,
                    remove_duplicates=remove_duplicates,
                    mode=mode,
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
    ) -> None:
        self._set_busy(False)
        if error:
            self.status_var.set(f"Organize failed: {error}")
            self.progress.set(0)
            return
        self._results = results
        self._fill_table(results)
        self.progress.set(1)
        parts = [f"{c}: {counts.get(c, 0)}" for c in CATEGORIES]
        if dry_run:
            verb = "Dry run"
        elif mode == "move":
            verb = "Moved"
        else:
            verb = "Copied"
        dups = duplicate_count(results) if remove_duplicates else 0
        dup_note = f"  |  Skipped duplicates: {dups}" if dups else ""
        self.status_var.set(
            f"{verb} — {', '.join(parts)}  |  Total: {sum(counts.values())}{dup_note}"
        )


def run_app() -> None:
    app = MidiOrganizerApp()
    app.mainloop()
