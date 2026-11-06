"""Application summaries. Each statement cites the fields it came from. Gaps are flagged, never filled."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from functools import lru_cache

from pydantic import BaseModel, Field

from .catalog import DATA_DIR
from .llm import LLM, LLMUnavailable, get_llm
from .precomputed import lookup
from .prompts import APPLICATION_SCHEMA, APPLICATION_SYSTEM, PROMPT_VERSION, feedback, lang_line
from .store import allow_llm_call, get_store

REQUIRED = [
    "organisation", "legal_form", "country", "project_title", "start_date", "end_date", "duration_months",
    "requested_amount_eur", "budget_personnel_eur", "budget_fieldwork_eur", "budget_other_eur",
    "target_sample_size", "team_size", "ethics_approval", "data_protection_officer", "project_description",
]
PII_FIELDS = {"contact_name", "contact_email"}
FIELD_LABELS = {
    "organisation": "Organisation", "legal_form": "Legal form", "country": "Country", "contact_name": "Contact name",
    "contact_email": "Contact email", "project_title": "Project title", "start_date": "Start date", "end_date": "End date",
    "duration_months": "Duration (months)", "requested_amount_eur": "Requested amount (EUR)",
    "budget_personnel_eur": "Budget: personnel (EUR)", "budget_fieldwork_eur": "Budget: fieldwork (EUR)",
    "budget_other_eur": "Budget: other (EUR)", "target_sample_size": "Target sample size", "team_size": "Team size",
    "ethics_approval": "Ethics approval", "data_protection_officer": "Data protection officer",
    "previous_funding": "Previous funding", "project_description": "Project description (free text)",
}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d /-]{7,}\d")
_DIGITS = re.compile(r"\d[\d.,]*\d|\d")


class Flag(BaseModel):
    kind: str  # missing | contradiction
    source: str  # rule | ai
    text: str
    fields: list[str]


class Statement(BaseModel):
    text: str
    fields: list[str]


class AppSummary(BaseModel):
    id: str
    status: str  # ok | fallback | rate_limited
    lang: str
    statements: list[Statement] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    attempts: int = 0
    rejected_issues: list[str] = Field(default_factory=list)
    model: str | None = None
    cached: bool = False
    sent_to_model: dict | None = None
    numbers_checked: int = 0


@lru_cache(maxsize=1)
def load() -> list[dict]:
    return json.loads((DATA_DIR / "applications.json").read_text())


def get(app_id: str) -> dict | None:
    return next((a for a in load() if a["id"] == app_id), None)


def missing_fields(app: dict) -> list[str]:
    return [k for k in REQUIRED if app["fields"].get(k) in (None, "")]


def _t(lang: str, en: str, de: str) -> str:
    return de if lang == "de" else en


def _eur(v: float, lang: str) -> str:
    s = f"{v:,.0f}"
    return "EUR " + (s.replace(",", ".") if lang == "de" else s)


def rule_flags(app: dict, lang: str) -> list[Flag]:
    """Checks that need no model: missing fields and arithmetic between fields."""
    f = app["fields"]
    flags = [
        Flag(kind="missing", source="rule", fields=[k],
             text=_t(lang, f"{FIELD_LABELS[k]} was not provided.", f"{FIELD_LABELS[k]}: keine Angabe."))
        for k in missing_fields(app)
    ]
    parts = [f.get(k) for k in ("budget_personnel_eur", "budget_fieldwork_eur", "budget_other_eur")]
    if all(isinstance(p, (int, float)) for p in parts) and sum(parts) != f.get("requested_amount_eur"):
        flags.append(Flag(
            kind="contradiction", source="rule",
            fields=["requested_amount_eur", "budget_personnel_eur", "budget_fieldwork_eur", "budget_other_eur"],
            text=_t(lang, f"Budget lines add up to {_eur(sum(parts), lang)}, the requested amount is {_eur(f['requested_amount_eur'], lang)}.",
                    f"Die Budgetposten ergeben {_eur(sum(parts), lang)}, beantragt sind {_eur(f['requested_amount_eur'], lang)}."),
        ))
    if f.get("start_date") and f.get("end_date") and f.get("duration_months"):
        a, b = date.fromisoformat(f["start_date"]), date.fromisoformat(f["end_date"])
        months = (b.year - a.year) * 12 + b.month - a.month + (1 if b.day >= a.day - 1 else 0)
        if months != f["duration_months"]:
            flags.append(Flag(
                kind="contradiction", source="rule", fields=["start_date", "end_date", "duration_months"],
                text=_t(lang, f"The dates span {months} months, the stated duration is {f['duration_months']} months.",
                        f"Die Daten umfassen {months} Monate, angegeben sind {f['duration_months']} Monate."),
            ))
    return flags


def payload_for_llm(app: dict) -> dict:
    """Contact details never leave. The free text must, so it is scrubbed first."""
    f = app["fields"]
    fields = {k: v for k, v in f.items() if k not in PII_FIELDS and v not in (None, "")}
    text = fields.get("project_description", "")
    text = _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", text))
    if f.get("contact_name"):
        text = text.replace(f["contact_name"], "[name removed]")
    fields["project_description"] = text
    return {"application_id": app["id"], "fields": fields, "missing_fields": missing_fields(app)}


def _numbers(text: str) -> set[str]:
    """Digits only, so 120,000, 120.000 and 120000 compare equal. Trailing .0 and ,5 are kept apart."""
    return {re.sub(r"[.,]", "", m) for m in _DIGITS.findall(text)}


def validate_summary(out: dict, app: dict) -> tuple[list[str], int]:
    issues: list[str] = []
    checked = 0
    payload = payload_for_llm(app)["fields"]
    missing = set(missing_fields(app))
    items = [(s, "statement") for s in out["statements"]] + [(c, "contradiction") for c in out["contradictions"]]
    if not out["statements"]:
        issues.append("empty: no statements")
    for item, kind in items:
        fields = item["fields"]
        if not fields:
            issues.append(f"missing_citation: {item['text']!r} cites no field")
        for k in fields:
            if k in missing:
                issues.append(f"cites_missing_field: {k} has no value")
            elif k not in payload:
                issues.append(f"unknown_field: {k}")
        if kind == "contradiction" and len(fields) < 2:
            issues.append(f"contradiction_needs_two_fields: {item['text']!r}")
        allowed: set[str] = set()
        for k in fields:
            allowed |= _numbers(str(payload.get(k, "")))
        for number in _numbers(item["text"]):
            checked += 1
            if number not in allowed:
                issues.append(f"number_not_in_cited_field: {number} in {item['text']!r}")
    return issues, checked


def cache_key(app_id: str, lang: str, llm_name: str) -> str:
    return "app:" + hashlib.sha256("|".join([app_id, lang, llm_name, PROMPT_VERSION]).encode()).hexdigest()[:32]


def summarise(app: dict, lang: str, client_id: str = "local", llm: LLM | None = None, use_budget: bool = True) -> AppSummary:
    llm = llm or get_llm()
    key = cache_key(app["id"], lang, llm.name)
    store = get_store()
    if hit := (store.get(key) or lookup(key)):
        return AppSummary(**{**hit, "cached": True})
    flags = rule_flags(app, lang)
    if use_budget and not allow_llm_call(client_id):
        return AppSummary(id=app["id"], status="rate_limited", lang=lang, flags=flags)

    payload = payload_for_llm(app)
    payload["server_flags"] = [x.text for x in flags]
    user = f"{lang_line(lang)}\n\n{json.dumps(payload, ensure_ascii=False)}"
    messages = [{"role": "user", "content": user}]
    rejected: list[str] = []
    attempt = 0
    for attempt in (1, 2):
        try:
            r = llm.create(system=APPLICATION_SYSTEM, messages=messages, schema=APPLICATION_SCHEMA)
        except LLMUnavailable as e:
            rejected.append(f"model_unavailable: {e}")
            break
        try:
            out = json.loads(r.text)
            issues, checked = validate_summary(out, app)
        except (ValueError, KeyError, TypeError) as e:
            rejected.append(f"unusable_output: {e}")
            continue
        if not issues:
            result = AppSummary(
                id=app["id"], status="ok", lang=lang, statements=[Statement(**s) for s in out["statements"]],
                flags=flags + [Flag(kind="contradiction", source="ai", text=c["text"], fields=c["fields"]) for c in out["contradictions"]],
                attempts=attempt, rejected_issues=rejected, model=llm.name, sent_to_model=payload, numbers_checked=checked,
            )
            store.set(key, result.model_dump(), 30 * 86_400)
            return result
        rejected += issues
        messages = [{"role": "user", "content": f"{user}\n\n{feedback_lines(issues)}"}]
    return AppSummary(id=app["id"], status="fallback", lang=lang, flags=flags, attempts=attempt,
                      rejected_issues=rejected, model=llm.name, sent_to_model=payload)


def feedback_lines(issues: list[str]) -> str:
    return "The validator rejected your previous answer:\n" + "\n".join(f"- {i}" for i in issues[:12]) + "\nFix these. Remove a statement rather than guess."


__all__ = ["feedback", "get", "load", "missing_fields", "payload_for_llm", "rule_flags", "summarise", "validate_summary"]
