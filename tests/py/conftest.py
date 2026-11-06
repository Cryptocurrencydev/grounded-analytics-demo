import os

os.environ["LLM_MODE"] = "mock"
os.environ.pop("DATABASE_URL", None)

import pytest

from grounded import llm, store


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    store.reset_store(store.MemoryStore())
    llm.set_llm(None)
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "1000")
    monkeypatch.setenv("DAILY_LLM_CAP", "1000")
    yield
