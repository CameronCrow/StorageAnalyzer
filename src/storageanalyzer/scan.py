"""Engine selection and the normalized ``scan()`` entry point.

Two walkers exist behind one contract:
  * ``storageanalyzer._native_walker`` -- the compiled C++ extension (fast).
  * ``storageanalyzer.fallback``      -- a pure-Python parallel walker.

Both return the same columnar dict; ``aggregate`` consumes either. The native
extension is optional: if it was never built, ``auto`` transparently uses the
Python walker.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from .aggregate import aggregate


def get_walker(engine: str = "auto") -> tuple[Callable[..., dict], str]:
    """Return ``(walk_callable, engine_name)`` for the requested engine.

    ``engine`` is one of:
      * ``auto``   -- native if available, else the Python fallback.
      * ``native`` -- native only; raises ``RuntimeError`` if not built.
      * ``python`` -- always the pure-Python fallback.
    """
    if engine not in ("auto", "native", "python"):
        raise ValueError(f"unknown engine {engine!r}")

    if engine == "python":
        from .fallback import walk

        return walk, "python"

    if engine == "native":
        try:
            from . import _native_walker  # type: ignore[attr-defined]
        except ImportError as exc:
            raise RuntimeError(
                "the native walker is not available -- it was not built "
                "(no C++ compiler at install time). Use --engine python, or "
                "install Visual Studio Build Tools and reinstall."
            ) from exc
        return _native_walker.walk, "native"

    # auto
    try:
        from . import _native_walker  # type: ignore[attr-defined]

        return _native_walker.walk, "native"
    except ImportError:
        from .fallback import walk

        return walk, "python"


def scan(
    root: str,
    *,
    engine: str = "auto",
    threads: int | None = None,
    include_hidden: bool = False,
    top_files: int = 50,
    top_dirs: int = 50,
    prune_threshold: float = 0.001,
) -> dict[str, Any]:
    """Scan ``root`` and return a report-ready aggregated dict.

    The returned dict is exactly what ``report.write_report`` expects.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(f"not a directory: {root}")

    if threads is None:
        cpu = os.cpu_count() or 4
        threads = min(16, max(2, cpu))

    walk, engine_name = get_walker(engine)
    # top_n for the walker must cover the largest table it needs to feed.
    walk_result = walk(
        root,
        threads=threads,
        include_hidden=include_hidden,
        top_n=max(top_files, 1),
    )

    report_data = aggregate(
        walk_result,
        top_files=top_files,
        top_dirs=top_dirs,
        prune_threshold=prune_threshold,
    )
    report_data["stats"]["engine"] = engine_name
    report_data["stats"]["include_hidden"] = include_hidden
    report_data["stats"].setdefault("threads", threads)
    # carry walker-reported timing/counters through if aggregate did not.
    for key in ("elapsed_seconds", "files_scanned"):
        if key in walk_result.get("stats", {}):
            report_data["stats"].setdefault(key, walk_result["stats"][key])
    return report_data
