"""Stats are checked against pandas and scipy on the raw rows, an independent path from the SQL."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from grounded import data
from grounded.catalog import DATA_DIR, MIN_N_INTERPRET, QUARTERS, Filters, comparison_windows
from grounded.sheet import build_sheet
from grounded.stats import (
    Moments,
    NpsCounts,
    anova,
    benjamini_hochberg,
    chi2_distribution,
    nps_z,
    round_half_up,
    welch_t,
)

DF = pd.read_parquet(DATA_DIR / "responses.parquet")


def m(x) -> Moments:
    return Moments(len(x), float(np.mean(x)), float(np.var(x, ddof=1)))


def test_dataset_shape():
    assert 2900 <= len(DF) <= 3100
    assert sorted(DF.quarter.unique()) == QUARTERS
    assert "comment" not in DF.columns, "raw free text must not be in the deployed file"
    assert DF[[c for c in DF if c.startswith("q_")]].stack().between(1, 5).all()
    assert DF.nps.between(0, 10).all()


@pytest.mark.parametrize("q", ["satisfaction", "workload", "leadership", "growth", "recognition", "wellbeing"])
@pytest.mark.parametrize("f", [Filters(), Filters(region="North"), Filters(period="2026", department="Operations"),
                               Filters(period="2025-Q4", role="Manager", region="South")])
def test_moments_match_pandas(q, f):
    s = DF[DF.quarter.isin(f.quarters())]
    for dim in ("region", "department", "role"):
        if getattr(f, dim) != "all":
            s = s[s[dim] == getattr(f, dim)]
    got = data.moments(f, q)
    assert got.n == len(s)
    assert got.mean == pytest.approx(s[f"q_{q}"].mean())
    assert got.var == pytest.approx(s[f"q_{q}"].var(ddof=1))
    assert data.distribution(f, q) == [int((s[f"q_{q}"] == i).sum()) for i in range(1, 6)]


def test_nps_matches_pandas():
    s = DF[DF.region == "West"]
    c = data.nps(Filters(region="West"))
    expected = 100 * ((s.nps >= 9).mean() - (s.nps <= 6).mean())
    assert c.score == pytest.approx(expected)
    assert c.n == len(s)


def test_welch_matches_scipy_on_raw_data():
    a = DF[DF.department == "Operations"].q_workload.to_numpy()
    b = DF[DF.department == "Finance"].q_workload.to_numpy()
    expected = sps.ttest_ind(a, b, equal_var=False)
    got = welch_t(m(a), m(b))
    assert got.statistic == pytest.approx(expected.statistic)
    assert got.p == pytest.approx(expected.pvalue)


def test_anova_matches_scipy_on_raw_data():
    groups = [g.q_recognition.to_numpy() for _, g in DF.groupby("department")]
    expected = sps.f_oneway(*groups)
    got = anova([m(g) for g in groups])
    assert got.statistic == pytest.approx(expected.statistic)
    assert got.p == pytest.approx(expected.pvalue)


def test_chi2_matches_scipy():
    a, b = [10, 20, 30, 25, 15], [15, 25, 25, 20, 15]
    expected = sps.chi2_contingency(np.array([a, b]), correction=False)
    got = chi2_distribution(a, b)
    assert got.statistic == pytest.approx(expected.statistic)
    assert got.p == pytest.approx(expected.pvalue)


def test_chi2_drops_empty_columns():
    assert chi2_distribution([10, 0, 5], [12, 0, 6]) is not None
    assert chi2_distribution([0, 0], [1, 2]) is None


def test_nps_variance_equals_coded_sample_variance():
    c = NpsCounts(30, 50, 20)
    coded = np.array([100] * 30 + [0] * 50 + [-100] * 20)
    assert c.score == pytest.approx(coded.mean())
    assert c.variance == pytest.approx(coded.var(ddof=0))


def test_nps_z_test():
    a, b = NpsCounts(120, 200, 80), NpsCounts(80, 200, 120)
    r = nps_z(a, b)
    se = math.sqrt(a.variance / a.n + b.variance / b.n)
    assert r.statistic == pytest.approx((a.score - b.score) / se)
    assert r.p < 0.001
    assert nps_z(NpsCounts(1, 0, 0), NpsCounts(0, 0, 0)) is None


def test_benjamini_hochberg_reference_values():
    # Worked example, checked against scipy.stats.false_discovery_control
    p = [0.01, 0.04, 0.03, 0.2, 0.5]
    assert benjamini_hochberg(p) == pytest.approx(list(sps.false_discovery_control(p, method="bh")))
    assert benjamini_hochberg([]) == []


@pytest.mark.parametrize("x,d,expected", [
    (3.845, 2, 3.85), (3.844999, 2, 3.84), (2.5, 0, 3), (3.5, 0, 4), (-0.125, 2, -0.13), (0.1 + 0.2, 1, 0.3), (1.005, 2, 1.01),
])
def test_round_half_up(x, d, expected):
    assert round_half_up(x, d) == expected


def test_round_never_returns_negative_zero():
    assert math.copysign(1, round_half_up(-0.001, 2)) == 1


def test_previous_period_windows():
    assert comparison_windows(Filters(period="2026-Q1"))[:2] == (["2026-Q1"], ["2025-Q4"])
    assert comparison_windows(Filters(period="2026"))[:2] == (["2026-Q1", "2026-Q2", "2026-Q3"], ["2025-Q2", "2025-Q3", "2025-Q4"])
    assert comparison_windows(Filters(period="2025-Q2")) is None
    assert comparison_windows(Filters(period="2025")) is None
    assert comparison_windows(Filters())[:2] == (["2026-Q3"], ["2026-Q2"])


def test_sheet_delta_equals_difference_and_is_adjusted():
    sheet = build_sheet(Filters(period="2026", department="Operations"))
    d = next(s for s in sheet.stats if s.key == "delta.workload")
    rel = {r.name: r.value for r in d.related}
    s = DF[DF.department == "Operations"]
    cur = s[s.quarter.str.startswith("2026")].q_workload
    prev = s[s.quarter.str.startswith("2025")].q_workload
    assert d.value == round_half_up(cur.mean() - prev.mean(), 2)
    assert rel["n_current"] == len(cur) and rel["n_previous"] == len(prev)
    raw_p = sps.ttest_ind(cur, prev, equal_var=False).pvalue
    assert rel["p_adjusted"] >= round_half_up(raw_p, 3)
    assert d.direction == "down" and d.significant is True, "the planted Operations workload slide must be found"


def test_sheet_noise_is_not_called_significant():
    sheet = build_sheet(Filters(period="2026-Q2"))
    # With the seeded data, Q2 2026 vs Q1 2026 has no real overall change planted
    assert [s.key for s in sheet.stats if s.kind == "delta" and s.significant] == []


def test_sheet_flags_small_sample_and_excludes_tiny_segments():
    sheet = build_sheet(Filters(period="2026-Q1", department="Finance"))
    assert sheet.n >= MIN_N_INTERPRET
    codes = [w.code for w in sheet.warnings]
    assert "small_sample" in codes and "segments_excluded" in codes
    assert not any(s.key.startswith("gap.role") and "Director" in s.entities for s in sheet.stats)


def test_sheet_below_threshold_has_no_figures():
    sheet = build_sheet(Filters(period="2026-Q1", department="Finance", role="Director"))
    assert sheet.insufficient and sheet.stats == []
    assert "Fewer than 5" in sheet.warnings[0].text and sheet.n is None
