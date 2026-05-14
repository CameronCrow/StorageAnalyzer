"""StorageAnalyzer: a fast, parallel Windows storage analyzer with HTML reports."""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["scan", "__version__"]


def scan(*args, **kwargs):
    """Lazy re-export of :func:`storageanalyzer.scan.scan`.

    Imported lazily so that ``storageanalyzer.aggregate`` / ``.report`` can be
    used without pulling in the walker machinery.
    """
    from .scan import scan as _scan

    return _scan(*args, **kwargs)
