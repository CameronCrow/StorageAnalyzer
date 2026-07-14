---
type: reference
tags: [repo/StorageAnalyzer]
up: "[[StorageAnalyzer]]"
---
# StorageAnalyzer — User Manual

StorageAnalyzer scans a folder (or a whole drive) and shows you **where your
space actually went**: an interactive treemap plus sortable tables of the
largest folders and files. It runs as a single desktop window — pick a folder,
press **Scan**, and the report renders right there. No terminal, no website, no
data leaves your machine.

- [1. Getting started](#1-getting-started)
- [2. The window at a glance](#2-the-window-at-a-glance)
- [3. Running a scan](#3-running-a-scan)
- [4. Reading the report](#4-reading-the-report)
- [5. Dark mode](#5-dark-mode)
- [6. Saving and sharing a report](#6-saving-and-sharing-a-report)
- [7. Command line](#7-command-line)
- [8. Troubleshooting](#8-troubleshooting)

---

## 1. Getting started

**If you have the `.exe`:** double-click `storageanalyzer.exe`. The window
opens — that's it. Nothing installs, nothing pops up a console.

**From a Python install:**

```powershell
pip install -e ".[gui]"     # the GUI needs pywebview
storageanalyzer             # opens the window
```

Requirements: Windows 10/11 (the window uses the built-in **Edge WebView2**
runtime, which ships with current Windows). Python 3.9+ if running from source.

---

## 2. The window at a glance

```
┌──────────────┬──────────────────────────────────────────────┐
│  Storage     │  StorageAnalyzer — C:\Users\you        [🌙]   │
│  Analyzer    │  ┌ Total ┐ ┌ Files ┐ ┌ Directories ┐ …        │
│              │                                                │
│  Folder      │   Treemap — click a folder to drill in        │
│  [ C:\ ][…]  │   ┌───────────┬─────────┐                     │
│  Engine  ▾   │   │  Windows  │  Users  │   (colored tiles)    │
│  Threads     │   ├─────┬─────┴────┬────┤                     │
│  Report size │   │ ... │   ...    │ .. │                     │
│  ☐ hidden    │   └─────┴──────────┴────┘                     │
│  [  Scan  ]  │                                                │
│  status…     │   Largest directories     Largest files       │
│  [Save…]     │   (sortable, filterable tables)               │
└──────────────┴──────────────────────────────────────────────┘
   sidebar              stage (the report renders here)
```

The **sidebar** (left) holds the scan controls. The **stage** (right) is where
the report appears. The **theme toggle** (🌙 / ☀️) sits in the top-right corner.

---

## 3. Running a scan

Fill in the sidebar and press **Scan**:

| Control | What it does |
| --- | --- |
| **Folder** | The directory to scan. Type a path or use **Browse…** to pick one. |
| **Browse…** | Opens a native folder picker. |
| **Engine** | `auto` (recommended) uses the fast native C++ walker if it was built, otherwise the pure-Python one. `native` forces the C++ walker (errors if it isn't built). `python` forces the fallback. |
| **Threads** | Worker threads for the walk. Leave blank for an automatic count (CPU-based). |
| **Report size → Top files / Top dirs** | How many of the largest files / directories to list in the tables. Default 50 each. |
| **Include hidden / system** | Off by default. Turn it on to count hidden and system items (see [§4](#the-missing-space-note)). |

While a scan runs, the status line shows a spinner and *"Scanning … "*. The walk
happens in the background, so the window stays responsive. When it finishes the
report renders and the status shows a summary (files, total size, elapsed time).
Press **Scan** again any time to re-scan with different options — the report
updates in place.

> Scanning an entire system drive (`C:\`) can take from seconds to a few minutes
> depending on how many files you have and whether the native engine is in use.

---

## 4. Reading the report

### Summary chips

Across the top: **Total** size, **Files**, **Directories**, **Access denied**,
**Elapsed** time, **Threads**, and the **Engine** used.

### Treemap

Each colored rectangle is a folder; its area is proportional to its size, so the
biggest space hogs are the biggest tiles.

- **Hover** a tile to see its full path and size.
- **Click** a tile to drill into that folder — the treemap redraws for its
  contents.
- Use the **breadcrumb** above the treemap (`root › Windows › System32`) to jump
  back up. Click any segment to return to that level.
- Tiny folders are folded into a single **`(other)`** tile so the picture stays
  readable; that tile isn't drillable.

### Tables

**Largest directories** — Path, **Recursive size** (the folder *and everything
under it*), **Own size** (files directly in that folder, excluding
sub-folders), and **Files** (count). **Largest files** — Path and Size.

- Click any **column header** to sort; click again to reverse.
- Use the **filter** box above a table to narrow rows by path substring.
- Click a **directory row** to focus that folder in the treemap above.

### Access-denied directories

If some folders couldn't be read (permissions), an **Access-denied** section
lists them and they're excluded from the totals. Click the **Access denied**
summary chip to jump to the list. Re-run from an **elevated** (Administrator)
prompt to include them.

### The "missing space" note

When **Include hidden / system** is off (the default), a note appears reminding
you that hidden and system items weren't counted. On a system drive that's
usually where "missing" space hides: the page file, hibernation file, shadow
copies, and the recycle bin. Turn the option on and re-scan to account for them.

---

## 5. Dark mode

Click the **🌙 / ☀️** button in the top-right corner to switch between light and
dark themes. By default StorageAnalyzer follows your **Windows app theme**; once
you click the toggle, your choice is remembered for next time. The treemap and
report recolor instantly. The toggle is available both in the live app and in a
saved report (see below).

---

## 6. Saving and sharing a report

Press **Save report…** after a scan to write a **standalone `.html` file**. That
file is completely self-contained — no internet, no StorageAnalyzer install
needed. Open it in any browser (or email it to someone) and it works exactly
like the in-app report: treemap drill-down, sortable tables, filters, and the
dark-mode toggle. The control sidebar is hidden in a saved report since the scan
is already done.

---

## 7. Command line

The GUI is the default, but there's a full CLI for scripting and headless use.
Run it through Python (the `.exe` is a windowed app with no console to print
to):

```powershell
python -m storageanalyzer "C:\Users\you\Downloads"        # scan + write/open an HTML report
python -m storageanalyzer "C:\" --engine python --no-open  # force fallback engine, don't auto-open
python -m storageanalyzer "C:\Users\you" --include-hidden -o report.html
```

Common options: `-o/--output PATH`, `--engine {auto,native,python}`,
`--threads N`, `--top-files N`, `--top-dirs N`, `--include-hidden`,
`--no-open`. Run `python -m storageanalyzer --help` for the full list. (Passing
a path or any flag to `storageanalyzer.exe` also runs the CLI scan and writes
the report — it just produces no console output.)

---

## 8. Troubleshooting

**The window is blank or won't open.** StorageAnalyzer needs the **Edge WebView2
runtime**. It's preinstalled on current Windows 10/11; if it's missing, install
the free "Evergreen" runtime from Microsoft
(<https://developer.microsoft.com/microsoft-edge/webview2/>) and relaunch.

**A lot of space is "missing" / totals look too small.** Two usual causes:
(1) hidden/system files weren't counted — turn on **Include hidden / system**;
(2) folders were **access-denied** — re-run as Administrator. Both are called
out in the report.

**Scans of `C:\` are slow.** Use the native engine for the big speedup. With a
source install, build it with a C++ compiler (Visual Studio Build Tools,
"Desktop development with C++"); the prebuilt `.exe` already includes it. `auto`
falls back to the slower pure-Python walker when the native engine isn't
available — the scan still completes.

**"native walker is not available" error.** You chose **Engine: native** but it
wasn't built. Switch to **auto** or **python**, or build the native extension.

**My theme choice didn't stick.** The choice is saved per WebView2 profile; if
storage is cleared it falls back to following the Windows app theme.

## Related

- [[Repos/StorageAnalyzer/StorageAnalyzer|StorageAnalyzer]] — repo hub
