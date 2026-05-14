"""Render an aggregated scan result into a self-contained HTML report."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

_PLACEHOLDER = "/*DATA*/"


def _load_template() -> str:
    return resources.files(__package__).joinpath("template.html").read_text(
        encoding="utf-8"
    )


def render(report_data: dict[str, Any]) -> str:
    """Return the full HTML document with ``report_data`` embedded as JSON."""
    template = _load_template()
    if _PLACEHOLDER not in template:
        raise ValueError("template.html is missing the /*DATA*/ placeholder")
    # ensure_ascii keeps the output 7-bit clean; </ is escaped so an embedded
    # path can never terminate the <script> block early.
    payload = json.dumps(report_data, ensure_ascii=True).replace("</", "<\\/")
    return template.replace(_PLACEHOLDER, payload)


def write_report(report_data: dict[str, Any], out_path: str | Path) -> Path:
    """Render and write the report to ``out_path``. Returns the written path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(report_data), encoding="utf-8")
    return out
