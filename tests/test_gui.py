"""Tests for the native GUI.

The pure helpers (size/row/summary formatting, default report path) are tested
directly -- they never touch Tk. Constructing the actual window requires a
display, so that smoke test is skipped when no display is available (e.g. a
headless CI box) rather than failing.
"""

import pytest

from storageanalyzer import gui


def _report_data():
    return {
        "root": r"C:\demo",
        "tree": {"name": r"C:\demo", "size": 300, "own": 0, "files": 0},
        "largest_files": [
            {"path": r"C:\demo\a\big.bin", "size": 150},
            {"path": r"C:\demo\b\small.txt", "size": 10},
        ],
        "largest_dirs": [
            {"path": r"C:\demo\a", "size": 200, "own": 200, "files": 2},
            {"path": r"C:\demo\b", "size": 100, "own": 100, "files": 1},
        ],
        "denied_dirs": [],
        "stats": {
            "total_bytes": 300,
            "files_scanned": 3,
            "dirs_scanned": 3,
            "denied_count": 0,
            "engine": "python",
            "threads": 4,
            "elapsed_seconds": 0.12,
            "include_hidden": False,
        },
    }


def test_default_report_path_is_timestamped_html():
    path = gui.default_report_path()
    assert path.name.startswith("storageanalyzer-report-")
    assert path.suffix == ".html"


def test_summary_rows_cover_key_stats():
    rows = dict(gui.summary_rows(_report_data()))
    assert rows["Root"] == r"C:\demo"
    assert rows["Engine"] == "python"
    assert rows["Files scanned"] == "3"
    assert rows["Total size"] == "300 B"
    assert rows["Elapsed"] == "0.12 s"
    # hidden/system note shown only when they were skipped
    assert "Note" in rows


def test_summary_rows_omit_note_when_hidden_included():
    data = _report_data()
    data["stats"]["include_hidden"] = True
    rows = dict(gui.summary_rows(data))
    assert "Note" not in rows


def test_dir_and_file_rows_format_sizes():
    data = _report_data()
    assert gui.dir_row(data["largest_dirs"][0]) == ("200 B", "2", r"C:\demo\a")
    assert gui.file_row(data["largest_files"][0]) == ("150 B", r"C:\demo\a\big.bin")


def test_app_constructs_when_display_available():
    """Smoke test: build the window and verify it renders results. Skips headless."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    try:
        root.withdraw()
        app = gui.StorageAnalyzerApp(root)
        app._populate(_report_data())
        assert len(app.tree_dirs.get_children()) == 2
        assert len(app.tree_files.get_children()) == 2
        # default sort is by size, descending -> largest folder first
        first = app.tree_dirs.item(app.tree_dirs.get_children()[0])["values"]
        assert first[2] == r"C:\demo\a"
    finally:
        root.destroy()
