"""Shared setup for the frozen T-005 acceptance tests.

Run from the project root (this worktree root)::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-005 -q -p no:cacheprovider

Every engine/client below the tests is a fake.  ``paddleocr`` is never
imported, no Paddle model is loaded, and no socket is opened.
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