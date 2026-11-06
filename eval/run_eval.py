"""Runs every question through the naive baseline and the grounded system, with real model calls.

    .venv/bin/python -m eval.run_eval              # writes eval/results.json
    .venv/bin/python -m eval.run_eval --mock       # plumbing check, writes to a temp file only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from grounded.env import load_env_file

load_env_file()

from grounded import chat
from grounded.catalog import Filters
from grounded.llm import EFFORT, MODEL, AnthropicLLM, LLMResponse, LLMUnavailable
from grounded.llm_mock import MockLLM
from grounded.prompts import PROMPT_VERSION

from .questions import ROOT, build
from .scoring import score, summarise

BASELINE_EFFORT = "medium"
BASELINE_SYSTEM = """You answer questions about an employee survey. The complete raw dataset is below as CSV. Columns: response_id, quarter, submitted_on, region, department, role, six 1-5 agreement questions (q_*, workload means "my workload is manageable"), nps (0-10: promoters 9-10, detractors 0-6, NPS = % promoters - % detractors), theme, comment.

Rules, the same ones the grounded system follows:
- Answer from this data only. Give figures to 2 decimals for means and 1 decimal for percentages and NPS.
- Agree means 4 or 5, disagree means 1 or 2.
- If the data cannot answer the question, use answer_type cannot_answer and give no figures.
- If a slice has fewer than 30 responses, use answer_type insufficient_data and report no figure for it.
- For significance questions use a Welch t-test at alpha 0.05 and say plainly whether it is significant.

Return JSON: answer_type (answer, insufficient_data or cannot_answer) and text (your answer in plain English).

DATA:
"""
BASELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_type": {"type": "string", "enum": ["answer", "insufficient_data", "cannot_answer"]},
        "text": {"type": "string"},
    },
    "required": ["answer_type", "text"], "additionalProperties": False,
}


def raw_csv() -> str:
    df = pd.read_parquet(ROOT / "data" / "responses.parquet")
    comments = pd.read_parquet(ROOT / "data" / "comments.parquet")
    return df.merge(comments, on="response_id", how="left").to_csv(index=False)


def ask_baseline(llm, q: dict, system: str) -> dict:
    t0 = time.monotonic()
    try:
        r: LLMResponse = llm.create(system=system, messages=[{"role": "user", "content": q["question"]}],
                                    schema=BASELINE_SCHEMA, effort=BASELINE_EFFORT, max_tokens=32000, cache_prompt=True)
        out = json.loads(r.text)
        return {"answer_type": out["answer_type"], "text": out["text"], "usage": r.usage,
                "latency_s": round(time.monotonic() - t0, 1)}
    except (LLMUnavailable, ValueError, KeyError) as e:
        return {"answer_type": "error", "text": f"[no answer: {e}]", "usage": {}, "latency_s": round(time.monotonic() - t0, 1)}


def ask_grounded(llm, q: dict) -> dict:
    t0 = time.monotonic()
    r = chat.run(q["question"], Filters(), "en", [], llm)
    text = " ".join(c.text for c in r.claims) + (" " + r.message if r.message else "")
    return {
        "answer_type": r.answer_type, "text": text.strip(), "usage": r.usage, "attempts": r.attempts,
        "rejected_issues": r.rejected_issues, "latency_s": round(time.monotonic() - t0, 1),
        "tool_calls": [c["tool"] for c in r.tool_calls],
        "citations": sum(len(c.cites) for c in r.claims),
        "validator_numbers": r.validation.numbers_checked if r.validation else 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--only", help="comma-separated question ids")
    args = ap.parse_args()
    if args.mock:
        grounded_llm = baseline_llm = MockLLM()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set")
        grounded_llm, baseline_llm = AnthropicLLM(timeout=200), AnthropicLLM(timeout=600)

    questions = build()
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    system = BASELINE_SYSTEM + raw_csv()

    def baseline(q):
        if args.mock:
            return {"answer_type": "answer", "text": "mock", "usage": {}, "latency_s": 0}
        return ask_baseline(baseline_llm, q, system)

    # One call first, so the data block is in the prompt cache before the rest run in parallel
    rows = []
    first = baseline(questions[0])
    with ThreadPoolExecutor(max_workers=1 if args.mock else 5) as pool:
        base = [first] + list(pool.map(baseline, questions[1:]))
        ground = list(pool.map(lambda q: ask_grounded(grounded_llm, q), questions))
    for q, b, g in zip(questions, base, ground):
        rows.append({**q, "baseline": {**b, **score(q, b["answer_type"], b["text"])},
                     "grounded": {**g, **score(q, g["answer_type"], g["text"])}})
        print(q["id"], "base", rows[-1]["baseline"]["correct"], rows[-1]["baseline"]["unsupported"],
              "| grounded", rows[-1]["grounded"]["correct"], rows[-1]["grounded"]["unsupported"], flush=True)

    result = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "mode": "mock" if args.mock else "real",
        "model": MODEL, "prompt_version": PROMPT_VERSION,
        "effort": {"baseline": BASELINE_EFFORT, "grounded": EFFORT},
        "baseline_prompt_chars": len(system),
        "summary": {"baseline": summarise(rows, "baseline"), "grounded": summarise(rows, "grounded")},
        "questions": rows,
    }
    path = Path(tempfile.gettempdir()) / "grounded-eval-mock.json" if args.mock or args.only else ROOT / "eval" / "results.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    print(json.dumps(result["summary"], indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
