"""Shared setup for the frozen T-006 acceptance tests.

Run from the project root with::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-006 -q -p no:cacheprovider

Every fixture is synthetic (Pillow/numpy).  No test reads ``books/`` or opens a
socket; temporary images are written under pytest's ``tmp_path`` only.
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