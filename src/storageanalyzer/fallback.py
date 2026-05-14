"""Pure-Python parallel directory walker.

This is the fallback engine used when the native C++ walker is not built
(e.g. no compiler installed). It is a fully-functional, first-class code path,
not a degraded stub.

It emits the **exact same columnar contract** as ``native/walker.cpp`` so
``aggregate`` and ``report`` are walker-agnostic. The one difference is that
this walker returns ``recursive_filled=False`` and lets ``aggregate`` do the
recursive-size rollup in Python.

Design mirrors the native side:
  * ``os.scandir`` enumeration -- on Windows ``DirEntry.stat()`` is satisfied
    from the directory enumeration itself, so there is no extra per-file
    syscall (same property the native walker exploits with FindFirstFileExW).
  * A fixed worker pool drains a shared job queue. Termination is reached when
    the queue is empty *and* no worker is mid-job (``active == 0``); the
    condition variable wakes idle workers so they can observe that state.
  * Records are appended parents-before-children, and each directory's child
    records are reserved before its child jobs are queued, so ``dir_parent``
    linkage is known up front and every worker only ever writes its own slot.
  * Reparse points (junctions/symlinks) are recorded as leaves and never
    recursed -- avoids cycles and double-counting.
  * Access-denied directories are marked and counted; the scan continues.
"""

from __future__ import annotations

import heapq
import os
import threading
import time
from typing import Any

# Win32 file attribute bits (also defined on non-Windows for test portability).
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _long_path(path: str) -> str:
    r"""Apply the ``\\?\`` prefix so enumeration is not bound by MAX_PATH."""
    if os.name != "nt":
        return path
    if path.startswith("\\\\?\\"):
        return path
    abspath = os.path.abspath(path)
    if abspath.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abspath[2:]
    return "\\\\?\\" + abspath


def _display_path(path: str) -> str:
    r"""Strip the ``\\?\`` prefix for human-facing output."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _attrs(entry: os.DirEntry) -> int:
    try:
        return entry.stat(follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return 0


class _Walker:
    def __init__(self, root: str, threads: int, include_hidden: bool, top_n: int):
        self.include_hidden = include_hidden
        self.top_n = top_n
        self.threads = max(1, threads)

        # Columnar record arrays -- index i describes one directory.
        self.dir_path: list[str] = []
        self.dir_own: list[int] = []
        self.dir_files: list[int] = []
        self.dir_parent: list[int] = []
        self.dir_depth: list[int] = []
        self.dir_denied: list[bool] = []

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._jobs: list[tuple[int, str]] = []   # (record_index, real_path)
        self._active = 0

        self._files_scanned = 0
        self._bytes_total = 0
        self._denied_count = 0

        # Each worker keeps a thread-local size-N min-heap of (size, path);
        # merged at the end. Avoids a global lock per file.
        self._local_heaps: list[list[tuple[int, str]]] = [
            [] for _ in range(self.threads)
        ]

        real_root = _long_path(root)
        idx = self._add_record(_display_path(real_root), parent=-1, depth=0)
        self._jobs.append((idx, real_root))

    def _add_record(self, display: str, parent: int, depth: int) -> int:
        self.dir_path.append(display)
        self.dir_own.append(0)
        self.dir_files.append(0)
        self.dir_parent.append(parent)
        self.dir_depth.append(depth)
        self.dir_denied.append(False)
        return len(self.dir_path) - 1

    def _hidden(self, attrs: int) -> bool:
        return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))

    def _process(self, worker_id: int, idx: int, real_path: str) -> None:
        """Enumerate one directory: tally its own files, queue child dirs."""
        own_bytes = 0
        own_files = 0
        child_jobs: list[tuple[int, str]] = []
        heap = self._local_heaps[worker_id]
        depth = self.dir_depth[idx]

        try:
            it = os.scandir(real_path)
        except (PermissionError, OSError):
            with self._lock:
                self.dir_denied[idx] = True
                self._denied_count += 1
            return

        try:
            for entry in it:
                try:
                    attrs = _attrs(entry)
                    if not self.include_hidden and self._hidden(attrs):
                        continue
                    is_reparse = bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)

                    if entry.is_dir(follow_symlinks=False) and not is_reparse:
                        # child record is reserved below, under the lock
                        child_jobs.append((entry.path, depth + 1))
                    else:
                        # files, reparse points, and symlinked dirs are leaves
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                        own_bytes += size
                        own_files += 1
                        if size > 0:
                            if len(heap) < self.top_n:
                                heapq.heappush(
                                    heap, (size, _display_path(entry.path))
                                )
                            elif heap and size > heap[0][0]:
                                heapq.heapreplace(
                                    heap, (size, _display_path(entry.path))
                                )
                except OSError:
                    continue
        finally:
            it.close()

        # Single critical section per directory: commit own totals, reserve
        # child records (so dir_parent linkage is correct), enqueue child jobs.
        with self._lock:
            self.dir_own[idx] = own_bytes
            self.dir_files[idx] = own_files
            self._files_scanned += own_files
            self._bytes_total += own_bytes
            for child_path, child_depth in child_jobs:
                child_idx = self._add_record(
                    _display_path(child_path), parent=idx, depth=child_depth
                )
                self._jobs.append((child_idx, child_path))
            if child_jobs:
                self._cond.notify_all()

    def _worker(self, worker_id: int) -> None:
        while True:
            with self._cond:
                # Wait while there is nothing to pop but work is still in
                # flight (an active worker may yet enqueue children).
                while not self._jobs and self._active > 0:
                    self._cond.wait()
                if not self._jobs:
                    # No jobs and no active workers: the walk is complete.
                    # Wake any peers still parked so they observe the same.
                    self._cond.notify_all()
                    return
                idx, real_path = self._jobs.pop()
                self._active += 1
            try:
                self._process(worker_id, idx, real_path)
            finally:
                with self._cond:
                    self._active -= 1
                    if self._active == 0 and not self._jobs:
                        self._cond.notify_all()

    def run(self) -> dict[str, Any]:
        workers = [
            threading.Thread(target=self._worker, args=(i,), daemon=True)
            for i in range(self.threads)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        merged: list[tuple[int, str]] = []
        for heap in self._local_heaps:
            merged.extend(heap)
        merged.sort(key=lambda t: t[0], reverse=True)
        top_files = [(p, s) for s, p in merged[: self.top_n]]

        n = len(self.dir_path)
        return {
            "dir_path": self.dir_path,
            "dir_own": self.dir_own,
            "dir_recursive": [0] * n,
            "dir_files": self.dir_files,
            "dir_parent": self.dir_parent,
            "dir_depth": self.dir_depth,
            "dir_denied": self.dir_denied,
            "top_files": top_files,
            "stats": {
                "files_scanned": self._files_scanned,
                "dirs_scanned": n,
                "total_bytes": self._bytes_total,
                "denied_count": self._denied_count,
            },
            "recursive_filled": False,
        }


def walk(
    root: str,
    threads: int = 8,
    include_hidden: bool = False,
    top_n: int = 50,
) -> dict[str, Any]:
    """Walk ``root`` in parallel and return the columnar walk result.

    Mirrors the signature and output contract of the native walker.
    """
    started = time.perf_counter()
    walker = _Walker(root, threads, include_hidden, top_n)
    result = walker.run()
    result["stats"]["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    result["stats"]["threads"] = walker.threads
    return result
