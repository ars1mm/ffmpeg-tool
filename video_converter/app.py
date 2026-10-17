"""Tkinter desktop UI for the local FFmpeg video converter."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import converter, elevation, ffmpeg, presets, update_checker
from .version import __version__

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
    ".m4v", ".mpg", ".mpeg", ".ts", ".3gp", ".ogv",
}

CROP_NONE = "None"
CROP_CUSTOM = "Custom..."
CPU_LABEL = "CPU (software)"
GPU_AUTO_LABEL = "GPU (auto: best available)"
GPU_WORKER_MAX = 2

DEFAULT_SOURCE_ROOT = str(Path.home() / "Videos")
CONFIG_PATH = Path.home() / ".ffmpeg_converter.json"


@dataclass
class Job:
    source: str
    preset_key: str
    destination: str | None = None
    status: str = "Queued"
    progress: float = 0.0
    item_id: str = ""
    width: int = 0
    height: int = 0
    artist: str | None = None


class ConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FFmpeg Video Converter")
        self.geometry("1360x820")
        self.minsize(1280, 720)

        self.worker_threads = max(1, (os.cpu_count() or 2) // 2)
        self.cpu_count = os.cpu_count() or 2
        self.workers = tk.IntVar(value=self.worker_threads)
        self.gpu_encoders: dict[str, str] = {}
        self.gpu_auto: dict[str, str] = {}
        self.gpu_devices: list[str] = []
        self.gpu_label = tk.StringVar(value=CPU_LABEL)

        self.jobs: list[Job] = []
        cfg = self._load_config()
        self.source_root = tk.StringVar(value=cfg.get("source_root", DEFAULT_SOURCE_ROOT))
        self.output_dir = tk.StringVar(value=cfg.get("output_dir", str(Path(DEFAULT_SOURCE_ROOT).parent)))
        self.preset_label = tk.StringVar(value=presets.labels()[0])
        self.name_template = tk.StringVar(
            value="{format}/{artist}/{slug}-{hex5}-{uuid}-{time}.{format}"
        )
        self.artist = tk.StringVar(value="")
        self.crop_label = tk.StringVar(value=CROP_NONE)
        self.custom_crop: presets.Crop | None = None
        self.status_text = tk.StringVar(value="Ready")
        self.overall = tk.DoubleVar(value=0.0)

        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._ui_queue: queue.Queue = queue.Queue()
        self._duplicates_window: object | None = None

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        self.after(100, self._drain_ui_queue)
        self._check_ffmpeg()
        self._detect_gpu()
        self._check_for_updates()
        if elevation.is_supported() and elevation.is_admin():
            self.title(f"FFmpeg Video Converter v{__version__}  (Administrator)")
        else:
            self.title(f"FFmpeg Video Converter v{__version__}")
        self.refresh_library()

    # ----------------------------------------------------------------- config
    def _load_config(self) -> dict:
        try:
            if CONFIG_PATH.exists():
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_config(self) -> None:
        try:
            cfg = {
                "source_root": self.source_root.get(),
                "output_dir": self.output_dir.get(),
            }
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ----------------------------------------------------------------- UI
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add files...", command=self.add_files)
        file_menu.add_command(label="Add folder...", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Clear queue", command=self.clear_queue)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(
            label="Find duplicate videos...", command=self.open_duplicates
        )
        tools_menu.add_separator()
        tools_menu.add_command(
            label="Restart as administrator...", command=self.restart_as_admin
        )
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 8))
        bar.pack(fill="x")
        self.add_files_button = ttk.Button(
            bar, text="Add files", command=self.add_files
        )
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(
            bar, text="Add folder", command=self.add_folder
        )
        self.add_folder_button.pack(side="left", padx=(6, 0))
        self.remove_button = ttk.Button(
            bar, text="Remove", command=self.remove_selected
        )
        self.remove_button.pack(side="left", padx=(6, 0))
        self.duplicates_button = ttk.Button(
            bar, text="Duplicates", command=self.open_duplicates
        )
        self.duplicates_button.pack(side="left", padx=(6, 0))
        self.clear_button = ttk.Button(bar, text="Clear", command=self.clear_queue)
        self.clear_button.pack(side="left", padx=(6, 0))

    def _build_body(self) -> None:
        vertical = ttk.PanedWindow(self, orient="vertical")
        vertical.pack(fill="both", expand=True)

        body = ttk.PanedWindow(vertical, orient="horizontal")
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=5)
        self._build_library(left)
        self._build_queue_view(right)
        self._build_controls(right)

        log_frame = ttk.Frame(vertical)
        self._build_log_panel(log_frame)
        vertical.add(body, weight=4)
        vertical.add(log_frame, weight=1)

    def _build_log_panel(self, parent: tk.Misc) -> None:
        header = ttk.Frame(parent, padding=(8, 6, 8, 0))
        header.pack(fill="x")
        ttk.Label(header, text="Activity log").pack(side="left")
        self.copy_log_button = ttk.Button(
            header, text="Copy", width=7, command=self.copy_log
        )
        self.copy_log_button.pack(side="right")
        self.clear_log_button = ttk.Button(
            header, text="Clear", width=7, command=self.clear_log
        )
        self.clear_log_button.pack(side="right", padx=(0, 6))

        wrap = ttk.Frame(parent, padding=(8, 4, 8, 8))
        wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            wrap,
            height=8,
            wrap="none",
            state="disabled",
            font=("Consolas", 9),
            relief="flat",
            borderwidth=1,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("info", foreground="#1f2328")
        self.log_text.tag_configure("save", foreground="#1a4fb4")
        self.log_text.tag_configure("done", foreground="#1a7f37")
        self.log_text.tag_configure("failed", foreground="#cf222e")
        self.log_text.tag_configure("cancel", foreground="#9a6700")
        self.log_text.tag_configure("gpu", foreground="#8250df")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def copy_log(self) -> None:
        text = self.log_text.get("1.0", "end-1c")
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_text.set("Activity log copied to clipboard")

    def _append_log(self, line: str, level: str = "info") -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n", level)
        # Bound memory for very long sessions.
        if int(self.log_text.index("end-1c").split(".")[0]) > 5000:
            self.log_text.delete("1.0", "1000.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log(self, message: str, level: str = "info") -> None:
        """Show a message in the activity log and mirror it to stdout."""
        print(message, flush=True)
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self._ui_queue.put(("log", line, level))

    def _build_library(self, parent: tk.Misc) -> None:
        frame = ttk.Frame(parent, padding=(8, 8))
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Source library").pack(anchor="w")
        root_row = ttk.Frame(frame)
        root_row.pack(fill="x", pady=(4, 6))
        ttk.Entry(root_row, textvariable=self.source_root).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(root_row, text="...", width=3, command=self.choose_source_root).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(root_row, text="Refresh", command=self.refresh_library).pack(
            side="left", padx=(4, 0)
        )

        list_wrap = ttk.Frame(frame)
        list_wrap.pack(fill="both", expand=True)
        self.library = ttk.Treeview(
            list_wrap, columns=("videos",), show="tree headings", selectmode="extended"
        )
        self.library.heading("#0", text="Folder")
        self.library.heading("videos", text="Videos")
        self.library.column("#0", width=190, anchor="w")
        self.library.column("videos", width=60, anchor="center")
        scroll = ttk.Scrollbar(
            list_wrap, orient="vertical", command=self.library.yview
        )
        self.library.configure(yscrollcommand=scroll.set)
        self.library.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.library.bind("<Double-1>", lambda _e: self.add_selected_from_library())

        self.library_add_button = ttk.Button(
            frame,
            text="Add selected folders to queue",
            command=self.add_selected_from_library,
        )
        self.library_add_button.pack(fill="x", pady=(6, 0))

    def _build_queue_view(self, parent: tk.Misc) -> None:
        frame = ttk.Frame(parent, padding=(8, 8))
        frame.pack(fill="both", expand=True)

        columns = ("file", "resolution", "duration", "status", "progress")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "file": ("File", 320),
            "resolution": ("Resolution", 110),
            "duration": ("Duration", 90),
            "status": ("Status", 140),
            "progress": ("Progress", 90),
        }
        for key, (text, width) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        self.tree.column("progress", anchor="center")
        self.tree.column("duration", anchor="center")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_controls(self, parent: tk.Misc) -> None:
        frame = ttk.Frame(parent, padding=(8, 8))
        frame.pack(fill="x")

        ttk.Label(frame, text="Format:").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(
            frame,
            textvariable=self.preset_label,
            values=presets.labels(),
            state="readonly",
            width=42,
        )
        combo.grid(row=0, column=1, sticky="w", padx=(6, 16))

        self.preset_desc = ttk.Label(frame, text="", foreground="#666")
        self.preset_desc.grid(row=0, column=2, columnspan=2, sticky="w")
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: (self._update_preset_desc(), self._update_encoder_hint()),
        )
        self._update_preset_desc()

        ttk.Label(frame, text="Output folder:").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        entry = ttk.Entry(frame, textvariable=self.output_dir, width=48)
        entry.grid(row=1, column=1, sticky="we", padx=(6, 6), pady=(8, 0))
        ttk.Button(frame, text="Browse...", command=self.choose_output).grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            frame, text="(blank = alongside source)", foreground="#666"
        ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(frame, text="Output name:").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        template_entry = ttk.Entry(frame, textvariable=self.name_template, width=48)
        template_entry.grid(row=2, column=1, sticky="we", padx=(6, 6), pady=(8, 0))
        ttk.Label(
            frame,
            text="placeholders: {format} {artist} {slug} {hex5} {uuid} {time} {name}",
            foreground="#666",
        ).grid(row=2, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="Artist tag:").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        artist_entry = ttk.Entry(frame, textvariable=self.artist, width=24)
        artist_entry.grid(row=3, column=1, sticky="w", padx=(6, 6), pady=(8, 0))
        ttk.Label(
            frame,
            text="used for the {artist} placeholder",
            foreground="#666",
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 0))

        crop_values = [CROP_NONE, *presets.ASPECT_PRESETS.keys(), CROP_CUSTOM]
        ttk.Label(frame, text="Crop:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.crop_combo = ttk.Combobox(
            frame,
            textvariable=self.crop_label,
            values=crop_values,
            state="readonly",
            width=22,
        )
        self.crop_combo.grid(row=4, column=1, sticky="w", padx=(6, 6), pady=(8, 0))
        self.crop_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_crop_changed())
        ttk.Button(frame, text="Custom WxH+X+Y...", command=self.edit_custom_crop).grid(
            row=4, column=2, sticky="w", pady=(8, 0)
        )
        self.crop_desc = ttk.Label(frame, text="", foreground="#666")
        self.crop_desc.grid(row=4, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self._update_crop_desc()

        ttk.Label(frame, text="Workers:").grid(
            row=5, column=0, sticky="w", pady=(8, 0)
        )
        self.workers_spin = ttk.Spinbox(
            frame,
            from_=1,
            to=self.cpu_count,
            textvariable=self.workers,
            width=6,
            command=self._update_workers_hint,
        )
        self.workers_spin.grid(row=5, column=1, sticky="w", padx=(6, 6), pady=(8, 0))
        self.workers_spin.bind("<KeyRelease>", lambda _e: self._update_workers_hint())
        self.workers_hint = ttk.Label(frame, text="", foreground="#666")
        self.workers_hint.grid(
            row=5, column=2, columnspan=2, sticky="w", pady=(8, 0)
        )
        self._update_workers_hint()

        ttk.Label(frame, text="Encoder:").grid(
            row=6, column=0, sticky="w", pady=(8, 0)
        )
        self.encoder_combo = ttk.Combobox(
            frame,
            textvariable=self.gpu_label,
            values=[CPU_LABEL],
            state="readonly",
            width=30,
        )
        self.encoder_combo.grid(row=6, column=1, sticky="w", padx=(6, 6), pady=(8, 0))
        self.encoder_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: (self._update_encoder_hint(), self._update_workers_hint()),
        )
        self.encoder_hint = ttk.Label(frame, text="", foreground="#666")
        self.encoder_hint.grid(
            row=6, column=2, columnspan=2, sticky="w", pady=(8, 0)
        )

        frame.columnconfigure(1, weight=1)

        actions = ttk.Frame(parent, padding=(8, 0, 8, 8))
        actions.pack(fill="x")
        self.start_button = ttk.Button(
            actions, text="Start conversion", command=self.start
        )
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=(6, 0))

        self.overall_bar = ttk.Progressbar(
            actions, variable=self.overall, maximum=100.0
        )
        self.overall_bar.pack(side="right", fill="x", expand=True, padx=(16, 0))

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, relief="sunken", padding=(8, 3))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_text).pack(side="left")

    def _update_preset_desc(self) -> None:
        preset = presets.preset_by_label(self.preset_label.get())
        self.preset_desc.config(text=preset.description)

    def _on_crop_changed(self) -> None:
        if self.crop_label.get() == CROP_CUSTOM and self.custom_crop is None:
            self.edit_custom_crop()
            return
        self._update_crop_desc()

    def _update_crop_desc(self) -> None:
        label = self.crop_label.get()
        if label == CROP_NONE:
            self.crop_desc.config(text="no crop")
        elif label == CROP_CUSTOM:
            text = (
                self.custom_crop.label if self.custom_crop else "not set"
            )
            self.crop_desc.config(text=text)
        else:
            self.crop_desc.config(text="centred on source")

    def _gpu_active(self) -> bool:
        option = self.gpu_label.get()
        return option == GPU_AUTO_LABEL or option in self.gpu_encoders

    def _clamp_workers(self) -> int:
        try:
            n = int(self.workers.get())
        except (tk.TclError, ValueError):
            n = self.worker_threads
        if self._gpu_active():
            n = min(n, GPU_WORKER_MAX)
        else:
            n = min(n, self.cpu_count)
        n = max(1, n)
        self.workers.set(n)
        return n

    def _update_workers_hint(self) -> None:
        try:
            n = int(self.workers.get())
        except (tk.TclError, ValueError):
            n = self.worker_threads
        if self._gpu_active():
            n = min(n, GPU_WORKER_MAX)
            threads = self._threads_per_job(n)
            self.workers_hint.config(
                text=f"GPU encoder: max {GPU_WORKER_MAX} concurrent jobs, "
                f"{threads} thread(s)/job for scaling filters"
            )
            return
        n = max(1, min(self.cpu_count, n))
        threads = self._threads_per_job(n)
        pct = min(100, round(threads * n / self.cpu_count * 100))
        self.workers_hint.config(
            text=f"{threads} thread(s)/job x up to {n} parallel job(s), "
            f"~{pct}% of {self.cpu_count} logical CPUs"
        )

    def _threads_per_job(self, workers: int) -> int:
        """Threads each job gets: cores split across the jobs in flight."""
        jobs = len(self.jobs) if self.jobs else workers
        return converter.threads_for_job(self.cpu_count, min(workers, jobs))

    def edit_custom_crop(self) -> None:
        dialog = _CropDialog(self, self.custom_crop)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.custom_crop = dialog.result
            self.crop_label.set(CROP_CUSTOM)
        self._update_crop_desc()

    @staticmethod
    def _crop_for(
        label: str, custom: presets.Crop | None, job: Job
    ) -> presets.Crop | None:
        if label == CROP_NONE:
            return None
        if label == CROP_CUSTOM:
            return custom
        ratio = presets.ASPECT_PRESETS.get(label)
        if ratio is None or not job.width or not job.height:
            return None
        return presets.crop_for_aspect(job.width, job.height, ratio)

    # ---------------------------------------------------------- elevation
    def restart_as_admin(self) -> None:
        if not elevation.is_supported():
            messagebox.showinfo("Not available", "Elevation is Windows-only.")
            return
        if elevation.is_admin():
            messagebox.showinfo("Already elevated", "This session is already elevated.")
            return
        if messagebox.askyesno(
            "Restart as administrator",
            "Relaunch the app elevated? A UAC prompt will appear and the "
            "current window will close.",
        ):
            if elevation.relaunch_as_admin():
                self.destroy()
            else:
                messagebox.showerror("Failed", "Could not start the elevated app.")

    def _ensure_writable(self, out_dir: str | None) -> bool:
        if not out_dir:
            return True
        if elevation.folder_is_writable(out_dir):
            return True

        if elevation.is_supported() and not elevation.is_admin():
            if messagebox.askyesno(
                "Folder not writable",
                f"'{out_dir}' is not writable by this user.\n\n"
                "Restart as administrator so the app can write there?",
            ):
                if elevation.relaunch_as_admin():
                    self.destroy()
            return False

        messagebox.showerror(
            "Folder not writable",
            f"Cannot write to '{out_dir}'. Choose another output folder.",
        )
        return False

    # ------------------------------------------------------------- actions
    def add_files(self) -> None:
        if self._is_running():
            return
        paths = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm *.flv *.wmv *.m4v *.mpg *.mpeg *.ts"),
                ("All files", "*.*"),
            ],
        )
        self._add_paths(paths)

    def add_folder(self) -> None:
        if self._is_running():
            return
        folder = filedialog.askdirectory(title="Select a folder of videos")
        if not folder:
            return
        found = [
            str(p)
            for p in sorted(Path(folder).iterdir())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ]
        if not found:
            messagebox.showinfo("No videos", "No supported video files found.")
            return
        self._add_paths(found)

    def _add_paths(self, paths, artist: str | None = None) -> None:
        existing = {job.source for job in self.jobs}
        for path in paths or []:
            if path in existing:
                continue
            job = Job(
                source=path, preset_key=self.preset_label.get(), artist=artist
            )
            self.jobs.append(job)
            self._insert_job_row(job)
            self._probe_job_async(job)
        self.status_text.set(f"{len(self.jobs)} file(s) in queue")
        self._update_workers_hint()

    def _insert_job_row(self, job: Job) -> None:
        job.item_id = self.tree.insert(
            "",
            "end",
            values=(
                Path(job.source).name,
                "...",
                "...",
                job.status,
                "0%",
            ),
        )

    def _probe_job_async(self, job: Job) -> None:
        def work() -> None:
            info = ffmpeg.probe(job.source)
            self._ui_queue.put(("probe", job, info))

        threading.Thread(target=work, daemon=True).start()

    def remove_selected(self) -> None:
        if self._is_running():
            return
        for item in self.tree.selection():
            self.tree.delete(item)
            self.jobs = [job for job in self.jobs if job.item_id != item]
        self.status_text.set(f"{len(self.jobs)} file(s) in queue")
        self._update_workers_hint()

    def clear_queue(self) -> None:
        if self._is_running():
            messagebox.showwarning("Busy", "Stop the current run before clearing.")
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.jobs.clear()
        self.overall.set(0.0)
        self.status_text.set("Queue cleared")
        self._update_workers_hint()

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir.set(folder)
            self._save_config()

    # ---------------------------------------------------------- library
    def choose_source_root(self) -> None:
        folder = filedialog.askdirectory(
            title="Select the source folder", initialdir=self.source_root.get()
        )
        if folder:
            self.source_root.set(folder)
            self._save_config()
            self.refresh_library()

    def refresh_library(self) -> None:
        for item in self.library.get_children():
            self.library.delete(item)
        root = self.source_root.get().strip()
        if not root or not Path(root).is_dir():
            self.status_text.set(f"Source folder not found: {root}")
            return
        self.status_text.set("Scanning library...")

        def work() -> None:
            self._ui_queue.put(("library", self._scan_library(root)))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _scan_library(root: str) -> list[tuple[str, int]]:
        results: list[tuple[str, int]] = []
        base = Path(root)
        try:
            children = sorted(
                (p for p in base.iterdir() if p.is_dir()),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return results

        for folder in children:
            count = sum(
                1
                for p in folder.rglob("*")
                if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
            )
            results.append((folder.name, count))
        return results

    def add_selected_from_library(self) -> None:
        if self._is_running():
            return
        selection = self.library.selection()
        if not selection:
            return
        root = Path(self.source_root.get().strip())
        added = 0
        for item in selection:
            folder_name = self.library.item(item, "text")
            folder = root / folder_name
            if not folder.is_dir():
                continue
            videos = sorted(
                str(p)
                for p in folder.rglob("*")
                if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
            )
            if videos:
                self._add_paths(videos, artist=folder_name)
                added += len(videos)
        if added:
            self.status_text.set(f"Added {added} video(s) from library")

    # ----------------------------------------------------------- conversion
    def _is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.library_add_button,
        ):
            button.config(state=state)
        self.start_button.config(state=state)
        self.cancel_button.config(state="normal" if running else "disabled")
        self.workers_spin.config(state=state)
        self.encoder_combo.config(state=state)

    def start(self) -> None:
        if self._is_running():
            return
        if not self.jobs:
            messagebox.showinfo("Nothing to do", "Add some videos first.")
            return

        out_dir = self.output_dir.get().strip() or None
        
        # Prompt user to select output folder if not set
        if not out_dir:
            response = messagebox.askyesno(
                "Output Folder Required",
                "No output folder is set.\n\n"
                "Would you like to select an output folder now?\n\n"
                "(Click 'No' to save converted files next to the original files)",
                icon="question"
            )
            if response:
                folder = filedialog.askdirectory(title="Choose output folder")
                if folder:
                    out_dir = folder
                    self.output_dir.set(folder)
                    self._save_config()
                else:
                    return  # User cancelled folder selection
        
        # Create output folder if it doesn't exist
        if out_dir and not Path(out_dir).is_dir():
            try:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                self._log(f"Created output folder: {out_dir}")
            except OSError as exc:
                messagebox.showerror(
                    "Cannot create folder",
                    f"Could not create output folder:\n{out_dir}\n\n{exc}",
                )
                return
        if not self._ensure_writable(out_dir):
            return

        workers = self._clamp_workers()
        if self._gpu_active():
            self._log(
                f"Hardware encoding: capped to {workers} concurrent "
                f"job(s), 1 encoder session each",
                "gpu",
            )
        chosen = self.preset_label.get()
        for job in self.jobs:
            job.preset_key = chosen
            job.progress = 0.0
            job.status = "Queued"
            self._update_row(job)

        self._cancel_event.clear()
        self._set_running(True)
        self.overall.set(0.0)
        self.status_text.set(f"Converting with {workers} worker(s)...")

        gpu_option = self.gpu_label.get()
        gpu_encoder = self.gpu_encoders.get(gpu_option)
        if gpu_encoder is None and gpu_option == GPU_AUTO_LABEL:
            gpu_encoder = GPU_AUTO_LABEL

        config = {
            "out_dir": out_dir,
            "template": self.name_template.get(),
            "default_artist": self.artist.get(),
            "crop_label": self.crop_label.get(),
            "custom_crop": self.custom_crop,
            "workers": workers,
            "gpu_encoder": gpu_encoder,
        }
        self._worker = threading.Thread(
            target=self._run_jobs, args=(config,), daemon=True
        )
        self._worker.start()

    def _run_jobs(self, config: dict) -> None:
        jobs = list(self.jobs)
        total = len(jobs)
        workers = max(1, min(config.get("workers", 1), total))
        threads = converter.threads_for_job(self.cpu_count, workers)
        config["threads_per_job"] = threads
        self._log(
            f"Pool: {total} job(s), {workers} worker(s), "
            f"{threads} thread(s)/job on {self.cpu_count} logical CPU(s)"
        )

        work: queue.Queue = queue.Queue()
        for job in jobs:
            work.put(job)

        def worker() -> None:
            while not self._cancel_event.is_set():
                try:
                    job = work.get_nowait()
                except queue.Empty:
                    return
                try:
                    self._process_job(job, config)
                except Exception as exc:  # noqa: BLE001 - keep pool alive
                    job.status = f"Failed: {exc}"
                    self._log(f"Error: {job.source}: {exc}", "failed")
                    self._ui_queue.put(("row", job))
                finally:
                    work.task_done()

        threads = [
            threading.Thread(target=worker, daemon=True) for _ in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if self._cancel_event.is_set():
            for job in jobs:
                if job.status == "Queued":
                    job.status = "Cancelled"
                    self._ui_queue.put(("row", job))

        self._ui_queue.put(("finished", self._cancel_event.is_set()))

    def _process_job(self, job: Job, config: dict) -> None:
        if self._cancel_event.is_set():
            job.status = "Cancelled"
            self._ui_queue.put(("row", job))
            return

        preset = presets.preset_by_label(job.preset_key)
        artist = (
            job.artist if job.artist is not None else config["default_artist"]
        )
        destination = converter.build_output_path(
            job.source, preset, config["out_dir"], config["template"], artist
        )
        crop = self._crop_for(config["crop_label"], config["custom_crop"], job)
        gpu_option = config.get("gpu_encoder")
        gpu_encoder = self._resolve_gpu_encoder(preset, config)
        hwaccel = self._resolve_hwaccel(config)
        if gpu_option and gpu_encoder is None and not preset.palette_gif:
            self._log(
                f"No {'GPU encoder' if gpu_option == GPU_AUTO_LABEL else gpu_option} "
                f"for '{preset.key}' preset - using CPU",
                "gpu",
            )
        job.destination = destination
        job.status = "Converting"
        self._ui_queue.put(("row", job))
        self._log(f"Saving {Path(job.source).name} to: {destination}", "save")

        result = converter.convert(
            job.source,
            destination,
            preset,
            crop=crop,
            cancel_event=self._cancel_event,
            on_progress=lambda frac, msg, j=job: self._ui_queue.put(
                ("progress", j, frac, msg)
            ),
            threads=config.get("threads_per_job", 1),
            gpu_encoder=gpu_encoder,
            hwaccel=hwaccel,
        )

        if result.cancelled:
            job.status = "Cancelled"
            self._log(f"Cancelled: {destination}", "cancel")
        elif result.success:
            job.status = "Done"
            job.progress = 1.0
            self._log(f"Saved: {destination}", "done")
        else:
            job.status = f"Failed: {result.message}"
            self._log(f"Failed: {job.source}: {result.message}", "failed")
        self._ui_queue.put(("row", job))

    def cancel(self) -> None:
        if self._is_running():
            self._cancel_event.set()
            self.status_text.set("Cancelling...")

    # --------------------------------------------------------- UI pumping
    def _drain_ui_queue(self) -> None:
        try:
            while True:
                message = self._ui_queue.get_nowait()
                self._handle_message(message)
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def _handle_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "log":
            self._append_log(message[1], message[2] if len(message) > 2 else "info")
        elif kind == "probe":
            _, job, info = message
            job.width = info.width
            job.height = info.height
            if self.tree.exists(job.item_id):
                values = list(self.tree.item(job.item_id, "values"))
                values[1] = info.resolution
                values[2] = self._format_duration(info.duration)
                self.tree.item(job.item_id, values=values)
        elif kind == "row":
            self._update_row(message[1])
            self._recompute_overall()
        elif kind == "progress":
            _, job, frac, _msg = message
            job.progress = frac
            self._update_row(job)
            self._recompute_overall()
        elif kind == "overall":
            self.overall.set(message[1])
        elif kind == "library":
            entries = message[1]
            for item in self.library.get_children():
                self.library.delete(item)
            total = 0
            for name, count in entries:
                self.library.insert(
                    "", "end", text=name, values=(count,), iid=name
                )
                total += count
            self.status_text.set(
                f"{len(entries)} folder(s), {total} video(s) in library"
            )
        elif kind == "finished":
            cancelled = message[1]
            self._set_running(False)
            if cancelled:
                self.status_text.set("Cancelled")
                self._log("Conversion cancelled", "cancel")
            else:
                done = sum(1 for j in self.jobs if j.status == "Done")
                failed = sum(1 for j in self.jobs if j.status.startswith("Failed"))
                if self.jobs:
                    self.overall.set(done / len(self.jobs) * 100)
                text = f"Finished - {done}/{len(self.jobs)} succeeded"
                if failed:
                    text += f", {failed} failed"
                self.status_text.set(text)
                level = "failed" if failed else "done"
                self._log(text, level)
        elif kind == "gpu_detected":
            names: list[str] = message[1]
            self.gpu_devices = list(message[2]) if len(message) > 2 else []
            self.gpu_encoders = {
                presets.GPU_ENCODERS[name][0]: name for name in names
            }
            self.gpu_auto = presets.auto_encoder_map(names, self.gpu_devices)

            values = [CPU_LABEL]
            if self.gpu_auto:
                values.append(GPU_AUTO_LABEL)
            values += list(self.gpu_encoders)
            self.encoder_combo.configure(values=values)

            if self.gpu_auto:
                self.gpu_label.set(GPU_AUTO_LABEL)
            else:
                self.gpu_label.set(CPU_LABEL)
            self._update_encoder_hint()
            self._update_workers_hint()

            if self.gpu_devices:
                self._log(
                    f"Detected GPU(s): {', '.join(self.gpu_devices)}", "gpu"
                )
            if names:
                labels = ", ".join(
                    presets.GPU_ENCODERS[n][0].split("(")[0].strip() for n in names
                )
                auto_desc = ", ".join(
                    f"{f}:{n}" for f, n in sorted(self.gpu_auto.items())
                )
                gpu_desc = (
                    f" - {', '.join(self.gpu_devices)}"
                    if self.gpu_devices else ""
                )
                self.status_text.set(f"✓ Hardware acceleration ready: {labels}")
                self._log(f"Encoders detected and verified: {', '.join(names)}", "gpu")
                self._log(f"Auto selection: {auto_desc}{gpu_desc}", "gpu")
            else:
                self.status_text.set("No GPU encoders detected — using CPU (software encoding)")
                self._log(
                    "No hardware encoders available, falling back to CPU", "gpu"
                )
        
        elif kind == "update_check":
            info: update_checker.UpdateInfo = message[1]
            if info.available:
                self._show_update_dialog(info)

    def _update_row(self, job: Job) -> None:
        if not self.tree.exists(job.item_id):
            return
        values = list(self.tree.item(job.item_id, "values"))
        values[3] = job.status
        values[4] = f"{int(job.progress * 100)}%"
        self.tree.item(job.item_id, values=values)

    def _recompute_overall(self) -> None:
        if not self.jobs:
            return
        frac = sum(job.progress for job in self.jobs) / len(self.jobs)
        self.overall.set(frac * 100)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds <= 0:
            return "?"
        total = int(seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _check_ffmpeg(self) -> None:
        try:
            version, _ = ffmpeg.verify_ffmpeg()
        except ffmpeg.FFmpegNotFoundError as exc:
            self.status_text.set("FFmpeg not found")
            self._log(f"FFmpeg not found: {exc}", "failed")
            messagebox.showerror("FFmpeg not found", str(exc))
            return
        self.status_text.set(version)
        self._log(f"FFmpeg ready: {version}")
        out_dir = self.output_dir.get().strip()
        self._log(
            "Converted files will be saved to: "
            + (out_dir if out_dir else "the folder next to each source file")
        )

    def _detect_gpu(self) -> None:
        self.status_text.set("Detecting GPU encoders…")
        encoder_keys = list(presets.GPU_ENCODERS)

        def probe_thread() -> None:
            try:
                names = ffmpeg.verified_hardware_encoders(encoder_keys)
            except ffmpeg.FFmpegNotFoundError:
                names = []
            try:
                gpus = ffmpeg.detect_gpus()
            except Exception:
                gpus = []
            self._ui_queue.put(("gpu_detected", names, gpus))

        threading.Thread(target=probe_thread, daemon=True).start()

    def _check_for_updates(self) -> None:
        """Check for updates in a background thread."""
        def check_thread() -> None:
            info = update_checker.check_for_updates(timeout=3.0)
            if info:
                self._ui_queue.put(("update_check", info))

        threading.Thread(target=check_thread, daemon=True).start()

    def _update_encoder_hint(self) -> None:
        option = self.gpu_label.get()
        gpu_note = f"  ({' + '.join(self.gpu_devices)})" if self.gpu_devices else ""
        if option == GPU_AUTO_LABEL:
            preset = presets.preset_by_label(self.preset_label.get())
            family = preset.codec_family
            chosen = self.gpu_auto.get(family) if family else None
            if chosen:
                label = presets.GPU_ENCODERS[chosen][0].split("(")[0].strip()
                self.encoder_hint.config(
                    text=f"auto: {label} for this preset{gpu_note}"
                )
            elif preset.palette_gif:
                hwaccel = self._resolve_hwaccel({"gpu_encoder": option})
                if hwaccel:
                    self.encoder_hint.config(
                        text=f"auto: GPU {hwaccel} decode + scale for GIF{gpu_note}"
                    )
                else:
                    self.encoder_hint.config(
                        text="auto: CPU palette GIF (no GPU available)"
                    )
            elif not family:
                self.encoder_hint.config(text="auto: no video track in this preset")
            else:
                self.encoder_hint.config(
                    text=f"auto: no hardware {family} encoder - using CPU"
                )
        elif option in self.gpu_encoders:
            name = self.gpu_encoders[option]
            self.encoder_hint.config(text=f"forced encoder: {name}{gpu_note}")
        else:
            self.encoder_hint.config(
                text="no hardware encoder found - using CPU (x264/x265)"
            )

    def _resolve_gpu_encoder(
        self, preset: presets.Preset, config: dict
    ) -> str | None:
        option = config.get("gpu_encoder")
        if not option:
            return None
        if option == GPU_AUTO_LABEL:
            family = preset.codec_family
            return self.gpu_auto.get(family) if family else None
        return option

    def _resolve_hwaccel(self, config: dict) -> str | None:
        """Hardware acceleration kind for GPU decode/scale.

        Derived from the chosen GPU encoders rather than the codec family,
        because GIFs have no hardware encoder of their own yet can still
        decode and scale on the GPU.
        """
        option = config.get("gpu_encoder")
        if not option:
            return None
        if option == GPU_AUTO_LABEL:
            names = list(self.gpu_auto.values())
        else:
            name = self.gpu_encoders.get(option)
            names = [name] if name else []
        return presets.hwaccel_for_encoders(names)

    def _about(self) -> None:
        messagebox.showinfo(
            "About",
            f"FFmpeg Video Converter v{__version__}\n\n"
            "A local batch transcoder for format compatibility.\n"
            "Everything runs on your machine - no uploads, no accounts.\n\n"
            "https://github.com/ars1mm/ffmpeg-tool"
        )

    def _show_update_dialog(self, info: update_checker.UpdateInfo) -> None:
        """Show a dialog notifying the user of an available update."""
        import webbrowser
        
        notes = update_checker.format_release_notes(info.release_notes, max_lines=5)
        message = (
            f"A new version of FFmpeg Video Converter is available!\n\n"
            f"Current version: {info.current_version}\n"
            f"Latest version:  {info.latest_version}\n\n"
            f"What's new:\n{notes}\n\n"
            f"Would you like to download the update now?"
        )
        
        response = messagebox.askyesno(
            "Update Available",
            message,
            icon="info"
        )
        
        if response:
            webbrowser.open(info.download_url)
            self._log(f"Opening download page: {info.download_url}")

    def open_duplicates(self) -> None:
        if self._duplicates_window is not None:
            try:
                if self._duplicates_window.winfo_exists():  # type: ignore[attr-defined]
                    self._duplicates_window.lift()  # type: ignore[attr-defined]
                    return
            except tk.TclError:
                pass
        from video_converter import duplicates_panel

        self._duplicates_window = duplicates_panel.DuplicatesWindow(
            self, Path(self.source_root.get())
        )


class _CropDialog(tk.Toplevel):
    """Small modal dialog for a custom WxH+X+Y crop."""

    def __init__(self, parent: tk.Misc, current: presets.Crop | None) -> None:
        super().__init__(parent)
        self.title("Custom crop")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: presets.Crop | None = None

        self.width = tk.StringVar(value=str(current.width if current else 1280))
        self.height = tk.StringVar(value=str(current.height if current else 720))
        self.x = tk.StringVar(value=str(current.x if current else 0))
        self.y = tk.StringVar(value=str(current.y if current else 0))

        fields = (
            ("Width", self.width),
            ("Height", self.height),
            ("Offset X", self.x),
            ("Offset Y", self.y),
        )
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        for row, (text, var) in enumerate(fields):
            ttk.Label(body, text=text + ":").grid(row=row, column=0, sticky="w")
            ttk.Entry(body, textvariable=var, width=12).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=2
            )

        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok).pack(
            side="right", padx=(0, 6)
        )

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent: tk.Misc) -> None:
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")
        except tk.TclError:
            pass

    def _ok(self) -> None:
        try:
            width = int(self.width.get())
            height = int(self.height.get())
            x = int(self.x.get())
            y = int(self.y.get())
        except ValueError:
            messagebox.showerror("Invalid values", "Use whole numbers only.", parent=self)
            return
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            messagebox.showerror(
                "Invalid crop",
                "Width/height must be positive and offsets non-negative.",
                parent=self,
            )
            return
        self.result = presets.Crop(width=width, height=height, x=x, y=y)
        self.destroy()


def main() -> None:
    app = ConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
