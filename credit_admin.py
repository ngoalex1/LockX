"""Private, audited credit grants. Admin identity is configured only on the server."""
from __future__ import annotations

import os
import re
import time
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

import credit_wallet as credits

PRIVATE_HEADERS = {"Cache-Control": "private, no-store"}
PAGE_SIZE = 1000
MAX_LOOKUP_PAGES = 10


def normalized_email(value: str) -> str:
    """Accept a bounded, unambiguous mailbox without optional email dependencies."""
    value = value.strip().lower()
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("Enter a valid email address")
    local, domain = value.split("@")
    if (not local or len(local) > 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)):
        raise ValueError("Enter a valid email address")
    labels = domain.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                              for label in labels):
        raise ValueError("Enter a valid email address")
    return value


def require_admin(identity: dict) -> str:
    """Never use email, role or writable user metadata to authorize an admin."""
    try:
        owner = str(UUID(identity["id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(403, "Credit administrator access is required") from None
    allowed = set()
    for value in os.getenv("LOCKX_CREDIT_ADMIN_IDS", "").split(","):
        try:
            allowed.add(str(UUID(value.strip())))
        except (ValueError, AttributeError):
            continue
    if owner not in allowed:
        raise HTTPException(403, "Credit administrator access is required")
    return owner


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS credit_admin_grants (
        id TEXT PRIMARY KEY, admin_id TEXT NOT NULL, owner_id TEXT NOT NULL,
        email TEXT NOT NULL, credits INTEGER NOT NULL CHECK(credits>0 AND credits<=10000),
        reason TEXT NOT NULL, request_key TEXT NOT NULL, created REAL NOT NULL,
        UNIQUE(admin_id,request_key))""")


def lookup_user(email: str) -> dict:
    """Resolve one exact email using the server-only Supabase Auth Admin API.

    Only pagination is needed from the documented list-users API. Never return
    the directory or trust substring matching to select a credit recipient.
    """
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(503, "Account lookup is not configured")
    headers = {"apikey": key}
    if key.count(".") == 2:
        headers["Authorization"] = "Bearer " + key
    for page in range(1, MAX_LOOKUP_PAGES + 1):
        try:
            response = httpx.get(url + "/auth/v1/admin/users", headers=headers,
                                params={"page": page, "per_page": PAGE_SIZE}, timeout=10)
            response.raise_for_status()
            users = response.json().get("users")
            if not isinstance(users, list):
                raise ValueError("Invalid account directory")
            for user in users:
                if not isinstance(user, dict):
                    raise ValueError("Invalid account directory")
                if (isinstance(user.get("email"), str) and user["email"].strip().lower() == email
                        and not user.get("deleted_at") and not user.get("is_anonymous")):
                    return {"id": str(UUID(user["id"])), "email": email}
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(503, "Account lookup is temporarily unavailable") from None
        if len(users) < PAGE_SIZE:
            raise HTTPException(404, "No existing LockX account has that email. Ask them to sign in first.")
    raise HTTPException(503, "Account lookup is temporarily unavailable")


class GrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    credits: int = Field(strict=True, ge=1, le=10000)
    reason: str = Field(min_length=1, max_length=300)
    request_key: UUID

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return normalized_email(value)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("A reason is required")
        return value


def grant_payload(db, row, *, duplicated=False):
    record = db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (row["owner_id"],)).fetchone()
    return {"grant_id": row["id"], "admin_id": row["admin_id"], "owner_id": row["owner_id"],
            "email": row["email"], "credits": row["credits"], "reason": row["reason"],
            "request_key": row["request_key"], "created": row["created"],
            "balance": max(0, record["balance"]) if record else 0, "duplicated": duplicated}


def existing_grant(db, admin_id, data):
    row = db.execute("SELECT * FROM credit_admin_grants WHERE admin_id=? AND request_key=?",
                     (admin_id, str(data.request_key))).fetchone()
    if row and (row["email"] != data.email or row["credits"] != data.credits or row["reason"] != data.reason):
        raise HTTPException(409, "That request key was already used for a different credit grant")
    return row


def create_router(authenticate_identity):
    router = APIRouter(prefix="/api/v1/credits/admin", tags=["Private credit administration"])

    def admin(identity=Depends(authenticate_identity)):
        return require_admin(identity)

    @router.get("/access")
    def access(admin_id=Depends(admin)):
        return JSONResponse({"is_admin": True}, headers=PRIVATE_HEADERS)

    @router.get("/users")
    def user(email: str = Query(min_length=3, max_length=254), admin_id=Depends(admin)):
        try:
            email = normalized_email(email)
        except ValueError:
            raise HTTPException(422, "Enter a valid email address") from None
        recipient = lookup_user(email)
        with credits.database() as db:
            row = db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (recipient["id"],)).fetchone()
        return JSONResponse({**recipient, "balance": max(0, row["balance"]) if row else 0}, headers=PRIVATE_HEADERS)

    @router.post("/grants")
    def grant(data: GrantCreate, admin_id=Depends(admin)):
        # Replays need no new provider lookup and remain safe if an account or
        # the upstream directory becomes temporarily unavailable afterward.
        with credits.database() as db:
            schema(db)
            previous = existing_grant(db, admin_id, data)
            if previous:
                return JSONResponse(grant_payload(db, previous, duplicated=True), headers=PRIVATE_HEADERS)
        recipient = lookup_user(data.email)
        with credits.database() as db:
            db.execute("BEGIN IMMEDIATE")
            schema(db)
            previous = existing_grant(db, admin_id, data)
            if previous:
                return JSONResponse(grant_payload(db, previous, duplicated=True), headers=PRIVATE_HEADERS)
            grant_id = str(uuid4())
            db.execute("INSERT INTO credit_admin_grants VALUES (?,?,?,?,?,?,?,?)",
                       (grant_id, admin_id, recipient["id"], data.email, data.credits,
                        data.reason, str(data.request_key), time.time()))
            if not credits.entry(db, recipient["id"], data.credits, "admin_grant", grant_id):
                raise HTTPException(409, "That credit grant has already been recorded")
            row = db.execute("SELECT * FROM credit_admin_grants WHERE id=?", (grant_id,)).fetchone()
            result = grant_payload(db, row)
        return JSONResponse(result, status_code=201, headers=PRIVATE_HEADERS)

    @router.get("/grants")
    def grants(admin_id=Depends(admin)):
        with credits.database() as db:
            schema(db)
            rows = db.execute("SELECT * FROM credit_admin_grants ORDER BY created DESC,id DESC LIMIT 50").fetchall()
            result = [grant_payload(db, row) for row in rows]
        return JSONResponse({"grants": result}, headers=PRIVATE_HEADERS)

    @router.get("/analytics")
    def analytics(days: int = Query(default=30), admin_id=Depends(admin)):
        if days not in {7, 30, 90}:
            raise HTTPException(422, "Choose 7, 30 or 90 days")
        from credit_analytics import analytics as business_analytics
        return JSONResponse(business_analytics(days), headers=PRIVATE_HEADERS)

    @router.get("/social")
    def social(days: int = Query(default=30), admin_id=Depends(admin)):
        if days not in {7, 30, 90}:
            raise HTTPException(422, "Choose 7, 30 or 90 days")
        from credit_social import analytics as social_analytics
        return JSONResponse(social_analytics(days), headers=PRIVATE_HEADERS)

    return router
