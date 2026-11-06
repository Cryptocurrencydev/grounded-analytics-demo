"""Deterministic claim checker. No model involved: same input, same verdict.

Rules, for every claim:
  1. It cites at least one stat, and every cited id exists.
  2. Every number in the text matches a figure on a cited stat under the rounding rules below.
  3. Quantities are digits. Spelled-out numbers cannot be checked, so they fail.
  4. Periods mentioned exist in the dataset.
  5. "Rose" and "fell" agree with the sign of a cited change.
  6. "Significant" needs a cited stat whose test was significant. "Not significant" needs one that was not.
  7. A segment or question named in the text is on a cited stat or in the active filter.
  8. No causal language. A survey aggregate cannot show why something happened.

Rounding: figures have a canonical rounded value, the same one the charts show. A claim may quote it
exactly or coarsen it with round-half-up: 3.85 may appear as 3.85 or 3.9, never 3.8. More digits than
the canonical value is rejected. Means and scale changes need at least 1 decimal. Counts are exact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .catalog import ALPHA, CASE_INSENSITIVE_ENTITIES, ENTITY_ALIASES, QUARTERS, YEARS
from .models import Claim, Issue, Number, Stat, ValidationReport

MIN_DECIMALS = {"scale": 1, "scale_delta": 1, "pct": 0, "pp": 0, "nps": 0, "nps_delta": 0, "count": 0, "p": 2}
VALID_PERIODS = {q[-2:] + q[:4] for q in QUARTERS}

_PERIOD = re.compile(
    r"\bQ([1-4])\s*[/\- ]?\s*(20\d{2})\b|\b(20\d{2})\s*[/\- ]?\s*Q([1-4])\b|\b([1-4])\.\s*Quartal\s+(20\d{2})\b"
)
_YEAR = re.compile(r"\b(" + "|".join(YEARS) + r")\b")
_NUMBER = re.compile(r"(?<![\w.,])([+\-−]?)(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?![\w])")
_PCT_AFTER = re.compile(r"\s*(%|percent\b|per cent\b|prozent\b)", re.IGNORECASE)
_PP_AFTER = re.compile(r"\s*(percentage points?\b|prozentpunkte?n?\b|pp\b)", re.IGNORECASE)
_P_BEFORE = re.compile(r"\bp(?:[-_ ]?(?:value|wert|adj\w*))?\s*(<=|≤|<|=)\s*$", re.IGNORECASE)

_NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|hundred|thousand|dozen|half|halved|third|thirds|twice|doubled|tripled"
    r"|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwanzig|dreißig|vierzig|fünfzig|sechzig|siebzig|achtzig|neunzig"
    r"|hundert|tausend|dutzend|hälfte|halbiert|drittel|viertel|verdoppelt|verdreifacht|doppelt)\b",
    re.IGNORECASE,
)
_UP = re.compile(
    r"\b(rose|risen|rising|rises|increas\w*|improv\w*|climb\w*|grew|grown|gain\w*"
    r"|gestiegen|steigt|stieg|anstieg|verbessert\w*|zugenommen|zugelegt|erhöht\w*)\b", re.IGNORECASE,
)
_DOWN = re.compile(
    r"\b(fell|fallen|falling|falls|drop\w*|declin\w*|decreas\w*|worsen\w*|slipp?\w*"
    r"|gesunken|sinkt|sank|rückgang|gefallen|verschlechtert\w*|abgenommen|zurückgegangen|rückläufig\w*)\b", re.IGNORECASE,
)
_SIGNIFICANT = re.compile(r"\b(statistically significant|significant\w*|signifikant\w*)\b", re.IGNORECASE)
_NOT_SIGNIFICANT = re.compile(
    r"\b(not|no|without|nicht|keine?\w*|ohne)\s+(?:\w+\s+){0,3}?(statistically\s+)?(significant|signifikant)\w*|\binsignificant\b", re.IGNORECASE
)
_CAUSAL = re.compile(
    r"\b(because|due to|caused by|causes|driven by|as a result of|leads? to|led to|thanks to"
    r"|weil|aufgrund|wegen|verursacht\w*|zurückzuführen|infolge|führt zu|führte zu|dank)\b", re.IGNORECASE,
)


@dataclass
class Token:
    raw: str
    value: Decimal
    decimals: int
    sign: str  # "", "+" or "-"
    pct: bool
    pp: bool
    p_op: str | None
    locale_error: bool = False


def _parse(body: str, lang: str) -> tuple[Decimal, int, bool]:
    decimal_sep, group_sep = (",", ".") if lang == "de" else (".", ",")
    if group_sep in body:
        groups = body.split(decimal_sep)[0].split(group_sep)
        is_grouped = len(groups) > 1 and 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])
        if not is_grouped:
            # 3.82 in German text, or 3,82 in English text
            return Decimal(body.replace(group_sep, ".").replace(decimal_sep, "")), 0, True
        body = body.replace(group_sep, "")
    whole, _, frac = body.partition(decimal_sep)
    return Decimal(f"{whole}.{frac}" if frac else whole), len(frac), False


def _mask_periods(text: str) -> tuple[str, list[str]]:
    bad: list[str] = []

    def replace(m: re.Match) -> str:
        quarter = m.group(1) or m.group(4) or m.group(5)
        year = m.group(2) or m.group(3) or m.group(6)
        if f"Q{quarter}{year}" not in VALID_PERIODS:
            bad.append(m.group(0))
        return " " * len(m.group(0))

    masked = _PERIOD.sub(replace, text)
    return _YEAR.sub(lambda m: " " * len(m.group(0)), masked), bad


def extract_numbers(text: str, lang: str) -> list[Token]:
    masked, _ = _mask_periods(text)
    tokens = []
    for m in _NUMBER.finditer(masked):
        value, decimals, bad = _parse(m.group(2), lang)
        after, before = masked[m.end():], masked[: m.start()]
        p = _P_BEFORE.search(before)
        sign = {"+": "+", "-": "-", "−": "-"}.get(m.group(1), "")
        tokens.append(Token(m.group(0), value, decimals, sign, bool(_PCT_AFTER.match(after)),
                            bool(_PP_AFTER.match(after)), p.group(1) if p else None, bad))
    return tokens


def _canonical(n: Number) -> Decimal:
    return Decimal(repr(round(n.value, 9))).quantize(Decimal(1).scaleb(-n.decimals), rounding=ROUND_HALF_UP)


def matches(token: Token, n: Number) -> bool:
    """Does this written number legitimately quote this figure?"""
    if token.pct and n.unit not in ("pct", "pp"):
        return False
    if token.pp and n.unit not in ("pp", "pct"):
        return False
    if n.unit == "p" and token.p_op is None and token.decimals < MIN_DECIMALS["p"]:
        return False
    canon = _canonical(n)
    if token.sign == "+" and canon < 0 or token.sign == "-" and canon > 0:
        return False
    target = abs(canon)
    if n.unit == "count":
        return token.decimals == 0 and token.value == target
    if token.decimals > n.decimals or token.decimals < MIN_DECIMALS[n.unit]:
        return False
    coarse = target.quantize(Decimal(1).scaleb(-token.decimals), rounding=ROUND_HALF_UP)
    return token.value == coarse


def _p_matches(token: Token, stat: Stat) -> bool:
    for n in stat.numbers():
        if n.unit != "p":
            continue
        if token.p_op == "=" and matches(token, n):
            return True
        if token.p_op in ("<", "<=", "≤"):
            # A threshold form: true when the unrounded canonical p is under the stated bound.
            # A canonical 0.000 means p < 0.0005, so "p < 0.001" holds.
            if Decimal(repr(n.value)) < token.value:
                return True
    return False


def _entities_in(text: str) -> set[str]:
    found = set()
    for entity, aliases in ENTITY_ALIASES.items():
        flags = re.IGNORECASE if entity in CASE_INSENSITIVE_ENTITIES else 0
        if any(re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", text, flags) for a in aliases):
            found.add(entity)
    return found


def validate(claims: list[Claim], stats: dict[str, Stat], lang: str, scope: list[str] | None = None) -> ValidationReport:
    issues: list[Issue] = []
    checked = matched = 0
    in_scope = set(scope or [])

    for i, claim in enumerate(claims):
        def flag(code: str, detail: str, i: int = i) -> None:
            issues.append(Issue(code=code, claim=i, detail=detail))

        if not claim.cites:
            flag("missing_citation", f"No stat cited: {claim.text!r}")
        cited = []
        for sid in claim.cites:
            if sid in stats:
                cited.append(stats[sid])
            else:
                flag("unknown_citation", f"{sid} does not exist")

        _, bad_periods = _mask_periods(claim.text)
        for period in bad_periods:
            flag("unknown_period", f"{period!r} is not in the dataset")
        for word in _NUMBER_WORDS.findall(claim.text):
            flag("spelled_number", f"{word!r} cannot be checked; quantities must be digits")

        for token in extract_numbers(claim.text, lang):
            checked += 1
            if token.locale_error:
                flag("wrong_number_format", f"{token.raw} is not valid in {lang} text")
                continue
            if token.p_op:
                ok = any(_p_matches(token, s) for s in cited)
            else:
                ok = any(matches(token, n) for s in cited for n in s.numbers())
            if ok:
                matched += 1
                continue
            elsewhere = next((s.id for s in stats.values() if s not in cited and any(matches(token, n) for n in s.numbers())), None)
            if elsewhere:
                flag("number_not_in_cited_stat", f"{token.raw} matches {elsewhere}, which is not cited")
            else:
                flag("number_not_found", f"{token.raw} matches no figure on the cited stats")

        deltas = [s for s in cited if s.direction in ("up", "down")]
        if deltas:
            says_up, says_down = bool(_UP.search(claim.text)), bool(_DOWN.search(claim.text))
            if says_up and not says_down and all(s.direction == "down" for s in deltas):
                flag("direction_mismatch", "Text says up, every cited change is down")
            if says_down and not says_up and all(s.direction == "up" for s in deltas):
                flag("direction_mismatch", "Text says down, every cited change is up")

        negated = _NOT_SIGNIFICANT.search(claim.text)
        positive = _SIGNIFICANT.search(_NOT_SIGNIFICANT.sub(" ", claim.text))
        if positive and not any(s.significant is True for s in cited):
            flag("unsupported_significance", "Says significant, no cited test was")
        if negated and not any(s.significant is False for s in cited):
            flag("unsupported_significance", "Says not significant, no cited test supports it")

        known = set(in_scope)
        for s in cited:
            known.update(s.entities)
        for entity in sorted(_entities_in(claim.text) - known):
            flag("entity_not_in_cited_stat", f"Names {entity}, no cited stat covers it")

        if m := _CAUSAL.search(claim.text):
            flag("causal_language", f"{m.group(0)!r} claims a cause the data cannot show")

    return ValidationReport(ok=not issues, claims_checked=len(claims), numbers_checked=checked,
                            numbers_matched=matched, issues=issues)


__all__ = ["ALPHA", "extract_numbers", "matches", "validate"]
