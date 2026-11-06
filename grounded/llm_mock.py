"""A deterministic stand-in for tests and CI. It follows the same contracts as the real model."""
from __future__ import annotations

import json
import re

from .llm import LLMResponse, ToolUse


def _fmt(v: float, decimals: int, lang: str) -> str:
    s = f"{v:,.{decimals}f}"
    return s.translate(str.maketrans(",.", ".,")) if lang == "de" else s


class MockLLM:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, system, messages, schema=None, tools=None, effort=None, max_tokens=8000, cache_prompt=False):
        self.calls += 1
        if tools:
            return self._chat(messages)
        last = messages[-1]["content"]
        lang = "de" if last.startswith("Write in German") else "en"
        body = json.loads(last[last.index("{"): last.rindex("}") + 1])
        if "application_id" in body:
            return self._application(body, lang)
        return self._interpret(body, lang)

    def _final(self, obj: dict) -> LLMResponse:
        text = json.dumps(obj, ensure_ascii=False)
        return LLMResponse("end_turn", text, [], [{"type": "text", "text": text}], {"input_tokens": 10, "output_tokens": 10})

    def _interpret(self, sheet: dict, lang: str) -> LLMResponse:
        stats = sheet["stats"]
        n = stats[0]
        means = [s for s in stats if "unit" in s and s["unit"] == "scale"]
        low = min(means, key=lambda s: s["value"])
        high = max(means, key=lambda s: s["value"])
        name = lambda s: s["label"].split(":")[0]
        if lang == "de":
            summary = f"{_fmt(n['value'], 0, lang)} Antworten im aktuellen Filter."
            f1 = ("Niedrigster Wert", f"{name(low)} liegt im Mittel bei {_fmt(low['value'], 2, lang)}.")
            f2 = ("Höchster Wert", f"{name(high)} liegt im Mittel bei {_fmt(high['value'], 2, lang)}.")
        else:
            summary = f"{_fmt(n['value'], 0, lang)} responses in the current filter."
            f1 = ("Lowest score", f"{name(low)} averages {_fmt(low['value'], 2, lang)}.")
            f2 = ("Highest score", f"{name(high)} averages {_fmt(high['value'], 2, lang)}.")
        return self._final({
            "summary": [{"text": summary, "cites": [n["id"]]}],
            "findings": [{"title": f1[0], "text": f1[1], "cites": [low["id"]]},
                         {"title": f2[0], "text": f2[1], "cites": [high["id"]]}],
        })

    def _application(self, body: dict, lang: str) -> LLMResponse:
        f = body["fields"]
        return self._final({
            "statements": [
                {"text": f"{f['organisation']}: {f['project_title']}.", "fields": ["organisation", "project_title"]},
                {"text": f"Requested amount EUR {f['requested_amount_eur']}.", "fields": ["requested_amount_eur"]},
            ],
            "contradictions": [],
        })

    def _chat(self, messages: list[dict]) -> LLMResponse:
        last = messages[-1]["content"]
        if isinstance(last, list):  # tool results came back
            result = json.loads(last[0]["content"])
            row = result["rows"][0]
            if result.get("status") == "applied":
                return self._final({"answer_type": "filters_applied", "claims": [
                    {"text": f"{row['value']:,.0f} responses in this view.", "cites": [row["id"]]}],
                    "message": "Dashboard filters updated."})
            if row.get("status") == "insufficient_sample":
                return self._final({"answer_type": "insufficient_data", "claims": [
                    {"text": "Too few responses in this slice to report a figure.", "cites": [row["id"]]}], "message": ""})
            return self._final({"answer_type": "answer", "claims": [
                {"text": f"The value is {row['value']}.", "cites": [row["id"]]}], "message": ""})
        question = last.rsplit("Question:", 1)[-1].lower()
        current = json.loads(re.search(r"filters: (\{.*\})", last).group(1))
        if re.search(r"salary|pay|turnover|why", question):
            return self._final({"answer_type": "cannot_answer", "claims": [],
                                "message": "That is not in this survey data."})
        if re.search(r"\b(show|only|filter)\b", question):
            args = {**current}
            for region in ("north", "south", "east", "west"):
                if region in question:
                    args["region"] = region.title()
            year = re.search(r"\b(2025|2026)\b", question)
            if year:
                args["period"] = year.group(1)
            return self._use("apply_dashboard_filters", args)
        return self._use("query_aggregate", {"measure": "nps", "group_by": "none", "filters": current})

    def _use(self, name: str, args: dict) -> LLMResponse:
        block = {"type": "tool_use", "id": f"toolu_mock_{self.calls}", "name": name, "input": args}
        return LLMResponse("tool_use", "", [ToolUse(block["id"], name, args)], [block], {"input_tokens": 10, "output_tokens": 10})
