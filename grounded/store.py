"""Cache and rate-limit storage. Postgres when DATABASE_URL is set, otherwise process memory.

Serverless instances do not share memory, so the public deployment needs the database for the
caps to mean anything. If the database fails mid-flight the memory store takes over.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Protocol

log = logging.getLogger("grounded.store")


class Store(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict, ttl: int) -> None: ...
    def incr(self, bucket: str, ttl: int) -> int: ...


class MemoryStore:
    def __init__(self) -> None:
        self._kv: dict[str, tuple[float, dict]] = {}
        self._counts: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            item = self._kv.get(key)
            if not item or item[0] < time.time():
                return None
            return item[1]

    def set(self, key: str, value: dict, ttl: int) -> None:
        with self._lock:
            self._kv[key] = (time.time() + ttl, value)

    def incr(self, bucket: str, ttl: int) -> int:
        with self._lock:
            expires, count = self._counts.get(bucket, (time.time() + ttl, 0))
            if expires < time.time():
                expires, count = time.time() + ttl, 0
            self._counts[bucket] = (expires, count + 1)
            return count + 1


class PostgresStore:
    def __init__(self, url: str) -> None:
        self.url = url
        self._conn = None
        self._lock = threading.Lock()
        self._fallback = MemoryStore()

    def _db(self):
        import psycopg

        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=5)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS ga_cache (key text PRIMARY KEY, value jsonb NOT NULL, expires_at timestamptz NOT NULL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS ga_counters (bucket text PRIMARY KEY, count int NOT NULL, expires_at timestamptz NOT NULL)"
            )
        return self._conn

    def _reset(self, error: Exception) -> None:
        log.warning("store falling back to memory: %s", type(error).__name__)
        self._conn = None

    def get(self, key: str) -> dict | None:
        with self._lock:
            try:
                row = self._db().execute(
                    "SELECT value FROM ga_cache WHERE key = %s AND expires_at > now()", (key,)
                ).fetchone()
                return row[0] if row else None
            except Exception as e:  # noqa: BLE001 - any database failure degrades to memory
                self._reset(e)
                return self._fallback.get(key)

    def set(self, key: str, value: dict, ttl: int) -> None:
        with self._lock:
            try:
                self._db().execute(
                    "INSERT INTO ga_cache VALUES (%s, %s, now() + make_interval(secs => %s)) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
                    (key, json.dumps(value), ttl),
                )
            except Exception as e:  # noqa: BLE001
                self._reset(e)
                self._fallback.set(key, value, ttl)

    def incr(self, bucket: str, ttl: int) -> int:
        with self._lock:
            try:
                return self._db().execute(
                    "INSERT INTO ga_counters VALUES (%s, 1, now() + make_interval(secs => %s)) "
                    "ON CONFLICT (bucket) DO UPDATE SET "
                    "count = CASE WHEN ga_counters.expires_at < now() THEN 1 ELSE ga_counters.count + 1 END, "
                    "expires_at = CASE WHEN ga_counters.expires_at < now() THEN excluded.expires_at ELSE ga_counters.expires_at END "
                    "RETURNING count",
                    (bucket, ttl),
                ).fetchone()[0]
            except Exception as e:  # noqa: BLE001
                self._reset(e)
                return self._fallback.incr(bucket, ttl)


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        url = os.environ.get("DATABASE_URL")
        _store = PostgresStore(url) if url else MemoryStore()
    return _store


def reset_store(store: Store | None = None) -> None:
    global _store
    _store = store


HOUR, DAY = 3600, 86_400


def limits() -> tuple[int, int]:
    return int(os.environ.get("RATE_LIMIT_PER_HOUR", "30")), int(os.environ.get("DAILY_LLM_CAP", "250"))


def allow_llm_call(client_id: str) -> bool:
    """Counts one model-backed request against the visitor's hourly and the site's daily budget."""
    per_hour, per_day = limits()
    store = get_store()
    now = int(time.time())
    if store.incr(f"ip:{client_id}:{now // HOUR}", HOUR) > per_hour:
        return False
    return store.incr(f"day:{now // DAY}", DAY) <= per_day
