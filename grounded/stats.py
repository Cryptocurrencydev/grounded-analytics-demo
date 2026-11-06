"""Statistics on aggregated moments. Nothing here needs a raw row."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy import stats as sps


def round_half_up(x: float, digits: int = 0) -> float:
    """Commercial rounding, the rule charts, stats and validator all share."""
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(round(float(x), 9))).quantize(q, rounding=ROUND_HALF_UP)) + 0.0  # no -0.0


@dataclass(frozen=True)
class Moments:
    n: int
    mean: float
    var: float  # sample variance, ddof=1


def ci95(m: Moments) -> tuple[float, float] | None:
    if m.n < 2:
        return None
    half = float(sps.t.ppf(0.975, m.n - 1)) * math.sqrt(m.var / m.n)
    return m.mean - half, m.mean + half


@dataclass(frozen=True)
class TestResult:
    test: str
    statistic: float
    p: float
    effect: float | None = None


def welch_t(a: Moments, b: Moments) -> TestResult | None:
    """Welch's t-test from summary statistics, with Cohen's d (pooled SD) as effect size."""
    if a.n < 2 or b.n < 2 or (a.var == 0 and b.var == 0):
        return None
    t, p = sps.ttest_ind_from_stats(
        a.mean, math.sqrt(a.var), a.n, b.mean, math.sqrt(b.var), b.n, equal_var=False
    )
    pooled = math.sqrt(((a.n - 1) * a.var + (b.n - 1) * b.var) / (a.n + b.n - 2))
    return TestResult("welch_t", float(t), float(p), (a.mean - b.mean) / pooled if pooled else None)


def anova(groups: list[Moments]) -> TestResult | None:
    """One-way ANOVA from group moments, with eta squared as effect size."""
    groups = [g for g in groups if g.n >= 2]
    k = len(groups)
    total = sum(g.n for g in groups)
    if k < 2 or total <= k:
        return None
    grand = sum(g.n * g.mean for g in groups) / total
    ss_between = sum(g.n * (g.mean - grand) ** 2 for g in groups)
    ss_within = sum((g.n - 1) * g.var for g in groups)
    if ss_within == 0:
        return None
    f = (ss_between / (k - 1)) / (ss_within / (total - k))
    return TestResult("anova_f", f, float(sps.f.sf(f, k - 1, total - k)), ss_between / (ss_between + ss_within))


def chi2_distribution(a: list[int], b: list[int]) -> TestResult | None:
    """Chi-square test of homogeneity on two count vectors, empty columns dropped."""
    table = np.array([a, b])
    table = table[:, table.sum(axis=0) > 0]
    if table.shape[1] < 2 or (table.sum(axis=1) == 0).any():
        return None
    r = sps.chi2_contingency(table, correction=False)
    n = table.sum()
    v = math.sqrt(r.statistic / (n * (min(table.shape) - 1)))
    return TestResult("chi2", float(r.statistic), float(r.pvalue), v)


@dataclass(frozen=True)
class NpsCounts:
    promoters: int
    passives: int
    detractors: int

    @property
    def n(self) -> int:
        return self.promoters + self.passives + self.detractors

    @property
    def score(self) -> float:
        return 100 * (self.promoters - self.detractors) / self.n if self.n else float("nan")

    @property
    def variance(self) -> float:
        """Variance of one response coded +100 / 0 / -100."""
        if not self.n:
            return float("nan")
        p, d = self.promoters / self.n, self.detractors / self.n
        return 10_000 * (p + d - (p - d) ** 2)


def nps_z(a: NpsCounts, b: NpsCounts) -> TestResult | None:
    """Two-sample z-test on the difference between two NPS scores."""
    if a.n < 2 or b.n < 2:
        return None
    se = math.sqrt(a.variance / a.n + b.variance / b.n)
    if se == 0:
        return None
    z = (a.score - b.score) / se
    return TestResult("nps_z", z, float(2 * sps.norm.sf(abs(z))))


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """False-discovery-rate adjusted p-values, in input order."""
    m = len(pvalues)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        adjusted[i] = running
    return adjusted
