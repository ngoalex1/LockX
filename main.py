"""LockX Stolen Watch Recovery REST API starter.

Run locally after installing requirements:
  uvicorn main:app --reload
"""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="LockX Recovery API", version="0.1.0")


class CaseStatus(str, Enum): monitoring = "monitoring"; paused = "paused"; closed = "closed"
class MatchDecision(str, Enum): reviewing = "reviewing"; dismissed = "dismissed"; escalated = "escalated"

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

def current_owner_id() -> str:
    # Replace with the existing LockX auth dependency (JWT/session), never a
    # client-provided account id.
    return "development-owner"

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "lockx-recovery", "time": datetime.now(timezone.utc)}

@app.post("/api/v1/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate) -> CaseOut:
    case = CaseOut(id=str(uuid4()), status=CaseStatus.monitoring, created_at=datetime.now(timezone.utc), **payload.model_dump())
    _cases[case.id] = case
    return case

@app.get("/api/v1/cases", response_model=list[CaseOut])
def list_cases() -> list[CaseOut]:
    current_owner_id()
    return list(_cases.values())

@app.post("/api/v1/cases/{case_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def request_scan(case_id: str) -> dict:
    if case_id not in _cases: raise HTTPException(404, "Recovery case not found")
    # Enqueue scan_case() with idempotency key and each connector's policy.
    return {"job_id": str(uuid4()), "case_id": case_id, "status": "queued", "access_policy": "approved_sources_only"}

@app.get("/api/v1/cases/{case_id}/matches")
def list_matches(case_id: str) -> list[dict]:
    if case_id not in _cases: raise HTTPException(404, "Recovery case not found")
    return [match for match in _matches.values() if match["case_id"] == case_id]

@app.post("/api/v1/matches/{match_id}/decision")
def decide_match(match_id: str, payload: MatchDecisionIn) -> dict:
    if match_id not in _matches: raise HTTPException(404, "Candidate match not found")
    _matches[match_id]["status"] = payload.decision
    _matches[match_id]["decision_note"] = payload.note
    return _matches[match_id]

@app.get("/api/v1/sources")
def sources() -> list[dict]:
    return [{"key": "official-api-example", "status": "not_configured", "access": "official_api_only"}]
