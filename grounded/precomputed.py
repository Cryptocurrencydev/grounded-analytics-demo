"""Results generated offline by scripts/prewarm.py and committed. Validated when they were made."""
from __future__ import annotations

import json
from functools import lru_cache

from .catalog import DATA_DIR


@lru_cache(maxsize=1)
def _load() -> dict:
    path = DATA_DIR / "precomputed.json"
    return json.loads(path.read_text()) if path.exists() else {}


def lookup(key: str) -> dict | None:
    return _load().get(key)
