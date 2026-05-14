"""Tests for HTML report rendering: data embeds, valid-ish HTML, no CDN refs."""

import json
import re

import pytest

from storageanalyzer.report import render, write_report


def _report_data():
    return {
        "root": r"C:\demo",
        "tree": {
            "name": r"C:\demo",
            "size": 300,
            "own": 0,
            "files": 0,
            "children": [
                {"name": r"C:\demo\a", "size": 200, "own": 200, "files": 2},
                {"name": r"C:\demo\b", "size": 100, "own": 100, "files": 1},
            ],
        },
        "largest_files": [{"path": r"C:\demo\a\big.bin", "size": 150}],
        "largest_dirs": [{"path": r"C:\demo\a", "size": 200, "own": 200, "files": 2}],
        "stats": {
            "total_bytes": 300,
            "files_scanned": 3,
            "dirs_scanned": 3,
            "denied_count": 0,
            "engine": "python",
            "threads": 4,
            "elapsed_seconds": 0.12,
        },
    }


def test_placeholder_is_replaced():
    html = render(_report_data())
    assert "/*DATA*/" not in html
    assert "const DATA =" in html


def test_embedded_json_round_trips():
    html = render(_report_data())
    m = re.search(r"const DATA = (.*?);\n", html, re.S)
    assert m, "could not locate embedded DATA assignment"
    embedded = json.loads(m.group(1).replace("<\\/", "</"))
    assert embedded["root"] == r"C:\demo"
    assert embedded["stats"]["files_scanned"] == 3
    assert embedded["tree"]["size"] == 300


def test_no_external_resources():
    html = render(_report_data())
    lowered = html.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "cdn" not in lowered
    assert "src=" not in lowered  # no external scripts/images


def test_script_close_tag_cannot_break_out():
    data = _report_data()
    data["largest_files"] = [{"path": r"C:\x\</script><b>evil", "size": 1}]
    html = render(data)
    # the literal closing tag must not appear unescaped inside the payload
    body = html.split("const DATA = ", 1)[1]
    assert "</script><b>evil" not in body.split(";\n", 1)[0]


def test_is_self_contained_html_document():
    html = render(_report_data())
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<canvas" in html
    assert html.rstrip().endswith("</html>")


def test_write_report_creates_file(tmp_path):
    out = write_report(_report_data(), tmp_path / "sub" / "report.html")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "const DATA =" in text


def test_missing_placeholder_raises(monkeypatch):
    monkeypatch.setattr(
        "storageanalyzer.report._load_template", lambda: "<html>no placeholder</html>"
    )
    with pytest.raises(ValueError):
        render(_report_data())
