"""Roll a columnar walk result up into a pruned nested tree plus top-N tables.

The walkers (native C++ and the pure-Python fallback) both emit the same
columnar dict::

    {
        "dir_path":      [str, ...]   # one entry per directory, BFS order
        "dir_own":       [int, ...]   # bytes of files directly in this dir
        "dir_recursive": [int, ...]   # bytes including all descendants (0 if not filled)
        "dir_files":     [int, ...]   # count of files directly in this dir
        "dir_parent":    [int, ...]   # index into these arrays, -1 for the root
        "dir_depth":     [int, ...]   # 0 for the root
        "dir_denied":    [bool, ...]  # access was denied enumerating this dir
        "top_files":     [(path, size), ...]   # globally largest files, any order
        "stats":         {...}        # walker-reported counters
        "recursive_filled": bool      # True if dir_recursive is already populated
    }

``aggregate`` returns a plain dict that ``report`` can embed directly as JSON.
"""

from __future__ import annotations

from typing import Any


def _fill_recursive(parent: list[int], own: list[int]) -> list[int]:
    """Compute recursive sizes from own sizes given BFS-ordered records.

    Records are appended parents-before-children, so iterating in reverse
    guarantees a child's recursive size is final before its parent reads it.
    """
    recursive = list(own)
    for i in range(len(recursive) - 1, 0, -1):
        p = parent[i]
        if p >= 0:
            recursive[p] += recursive[i]
    return recursive


def _build_tree(
    dir_path: list[str],
    own: list[int],
    recursive: list[int],
    dir_files: list[int],
    parent: list[int],
    children: list[list[int]],
    idx: int,
    root_total: int,
    threshold: float,
) -> dict[str, Any]:
    """Build the nested node for ``idx``, pruning sub-threshold descendants.

    Children whose recursive size is below ``threshold`` of the root total are
    collapsed into a single synthetic ``(other)`` node so a full-drive scan
    does not embed a multi-megabyte tree. The top-N tables keep full detail.
    """
    node: dict[str, Any] = {
        "name": dir_path[idx],
        "size": recursive[idx],
        "own": own[idx],
        "files": dir_files[idx],
    }

    kids = children[idx]
    if not kids:
        return node

    cutoff = root_total * threshold
    visible: list[dict[str, Any]] = []
    other_size = 0
    other_count = 0
    for c in kids:
        if recursive[c] >= cutoff:
            visible.append(
                _build_tree(
                    dir_path, own, recursive, dir_files, parent,
                    children, c, root_total, threshold,
                )
            )
        else:
            other_size += recursive[c]
            other_count += 1

    visible.sort(key=lambda n: n["size"], reverse=True)
    if other_count:
        visible.append({
            "name": f"({other_count} smaller folders)",
            "size": other_size,
            "own": 0,
            "files": 0,
            "other": True,
        })
    if visible:
        node["children"] = visible
    return node


def aggregate(
    walk_result: dict[str, Any],
    top_files: int = 50,
    top_dirs: int = 50,
    prune_threshold: float = 0.001,
) -> dict[str, Any]:
    """Turn a columnar walk result into a report-ready dict.

    ``prune_threshold`` is the fraction of the root's recursive size below
    which a directory is folded into an ``(other)`` aggregate in the tree.
    """
    dir_path = walk_result["dir_path"]
    own = walk_result["dir_own"]
    dir_files = walk_result["dir_files"]
    parent = walk_result["dir_parent"]
    denied = walk_result["dir_denied"]

    if walk_result.get("recursive_filled"):
        recursive = list(walk_result["dir_recursive"])
    else:
        recursive = _fill_recursive(parent, own)

    n = len(dir_path)
    children: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        p = parent[i]
        if p >= 0:
            children[p].append(i)

    root_total = recursive[0] if n else 0

    tree = (
        _build_tree(
            dir_path, own, recursive, dir_files, parent, children,
            0, root_total or 1, prune_threshold,
        )
        if n
        else {"name": "", "size": 0, "own": 0, "files": 0}
    )

    largest_dirs = sorted(
        (
            {
                "path": dir_path[i],
                "size": recursive[i],
                "own": own[i],
                "files": dir_files[i],
            }
            for i in range(n)
        ),
        key=lambda d: d["size"],
        reverse=True,
    )[:top_dirs]

    largest_files = sorted(
        (
            {"path": p, "size": s}
            for p, s in walk_result.get("top_files", [])
        ),
        key=lambda f: f["size"],
        reverse=True,
    )[:top_files]

    denied_dirs = sorted(dir_path[i] for i in range(n) if denied[i])

    stats = dict(walk_result.get("stats", {}))
    stats.setdefault("dirs_scanned", n)
    stats.setdefault("denied_count", len(denied_dirs))
    stats.setdefault("total_bytes", root_total)

    return {
        "root": dir_path[0] if n else "",
        "tree": tree,
        "largest_files": largest_files,
        "largest_dirs": largest_dirs,
        "denied_dirs": denied_dirs,
        "stats": stats,
    }
