# PyInstaller build spec -- produces a polished one-file Windows exe that opens
# the pywebview desktop GUI when launched with no arguments and runs the CLI
# when given any. It is a *windowed* (GUI subsystem) exe, so double-clicking it
# never flashes a terminal; the report renders inside the app window itself.
# CLI users run `python -m storageanalyzer ...` (the exe has no console to print
# to). The frontend is self-contained -- it pulls nothing from the network.
#
# Build:  pyinstaller storageanalyzer.spec --noconfirm
# Or just run build-exe.ps1, which (re)builds the native extension first.
#
# Beyond bundling the code, this spec gives the exe a real Windows identity:
#   * an application icon (packaging/storageanalyzer.ico), and
#   * a version resource (Properties -> Details: ProductName, version, company,
#     copyright, ...) generated from storageanalyzer.__version__ so it can never
#     drift from the package version.

import glob
import re
from pathlib import Path

# --- single source of truth: the package __version__ -----------------------
# Parsed (not imported) so building the version resource never has to import the
# package or its native extension.
_init = Path("src/storageanalyzer/__init__.py").read_text(encoding="utf-8")
_m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", _init)
_version = _m.group(1) if _m else "0.0.0"
# Windows file/product version wants a 4-int tuple; pad/truncate from the parts.
_nums = (re.findall(r"\d+", _version) + ["0", "0", "0", "0"])[:4]
_vtuple = tuple(int(n) for n in _nums)

# --- Windows version resource ----------------------------------------------
# Written to build/ (git-ignored) each build and handed to EXE(version=...).
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

_version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_vtuple,
        prodvers=_vtuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,      # VOS_NT_WINDOWS32
        fileType=0x1,    # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable(
                "040904B0",  # U.S. English, Unicode
                [
                    StringStruct("CompanyName", "Cameron Crow"),
                    StringStruct(
                        "FileDescription",
                        "Fast parallel Windows storage analyzer "
                        "with an interactive HTML report",
                    ),
                    StringStruct("FileVersion", _version),
                    StringStruct("InternalName", "storageanalyzer"),
                    StringStruct(
                        "LegalCopyright", "Cameron Crow. MIT License."
                    ),
                    StringStruct("OriginalFilename", "storageanalyzer.exe"),
                    StringStruct("ProductName", "StorageAnalyzer"),
                    StringStruct("ProductVersion", _version),
                ],
            )
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

Path("build").mkdir(exist_ok=True)
_version_file = Path("build/version_info.txt")
_version_file.write_text(str(_version_info), encoding="utf-8")

# --- application icon (optional) -------------------------------------------
_icon = "packaging/storageanalyzer.ico"
_icon = _icon if Path(_icon).is_file() else None

# --- native walker (optional) ----------------------------------------------
# If the native C++ walker was built in place (by `pip install -e .` or
# build-exe.ps1) bundle the .pyd and register it as a hidden import -- scan.py
# imports it lazily inside a try/except, so PyInstaller's static analysis would
# otherwise miss it. If it was never built, the exe still works on the
# pure-Python walker.
_pyd = glob.glob("src/storageanalyzer/_native_walker*.pyd")
binaries = [(p, "storageanalyzer") for p in _pyd]
datas = [("src/storageanalyzer/template.html", "storageanalyzer")]
hiddenimports = []
if _pyd:
    hiddenimports.append("storageanalyzer._native_walker")

# pywebview hosts the GUI window. It ships its own PyInstaller hooks, but its
# Windows backend rides on pythonnet/clr (Python.Runtime.dll + the WebView2
# loader) which static analysis can miss -- collect them all explicitly so the
# windowed exe carries a working webview engine.
from PyInstaller.utils.hooks import collect_all  # noqa: E402

for _pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        continue
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["scripts/sa_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "_pytest", "pybind11", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="storageanalyzer",
    icon=_icon,
    version=str(_version_file),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
