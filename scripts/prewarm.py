"""Generates validated interpretations and application summaries for the common filter states and
writes them to data/precomputed.json, so the usual demo path costs nothing and loads at once."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from grounded.env import load_env_file

load_env_file()

from grounded import applications
from grounded.catalog import DATA_DIR, DEPARTMENTS, REGIONS, ROLES, Filters
from grounded.interpret import cache_key, interpret
from grounded.llm import get_llm
from grounded.store import MemoryStore, reset_store

STATES = [Filters()]
STATES += [Filters(period=p) for p in ("2025", "2026", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3")]
STATES += [Filters(region=r) for r in REGIONS] + [Filters(department=d) for d in DEPARTMENTS]
STATES += [Filters(role=r) for r in ROLES if r != "Director"]
STATES += [Filters(period="2026", region=r) for r in REGIONS] + [Filters(period="2026", department=d) for d in DEPARTMENTS]
STATES += [Filters(period="2026", department="Operations", region="South")]


def main() -> None:
    reset_store(MemoryStore())
    llm = get_llm()
    out: dict = {}
    log = {"interpretations": 0, "first_try": 0, "regenerated": 0, "fallback": 0, "issues": []}

    def one(job):
        f, lang = job
        return f, lang, interpret(f, lang, llm=llm, use_budget=False)

    jobs = [(f, lang) for f in STATES for lang in ("en", "de")]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for f, lang, r in pool.map(one, jobs):
            log["interpretations"] += 1
            print(f.canonical(), lang, r.status, r.attempts, flush=True)
            log["issues"] += [i.split(":")[0] for i in r.rejected_issues]
            if r.status == "ok":
                log["first_try" if r.attempts == 1 else "regenerated"] += 1
                d = r.model_dump(mode="json")
                out[cache_key(f, lang, llm.name)] = d
            elif r.status == "fallback":
                log["fallback"] += 1
    for a in applications.load():
        for lang in ("en", "de"):
            s = applications.summarise(a, lang, llm=llm, use_budget=False)
            print(a["id"], lang, s.status, s.attempts, s.rejected_issues[:2], flush=True)
            if s.status == "ok":
                out[applications.cache_key(a["id"], lang, llm.name)] = s.model_dump(mode="json")
    (DATA_DIR / "precomputed.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    (DATA_DIR.parent / "eval" / "prewarm_log.json").write_text(json.dumps(log, indent=1))
    print(log)


if __name__ == "__main__":
    main()
