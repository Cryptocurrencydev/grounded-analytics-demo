"""Filter state -> stats -> model -> validator -> cached result."""
from __future__ import annotations

import hashlib
import json
import logging
import time

from pydantic import BaseModel, Field

from .catalog import Filters
from .data import dataset_version
from .llm import LLM, LLMUnavailable, get_llm
from .models import Claim, Stat, ValidationReport
from .precomputed import lookup
from .prompts import INTERPRET_SCHEMA, INTERPRET_SYSTEM, PROMPT_VERSION, feedback, lang_line
from .sheet import StatSheet, build_sheet, scope_entities
from .store import allow_llm_call, get_store
from .validator import validate

log = logging.getLogger("grounded.interpret")
CACHE_TTL = 30 * 86_400


class Finding(BaseModel):
    title: str
    text: str
    cites: list[str]


class Interpretation(BaseModel):
    status: str  # ok | insufficient | fallback | rate_limited
    lang: str
    scope: str
    n: int | None
    summary: list[Claim] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stats: list[Stat] = Field(default_factory=list)
    validation: ValidationReport | None = None
    attempts: int = 0
    rejected_issues: list[str] = Field(default_factory=list)
    model: str | None = None
    cached: bool = False
    sent_to_model: dict | None = None
    usage: dict = Field(default_factory=dict)
    latency_ms: int = 0


def cache_key(f: Filters, lang: str, llm_name: str) -> str:
    raw = "|".join([f.canonical(), lang, llm_name, PROMPT_VERSION, dataset_version()])
    return "interp:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _claims(out: dict) -> list[Claim]:
    claims = [Claim(text=c["text"], cites=c["cites"]) for c in out.get("summary", [])]
    claims += [Claim(text=f"{x['title']}. {x['text']}", cites=x["cites"]) for x in out.get("findings", [])]
    return claims


def _fmt(value: float, decimals: int, lang: str) -> str:
    s = f"{value:,.{decimals}f}"
    return s.translate(str.maketrans(",.", ".,")) if lang == "de" else s


def fallback_claims(sheet: StatSheet, lang: str) -> list[Claim]:
    """Safe text from a template. Every figure is copied from the sheet, nothing is written by a model."""
    by_key = {s.key: s for s in sheet.stats}
    sat, nps, n = by_key["mean.satisfaction"], by_key["nps"], by_key["n"]
    if lang == "de":
        text = (f"{_fmt(n.value, 0, lang)} Antworten im aktuellen Filter. Gesamtzufriedenheit im Mittel "
                f"{_fmt(sat.value, 2, lang)}, Mitarbeiter-NPS {_fmt(nps.value, 1, lang)}.")
    else:
        text = (f"{_fmt(n.value, 0, lang)} responses in the current filter. Overall satisfaction averages "
                f"{_fmt(sat.value, 2, lang)}, employee NPS is {_fmt(nps.value, 1, lang)}.")
    return [Claim(text=text, cites=[n.id, sat.id, nps.id])]


def _base(sheet: StatSheet, lang: str, status: str) -> Interpretation:
    return Interpretation(status=status, lang=lang, scope=sheet.scope, n=sheet.n,
                          warnings=[w.text for w in sheet.warnings], stats=sheet.stats)


def _fallback(sheet: StatSheet, lang: str, status: str, rejected: list[str] | None = None, attempts: int = 0) -> Interpretation:
    r = _base(sheet, lang, status)
    r.summary = fallback_claims(sheet, lang)
    r.validation = validate(r.summary, sheet.by_id(), lang)
    r.rejected_issues, r.attempts = rejected or [], attempts
    return r


def interpret(f: Filters, lang: str, client_id: str = "local", llm: LLM | None = None, use_budget: bool = True) -> Interpretation:
    started = time.monotonic()
    sheet = build_sheet(f, lang)
    if sheet.insufficient:
        return _base(sheet, lang, "insufficient")  # no model call at all

    llm = llm or get_llm()
    key = cache_key(f, lang, llm.name)
    store = get_store()
    hit = store.get(key) or lookup(key)
    if hit:
        return Interpretation(**{**hit, "cached": True})

    if use_budget and not allow_llm_call(client_id):
        return _fallback(sheet, lang, "rate_limited")

    result = generate(sheet, f, lang, llm)
    result.latency_ms = int((time.monotonic() - started) * 1000)
    if result.status == "ok":
        store.set(key, result.model_dump(), CACHE_TTL)
    return result


def generate(sheet: StatSheet, f: Filters, lang: str, llm: LLM) -> Interpretation:
    payload = sheet.for_llm()
    user = f"{lang_line(lang)}\n\n{json.dumps(payload, ensure_ascii=False)}"
    messages: list[dict] = [{"role": "user", "content": user}]
    rejected: list[str] = []
    stats = sheet.by_id()
    usage: dict = {}
    attempt = 0
    for attempt in (1, 2):
        try:
            response = llm.create(system=INTERPRET_SYSTEM, messages=messages, schema=INTERPRET_SCHEMA)
        except LLMUnavailable as e:
            log.warning("model unavailable: %s", e)
            rejected.append(f"model_unavailable: {e}")
            break
        for k, v in response.usage.items():
            usage[k] = usage.get(k, 0) + v
        try:
            if response.stop_reason not in ("end_turn", "stop_sequence"):
                raise ValueError(f"stop_reason {response.stop_reason}")
            out = json.loads(response.text)
            claims = _claims(out)
            if not out.get("summary") or not out.get("findings"):
                raise ValueError("empty output")
        except (ValueError, KeyError, TypeError) as e:
            rejected.append(f"unusable_output: {e}")
            messages = [{"role": "user", "content": user + "\n\nReturn valid JSON for the schema."}]
            continue
        report = validate(claims, stats, lang, scope_entities(f))
        if report.ok:
            r = _base(sheet, lang, "ok")
            r.summary = [Claim(**c) for c in out["summary"]]
            r.findings = [Finding(**x) for x in out["findings"]]
            r.validation, r.attempts, r.rejected_issues = report, attempt, rejected
            r.model, r.sent_to_model, r.usage = llm.name, payload, usage
            return r
        rejected += [f"{i.code}: {i.detail}" for i in report.issues]
        # A fresh request carrying the feedback: nothing rejected is replayed as if it were true
        messages = [{"role": "user", "content": f"{user}\n\n{feedback(report.issues)}"}]
    r = _fallback(sheet, lang, "fallback", rejected, attempt)
    r.model, r.sent_to_model, r.usage = llm.name, payload, usage
    return r
