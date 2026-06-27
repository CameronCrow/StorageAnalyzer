"""PyInstaller entry point.

PyInstaller runs its entry script as ``__main__``, so the package's own
``__main__.py`` (which uses a relative import) cannot be the target. This thin
wrapper uses an absolute import instead and is otherwise identical.
"""

import os
import sys

# The shipped exe is windowed (no console), so PyInstaller leaves sys.stdout /
# sys.stderr as None. If the exe is nonetheless invoked with CLI args, route the
# CLI's prints to a sink so it can still write the report instead of crashing on
# the first print. `python -m storageanalyzer` keeps its real console streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from storageanalyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
