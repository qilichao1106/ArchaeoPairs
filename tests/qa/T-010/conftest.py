"""Frozen T-010 acceptance-test setup.

Run from the project root with::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-010 -q -p no:cacheprovider

Every fixture is synthetic: PIL images are written under ``tmp_path``; OCR and
the Writer are fakes, so no test reads ``books/``, writes a book artifact or
opens a socket.
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