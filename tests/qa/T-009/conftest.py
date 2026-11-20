"""Shared setup for the frozen T-009 acceptance tests.

Run from the project root with::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-009 -q -p no:cacheprovider

Every fixture is synthetic: PIL/numpy images are built in memory, masks are
encoded with the production RLE helper, and no test reads ``books/``, writes a
file or opens a socket.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SRC_DIR = REPO_ROOT / "src"

for path in (SRC_DIR, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))