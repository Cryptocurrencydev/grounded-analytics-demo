"""Builds the stat sheet: the complete set of figures the model is allowed to talk about."""
from __future__ import annotations

import hashlib
import hmac
import os

from pydantic import BaseModel, Field

from . import data
from .catalog import (
    ALPHA,
    DIMENSIONS,
    MIN_CELL_N,
    MIN_N_INTERPRET,
    MIN_SEGMENT_N,
    QUARTERS,
    QUESTIONS,
    SMALL_SAMPLE_WARN,
    THEMES,
    Filters,
    comparison_windows,
    quarter_label,
    tr,
)
from .models import ChartRef, Number, Stat
from .stats import Moments, TestResult, anova, benjamini_hochberg, chi2_distribution, nps_z, round_half_up, welch_t


class Warning_(BaseModel):
    code: str
    text: str


class StatSheet(BaseModel):
    scope: str
    n: int | None
    insufficient: bool
    comparison: str | None
    warnings: list[Warning_] = Field(default_factory=list)
    stats: list[Stat] = Field(default_factory=list)

    def by_id(self) -> dict[str, Stat]:
        return {s.id: s for s in self.stats}

    def for_llm(self) -> dict:
        return {
            "scope": self.scope,
            "n_responses": self.n,
            "comparison": self.comparison,
            "warnings": [w.text for w in self.warnings],
            "stats": [s.for_llm() for s in self.stats],
        }


def pseudonym(response_id: str) -> str:
    salt = os.environ.get("PSEUDONYM_SALT", "local-dev-salt").encode()
    return "p_" + hmac.new(salt, response_id.encode(), hashlib.sha256).hexdigest()[:10]


def scope_entities(f: Filters) -> list[str]:
    return [v for v in (f.region, f.department, f.role) if v != "all"]


def _num(name: str, value: float, unit, decimals: int) -> Number:
    return Number(name=name, value=round_half_up(value, decimals), unit=unit, decimals=decimals)


def _direction(delta: float) -> str:
    return "flat" if delta == 0 else ("up" if delta > 0 else "down")


def _msg(lang: str, en: str, de: str) -> str:
    return de if lang == "de" else en


def build_sheet(f: Filters, lang: str = "en") -> StatSheet:
    n = data.count(f)
    window = comparison_windows(f)
    sheet = StatSheet(
        scope=f.scope_label(lang), n=n, insufficient=n < MIN_N_INTERPRET,
        comparison=window[2] if window else None,
    )
    stats: list[Stat] = []

    def add(**kw) -> Stat:
        s = Stat(id=f"S{len(stats) + 1:02d}", **kw)
        stats.append(s)
        return s

    if sheet.insufficient:
        hidden = n < MIN_CELL_N  # counts this small are never shown
        how_many_en = f"Fewer than {MIN_CELL_N}" if hidden else f"Only {n}"
        how_many_de = f"Weniger als {MIN_CELL_N}" if hidden else f"Nur {n}"
        if hidden:
            sheet.n = None
        sheet.warnings.append(Warning_(code="insufficient_sample", text=_msg(
            lang,
            f"{how_many_en} responses match this filter. At least {MIN_N_INTERPRET} are needed for an interpretation.",
            f"{how_many_de} Antworten passen zu diesem Filter. Für eine Interpretation sind mindestens {MIN_N_INTERPRET} nötig.",
        )))
        return sheet
    add(key="n", kind="count", value=n, unit="count", decimals=0, n=n,
        label=_msg(lang, "Responses in the current filter", "Antworten im aktuellen Filter"))
    if n < SMALL_SAMPLE_WARN:
        sheet.warnings.append(Warning_(code="small_sample", text=_msg(
            lang, f"Small sample ({n} responses): treat differences with caution.",
            f"Kleine Stichprobe ({n} Antworten): Unterschiede mit Vorsicht lesen.",
        )))

    # Levels for the selected window
    for q, names in QUESTIONS.items():
        m = data.moments(f, q)
        dist = data.distribution(f, q)
        top2 = 100 * (dist[3] + dist[4]) / m.n
        bottom2 = 100 * (dist[0] + dist[1]) / m.n
        add(key=f"mean.{q}", kind="mean", value=round_half_up(m.mean, 2), unit="scale", decimals=2, n=m.n,
            label=_msg(lang, f"{names['en']}: mean on the 1-5 scale", f"{names['de']}: Mittelwert auf der Skala 1-5"),
            entities=[f"q:{q}"], chart=ChartRef(chart="trend", series=q))
        add(key=f"top2.{q}", kind="top2", value=round_half_up(top2, 1), unit="pct", decimals=1, n=m.n,
            label=_msg(lang, f"{names['en']}: share who agree (top 2 boxes)", f"{names['de']}: Anteil Zustimmung (Top 2)"),
            related=[_num("disagree_pct", bottom2, "pct", 1)],
            entities=[f"q:{q}"], chart=ChartRef(chart="distribution", categories=[q]))

    counts = data.nps(f)
    add(key="nps", kind="nps", value=round_half_up(counts.score, 1), unit="nps", decimals=1, n=counts.n,
        label=_msg(lang, "Employee NPS", "Mitarbeiter-NPS"),
        related=[_num("promoters_pct", 100 * counts.promoters / counts.n, "pct", 1),
                 _num("passives_pct", 100 * counts.passives / counts.n, "pct", 1),
                 _num("detractors_pct", 100 * counts.detractors / counts.n, "pct", 1)],
        chart=ChartRef(chart="nps", series="nps"))

    _change_stats(f, lang, sheet, add, window)
    if f.period == "all":  # the whole span too, so slow drifts are visible
        span = f"{quarter_label(QUARTERS[-1])} vs {quarter_label(QUARTERS[0])}"
        _change_stats(f, lang, sheet, add, ([QUARTERS[-1]], [QUARTERS[0]], span), prefix="span")
    _segment_stats(f, lang, sheet, add)
    _theme_stats(f, lang, add)
    sheet.stats = stats
    return sheet


def _change_stats(f: Filters, lang: str, sheet: StatSheet, add, window, prefix: str = "delta") -> None:
    if not window:
        sheet.warnings.append(Warning_(code="no_previous_period", text=_msg(
            lang, "No earlier period of the same length exists, so there are no change figures.",
            "Es gibt keinen vorherigen Zeitraum gleicher Länge, daher keine Veränderungswerte.",
        )))
        return
    cur_q, prev_q, label = window
    rows: list[dict] = []
    for q, names in QUESTIONS.items():
        a, b = data.moments(f, q, cur_q), data.moments(f, q, prev_q)
        if min(a.n, b.n) < MIN_SEGMENT_N:
            continue
        rows.append(dict(key=q, a=a, b=b, test=welch_t(a, b), names=names,
                         chi2=chi2_distribution(data.distribution(f, q, cur_q), data.distribution(f, q, prev_q))))
    na, nb = data.nps(f, cur_q), data.nps(f, prev_q)
    nps_row = None
    if min(na.n, nb.n) >= MIN_SEGMENT_N:
        nps_row = dict(a=na, b=nb, test=nps_z(na, nb))
    if not rows and nps_row is None:
        sheet.warnings.append(Warning_(code="change_suppressed", text=_msg(
            lang, f"Too few responses in one of the periods to compare {label}.",
            f"Zu wenige Antworten in einem der Zeiträume für den Vergleich {label}.",
        )))
        return

    tested = [r for r in rows if r["test"]] + ([nps_row] if nps_row and nps_row["test"] else [])
    for r, p_adj in zip(tested, benjamini_hochberg([r["test"].p for r in tested])):
        r["p_adj"] = p_adj

    up = down = 0
    for r in rows:
        q, a, b, names = r["key"], r["a"], r["b"], r["names"]
        delta = a.mean - b.mean
        p_adj = r.get("p_adj")
        significant = p_adj is not None and p_adj < ALPHA
        up += significant and delta > 0
        down += significant and delta < 0
        related = [_num("current", a.mean, "scale", 2), _num("previous", b.mean, "scale", 2),
                   _num("n_current", a.n, "count", 0), _num("n_previous", b.n, "count", 0)]
        if p_adj is not None:
            related.append(_num("p_adjusted", p_adj, "p", 3))
        if r["test"] and r["test"].effect is not None:
            related.append(_num("cohens_d", r["test"].effect, "scale_delta", 2))
        if r["chi2"]:
            related.append(_num("distribution_shift_p", r["chi2"].p, "p", 3))
        add(key=f"{prefix}.{q}", kind="delta", value=round_half_up(delta, 2), unit="scale_delta", decimals=2, n=a.n + b.n,
            label=_msg(lang, f"{names['en']}: change in mean, {label}", f"{names['de']}: Veränderung des Mittelwerts, {label}"),
            related=related, direction=_direction(round_half_up(delta, 2)), significant=significant,
            test="Welch t-test, Benjamini-Hochberg adjusted", entities=[f"q:{q}"],
            chart=ChartRef(chart="trend", series=q))
    if nps_row:
        delta = na.score - nb.score
        p_adj = nps_row.get("p_adj")
        significant = p_adj is not None and p_adj < ALPHA
        up += significant and delta > 0
        down += significant and delta < 0
        related = [_num("current", na.score, "nps", 1), _num("previous", nb.score, "nps", 1),
                   _num("n_current", na.n, "count", 0), _num("n_previous", nb.n, "count", 0)]
        if p_adj is not None:
            related.append(_num("p_adjusted", p_adj, "p", 3))
        add(key=f"{prefix}.nps", kind="delta", value=round_half_up(delta, 1), unit="nps_delta", decimals=1, n=na.n + nb.n,
            label=_msg(lang, f"Employee NPS: change, {label}", f"Mitarbeiter-NPS: Veränderung, {label}"),
            related=related, direction=_direction(round_half_up(delta, 1)), significant=significant,
            test="Two-sample z-test, Benjamini-Hochberg adjusted", chart=ChartRef(chart="nps", series="nps"))
    add(key=f"{prefix}.significant_changes", kind="count", value=up + down, unit="count", decimals=0, n=sheet.n,
        label=_msg(lang, f"Measures with a significant change, {label}", f"Kennzahlen mit signifikanter Veränderung, {label}"),
        related=[_num("significant_up", up, "count", 0), _num("significant_down", down, "count", 0),
                 _num("measures_tested", len(tested), "count", 0)])


def _segment_stats(f: Filters, lang: str, sheet: StatSheet, add) -> None:
    excluded: dict[str, int] = {}
    tests: list[dict] = []
    for dim in DIMENSIONS:
        if getattr(f, dim) != "all":
            continue
        for q, names in QUESTIONS.items():
            groups = data.moments_by(f, q, dim)
            usable: dict[str, Moments] = {}
            for name, m in groups.items():
                if m.n >= MIN_SEGMENT_N:
                    usable[name] = m
                else:
                    excluded[name] = m.n
            if len(usable) < 2:
                continue
            result: TestResult | None = anova(list(usable.values()))
            if result:
                tests.append(dict(dim=dim, q=q, names=names, groups=usable, test=result))
    for t, p_adj in zip(tests, benjamini_hochberg([t["test"].p for t in tests])):
        t["p_adj"] = p_adj
    # The sheet carries the clearest gaps, not all of them, to keep the prompt small
    for t in sorted(tests, key=lambda t: (t["p_adj"], -t["test"].statistic))[:8]:
        groups = t["groups"]
        top = max(groups, key=lambda k: groups[k].mean)
        bottom = min(groups, key=lambda k: groups[k].mean)
        q, dim, names = t["q"], t["dim"], t["names"]
        gap = groups[top].mean - groups[bottom].mean
        add(key=f"gap.{dim}.{q}", kind="segment_gap", value=round_half_up(gap, 2), unit="scale_delta", decimals=2,
            n=sum(g.n for g in groups.values()),
            label=_msg(lang, f"{names['en']}: highest vs lowest {dim}: {top} vs {bottom}",
                       f"{names['de']}: höchste vs niedrigste {tr(dim, 'de')}: {tr(top, 'de')} vs {tr(bottom, 'de')}"),
            related=[_num("highest_mean", groups[top].mean, "scale", 2), _num("lowest_mean", groups[bottom].mean, "scale", 2),
                     _num("n_highest", groups[top].n, "count", 0), _num("n_lowest", groups[bottom].n, "count", 0),
                     _num("p_adjusted", t["p_adj"], "p", 3), _num("eta_squared", t["test"].effect, "scale_delta", 3)],
            significant=t["p_adj"] < ALPHA, test="One-way ANOVA across segments, Benjamini-Hochberg adjusted",
            entities=[f"q:{q}", top, bottom],
            chart=ChartRef(chart="segments", dimension=dim, question=q, categories=[top, bottom]))
    if excluded:
        names = ", ".join(f"{tr(k, lang)} (n={v})" if v >= MIN_CELL_N else f"{tr(k, lang)} (n<{MIN_CELL_N})"
                          for k, v in sorted(excluded.items()))
        sheet.warnings.append(Warning_(code="segments_excluded", text=_msg(
            lang, f"Left out of segment comparisons, fewer than {MIN_SEGMENT_N} responses: {names}.",
            f"Nicht in Segmentvergleichen, weniger als {MIN_SEGMENT_N} Antworten: {names}.",
        )))


def _theme_stats(f: Filters, lang: str, add) -> None:
    counts, total = data.themes(f)
    for theme, c in list(counts.items())[:5]:
        if c < MIN_CELL_N or total < MIN_SEGMENT_N:
            continue
        add(key=f"theme.{theme}", kind="theme_share", value=round_half_up(100 * c / total, 1), unit="pct", decimals=1, n=total,
            label=_msg(lang, f"Comment theme: {THEMES[theme]['en']} (share of comments)",
                       f"Kommentarthema: {THEMES[theme]['de']} (Anteil der Kommentare)"),
            related=[_num("comments_in_theme", c, "count", 0)],
            refs=[pseudonym(r) for r in data.theme_response_ids(f, theme)],
            chart=ChartRef(chart="themes", categories=[theme]))
