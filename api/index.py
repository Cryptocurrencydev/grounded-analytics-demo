"""Vercel Python entrypoint."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grounded.main import app

__all__ = ["app"]
