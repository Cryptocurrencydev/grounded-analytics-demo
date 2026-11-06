"""The whitelist. Every dimension, measure and label the system may use is declared here."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

MIN_N_INTERPRET = 30  # below this the AI refuses to interpret
SMALL_SAMPLE_WARN = 50  # interpret, but warn
MIN_SEGMENT_N = 30  # a segment below this is never compared
MIN_CELL_N = 5  # a cell below this is hidden from the API entirely
ALPHA = 0.05

QUARTERS = ["2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]
YEARS = {"2025": ["2025-Q2", "2025-Q3", "2025-Q4"], "2026": ["2026-Q1", "2026-Q2", "2026-Q3"]}

Lang = Literal["en", "de"]
Period = Literal["all", "2025", "2026", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]
Region = Literal["all", "North", "South", "East", "West"]
Department = Literal["all", "Engineering", "Sales", "Operations", "Support", "Finance"]
Role = Literal["all", "Individual contributor", "Team lead", "Manager", "Director"]

REGIONS = list(get_args(Region))[1:]
DEPARTMENTS = list(get_args(Department))[1:]
ROLES = list(get_args(Role))[1:]
DIMENSIONS = {"region": REGIONS, "department": DEPARTMENTS, "role": ROLES}

QUESTIONS: dict[str, dict[str, str]] = {
    "satisfaction": {"en": "Overall satisfaction", "de": "Gesamtzufriedenheit"},
    "workload": {"en": "Manageable workload", "de": "Bewältigbare Arbeitsbelastung"},
    "leadership": {"en": "Trust in leadership", "de": "Vertrauen in die Führung"},
    "growth": {"en": "Career growth", "de": "Karriereentwicklung"},
    "recognition": {"en": "Recognition", "de": "Anerkennung"},
    "wellbeing": {"en": "Wellbeing", "de": "Wohlbefinden"},
}
QUESTION_STATEMENTS = {
    "satisfaction": "Overall, I am satisfied with working here.",
    "workload": "My workload is manageable.",
    "leadership": "I trust the decisions of senior leadership.",
    "growth": "I can see a future for my career here.",
    "recognition": "Good work is recognised here.",
    "wellbeing": "I feel well at work.",
}
LIKERT = {
    "en": ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"],
    "de": ["Stimme gar nicht zu", "Stimme nicht zu", "Neutral", "Stimme zu", "Stimme voll zu"],
}
THEMES = {
    "workload_pressure": {"en": "Workload pressure", "de": "Arbeitsdruck"},
    "leadership_comms": {"en": "Leadership communication", "de": "Kommunikation der Führung"},
    "career_paths": {"en": "Career paths", "de": "Karrierewege"},
    "tools_systems": {"en": "Tools and systems", "de": "Tools und Systeme"},
    "recognition_pay": {"en": "Recognition and pay", "de": "Anerkennung und Vergütung"},
    "flexible_work": {"en": "Flexible work", "de": "Flexibles Arbeiten"},
    "team_culture": {"en": "Team culture", "de": "Teamkultur"},
}
LABELS_DE = {
    "North": "Nord", "South": "Süd", "East": "Ost", "West": "West",
    "Engineering": "Entwicklung", "Sales": "Vertrieb", "Operations": "Betrieb",
    "Support": "Kundenservice", "Finance": "Finanzen",
    "Individual contributor": "Fachkräfte", "Team lead": "Teamleitung",
    "Manager": "Management", "Director": "Direktion",
    "region": "Region", "department": "Abteilung", "role": "Rolle",
}


def tr(value: str, lang: str) -> str:
    return LABELS_DE.get(value, value) if lang == "de" else value


def quarter_label(q: str) -> str:
    """'2026-Q1' -> 'Q1 2026'."""
    return f"{q[-2:]} {q[:4]}"


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: Period = "all"
    region: Region = "all"
    department: Department = "all"
    role: Role = "all"

    def canonical(self) -> str:
        return f"{self.period}|{self.region}|{self.department}|{self.role}"

    def quarters(self) -> list[str]:
        if self.period == "all":
            return list(QUARTERS)
        return YEARS.get(self.period, [self.period])

    def scope_label(self, lang: str) -> str:
        parts = []
        if self.period == "all":
            parts.append("alle 6 Quartale" if lang == "de" else "all 6 quarters")
        elif self.period in YEARS:
            parts.append(self.period)
        else:
            parts.append(quarter_label(self.period))
        for v in (self.region, self.department, self.role):
            if v != "all":
                parts.append(tr(v, lang))
        return " · ".join(parts)


def comparison_windows(f: Filters) -> tuple[list[str], list[str], str] | None:
    """(current window, previous window, label) for the change-over-time stats.

    A quarter compares to the quarter before. 2026 (Q1-Q3) compares to 2025 (Q2-Q4), the same
    length. With all quarters selected, the latest quarter compares to the one before it.
    """
    if f.period == "all":
        return [QUARTERS[-1]], [QUARTERS[-2]], f"{quarter_label(QUARTERS[-1])} vs {quarter_label(QUARTERS[-2])}"
    if f.period == "2026":
        return YEARS["2026"], YEARS["2025"], "2026 vs 2025"
    if f.period == "2025":
        return None
    i = QUARTERS.index(f.period)
    if i == 0:
        return None
    return [f.period], [QUARTERS[i - 1]], f"{quarter_label(f.period)} vs {quarter_label(QUARTERS[i - 1])}"


# Names the validator looks for in a claim. A claim naming one needs a cited stat about it.
ENTITY_ALIASES: dict[str, list[str]] = {
    "North": ["North", "Northern", "Nord", "Norden"],
    "South": ["South", "Southern", "Süd", "Süden"],
    "East": ["East", "Eastern", "Ost", "Osten"],
    "West": ["West", "Western", "Westen"],
    "Engineering": ["Engineering", "Entwicklung"],
    "Sales": ["Sales", "Vertrieb"],
    "Operations": ["Operations", "Betrieb"],
    "Support": ["Support", "Kundenservice"],
    "Finance": ["Finance", "Finanzen"],
    "Individual contributor": ["Individual contributors", "Individual contributor", "Fachkräfte", "Fachkräften"],
    "Team lead": ["Team leads", "Team lead", "Teamleitung", "Teamleitungen"],
    "Manager": ["Managers", "Manager", "Management"],
    "Director": ["Directors", "Director", "Direktion"],
    "q:workload": ["workload", "Arbeitsbelastung"],
    "q:leadership": ["leadership", "Führung"],
    "q:growth": ["career growth", "Karriereentwicklung"],
    "q:recognition": ["recognition", "Anerkennung"],
    "q:wellbeing": ["wellbeing", "Wohlbefinden"],
    "q:satisfaction": ["satisfaction", "Zufriedenheit", "Gesamtzufriedenheit"],
}
CASE_INSENSITIVE_ENTITIES = {k for k in ENTITY_ALIASES if k.startswith("q:")}
