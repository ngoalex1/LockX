"""Minimal first-party campaign attribution; confirmed payments stay server-owned."""
from datetime import datetime, timedelta, timezone
import ipaddress
import re
import time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

import credit_wallet as credits
from lost_found import limited

VISIT_SECONDS = 24 * 3600
PRIVATE_HEADERS = {"Cache-Control": "private, no-store"}
METRICS = ("visits", "verify_clicks", "wallet_opens", "checkout_starts", "paying_visits",
           "payments_count", "gross_sales_cents", "verifications_submitted",
           "verifications_completed", "verifications_matched")


def schema(db):
    for statement in (
        """CREATE TABLE IF NOT EXISTS marketing_visits (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, medium TEXT NOT NULL,
            campaign TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS marketing_visit_date ON marketing_visits(created)",
        """CREATE TABLE IF NOT EXISTS marketing_events (
            visit_id TEXT NOT NULL REFERENCES marketing_visits(id), event TEXT NOT NULL,
            created REAL NOT NULL, PRIMARY KEY(visit_id,event))""",
        """CREATE TABLE IF NOT EXISTS marketing_checkouts (
            checkout_id TEXT PRIMARY KEY REFERENCES credit_checkouts(id),
            visit_id TEXT NOT NULL REFERENCES marketing_visits(id), created REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS marketing_verifications (
            request_id TEXT PRIMARY KEY REFERENCES ih_requests(id),
            visit_id TEXT NOT NULL REFERENCES marketing_visits(id), created REAL NOT NULL)""",
    ):
        db.execute(statement)


def clean_label(value):
    value = re.sub(r"\s+", "-", value.strip().lower())
    if value and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value):
        raise ValueError("Use campaign labels, not URLs or personal details")
    if value:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            raise ValueError("IP addresses are not campaign labels")
    return value


class VisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="direct", max_length=80)
    medium: str = Field(default="none", max_length=80)
    campaign: str = Field(default="", max_length=80)
    content: str = Field(default="", max_length=120)

    @field_validator("source", "medium", "campaign", "content")
    @classmethod
    def label(cls, value):
        return clean_label(value)


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visit_id: UUID
    event: Literal["verify_click", "wallet_open"]


class VerificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visit_id: UUID
    request_id: UUID


def valid_visit(db, visit_id, now):
    row = db.execute("SELECT * FROM marketing_visits WHERE id=?", (visit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Visit not found")
    if row["created"] > now or now - row["created"] > VISIT_SECONDS:
        raise HTTPException(410, "That visit is no longer available for attribution")
    return row


def attribute_checkout(db, checkout_id, visit_id):
    """Best-effort metadata in the checkout transaction; never reattribute or bill.

    An expired/unknown optional visit leaves the real checkout unattributed.
    A later visit cannot retroactively claim an existing purchase.
    """
    schema(db)
    if db.execute("SELECT 1 FROM marketing_checkouts WHERE checkout_id=?", (checkout_id,)).fetchone():
        return False
    now = time.time()
    try:
        visit = valid_visit(db, str(visit_id), now)
    except HTTPException:
        return False
    checkout = db.execute("SELECT created FROM credit_checkouts WHERE id=?", (checkout_id,)).fetchone()
    if not checkout or not visit["created"] <= checkout["created"] <= now:
        return False
    return bool(db.execute("INSERT OR IGNORE INTO marketing_checkouts VALUES (?,?,?)",
                           (checkout_id, str(visit_id), now)).rowcount)


def create_router(current_user):
    router = APIRouter(prefix="/api/v1/credits/traffic", tags=["First-party campaign attribution"])

    def rate(request, kind, limit):
        # limited() hashes the key before persisting its bounded rate counter.
        limited("marketing-" + kind + ":" + (request.client.host if request.client else "unknown"), limit)

    @router.post("/visits", status_code=201)
    def visit(data: VisitCreate, request: Request):
        rate(request, "visit", 120)
        visit_id, now = str(uuid4()), time.time()
        with credits.database() as db:
            db.execute("BEGIN IMMEDIATE")
            schema(db)
            db.execute("INSERT INTO marketing_visits VALUES (?,?,?,?,?,?)",
                       (visit_id, data.source or "direct", data.medium or "none", data.campaign, data.content, now))
        return JSONResponse({"visit_id": visit_id, "created": now, "expires_at": now + VISIT_SECONDS},
                            status_code=201, headers=PRIVATE_HEADERS)

    @router.post("/events")
    def event(data: EventCreate, request: Request):
        rate(request, "event", 240)
        with credits.database() as db:
            db.execute("BEGIN IMMEDIATE")
            schema(db)
            previous = db.execute("SELECT 1 FROM marketing_events WHERE visit_id=? AND event=?",
                                  (str(data.visit_id), data.event)).fetchone()
            if previous:
                return JSONResponse({"recorded": True, "duplicated": True}, headers=PRIVATE_HEADERS)
            now = time.time()
            valid_visit(db, str(data.visit_id), now)
            db.execute("INSERT INTO marketing_events VALUES (?,?,?)", (str(data.visit_id), data.event, now))
        return JSONResponse({"recorded": True, "duplicated": False}, status_code=201, headers=PRIVATE_HEADERS)

    @router.post("/verifications")
    def verification(data: VerificationCreate, request: Request, owner=Depends(current_user)):
        rate(request, "verification", 120)
        with credits.database() as db:
            db.execute("BEGIN IMMEDIATE")
            schema(db)
            record = db.execute("SELECT owner_id,created FROM ih_requests WHERE id=?", (str(data.request_id),)).fetchone()
            if not record or record["owner_id"] != owner:
                raise HTTPException(404, "Verification not found")
            previous = db.execute("SELECT visit_id FROM marketing_verifications WHERE request_id=?",
                                  (str(data.request_id),)).fetchone()
            if previous:
                if previous["visit_id"] != str(data.visit_id):
                    raise HTTPException(409, "That verification is already attributed")
                return JSONResponse({"recorded": True, "duplicated": True}, headers=PRIVATE_HEADERS)
            now = time.time()
            visit = valid_visit(db, str(data.visit_id), now)
            if not visit["created"] <= record["created"] <= now:
                raise HTTPException(409, "An earlier verification cannot be attributed to a later visit")
            db.execute("INSERT INTO marketing_verifications VALUES (?,?,?)",
                       (str(data.request_id), str(data.visit_id), now))
        return JSONResponse({"recorded": True, "duplicated": False}, status_code=201, headers=PRIVATE_HEADERS)

    return router


def empty_metrics():
    return dict.fromkeys(METRICS, 0)


def with_rate(row):
    row["payment_conversion_rate"] = row["paying_visits"] / row["visits"] if row["visits"] else None
    return row


def analytics(days=30):
    if days not in {7, 30, 90}:
        raise ValueError("Choose 7, 30 or 90 days")
    from in_hand import database
    now = time.time()
    today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    since = start.timestamp()
    daily = {(start + timedelta(days=i)).strftime("%Y-%m-%d"):
             {"date": (start + timedelta(days=i)).strftime("%Y-%m-%d"), **empty_metrics()} for i in range(days)}
    summary, sources, campaigns = empty_metrics(), {}, {}
    tracking_since = None
    with database(read_only=True) as db:
        db.execute("BEGIN")
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marketing_visits'").fetchone()
        if exists:
            tracking_since = db.execute("SELECT MIN(created) FROM marketing_visits WHERE created<=?", (now,)).fetchone()[0]
            visits = db.execute("SELECT * FROM marketing_visits WHERE created>=? AND created<=?", (since, now)).fetchall()
            by_visit = {row["id"]: {**dict(row), **empty_metrics(), "visits": 1} for row in visits}
            for row in db.execute("""SELECT e.visit_id,e.event FROM marketing_events e
                JOIN marketing_visits v ON v.id=e.visit_id
                WHERE v.created>=? AND v.created<=? AND e.created<=?""", (since, now, now)):
                if row["event"] in {"verify_click", "wallet_open"}:
                    by_visit[row["visit_id"]]["verify_clicks" if row["event"] == "verify_click" else "wallet_opens"] = 1
            for row in db.execute("""SELECT m.visit_id,COUNT(*) AS count FROM marketing_checkouts m
                JOIN marketing_visits v ON v.id=m.visit_id
                WHERE v.created>=? AND v.created<=? AND m.created<=? GROUP BY m.visit_id""", (since, now, now)):
                by_visit[row["visit_id"]]["checkout_starts"] = row["count"]
            for row in db.execute("""SELECT m.visit_id,COUNT(*) AS count,SUM(p.amount_cents) AS gross
                FROM marketing_checkouts m JOIN marketing_visits v ON v.id=m.visit_id
                JOIN credit_payments p ON p.checkout_id=m.checkout_id
                JOIN credit_ledger l ON l.kind='purchase' AND l.reference=p.payment_id
                WHERE v.created>=? AND v.created<=? AND m.created<=?
                  AND l.created>=v.created AND l.created<=? GROUP BY m.visit_id""", (since, now, now, now)):
                item = by_visit[row["visit_id"]]
                item.update(paying_visits=1, payments_count=row["count"], gross_sales_cents=row["gross"])
            for row in db.execute("""SELECT m.visit_id,r.status,r.analysis_status FROM marketing_verifications m
                JOIN marketing_visits v ON v.id=m.visit_id JOIN ih_requests r ON r.id=m.request_id
                WHERE v.created>=? AND v.created<=? AND m.created<=?
                  AND r.submitted>=v.created AND r.submitted<=?""", (since, now, now, now)):
                item = by_visit[row["visit_id"]]
                item["verifications_submitted"] += 1
                if row["analysis_status"] == "complete":
                    item["verifications_completed"] += 1
                    if row["status"] == "confirmed":
                        item["verifications_matched"] += 1
            for item in by_visit.values():
                source_key = (item["source"], item["medium"])
                campaign_key = (*source_key, item["campaign"], item["content"])
                source = sources.setdefault(source_key, {"source": item["source"], "medium": item["medium"], **empty_metrics()})
                campaign = campaigns.setdefault(campaign_key, {"source": item["source"], "medium": item["medium"],
                    "campaign": item["campaign"], "content": item["content"], **empty_metrics()})
                day = daily[datetime.fromtimestamp(item["created"], timezone.utc).strftime("%Y-%m-%d")]
                for key in METRICS:
                    for target in (summary, source, campaign, day):
                        target[key] += item[key]
    sort_rows = lambda rows: [with_rate(row) for row in sorted(rows, key=lambda r: (-r["visits"], -r["gross_sales_cents"], r["source"], r.get("campaign", "")))]
    return {"currency": "USD", "timezone": "UTC", "days": days, "start": start.strftime("%Y-%m-%d"),
            "end": today.strftime("%Y-%m-%d"), "generated_at": now, "tracking_since": tracking_since,
            "summary": with_rate(summary), "sources": sort_rows(sources.values()), "campaigns": sort_rows(campaigns.values()),
            "daily": [with_rate(row) for row in daily.values()], "notes": [
                "First-party campaign tracking starts after this feature is released. Earlier visits and unattributed purchases are unavailable; no history is backfilled.",
                "The UTC cohort uses each visit's creation date. Linked checkout, payment and verification outcomes are included through this snapshot, even on later dates.",
                "Visits are browser visits, not unique people. Clicks and wallet opens count once per visit. This is not advertising-platform reach, impressions, spend or ROAS.",
                "Payment conversion is distinct paying visits divided by tracked visits. Sales require a recorded verified payment and purchased-credit ledger entry; free credit grants and unpaid checkouts are excluded.",
                "Attributed sales are gross payments before refunds, processing fees and costs. Completed verifications have a completed comparison; matched means a visual match, not authenticity. Drafts are excluded."
            ]}
