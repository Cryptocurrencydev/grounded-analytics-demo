"""The only module that touches the dataset. SQL is built from whitelisted names, values are bound."""
from __future__ import annotations

import threading
from functools import lru_cache

import duckdb

from .catalog import DATA_DIR, DIMENSIONS, QUARTERS, QUESTIONS, Filters
from .stats import Moments, NpsCounts

_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


def conn() -> duckdb.DuckDBPyConnection:
    global _conn
    with _lock:
        if _conn is None:
            c = duckdb.connect(":memory:")
            c.execute("SET threads=1")
            # Read-only for the process: one table, loaded once. No comment text in this file.
            c.execute(f"CREATE TABLE responses AS SELECT * FROM read_parquet('{DATA_DIR / 'responses.parquet'}')")
            _conn = c
        return _conn.cursor()


def _where(f: Filters, quarters: list[str] | None = None) -> tuple[str, list]:
    qs = quarters if quarters is not None else f.quarters()
    clauses = [f"quarter IN ({','.join('?' * len(qs))})"]
    params: list = list(qs)
    for dim, value in (("region", f.region), ("department", f.department), ("role", f.role)):
        if value != "all":
            clauses.append(f"{dim} = ?")
            params.append(value)
    return " AND ".join(clauses), params


def _column(question: str) -> str:
    if question not in QUESTIONS:
        raise ValueError(f"unknown question {question!r}")
    return f"q_{question}"


def _group_column(group_by: str) -> str:
    if group_by != "quarter" and group_by not in DIMENSIONS:
        raise ValueError(f"unknown dimension {group_by!r}")
    return group_by


def count(f: Filters, quarters: list[str] | None = None) -> int:
    where, params = _where(f, quarters)
    return conn().execute(f"SELECT count(*) FROM responses WHERE {where}", params).fetchone()[0]


def moments(f: Filters, question: str, quarters: list[str] | None = None) -> Moments:
    col = _column(question)
    where, params = _where(f, quarters)
    n, mean, var = conn().execute(
        f"SELECT count({col}), avg({col}), var_samp({col}) FROM responses WHERE {where}", params
    ).fetchone()
    return Moments(n, mean or 0.0, var or 0.0)


def moments_by(f: Filters, question: str, group_by: str, quarters: list[str] | None = None) -> dict[str, Moments]:
    col, group = _column(question), _group_column(group_by)
    where, params = _where(f, quarters)
    rows = conn().execute(
        f"SELECT {group}, count({col}), avg({col}), var_samp({col}) FROM responses WHERE {where} GROUP BY 1 ORDER BY 1",
        params,
    ).fetchall()
    return {r[0]: Moments(r[1], r[2] or 0.0, r[3] or 0.0) for r in rows}


def distribution(f: Filters, question: str, quarters: list[str] | None = None) -> list[int]:
    col = _column(question)
    where, params = _where(f, quarters)
    rows = dict(conn().execute(
        f"SELECT {col}, count(*) FROM responses WHERE {where} GROUP BY 1", params
    ).fetchall())
    return [rows.get(i, 0) for i in range(1, 6)]


_NPS_SELECT = (
    "count(*) FILTER (WHERE nps >= 9), count(*) FILTER (WHERE nps BETWEEN 7 AND 8), "
    "count(*) FILTER (WHERE nps <= 6)"
)


def nps(f: Filters, quarters: list[str] | None = None) -> NpsCounts:
    where, params = _where(f, quarters)
    return NpsCounts(*conn().execute(f"SELECT {_NPS_SELECT} FROM responses WHERE {where}", params).fetchone())


def nps_by(f: Filters, group_by: str, quarters: list[str] | None = None) -> dict[str, NpsCounts]:
    group = _group_column(group_by)
    where, params = _where(f, quarters)
    rows = conn().execute(
        f"SELECT {group}, {_NPS_SELECT} FROM responses WHERE {where} GROUP BY 1 ORDER BY 1", params
    ).fetchall()
    return {r[0]: NpsCounts(r[1], r[2], r[3]) for r in rows}


def themes(f: Filters, quarters: list[str] | None = None) -> tuple[dict[str, int], int]:
    """Comment counts per theme, plus how many responses left a comment."""
    where, params = _where(f, quarters)
    rows = conn().execute(
        f"SELECT theme, count(*) FROM responses WHERE {where} AND theme IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1",
        params,
    ).fetchall()
    return {r[0]: r[1] for r in rows}, sum(r[1] for r in rows)


def theme_response_ids(f: Filters, theme: str, limit: int = 3) -> list[str]:
    """Internal ids for pseudonymised references. Callers must hash these before they go anywhere."""
    where, params = _where(f)
    rows = conn().execute(
        f"SELECT response_id FROM responses WHERE {where} AND theme = ? ORDER BY response_id LIMIT ?",
        [*params, theme, limit],
    ).fetchall()
    return [r[0] for r in rows]


@lru_cache(maxsize=1)
def dataset_version() -> str:
    c = conn()
    n, last = c.execute("SELECT count(*), max(response_id) FROM responses").fetchone()
    return f"{n}-{last}-{len(QUARTERS)}"
