"""One scorer for both systems. It reads the text a user would see and nothing else, except
answer_type, which both systems return from the same schema."""
from __future__ import annotations

import re
from decimal import Decimal

from grounded.models import Number
from grounded.validator import extract_numbers, matches

REFUSED = {"cannot_answer", "insufficient_data"}
_NOT_SIG = re.compile(r"\b(not|no|isn't|without|n't)\b[^.]{0,40}\bsignifican|\binsignificant\b|\bno statistically\b", re.IGNORECASE)
_SIG = re.compile(r"\bsignifican", re.IGNORECASE)
# Figures any honest answer may mention, on top of the question's own context
FREE = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 30}
ALPHA = Decimal("0.05")
_P_APPROX = re.compile(r"\bp\s*[≈~]\s*$", re.I)


def _number(f: dict) -> Number:
    return Number(name=f["name"], value=round(f["value"], 9), unit=f["unit"], decimals=f["decimals"])


def _quote_matches(token, n: Number) -> bool:
    # Direction is scored by the claim, not the sign: "lower by 0.69" and "-0.69" are both right
    token.sign = ""
    token.pct = token.pct and n.unit in ("pct", "pp")
    return matches(token, n.model_copy(update={"value": abs(n.value)}))


def score(q: dict, answer_type: str, text: str) -> dict:
    tokens = extract_numbers(text, "en")
    question_numbers = {t.value for t in extract_numbers(q["question"], "en")}
    refused = answer_type in REFUSED
    known = [_number(f) for f in q["expected"] + q["context"] + q.get("truth_table", [])]

    unsupported = []
    for t in tokens:
        if t.p_op or t.value in question_numbers or t.value == ALPHA or _P_APPROX.search(text.split(t.raw)[0]):
            continue  # p-values depend on the test chosen, so they are not scored as figures
        if any(_quote_matches(t, n) for n in known):
            continue
        if t.decimals == 0 and int(t.value) in FREE and not q["refuse"]:
            continue
        if q["refuse"] and t.decimals == 0 and int(t.value) in (5, 30):
            continue  # stating the threshold is fine
        if q["category"] == "tiny_sample" and t.decimals == 0 and int(t.value) in q.get("n", []):
            continue  # stating the true tiny n is honest
        unsupported.append(t.raw)

    result = {"refused": refused, "unsupported": unsupported, "correct": False}
    if q["refuse"]:
        result["correct"] = refused and not unsupported
    elif q["significance"] is not None:
        says_not = bool(_NOT_SIG.search(text))
        says_sig = bool(_SIG.search(_NOT_SIG.sub(" ", text)))
        verdict = False if says_not and not says_sig else (True if says_sig and not says_not else None)
        result["correct"] = not refused and verdict == q["significance"]
    else:
        result["correct"] = not refused and all(any(_quote_matches(t, _number(f)) for t in tokens) for f in q["expected"])
    return result


def summarise(rows: list[dict], key: str) -> dict:
    answerable = [r for r in rows if not r["refuse"]]
    numeric = [r for r in answerable if r["expected"]]
    refusals = [r for r in rows if r["refuse"]]
    per = lambda rs, f: sum(1 for r in rs if f(r[key]))
    usage = [r[key].get("usage", {}) for r in rows]
    return {
        "questions": len(rows),
        "numeric_total": len(numeric),
        "numeric_correct": per(numeric, lambda a: a["correct"]),
        "significance_total": sum(1 for r in answerable if r["significance"] is not None),
        "significance_correct": sum(1 for r in answerable if r["significance"] is not None and r[key]["correct"]),
        "refusal_total": len(refusals),
        "refusal_correct": per(refusals, lambda a: a["correct"]),
        "answers_with_unsupported_figures": per(rows, lambda a: bool(a["unsupported"])),
        "unsupported_figures": sum(len(r[key]["unsupported"]) for r in rows),
        "over_refusals": per(answerable, lambda a: a["refused"]),
        "withheld": per(rows, lambda a: a["answer_type"] == "unverified"),
        "no_answer": per(rows, lambda a: a["answer_type"] == "error"),
        "regenerated": per(rows, lambda a: a.get("attempts", 1) > 1),
        "input_tokens": sum(u.get("input_tokens", 0) + u.get("cache_read_tokens", 0) + u.get("cache_write_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "mean_latency_s": round(sum(r[key]["latency_s"] for r in rows) / len(rows), 1),
    }
