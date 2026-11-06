"""The eval set. Answers are computed here with pandas on the raw parquet, an independent path
from the DuckDB code the app uses. No expected value is typed by hand."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats as sps

ROOT = Path(__file__).resolve().parent.parent
DF = pd.read_parquet(ROOT / "data" / "responses.parquet")
MIN_N = 30


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


def build() -> list[dict]:
    ops26, ops25 = sl("2026", department="Operations"), sl("2025", department="Operations")
    fin, ops = sl(department="Finance"), sl(department="Operations")
    north26, north25 = sl("2026", region="North"), sl("2025", region="North")
    dept_workload = DF.groupby("department").q_workload.mean()
    lowest_dept = dept_workload.idxmin()
    region_nps = {r: nps(sl(region=r)) for r in DF.region.unique()}
    best_region = max(region_nps, key=region_nps.get)
    themes = DF.theme.value_counts()
    top_theme = themes.index[0]
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
    for q in questions:
        q["note"] = {"lowest_dept": lowest_dept, "best_region": best_region, "top_theme": top_theme}.get(q["id"], "")
    return questions
