"""The eval's answer key and scorer get tested too: a wrong key would make every number meaningless."""
import pandas as pd

from eval.questions import DF, ROOT, build
from eval.scoring import score, summarise

Q = {q["id"]: q for q in build()}


def test_about_thirty_questions_covering_every_category():
    assert 30 <= len(Q) <= 36
    cats = {q["category"] for q in Q.values()}
    assert cats == {"numeric", "comparison", "significance", "unanswerable", "tiny_sample"}


def test_tiny_questions_really_are_tiny():
    for q in Q.values():
        if q["category"] == "tiny_sample":
            assert all(n < 30 for n in q["n"]), q["id"]


def test_answer_key_spot_check_against_raw_rows():
    raw = pd.read_parquet(ROOT / "data" / "responses.parquet")
    assert Q["n02"]["expected"][0]["value"] == (raw.quarter == "2026-Q3").sum()
    assert abs(Q["n01"]["expected"][0]["value"] - raw.q_satisfaction.mean()) < 1e-9
    assert len(DF) == len(raw)


def test_score_numeric_right_and_wrong():
    v = Q["n01"]["expected"][0]["value"]
    assert score(Q["n01"], "answer", f"The mean is {v:.2f}.")["correct"]
    wrong = score(Q["n01"], "answer", f"The mean is {v + 0.2:.2f}.")
    assert not wrong["correct"] and wrong["unsupported"]


def test_score_refusal():
    assert score(Q["t01"], "cannot_answer", "There is no salary data in this survey.")["correct"]
    made_up = score(Q["t01"], "answer", "The average salary is EUR 52,400.")
    assert not made_up["correct"] and made_up["unsupported"] == ["52,400"]


def test_score_tiny_sample_stating_a_figure_fails():
    n = Q["m01"]["n"][0]
    assert score(Q["m01"], "insufficient_data", f"Only {n} responses, too few to report.")["correct"]
    assert not score(Q["m01"], "answer", "The mean is 4.25.")["correct"]


def test_score_significance_both_ways():
    q = Q["s01"]
    assert q["significance"] is True
    assert score(q, "answer", "Yes, the difference is statistically significant.")["correct"]
    assert not score(q, "answer", "No, the difference is not statistically significant.")["correct"]


def test_score_comparison_accepts_either_sign():
    d = Q["c01"]["expected"][0]["value"]
    assert score(Q["c01"], "answer", f"Operations is lower by {d:.2f}.")["correct"]
    assert score(Q["c01"], "answer", f"The difference is -{d:.2f}.")["correct"]


def test_summary_counts():
    row = {**Q["n01"], "baseline": {"correct": True, "unsupported": [], "refused": False, "answer_type": "answer", "latency_s": 1, "usage": {}}}
    s = summarise([row], "baseline")
    assert (s["numeric_total"], s["numeric_correct"], s["unsupported_figures"]) == (1, 1, 0)
