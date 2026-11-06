"""Interpretation flow, chat tools and refusal, applications, privacy, budgets, API."""
import json

import pytest
from fastapi.testclient import TestClient

from grounded import applications, chat, data, llm, store, tools
from grounded.catalog import DATA_DIR, Filters
from grounded.interpret import interpret
from grounded.llm import LLMResponse, LLMUnavailable, ToolUse
from grounded.llm_mock import MockLLM
from grounded.main import app
from grounded.sheet import build_sheet, pseudonym


class Scripted:
    """Returns canned responses in order and records what it was sent."""
    name = "scripted"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, *, system, messages, schema=None, tools=None, **_):
        self.requests.append({"system": system, "messages": json.loads(json.dumps(messages, default=str)), "tools": tools})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, LLMResponse):
            return r
        return final(r)


def final(obj):
    text = json.dumps(obj)
    return LLMResponse("end_turn", text, [], [{"type": "text", "text": text}], {"input_tokens": 1, "output_tokens": 1})


def tool_use(name, args, id="t1"):
    return LLMResponse("tool_use", "", [ToolUse(id, name, args)], [{"type": "tool_use", "id": id, "name": name, "input": args}], {})


def out_ok(sheet):
    s = next(x for x in sheet.stats if x.key == "mean.satisfaction")
    return {"summary": [{"text": f"Satisfaction averages {s.value:.2f}.", "cites": [s.id]}],
            "findings": [{"title": "Level", "text": f"The mean is {s.value:.2f}.", "cites": [s.id]}]}


BAD = {"summary": [{"text": "Satisfaction averages 4.99.", "cites": ["S01"]}], "findings": [{"title": "x", "text": "y", "cites": []}]}
F = Filters(region="South")


def test_valid_output_passes_first_time_and_is_cached():
    m = Scripted(out_ok(build_sheet(F)))
    first = interpret(F, "en", llm=m)
    assert (first.status, first.attempts, first.cached) == ("ok", 1, False)
    second = interpret(F, "en", llm=m)
    assert second.cached and len(m.requests) == 1


def test_cache_key_separates_filters_and_language():
    sheet = build_sheet(F)
    german = {"summary": [{"text": "Keine Auffälligkeit.", "cites": ["S01"]}], "findings": [{"title": "Lage", "text": "Stabil.", "cites": ["S01"]}]}
    m = Scripted(out_ok(sheet), german)
    interpret(F, "en", llm=m)
    interpret(F, "de", llm=m)
    assert len(m.requests) == 2


def test_invalid_output_regenerates_once_with_feedback():
    m = Scripted(BAD, out_ok(build_sheet(F)))
    r = interpret(F, "en", llm=m)
    assert (r.status, r.attempts) == ("ok", 2)
    assert any("number_not" in i for i in r.rejected_issues)
    assert "rejected your previous answer" in m.requests[1]["messages"][-1]["content"]


def test_two_failures_show_the_safe_fallback_and_are_not_cached():
    m = Scripted(BAD, BAD)
    r = interpret(F, "en", llm=m)
    assert r.status == "fallback" and r.attempts == 2 and r.validation.ok and r.findings == []
    assert "4.99" not in json.dumps(r.summary[0].model_dump())
    m2 = Scripted(out_ok(build_sheet(F)))
    assert interpret(F, "en", llm=m2).status == "ok"


def test_model_outage_shows_the_fallback():
    assert interpret(F, "en", llm=Scripted(LLMUnavailable("connection"))).status == "fallback"


def test_truncated_output_is_never_shown():
    cut = LLMResponse("max_tokens", '{"summary": [', [], [], {})
    assert interpret(F, "en", llm=Scripted(cut, cut)).status == "fallback"


@pytest.mark.parametrize("f", [Filters(period="2026-Q1", department="Finance", role="Director"),
                               Filters(period="2026-Q1", region="East", department="Finance")])
def test_small_sample_refuses_without_calling_the_model(f):
    m = Scripted()
    r = interpret(f, "en", llm=m)
    assert r.status == "insufficient" and r.summary == [] and m.requests == []
    assert "needed for an interpretation" in r.warnings[0]


def test_insufficient_warning_in_german():
    r = interpret(Filters(period="2026-Q1", department="Finance", role="Director"), "de", llm=Scripted())
    assert "mindestens" in r.warnings[0]


def test_budget_exhausted_gives_fallback_without_a_model_call(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "0")
    m = Scripted()
    r = interpret(F, "en", llm=m)
    assert r.status == "rate_limited" and m.requests == [] and r.summary


def test_rate_limits_per_client_and_per_day(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "2")
    monkeypatch.setenv("DAILY_LLM_CAP", "3")
    assert [store.allow_llm_call("a") for _ in range(3)] == [True, True, False]
    assert [store.allow_llm_call("b") for _ in range(3)] == [True, False, False]  # daily cap reached


# Privacy

def test_model_input_has_no_raw_rows_or_free_text():
    comments = __import__("pandas").read_parquet(DATA_DIR / "comments.parquet")
    m = MockLLM()
    seen = []
    orig = m.create
    m.create = lambda **kw: (seen.append(json.dumps(kw["messages"])), orig(**kw))[1]
    interpret(Filters(), "en", llm=m)
    sent = seen[0]
    assert not any(text in sent for text in comments.comment.head(300))
    assert "R0" not in sent, "real response ids must not appear"
    assert "p_" in sent and "pseudonymous_refs" in sent
    assert all(name not in sent for name in ("Lindqvist", "Ferro", "Okafor", "Weidmann"))


def test_comment_file_is_excluded_from_the_deployment():
    cfg = json.loads((DATA_DIR.parent / "vercel.json").read_text())
    assert "comments.parquet" in json.dumps(cfg["functions"])


def test_pseudonyms_depend_on_the_salt(monkeypatch):
    a = pseudonym("R00001")
    monkeypatch.setenv("PSEUDONYM_SALT", "other")
    assert pseudonym("R00001") != a and "R00001" not in a


def test_small_counts_are_hidden_from_the_dashboard_api():
    c = TestClient(app)
    r = c.post("/api/dashboard", json={"filters": {"period": "2026-Q1", "department": "Finance", "role": "Director"}}).json()
    assert r["too_small"] and r["n"] is None and r["kpis"]["nps"] is None
    assert all(p is None for row in r["distribution"] for p in row["pct"])


# Tools

def test_tool_schemas_offer_only_whitelisted_values():
    schema = tools.TOOLS[0]["input_schema"]["properties"]
    assert "salary" not in schema["measure"]["enum"]
    assert set(schema["group_by"]["enum"]) == {"none", "quarter", "region", "department", "role"}
    assert all(t["strict"] is True for t in tools.TOOLS)
    assert {t["name"] for t in tools.TOOLS} == {"query_aggregate", "compare_segments", "apply_dashboard_filters"}


@pytest.mark.parametrize("name,args", [
    ("query_aggregate", {"measure": "salary", "group_by": "none", "filters": {}}),
    ("query_aggregate", {"measure": "nps", "group_by": "gender", "filters": {}}),
    ("query_aggregate", {"measure": "nps", "group_by": "none", "filters": {"region": "Atlantis"}}),
    ("query_aggregate", {"measure": "nps", "group_by": "none", "filters": {}, "sql": "SELECT 1"}),
    ("query_aggregate", {"measure": "nps; DROP TABLE responses", "group_by": "none", "filters": {}}),
    ("query_aggregate", {"measure": "nps", "group_by": "none", "filters": {"region": "North' OR '1'='1"}}),
    ("compare_segments", {"measure": "mean_workload", "dimension": "region", "a": "North", "b": "Mars", "filters": {}}),
    ("compare_segments", {"measure": "mean_workload", "dimension": "period", "a": "2024", "b": "2025", "filters": {}}),
    ("compare_segments", {"measure": "response_count", "dimension": "region", "a": "North", "b": "South", "filters": {}}),
    ("apply_dashboard_filters", {"region": "Atlantis", "period": "all", "department": "all", "role": "all"}),
    ("run_sql", {"query": "SELECT * FROM responses"}),
])
def test_tool_rejects_anything_off_the_whitelist(name, args):
    out, is_error = tools.execute(name, args, tools.Ledger("en"))
    assert is_error and "error" in out


def test_data_layer_refuses_unknown_columns_directly():
    with pytest.raises(ValueError):
        data.moments(Filters(), "salary")
    with pytest.raises(ValueError):
        data.moments_by(Filters(), "workload", "1=1; DROP TABLE responses")


def test_query_aggregate_returns_citable_stats():
    ledger = tools.Ledger("en")
    out, err = tools.execute("query_aggregate", {"measure": "mean_workload", "group_by": "department", "filters": Filters().model_dump()}, ledger)
    assert not err and len(out["rows"]) == 5
    finance = next(r for r in out["rows"] if r["group"] == "Finance")
    assert finance["value"] == pytest.approx(data.moments(Filters(department="Finance"), "workload").mean, abs=0.005)
    assert finance["id"] in ledger.stats


def test_small_slice_returns_no_value():
    ledger = tools.Ledger("en")
    out, _ = tools.execute("query_aggregate", {"measure": "mean_workload", "group_by": "none", "filters": Filters(
        period="2026-Q1", department="Finance", role="Director").model_dump()}, ledger)
    row = out["rows"][0]
    assert row["status"] == "insufficient_sample" and "value" not in row and row["n"] == "fewer than 5"


def test_compare_segments_runs_a_test():
    ledger = tools.Ledger("en")
    out, _ = tools.execute("compare_segments", {"measure": "mean_workload", "dimension": "department", "a": "Operations",
                                                "b": "Finance", "filters": Filters().model_dump()}, ledger)
    row = out["rows"][0]
    assert row["significant"] is True and row["value"] < 0 and row["p_value"] < 0.05 and row["test"] == "welch_t"


def test_compare_periods_and_agree_share():
    ledger = tools.Ledger("en")
    out, _ = tools.execute("compare_segments", {"measure": "agree_pct_workload", "dimension": "period", "a": "2026",
                                                "b": "2025", "filters": Filters(department="Operations").model_dump()}, ledger)
    assert out["rows"][0]["unit"] == "pp" and out["rows"][0]["test"] == "chi2"


def test_period_direction_follows_time_not_argument_order():
    args = lambda a, b: {"measure": "mean_workload", "dimension": "period", "a": a, "b": b, "filters": Filters(department="Operations").model_dump()}
    for a, b in (("2025", "2026"), ("2026", "2025")):
        ledger = tools.Ledger("en")
        tools.execute("compare_segments", args(a, b), ledger)
        assert ledger.stats["C01"].direction == "down", "the score fell from 2025 to 2026 whichever way it was asked"


def test_segment_comparison_has_no_direction():
    ledger = tools.Ledger("en")
    tools.execute("compare_segments", {"measure": "mean_workload", "dimension": "region", "a": "North", "b": "South",
                                       "filters": Filters().model_dump()}, ledger)
    assert ledger.stats["C01"].direction is None


def test_theme_name_counts_as_covering_its_question():
    from grounded.models import Claim
    from grounded.validator import validate
    sheet = build_sheet(Filters())
    s = next(x for x in sheet.stats if x.key == "theme.workload_pressure")
    assert validate([Claim(text=f"Workload pressure leads at {s.value}% of comments.", cites=[s.id])], sheet.by_id(), "en").ok


# Chat

def test_chat_applies_filters_through_the_tool():
    r = chat.answer("show me only the north region in 2026", Filters(), "en", llm=MockLLM())
    assert r.answer_type == "filters_applied" and r.applied_filters == Filters(region="North", period="2026")
    assert r.validation.ok


def test_chat_cannot_claim_filters_without_the_tool_call():
    m = Scripted({"answer_type": "filters_applied", "claims": [], "message": "Done."},
                 {"answer_type": "filters_applied", "claims": [], "message": "Done."})
    assert chat.answer("show north", Filters(), "en", llm=m).answer_type == "unverified"


def test_chat_refuses_what_the_data_cannot_answer():
    r = chat.answer("what is the average salary?", Filters(), "en", llm=MockLLM())
    assert r.answer_type == "cannot_answer" and r.claims == [] and r.tool_calls == []


def test_chat_refusal_with_a_number_is_rejected():
    bad = {"answer_type": "cannot_answer", "claims": [], "message": "Salaries average 52,000."}
    good = {"answer_type": "cannot_answer", "claims": [], "message": "The survey has no salary data."}
    m = Scripted(bad, good)
    r = chat.answer("salary?", Filters(), "en", llm=m)
    assert r.answer_type == "cannot_answer" and "52" not in r.message and r.attempts == 2


def test_chat_answer_with_invented_number_is_regenerated_then_withheld():
    args = {"measure": "nps", "group_by": "none", "filters": Filters().model_dump()}
    bad = {"answer_type": "answer", "claims": [{"text": "NPS is 55.5.", "cites": ["C01"]}], "message": ""}
    m = Scripted(tool_use("query_aggregate", args), bad, bad)
    r = chat.answer("nps?", Filters(), "en", llm=m)
    assert r.answer_type == "unverified" and r.claims == [] and r.stats, "shows tool figures, not the bad text"


def test_chat_citation_must_come_from_this_turn():
    bad = {"answer_type": "answer", "claims": [{"text": "NPS is -23.9.", "cites": ["C01"]}], "message": ""}
    r = chat.answer("nps?", Filters(), "en", llm=Scripted(bad, bad))
    assert r.answer_type == "unverified", "no tool ran, so C01 does not exist"


def test_chat_history_is_text_only_and_short():
    m = Scripted({"answer_type": "cannot_answer", "claims": [], "message": "No."})
    hist = [chat.Turn(role="user", text="q"), chat.Turn(role="assistant", text="a" * 2000)]
    chat.answer("why?", Filters(), "en", history=hist, llm=m)
    assert len(m.requests[0]["messages"][1]["content"]) == 800


def test_chat_outage_is_a_clear_error():
    r = chat.answer("nps?", Filters(), "en", llm=Scripted(LLMUnavailable("connection")))
    assert r.answer_type == "error" and "not available" in r.message


# Applications

def by_id(i):
    return applications.get(i)


def test_rule_flags_find_each_planted_problem():
    assert applications.rule_flags(by_id("APP-1041"), "en") == []
    assert sorted(applications.missing_fields(by_id("APP-1042"))) == ["budget_fieldwork_eur", "data_protection_officer", "target_sample_size"]
    assert "125,000" in applications.rule_flags(by_id("APP-1043"), "en")[0].text
    assert "12 months" in applications.rule_flags(by_id("APP-1044"), "en")[0].text
    assert applications.missing_fields(by_id("APP-1045")) == ["end_date"]


def test_contact_details_never_reach_the_model():
    sent = json.dumps(applications.payload_for_llm(by_id("APP-1042")))
    assert "Ferro" not in sent and "@" not in sent


def test_summary_validator_catches_each_failure():
    app_ = by_id("APP-1042")
    check = lambda s, c=(): applications.validate_summary({"statements": s, "contradictions": list(c)}, app_)[0]
    assert check([{"text": "A pulse survey.", "fields": ["project_description"]}]) == []
    assert check([{"text": "Requests EUR 61,500.", "fields": ["requested_amount_eur"]}]) == []
    assert check([{"text": "Requests EUR 61.500.", "fields": ["requested_amount_eur"]}]) == []
    assert "missing_citation" in check([{"text": "A survey.", "fields": []}])[0]
    assert "number_not_in_cited_field" in check([{"text": "Requests EUR 70,000.", "fields": ["requested_amount_eur"]}])[0]
    assert "number_not_in_cited_field" in check([{"text": "Requests EUR 61,500.", "fields": ["organisation"]}])[0]
    assert "cites_missing_field" in check([{"text": "Sample unknown.", "fields": ["target_sample_size"]}])[0]
    assert "unknown_field" in check([{"text": "Budget.", "fields": ["salary"]}])[0]
    assert "contradiction_needs_two_fields" in check([{"text": "ok", "fields": ["organisation"]}],
                                                     [{"text": "Conflict.", "fields": ["team_size"]}])[0]


def test_summary_regenerates_then_falls_back_to_flags_only():
    bad = {"statements": [{"text": "Requests EUR 99,999.", "fields": ["requested_amount_eur"]}], "contradictions": []}
    r = applications.summarise(by_id("APP-1042"), "en", llm=Scripted(bad, bad))
    assert r.status == "fallback" and r.statements == [] and len(r.flags) == 3


# HTTP

def test_api_rejects_bad_input():
    c = TestClient(app)
    assert c.post("/api/dashboard", json={"filters": {"region": "Atlantis"}}).status_code == 422
    assert c.post("/api/dashboard", json={"filters": {"sql": "x"}}).status_code == 422
    assert c.post("/api/chat", json={"question": "x" * 501}).status_code == 422
    assert c.post("/api/chat", json={"question": ""}).status_code == 422
    assert c.post("/api/interpret", json={"lang": "fr"}).status_code == 422
    assert c.get("/api/applications/NOPE").status_code == 404


def test_api_end_to_end_with_mock():
    c = TestClient(app)
    llm.set_llm(MockLLM())
    d = c.post("/api/dashboard", json={"filters": {"period": "2026"}}).json()
    assert d["n"] > 1000 and len(d["trend"]) == 6 and len(d["trend"][0]["points"]) == 6
    assert d["selected_quarters"] == ["2026-Q1", "2026-Q2", "2026-Q3"]
    r = c.post("/api/interpret", json={"filters": {"period": "2026"}, "lang": "en"}).json()
    assert r["status"] == "ok" and r["sent_to_model"]["stats"]
    assert {"id", "label", "value"} <= set(r["stats"][0])
