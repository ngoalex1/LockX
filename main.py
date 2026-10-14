
import os, hashlib, logging
from datetime import datetime, timezone
from uuid import uuid4
import httpx
from fastapi import FastAPI, Header, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
log = logging.getLogger("lockx.supabase")
app.add_middleware(CORSMiddleware, allow_origins=["https://lockx.ai", "https://www.lockx.ai"], allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])

class CaseCreate(BaseModel):
    brand: str
    model: str
    reference: str | None = None
    serial_number: str | None = None
    distinctive_details: str | None = None

class CaseUpdate(BaseModel):
    brand: str
    model: str
    reference: str | None = None
    serial_number: str | None = None
    distinctive_details: str | None = None

def settings():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key: raise HTTPException(503, "Case storage is not configured")
    return url.rstrip("/"), key

def service_headers(key, content_type="application/json"):
    headers = {"apikey": key, "Content-Type": content_type}
    if key.count(".") == 2: headers["Authorization"] = f"Bearer {key}"
    return headers

def supabase_request(method, path, payload=None):
    url, key = settings()
    try:
        headers = service_headers(key); headers["Prefer"] = "return=representation"
        response = httpx.request(method, f"{url}/rest/v1/{path}", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        log.warning("Supabase REST %s %s returned %s: %s", method, path, exc.response.status_code, exc.response.text[:500])
        raise HTTPException(503, "Case storage is temporarily unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Case storage is temporarily unavailable") from exc

def current_user(authorization: str | None = Header(default=None, alias="Authorization")):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Sign in to access recovery cases")
    url, _ = settings()
    public_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_7J4GYdd-XvtT0SJ-gOG0VQ_Py1qXP1o")
    try:
        response = httpx.get(f"{url}/auth/v1/user", headers={"apikey": public_key, "Authorization": authorization}, timeout=10)
        user = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Authentication is temporarily unavailable") from exc
    if not user.get("id"): raise HTTPException(401, "Your session has expired; please sign in again")
    return user["id"]

def serialize_case(row):
    return {"id": row["id"], "case_number": row["case_number"], "brand": row["brand"], "model": row.get("model") or "Unknown model", "reference": row.get("reference_number"), "serial_number": row.get("serial_number"), "distinctive_details": row.get("distinctive_marks"), "status": "paused" if row.get("status") == "paused" else "monitoring", "created_at": row["created_at"]}

def assert_case_owner(case_id, owner_id):
    if not supabase_request("GET", f"watch_cases?id=eq.{case_id}&owner_id=eq.{owner_id}&select=id").json(): raise HTTPException(404, "Recovery case not found")

@app.get("/health")
def health():
    try:
        url, key = settings(); httpx.get(f"{url}/rest/v1/", headers=service_headers(key), timeout=5).raise_for_status(); database = "connected"
    except Exception: database = "unavailable"
    return {"status": "ok" if database == "connected" else "degraded", "database": database, "time": datetime.now(timezone.utc)}

@app.post("/api/v1/cases", status_code=201)
def create_case(case: CaseCreate, owner_id=Depends(current_user)):
    case_id = str(uuid4())
    row = supabase_request("POST", "watch_cases", {"id": case_id, "owner_id": owner_id, "case_number": f"LX-{case_id.replace('-', '')[-8:].upper()}", "brand": case.brand, "model": case.model, "reference_number": case.reference, "serial_number": case.serial_number, "distinctive_marks": case.distinctive_details, "status": "open"}).json()[0]
    return serialize_case(row)

@app.get("/api/v1/cases")
def list_cases(owner_id=Depends(current_user)):
    return [serialize_case(row) for row in supabase_request("GET", f"watch_cases?owner_id=eq.{owner_id}&select=id,case_number,brand,model,reference_number,serial_number,distinctive_marks,status,created_at&order=created_at.desc").json()]

@app.patch("/api/v1/cases/{case_id}")
def update_case(case_id: str, case: CaseUpdate, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    row = supabase_request("PATCH", f"watch_cases?id=eq.{case_id}&owner_id=eq.{owner_id}", {"brand": case.brand, "model": case.model, "reference_number": case.reference, "serial_number": case.serial_number, "distinctive_marks": case.distinctive_details}).json()[0]
    return serialize_case(row)

@app.post("/api/v1/cases/{case_id}/photos", status_code=201)
async def upload_photo(case_id: str, photo: UploadFile = File(...), owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    content_type = (photo.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/heic"}: raise HTTPException(415, "Use a JPG, PNG, or HEIC reference photo")
    content = await photo.read(10485761)
    if not content or len(content) > 10485760: raise HTTPException(413, "Each reference photo must be 10 MB or smaller")
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/heic": "heic"}[content_type]
    photo_id = str(uuid4()); object_path = f"{owner_id}/{case_id}/{photo_id}.{extension}"
    url, key = settings()
    try:
        response = httpx.put(f"{url}/storage/v1/object/case-photos/{object_path}", headers=service_headers(key, content_type), content=content, timeout=30)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning("Supabase Storage upload returned %s: %s", exc.response.status_code, exc.response.text[:500])
        raise HTTPException(503, "Photo storage is temporarily unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Photo storage is temporarily unavailable") from exc
    supabase_request("POST", "case_photos", {"id": photo_id, "case_id": case_id, "storage_path": object_path, "sha256": hashlib.sha256(content).hexdigest(), "image_role": "reference"})
    return {"id": photo_id, "retention": "private_evidence"}

@app.post("/api/v1/cases/{case_id}/scan", status_code=202)
def scan(case_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    return {"job_id": str(uuid4()), "case_id": case_id, "status": "queued", "access_policy": "approved_sources_only"}

@app.get("/api/v1/sources")
def sources(): return [{"key": "official-api-example", "status": "not_configured", "access": "official_api_only"}]


@app.post("/api/v1/cases/{case_id}/delete", status_code=204)
def delete_case(case_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    photos = supabase_request("GET", f"case_photos?case_id=eq.{case_id}&select=storage_path").json()
    paths = [photo["storage_path"] for photo in photos if photo.get("storage_path")]
    if paths:
        url, key = settings()
        try:
            response = httpx.request("DELETE", f"{url}/storage/v1/object/case-photos", headers=service_headers(key), json={"prefixes": paths}, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Photo storage is temporarily unavailable") from exc
    supabase_request("DELETE", f"case_photos?case_id=eq.{case_id}")
    supabase_request("DELETE", f"watch_cases?id=eq.{case_id}&owner_id=eq.{owner_id}")
