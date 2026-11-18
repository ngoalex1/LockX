"""Account-owned result events and a leased, bounded transactional email outbox.

Only finalization writers call refresh_state. Reads and worker sweeps never
bootstrap events from historical inspections. No provider call occurs in SQLite.
"""
import asyncio
import json
import os
import time
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from credit_admin import normalized_email

RETRY_SECONDS = 23 * 3600
LEASE_SECONDS = 30
PUBLIC_ORIGIN = "https://lockx.ai"


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS verification_notification_control (
        id INTEGER PRIMARY KEY CHECK(id=1), activated_at REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS verification_notification_assessments (
        request_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, completed_at REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS verification_identities (
        owner_id TEXT PRIMARY KEY, email TEXT NOT NULL, email_confirmed_at TEXT NOT NULL,
        updated REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS verification_notifications (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, root_request_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL,
        title TEXT NOT NULL, verified_count INTEGER NOT NULL, total_count INTEGER NOT NULL,
        created REAL NOT NULL, ready_at REAL, read_at REAL,
        email_state TEXT NOT NULL, recipient TEXT, payload TEXT, provider_id TEXT,
        first_attempt REAL, last_attempt REAL, provider_started REAL, next_attempt REAL NOT NULL DEFAULT 0,
        lease_until REAL NOT NULL DEFAULT 0, claim_id TEXT,
        UNIQUE(attempt_id,kind))""")
    db.execute("CREATE INDEX IF NOT EXISTS verification_notification_owner ON verification_notifications(owner_id,created,id)")
    db.execute("CREATE INDEX IF NOT EXISTS verification_notification_outbox ON verification_notifications(email_state,next_attempt)")
    if "provider_started" not in {row[1] for row in db.execute("PRAGMA table_info(verification_notifications)")}:
        db.execute("ALTER TABLE verification_notifications ADD COLUMN provider_started REAL")


def activation(db):
    """Initialize only inside a mutation transaction, never during DB setup."""
    schema(db)
    row = db.execute("SELECT activated_at FROM verification_notification_control WHERE id=1").fetchone()
    if row is None:
        db.execute("INSERT OR IGNORE INTO verification_notification_control VALUES(1,?)", (time.time(),))
        row = db.execute("SELECT activated_at FROM verification_notification_control WHERE id=1").fetchone()
    return row[0]


def owner_uuid(value):
    try:
        return str(UUID(value)) if isinstance(value, str) else None
    except (ValueError, TypeError, AttributeError):
        return None


def bind_identity(db, user):
    """Input must be the server's verified Supabase /auth/v1/user response."""
    schema(db)
    activation(db)
    if not isinstance(user, dict):
        return False
    owner = owner_uuid(user.get("id"))
    def invalidate():
        if owner:
            db.execute("DELETE FROM verification_identities WHERE owner_id=?", (owner,))
        return False
    if user.get("is_anonymous") is True or user.get("deleted_at"):
        return invalidate()
    confirmed = user.get("email_confirmed_at")
    try:
        address = normalized_email(user.get("email"))
        if not owner or not isinstance(confirmed, str):
            return invalidate()
        when = datetime.fromisoformat(confirmed.replace("Z", "+00:00"))
        if when.tzinfo is None or not 0 < when.timestamp() <= time.time() + 300:
            return invalidate()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return invalidate()
    prior = db.execute("SELECT email,email_confirmed_at FROM verification_identities WHERE owner_id=?", (owner,)).fetchone()
    if not prior or prior["email"] != address or prior["email_confirmed_at"] != confirmed:
        db.execute("""INSERT INTO verification_identities VALUES(?,?,?,?)
            ON CONFLICT(owner_id) DO UPDATE SET email=excluded.email,
            email_confirmed_at=excluded.email_confirmed_at,updated=excluded.updated""",
            (owner, address, confirmed, time.time()))
    # Only already-created recent events can resume. This never enumerates old
    # requests or invents a notification on login.
    if db.execute("SELECT 1 FROM verification_notifications WHERE owner_id=? AND email_state='waiting_identity' AND ready_at IS NOT NULL AND COALESCE(ready_at,created)>? LIMIT 1", (owner, time.time() - RETRY_SECONDS)).fetchone():
        db.execute("""UPDATE verification_notifications SET email_state='pending'
            WHERE owner_id=? AND email_state='waiting_identity' AND ready_at IS NOT NULL
            AND COALESCE(ready_at,created)>?""", (owner, time.time() - RETRY_SECONDS))
    return True


def _family(db, request_id):
    import capture_attempts
    root, rows = capture_attempts.family(db, request_id)
    return root, rows


def attempt_summary(db, row):
    import in_hand as ih
    listing = json.loads(row["listing"])
    eligible = ih.photo_eligibility(db, row)
    publication = ih.seller_publication(db, row)
    state = ih.status(row)
    if state in {"cancelled", "declined", "expired"}:
        outcome = state
    elif row["analysis_status"] in {"failed", "unavailable"}:
        outcome = "failed"
    elif state == "processing" or row["analysis_status"] in {"queued", "running"}:
        outcome = "processing"
    elif row["analysis_status"] != "complete":
        outcome = "pending"
    elif publication.get("publication_status") == "withdrawn":
        outcome = "withdrawn"
    elif publication.get("publication_status") == "failed" and eligible["verified_count"]:
        outcome = "proof_preparation_failed"
    elif publication.get("publication_status") == "pending" and eligible["verified_count"]:
        outcome = "preparing_proof"
    elif publication.get("publication_status") == "consent_required" and eligible["verified_count"]:
        outcome = "ready_to_publish"
    elif eligible["verified_count"] == eligible["total_count"] and eligible["total_count"]:
        outcome = "verified"
    elif eligible["verified_count"]:
        outcome = "partial"
    else:
        outcome = "mismatch" if state == "mismatch" else "inconclusive"
    analysis = json.loads(row["analysis"] or "{}")
    pub = db.execute("SELECT id FROM ih_publications WHERE request_id=? AND revoked IS NULL", (row["id"],)).fetchone()
    marker = db.execute("SELECT completed_at FROM verification_notification_assessments WHERE request_id=?", (row["id"],)).fetchone()
    last_event = db.execute("SELECT MAX(created) FROM ih_events WHERE request_id=?", (row["id"],)).fetchone()[0]
    updated = max(row["created"], row["submitted"] or 0, marker["completed_at"] if marker else 0, last_event or 0)
    return {"id": row["id"], "status": state, "analysis_status": row["analysis_status"],
            "outcome": outcome, "result": analysis.get("result"),
            "verified_count": eligible["verified_count"], "total_count": eligible["total_count"],
            "created": row["created"], "updated": updated,
            "publication_status": publication.get("publication_status", "not_requested"),
            "publication_id": pub["id"] if pub else None}


def _insert(db, root, row, summary, kind, *, ready):
    owner = owner_uuid(root["owner_id"])
    if not owner:
        return None
    identity = db.execute("SELECT email FROM verification_identities WHERE owner_id=?", (owner,)).fetchone()
    now = time.time()
    state = "waiting_publication" if not ready else "pending" if identity else "waiting_identity"
    title = " ".join(str(json.loads(root["listing"]).get("title") or "Your item").split())[:160]
    db.execute("""INSERT OR IGNORE INTO verification_notifications
        (id,owner_id,root_request_id,attempt_id,kind,outcome,title,verified_count,total_count,
        created,ready_at,email_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid4()), owner, root["id"], row["id"], kind, summary["outcome"], title,
         summary["verified_count"], summary["total_count"], now, now if ready else None, state))
    event = db.execute("SELECT * FROM verification_notifications WHERE attempt_id=? AND kind=?", (row["id"], kind)).fetchone()
    if ready and event["email_state"] == "waiting_publication":
        db.execute("""UPDATE verification_notifications SET ready_at=?,email_state=?,outcome=?,verified_count=?,total_count=?
            WHERE id=? AND email_state='waiting_publication'""",
            (now, "pending" if identity else "waiting_identity", summary["outcome"], summary["verified_count"], summary["total_count"], event["id"]))
    return event["id"]


def _queue_state(db, request_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verification_jobs'").fetchone():
        return None
    job = db.execute("SELECT state FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone()
    return job["state"] if job else None


def refresh_state(db, request_id, *, assessment_complete=False, final_failure=False):
    """Called inside result/publication/final-error writer transactions only."""
    schema(db)
    activation(db)
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (request_id,)).fetchone()
    if not row or not owner_uuid(row["owner_id"]):
        return None
    if (assessment_complete and row["analysis_status"] == "complete") or (final_failure and row["analysis_status"] in {"failed", "unavailable"}):
        db.execute("INSERT OR IGNORE INTO verification_notification_assessments VALUES(?,?,?)",
                   (row["id"], row["owner_id"], time.time()))
    marker = db.execute("SELECT owner_id FROM verification_notification_assessments WHERE request_id=?", (row["id"],)).fetchone()
    if not marker or marker["owner_id"] != row["owner_id"] or _queue_state(db, row["id"]) in {"queued", "running", "retrying", "budget_wait"}:
        return None
    root, rows = _family(db, request_id)
    if row["owner_id"] != root["owner_id"]:
        return None
    summary = attempt_summary(db, row)
    if row["analysis_status"] in {"failed", "unavailable"}:
        return _insert(db, root, row, summary, "processing_failed", ready=True) if final_failure else None
    if row["analysis_status"] != "complete" or row["status"] not in {"confirmed", "mismatch", "inconclusive"}:
        return None
    listing = json.loads(row["listing"])
    required = bool(listing.get("auto_publish") is True and summary["verified_count"]
                    and (summary["verified_count"] == summary["total_count"] or listing.get("publish_matched_photos") is True))
    ready = not required or summary["publication_status"] == "ready"
    publication_job = db.execute("SELECT state FROM ih_publication_jobs WHERE request_id=?", (request_id,)).fetchone()
    if required and not ready and (final_failure or (publication_job and publication_job["state"] == "failed")):
        summary["outcome"] = "proof_preparation_failed"
        return _insert(db, root, row, summary, "proof_preparation_failed", ready=True)
    return _insert(db, root, row, summary, "result_ready", ready=ready)


def unread_count(db, owner, root_id=None):
    schema(db)
    clause = " AND root_request_id=?" if root_id else ""
    args = [owner, root_id] if root_id else [owner]
    return db.execute("SELECT COUNT(*) FROM verification_notifications WHERE owner_id=? AND ready_at IS NOT NULL AND read_at IS NULL" + clause, args).fetchone()[0]


def configured():
    return (os.getenv("LOCKX_RESULT_EMAIL_ENABLED", "1") != "0"
            and bool(os.getenv("LOCKX_RESULT_EMAIL_RESEND_KEY") or os.getenv("LOCKX_SELLER_EMAIL_RESEND_KEY") or os.getenv("RESEND_API_KEY"))
            and bool(os.getenv("LOCKX_RESULT_EMAIL_FROM") or os.getenv("LOCKX_SELLER_EMAIL_FROM") or os.getenv("LOCKX_ALERT_FROM")))


def _payload(event, recipient):
    sender = os.getenv("LOCKX_RESULT_EMAIL_FROM") or os.getenv("LOCKX_SELLER_EMAIL_FROM") or os.getenv("LOCKX_ALERT_FROM")
    if not sender or len(sender) > 254 or any(ord(c) < 32 for c in sender):
        raise ValueError("Invalid result email sender")
    labels = {"verified": "Selected photos verified", "partial": "Some selected photos verified",
              "mismatch": "A match was not established: different visible details",
              "inconclusive": "A match could not be established", "failed": "Processing could not be completed",
              "proof_preparation_failed": "Comparison finished; proof preparation needs attention"}
    label = labels.get(event["outcome"], "Your result is available")
    text = (f"Your LockX result for {event['title']} is available.\n\n{label}.\n"
            f"{event['verified_count']} of {event['total_count']} photos passed the comparison for this recording.\n\n"
            f"View your private result:\n{PUBLIC_ORIGIN}/#in-hand/report/{event['attempt_id']}?account=1\n\n"
            "Sign in to the LockX account that created this check. The page shows the current result and proof status.\n"
            "A comparison does not certify authenticity, ownership, payment protection or delivery.\n\nLockX.ai")
    return {"from": sender, "to": [recipient], "subject": "Your LockX result is ready", "text": text}


def current_event(db, event):
    """One shared fence before and after asynchronous account lookup."""
    try:
        root, family = _family(db, event["attempt_id"])
        import capture_attempts
        if (root["owner_id"] != event["owner_id"] or family[-1]["id"] != event["attempt_id"]
                or capture_attempts.blocked(db, family)
                or _queue_state(db, event["attempt_id"]) in {"queued", "running", "retrying", "budget_wait"}):
            return False
        current = family[-1]
        summary = attempt_summary(db, current)
        if event["kind"] == "processing_failed":
            return current["analysis_status"] in {"failed", "unavailable"}
        if event["kind"] == "result_ready":
            return current["analysis_status"] == "complete" and summary["outcome"] == event["outcome"]
        if event["kind"] == "proof_preparation_failed":
            return current["analysis_status"] == "complete" and summary["publication_status"] != "ready"
    except Exception:
        return False
    return False


def _claim(db, now):
    """Caller holds BEGIN IMMEDIATE; returning a payload never sends it."""
    schema(db)
    activation(db)
    rows = db.execute("""SELECT * FROM verification_notifications
        WHERE ready_at IS NOT NULL AND next_attempt<=? AND
        (email_state IN ('pending','uncertain','rejected','waiting_identity') OR
         (email_state='sending' AND lease_until<=?)) ORDER BY created,id LIMIT 20""", (now, now)).fetchall()
    for event in rows:
        if now - (event["provider_started"] or event["ready_at"] or event["created"]) >= RETRY_SECONDS:
            db.execute("UPDATE verification_notifications SET email_state='expired',lease_until=0 WHERE id=?", (event["id"],))
            continue
        stale = not current_event(db, event)
        identity = db.execute("SELECT email FROM verification_identities WHERE owner_id=?", (event["owner_id"],)).fetchone()
        if stale or (event["provider_started"] and event["recipient"] and identity and identity["email"] != event["recipient"]):
            db.execute("UPDATE verification_notifications SET email_state='suppressed',lease_until=0 WHERE id=?", (event["id"],))
            continue
        recipient = event["recipient"] or (identity["email"] if identity else None)
        try:
            payload = json.loads(event["payload"]) if event["payload"] else _payload(event, recipient) if recipient else None
        except (ValueError, TypeError):
            db.execute("UPDATE verification_notifications SET email_state='suppressed' WHERE id=?", (event["id"],))
            continue
        claim_id = str(uuid4())
        db.execute("""UPDATE verification_notifications SET email_state='sending',recipient=?,payload=?,
            first_attempt=COALESCE(first_attempt,?),last_attempt=?,lease_until=?,claim_id=? WHERE id=?""",
            (recipient, json.dumps(payload, sort_keys=True, separators=(",", ":")) if payload is not None else None, now, now, now + LEASE_SECONDS, claim_id, event["id"]))
        return {"id": event["id"], "owner_id": event["owner_id"], "claim_id": claim_id, "payload": payload,
                "idempotency_key": "lockx-result-" + event["id"]}
    return None


async def resolve_identity(owner):
    """Fresh exact-user lookup; no directory search or client-provided address."""
    identifier = owner_uuid(owner)
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    try:
        parsed = urlsplit(url)
        if (not identifier or not key or parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
            return None
        headers = {"apikey": key}
        if key.count(".") == 2:
            headers["Authorization"] = "Bearer " + key
        async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = await client.get(url + "/auth/v1/admin/users/" + identifier, headers=headers)
        if response.status_code == 404:
            return {"id": identifier, "deleted_at": "unavailable"}
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def authorize_delivery(db, claim, user, *, now=None):
    """Recheck lease/account/current result after profile I/O, before mail I/O."""
    now = time.time() if now is None else now
    event = db.execute("SELECT * FROM verification_notifications WHERE id=? AND claim_id=? AND email_state='sending' AND lease_until>?", (claim["id"], claim["claim_id"], now)).fetchone()
    if not event:
        return None
    if user is None:
        db.execute("UPDATE verification_notifications SET email_state=?,next_attempt=?,lease_until=0 WHERE id=? AND claim_id=?",
                   ("uncertain" if event["provider_started"] else "pending", now + 300, event["id"], claim["claim_id"]))
        return None
    valid = isinstance(user, dict) and owner_uuid(user.get("id")) == event["owner_id"] and bind_identity(db, user)
    identity = db.execute("SELECT email FROM verification_identities WHERE owner_id=?", (event["owner_id"],)).fetchone() if valid else None
    valid = valid and current_event(db, event)
    if not valid or not identity or (event["provider_started"] and identity["email"] != event["recipient"]):
        db.execute("UPDATE verification_notifications SET email_state='suppressed',lease_until=0 WHERE id=? AND claim_id=?", (event["id"], claim["claim_id"]))
        return None
    payload = json.loads(event["payload"]) if event["provider_started"] else _payload(event, identity["email"])
    db.execute("""UPDATE verification_notifications SET recipient=?,payload=?,provider_started=COALESCE(provider_started,?),
        first_attempt=CASE WHEN provider_started IS NULL THEN ? ELSE first_attempt END WHERE id=? AND claim_id=?""",
        (identity["email"], json.dumps(payload, sort_keys=True, separators=(",", ":")), now, now, event["id"], claim["claim_id"]))
    return payload


async def deliver(payload, idempotency_key):
    key = os.getenv("LOCKX_RESULT_EMAIL_RESEND_KEY") or os.getenv("LOCKX_SELLER_EMAIL_RESEND_KEY") or os.getenv("RESEND_API_KEY")
    if not key:
        return {"state": "rejected", "retry_after": 300}
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False, follow_redirects=False) as client:
            response = await client.post("https://api.resend.com/emails", headers={"Authorization": "Bearer " + key, "Idempotency-Key": idempotency_key}, json=payload)
        if response.status_code in {200, 201, 202}:
            value = response.json()
            if isinstance(value, dict) and isinstance(value.get("id"), str) and 1 <= len(value["id"]) <= 100:
                return {"state": "accepted", "provider_id": value["id"]}
        if response.status_code in {400, 401, 403, 404, 422, 429}:
            delay = response.headers.get("retry-after", "300")
            return {"state": "rejected", "retry_after": min(3600, max(30, int(delay))) if delay.isdecimal() and len(delay) <= 6 else 300}
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return {"state": "uncertain", "retry_after": 60}


def complete(db, claim, result, *, now=None):
    now = time.time() if now is None else now
    state = result.get("state") if result.get("state") in {"accepted", "uncertain", "rejected"} else "uncertain"
    delay = result.get("retry_after", 60)
    delay = min(3600, max(30, delay)) if type(delay) is int else 60
    return bool(db.execute("""UPDATE verification_notifications SET email_state=?,provider_id=?,
        next_attempt=?,lease_until=0 WHERE id=? AND claim_id=? AND email_state='sending'""",
        (state, result.get("provider_id") if state == "accepted" else None, now + delay, claim["id"], claim["claim_id"])).rowcount)


async def drain_once(database_factory):
    if not configured():
        return False
    with database_factory() as db:
        db.execute("BEGIN IMMEDIATE")
        claim = _claim(db, time.time())
    if not claim:
        return False
    user = await resolve_identity(claim["owner_id"])
    with database_factory() as db:
        db.execute("BEGIN IMMEDIATE")
        payload = authorize_delivery(db, claim, user)
    if payload is None:
        return True
    result = await deliver(payload, claim["idempotency_key"])
    with database_factory() as db:
        db.execute("BEGIN IMMEDIATE")
        complete(db, claim, result)
    return True


async def worker_loop(database_factory):
    while True:
        try:
            worked = await drain_once(database_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            worked = False
        await asyncio.sleep(1.0 if worked else 5)
