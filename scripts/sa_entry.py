"""PyInstaller entry point.

PyInstaller runs its entry script as ``__main__``, so the package's own
``__main__.py`` (which uses a relative import) cannot be the target. This thin
wrapper uses an absolute import instead and is otherwise identical.
"""

import sys

from storageanalyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
