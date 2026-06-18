"""Shared, dependency-free formatting helpers used by the CLI and the GUI."""

from __future__ import annotations


def format_size(num_bytes: float) -> str:
    """Format a byte count as a human-readable string (e.g. ``1.50 GB``).

    Bytes are shown as a bare integer; KB and up use two decimals. Anything
    at or above 1024 TB is still reported in TB rather than rolling over.
    """
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.2f} TB"
