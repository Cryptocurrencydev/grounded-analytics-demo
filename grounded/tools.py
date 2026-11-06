"""The chat model's whole interface to the data. It can pick from these lists and nothing else."""
from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from . import data
from .catalog import (
    ALPHA,
    DIMENSIONS,
    MIN_CELL_N,
    MIN_N_INTERPRET,
    QUARTERS,
    QUESTIONS,
    THEME_ENTITIES,
    THEMES,
    YEARS,
    Department,
    Filters,
    Period,
    Region,
    Role,
    quarter_label,
    tr,
)
from .models import ChartRef, Number, Stat
from .stats import chi2_distribution, nps_z, round_half_up, welch_t

_Q = list(QUESTIONS)
MEASURES = (
    [f"mean_{q}" for q in _Q] + [f"agree_pct_{q}" for q in _Q] + [f"disagree_pct_{q}" for q in _Q]
    + ["nps", "promoters_pct", "detractors_pct", "response_count", "comment_theme_share"]
)
GROUP_BY = ["none", "quarter", "region", "department", "role"]
COMPARE_DIMENSIONS = ["region", "department", "role", "period"]
COMPARABLE = [m for m in MEASURES if m.startswith(("mean_", "agree_pct_")) or m == "nps"]

_FILTER_PROPS = {
    "period": {"type": "string", "enum": list(get_args(Period))},
    "region": {"type": "string", "enum": list(get_args(Region))},
    "department": {"type": "string", "enum": list(get_args(Department))},
    "role": {"type": "string", "enum": list(get_args(Role))},
}
_FILTERS = {"type": "object", "properties": _FILTER_PROPS, "required": list(_FILTER_PROPS), "additionalProperties": False}

TOOLS = [
    {
        "name": "query_aggregate", "strict": True,
        "description": "Compute one whitelisted measure for a filtered slice, optionally per group. Returns stats with ids to cite. Slices under 30 responses come back as insufficient_sample with no value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "measure": {"type": "string", "enum": MEASURES},
                "group_by": {"type": "string", "enum": GROUP_BY},
                "filters": _FILTERS,
            },
            "required": ["measure", "group_by", "filters"], "additionalProperties": False,
        },
    },
    {
        "name": "compare_segments", "strict": True,
        "description": "Test the difference in a measure between two segments or two periods. Returns the difference, both values, both n, the p-value and whether it is significant (Welch t-test for means, chi-square for agree shares, z-test for NPS). For dimension period, a and b are period values such as 2026 or 2026-Q1.",
        "input_schema": {
            "type": "object",
            "properties": {
                "measure": {"type": "string", "enum": COMPARABLE},
                "dimension": {"type": "string", "enum": COMPARE_DIMENSIONS},
                "a": {"type": "string"}, "b": {"type": "string"},
                "filters": _FILTERS,
            },
            "required": ["measure", "dimension", "a", "b", "filters"], "additionalProperties": False,
        },
    },
    {
        "name": "apply_dashboard_filters", "strict": True,
        "description": "Change the filters on the user's dashboard. Use only when the user asks to see or filter something. Returns the new response count.",
        "input_schema": _FILTERS,
    },
]


class QueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: Literal[tuple(MEASURES)]  # type: ignore[valid-type]
    group_by: Literal[tuple(GROUP_BY)] = "none"  # type: ignore[valid-type]
    filters: Filters = Filters()


class CompareArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: Literal[tuple(COMPARABLE)]  # type: ignore[valid-type]
    dimension: Literal[tuple(COMPARE_DIMENSIONS)]  # type: ignore[valid-type]
    a: str
    b: str
    filters: Filters = Filters()


class Ledger:
    """Every stat produced this turn. The validator accepts citations from here and nowhere else."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.stats: dict[str, Stat] = {}
        self.applied: Filters | None = None
        self.calls: list[dict] = []

    def add(self, **kw) -> Stat:
        s = Stat(id=f"C{len(self.stats) + 1:02d}", **kw)
        self.stats[s.id] = s
        return s


def _measure_label(measure: str, lang: str) -> str:
    de = lang == "de"
    for prefix, en_l, de_l in (("mean_", "mean (1-5)", "Mittelwert (1-5)"), ("agree_pct_", "share who agree", "Anteil Zustimmung"),
                               ("disagree_pct_", "share who disagree", "Anteil Ablehnung")):
        if measure.startswith(prefix):
            q = QUESTIONS[measure[len(prefix):]]["de" if de else "en"]
            return f"{q}: {de_l if de else en_l}"
    return {
        "nps": ("Employee NPS", "Mitarbeiter-NPS"), "promoters_pct": ("Promoters", "Promotoren"),
        "detractors_pct": ("Detractors", "Detraktoren"), "response_count": ("Responses", "Antworten"),
    }[measure][1 if de else 0]


def _entities(measure: str, f: Filters, extra: list[str] | None = None) -> list[str]:
    out = [v for v in (f.region, f.department, f.role) if v != "all"] + (extra or [])
    q = measure.rsplit("_", 1)[-1]
    if q in QUESTIONS:
        out.append(f"q:{q}")
    return out


def _cell(measure: str, f: Filters, quarters: list[str] | None) -> tuple[float, str, int, int]:
    """(value, unit, decimals, n) for one slice, rounded once, here."""
    if measure == "response_count":
        n = data.count(f, quarters)
        return n, "count", 0, n
    if measure in ("nps", "promoters_pct", "detractors_pct"):
        c = data.nps(f, quarters)
        if not c.n:
            return 0, "nps", 1, 0
        if measure == "nps":
            return round_half_up(c.score, 1), "nps", 1, c.n
        part = c.promoters if measure == "promoters_pct" else c.detractors
        return round_half_up(100 * part / c.n, 1), "pct", 1, c.n
    kind, q = measure.rsplit("_", 1)
    if kind == "mean":
        m = data.moments(f, q, quarters)
        return round_half_up(m.mean, 2), "scale", 2, m.n
    dist = data.distribution(f, q, quarters)
    n = sum(dist)
    if not n:
        return 0, "pct", 1, 0
    part = dist[3] + dist[4] if kind == "agree_pct" else dist[0] + dist[1]
    return round_half_up(100 * part / n, 1), "pct", 1, n


def _insufficient(ledger: Ledger, label: str, n: int, entities: list[str]) -> dict:
    hidden = n < MIN_CELL_N
    s = ledger.add(
        key="insufficient", kind="insufficient", label=f"{label}: too few responses",
        value=MIN_N_INTERPRET, unit="count", decimals=0, n=0 if hidden else n, entities=entities,
        related=[Number(name="suppression_threshold", value=MIN_CELL_N, unit="count", decimals=0)] if hidden else [],
    )
    d = {"id": s.id, "group": label, "status": "insufficient_sample", "minimum_required": MIN_N_INTERPRET}
    d["n"] = f"fewer than {MIN_CELL_N}" if hidden else n
    return d


def query_aggregate(args: QueryArgs, ledger: Ledger) -> dict:
    f, lang = args.filters, ledger.lang
    if args.measure == "comment_theme_share":
        return _themes(f, ledger)
    label = _measure_label(args.measure, lang)
    if args.group_by == "none":
        groups: list[tuple[str, Filters, list[str] | None, list[str]]] = [(f.scope_label(lang), f, None, [])]
    elif args.group_by == "quarter":
        groups = [(quarter_label(q), f, [q], []) for q in f.quarters()]
    else:
        current = getattr(f, args.group_by)
        values = [current] if current != "all" else DIMENSIONS[args.group_by]
        groups = [(tr(v, lang), f.model_copy(update={args.group_by: v}), None, [v]) for v in values]

    rows = []
    for name, gf, quarters, extra in groups:
        value, unit, decimals, n = _cell(args.measure, gf, quarters)
        entities = _entities(args.measure, gf, extra)
        full = f"{label}, {name}"
        too_small = n < MIN_CELL_N if args.measure == "response_count" else n < MIN_N_INTERPRET
        if too_small:
            rows.append(_insufficient(ledger, full, n, entities))
            continue
        s = ledger.add(key=f"{args.measure}.{name}", kind="aggregate", label=full, value=value, unit=unit,
                       decimals=decimals, n=n, entities=entities)
        rows.append({**s.for_llm(), "group": name, "status": "ok"})
    return {"measure": args.measure, "scope": f.scope_label(lang), "rows": rows}


def _themes(f: Filters, ledger: Ledger) -> dict:
    counts, total = data.themes(f)
    rows = []
    for theme, c in counts.items():
        name = THEMES[theme][ledger.lang]
        if c < MIN_CELL_N or total < MIN_N_INTERPRET:
            rows.append(_insufficient(ledger, name, c, []))
            continue
        s = ledger.add(key=f"theme.{theme}", kind="aggregate", label=name, value=round_half_up(100 * c / total, 1),
                       unit="pct", decimals=1, n=total,
                       related=[Number(name="comments_in_theme", value=c, unit="count", decimals=0)],
                       entities=THEME_ENTITIES.get(theme, []),
                       chart=ChartRef(chart="themes", categories=[theme]))
        rows.append({**s.for_llm(), "status": "ok"})
    return {"measure": "comment_theme_share", "scope": f.scope_label(ledger.lang), "rows": rows}


def _resolve_side(args: CompareArgs, value: str) -> tuple[Filters, list[str] | None, str]:
    f = args.filters
    if args.dimension == "period":
        if value in YEARS:
            return f, YEARS[value], value
        if value in QUARTERS:
            return f, [value], quarter_label(value)
        raise ValueError(f"unknown period {value!r}")
    if value not in DIMENSIONS[args.dimension]:
        raise ValueError(f"unknown {args.dimension} {value!r}")
    return f.model_copy(update={args.dimension: value}), None, value


def compare_segments(args: CompareArgs, ledger: Ledger) -> dict:
    lang = ledger.lang
    fa, qa, la = _resolve_side(args, args.a)
    fb, qb, lb = _resolve_side(args, args.b)
    label = _measure_label(args.measure, lang)
    va, unit, decimals, na = _cell(args.measure, fa, qa)
    vb, _, _, nb = _cell(args.measure, fb, qb)
    ents = _entities(args.measure, args.filters, [x for x in (args.a, args.b) if args.dimension != "period"])
    title = f"{label}: {tr(la, lang)} vs {tr(lb, lang)}"
    if min(na, nb) < MIN_N_INTERPRET:
        return {"status": "insufficient_sample", "rows": [
            _insufficient(ledger, f"{label}, {tr(la, lang)}", na, ents),
            _insufficient(ledger, f"{label}, {tr(lb, lang)}", nb, ents),
        ]}
    if args.measure == "nps":
        ca, cb = data.nps(fa, qa), data.nps(fb, qb)
        test, delta, delta_unit = nps_z(ca, cb), ca.score - cb.score, "nps_delta"
    elif args.measure.startswith("mean_"):
        q = args.measure[len("mean_"):]
        ma, mb = data.moments(fa, q, qa), data.moments(fb, q, qb)
        test, delta, delta_unit = welch_t(ma, mb), ma.mean - mb.mean, "scale_delta"
    else:
        q = args.measure[len("agree_pct_"):]
        da, db = data.distribution(fa, q, qa), data.distribution(fb, q, qb)
        a2, b2 = da[3] + da[4], db[3] + db[4]
        test = chi2_distribution([a2, sum(da) - a2], [b2, sum(db) - b2])
        delta, delta_unit = 100 * (a2 / sum(da) - b2 / sum(db)), "pp"
    delta = round_half_up(delta, decimals)
    p = test.p if test else 1.0
    # A direction only means something over time, and time runs from the earlier period to the later one
    direction = None
    if args.dimension == "period" and delta != 0:
        a_is_later = max(qa) > max(qb)
        direction = "up" if (delta > 0) == a_is_later else "down"
    s = ledger.add(
        key=f"compare.{args.measure}", kind="delta", label=title, value=delta, unit=delta_unit, decimals=decimals,
        n=na + nb, significant=p < ALPHA, test=test.test if test else None,
        direction=direction, entities=ents,
        related=[
            Number(name="value_a", value=va, unit=unit, decimals=decimals),
            Number(name="value_b", value=vb, unit=unit, decimals=decimals),
            Number(name="n_a", value=na, unit="count", decimals=0),
            Number(name="n_b", value=nb, unit="count", decimals=0),
            Number(name="p_value", value=round_half_up(p, 3), unit="p", decimals=3),
        ],
    )
    return {"status": "ok", "a": tr(la, lang), "b": tr(lb, lang), "note": "value = a minus b", "rows": [s.for_llm()]}


def apply_filters(f: Filters, ledger: Ledger) -> dict:
    ledger.applied = f
    n = data.count(f)
    shown = n if n >= MIN_CELL_N else 0
    s = ledger.add(key="filters.n", kind="count", label=f"Responses after filtering: {f.scope_label(ledger.lang)}",
                   value=shown, unit="count", decimals=0, n=shown,
                   entities=[v for v in (f.region, f.department, f.role) if v != "all"])
    return {"status": "applied", "filters": f.model_dump(), "rows": [s.for_llm()]}


def execute(name: str, raw: dict, ledger: Ledger) -> tuple[dict, bool]:
    """Runs one tool call. Returns (result, is_error). Arguments are validated again here: the
    schema sent to the model is not the security boundary."""
    ledger.calls.append({"tool": name, "input": raw})
    try:
        if name == "query_aggregate":
            return query_aggregate(QueryArgs(**raw), ledger), False
        if name == "compare_segments":
            return compare_segments(CompareArgs(**raw), ledger), False
        if name == "apply_dashboard_filters":
            return apply_filters(Filters(**raw), ledger), False
    except (ValidationError, ValueError, TypeError) as e:
        return {"error": f"rejected: {str(e).splitlines()[0]}"}, True
    return {"error": f"unknown tool {name!r}"}, True
