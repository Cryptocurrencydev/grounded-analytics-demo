"""HTTP API. Runs as a Vercel Python function and under uvicorn locally."""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import applications, chat, dashboard
from .catalog import Filters
from .interpret import interpret
from .llm import get_llm
from .models import Claim  # noqa: F401 - keeps the schema in the OpenAPI document

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Quorra Insights grounded analytics", docs_url=None, redoc_url=None, openapi_url=None)


class FilterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: Filters = Filters()


class InterpretBody(FilterBody):
    lang: Literal["en", "de"] = "en"


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    filters: Filters = Filters()
    lang: Literal["en", "de"] = "en"
    history: list[chat.Turn] = Field(default_factory=list, max_length=12)


class SummaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lang: Literal["en", "de"] = "en"


def client_id(request: Request) -> str:
    """Hashed client address: enough to rate-limit, not stored in the clear."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    salt = os.environ.get("PSEUDONYM_SALT", "local-dev-salt")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]


@app.exception_handler(Exception)
async def on_error(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("grounded").exception("unhandled", exc_info=exc)
    return JSONResponse({"detail": "Something went wrong on the server."}, status_code=500)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "model": get_llm().name}


@app.get("/api/meta")
def meta() -> dict:
    return dashboard.meta()


@app.post("/api/dashboard")
def dashboard_data(body: FilterBody) -> dict:
    return dashboard.build(body.filters)


@app.post("/api/interpret")
def interpret_route(body: InterpretBody, request: Request) -> dict:
    return interpret(body.filters, body.lang, client_id(request)).model_dump(mode="json")


@app.post("/api/chat")
def chat_route(body: ChatBody, request: Request) -> dict:
    return chat.answer(body.question, body.filters, body.lang, body.history, client_id(request)).model_dump(mode="json")


@app.get("/api/applications")
def list_applications() -> list[dict]:
    out = []
    for a in applications.load():
        f = a["fields"]
        out.append({
            "id": a["id"], "programme": a["programme"], "submitted_on": a["submitted_on"],
            "organisation": f["organisation"], "project_title": f["project_title"],
            "missing": len(applications.missing_fields(a)),
        })
    return out


@app.get("/api/applications/{app_id}")
def application_detail(app_id: str) -> dict:
    a = applications.get(app_id)
    if not a:
        raise HTTPException(404, "Unknown application")
    fields = [
        {"key": k, "label": applications.FIELD_LABELS[k], "value": v, "pii": k in applications.PII_FIELDS,
         "missing": k in applications.missing_fields(a)}
        for k, v in a["fields"].items()
    ]
    return {"id": a["id"], "programme": a["programme"], "submitted_on": a["submitted_on"], "fields": fields}


@app.post("/api/applications/{app_id}/summary")
def application_summary(app_id: str, body: SummaryBody, request: Request) -> dict:
    a = applications.get(app_id)
    if not a:
        raise HTTPException(404, "Unknown application")
    return applications.summarise(a, body.lang, client_id(request)).model_dump(mode="json")
