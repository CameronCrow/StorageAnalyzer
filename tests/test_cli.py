"""Tests for the CLI entry point's dispatch.

The exe/console command opens the desktop GUI when launched with no arguments
and runs the command-line scanner when given any. These tests pin that routing
without standing up Tk or running a real scan.
"""

from storageanalyzer import cli, gui


def test_no_args_launches_gui(monkeypatch):
    calls = []
    monkeypatch.setattr(gui, "main", lambda *a, **k: (calls.append("gui"), 0)[1])
    assert cli.main([]) == 0
    assert calls == ["gui"]


def test_gui_flag_launches_gui(monkeypatch):
    calls = []
    monkeypatch.setattr(gui, "main", lambda *a, **k: (calls.append("gui"), 0)[1])
    assert cli.main(["--gui"]) == 0
    assert calls == ["gui"]


def test_path_arg_routes_to_cli(monkeypatch, tmp_path):
    # A path argument must go to the scanner, not the GUI. A bogus path takes the
    # CLI validation path (exit 2), which proves we did not open the window.
    monkeypatch.setattr(
        gui, "main", lambda *a, **k: pytest_fail("GUI launched for a path arg")
    )
    missing = tmp_path / "does-not-exist"
    assert cli.main([str(missing)]) == 2


def pytest_fail(msg):  # tiny helper so the lambda above stays readable
    raise AssertionError(msg)
