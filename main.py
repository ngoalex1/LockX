from __future__ import annotations

import os, hashlib, logging
from datetime import date, datetime, timezone
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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

class VaultItemCreate(BaseModel):
    category: str
    item_name: str
    brand: str | None = None
    model: str | None = None
    reference_number: str | None = None
    serial_number: str | None = None
    description: str | None = None
    distinctive_details: str | None = None
    purchase_date: date | None = None
    estimated_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

class VaultItemUpdate(BaseModel):
    category: str | None = None
    item_name: str | None = None
    brand: str | None = None
    model: str | None = None
    reference_number: str | None = None
    serial_number: str | None = None
    description: str | None = None
    distinctive_details: str | None = None
    purchase_date: date | None = None
    estimated_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: str | None = None

class VaultRecoveryRequest(BaseModel):
    status: str
    note: str | None = None

class VaultTransferCreate(BaseModel):
    recipient_email: str
    sharing_level: str = "full"
    handover_note: str | None = None

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

def authenticated_identity(authorization: str | None = Header(default=None, alias="Authorization")):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Sign in to access recovery cases")
    url, _ = settings()
    public_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_7J4GYdd-XvtT0SJ-gOG0VQ_Py1qXP1o")
    try:
        response = httpx.get(f"{url}/auth/v1/user", headers={"apikey": public_key, "Authorization": authorization}, timeout=10)
        user = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Authentication is temporarily unavailable") from exc
    if not user.get("id"): raise HTTPException(401, "Your session has expired; please sign in again")
    return user

def current_user(authorization: str | None = Header(default=None, alias="Authorization")):
    return authenticated_identity(authorization)["id"]

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
    snapshots = supabase_request("GET", f"vault_recovery_photos?case_id=eq.{case_id}&select=storage_path").json()
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
    for snapshot in snapshots:
        cleanup_vault_file(snapshot["storage_path"])


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
    snapshots = supabase_request("GET", f"vault_recovery_photos?case_id=eq.{case_id}&select=id,storage_path,created_at&order=created_at.asc").json()
    for photo in snapshots:
        signed_url = signed_storage_url("vault-files", photo["storage_path"])
        if signed_url:
            results.append({"id": photo["id"], "url": signed_url, "created_at": photo.get("created_at"), "source": "vault_snapshot"})
    return results


@app.post("/api/v1/cases/{case_id}/photos/{photo_id}/delete", status_code=204)
def delete_photo(case_id: str, photo_id: str, owner_id=Depends(current_user)):
    assert_case_owner(case_id, owner_id)
    photos = supabase_request("GET", f"case_photos?id=eq.{photo_id}&case_id=eq.{case_id}&select=id,storage_path").json()
    if not photos:
        snapshots = supabase_request("GET", f"vault_recovery_photos?id=eq.{photo_id}&case_id=eq.{case_id}&select=storage_path").json()
        if not snapshots:
            raise HTTPException(404, "Reference photo not found")
        supabase_request("DELETE", f"vault_recovery_photos?id=eq.{photo_id}&case_id=eq.{case_id}")
        cleanup_vault_file(snapshots[0]["storage_path"])
        return
    object_path = photos[0].get("storage_path")
    if object_path:
        url, key = settings()
        try:
            response = httpx.request("DELETE", f"{url}/storage/v1/object/case-photos", headers=service_headers(key), json={"prefixes": [object_path]}, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Photo storage is temporarily unavailable") from exc
    supabase_request("DELETE", f"case_photos?id=eq.{photo_id}&case_id=eq.{case_id}")


# Digital Vault -------------------------------------------------------------

VAULT_CATEGORIES = {"watch", "jewellery", "handbag"}
VAULT_STATUSES = {"protected", "missing", "stolen", "recovered", "archived", "pending_transfer"}
VAULT_PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/heic": "heic"}
VAULT_DOCUMENT_TYPES = {**VAULT_PHOTO_TYPES, "application/pdf": "pdf"}


def serialize_vault_item(row):
    return {
        "id": row["id"], "category": row["category"], "item_name": row["item_name"],
        "brand": row.get("brand"), "model": row.get("model"), "reference_number": row.get("reference_number"),
        "serial_number": row.get("serial_number"), "description": row.get("description"),
        "distinctive_details": row.get("distinctive_details"), "purchase_date": row.get("purchase_date"),
        "estimated_value": row.get("estimated_value"), "currency": row.get("currency") or "USD",
        "status": row.get("status") or "protected", "recovery_case_id": row.get("recovery_case_id"),
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
    }


def owned_vault_item(item_id, owner_id):
    validate_vault_id(item_id)
    rows = supabase_request("GET", f"vault_items?id=eq.{item_id}&owner_id=eq.{owner_id}&select=*").json()
    if not rows:
        raise HTTPException(404, "Vault item not found")
    return rows[0]


def validate_vault_id(value):
    try:
        UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid vault identifier") from exc


def vault_mutate(action, owner_id, item_id, payload=None, email=None, transfer_id=None):
    validate_vault_id(item_id)
    if transfer_id:
        validate_vault_id(transfer_id)
    result = supabase_request("POST", "rpc/vault_mutate", {
        "p_action": action, "p_actor": owner_id, "p_item": item_id,
        "p_payload": payload or {}, "p_email": email, "p_transfer": transfer_id,
    }).json()
    if result.get("error"):
        raise HTTPException(result["error"], result["message"])
    return result


def cleanup_vault_file(object_path):
    """Remove unreferenced bytes; recovery snapshots may retain the original evidence."""
    for table in ("vault_item_photos", "vault_documents", "vault_recovery_photos"):
        if supabase_request("GET", f"{table}?storage_path=eq.{quote(object_path, safe='')}&select=id").json():
            return
    url, key = settings()
    try:
        response = httpx.request("DELETE", f"{url}/storage/v1/object/vault-files",
                                headers=service_headers(key), json={"prefixes": [object_path]}, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError:
        # The private object is inaccessible through the app after its record is removed.
        log.exception("Unreferenced vault file needs storage cleanup")


def vault_event(item_id, event_type, event_data=None):
    supabase_request("POST", "vault_events", {
        "id": str(uuid4()), "item_id": item_id, "event_type": event_type,
        "event_data": event_data or {}, "occurred_at": datetime.now(timezone.utc).isoformat(),
    })


def signed_storage_url(bucket, object_path):
    url, key = settings()
    try:
        response = httpx.post(
            f"{url}/storage/v1/object/sign/{bucket}/{object_path}",
            headers=service_headers(key), json={"expiresIn": 3600}, timeout=30,
        )
        response.raise_for_status()
        signed_url = response.json().get("signedURL")
        if not signed_url:
            raise HTTPException(503, "Vault file preview is temporarily unavailable")
        return signed_url if signed_url.startswith("http") else f"{url}/storage/v1{signed_url}"
    except httpx.HTTPError as exc:
        log.warning("Supabase Storage sign request failed: %s", exc)
        raise HTTPException(503, "Vault file preview is temporarily unavailable") from exc


def vault_upload(bucket, object_path, content, content_type):
    url, key = settings()
    try:
        response = httpx.put(
            f"{url}/storage/v1/object/{bucket}/{object_path}",
            headers=service_headers(key, content_type), content=content, timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning("Vault Storage upload returned %s: %s", exc.response.status_code, exc.response.text[:500])
        raise HTTPException(503, "Vault file storage is temporarily unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Vault file storage is temporarily unavailable") from exc


@app.get("/api/v1/vault/items")
def list_vault_items(owner_id=Depends(current_user)):
    pending = supabase_request("GET", f"vault_items?owner_id=eq.{owner_id}&status=eq.pending_transfer&select=id").json()
    for item in pending:
        vault_mutate("expire", owner_id, item["id"])
    rows = supabase_request("GET", f"vault_items?owner_id=eq.{owner_id}&select=*&order=updated_at.desc").json()
    return [serialize_vault_item(row) for row in rows]


@app.post("/api/v1/vault/items", status_code=201)
def create_vault_item(item: VaultItemCreate, owner_id=Depends(current_user)):
    if item.category not in VAULT_CATEGORIES:
        raise HTTPException(422, "Choose watch, jewellery, or handbag")
    if not item.item_name.strip():
        raise HTTPException(422, "Item name is required")
    item_id = str(uuid4())
    row = vault_mutate("create", owner_id, item_id, item.model_dump(mode="json"))
    return serialize_vault_item(row)


@app.patch("/api/v1/vault/items/{item_id}")
def update_vault_item(item_id: str, item: VaultItemUpdate, owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    if item.category is not None and item.category not in VAULT_CATEGORIES:
        raise HTTPException(422, "Choose watch, jewellery, or handbag")
    if item.item_name is not None and not item.item_name.strip():
        raise HTTPException(422, "Item name is required")
    if item.status and item.status not in {"protected", "recovered", "archived"}:
        raise HTTPException(422, "Invalid vault status")
    payload = item.model_dump(mode="json", exclude_unset=True)
    if any(payload.get(field) is None for field in ("category", "item_name", "status", "currency") if field in payload):
        raise HTTPException(422, "Category, name, currency and status cannot be empty")
    row = vault_mutate("update", owner_id, item_id, payload)
    return serialize_vault_item(row)


@app.get("/api/v1/vault/items/{item_id}/photos")
def list_vault_photos(item_id: str, owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    rows = supabase_request("GET", f"vault_item_photos?item_id=eq.{item_id}&select=id,storage_path,created_at&order=created_at.asc").json()
    results = []
    for row in rows:
        url = signed_storage_url("vault-files", row["storage_path"])
        if url:
            results.append({"id": row["id"], "url": url, "created_at": row.get("created_at")})
    return results


@app.post("/api/v1/vault/items/{item_id}/photos", status_code=201)
async def upload_vault_photo(item_id: str, photo: UploadFile = File(...), owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    existing = supabase_request("GET", f"vault_item_photos?item_id=eq.{item_id}&select=id").json()
    if len(existing) >= 20:
        raise HTTPException(409, "Each vault item can have up to 20 photos")
    content_type = (photo.content_type or "").lower()
    if content_type not in VAULT_PHOTO_TYPES:
        raise HTTPException(415, "Use a JPG, PNG, or HEIC item photo")
    content = await photo.read(10485761)
    if not content or len(content) > 10485760:
        raise HTTPException(413, "Each vault photo must be 10 MB or smaller")
    photo_id = str(uuid4())
    object_path = f"vault/{owner_id}/{item_id}/photos/{photo_id}.{VAULT_PHOTO_TYPES[content_type]}"
    vault_upload("vault-files", object_path, content, content_type)
    try:
        vault_mutate("photo_add", owner_id, item_id, {"id": photo_id, "storage_path": object_path, "sha256": hashlib.sha256(content).hexdigest()})
    except HTTPException:
        cleanup_vault_file(object_path)
        raise
    return {"id": photo_id, "retention": "private_vault_evidence"}


@app.post("/api/v1/vault/items/{item_id}/photos/{photo_id}/delete", status_code=204)
def delete_vault_photo(item_id: str, photo_id: str, owner_id=Depends(current_user)):
    validate_vault_id(photo_id)
    result = vault_mutate("photo_delete", owner_id, item_id, {"id": photo_id})
    cleanup_vault_file(result["storage_path"])


@app.get("/api/v1/vault/items/{item_id}/documents")
def list_vault_documents(item_id: str, owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    rows = supabase_request("GET", f"vault_documents?item_id=eq.{item_id}&select=*&order=created_at.asc").json()
    return [{"id": row["id"], "file_name": row["file_name"], "document_type": row["document_type"], "transferable": row["transferable"], "url": signed_storage_url("vault-files", row["storage_path"]), "created_at": row.get("created_at")} for row in rows]


@app.post("/api/v1/vault/items/{item_id}/documents", status_code=201)
async def upload_vault_document(item_id: str, document: UploadFile = File(...), owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    content_type = (document.content_type or "").lower()
    if content_type not in VAULT_DOCUMENT_TYPES:
        raise HTTPException(415, "Use a PDF, JPG, PNG, or HEIC document")
    content = await document.read(15728641)
    if not content or len(content) > 15728640:
        raise HTTPException(413, "Each vault document must be 15 MB or smaller")
    document_id = str(uuid4())
    safe_name = (document.filename or "vault-document").replace("/", "-")[:180]
    object_path = f"vault/{owner_id}/{item_id}/documents/{document_id}.{VAULT_DOCUMENT_TYPES[content_type]}"
    vault_upload("vault-files", object_path, content, content_type)
    try:
        vault_mutate("document_add", owner_id, item_id, {"id": document_id, "storage_path": object_path,
                     "file_name": safe_name, "content_type": content_type, "sha256": hashlib.sha256(content).hexdigest()})
    except HTTPException:
        cleanup_vault_file(object_path)
        raise
    return {"id": document_id, "retention": "private_vault_evidence"}


@app.get("/api/v1/vault/items/{item_id}/events")
def list_vault_events(item_id: str, owner_id=Depends(current_user)):
    owned_vault_item(item_id, owner_id)
    return supabase_request("GET", f"vault_events?item_id=eq.{item_id}&select=id,event_type,event_data,occurred_at&order=occurred_at.desc").json()


@app.post("/api/v1/vault/items/{item_id}/start-recovery", status_code=201)
def start_vault_recovery(item_id: str, request: VaultRecoveryRequest, owner_id=Depends(current_user)):
    if request.status not in {"missing", "stolen"}:
        raise HTTPException(422, "Recovery status must be missing or stolen")
    result = vault_mutate("recovery", owner_id, item_id, request.model_dump())
    result["item"] = serialize_vault_item(result["item"])
    return result


@app.post("/api/v1/vault/items/{item_id}/transfers", status_code=201)
def create_vault_transfer(item_id: str, transfer: VaultTransferCreate, identity=Depends(authenticated_identity)):
    owner_id = identity["id"]
    item = owned_vault_item(item_id, owner_id)
    recipient_email = transfer.recipient_email.strip().lower()
    if "@" not in recipient_email or len(recipient_email) > 320:
        raise HTTPException(422, "Enter the recipient's email address")
    if transfer.sharing_level != "full":
        raise HTTPException(422, "Digital Vault transfers carry the full item passport")
    if item.get("status") in {"missing", "stolen"}:
        raise HTTPException(409, "Resolve the active recovery status before transferring this item")
    if recipient_email == str(identity.get("email") or "").lower():
        raise HTTPException(422, "Choose a different recipient")
    row = vault_mutate("transfer", owner_id, item_id, {"recipient_email": recipient_email, "handover_note": transfer.handover_note})
    return {"id": row["id"], "status": row["status"], "expires_at": row["expires_at"], "item_name": item["item_name"]}


@app.get("/api/v1/vault/transfers")
def list_vault_transfers(identity=Depends(authenticated_identity)):
    owner_id, email = identity["id"], str(identity.get("email") or "").lower()
    sent = supabase_request("GET", f"vault_transfers?from_owner_id=eq.{owner_id}&select=*&order=created_at.desc").json()
    received = supabase_request("GET", f"vault_transfers?recipient_email=eq.{quote(email, safe='')}&status=eq.pending&select=*&order=created_at.desc").json()
    def public_transfer(row, direction):
        status = row["status"]
        if status == "pending" and datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            status = "expired"
        return {"id": row["id"], "direction": direction, "status": status, "sharing_level": "full", "expires_at": row["expires_at"], "created_at": row["created_at"], "item": row.get("item_snapshot") or {}}
    return {"sent": [public_transfer(row, "sent") for row in sent], "received": [public_transfer(row, "received") for row in received]}


@app.post("/api/v1/vault/transfers/{transfer_id}/accept")
def accept_vault_transfer(transfer_id: str, identity=Depends(authenticated_identity)):
    validate_vault_id(transfer_id)
    if not identity.get("email_confirmed_at"):
        raise HTTPException(403, "Verify your email address before accepting an item")
    owner_id, email = identity["id"], str(identity.get("email") or "").lower()
    rows = supabase_request("GET", f"vault_transfers?id=eq.{transfer_id}&recipient_email=eq.{quote(email, safe='')}&select=*").json()
    if not rows:
        raise HTTPException(404, "Transfer invitation not found")
    transfer = rows[0]
    result = vault_mutate("accept", owner_id, transfer["item_id"], email=email, transfer_id=transfer_id)
    result["item"] = serialize_vault_item(result["item"])
    return result


@app.post("/api/v1/vault/transfers/{transfer_id}/cancel", status_code=204)
def cancel_vault_transfer(transfer_id: str, owner_id=Depends(current_user)):
    validate_vault_id(transfer_id)
    rows = supabase_request("GET", f"vault_transfers?id=eq.{transfer_id}&from_owner_id=eq.{owner_id}&select=*").json()
    if not rows or rows[0]["status"] != "pending":
        raise HTTPException(404, "Pending transfer not found")
    transfer = rows[0]
    vault_mutate("cancel", owner_id, transfer["item_id"], transfer_id=transfer_id)
