
"""LockX Stolen Watch Recovery REST API starter."""
import os
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="LockX Recovery API", version="0.2.0")

class CaseStatus(str, Enum):
    monitoring = "monitoring"
    paused = "paused"
    closed = "closed"

class MatchDecision(str, Enum):
    reviewing = "reviewing"
    dismissed = "dismissed"
    escalated = "escalated"

class CaseCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    reference: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    distinctive_details: str | None = Field(default=None, max_length=5000)

class CaseOut(CaseCreate):
    id: str
    status: CaseStatus
    created_at: datetime

class MatchDecisionIn(BaseModel):
    decision: MatchDecision
    note: str | None = Field(default=None, max_length=2000)

class EvidenceOut(BaseModel):
    id: str
    candidate_id: str
    source_url: HttpUrl
    sha256: str
    captured_at: datetime
    retention: str = "immutable"

_cases: dict[str, CaseOut] = {}
_matches: dict[str, dict] = {}

def supabase_status() -> str:
    """Verify Railway can reach Supabase without exposing server credentials."""
    project_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not project_url or not service_key:
        return "not_configured"
    try:
        response = httpx.get(
            f"{project_url.rstrip('/')}/rest/v1/watch_cases?select=id&limit=1",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return "unavailable"
    return "connected"

@app.get("/health")
def health() -> dict:
    database = supabase_status()
    return {"status": "ok" if database != "unavailable" else "degraded", "service": "lockx-recovery", "database": database, "time": datetime.now(timezone.utc)}

@app.post("/api/v1/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate) -> CaseOut:
    case = CaseOut(id=str(uuid4()), status=CaseStatus.monitoring, created_at=datetime.now(timezone.utc), **payload.model_dump())
    _cases[case.id] = case
    return case

@app.get("/api/v1/cases", response_model=list[CaseOut])
def list_cases() -> list[CaseOut]:
    return list(_cases.values())

@app.post("/api/v1/cases/{case_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def request_scan(case_id: str) -> dict:
    if case_id not in _cases:
        raise HTTPException(404, "Recovery case not found")
    return {"job_id": str(uuid4()), "case_id": case_id, "status": "queued", "access_policy": "approved_sources_only"}

@app.get("/api/v1/cases/{case_id}/matches")
def list_matches(case_id: str) -> list[dict]:
    if case_id not in _cases:
        raise HTTPException(404, "Recovery case not found")
    return [match for match in _matches.values() if match["case_id"] == case_id]

@app.post("/api/v1/matches/{match_id}/decision")
def decide_match(match_id: str, payload: MatchDecisionIn) -> dict:
    if match_id not in _matches:
        raise HTTPException(404, "Candidate match not found")
    _matches[match_id]["status"] = payload.decision
    _matches[match_id]["decision_note"] = payload.note
    return _matches[match_id]

@app.get("/api/v1/sources")
def sources() -> list[dict]:
    return [{"key": "official-api-example", "status": "not_configured", "access": "official_api_only"}]
