"""Shapes shared by the stat sheet, the validator and the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Unit = Literal["scale", "scale_delta", "pct", "pp", "nps", "nps_delta", "count", "p"]


class Number(BaseModel):
    """A figure a claim may quote: the rounded canonical value and how it may be written."""
    name: str
    value: float
    unit: Unit
    decimals: int


class ChartRef(BaseModel):
    chart: Literal["trend", "distribution", "segments", "nps", "themes"]
    series: str | None = None
    categories: list[str] = Field(default_factory=list)
    dimension: str | None = None
    question: str | None = None


class Stat(BaseModel):
    id: str
    key: str
    kind: str
    label: str
    value: float
    unit: Unit
    decimals: int
    n: int
    related: list[Number] = Field(default_factory=list)
    direction: Literal["up", "down", "flat"] | None = None
    significant: bool | None = None
    test: str | None = None
    refs: list[str] = Field(default_factory=list)  # pseudonymised response ids, themes only
    entities: list[str] = Field(default_factory=list)
    chart: ChartRef | None = None

    def numbers(self) -> list[Number]:
        out = [Number(name="value", value=self.value, unit=self.unit, decimals=self.decimals)]
        out.append(Number(name="n", value=self.n, unit="count", decimals=0))
        return out + self.related

    def for_llm(self) -> dict:
        """What the model sees for this stat. Entities and chart routing stay on the server."""
        d: dict = {"id": self.id, "label": self.label, "value": self.value, "unit": self.unit, "n": self.n}
        for r in self.related:
            d[r.name] = r.value
        if self.direction:
            d["direction"] = self.direction
        if self.significant is not None:
            d["significant"] = self.significant
        if self.test:
            d["test"] = self.test
        if self.refs:
            d["pseudonymous_refs"] = self.refs
        return d


class Claim(BaseModel):
    text: str
    cites: list[str]


class Issue(BaseModel):
    code: str
    claim: int
    detail: str


class ValidationReport(BaseModel):
    ok: bool
    claims_checked: int
    numbers_checked: int
    numbers_matched: int
    issues: list[Issue] = Field(default_factory=list)
