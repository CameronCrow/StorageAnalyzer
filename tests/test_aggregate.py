"""Tests for the columnar -> tree rollup, top-N tables, and pruning."""

from storageanalyzer.aggregate import aggregate


def _columnar(recursive_filled=False):
    """A small synthetic tree (BFS order: parents before children).

    0  root
    1   root\\big        (own 100)
    2   root\\small      (own 5)
    3   root\\big\\sub   (own 900)
    """
    dir_path = [r"root", r"root\big", r"root\small", r"root\big\sub"]
    dir_own = [10, 100, 5, 900]
    dir_files = [1, 2, 1, 3]
    dir_parent = [-1, 0, 0, 1]
    dir_depth = [0, 1, 1, 2]
    dir_denied = [False, False, True, False]
    result = {
        "dir_path": dir_path,
        "dir_own": dir_own,
        "dir_recursive": [0, 0, 0, 0],
        "dir_files": dir_files,
        "dir_parent": dir_parent,
        "dir_depth": dir_depth,
        "dir_denied": dir_denied,
        "top_files": [
            (r"root\big\sub\huge.bin", 800),
            (r"root\big\a.txt", 90),
            (r"root\small\s.txt", 5),
        ],
        "stats": {"files_scanned": 7},
        "recursive_filled": recursive_filled,
    }
    if recursive_filled:
        # 3 -> 900 ; 1 -> 100 + 900 = 1000 ; 2 -> 5 ; 0 -> 10+1000+5 = 1015
        result["dir_recursive"] = [1015, 1000, 5, 900]
    return result


def test_recursive_rollup_from_own_sizes():
    out = aggregate(_columnar(recursive_filled=False))
    assert out["tree"]["size"] == 1015
    big = next(c for c in out["tree"]["children"] if c["name"].endswith("big"))
    assert big["size"] == 1000
    sub = next(c for c in big["children"] if c["name"].endswith("sub"))
    assert sub["size"] == 900


def test_recursive_filled_is_trusted():
    out = aggregate(_columnar(recursive_filled=True))
    assert out["tree"]["size"] == 1015
    # both paths must agree
    out2 = aggregate(_columnar(recursive_filled=False))
    assert out["tree"]["size"] == out2["tree"]["size"]


def test_largest_dirs_sorted_desc():
    out = aggregate(_columnar(), top_dirs=10)
    sizes = [d["size"] for d in out["largest_dirs"]]
    assert sizes == sorted(sizes, reverse=True)
    assert out["largest_dirs"][0]["path"] == "root"
    assert out["largest_dirs"][0]["size"] == 1015


def test_largest_files_sorted_and_capped():
    out = aggregate(_columnar(), top_files=2)
    assert len(out["largest_files"]) == 2
    assert out["largest_files"][0]["size"] == 800
    assert out["largest_files"][1]["size"] == 90


def test_denied_count_derived():
    out = aggregate(_columnar())
    assert out["stats"]["denied_count"] == 1
    assert out["stats"]["dirs_scanned"] == 4
    assert out["stats"]["total_bytes"] == 1015


def test_denied_dirs_listed_and_sorted():
    out = aggregate(_columnar())
    assert out["denied_dirs"] == [r"root\small"]
    # count and list always agree
    assert len(out["denied_dirs"]) == out["stats"]["denied_count"]


def test_denied_dirs_empty_when_none():
    result = _columnar()
    result["dir_denied"] = [False] * 4
    out = aggregate(result)
    assert out["denied_dirs"] == []
    assert out["stats"]["denied_count"] == 0


def test_pruning_collapses_subthreshold_children():
    # root has one giant child and many tiny ones; tiny ones should collapse.
    dir_path = ["root"] + [f"root\\tiny{i}" for i in range(20)] + ["root\\giant"]
    dir_own = [0] + [1] * 20 + [1_000_000]
    dir_files = [0] * 22
    dir_parent = [-1] + [0] * 21
    dir_depth = [0] + [1] * 21
    dir_denied = [False] * 22
    result = {
        "dir_path": dir_path,
        "dir_own": dir_own,
        "dir_recursive": [0] * 22,
        "dir_files": dir_files,
        "dir_parent": dir_parent,
        "dir_depth": dir_depth,
        "dir_denied": dir_denied,
        "top_files": [],
        "stats": {},
        "recursive_filled": False,
    }
    out = aggregate(result, prune_threshold=0.001)
    kids = out["tree"]["children"]
    other = [c for c in kids if c.get("other")]
    assert len(other) == 1
    assert other[0]["size"] == 20
    assert "20 smaller folders" in other[0]["name"]
    # the giant child survives pruning
    assert any(c["name"].endswith("giant") for c in kids)
    # all directories still appear in the full top-N table
    assert len(out["largest_dirs"]) == 22


def test_empty_walk_result():
    out = aggregate({
        "dir_path": [], "dir_own": [], "dir_recursive": [], "dir_files": [],
        "dir_parent": [], "dir_depth": [], "dir_denied": [],
        "top_files": [], "stats": {}, "recursive_filled": False,
    })
    assert out["tree"]["size"] == 0
    assert out["largest_dirs"] == []
    assert out["largest_files"] == []
