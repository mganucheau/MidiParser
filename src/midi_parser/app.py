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
        self.geometry("960x680")
        self.minsize(800, 560)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self._results: list[FileResult] = []
        self._busy = False

        self._build()

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 8}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Source
        src_frame = ctk.CTkFrame(self, fg_color="transparent")
        src_frame.grid(row=0, column=0, sticky="ew", **pad)
        src_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(src_frame, text="Source", width=90, anchor="w").grid(row=0, column=0)
        self.source_var = tk.StringVar()
        ctk.CTkEntry(src_frame, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8)
        )
        ctk.CTkButton(src_frame, text="Browse", width=90, command=self._browse_source).grid(
            row=0, column=2
        )

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
        self.scan_btn = ctk.CTkButton(act, text="Scan", width=120, command=self._on_scan)
        self.scan_btn.pack(side="left", padx=(0, 8))
        self.org_btn = ctk.CTkButton(act, text="Organize", width=120, command=self._on_organize)
        self.org_btn.pack(side="left", padx=(0, 8))
        self.dry_run_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(act, text="Dry run", variable=self.dry_run_var).pack(
            side="left", padx=(8, 0)
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
        self.tree.column("reason", width=80, stretch=False)
        self.tree.column("relative", width=320, stretch=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        # Counts panel
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

        # Progress
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        bot.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(bot)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.status_var = tk.StringVar(value="Pick a source folder and click Scan.")
        ctk.CTkLabel(bot, textvariable=self.status_var, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(6, 0)
        )

    def _browse_source(self) -> None:
        path = filedialog.askdirectory(title="Select source folder")
        if path:
            self.source_var.set(path)

    def _browse_dest(self) -> None:
        path = filedialog.askdirectory(title="Select destination folder")
        if path:
            self.dest_var.set(path)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.scan_btn.configure(state=state)
        self.org_btn.configure(state=state)

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
        source = self.source_var.get().strip()
        if not source or not Path(source).is_dir():
            self.status_var.set("Choose a valid source folder.")
            return

        self._set_busy(True)
        self.status_var.set("Scanning…")
        self.progress.set(0)
        remove_duplicates = self.dedupe_var.get()

        def work() -> None:
            try:
                results = classify_all(
                    source,
                    progress=self._update_progress,
                    remove_duplicates=remove_duplicates,
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._scan_done([], error=str(exc)))
                return
            self.after(0, lambda: self._scan_done(results))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, results: list[FileResult], error: str | None = None) -> None:
        self._set_busy(False)
        if error:
            self.status_var.set(f"Scan failed: {error}")
            self.progress.set(0)
            return
        self._results = results
        self._fill_table(results)
        self.progress.set(1)
        dups = duplicate_count(results)
        if self.dedupe_var.get() and dups:
            kept = len(results) - dups
            self.status_var.set(
                f"Scan complete — {len(results)} file(s), {dups} duplicate(s) "
                f"(will keep {kept})."
            )
        else:
            self.status_var.set(f"Scan complete — {len(results)} MIDI file(s).")

    def _on_organize(self) -> None:
        if self._busy:
            return
        source = self.source_var.get().strip()
        dest = self.dest_var.get().strip()
        if not source or not Path(source).is_dir():
            self.status_var.set("Choose a valid source folder.")
            return
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
        self._set_busy(True)
        self.status_var.set("Dry run…" if dry_run else "Organizing…")
        self.progress.set(0)
        prior = list(self._results) if self._results else None

        def work() -> None:
            try:
                results, counts = organize(
                    source,
                    dest,
                    dry_run=dry_run,
                    remove_duplicates=remove_duplicates,
                    results=prior,
                    progress=self._update_progress,
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._organize_done([], {}, error=str(exc)))
                return
            self.after(
                0,
                lambda: self._organize_done(
                    results, counts, dry_run=dry_run, remove_duplicates=remove_duplicates
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
        verb = "Dry run" if dry_run else "Organized"
        dups = duplicate_count(results) if remove_duplicates else 0
        dup_note = f"  |  Skipped duplicates: {dups}" if dups else ""
        self.status_var.set(
            f"{verb} — {', '.join(parts)}  |  Total: {sum(counts.values())}{dup_note}"
        )


def run_app() -> None:
    app = MidiOrganizerApp()
    app.mainloop()
