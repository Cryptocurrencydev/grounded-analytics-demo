"""The eval set. Answers are computed here with pandas on the raw parquet, an independent path
from the DuckDB code the app uses. No expected value is typed by hand."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats as sps

ROOT = Path(__file__).resolve().parent.parent
DF = pd.read_parquet(ROOT / "data" / "responses.parquet")
MIN_N = 30
QUESTIONS = ["satisfaction", "workload", "leadership", "growth", "recognition", "wellbeing"]


def sl(period=None, **dims) -> pd.DataFrame:
    s = DF
    if period:
        s = s[s.quarter.str.startswith(period)]
    for k, v in dims.items():
        s = s[s[k] == v]
    return s


def nps(s) -> float:
    return 100 * ((s.nps >= 9).mean() - (s.nps <= 6).mean())


def agree(s, q) -> float:
    return 100 * (s[f"q_{q}"] >= 4).mean()


def disagree(s, q) -> float:
    return 100 * (s[f"q_{q}"] <= 2).mean()


def fig(name, value, unit, decimals) -> dict:
    return {"name": name, "value": float(value), "unit": unit, "decimals": decimals}


def mean_fig(name, s, q):
    return fig(name, s[f"q_{q}"].mean(), "scale", 2)


def count_fig(name, s):
    return fig(name, len(s), "count", 0)


def numeric(id, question, expected, context=()):
    return dict(id=id, category="numeric", question=question, expected=list(expected), context=list(context),
                refuse=False, significance=None, names=[])


def compare(id, question, a, b, value_fn, unit, delta_unit, decimals, label_a, label_b):
    va, vb = value_fn(a), value_fn(b)
    return dict(
        id=id, category="comparison", question=question,
        expected=[fig("difference", abs(va - vb), delta_unit, decimals)],
        context=[fig(label_a, va, unit, decimals), fig(label_b, vb, unit, decimals),
                 count_fig(f"n {label_a}", a), count_fig(f"n {label_b}", b)],
        refuse=False, significance=None, names=[],
    )


def significance(id, question, a, b, q, label_a, label_b):
    t = sps.ttest_ind(a[f"q_{q}"], b[f"q_{q}"], equal_var=False)
    va, vb = a[f"q_{q}"].mean(), b[f"q_{q}"].mean()
    return dict(
        id=id, category="significance", question=question, expected=[],
        context=[fig(label_a, va, "scale", 2), fig(label_b, vb, "scale", 2), fig("difference", abs(va - vb), "scale_delta", 2),
                 count_fig(f"n {label_a}", a), count_fig(f"n {label_b}", b)],
        refuse=False, significance=bool(t.pvalue < 0.05), names=[], p=float(t.pvalue),
    )


def refusal(id, category, question, slices=()):
    for s in slices:
        assert len(s) < MIN_N, f"{id} is not a tiny slice: n={len(s)}"
    return dict(id=id, category=category, question=question, expected=[], context=[], refuse=True,
                significance=None, names=[], n=[len(s) for s in slices])


def _slice_figures(s: pd.DataFrame, tag: str) -> list[dict]:
    """Every true figure a careful analyst could quote about one slice."""
    if not len(s):
        return []
    out = [count_fig(f"{tag} n", s)]
    for q in QUESTIONS:
        c = s[f"q_{q}"]
        out += [fig(f"{tag} {q} sum", c.sum(), "count", 0), mean_fig(f"{tag} {q} mean", s, q),
                fig(f"{tag} {q} sd", c.std(ddof=1), "scale", 2),
                fig(f"{tag} {q} agree n", (c >= 4).sum(), "count", 0), fig(f"{tag} {q} agree", agree(s, q), "pct", 1),
                fig(f"{tag} {q} disagree n", (c <= 2).sum(), "count", 0), fig(f"{tag} {q} disagree", disagree(s, q), "pct", 1)]
    groups = {"promoters": s.nps >= 9, "passives": s.nps.between(7, 8), "detractors": s.nps <= 6}
    out.append(fig(f"{tag} nps", nps(s), "nps", 1))
    for name, mask in groups.items():
        out += [fig(f"{tag} {name} n", mask.sum(), "count", 0), fig(f"{tag} {name}", 100 * mask.mean(), "pct", 1)]
    themes = s.theme.value_counts()
    out.append(fig(f"{tag} comments", themes.sum(), "count", 0))
    for k, v in themes.items():
        out += [fig(f"{tag} {k} n", v, "count", 0), fig(f"{tag} {k}", 100 * v / themes.sum(), "pct", 1)]
    return out


def truth_table(slices: list[pd.DataFrame]) -> list[dict]:
    """All true figures for a question's slices, per quarter too, and between pairs of slices.

    An answer's number counts as unsupported only if it matches nothing here. The table is wide on
    purpose: a wrong count can match by chance, which favours the baseline, never the grounded side.
    """
    out: list[dict] = []
    for i, s in enumerate(slices):
        out += _slice_figures(s, f"s{i}")
        for quarter, part in s.groupby("quarter"):
            out += _slice_figures(part, f"s{i} {quarter}")
    for i, a in enumerate(slices):
        for b in slices[i + 1:]:
            out.append(fig("n total", len(a) + len(b), "count", 0))
            out.append(fig("nps diff", abs(nps(a) - nps(b)), "nps_delta", 1))
            for q in QUESTIONS:
                x, y = a[f"q_{q}"], b[f"q_{q}"]
                t = sps.ttest_ind(x, y, equal_var=False)
                out += [fig(f"{q} diff", abs(x.mean() - y.mean()), "scale_delta", 2), fig(f"{q} t", abs(t.statistic), "scale_delta", 2),
                        fig(f"{q} df", t.df, "nps", 0), fig(f"{q} agree diff", abs(agree(a, q) - agree(b, q)), "pp", 1)]
    return out


def build() -> list[dict]:
    ops26, ops25 = sl("2026", department="Operations"), sl("2025", department="Operations")
    fin, ops = sl(department="Finance"), sl(department="Operations")
    north26, north25 = sl("2026", region="North"), sl("2025", region="North")
    dept_workload = DF.groupby("department").q_workload.mean()
    region_nps = {r: nps(sl(region=r)) for r in DF.region.unique()}
    themes = DF.theme.value_counts()
    q3, q2 = sl("2026-Q3"), sl("2026-Q2")
    sup3, sup2 = sl("2026-Q3", department="Support"), sl("2026-Q2", department="Support")

    questions = [
        numeric("n01", "What is the mean overall satisfaction score across all responses?",
                [mean_fig("mean", DF, "satisfaction")], [count_fig("n", DF)]),
        numeric("n02", "How many responses were submitted in Q3 2026?", [count_fig("n", sl("2026-Q3"))]),
        numeric("n03", "What is the overall employee NPS?", [fig("nps", nps(DF), "nps", 1)], [count_fig("n", DF)]),
        numeric("n04", "What was the employee NPS in Q3 2026?", [fig("nps", nps(q3), "nps", 1)], [count_fig("n", q3)]),
        numeric("n05", "What is the mean workload score for Operations in 2026?", [mean_fig("mean", ops26, "workload")], [count_fig("n", ops26)]),
        numeric("n06", "What is the mean trust-in-leadership score in the North region in Q3 2026?",
                [mean_fig("mean", sl("2026-Q3", region="North"), "leadership")], [count_fig("n", sl("2026-Q3", region="North"))]),
        numeric("n07", "What percentage of Engineering respondents agree or strongly agree with the career growth question?",
                [fig("pct", agree(sl(department="Engineering"), "growth"), "pct", 1)], [count_fig("n", sl(department="Engineering"))]),
        numeric("n08", "What percentage of Operations respondents in the South disagreed or strongly disagreed that their workload is manageable in 2026?",
                [fig("pct", disagree(sl("2026", department="Operations", region="South"), "workload"), "pct", 1)],
                [count_fig("n", sl("2026", department="Operations", region="South"))]),
        numeric("n09", "How many responses came from the Sales department in total?", [count_fig("n", sl(department="Sales"))]),
        numeric("n10", "What is the mean wellbeing score in the West region?", [mean_fig("mean", sl(region="West"), "wellbeing")], [count_fig("n", sl(region="West"))]),
        numeric("n11", "What share of Support respondents were NPS detractors in 2025?",
                [fig("pct", 100 * (sl("2025", department="Support").nps <= 6).mean(), "pct", 1)], [count_fig("n", sl("2025", department="Support"))]),
        numeric("n12", "What share of all comments fall into the most common comment theme?",
                [fig("pct", 100 * themes.iloc[0] / themes.sum(), "pct", 1)], [fig("count", themes.iloc[0], "count", 0), fig("comments", themes.sum(), "count", 0)]),
        numeric("n13", "What is the mean recognition score among Directors?", [mean_fig("mean", sl(role="Director"), "recognition")], [count_fig("n", sl(role="Director"))]),
        numeric("n14", "Which department has the lowest mean workload score, and what is that score?",
                [fig("mean", dept_workload.min(), "scale", 2)],
                [fig(k, v, "scale", 2) for k, v in dept_workload.items()] + [count_fig(k, sl(department=k)) for k in dept_workload.index]),
        numeric("n15", "Which region has the highest employee NPS, and what is it?",
                [fig("nps", max(region_nps.values()), "nps", 1)],
                [fig(k, v, "nps", 1) for k, v in region_nps.items()] + [count_fig(k, sl(region=k)) for k in region_nps]),
        compare("c01", "How much lower is the mean workload score in Operations than in Finance?", fin, ops,
                lambda s: s.q_workload.mean(), "scale", "scale_delta", 2, "Finance", "Operations"),
        compare("c02", "By how much did the mean trust-in-leadership score in the North change between 2025 and 2026?", north26, north25,
                lambda s: s.q_leadership.mean(), "scale", "scale_delta", 2, "2026", "2025"),
        compare("c03", "What is the difference in employee NPS between Sales and Support?", sl(department="Sales"), sl(department="Support"),
                nps, "nps", "nps_delta", 1, "Sales", "Support"),
        compare("c04", "How many percentage points did agreement with the recognition question change in Support from Q2 2026 to Q3 2026?", sup3, sup2,
                lambda s: agree(s, "recognition"), "pct", "pp", 1, "Q3", "Q2"),
        compare("c05", "How much did the mean workload score in Operations change between 2025 and 2026?", ops26, ops25,
                lambda s: s.q_workload.mean(), "scale", "scale_delta", 2, "2026", "2025"),
        significance("s01", "Is the difference in mean workload between Operations and Finance statistically significant?", ops, fin, "workload", "Operations", "Finance"),
        significance("s02", "Is the difference in mean satisfaction between the West and East regions statistically significant?",
                     sl(region="West"), sl(region="East"), "satisfaction", "West", "East"),
        significance("s03", "Did mean overall satisfaction change significantly from Q2 2026 to Q3 2026?", q3, q2, "satisfaction", "Q3", "Q2"),
        significance("s04", "Is the change in mean wellbeing in Operations between 2025 and 2026 statistically significant?", ops26, ops25, "wellbeing", "2026", "2025"),
        refusal("t01", "unanswerable", "What is the average salary in the Sales department?"),
        refusal("t02", "unanswerable", "What was the employee turnover rate in 2026?"),
        refusal("t03", "unanswerable", "What was the employee NPS in Q1 2024?"),
        refusal("t04", "unanswerable", "How does the Legal department compare with Finance on satisfaction?"),
        refusal("t05", "unanswerable", "Why did the workload score fall in Operations?"),
        refusal("t06", "unanswerable", "What will the employee NPS be in Q2 2027?"),
        refusal("m01", "tiny_sample", "What is the mean satisfaction among Directors in Finance in Q1 2026?",
                [sl("2026-Q1", department="Finance", role="Director")]),
        refusal("m02", "tiny_sample", "What is the employee NPS among Directors in the East in Q3 2026?",
                [sl("2026-Q3", region="East", role="Director")]),
        refusal("m03", "tiny_sample", "What is the mean workload score for Team leads in Finance in the West in Q2 2026?",
                [sl("2026-Q2", department="Finance", region="West", role="Team lead")]),
        refusal("m04", "tiny_sample", "Compare mean wellbeing between Managers in Finance and Managers in Support in Q3 2026.",
                [sl("2026-Q3", department="Finance", role="Manager"), sl("2026-Q3", department="Support", role="Manager")]),
    ]
    depts = [sl(department=d) for d in dept_workload.index]
    regions = [sl(region=r) for r in region_nps]
    scope = {
        "n01": [DF], "n02": [q3], "n03": [DF], "n04": [q3], "n05": [ops26], "n06": [sl("2026-Q3", region="North")],
        "n07": [sl(department="Engineering")], "n08": [sl("2026", department="Operations", region="South")],
        "n09": [sl(department="Sales"), DF], "n10": [sl(region="West")], "n11": [sl("2025", department="Support")], "n12": [DF],
        "n13": [sl(role="Director")], "n14": [*depts, DF], "n15": [*regions, DF], "c01": [fin, ops], "c02": [north26, north25],
        "c03": [sl(department="Sales"), sl(department="Support")], "c04": [sup3, sup2], "c05": [ops26, ops25],
        "s01": [ops, fin], "s02": [sl(region="West"), sl(region="East")], "s03": [q3, q2], "s04": [ops26, ops25],
    }
    for q in questions:
        q["truth_table"] = truth_table(scope.get(q["id"], []))
    return questions
