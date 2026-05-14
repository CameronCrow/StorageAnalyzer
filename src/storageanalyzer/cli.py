"""Command-line interface: argument parsing, orchestration, console summary."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .report import write_report
from .scan import scan


def _fmt_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.2f} TB"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="storageanalyzer",
        description="Fast parallel storage analyzer -> interactive HTML report.",
    )
    p.add_argument(
        "root",
        nargs="?",
        default="C:\\",
        help="root directory to scan (default: C:\\)",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="HTML report path (default: storageanalyzer-report-<timestamp>.html)",
    )
    p.add_argument(
        "--engine",
        choices=("auto", "native", "python"),
        default="auto",
        help="walker engine: auto (native if built, else python), native, python",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=None,
        help="worker thread count (default: CPU count clamped to [2,16])",
    )
    p.add_argument(
        "--top-files",
        type=int,
        default=50,
        help="number of largest files to report (default: 50)",
    )
    p.add_argument(
        "--top-dirs",
        type=int,
        default=50,
        help="number of largest directories to report (default: 50)",
    )
    p.add_argument(
        "--include-hidden",
        action="store_true",
        help="include hidden and system files/directories",
    )
    p.add_argument(
        "--prune-threshold",
        type=float,
        default=0.001,
        help="treemap: fold dirs below this fraction of the root into '(other)'"
        " (default: 0.001)",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="do not open the report in a browser when finished",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _print_summary(
    report_data: dict, out_path: Path, include_hidden: bool
) -> None:
    stats = report_data["stats"]
    dirs = report_data["largest_dirs"][:10]
    files = report_data["largest_files"][:10]

    print()
    print(f"  Scan summary  --  {report_data['root']}")
    print(f"  {'-' * 58}")
    print(f"  Engine            : {stats.get('engine', 'n/a')}")
    print(f"  Threads           : {stats.get('threads', 'n/a')}")
    print(f"  Files scanned     : {stats.get('files_scanned', 0):,}")
    print(f"  Directories       : {stats.get('dirs_scanned', 0):,}")
    print(f"  Total size        : {_fmt_size(stats.get('total_bytes', 0))}")
    print(f"  Access denied     : {stats.get('denied_count', 0):,}")
    if stats.get("elapsed_seconds") is not None:
        print(f"  Elapsed           : {stats['elapsed_seconds']:.2f} s")
    if not include_hidden:
        print(
            "  Note: hidden/system items were skipped "
            "-- re-run with --include-hidden to count them"
        )

    if dirs:
        print()
        print("  Top directories by recursive size")
        for d in dirs:
            print(f"    {_fmt_size(d['size']):>11}  {d['path']}")
    if files:
        print()
        print("  Top files by size")
        for f in files:
            print(f"    {_fmt_size(f['size']):>11}  {f['path']}")

    denied = report_data.get("denied_dirs", [])
    if denied:
        shown = denied[:15]
        print()
        print(f"  Access-denied directories ({len(denied):,} not scanned)")
        for path in shown:
            print(f"    {path}")
        if len(denied) > len(shown):
            print(f"    ... and {len(denied) - len(shown):,} more (see HTML report)")

    print()
    print(f"  HTML report written to: {out_path}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: not a directory: {args.root}", file=sys.stderr)
        return 2
    if args.threads is not None and args.threads < 1:
        print("error: --threads must be >= 1", file=sys.stderr)
        return 2

    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = Path.cwd() / f"storageanalyzer-report-{stamp}.html"

    print(f"Scanning {root} (engine={args.engine}) ...")
    started = time.perf_counter()
    try:
        report_data = scan(
            str(root),
            engine=args.engine,
            threads=args.threads,
            include_hidden=args.include_hidden,
            top_files=args.top_files,
            top_dirs=args.top_dirs,
            prune_threshold=args.prune_threshold,
        )
    except RuntimeError as exc:
        # raised by get_walker when --engine native is requested but unbuilt
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return 130

    # ensure an elapsed time is present even if the walker did not report one
    report_data["stats"].setdefault(
        "elapsed_seconds", round(time.perf_counter() - started, 4)
    )

    write_report(report_data, out_path)
    _print_summary(report_data, out_path, args.include_hidden)

    if not args.no_open:
        try:
            import webbrowser

            webbrowser.open(out_path.resolve().as_uri())
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
