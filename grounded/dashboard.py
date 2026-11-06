"""Chart data. Deterministic and instant: nothing here involves a model."""
from __future__ import annotations

from . import data
from .catalog import (
    DIMENSIONS,
    LIKERT,
    MIN_CELL_N,
    MIN_SEGMENT_N,
    QUARTERS,
    QUESTIONS,
    THEMES,
    Filters,
    quarter_label,
)
from .stats import ci95, round_half_up


def _cell(m) -> dict:
    if m.n < MIN_CELL_N:
        return {"value": None, "n": None, "lo": None, "hi": None, "small": True}
    ci = ci95(m)
    return {
        "value": round_half_up(m.mean, 2), "n": m.n, "small": m.n < MIN_SEGMENT_N,
        "lo": round_half_up(ci[0], 2) if ci else None, "hi": round_half_up(ci[1], 2) if ci else None,
    }


def build(f: Filters) -> dict:
    n = data.count(f)
    time_free = f.model_copy(update={"period": "all"})  # time charts always show all quarters

    trend = []
    for q, names in QUESTIONS.items():
        by_quarter = data.moments_by(time_free, q, "quarter")
        points = []
        for quarter in QUARTERS:
            m = by_quarter.get(quarter)
            cell = _cell(m) if m else {"value": None, "n": None, "small": True}
            points.append({"value": cell["value"], "n": cell["n"], "small": cell["small"]})
        trend.append({"key": q, "label": names["en"], "points": points})

    distribution = []
    for q, names in QUESTIONS.items():
        counts = data.distribution(f, q)
        total = sum(counts)
        hidden = total < MIN_CELL_N
        distribution.append({
            "key": q, "label": names["en"], "n": None if hidden else total,
            "pct": [None if hidden else round_half_up(100 * c / total, 1) for c in counts],
        })

    segments: dict = {}
    for dim, values in DIMENSIONS.items():
        if getattr(f, dim) != "all":
            continue
        segments[dim] = {}
        for q in QUESTIONS:
            groups = data.moments_by(f, q, dim)
            rows = []
            for v in values:
                m = groups.get(v)
                rows.append({"name": v, **(_cell(m) if m else {"value": None, "n": None, "lo": None, "hi": None, "small": True})})
            segments[dim][q] = rows

    nps_rows = []
    by_quarter = data.nps_by(time_free, "quarter")
    for quarter in QUARTERS:
        c = by_quarter.get(quarter)
        if not c or c.n < MIN_CELL_N:
            nps_rows.append({"quarter": quarter, "n": None, "score": None, "promoters": None, "passives": None, "detractors": None, "small": True})
            continue
        nps_rows.append({
            "quarter": quarter, "n": c.n, "score": round_half_up(c.score, 1), "small": c.n < MIN_SEGMENT_N,
            "promoters": round_half_up(100 * c.promoters / c.n, 1),
            "passives": round_half_up(100 * c.passives / c.n, 1),
            "detractors": round_half_up(100 * c.detractors / c.n, 1),
        })

    counts, total = data.themes(f)
    themes = [
        {"key": k, "label": THEMES[k]["en"], "count": c, "pct": round_half_up(100 * c / total, 1)}
        for k, c in counts.items() if c >= MIN_CELL_N
    ]

    current = data.nps(f)
    sat = data.moments(f, "satisfaction")
    hidden = n < MIN_CELL_N
    return {
        "n": None if hidden else n,
        "too_small": hidden,
        "scope": f.scope_label("en"),
        "selected_quarters": f.quarters(),
        "quarters": [{"key": q, "label": quarter_label(q)} for q in QUARTERS],
        "kpis": {
            "satisfaction": None if hidden else round_half_up(sat.mean, 2),
            "nps": None if hidden or not current.n else round_half_up(current.score, 1),
            "promoters": None if hidden or not current.n else round_half_up(100 * current.promoters / current.n, 1),
            "detractors": None if hidden or not current.n else round_half_up(100 * current.detractors / current.n, 1),
        },
        "trend": trend,
        "distribution": distribution,
        "likert": LIKERT["en"],
        "segments": segments,
        "nps": nps_rows,
        "themes": themes,
    }


def meta() -> dict:
    return {
        "periods": [{"value": "all", "label": "All 6 quarters"}, {"value": "2025", "label": "2025"}, {"value": "2026", "label": "2026"}]
        + [{"value": q, "label": quarter_label(q)} for q in QUARTERS],
        "regions": DIMENSIONS["region"], "departments": DIMENSIONS["department"], "roles": DIMENSIONS["role"],
        "questions": [{"key": k, "label": v["en"]} for k, v in QUESTIONS.items()],
    }
