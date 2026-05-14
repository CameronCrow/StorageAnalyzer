# PyInstaller build spec -- produces a one-file Windows console exe.
#
# Build:  pyinstaller storageanalyzer.spec --noconfirm
# Or just run build-exe.ps1, which (re)builds the native extension first.

import glob

# The native C++ walker is optional. If it was built in place (by
# `pip install -e .` or build-exe.ps1) bundle the .pyd and register it as a
# hidden import -- scan.py imports it lazily inside a try/except, so
# PyInstaller's static analysis would otherwise miss it. If it was never
# built, the exe still works on the pure-Python walker.
_pyd = glob.glob("src/storageanalyzer/_native_walker*.pyd")
binaries = [(p, "storageanalyzer") for p in _pyd]
hiddenimports = ["storageanalyzer._native_walker"] if _pyd else []

a = Analysis(
    ["scripts/sa_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=[("src/storageanalyzer/template.html", "storageanalyzer")],
    hiddenimports=hiddenimports,
    excludes=["pytest", "_pytest", "pybind11"],
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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
