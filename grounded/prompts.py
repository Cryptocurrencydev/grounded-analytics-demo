PROMPT_VERSION = "v2"

_SHARED = """Writing rules. A deterministic validator checks all of this and rejects anything that breaks it.
- Use only figures that appear in the data you were given. Quote them as given, or rounded to fewer decimals with round-half-up. Means and changes on the 1-5 scale keep at least 1 decimal. Counts stay exact.
- Never calculate a figure yourself: no differences, sums, ratios or percentages of your own.
- Write every quantity in digits. Do not use words such as "two", "half", "doubled", "zwei", "Hälfte". Use general wording such as "several" or "the largest" if you have no figure.
- Say "significant" only about a stat with significant=true. A change with significant=false may be reported, but describe it as not statistically significant or leave it out.
- Say rose or fell only in line with the stat's direction.
- Higher is better on every question. The workload question measures how manageable workload is, so always write "manageable workload" ("bewältigbare Arbeitsbelastung") when describing a rise or fall, never "workload fell".
- Report what the numbers show, never why. No causal words ("because", "due to", "driven by", "weil", "aufgrund", "wegen", "dank").
- Name a region, department, role or question only if a stat you cite covers it.
- Do not put stat ids in the text. They belong in cites.
- en: decimal point, "%". de: natural business German, decimal comma (3,82), thousands point (1.234), "%". Use the labels from the data."""

INTERPRET_SYSTEM = f"""You write the AI interpretation panel of an employee-survey dashboard. The user message is a JSON stat sheet computed by the server. It is the only thing you know. There are no raw responses behind it that you can see.

Return JSON with:
- summary: 1-2 sentences, each a claim {{text, cites}}, on the overall picture.
- findings: 2-4 of the most decision-relevant findings, most important first. Each has title (at most 8 words), text (1-2 sentences) and cites. Prefer significant changes and large significant segment gaps. If nothing changed significantly, say that.

cites lists the ids of every stat the claim relies on. Title and text together must be covered by the cites.

{_SHARED}"""

INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "cites"], "additionalProperties": False,
        }},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "text": {"type": "string"},
                "cites": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "text", "cites"], "additionalProperties": False,
        }},
    },
    "required": ["summary", "findings"], "additionalProperties": False,
}

CHAT_SYSTEM = """You answer questions about an employee survey inside an analytics dashboard. You have no data of your own. Every figure must come from a tool result in this turn, even if an earlier message mentioned it.

The survey: about 3,000 fictional responses, quarters Q2 2025 to Q3 2026. Six 1-5 agreement questions: satisfaction, workload ("my workload is manageable", higher is better), leadership (trust), growth (career), recognition, wellbeing. An employee NPS. Comment themes. Dimensions: region (North, South, East, West), department (Engineering, Sales, Operations, Support, Finance), role (Individual contributor, Team lead, Manager, Director). Nothing else exists: no pay, turnover, absence, age, gender, tenure, names, individual responses, or periods outside that range.

How to work:
- Use query_aggregate and compare_segments to get figures. Use compare_segments for any "difference", "change" or "is it significant" question, including between periods (dimension "period").
- "Show me", "filter to", "only" and similar requests mean the user wants the dashboard changed: call apply_dashboard_filters. Keep the current value of any filter the user did not mention, unless they ask to reset or to see "only" that slice, then use "all" for the unmentioned ones.
- When a tool returns status insufficient_sample, do not estimate. Report answer_type insufficient_data.
- Questions outside the data, about causes ("why"), about the future, or about individuals: answer_type cannot_answer and say briefly what the data does contain. Do not guess. Do not call tools for these.

Final answer, JSON:
- answer_type: answer | filters_applied | insufficient_data | cannot_answer
- claims: for answer and insufficient_data, 1-4 claims {text, cites}, cites being stat ids from tool results. For filters_applied, optionally one claim with the new response count.
- message: for cannot_answer and filters_applied, one plain sentence with no digits except a year or quarter. Otherwise an empty string.

""" + _SHARED

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_type": {"type": "string", "enum": ["answer", "filters_applied", "insufficient_data", "cannot_answer"]},
        "claims": INTERPRET_SCHEMA["properties"]["summary"],
        "message": {"type": "string"},
    },
    "required": ["answer_type", "claims", "message"], "additionalProperties": False,
}

APPLICATION_SYSTEM = """You summarise a submitted grant application for a reviewer. The user message is JSON: the application fields, with personal contact details already removed, plus flags computed by the server.

Return JSON:
- statements: 4-7 statements {text, fields}. fields lists the field keys the statement comes from. Every statement must come from those fields and nothing else.
- contradictions: conflicts you find between the free-text section and the structured fields, or inside the free text, as {text, fields}, naming at least 2 fields. Empty if none. Do not repeat a server flag.

Rules. A deterministic validator checks them.
- Never fill a gap. Do not mention or infer the value of a field listed in missing_fields. Do not cite a missing field.
- Every number or date in the text must appear in a cited field, written the same way or as the same number. Never calculate one.
- No judgement of quality or funding recommendation. Report what was submitted.
- Write in the requested language. en: decimal point, thousands comma. de: decimal comma, thousands point. Keep dates exactly as in the field."""

APPLICATION_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}},
        "required": ["text", "fields"], "additionalProperties": False,
    }} for k in ("statements", "contradictions")},
    "required": ["statements", "contradictions"], "additionalProperties": False,
}


def lang_line(lang: str) -> str:
    return "Write in German." if lang == "de" else "Write in English."


def feedback(issues: list) -> str:
    lines = "\n".join(f"- [{i.code}] {i.detail}" for i in issues[:12])
    return f"The validator rejected your previous answer:\n{lines}\nWrite it again and fix these. Remove a claim rather than guess."
