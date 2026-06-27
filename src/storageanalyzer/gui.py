"""Desktop GUI for StorageAnalyzer -- a single pywebview window.

The look and feel mirrors the PLC Crawler frontend: one native window with a
left sidebar of scan controls and a main "stage" that renders the interactive
HTML report *in the same window* (Edge WebView2 on Windows). No terminal, no
separate browser tab -- the report shows up where you launched the scan.

The window loads ``template.html`` (rendered with ``DATA = null``) and exposes
this module's :class:`Api` to JavaScript as ``window.pywebview.api``. Pressing
Scan calls :meth:`Api.scan`, which drives the same :func:`storageanalyzer.scan`
entry point the CLI uses, in-process, and hands the result dict straight back to
the page to render -- no on-disk round-trip. pywebview runs each ``js_api`` call
on a worker thread, so a long scan never freezes the window.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .report import render, write_report
from .scan import scan


def default_report_path() -> Path:
    """Default on-disk path for an exported HTML report (timestamped, in cwd)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / f"storageanalyzer-report-{stamp}.html"


class Api:
    """The object exposed to JS as ``window.pywebview.api``.

    Holds the last scan result so the report can be saved to disk, and a back
    reference to the window for the native folder / save dialogs (set by
    :func:`main` once the window exists).
    """

    def __init__(self) -> None:
        self._window: Any = None
        self._last: Optional[dict[str, Any]] = None

    # -- static info for building the controls ------------------------------ #
    def meta(self) -> dict[str, Any]:
        return {"version": __version__, "default_root": os.path.abspath(os.sep)}

    # -- native dialogs ----------------------------------------------------- #
    def pick_folder(self) -> str:
        """Open a native folder picker; return the chosen path ("" if cancelled)."""
        if self._window is None:
            return ""
        import webview

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return ""
        return result[0] if isinstance(result, (list, tuple)) else str(result)

    def save_report(self) -> str:
        """Write the last scan's report to a user-chosen path; return it ("" if
        nothing scanned yet or the save was cancelled)."""
        if self._window is None or self._last is None:
            return ""
        import webview

        chosen = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_report_path().name,
            file_types=("HTML report (*.html)", "All files (*.*)"),
        )
        if not chosen:
            return ""
        path = chosen[0] if isinstance(chosen, (list, tuple)) else str(chosen)
        write_report(self._last, path)
        return path

    # -- the scan ----------------------------------------------------------- #
    def scan(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a scan for ``params`` and return ``{"data": report_dict}`` or
        ``{"error": message}``. Never raises into JS."""
        p = params or {}
        root = str(p.get("root", "")).strip()
        if not root or not os.path.isdir(root):
            return {"error": f"Not a directory: {root or '(empty)'}"}
        threads = p.get("threads")
        if threads is not None:
            try:
                threads = int(threads)
            except (TypeError, ValueError):
                threads = None
            if threads is not None and threads < 1:
                return {"error": "Threads must be a positive integer."}
        started = time.perf_counter()
        try:
            data = scan(
                root,
                engine=str(p.get("engine", "auto")),
                threads=threads,
                include_hidden=bool(p.get("include_hidden", False)),
                top_files=max(1, int(p.get("top_files", 50) or 50)),
                top_dirs=max(1, int(p.get("top_dirs", 50) or 50)),
            )
        except Exception as exc:  # native-unbuilt RuntimeError, perms, etc.
            return {"error": str(exc)}
        data["stats"].setdefault(
            "elapsed_seconds", round(time.perf_counter() - started, 4)
        )
        self._last = data
        return {"data": data}


def main(argv: Optional[list[str]] = None) -> int:
    """Launch the pywebview window. Returns a process exit code."""
    try:
        import webview
    except ImportError:  # pragma: no cover - dependency missing from a stripped build
        print("error: pywebview is not installed (pip install pywebview).")
        return 1

    api = Api()
    window = webview.create_window(
        f"StorageAnalyzer {__version__}",
        html=render(None),
        js_api=api,
        width=1180,
        height=780,
        min_size=(880, 560),
    )
    api._window = window
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
