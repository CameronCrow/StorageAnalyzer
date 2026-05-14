"""Tests for the pure-Python parallel walker and the scan() integration.

These exercise real filesystem trees built under tmp_path, so they run on any
OS even though the production target is Windows.
"""

import os
import sys

import pytest

from storageanalyzer.aggregate import aggregate
from storageanalyzer.fallback import walk
from storageanalyzer.scan import get_walker, scan

CONTRACT_KEYS = {
    "dir_path", "dir_own", "dir_recursive", "dir_files",
    "dir_parent", "dir_depth", "dir_denied", "top_files",
    "stats", "recursive_filled",
}


def _make_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)


@pytest.fixture
def tree(tmp_path):
    """A deep, wide synthetic tree with known sizes.

    root/
      a/f1 (100)  a/f2 (200)
      a/aa/f3 (300)
      a/aa/aaa/f4 (400)
      b/f5 (50)
      empty/            (no files)
    Total = 1050 bytes, 5 files, 6 directories (incl. root).
    """
    _make_file(tmp_path / "a" / "f1", 100)
    _make_file(tmp_path / "a" / "f2", 200)
    _make_file(tmp_path / "a" / "aa" / "f3", 300)
    _make_file(tmp_path / "a" / "aa" / "aaa" / "f4", 400)
    _make_file(tmp_path / "b" / "f5", 50)
    (tmp_path / "empty").mkdir()
    return tmp_path


def test_output_matches_contract(tree):
    result = walk(str(tree), threads=4, top_n=10)
    assert set(result) >= CONTRACT_KEYS
    n = len(result["dir_path"])
    for key in ("dir_own", "dir_recursive", "dir_files",
                "dir_parent", "dir_depth", "dir_denied"):
        assert len(result[key]) == n, f"{key} length mismatch"
    assert result["recursive_filled"] is False
    assert result["dir_parent"][0] == -1
    assert result["dir_depth"][0] == 0


def test_totals_are_correct(tree):
    result = walk(str(tree), threads=4, top_n=10)
    assert result["stats"]["files_scanned"] == 5
    assert result["stats"]["total_bytes"] == 1050
    assert result["stats"]["dirs_scanned"] == 6  # root, a, aa, aaa, b, empty


def test_recursive_rollup_via_aggregate(tree):
    result = walk(str(tree), threads=4, top_n=10)
    report = aggregate(result, top_dirs=10)
    assert report["tree"]["size"] == 1050
    by_path = {d["path"]: d for d in report["largest_dirs"]}
    a_dir = next(p for p in by_path if p.endswith("a") and not p.endswith("aa"))
    assert by_path[a_dir]["size"] == 1000  # 100+200+300+400
    aa_dir = next(p for p in by_path if p.endswith(os.sep + "aa"))
    assert by_path[aa_dir]["size"] == 700  # 300+400


def test_parent_indices_are_consistent(tree):
    result = walk(str(tree), threads=4, top_n=10)
    parents = result["dir_parent"]
    depths = result["dir_depth"]
    for i, p in enumerate(parents):
        if p == -1:
            assert depths[i] == 0
        else:
            assert p < i, "parent must precede child (BFS append order)"
            assert depths[i] == depths[p] + 1


def test_top_files_ranked(tree):
    result = walk(str(tree), threads=4, top_n=3)
    sizes = [s for _, s in result["top_files"]]
    assert sizes == [400, 300, 200]
    assert len(result["top_files"]) == 3


@pytest.mark.parametrize("threads", [1, 2, 4, 8, 16])
def test_termination_no_race(tree, threads):
    # Run repeatedly across thread counts; a termination race would hang or
    # drop records. Every run must produce the identical, complete result.
    for _ in range(8):
        result = walk(str(tree), threads=threads, top_n=10)
        assert result["stats"]["dirs_scanned"] == 6
        assert result["stats"]["files_scanned"] == 5
        assert result["stats"]["total_bytes"] == 1050


def test_access_denied_is_counted_not_crashed(tmp_path, monkeypatch):
    _make_file(tmp_path / "ok" / "f", 10)
    locked = tmp_path / "locked"
    locked.mkdir()
    _make_file(locked / "secret", 999)

    real_scandir = os.scandir

    def guarded_scandir(path):
        if os.path.basename(str(path).rstrip("\\/")) == "locked":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded_scandir)
    result = walk(str(tmp_path), threads=4, top_n=10)
    assert result["stats"]["denied_count"] == 1
    assert any(result["dir_denied"]), "denied dir should be flagged"
    # the rest of the scan still completed
    assert result["stats"]["files_scanned"] == 1


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"),
                    reason="needs symlink support")
def test_reparse_points_not_recursed(tmp_path):
    _make_file(tmp_path / "real" / "f", 100)
    link = tmp_path / "link"
    try:
        os.symlink(tmp_path / "real", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    result = walk(str(tmp_path), threads=4, top_n=10)
    # 'real' is counted once; 'link' must not add a second copy of f.
    assert result["stats"]["total_bytes"] == 100
    # link is either skipped or recorded as a leaf, never recursed
    paths = [p for p in result["dir_path"]]
    link_recs = [p for p in paths if p.endswith("link")]
    assert len(link_recs) <= 1


def test_hidden_toggle(tmp_path):
    _make_file(tmp_path / "visible.txt", 10)
    hidden = tmp_path / "hidden.dat"
    _make_file(hidden, 5000)
    if os.name == "nt":
        import subprocess
        subprocess.run(["attrib", "+H", str(hidden)], check=False)
    else:
        # emulate: dotfiles are not what fallback checks (it checks Win attrs),
        # so on non-Windows the toggle is effectively a no-op -- assert it at
        # least does not crash and counts the file.
        result = walk(str(tmp_path), threads=2, top_n=10)
        assert result["stats"]["files_scanned"] == 2
        return

    excluded = walk(str(tmp_path), threads=2, include_hidden=False, top_n=10)
    included = walk(str(tmp_path), threads=2, include_hidden=True, top_n=10)
    assert excluded["stats"]["total_bytes"] == 10
    assert included["stats"]["total_bytes"] == 5010


def test_empty_directory(tmp_path):
    result = walk(str(tmp_path), threads=4, top_n=10)
    assert result["stats"]["files_scanned"] == 0
    assert result["stats"]["total_bytes"] == 0
    assert result["stats"]["dirs_scanned"] == 1
    assert result["dir_parent"] == [-1]


def test_get_walker_python_engine():
    walker, name = get_walker("python")
    assert name == "python"
    assert walker is walk


def _native_built() -> bool:
    try:
        from storageanalyzer import _native_walker  # noqa: F401

        return True
    except ImportError:
        return False


def test_get_walker_native_engine():
    # The native extension is optional. If it built, --engine native must use
    # it; if it did not, --engine native must fail with a clear, actionable
    # RuntimeError -- never silently fall back.
    if _native_built():
        walker, name = get_walker("native")
        assert name == "native"
        assert callable(walker)
    else:
        with pytest.raises(RuntimeError, match="not available"):
            get_walker("native")


def test_get_walker_auto():
    # auto prefers native when available, otherwise the Python fallback.
    walker, name = get_walker("auto")
    if _native_built():
        assert name == "native"
        assert callable(walker)
    else:
        assert name == "python"
        assert walker is walk


@pytest.mark.skipif(not _native_built(), reason="native extension not built")
def test_native_matches_python(tree):
    # When both engines exist they must agree on every reported number --
    # they share one output contract.
    py_report = scan(str(tree), engine="python", threads=4)
    nat_report = scan(str(tree), engine="native", threads=4)
    assert py_report["stats"]["total_bytes"] == nat_report["stats"]["total_bytes"]
    assert py_report["stats"]["files_scanned"] == nat_report["stats"]["files_scanned"]
    assert py_report["stats"]["dirs_scanned"] == nat_report["stats"]["dirs_scanned"]
    assert py_report["tree"]["size"] == nat_report["tree"]["size"]
    py_files = sorted((f["path"], f["size"]) for f in py_report["largest_files"])
    nat_files = sorted((f["path"], f["size"]) for f in nat_report["largest_files"])
    assert py_files == nat_files


def test_get_walker_rejects_unknown():
    with pytest.raises(ValueError):
        get_walker("turbo")


def test_scan_end_to_end_produces_report_data(tree):
    report = scan(str(tree), engine="python", threads=4)
    assert report["stats"]["engine"] == "python"
    assert report["stats"]["total_bytes"] == 1050
    assert report["stats"]["files_scanned"] == 5
    assert report["tree"]["size"] == 1050
    assert "elapsed_seconds" in report["stats"]
    assert report["stats"]["threads"] == 4


def test_scan_rejects_non_directory(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        scan(str(f), engine="python")
