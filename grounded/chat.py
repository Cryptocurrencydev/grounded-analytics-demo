"""Tool-only conversational analytics. Answers pass the same validator as the interpretation panel."""
from __future__ import annotations

import hashlib
import json
import logging

from pydantic import BaseModel, Field

from .catalog import Filters
from .data import dataset_version
from .llm import LLM, LLMUnavailable, get_llm
from .models import Claim, Issue, Stat, ValidationReport
from .prompts import CHAT_SCHEMA, CHAT_SYSTEM, PROMPT_VERSION, feedback, lang_line
from .sheet import scope_entities
from .store import allow_llm_call, get_store
from .tools import TOOLS, Ledger, execute
from .validator import extract_numbers, validate

log = logging.getLogger("grounded.chat")
MAX_ROUNDS = 6


class Turn(BaseModel):
    role: str
    text: str


class ChatResult(BaseModel):
    answer_type: str  # answer | filters_applied | insufficient_data | cannot_answer | unverified | rate_limited | error
    claims: list[Claim] = Field(default_factory=list)
    message: str = ""
    stats: list[Stat] = Field(default_factory=list)
    applied_filters: Filters | None = None
    validation: ValidationReport | None = None
    attempts: int = 0
    rejected_issues: list[str] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    cached: bool = False


UNVERIFIED = {
    "en": "I could not verify an answer against the data, so I am not showing one. The figures the tools returned are listed below.",
    "de": "Ich konnte keine Antwort gegen die Daten verifizieren und zeige deshalb keine an. Die von den Tools gelieferten Werte stehen unten.",
}
UNAVAILABLE = {
    "en": "The AI service is not available right now. The dashboard and its figures still work.",
    "de": "Der KI-Dienst ist gerade nicht verfügbar. Das Dashboard und seine Werte funktionieren weiterhin.",
}
LIMITED = {
    "en": "This public demo has reached its usage limit for now. Please try again later.",
    "de": "Diese öffentliche Demo hat ihr Nutzungslimit erreicht. Bitte versuchen Sie es später erneut.",
}


def check_answer(out: dict, ledger: Ledger, lang: str, filters: Filters) -> ValidationReport:
    claims = [Claim(**c) for c in out["claims"]]
    active = ledger.applied or filters
    report = validate(claims, ledger.stats, lang, scope_entities(active))
    kind = out["answer_type"]
    extra = []
    if kind == "answer" and not claims:
        extra.append(("missing_citation", "An answer needs at least one cited claim"))
    if kind in ("cannot_answer", "filters_applied"):
        for t in extract_numbers(out.get("message", ""), lang):
            extra.append(("number_in_uncited_text", f"{t.raw} appears in text with no citation"))
    if kind == "filters_applied" and ledger.applied is None:
        extra.append(("no_filter_call", "Said filters were applied but no tool call did it"))
    if extra:
        issues = report.issues + [Issue(code=c, claim=-1, detail=d) for c, d in extra]
        return report.model_copy(update={"ok": False, "issues": issues})
    return report


def _cache_key(question: str, filters: Filters, lang: str, llm: LLM) -> str:
    raw = "|".join([" ".join(question.lower().split()), filters.canonical(), lang, llm.name, PROMPT_VERSION, dataset_version()])
    return "chat:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def answer(question: str, filters: Filters, lang: str, history: list[Turn] | None = None, client_id: str = "local",
           llm: LLM | None = None, use_budget: bool = True) -> ChatResult:
    llm = llm or get_llm()
    store = get_store()
    key = _cache_key(question, filters, lang, llm) if not history else None
    if key and (hit := store.get(key)):
        return ChatResult(**{**hit, "cached": True})
    if use_budget and not allow_llm_call(client_id):
        return ChatResult(answer_type="rate_limited", message=LIMITED[lang])
    result = run(question, filters, lang, history or [], llm)
    if key and result.answer_type in ("answer", "filters_applied", "insufficient_data", "cannot_answer"):
        store.set(key, result.model_dump(mode="json"), 7 * 86_400)
    return result


def run(question: str, filters: Filters, lang: str, history: list[Turn], llm: LLM) -> ChatResult:
    ledger = Ledger(lang)
    context = f"{lang_line(lang)} Current dashboard filters: {filters.model_dump_json()}"
    messages: list[dict] = []
    for t in history[-6:]:  # earlier turns are text only: no figure in them can be cited
        messages.append({"role": "user" if t.role == "user" else "assistant", "content": t.text[:800]})
    if messages and messages[0]["role"] != "user":
        messages.pop(0)
    messages.append({"role": "user", "content": f"{context}\n\nQuestion: {question}"})

    usage: dict = {}
    rejected: list[str] = []
    attempts = 0
    for _ in range(MAX_ROUNDS):
        try:
            r = llm.create(system=CHAT_SYSTEM, messages=messages, schema=CHAT_SCHEMA, tools=TOOLS)
        except LLMUnavailable as e:
            log.warning("model unavailable: %s", e)
            return ChatResult(answer_type="error", message=UNAVAILABLE[lang], usage=usage, tool_calls=ledger.calls)
        for k, v in r.usage.items():
            usage[k] = usage.get(k, 0) + v
        if r.tool_uses:
            messages.append({"role": "assistant", "content": r.content})
            results = []
            for use in r.tool_uses:
                out, is_error = execute(use.name, use.input, ledger)
                block = {"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(out, ensure_ascii=False)}
                if is_error:
                    block["is_error"] = True
                results.append(block)
            messages.append({"role": "user", "content": results})
            continue
        attempts += 1
        report = None
        try:
            if r.stop_reason not in ("end_turn", "stop_sequence"):
                raise ValueError(f"stop_reason {r.stop_reason}")
            out = json.loads(r.text)
            report = check_answer(out, ledger, lang, filters)
        except (ValueError, KeyError, TypeError) as e:
            rejected.append(f"unusable_output: {e}")
        if report and report.ok:
            return ChatResult(
                answer_type=out["answer_type"], claims=[Claim(**c) for c in out["claims"]], message=out.get("message", ""),
                stats=list(ledger.stats.values()), applied_filters=ledger.applied, validation=report, attempts=attempts,
                rejected_issues=rejected, tool_calls=ledger.calls, usage=usage,
            )
        if report:
            rejected += [f"{i.code}: {i.detail}" for i in report.issues]
        if attempts >= 2:
            break
        messages.append({"role": "assistant", "content": r.content})
        messages.append({"role": "user", "content": feedback(report.issues) if report else "Return valid JSON for the schema."})
    return ChatResult(answer_type="unverified", message=UNVERIFIED[lang], stats=list(ledger.stats.values()),
                      applied_filters=ledger.applied, attempts=attempts, rejected_issues=rejected,
                      tool_calls=ledger.calls, usage=usage)
