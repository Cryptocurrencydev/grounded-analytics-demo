"""Loads .env.local into the process for offline scripts. Values are never printed."""
import os
from pathlib import Path


def load_env_file() -> None:
    path = Path(__file__).resolve().parent.parent / ".env.local"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))
