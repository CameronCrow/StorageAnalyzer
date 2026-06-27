# StorageAnalyzer

A fast, parallel storage analyzer for Windows. It walks a directory tree,
finds the biggest space hogs, and writes a **self-contained interactive HTML
report** — a squarified treemap you can click to drill into folders, plus
sortable, searchable tables of the largest files and directories.

The performance-critical directory walk is an optional C++ extension. When the
extension is not built (e.g. no C++ compiler installed), the tool transparently
falls back to a pure-Python parallel walker — **the tool is fully functional
either way**, the native engine is purely a speedup.

## Highlights

- **Parallel walk.** A worker pool enumerates directories concurrently. On a
  ~300k-file tree the native engine completes in ~1 second; the pure-Python
  engine in ~8 seconds. Both produce byte-identical results.
- **Interactive HTML report.** One `.html` file, no CDN, no network — opens
  offline with a double-click. Treemap drill-down, breadcrumb navigation,
  column sorting, path filtering.
- **Desktop GUI.** Launch the app with no arguments (double-click the exe, or
  run `storageanalyzer`) and a single native window opens — a left sidebar to
  pick a folder and set options, scan, and the **interactive treemap report
  renders right in the same window**. No terminal, no separate browser tab. The
  window is hosted by [pywebview](https://pywebview.flowrl.com/) on the system
  webview (Edge WebView2 on Windows).
- **Zero-dependency CLI.** The command-line scanner is pure standard library.
  Only the desktop GUI adds a dependency (pywebview); the C++ build needs
  `pybind11` + a compiler, but those are build-time only.
- **Optional native speedup.** No compiler? `pip install` still succeeds and
  the tool runs. Install the compiler later for a drop-in ~8x speedup.

## Requirements

- Windows
- Python 3.9+
- *(optional, for the native speedup)* Visual Studio Build Tools with the
  "Desktop development with C++" workload

## Install

```powershell
pip install .
```

This installs the `storageanalyzer` command. If a C++ compiler is available
the native walker is compiled automatically; if not, the install prints a
short notice and proceeds — the pure-Python walker is used instead.

For development (editable install, skips build isolation so it reuses your
environment's `pybind11`):

```powershell
pip install -e . --no-build-isolation
```

## Desktop GUI

Prefer clicking to typing? Just launch the app with **no arguments** — the
desktop window is the default:

```powershell
# any of these opens the native window
storageanalyzer            # no arguments -> GUI
storageanalyzer --gui      # explicit
python -m storageanalyzer.gui

# from source, the GUI needs pywebview:
pip install -e ".[gui]"
```

It's **one window**: a left sidebar to pick a folder, choose the engine / thread
count / top-N counts, and toggle hidden-and-system inclusion, and a main stage
that renders the **interactive treemap report in place** the moment the scan
finishes — treemap drill-down, breadcrumb, sortable tables, path filters, all in
the same window. The scan runs in-process on a worker thread so the window stays
responsive; *Save report…* writes the standalone HTML to a file you choose.

The window is hosted by **pywebview** on the system webview (Edge WebView2 on
Windows) and drives the same `scan()` engine the CLI uses. The frontend look and
feel mirrors the PLC Crawler sidebar-and-stage layout.

## Build a standalone .exe

To ship the tool as a single self-contained `storageanalyzer.exe` (no Python
install required on the target machine):

```powershell
# one-time: install the build tooling (PyInstaller + pybind11)
pip install -e ".[build]"

# build -- produces dist\storageanalyzer.exe
.\build-exe.ps1
```

`build-exe.ps1` compiles the native C++ walker, then runs PyInstaller against
`storageanalyzer.spec` to produce a one-file **windowed** exe (~21 MB) with the
native walker, the HTML frontend, and the pywebview/WebView2 host bundled in.
Because it is a GUI-subsystem exe, double-clicking it **never flashes a
terminal**. The exe is a proper Windows artifact:
it carries the application **icon** and a **version resource** (right-click →
Properties → Details shows ProductName, version, company, and copyright), both
derived from `storageanalyzer.__version__` so they never drift. PyInstaller
caches its analysis in `build\`, so re-runs are quick — pure-Python source edits
need no recompile, only `walker.cpp` changes do. Pass `-Clean` to force a full
rebuild.

The exe is fully portable: copy `dist\storageanalyzer.exe` anywhere and run it.
**Double-clicking it opens the desktop GUI** with no terminal. (It's a windowed
exe, so for scripted CLI scans with console output use
`python -m storageanalyzer ...`; passing a path/flag to the exe still scans, it
just has no console to print to.)

### Build a Windows installer

For a friendlier distribution — a per-user installer that adds `storageanalyzer`
to your PATH and registers an uninstaller — build the [Inno Setup](https://jrsoftware.org/isinfo.php)
package:

```powershell
# one-time: install Inno Setup
winget install JRSoftware.InnoSetup

# build -- produces dist\StorageAnalyzer-Setup-<version>.exe
.\build-installer.ps1
```

`build-installer.ps1` builds the exe first, then compiles
`installer\storageanalyzer.iss`. The installer needs no admin rights (installs
under `%LOCALAPPDATA%\Programs`), offers an opt-in "add to PATH" task, and shows
up in *Apps & features*. If Inno Setup isn't installed the script still builds
the exe and exits with a note — the one-file exe is shippable on its own.

### Automated releases

`.github/workflows/release.yml` builds the exe and the installer on Windows for
every push and PR, and **publishes a GitHub Release with both attached whenever
a version tag is pushed**:

```powershell
git tag v1.0.1
git push --tags
```

The icon and version metadata are regenerated from `__version__` on every build,
so the only thing to bump for a release is `__version__` in
`src/storageanalyzer/__init__.py` (and the matching `version` in
`pyproject.toml`). The application icon lives at `packaging/storageanalyzer.ico`;
regenerate or tweak it with `python packaging/make_icon.py` (requires Pillow).

## Usage

Run with **no arguments to open the desktop GUI**; pass a path (or any flag) to
use the command-line scanner.

```powershell
# no arguments -> open the desktop GUI
storageanalyzer

# scan a specific folder from the command line (writes + opens the HTML report)
storageanalyzer "C:\Users\you\Downloads"

# scan C:\ explicitly
storageanalyzer "C:\"

# also runnable as a module
python -m storageanalyzer "D:\"
```

### Options

| Option | Description | Default |
| --- | --- | --- |
| *(no arguments)* | Open the desktop GUI instead of scanning | — |
| `root` | Directory to scan (omit entirely to open the GUI) | `C:\` |
| `-o, --output PATH` | HTML report path | `storageanalyzer-report-<timestamp>.html` |
| `--engine {auto,native,python}` | Walker engine. `auto` uses native if built, else python. `native` errors if not built. `python` forces the fallback. | `auto` |
| `--threads N` | Worker thread count | CPU count, clamped to `[2, 16]` |
| `--top-files N` | Number of largest files to report | `50` |
| `--top-dirs N` | Number of largest directories to report | `50` |
| `--include-hidden` | Include hidden and system files/directories | off |
| `--prune-threshold F` | Treemap: fold directories smaller than this fraction of the root into an aggregated `(other)` node | `0.001` |
| `--no-open` | Do not open the report in a browser when finished | off |

### Examples

```powershell
# top 100 files / 100 dirs, force the pure-Python engine, don't auto-open
storageanalyzer "C:\" --top-files 100 --top-dirs 100 --engine python --no-open

# include hidden/system items, write the report to a fixed path
storageanalyzer "C:\Users\you" --include-hidden -o report.html
```

## How it works

```
src/storageanalyzer/
  cli.py         argparse, validation, orchestration, console summary
  gui.py         pywebview shell + Api (scan/pick_folder/save_report) for the JS
  scan.py        engine selection (native vs fallback), normalized scan()
  fallback.py    pure-Python ThreadPoolExecutor-style parallel walker
  aggregate.py   recursive size rollup, top-N tables, treemap tree + pruning
  report.py      fills template.html with the embedded JSON payload (or null)
  template.html  the frontend: sidebar controls + in-window treemap report
  _format.py     shared human-readable byte formatting (CLI + GUI)
  template.html  the single-file report (inline CSS/JS, vanilla treemap)
native/walker.cpp   optional pybind11 C++ walker (FindFirstFileExW + thread pool)
```

Both walkers emit the **same columnar result contract**, so `aggregate` and
`report` do not care which engine ran. The native walker uses
`FindFirstFileExW` with `FindExInfoBasic` + `FIND_FIRST_EX_LARGE_FETCH`, which
returns file sizes inside the enumeration result — no per-file `stat`. The
Python fallback gets the same property from `os.scandir`. Both:

- skip reparse points / junctions / symlinks (recorded as leaves, never
  recursed — no cycles, no double-counting),
- count access-denied directories instead of crashing on them,
- apply the `\\?\` long-path prefix,
- skip hidden/system entries unless `--include-hidden` is set.

A full-drive scan can touch hundreds of thousands of directories, so
`aggregate` prunes sub-threshold folders out of the embedded treemap JSON
(folding them into an `(other)` node). The top-N tables always keep full
detail; pruning only affects the treemap payload size.

## Development

Run the test suite:

```powershell
pytest
```

The tests cover the rollup/pruning logic, the HTML report rendering, the
pure-Python walker (including the termination race across thread counts,
reparse-point handling, and access-denied accounting), and — when the native
extension is built — native/Python output parity.
