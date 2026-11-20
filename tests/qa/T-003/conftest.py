"""Shared setup for the frozen T-003 acceptance tests.

The suite is run from the project root with:

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-003 -q -p no:cacheprovider

``pyproject.toml`` already puts ``src`` on ``pythonpath``; the explicit insert
keeps the suite runnable when pytest is invoked with ``-c`` or from another
rootdir.  No test here reads book media or writes into the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))