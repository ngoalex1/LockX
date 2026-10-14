"""LockX Recovery API — authenticated, owner-scoped case management."""
import os
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="LockX Recovery API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["https://lockx.ai", "https://www.lockx.ai"], allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])

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
    case_number: str
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

_matches: dict[str, dict] = {}

def settings() -> tuple[str, str]:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(503, "Case storage is not configured")
    return url.rstrip("/"), key

def supabase_request(method: str, path: str, payload: dict | None = None) -> httpx.Response:
    url, key = settings()
    try:
        response = httpx.request(method, f"{url}/rest/v1/{path.lstrip('/')}", headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=representation"}, json=payload, timeout=10.0)
        response.raise_for_status()
        return response
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Case storage is temporarily unavailable") from exc

def current_user_id(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to access recovery cases")
    url, key = settings()
    try:
        response = httpx.get(f"{url}/auth/v1/user", headers={"apikey": key, "Authorization": authorization}, timeout=10.0)
        user = response.json() if response.status_code == 200 else {}
        if not user.get("id"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired; please sign in again")
        return user["id"]
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Authentication is temporarily unavailable") from exc

def serialize_case(row: dict) -> CaseOut:
    return CaseOut(id=row["id"], case_number=row["case_number"], brand=row["brand"], model=row.get("model") or "Unknown model", reference=row.get("reference_number"), serial_number=row.get("serial_number"), distinctive_details=row.get("distinctive_marks") or row.get("description"), status=CaseStatus.paused if row.get("status") == "paused" else CaseStatus.monitoring, created_at=row["created_at"])

def supabase_status() -> str:
    try:
        url, key = settings()
        response = httpx.get(f"{url}/rest/v1/", headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=5.0)
        response.raise_for_status()
        return "connected"
    except HTTPException:
        return "not_configured"
    except httpx.HTTPError:
        return "unavailable"

@app.get("/health")
def health() -> dict:
    database = supabase_status()
    return {"status": "ok" if database != "unavailable" else "degraded", "service": "lockx-recovery", "database": database, "time": datetime.now(timezone.utc)}

@app.post("/api/v1/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, owner_id: str = Depends(current_user_id)) -> CaseOut:
    case_id = str(uuid4())
    response = supabase_request("POST", "watch_cases", {"id": case_id, "owner_id": owner_id, "case_number": f"LX-{case_id.replace('-', '')[-8:].upper()}", "brand": payload.brand, "model": payload.model, "reference_number": payload.reference, "serial_number": payload.serial_number, "distinctive_marks": payload.distinctive_details, "status": "open"})
    return serialize_case(response.json()[0])

@app.get("/api/v1/cases", response_model=list[CaseOut])
def list_cases(owner_id: str = Depends(current_user_id)) -> list[CaseOut]:
    response = supabase_request("GET", "watch_cases?owner_id=eq." + owner_id + "&select=id,case_number,brand,model,reference_number,serial_number,distinctive_marks,status,created_at&order=created_at.desc")
    return [serialize_case(row) for row in response.json()]

@app.post("/api/v1/cases/{case_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def request_scan(case_id: str, owner_id: str = Depends(current_user_id)) -> dict:
    return {"job_id": str(uuid4()), "case_id": case_id, "status": "queued", "access_policy": "approved_sources_only"}

@app.get("/api/v1/cases/{case_id}/matches")
def list_matches(case_id: str, owner_id: str = Depends(current_user_id)) -> list[dict]:
    return [match for match in _matches.values() if match["case_id"] == case_id and match.get("owner_id") == owner_id]

@app.post("/api/v1/matches/{match_id}/decision")
def decide_match(match_id: str, payload: MatchDecisionIn, owner_id: str = Depends(current_user_id)) -> dict:
    if match_id not in _matches or _matches[match_id].get("owner_id") != owner_id:
        raise HTTPException(404, "Candidate match not found")
    _matches[match_id].update(status=payload.decision, decision_note=payload.note)
    return _matches[match_id]

@app.get("/api/v1/sources")
def sources() -> list[dict]:
    return [{"key": "official-api-example", "status": "not_configured", "access": "official_api_only"}]
