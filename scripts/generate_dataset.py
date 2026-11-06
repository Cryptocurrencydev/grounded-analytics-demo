"""Generate the synthetic Quorra Insights employee survey. Seeded, so the output is reproducible.

No real people. Writes two files on purpose:
  data/responses.parquet  numeric answers, demographics, theme id. Deployed with the API.
  data/comments.parquet   raw free text. Never deployed, only used offline by the eval baseline.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261106
QUARTERS = ["2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]
QUARTER_SIZES = [470, 505, 490, 520, 515, 500]  # 3,000 in total
REGIONS, REGION_P = ["North", "South", "East", "West"], [0.31, 0.29, 0.17, 0.23]
DEPTS, DEPT_P = (
    ["Engineering", "Sales", "Operations", "Support", "Finance"],
    [0.27, 0.21, 0.26, 0.18, 0.08],
)
ROLES, ROLE_P = (
    ["Individual contributor", "Team lead", "Manager", "Director"],
    [0.68, 0.18, 0.11, 0.03],
)
QUESTIONS = ["satisfaction", "workload", "leadership", "growth", "recognition", "wellbeing"]
BASE = dict(satisfaction=3.75, workload=3.45, leadership=3.5, growth=3.25, recognition=3.35, wellbeing=3.6)

THEMES = {
    "workload_pressure": [
        "Too many parallel projects, the workload has been heavy since the new year.",
        "We are short staffed and overtime has become normal.",
        "Deadlines keep moving forward while the team stays the same size.",
        "Shift planning leaves no time to recover after peak weeks.",
    ],
    "leadership_comms": [
        "Leadership explains decisions much better than last year.",
        "I would like clearer communication from senior leadership about priorities.",
        "The town halls help, but strategy still feels unclear on the ground.",
        "{name} from leadership actually answered our questions openly.",
    ],
    "career_paths": [
        "There is no visible career path for specialists here.",
        "Promotion criteria are vague and depend on who you know.",
        "I would value a proper development plan and more training budget.",
    ],
    "tools_systems": [
        "The ticketing system is slow and costs us hours each week.",
        "Our internal tools are outdated compared with what customers use.",
        "The new reporting tool saved my team a lot of manual work.",
    ],
    "recognition_pay": [
        "Good work rarely gets noticed outside the immediate team.",
        "Pay has not kept up with the extra responsibility.",
        "My manager {name} makes a point of recognising the team, which helps.",
    ],
    "flexible_work": [
        "Hybrid working is the best thing about this company.",
        "Flexible hours make it possible to balance work and family.",
        "The new office attendance rule feels like a step backwards.",
    ],
    "team_culture": [
        "Colleagues in my team are supportive and honest with each other.",
        "Collaboration across departments has improved a lot.",
        "There is a real sense of trust within the team.",
    ],
}
THEME_P = dict(
    workload_pressure=0.24, leadership_comms=0.17, career_paths=0.16, tools_systems=0.13,
    recognition_pay=0.12, flexible_work=0.10, team_culture=0.08,
)
FICTIONAL_NAMES = ["Mara Lindqvist", "Tobias Ferro", "Ines Okafor", "Jonas Weidmann"]


def effects(q: str, quarter: str, region: str, dept: str, role: str) -> float:
    """Planted signals, so the AI panel has something real to find."""
    i = QUARTERS.index(quarter)
    e = 0.0
    if q == "workload":
        e += {"Operations": -0.25, "Engineering": 0.05, "Finance": 0.2}.get(dept, 0)
        if dept == "Operations" and i >= 3:  # workload slide from 2026-Q1
            e -= 0.2 + 0.14 * (i - 3)
            if region == "South":
                e -= 0.35
    if q == "leadership":
        e += {"Director": 0.55, "Manager": 0.25}.get(role, 0)
        if region == "North" and i >= 2:  # trust climbs in the North from 2025-Q4
            e += 0.12 + 0.1 * (i - 2)
    if q == "growth":
        e += {"Individual contributor": -0.18, "Manager": 0.25, "Director": 0.45}.get(role, 0)
        e += 0.05 * i if dept == "Engineering" else 0
    if q == "recognition":
        e += {"Support": -0.35, "Sales": 0.2}.get(dept, 0)
        if dept == "Support" and i == 5:
            e += 0.35
    if q == "wellbeing":
        if dept == "Operations" and i >= 3:
            e -= 0.14 + 0.06 * (i - 3)
        e += {"West": 0.12, "East": -0.1}.get(region, 0)
    if q == "satisfaction":
        e += {"Sales": 0.1, "Support": -0.14}.get(dept, 0)
        if dept == "Operations" and i >= 3:
            e -= 0.16
    return e


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows, comments = [], []
    rid = 0
    for quarter, size in zip(QUARTERS, QUARTER_SIZES):
        year, qn = int(quarter[:4]), int(quarter[-1])
        start = np.datetime64(f"{year}-{3 * (qn - 1) + 1:02d}-01")
        for _ in range(size):
            rid += 1
            response_id = f"R{rid:05d}"
            region = rng.choice(REGIONS, p=REGION_P)
            dept = rng.choice(DEPTS, p=DEPT_P)
            role = rng.choice(ROLES, p=ROLE_P)
            person = rng.normal(0, 0.55)
            row = dict(
                response_id=response_id, quarter=quarter,
                submitted_on=str(start + int(rng.integers(0, 85))),
                region=str(region), department=str(dept), role=str(role),
            )
            latent = []
            for q in QUESTIONS:
                mu = BASE[q] + effects(q, quarter, region, dept, role) + person
                value = mu + rng.normal(0, 0.72)
                latent.append(value)
                row[f"q_{q}"] = int(np.clip(np.rint(value), 1, 5))
            # eNPS follows the person's mean feeling, with its own noise
            row["nps"] = int(np.clip(np.rint(7.0 + 1.75 * (np.mean(latent) - 3.5) + rng.normal(0, 1.2)), 0, 10))
            row["theme"] = None
            if rng.random() < 0.46:
                p = dict(THEME_P)
                if row["q_workload"] <= 2:
                    p["workload_pressure"] *= 2.6
                if row["q_recognition"] <= 2:
                    p["recognition_pay"] *= 2.2
                if row["q_growth"] <= 2:
                    p["career_paths"] *= 2.0
                keys = list(p)
                probs = np.array([p[k] for k in keys])
                theme = str(rng.choice(keys, p=probs / probs.sum()))
                text = str(rng.choice(THEMES[theme])).format(name=rng.choice(FICTIONAL_NAMES))
                row["theme"] = theme
                comments.append(dict(response_id=response_id, comment=text))
            rows.append(row)
    out = Path(__file__).resolve().parent.parent / "data"
    df = pd.DataFrame(rows)
    df.to_parquet(out / "responses.parquet", index=False)
    pd.DataFrame(comments).to_parquet(out / "comments.parquet", index=False)
    print(len(df), "responses,", len(comments), "comments")
    print(df.groupby("quarter")[[f"q_{q}" for q in QUESTIONS] + ["nps"]].mean().round(2))
    print(df.groupby(["department", "role", "region"]).size().describe().round(1))


if __name__ == "__main__":
    main()
