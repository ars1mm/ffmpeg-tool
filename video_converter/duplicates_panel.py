"""Duplicate-detection panel based on content hashes."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from video_converter import dupes, recycle


def _format_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


class DuplicatesWindow(tk.Toplevel):
    """Finds byte-identical videos and lets the user recycle the extras."""

    def __init__(self, master: tk.Misc, root_dir: Path) -> None:
        super().__init__(master)
        self.title("Duplicate videos - hash comparison")
        self.geometry("980x600")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._root_var = tk.StringVar(value=str(root_dir))
        self._status = tk.StringVar(value="Press Scan to hash the library.")
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

        self._build_ui()
        self.after(100, self._drain)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(8, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Root folder:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self._root_var, width=60)
        entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Button(top, text="...", width=3, command=self._choose_root).pack(
            side="left"
        )
        self.scan_button = ttk.Button(top, text="Scan", command=self.start_scan)
        self.scan_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(
            top, text="Stop", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(6, 0))

        ttk.Label(top, textvariable=self._status, foreground="#666").pack(
            side="left", padx=(12, 0)
        )

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        columns = ("group", "size", "hash", "file")
        self.tree = ttk.Treeview(
            body, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "group": ("Group", 70),
            "size": ("Size", 80),
            "hash": ("SHA-256", 120),
            "file": ("File", 460),
        }
        for key, (text, width) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        self.tree.column("group", anchor="center")
        self.tree.column("hash", anchor="w")

        yscroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.tree.tag_configure("keep", foreground="#5a5a5a")
        self.tree.tag_configure("dup", foreground="#b00020")

        actions = ttk.Frame(self, padding=(8, 8))
        actions.pack(fill="x")
        self.select_dup_button = ttk.Button(
            actions,
            text="Select all but first in each group",
            command=self._select_duplicates,
        )
        self.select_dup_button.pack(side="left")
        self.delete_button = ttk.Button(
            actions,
            text="Delete selected (Recycle Bin)",
            command=self._delete_selected,
        )
        self.delete_button.pack(side="left", padx=(6, 0))
        self.reveal_button = ttk.Button(
            actions, text="Open folder", command=self._reveal_selected
        )
        self.reveal_button.pack(side="left", padx=(6, 0))
        self._set_actions("disabled")

    def _set_actions(self, state: str) -> None:
        for widget in (self.select_dup_button, self.delete_button,
                       self.reveal_button):
            widget.config(state=state)

    def _choose_root(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self._root_var.get())
        if chosen:
            self._root_var.set(chosen)

    def start_scan(self) -> None:
        root = Path(self._root_var.get().strip())
        if not root.is_dir():
            messagebox.showerror("Invalid folder", "Root folder does not exist.")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_flag.clear()
        self.scan_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self._set_actions("disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._status.set("Scanning for video files...")

        self._thread = threading.Thread(
            target=self._run_scan, args=(root,), daemon=True
        )
        self._thread.start()

    def _stop(self) -> None:
        self._stop_flag.set()
        self._status.set("Stopping...")
        self.stop_button.config(state="disabled")

    def _run_scan(self, root: Path) -> None:
        try:
            def progress(done: int, total: int, path: str) -> None:
                self._queue.put(
                    ("progress", f"Hashing {done}/{total}: {path}", done, total)
                )
                self._queue.put(("hashed", (done, total)))

            files = list(dupes.iter_videos(root))
            self._queue.put(("info", f"Found {len(files)} video files - hashing..."))
            groups = dupes.find_duplicates(files, progress=progress,
                                           should_stop=self._stop_flag.is_set)
            self._queue.put(("done", groups))
        except InterruptedError:
            self._queue.put(("error", "Scan stopped."))
        except Exception as exc:  # noqa: BLE001 - surface any scan failure
            self._queue.put(("error", f"Scan failed: {exc}"))

    def _drain(self) -> None:
        try:
            while True:
                kind, *payload = self._queue.get_nowait()
                if kind == "progress":
                    self._status.set(payload[0])
                elif kind == "info":
                    self._status.set(payload[0])
                    self.update_idletasks()
                elif kind == "hashed":
                    pass
                elif kind == "error":
                    self._status.set(payload[0])
                elif kind == "done":
                    self._show_results(payload[0])
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _show_results(self, groups: list[dupes.DuplicateGroup]) -> None:
        self.scan_button.config(state="normal")
        self.stop_button.config(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)

        dup_count = sum(len(g.files) - 1 for g in groups)
        if not groups:
            self._status.set("No duplicates found.")
            return

        for index, group in enumerate(groups, start=1):
            for i, path in enumerate(group.files):
                tag = "keep" if i == 0 else "dup"
                self.tree.insert(
                    "", "end",
                    iid=str(path),
                    values=(index, _format_size(group.size),
                            group.sha256[:16], str(path)),
                    tags=(tag,),
                )
        self._status.set(
            f"{len(groups)} duplicate group(s), {dup_count} file(s) can be removed."
        )
        self._set_actions("normal")

    def _select_duplicates(self) -> None:
        seen: set[str] = set()
        selection: list[str] = []
        for iid in self.tree.get_children():
            group_id = self.tree.set(iid, "group")
            if group_id in seen:
                selection.append(iid)
            else:
                seen.add(group_id)
        self.tree.selection_set(selection)

    def _selected_paths(self) -> list[Path]:
        return [Path(iid) for iid in self.tree.selection() if Path(iid).exists()]

    def _delete_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("Nothing selected", "Select files first.")
            return
        total = sum(p.stat().st_size for p in paths)
        answer = messagebox.askyesno(
            "Confirm",
            f"Move {len(paths)} file(s) ({_format_size(total)}) to the "
            "Recycle Bin?\nThey stay usable if you undo.",
        )
        if not answer:
            return
        failed = []
        try:
            failed = recycle.send_to_recycle_bin(paths)
        except NotImplementedError:
            messagebox.showerror("Unsupported",
                                 "Recycle Bin delete is Windows-only.")
            return
        for path in paths:
            if path not in failed and not path.exists():
                if self.tree.exists(str(path)):
                    self.tree.delete(str(path))
        self._cleanup_empty_groups()
        remaining = self.tree.get_children()
        if failed:
            messagebox.showerror(
                "Some files not deleted",
                f"{len(failed)} file(s) could not be moved to the Recycle Bin.",
            )
        elif not remaining:
            self._status.set("All duplicates removed.")
            self._set_actions("disabled")

    def _cleanup_empty_groups(self) -> None:
        counts: dict[str, int] = {}
        for iid in self.tree.get_children():
            group_id = self.tree.set(iid, "group")
            counts[group_id] = counts.get(group_id, 0) + 1
        to_drop = [gid for gid, n in counts.items() if n < 2]
        for iid in self.tree.get_children():
            if self.tree.set(iid, "group") in to_drop:
                self.tree.delete(iid)

    def _reveal_selected(self) -> None:
        paths = [Path(iid) for iid in self.tree.selection()]
        if not paths:
            return
        import subprocess

        subprocess.Popen(["explorer", "/select,", str(paths[0])])