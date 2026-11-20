"""Frozen T-011 acceptance-test setup.

Run from the project root with::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-011 -q -p no:cacheprovider

Every fixture is synthetic: books, images, XML and OCR are created under
``tmp_path`` and no test reads the real ``books/`` tree, opens a socket or
instantiates PaddleOCR / a VLM client.  ``FileWriter`` is exercised against the
real filesystem because that is what the card asks it to persist.
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