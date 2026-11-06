import pytest

from grounded.catalog import Filters
from grounded.interpret import fallback_claims
from grounded.models import ChartRef, Claim, Number, Stat
from grounded.sheet import build_sheet
from grounded.validator import extract_numbers, validate


def stat(id="S01", value=3.85, unit="scale", decimals=2, n=812, **kw):
    return Stat(id=id, key=id, kind=kw.pop("kind", "mean"), label="x", value=value, unit=unit, decimals=decimals, n=n, **kw)


MEAN = stat(entities=["q:satisfaction"])
PCT = stat("S02", 62.4, "pct", 1, kind="top2")
DOWN = stat("S03", -0.14, "scale_delta", 2, 900, kind="delta", direction="down", significant=True,
            entities=["q:workload", "Operations"],
            related=[Number(name="p_adjusted", value=0.032, unit="p", decimals=3),
                     Number(name="current", value=3.21, unit="scale", decimals=2)])
UP_NS = stat("S04", 0.05, "scale_delta", 2, 900, kind="delta", direction="up", significant=False, entities=["q:growth"],
             related=[Number(name="p_adjusted", value=0.514, unit="p", decimals=3)])
TINY_P = stat("S05", 0.69, "scale_delta", 2, 900, kind="segment_gap", significant=True,
              related=[Number(name="p_adjusted", value=0.0, unit="p", decimals=3)])
NPS = stat("S06", -23.9, "nps", 1, 3000, kind="nps")
COUNT = stat("S07", 1234, "count", 0, 1234, kind="count")
STATS = {s.id: s for s in (MEAN, PCT, DOWN, UP_NS, TINY_P, NPS, COUNT)}


def codes(text, cites, lang="en", scope=None):
    return [i.code for i in validate([Claim(text=text, cites=cites)], STATS, lang, scope).issues]


@pytest.mark.parametrize("text,cites", [
    ("Satisfaction averages 3.85.", ["S01"]),
    ("Satisfaction averages about 3.9.", ["S01"]),          # coarsened, round half up
    ("Agreement stands at 62.4%.", ["S02"]),
    ("Agreement stands at 62 %.", ["S02"]),
    ("Agreement stands at 62 percent.", ["S02"]),
    ("Manageable workload fell by 0.14 to 3.21 and the drop is significant (p = 0.032).", ["S03"]),
    ("Manageable workload fell by 0.1.", ["S03"]),
    ("Workload changed by -0.14.", ["S03"]),
    ("The gap is significant (p < 0.001).", ["S05"]),
    ("The change is not statistically significant.", ["S04"]),
    ("Based on 812 responses, the mean is 3.85.", ["S01"]),
    ("The NPS is -23.9.", ["S06"]),
    ("The NPS is −23.9.", ["S06"]),
    ("We received 1,234 responses.", ["S07"]),
    ("In Q3 2026 satisfaction averages 3.85.", ["S01"]),
    ("In 2025-Q4 and 2026 satisfaction averages 3.85.", ["S01"]),
])
def test_accepts(text, cites):
    assert codes(text, cites) == []


@pytest.mark.parametrize("text,cites,lang", [
    ("Die Zufriedenheit liegt bei 3,85.", ["S01"], "de"),
    ("Die Zustimmung liegt bei 62,4 %.", ["S02"], "de"),
    ("Es gingen 1.234 Antworten ein.", ["S07"], "de"),
    ("Im 3. Quartal 2026 liegt die Zufriedenheit bei 3,9.", ["S01"], "de"),
    ("Die Veränderung ist nicht signifikant.", ["S04"], "de"),
    ("Die bewältigbare Arbeitsbelastung ist gesunken, p = 0,032.", ["S03"], "de"),
])
def test_accepts_german(text, cites, lang):
    assert codes(text, cites, lang) == []


@pytest.mark.parametrize("text,cites,code", [
    ("Satisfaction averages 3.95.", ["S01"], "number_not_found"),                   # made up
    ("Satisfaction averages 3.8.", ["S01"], "number_not_found"),                    # 3.85 rounds to 3.9, not 3.8
    ("Satisfaction averages 3.851.", ["S01"], "number_not_found"),                  # false precision
    ("Satisfaction averages 4.", ["S01"], "number_not_found"),                      # too coarse for a mean
    ("Agreement stands at 3.85%.", ["S01"], "number_not_found"),                    # right digits, wrong unit
    ("Workload changed by +0.14.", ["S03"], "number_not_found"),                    # wrong sign
    ("We received about 1,200 responses.", ["S07"], "number_not_found"),            # counts stay exact
    ("Agreement stands at 62.4%.", ["S01"], "number_not_in_cited_stat"),            # true, but cites the wrong stat
    ("The p-value is p = 0.04.", ["S03"], "number_not_found"),
    ("The gap holds at p < 0.0001.", ["S03"], "number_not_found"),                  # the bound is false for 0.032
])
def test_catches_wrong_numbers(text, cites, code):
    assert code in codes(text, cites)


@pytest.mark.parametrize("text,code", [
    ("Everything looks healthy.", "missing_citation"),
    ("Satisfaction averages 3.85.", "missing_citation"),
])
def test_catches_missing_citations(text, code):
    assert code in codes(text, [])


def test_catches_unknown_citation():
    assert codes("Satisfaction averages 3.85.", ["S99"])[0] == "unknown_citation"


@pytest.mark.parametrize("text,cites,code,lang", [
    ("Manageable workload rose by 0.14.", ["S03"], "direction_mismatch", "en"),
    ("Workload fell by 0.14.", ["S03"], "ambiguous_polarity", "en"),
    ("Die Arbeitsbelastung ist gesunken.", ["S03"], "ambiguous_polarity", "de"),
    ("Growth fell by 0.05.", ["S04"], "direction_mismatch", "en"),
    ("Die bewältigbare Arbeitsbelastung ist gestiegen.", ["S03"], "direction_mismatch", "de"),
    ("Growth improved significantly.", ["S04"], "unsupported_significance", "en"),
    ("The change is not significant.", ["S03"], "unsupported_significance", "en"),
    ("Satisfaction is significantly high at 3.85.", ["S01"], "unsupported_significance", "en"),
    ("About half of staff agree.", ["S02"], "spelled_number", "en"),
    ("Workload doubled.", ["S03"], "spelled_number", "en"),
    ("Etwa zwei Drittel stimmen zu.", ["S02"], "spelled_number", "de"),
    ("Satisfaction in Q1 2024 was 3.85.", ["S01"], "unknown_period", "en"),
    ("Satisfaction in Q4 2026 was 3.85.", ["S01"], "unknown_period", "en"),
    ("In the North, satisfaction averages 3.85.", ["S01"], "entity_not_in_cited_stat", "en"),
    ("Recognition averages 3.85.", ["S01"], "entity_not_in_cited_stat", "en"),
    ("Workload fell because of staffing.", ["S03"], "causal_language", "en"),
    ("Workload fell, driven by overtime.", ["S03"], "causal_language", "en"),
    ("Die Belastung sank aufgrund der Personallage.", ["S03"], "causal_language", "de"),
])
def test_catches_claim_level_errors(text, cites, code, lang):
    assert code in codes(text, cites, lang)


@pytest.mark.parametrize("text,lang", [("Die Zufriedenheit liegt bei 3.85.", "de"), ("Satisfaction averages 3,85.", "en")])
def test_catches_wrong_locale_format(text, lang):
    assert "wrong_number_format" in codes(text, ["S01"], lang)


def test_active_filter_counts_as_covered():
    assert codes("In the North, satisfaction averages 3.85.", ["S01"], scope=["North"]) == []


@pytest.mark.parametrize("text", ["Satisfaction is 3.85 on the 1-5 scale.", "Satisfaction is 3.85 on the 1–5 scale.", "Satisfaction is 3.85 on a scale of 1 to 5."])
def test_the_survey_scale_is_not_a_figure(text):
    assert codes(text, ["S01"]) == []


@pytest.mark.parametrize("text,lang", [("Across all 6 quarters satisfaction is 3.85.", "en"), ("Über alle 6 Quartale liegt die Zufriedenheit bei 3,85.", "de")])
def test_the_scope_label_is_not_a_figure(text, lang):
    assert codes(text, ["S01"], lang) == []


def test_other_quarter_counts_are_still_checked():
    assert "number_not_found" in codes("Across all 7 quarters satisfaction is 3.85.", ["S01"])


def test_scale_mask_does_not_hide_a_real_range():
    assert "number_not_found" in codes("Satisfaction moved 1-5.5 points.", ["S01"])


def test_tally_stat_supports_significance_wording():
    tally = stat("S09", 0, "count", 0, 3000, kind="count")
    tally.key = "delta.significant_changes"
    r = validate([Claim(text="No measure changed significantly, 0 in total.", cites=["S09"])], {"S09": tally}, "en")
    assert r.ok, r.issues


def test_support_as_a_verb_is_not_the_department():
    assert codes("These figures support a mean of 3.85.", ["S01"]) == []


def test_stat_ids_and_ranges_do_not_become_numbers():
    assert [t.value for t in extract_numbers("See S12 and Q3", "en")] == []
    assert [str(t.value) for t in extract_numbers("3.21-3.85", "en")] == ["3.21", "3.85"]


def test_counts_numbers_for_the_report():
    r = validate([Claim(text="Manageable workload fell by 0.14 to 3.21.", cites=["S03"])], STATS, "en")
    assert (r.ok, r.claims_checked, r.numbers_checked, r.numbers_matched) == (True, 1, 2, 2)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_safe_fallback_itself_passes_the_validator(lang):
    sheet = build_sheet(Filters(region="South"), lang)
    assert validate(fallback_claims(sheet, lang), sheet.by_id(), lang).ok


def test_every_mutated_number_is_caught():
    """Take a passing text and nudge each figure: the validator must reject every variant."""
    sheet = build_sheet(Filters())
    s = next(x for x in sheet.stats if x.key == "mean.workload")
    t = next(x for x in sheet.stats if x.key == "top2.workload")
    text = f"Workload averages {s.value:.2f} and {t.value:.1f}% agree."
    cites = [s.id, t.id]
    assert validate([Claim(text=text, cites=cites)], sheet.by_id(), "en").ok
    for mutated in (
        text.replace(f"{s.value:.2f}", f"{s.value + 0.01:.2f}"),
        text.replace(f"{s.value:.2f}", f"{s.value - 0.1:.2f}"),
        text.replace(f"{t.value:.1f}", f"{t.value + 0.1:.1f}"),
        text.replace(f"{t.value:.1f}", f"{t.value + 5:.1f}"),
    ):
        assert not validate([Claim(text=mutated, cites=cites)], sheet.by_id(), "en").ok, mutated


def test_chart_ref_is_not_sent_to_the_model():
    s = stat(chart=ChartRef(chart="trend", series="workload"), entities=["q:workload"])
    assert "chart" not in s.for_llm() and "entities" not in s.for_llm()
