"""Tests for the pywebview desktop shell.

The GUI is one pywebview window whose JS calls into :class:`gui.Api`. Those API
methods are plain Python (no window, no display needed for the scan path), so we
exercise them directly: a real in-process scan of a temp tree, error handling,
and the empty live-app page the window loads before the first scan.
"""

import os

from storageanalyzer import gui
from storageanalyzer.report import render


def test_default_report_path_is_timestamped_html():
    path = gui.default_report_path()
    assert path.name.startswith("storageanalyzer-report-")
    assert path.suffix == ".html"


def test_meta_reports_version_and_root():
    meta = gui.Api().meta()
    assert meta["version"]
    assert os.path.isdir(meta["default_root"])


def test_scan_rejects_non_directory():
    res = gui.Api().scan({"root": r"C:\definitely\not\a\real\dir\xyzzy"})
    assert "error" in res and "Not a directory" in res["error"]


def test_scan_rejects_bad_threads(tmp_path):
    res = gui.Api().scan({"root": str(tmp_path), "threads": 0})
    assert "error" in res


def test_scan_runs_in_process_and_returns_data(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "big.bin").write_bytes(b"x" * 4096)
    (tmp_path / "small.txt").write_text("hi", encoding="utf-8")

    api = gui.Api()
    res = api.scan({"root": str(tmp_path), "engine": "python", "threads": 2})
    assert "data" in res
    data = res["data"]
    assert data["root"] == os.path.abspath(str(tmp_path))
    assert data["stats"]["files_scanned"] >= 2
    assert data["stats"]["elapsed_seconds"] is not None
    # the result is retained so a subsequent Save can write it
    assert api._last is data


def test_render_none_is_the_live_app_shell():
    html = render(None)
    assert "/*DATA*/" not in html
    assert "const DATA = null;" in html
    assert html.lstrip().startswith("<!DOCTYPE html>")
