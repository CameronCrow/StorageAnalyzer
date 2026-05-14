"""Optional native-extension build for StorageAnalyzer.

All package metadata lives in ``pyproject.toml``. This file exists solely to
compile ``native/walker.cpp`` into the ``storageanalyzer._native_walker``
extension -- and to make that build *optional*.

If no C++ compiler is available (the common case on a fresh Windows box with
no Visual Studio Build Tools), the build is skipped with a clear warning
instead of failing. ``pip install .`` then succeeds and the package runs on
its pure-Python parallel walker. Installing "Desktop development with C++"
and reinstalling is a drop-in speedup -- nothing else changes.
"""

from __future__ import annotations

import sys

from setuptools import setup
from setuptools.command.build_ext import build_ext as _build_ext

try:
    from pybind11.setup_helpers import Pybind11Extension

    ext_modules = [
        Pybind11Extension(
            "storageanalyzer._native_walker",
            ["native/walker.cpp"],
            cxx_std=17,
        )
    ]
except ImportError:
    # pybind11 missing entirely -- still install the pure-Python package.
    ext_modules = []


class optional_build_ext(_build_ext):
    """build_ext that downgrades a compile failure to a warning."""

    def run(self) -> None:
        try:
            super().run()
        except Exception as exc:  # noqa: BLE001 - intentionally broad
            self._warn(exc)

    def build_extension(self, ext) -> None:
        try:
            super().build_extension(ext)
        except Exception as exc:  # noqa: BLE001 - intentionally broad
            self._warn(exc)

    @staticmethod
    def _warn(exc: Exception) -> None:
        sys.stderr.write(
            "\n"
            "============================================================\n"
            "StorageAnalyzer: the optional native C++ walker did NOT build.\n"
            f"  reason: {exc}\n"
            "This is fine -- the tool is fully functional on its pure-Python\n"
            "parallel walker. For a speedup, install the Visual Studio Build\n"
            "Tools ('Desktop development with C++') and reinstall.\n"
            "============================================================\n\n"
        )


setup(
    ext_modules=ext_modules,
    cmdclass={"build_ext": optional_build_ext},
)
