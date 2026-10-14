
import os, hashlib, logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5
import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from connectors import SearchProfile, configured_connectors, source_catalog
from worker import scan_case

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

def supabase_request(method, path, payload=None, prefer="return=representation"):
    url, key = settings()
    try:
        headers = service_headers(key); headers["Prefer"] = prefer
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

def owned_case_row(case_id, owner_id):
    rows = supabase_request("GET", f"watch_cases?id=eq.{case_id}&owner_id=eq.{owner_id}&select=id,brand,model,reference_number,serial_number,distinctive_marks").json()
    if not rows: raise HTTPException(404, "Recovery case not found")
    return rows[0]

def scan_profile(case_row):
    return SearchProfile(case_id=case_row["id"], brand=case_row["brand"], model=case_row.get("model") or "", reference=case_row.get("reference_number"), serial_number=case_row.get("serial_number"), distinctive_details=case_row.get("distinctive_marks"))

def serialize_scan(row):
    return {"id": row["id"], "case_id": row["case_id"], "status": row["status"], "configured_sources": row.get("configured_sources") or [], "summary": row.get("summary") or {}, "requested_at": row.get("requested_at"), "started_at": row.get("started_at"), "completed_at": row.get("completed_at")}

async def process_scan_job(job_id, owner_id, profile):
    """Run only configured official connectors and preserve normalized evidence."""
    try:
        supabase_request("PATCH", f"marketplace_scan_jobs?id=eq.{job_id}", {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
        findings = await scan_case(profile, configured_connectors())
        for finding in findings:
            listing = finding["listing"]
            payload = {
                "id": str(uuid5(NAMESPACE_URL, f"lockx:{profile.case_id}:{finding['connector_key']}:{listing.external_id}")), "owner_id": owner_id, "case_id": profile.case_id, "scan_job_id": job_id,
                "connector_key": finding["connector_key"], "external_id": listing.external_id, "listing_url": listing.url,
                "title": listing.title, "description": listing.description, "price": listing.price, "currency": listing.currency,
                "location": listing.location, "listing_image_urls": listing.image_urls, "raw_listing": listing.raw,
                "text_score": finding["confidence"], "image_score": finding["image_score"], "confidence": finding["confidence"],
                "visual_status": finding["visual_status"], "match_reasons": finding["text_reasons"],
                "evidence_sha256": finding["evidence_sha256"], "evidence_captured_at": finding["found_at"],
            }
            supabase_request("POST", "marketplace_candidates?on_conflict=case_id,connector_key,external_id", payload, "resolution=merge-duplicates,return=representation")
        supabase_request("PATCH", f"marketplace_scan_jobs?id=eq.{job_id}", {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat(), "summary": {"findings": len(findings), "visual_matching": "not_run_without_explicit_owner_consent"}})
    except Exception as exc:
        log.exception("Marketplace scan %s failed", job_id)
        try: supabase_request("PATCH", f"marketplace_scan_jobs?id=eq.{job_id}", {"status": "failed", "completed_at": datetime.now(timezone.utc).isoformat(), "summary": {"error": "connector_request_failed"}})
        except Exception: log.exception("Could not update failed scan %s", job_id)

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
def scan(case_id: str, background_tasks: BackgroundTasks, owner_id=Depends(current_user)):
    case_row = owned_case_row(case_id, owner_id)
    connectors = configured_connectors()
    job_id = str(uuid4())
    source_keys = [connector.key for connector in connectors]
    status = "queued" if source_keys else "waiting_for_source_access"
    row = supabase_request("POST", "marketplace_scan_jobs", {"id": job_id, "owner_id": owner_id, "case_id": case_id, "status": status, "configured_sources": source_keys, "summary": {"policy": "official_api_or_authorized_feed_only", "owner_photo_sharing": "not_started_without_explicit_consent"}}).json()[0]
    if connectors: background_tasks.add_task(process_scan_job, job_id, owner_id, scan_profile(case_row))
    return serialize_scan(row)

@app.get("/api/v1/sources")
def sources(): return source_catalog()

@app.get("/api/v1/cases/{case_id}/scans")
def case_scans(case_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    rows = supabase_request("GET", f"marketplace_scan_jobs?case_id=eq.{case_id}&owner_id=eq.{owner_id}&select=*&order=requested_at.desc").json()
    return [serialize_scan(row) for row in rows]

@app.get("/api/v1/matches")
def matches(owner_id=Depends(current_user)):
    rows = supabase_request("GET", f"marketplace_candidates?owner_id=eq.{owner_id}&select=id,case_id,connector_key,listing_url,title,price,currency,location,listing_image_urls,confidence,visual_status,match_reasons,status,evidence_sha256,evidence_captured_at,created_at&order=created_at.desc").json()
    return rows


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


@app.get("/api/v1/cases/{case_id}/photos")
def list_case_photos(case_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    photos = supabase_request("GET", f"case_photos?case_id=eq.{case_id}&select=id,storage_path,created_at&order=created_at.asc").json()
    url, key = settings()
    results = []
    for photo in photos:
        try:
            response = httpx.post(f"{url}/storage/v1/object/sign/case-photos/{photo['storage_path']}", headers=service_headers(key), json={"expiresIn": 3600}, timeout=30)
            response.raise_for_status()
            signed_url = response.json().get("signedURL")
            if signed_url:
                results.append({"id": photo["id"], "url": signed_url if signed_url.startswith("http") else f"{url}/storage/v1{signed_url}", "created_at": photo.get("created_at")})
        except httpx.HTTPError as exc:
            log.warning("Supabase Storage sign request failed: %s", exc)
    return results


@app.post("/api/v1/cases/{case_id}/photos/{photo_id}/delete", status_code=204)
def delete_photo(case_id: str, photo_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    photos = supabase_request("GET", f"case_photos?id=eq.{photo_id}&case_id=eq.{case_id}&select=id,storage_path").json()
    if not photos: raise HTTPException(404, "Reference photo not found")
    object_path = photos[0].get("storage_path")
    if object_path:
        url, key = settings()
        try:
            response = httpx.request("DELETE", f"{url}/storage/v1/object/case-photos", headers=service_headers(key), json={"prefixes": [object_path]}, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Photo storage is temporarily unavailable") from exc
    supabase_request("DELETE", f"case_photos?id=eq.{photo_id}&case_id=eq.{case_id}")
