"""Compatibility alias for :mod:`t007_synthetic` (the canonical helper module).

The T-007 tests import ``t007_synthetic`` directly so a full-suite run cannot
accidentally reuse ``tests/qa/T-006/synthetic.py`` (same top-level module name).
This alias remains only for ad-hoc imports from this directory.
"""

from __future__ import annotations

from t007_synthetic import *  # noqa: F401,F403