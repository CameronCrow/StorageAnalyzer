"""Native desktop GUI for StorageAnalyzer (Tkinter, standard library only).

This is a real native window -- not a web view. It drives the same
:func:`storageanalyzer.scan.scan` entry point the CLI uses, in-process, so the
GUI inherits the native/python engine selection, the parallel walk, and the
exact result contract for free. No new runtime dependency is introduced: Tk
ships with CPython on Windows and bundles cleanly into the PyInstaller exe.

The scan runs on a daemon worker thread; the result is handed back to the Tk
event loop through a queue that the main thread polls with ``after``. The Tk
widgets are therefore only ever touched from the main thread.

The rich squarified treemap still lives in the HTML report -- the "Open HTML
report" / "Save HTML report" actions render it on demand via
:func:`storageanalyzer.report.write_report`, reusing that whole feature rather
than reimplementing a treemap on a Tk canvas.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from ._format import format_size
from .report import write_report
from .scan import scan

# --------------------------------------------------------------------------- #
# Pure helpers (no Tk) -- kept import-light and unit-testable on any platform. #
# --------------------------------------------------------------------------- #


def default_report_path() -> Path:
    """Default on-disk path for an exported HTML report (timestamped, in cwd)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / f"storageanalyzer-report-{stamp}.html"


def summary_rows(report_data: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(label, value)`` pairs summarizing a scan for a key/value grid."""
    stats = report_data.get("stats", {})
    rows: list[tuple[str, str]] = [
        ("Root", report_data.get("root", "")),
        ("Engine", str(stats.get("engine", "n/a"))),
        ("Threads", str(stats.get("threads", "n/a"))),
        ("Files scanned", f"{stats.get('files_scanned', 0):,}"),
        ("Directories", f"{stats.get('dirs_scanned', 0):,}"),
        ("Total size", format_size(stats.get("total_bytes", 0))),
        ("Access denied", f"{stats.get('denied_count', 0):,}"),
    ]
    if stats.get("elapsed_seconds") is not None:
        rows.append(("Elapsed", f"{stats['elapsed_seconds']:.2f} s"))
    if not stats.get("include_hidden", False):
        rows.append(("Note", "hidden/system items skipped (enable to count them)"))
    return rows


def dir_row(entry: dict[str, Any]) -> tuple[str, str, str]:
    """Display columns for one 'largest directory' row: (size, files, path)."""
    return (format_size(entry["size"]), f"{entry.get('files', 0):,}", entry["path"])


def file_row(entry: dict[str, Any]) -> tuple[str, str]:
    """Display columns for one 'largest file' row: (size, path)."""
    return (format_size(entry["size"]), entry["path"])


# --------------------------------------------------------------------------- #
# Showing the report "in the app".                                            #
#                                                                              #
# The report is a self-contained JavaScript web app, which Tk cannot render.   #
# Rather than a normal browser tab we launch a Chromium browser (Edge first,   #
# then Chrome) in `--app` mode: a clean, borderless window with no tabs or     #
# address bar -- as close to "inside the app" as we get without taking a       #
# dependency. If no such browser is found we fall back to the default browser. #
# All stdlib (subprocess / shutil), so the zero-dependency promise holds.      #
# --------------------------------------------------------------------------- #


def find_app_browser() -> Optional[str]:
    """Path to a Chromium browser that supports ``--app`` mode (Edge, then
    Chrome), or ``None`` if neither is found."""
    if os.name != "nt":
        for name in ("microsoft-edge", "google-chrome", "chromium", "chrome"):
            found = shutil.which(name)
            if found:
                return found
        return None
    # Windows: probe the standard install locations, Edge before Chrome.
    relatives = [
        ("Microsoft", "Edge", "Application", "msedge.exe"),
        ("Google", "Chrome", "Application", "chrome.exe"),
    ]
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for parts in relatives:
            candidate = os.path.join(base, *parts)
            if os.path.isfile(candidate):
                return candidate
    return None


def app_window_argv(
    browser_path: str, uri: str, size: tuple[int, int] = (1200, 800)
) -> list[str]:
    """Build the argv that opens *uri* as a chromeless ``--app`` window."""
    width, height = size
    return [browser_path, f"--app={uri}", f"--window-size={width},{height}"]


def open_report_window(html_path: os.PathLike[str] | str) -> None:
    """Open an HTML report in a chromeless app window; fall back to the default
    browser if no Chromium browser is available."""
    uri = Path(html_path).resolve().as_uri()
    browser = find_app_browser()
    if browser:
        try:
            subprocess.Popen(app_window_argv(browser, uri))
            return
        except OSError:
            pass  # fall through to the default browser
    webbrowser.open(uri)


def _maybe_hide_console() -> None:
    """When the exe was double-clicked we exclusively own a console window;
    hide it so the GUI behaves like a real desktop app. No-op when launched from
    a shared terminal (so the user's shell is never hidden) or off Windows.
    Pure stdlib via ctypes."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        # GetConsoleProcessList reports how many processes share this console;
        # 1 means it is ours alone (a double-click), so it is safe to hide.
        buf = (ctypes.c_uint * 1)()
        if kernel32.GetConsoleProcessList(buf, 1) == 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Tk application                                                               #
# --------------------------------------------------------------------------- #


class StorageAnalyzerApp:
    """The main window: scan options, a live progress indicator, and results."""

    POLL_MS = 100

    def __init__(self, root: "object") -> None:
        # Imported lazily so the pure helpers above (and their tests) never
        # require a display / Tk to be importable.
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root

        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._scanning = False
        self._report_data: Optional[dict[str, Any]] = None
        self._dirs: list[dict[str, Any]] = []
        self._files: list[dict[str, Any]] = []
        self._dir_sort: tuple[str, bool] = ("size", True)
        self._file_sort: tuple[str, bool] = ("size", True)

        root.title(f"StorageAnalyzer {__version__}")
        root.geometry("960x680")
        root.minsize(720, 520)

        # Tk variables for the option controls.
        self.var_folder = tk.StringVar(value=os.path.abspath(os.sep))
        self.var_engine = tk.StringVar(value="auto")
        self.var_threads = tk.StringVar(value="")
        self.var_hidden = tk.BooleanVar(value=False)
        self.var_top_files = tk.StringVar(value="50")
        self.var_top_dirs = tk.StringVar(value="50")
        self.var_status = tk.StringVar(value="Pick a folder and press Scan.")

        self._build_controls()
        self._build_results()
        self._build_actions()

    # -- layout ------------------------------------------------------------- #

    def _build_controls(self) -> None:
        tk, ttk = self.tk, self.ttk
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(side=tk.TOP, fill=tk.X)

        # Folder picker row.
        row = ttk.Frame(frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Folder:").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=self.var_folder)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.btn_browse = ttk.Button(row, text="Browse…", command=self._browse)
        self.btn_browse.pack(side=tk.LEFT)

        # Options row.
        opts = ttk.Frame(frame)
        opts.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(opts, text="Engine:").pack(side=tk.LEFT)
        self.cmb_engine = ttk.Combobox(
            opts,
            textvariable=self.var_engine,
            values=("auto", "native", "python"),
            state="readonly",
            width=8,
        )
        self.cmb_engine.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="Threads:").pack(side=tk.LEFT)
        self.spn_threads = ttk.Spinbox(
            opts, from_=1, to=64, textvariable=self.var_threads, width=5
        )
        self.spn_threads.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="Top files:").pack(side=tk.LEFT)
        self.spn_top_files = ttk.Spinbox(
            opts, from_=1, to=10000, textvariable=self.var_top_files, width=7
        )
        self.spn_top_files.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="Top dirs:").pack(side=tk.LEFT)
        self.spn_top_dirs = ttk.Spinbox(
            opts, from_=1, to=10000, textvariable=self.var_top_dirs, width=7
        )
        self.spn_top_dirs.pack(side=tk.LEFT, padx=(4, 12))
        self.chk_hidden = ttk.Checkbutton(
            opts, text="Include hidden/system", variable=self.var_hidden
        )
        self.chk_hidden.pack(side=tk.LEFT)

        # Scan + progress row.
        run = ttk.Frame(frame)
        run.pack(fill=tk.X, pady=(8, 0))
        self.btn_scan = ttk.Button(run, text="Scan", command=self._start_scan)
        self.btn_scan.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(run, mode="indeterminate", length=160)
        self.progress.pack(side=tk.LEFT, padx=(10, 10))
        ttk.Label(run, textvariable=self.var_status).pack(side=tk.LEFT)

    def _build_results(self) -> None:
        tk, ttk = self.tk, self.ttk
        body = ttk.Frame(self.root, padding=(10, 0, 10, 0))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Summary key/value grid.
        self.summary = ttk.LabelFrame(body, text="Summary", padding=8)
        self.summary.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(self.summary, text="No scan yet.").grid(row=0, column=0, sticky="w")

        # Tabbed tables: largest folders / largest files.
        nb = ttk.Notebook(body)
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(8, 0))

        self.tree_dirs = self._make_tree(
            nb,
            columns=("size", "files", "path"),
            headings=(("size", "Size"), ("files", "Files"), ("path", "Path")),
            widths={"size": 110, "files": 80, "path": 640},
            on_sort=self._sort_dirs,
        )
        self.tree_files = self._make_tree(
            nb,
            columns=("size", "path"),
            headings=(("size", "Size"), ("path", "Path")),
            widths={"size": 110, "path": 720},
            on_sort=self._sort_files,
        )
        nb.add(self.tree_dirs.master, text="Largest folders")
        nb.add(self.tree_files.master, text="Largest files")

    def _build_actions(self) -> None:
        tk, ttk = self.tk, self.ttk
        bar = ttk.Frame(self.root, padding=10)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.btn_open = ttk.Button(
            bar, text="Open HTML report", command=self._open_report, state="disabled"
        )
        self.btn_open.pack(side=tk.LEFT)
        self.btn_save = ttk.Button(
            bar, text="Save HTML report…",
            command=self._save_report, state="disabled",
        )
        self.btn_save.pack(side=tk.LEFT, padx=(8, 0))

    def _make_tree(self, parent, columns, headings, widths, on_sort):
        """Build a scrollable, sortable Treeview inside its own frame."""
        ttk = self.ttk
        tk = self.tk
        holder = ttk.Frame(parent)
        tree = ttk.Treeview(holder, columns=columns, show="headings", selectmode="browse")
        for key, label in headings:
            tree.heading(key, text=label, command=lambda c=key: on_sort(c))
            anchor = "e" if key == "size" or key == "files" else "w"
            tree.column(key, width=widths.get(key, 120), anchor=anchor, stretch=(key == "path"))
        vsb = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        return tree

    # -- actions ------------------------------------------------------------ #

    def _browse(self) -> None:
        from tkinter import filedialog

        initial = self.var_folder.get() or os.path.abspath(os.sep)
        chosen = filedialog.askdirectory(initialdir=initial, mustexist=True)
        if chosen:
            self.var_folder.set(os.path.normpath(chosen))

    def _parse_int(self, value: str) -> Optional[int]:
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _start_scan(self) -> None:
        from tkinter import messagebox

        if self._scanning:
            return
        root = self.var_folder.get().strip()
        if not root or not os.path.isdir(root):
            messagebox.showerror("StorageAnalyzer", f"Not a directory:\n{root}")
            return

        threads = self._parse_int(self.var_threads.get())
        if self.var_threads.get().strip() and (threads is None or threads < 1):
            messagebox.showerror("StorageAnalyzer", "Threads must be a positive integer.")
            return
        top_files = self._parse_int(self.var_top_files.get()) or 50
        top_dirs = self._parse_int(self.var_top_dirs.get()) or 50

        params = dict(
            root=root,
            engine=self.var_engine.get(),
            threads=threads,
            include_hidden=self.var_hidden.get(),
            top_files=max(1, top_files),
            top_dirs=max(1, top_dirs),
        )

        self._set_scanning(True)
        self.var_status.set(f"Scanning {root} …")
        worker = threading.Thread(target=self._run_scan, args=(params,), daemon=True)
        worker.start()
        self.root.after(self.POLL_MS, self._poll)

    def _run_scan(self, params: dict[str, Any]) -> None:
        """Worker-thread body. Never touches Tk; reports back via the queue."""
        try:
            data = scan(**params)
            self._queue.put(("ok", data))
        except BaseException as exc:  # surface RuntimeError (native unbuilt), etc.
            self._queue.put(("error", exc))

    def _poll(self) -> None:
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            if self._scanning:
                self.root.after(self.POLL_MS, self._poll)
            return

        self._set_scanning(False)
        if kind == "ok":
            self._report_data = payload
            self._populate(payload)
            stats = payload.get("stats", {})
            self.var_status.set(
                f"Done: {stats.get('files_scanned', 0):,} files, "
                f"{format_size(stats.get('total_bytes', 0))} in "
                f"{stats.get('elapsed_seconds', 0):.2f} s."
            )
            self.btn_open.config(state="normal")
            self.btn_save.config(state="normal")
            # Pop the interactive report open as soon as the scan finishes.
            self._open_report()
        else:
            from tkinter import messagebox

            self.var_status.set("Scan failed.")
            messagebox.showerror("StorageAnalyzer", f"Scan failed:\n{payload}")

    def _set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        state = "disabled" if scanning else "normal"
        for widget in (
            self.btn_scan, self.btn_browse, self.spn_threads,
            self.spn_top_files, self.spn_top_dirs, self.chk_hidden,
        ):
            widget.config(state=state)
        self.cmb_engine.config(state="disabled" if scanning else "readonly")
        if scanning:
            self.progress.start(12)
        else:
            self.progress.stop()

    # -- results rendering -------------------------------------------------- #

    def _populate(self, data: dict[str, Any]) -> None:
        for child in self.summary.winfo_children():
            child.destroy()
        for i, (label, value) in enumerate(summary_rows(data)):
            r, c = divmod(i, 2)
            cell = self.ttk.Frame(self.summary)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 24), pady=1)
            self.ttk.Label(cell, text=f"{label}:", width=14, anchor="w").pack(side=self.tk.LEFT)
            self.ttk.Label(cell, text=value).pack(side=self.tk.LEFT)

        self._dirs = list(data.get("largest_dirs", []))
        self._files = list(data.get("largest_files", []))
        self._render_dirs()
        self._render_files()

    def _render_dirs(self) -> None:
        key, reverse = self._dir_sort
        keyfn = (lambda d: d["path"].lower()) if key == "path" else (lambda d: d.get(key, 0))
        self._dirs.sort(key=keyfn, reverse=reverse)
        self.tree_dirs.delete(*self.tree_dirs.get_children())
        for d in self._dirs:
            self.tree_dirs.insert("", "end", values=dir_row(d))

    def _render_files(self) -> None:
        key, reverse = self._file_sort
        keyfn = (lambda f: f["path"].lower()) if key == "path" else (lambda f: f.get(key, 0))
        self._files.sort(key=keyfn, reverse=reverse)
        self.tree_files.delete(*self.tree_files.get_children())
        for f in self._files:
            self.tree_files.insert("", "end", values=file_row(f))

    def _sort_dirs(self, col: str) -> None:
        key, reverse = self._dir_sort
        self._dir_sort = (col, not reverse if col == key else True)
        self._render_dirs()

    def _sort_files(self, col: str) -> None:
        key, reverse = self._file_sort
        self._file_sort = (col, not reverse if col == key else True)
        self._render_files()

    # -- HTML report export ------------------------------------------------- #

    def _open_report(self) -> None:
        if not self._report_data:
            return
        from tkinter import messagebox

        try:
            tmp = Path(tempfile.gettempdir()) / default_report_path().name
            write_report(self._report_data, tmp)
            open_report_window(tmp)
        except Exception as exc:
            messagebox.showerror("StorageAnalyzer", f"Could not open report:\n{exc}")

    def _save_report(self) -> None:
        if not self._report_data:
            return
        from tkinter import filedialog, messagebox

        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML report", "*.html"), ("All files", "*.*")],
            initialfile=default_report_path().name,
        )
        if not path:
            return
        try:
            write_report(self._report_data, path)
            self.var_status.set(f"Report saved to {path}")
        except Exception as exc:
            messagebox.showerror("StorageAnalyzer", f"Could not save report:\n{exc}")


def main(argv: Optional[list[str]] = None) -> int:
    """Launch the GUI. Returns a process exit code."""
    _maybe_hide_console()
    try:
        import tkinter as tk
    except ImportError:  # pragma: no cover - tkinter missing from a stripped build
        print("error: Tkinter is not available in this Python build.")
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display / headless session
        print(f"error: could not open a display for the GUI: {exc}")
        return 1

    StorageAnalyzerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
