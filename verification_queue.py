"""Single-volume durable verification queue and shared OpenAI admission control.

SQLite is the authority for evidence, leases, spending reservations and results.
This implementation deliberately does not claim horizontal multi-volume capacity.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

import httpx
from fastapi import HTTPException

CURRENT_CLAIM = ContextVar("verification_claim", default=None)
STATES = ("queued", "running", "retrying", "budget_wait", "completed", "failed")
ACTIVE = ("queued", "running", "retrying", "budget_wait")
PRICE_VERSION = "gpt-4.1-2025-04-14-input2-output8-USD-per-million"
SUPPORTED_MODELS = {"gpt-4.1", "gpt-4.1-2025-04-14"}


class LeaseLost(Exception):
    pass


class AdmissionWait(Exception):
    def __init__(self, reason, retry_at):
        self.reason, self.retry_at = reason, retry_at
        super().__init__(reason)


def enabled():
    return os.getenv("LOCKX_VERIFICATION_QUEUE_ENABLED") == "1"


def integer(name, default, low, high):
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def max_workers():
    return integer("LOCKX_VERIFICATION_MAX_WORKERS", 8, 1, 8)


def lease_seconds():
    return integer("LOCKX_VERIFICATION_LEASE_SECONDS", 120, 30, 600)


def database():
    from credit_wallet import database as credit_database
    return credit_database()


def schema(db):
    for sql in (
        """CREATE TABLE IF NOT EXISTS verification_jobs (
          id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES ih_requests(id), session_id TEXT NOT NULL,
          manifest TEXT NOT NULL, state TEXT NOT NULL, queued_at REAL NOT NULL, started_at REAL,
          updated_at REAL NOT NULL, next_run REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          fence INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until REAL, reason TEXT,
          UNIQUE(request_id,session_id))""",
        "CREATE INDEX IF NOT EXISTS verification_fifo ON verification_jobs(state,next_run,queued_at)",
        """CREATE TABLE IF NOT EXISTS verification_calls (
          id TEXT PRIMARY KEY, job_id TEXT, fence INTEGER, created REAL NOT NULL, model TEXT NOT NULL,
          price_version TEXT NOT NULL, reserved_micros INTEGER NOT NULL, charged_micros INTEGER NOT NULL,
          input_tokens INTEGER, output_tokens INTEGER, outcome TEXT NOT NULL DEFAULT 'unknown')""",
        "CREATE INDEX IF NOT EXISTS verification_spend ON verification_calls(created)",
        """CREATE TABLE IF NOT EXISTS verification_control (
          id INTEGER PRIMARY KEY CHECK(id=1), next_api REAL NOT NULL DEFAULT 0,
          pause_until REAL NOT NULL DEFAULT 0, adaptive_limit INTEGER NOT NULL DEFAULT 8)""",
        "INSERT OR IGNORE INTO verification_control(id) VALUES (1)",
        """CREATE TABLE IF NOT EXISTS verification_workers (
          id TEXT PRIMARY KEY, heartbeat REAL NOT NULL, job_id TEXT)""",
    ):
        db.execute(sql)


def has_job(db, request_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='verification_jobs'").fetchone():
        return False
    return bool(db.execute("SELECT 1 FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone())


def check_storage(db, extra_bytes=0):
    if not enabled():
        return
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    if shutil.disk_usage(Path(filename).parent).free < extra_bytes + integer("LOCKX_VERIFICATION_MIN_FREE_MB", 256, 64, 100000) * 1024 * 1024:
        raise HTTPException(503, "Verification storage is busy. Please try again later.")


def check_capacity(db):
    if not enabled():
        return
    schema(db)
    count = db.execute("SELECT COUNT(*) FROM verification_jobs WHERE state IN ('queued','running','retrying','budget_wait')").fetchone()[0]
    if count >= integer("LOCKX_VERIFICATION_MAX_QUEUED", 10000, 1, 10000):
        raise HTTPException(503, "Verification is busy. Please try again later before recording.")
    check_storage(db)


def evidence_manifest(db, request_id, model=None):
    from in_hand import vision_model
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (request_id,)).fetchone()
    session = db.execute("SELECT * FROM ih_sessions WHERE id=? AND request_id=?", (row["session_id"], request_id)).fetchone() if row else None
    media = db.execute("SELECT id,role,sha256,content FROM ih_media WHERE request_id=? AND role IN ('listing','video') ORDER BY rowid", (request_id,)).fetchall()
    model = model or vision_model()
    if model not in SUPPORTED_MODELS:
        raise HTTPException(503, "The verification model must be configured before queueing.")
    if not row or not session or not session["finished"] or not 1 <= sum(m["role"] == "listing" for m in media) <= 6 or sum(m["role"] == "video" for m in media) != 1:
        raise ValueError("Complete saved evidence is required")
    for m in media:
        if hashlib.sha256(m["content"]).hexdigest() != m["sha256"]:
            raise ValueError("Saved evidence hash mismatch")
    state = {key: session[key] for key in ("id", "request_id", "started", "finished", "stages", "observations")}
    observations = json.loads(session["observations"])
    durations = [o["recording_seconds"] for o in observations if o.get("recording_end") and isinstance(o.get("recording_seconds"), (int,float))]
    captured_at = min(session["finished"], session["started"] + durations[-1]) if durations else session["finished"]
    return {"request_id": request_id, "session_id": session["id"], "captured_at": captured_at, "model": model,
            "listing_hash": hashlib.sha256(row["listing"].encode()).hexdigest(),
            "session_hash": hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(),
            "media": [{"id": m["id"], "role": m["role"], "sha256": m["sha256"]} for m in media]}


def enqueue(db, request_id, *, technical_retry=False):
    schema(db)
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (request_id,)).fetchone()
    previous = db.execute("SELECT * FROM verification_jobs WHERE request_id=? AND session_id=?", (request_id, row["session_id"])).fetchone()
    if previous and not (technical_retry and previous["state"] == "failed"):
        return public_status(db, request_id)
    if row["analysis_status"] == "complete":
        raise HTTPException(409, "A completed comparison cannot be queued again")
    check_capacity(db)
    manifest, now = evidence_manifest(db, request_id), time.time()
    # Canonical capture time is the recording end, not the later upload receipt.
    db.execute("UPDATE ih_sessions SET finished=? WHERE id=?", (manifest["captured_at"],row["session_id"]))
    manifest = evidence_manifest(db,request_id,model=manifest["model"])
    if previous:
        db.execute("""UPDATE verification_jobs SET manifest=?,state='queued',queued_at=?,updated_at=?,next_run=?,
            attempts=0,fence=fence+1,lease_owner=NULL,lease_until=NULL,reason=NULL WHERE id=?""",
                   (json.dumps(manifest), now, now, now, previous["id"]))
    else:
        db.execute("INSERT INTO verification_jobs(id,request_id,session_id,manifest,state,queued_at,updated_at,next_run) VALUES (?,?,?,?,'queued',?,?,?)",
                   (str(uuid4()), request_id, row["session_id"], json.dumps(manifest), now, now, now))
    db.execute("UPDATE ih_requests SET analysis_status='queued' WHERE id=?", (request_id,))
    return public_status(db, request_id)


def ensure_current(db, claim, *, verify_evidence=True):
    row = db.execute("SELECT * FROM verification_jobs WHERE id=?", (claim["id"],)).fetchone()
    if (not row or row["state"] != "running" or row["fence"] != claim["fence"] or row["lease_owner"] != claim["lease_owner"]
            or row["lease_until"] <= time.time()):
        raise LeaseLost("Verification lease changed")
    request = db.execute("SELECT session_id FROM ih_requests WHERE id=?", (row["request_id"],)).fetchone()
    if not request or request["session_id"] != row["session_id"]:
        raise LeaseLost("Verification session changed")
    manifest = json.loads(row["manifest"])
    if verify_evidence and evidence_manifest(db, row["request_id"], model=manifest["model"]) != manifest:
        raise ValueError("Saved evidence changed")
    return row


def worker_model():
    claim = CURRENT_CLAIM.get()
    return json.loads(claim["manifest"])["model"] if claim else None


def _terminal(db, job, reason):
    import credit_wallet as credits
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (job["request_id"],)).fetchone()
    if row and row["session_id"] == job["session_id"] and row["analysis_status"] != "complete":
        analysis = json.loads(row["analysis"] or "{}")
        analysis.update(result="inconclusive", failure_reason=reason,
                        summary="Your recording is saved, but verification could not complete. Any reserved credit is restored.")
        db.execute("UPDATE ih_requests SET status='inconclusive',analysis_status='failed',analysis=? WHERE id=?", (json.dumps(analysis), row["id"]))
        credits.settle_check(db, row["id"])
    db.execute("UPDATE verification_jobs SET state='failed',updated_at=?,lease_owner=NULL,lease_until=NULL,reason=? WHERE id=?",
               (time.time(), reason, job["id"]))


def desired_workers(backlog):
    base = integer("LOCKX_VERIFICATION_CONCURRENCY", 2, 1, 8)
    return min(max_workers(), max(base, math.ceil(backlog / 20)))


def claim_job(worker_id):
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        db.execute("INSERT INTO verification_workers VALUES (?,?,NULL) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat", (worker_id, now))
        overdue = db.execute("SELECT * FROM verification_jobs WHERE state IN ('queued','retrying','budget_wait','running') AND queued_at<?", (now - 86400,)).fetchall()
        for job in overdue:
            _terminal(db, job, "queue_wait_expired")
        db.execute("UPDATE verification_jobs SET state='retrying',next_run=?,lease_owner=NULL,lease_until=NULL,reason='worker_recovery' WHERE state='running' AND lease_until<=?", (now, now))
        backlog = db.execute("SELECT COUNT(*) FROM verification_jobs WHERE state IN ('queued','retrying','budget_wait')").fetchone()[0]
        running = db.execute("SELECT COUNT(*) FROM verification_jobs WHERE state='running'").fetchone()[0]
        control = db.execute("SELECT * FROM verification_control WHERE id=1").fetchone()
        if running >= min(desired_workers(backlog + running), control["adaptive_limit"]):
            return None
        job = db.execute("SELECT * FROM verification_jobs WHERE state IN ('queued','retrying','budget_wait') AND next_run<=? ORDER BY queued_at,id LIMIT 1", (now,)).fetchone()
        if not job:
            return None
        if job["attempts"] >= integer("LOCKX_VERIFICATION_MAX_ATTEMPTS", 5, 1, 10):
            _terminal(db, job, "technical_retries_exhausted")
            return None
        db.execute("UPDATE verification_jobs SET state='running',started_at=COALESCE(started_at,?),updated_at=?,attempts=attempts+1,fence=fence+1,lease_owner=?,lease_until=?,reason=NULL WHERE id=?",
                   (now, now, worker_id, now + lease_seconds(), job["id"]))
        db.execute("UPDATE verification_workers SET job_id=? WHERE id=?", (job["id"], worker_id))
        return dict(db.execute("SELECT * FROM verification_jobs WHERE id=?", (job["id"],)).fetchone())


def heartbeat(claim=None, worker_id=None):
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        if claim:
            ensure_current(db, claim, verify_evidence=False)
            db.execute("UPDATE verification_jobs SET lease_until=?,updated_at=? WHERE id=?", (now + lease_seconds(), now, claim["id"]))
            worker_id = claim["lease_owner"]
        if worker_id:
            db.execute("INSERT INTO verification_workers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,job_id=excluded.job_id",
                       (worker_id, now, claim["id"] if claim else None))


def retry_after(response, default=10):
    raw = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        return max(1, min(3600, float(raw)))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            return max(1, min(3600, parsedate_to_datetime(raw).timestamp() - time.time()))
        except (ValueError, TypeError):
            return default


def retry_classification(error):
    if isinstance(error, AdmissionWait):
        return error.reason, error.retry_at
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
        return "provider_retry", time.time() + 10
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        try:
            code = response.json().get("error", {}).get("code")
        except (ValueError, AttributeError):
            code = None
        if code in {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active", "credit_balance_exhausted",
                    "organization_usage_limit_exceeded", "organization_spend_limit_exceeded", "project_spend_limit_exceeded", "usage_limit_exceeded"}:
            return None
        if response.status_code == 429:
            return "provider_rate_limit", time.time() + retry_after(response)
        if 500 <= response.status_code <= 599:
            return "provider_retry", time.time() + retry_after(response)
    return None


def finish_job(claim, error=None):
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        try:
            job = ensure_current(db, claim, verify_evidence=False)
        except LeaseLost:
            return False
        row = db.execute("SELECT analysis_status FROM ih_requests WHERE id=?", (job["request_id"],)).fetchone()
        if error is None and row["analysis_status"] == "complete":
            db.execute("UPDATE verification_jobs SET state='completed',updated_at=?,lease_owner=NULL,lease_until=NULL WHERE id=?", (now, job["id"]))
            db.execute("UPDATE verification_control SET adaptive_limit=MIN(8,adaptive_limit+1) WHERE id=1")
            return True
        retry = retry_classification(error)
        if retry and (isinstance(error, AdmissionWait) or job["attempts"] < integer("LOCKX_VERIFICATION_MAX_ATTEMPTS", 5, 1, 10)):
            reason, next_run = retry
            delay = next_run if isinstance(error, AdmissionWait) else max(next_run, now + min(300, 2 ** job["attempts"]))
            state = "budget_wait" if reason == "budget_limit" else "retrying"
            db.execute("UPDATE verification_jobs SET state=?,reason=?,next_run=?,updated_at=?,lease_owner=NULL,lease_until=NULL,attempts=attempts-? WHERE id=?",
                       (state, reason, delay, now, int(isinstance(error, AdmissionWait)), job["id"]))
            db.execute("UPDATE ih_requests SET analysis_status='queued' WHERE id=? AND analysis_status!='complete'", (job["request_id"],))
            return True
        _terminal(db, job, "technical_failure")
        return True


def estimate_micros(model, instructions, content, output_schema, max_output_tokens):
    if model not in SUPPORTED_MODELS or max_output_tokens > 5000:
        raise ValueError("Unpriced verification model or output bound")
    if sum(item.get("type") == "input_image" for item in content) > 18:
        raise ValueError("Verification input exceeds its spending bound")
    # Full gpt-4.1 context ceiling 1,047,576 tokens at $2/million plus
    # max5,000 output tokens at $8/million is below $3, regardless of image
    # tokenization. Unknown outcomes keep this full reservation for an hour.
    return 3000000


def reserve_call(model, instructions, content, output_schema, max_output_tokens=5000):
    amount = estimate_micros(model, instructions, content, output_schema, max_output_tokens)
    now, claim, call_id = time.time(), CURRENT_CLAIM.get(), str(uuid4())
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        if claim:
            ensure_current(db, claim)
        control = db.execute("SELECT * FROM verification_control WHERE id=1").fetchone()
        if control["pause_until"] > now:
            raise AdmissionWait("provider_rate_limit", control["pause_until"])
        if control["next_api"] > now:
            raise AdmissionWait("pacing", control["next_api"])
        spend = db.execute("SELECT COALESCE(SUM(charged_micros),0) FROM verification_calls WHERE created>?", (now - 3600,)).fetchone()[0]
        cap = integer("LOCKX_VERIFICATION_HOURLY_BUDGET_USD", 100, 1, 100) * 1000000
        if spend + amount > cap:
            oldest = db.execute("SELECT MIN(created) FROM verification_calls WHERE created>? AND charged_micros>0", (now - 3600,)).fetchone()[0]
            raise AdmissionWait("budget_limit", (oldest + 3600.1) if oldest else now + 3600)
        db.execute("INSERT INTO verification_calls(id,job_id,fence,created,model,price_version,reserved_micros,charged_micros) VALUES (?,?,?,?,?,?,?,?)",
                   (call_id, claim["id"] if claim else None, claim["fence"] if claim else None, now, model, PRICE_VERSION, amount, amount))
        db.execute("UPDATE verification_control SET next_api=? WHERE id=1", (now + 1,))
    return call_id


def record_usage(call_id, usage):
    if not isinstance(usage, dict) or type(usage.get("input_tokens")) is not int or type(usage.get("output_tokens")) is not int:
        return
    input_tokens, output_tokens = usage["input_tokens"], usage["output_tokens"]
    if min(input_tokens, output_tokens) < 0:
        return
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        amount = input_tokens * 2 + output_tokens * 8
        previous = db.execute("SELECT charged_micros,outcome FROM verification_calls WHERE id=?", (call_id,)).fetchone()
        db.execute("UPDATE verification_calls SET charged_micros=?,input_tokens=?,output_tokens=?,outcome='known_usage' WHERE id=? AND outcome='unknown'",
                   (amount, input_tokens, output_tokens, call_id))
        if previous and previous["outcome"] == "unknown" and amount < previous["charged_micros"]:
            # Wake paused jobs when a confirmed response releases headroom.
            # Each worker still rechecks the shared budget before calling AI.
            db.execute("UPDATE verification_jobs SET next_run=MIN(next_run,?) WHERE state='budget_wait'", (time.time(),))


def note_provider_failure(error):
    if not isinstance(error, httpx.HTTPStatusError) or error.response.status_code != 429:
        return
    retry = retry_classification(error)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        schema(db)
        delay = retry[1] if retry else time.time() + 3600
        db.execute("UPDATE verification_control SET pause_until=MAX(pause_until,?),adaptive_limit=MAX(1,adaptive_limit/2) WHERE id=1", (delay,))


def public_status(db, request_id):
    if not has_job(db, request_id):
        return None
    job = db.execute("SELECT * FROM verification_jobs WHERE request_id=? ORDER BY queued_at DESC LIMIT 1", (request_id,)).fetchone()
    position = db.execute("SELECT COUNT(*) FROM verification_jobs WHERE state IN ('queued','retrying','budget_wait') AND queued_at<?", (job["queued_at"],)).fetchone()[0] + 1 if job["state"] in {"queued", "retrying", "budget_wait"} else None
    return {"state": job["state"], "queued_at": job["queued_at"], "started_at": job["started_at"], "updated_at": job["updated_at"],
            "attempts": job["attempts"], "position": position, "estimated_wait_seconds": None,
            "retry_at": job["next_run"] if job["state"] in {"retrying", "budget_wait"} else None, "reason": job["reason"]}


def admin_status():
    now = time.time()
    with database() as db:
        schema(db)
        counts = {state: 0 for state in STATES}
        counts.update({r["state"]: r["count"] for r in db.execute("SELECT state,COUNT(*) AS count FROM verification_jobs GROUP BY state")})
        oldest = db.execute("SELECT MIN(queued_at) FROM verification_jobs WHERE state IN ('queued','retrying','budget_wait')").fetchone()[0]
        workers = db.execute("SELECT COUNT(*) AS count,MAX(heartbeat) AS latest FROM verification_workers WHERE heartbeat>?", (now - 30,)).fetchone()
        calls = db.execute("SELECT COALESCE(SUM(charged_micros),0) AS reserved,COALESCE(SUM(CASE WHEN outcome='known_usage' THEN charged_micros ELSE 0 END),0) AS actual FROM verification_calls WHERE created>?", (now - 3600,)).fetchone()
        recent = [dict(r) for r in db.execute("SELECT state,queued_at,started_at,updated_at,attempts,next_run AS retry_at,reason FROM verification_jobs ORDER BY queued_at DESC LIMIT 20")]
        hourly = {r["state"]: r["count"] for r in db.execute("SELECT state,COUNT(*) AS count FROM verification_jobs WHERE updated_at>=? GROUP BY state", (now - 3600,))}
    return {"enabled": enabled(), "states": counts, **counts, "oldest_wait_seconds": max(0, now - oldest) if oldest else 0,
            "estimated_wait_seconds": None, "worker_heartbeat_at": workers["latest"], "active_workers": workers["count"],
            "hourly_budget_usd": integer("LOCKX_VERIFICATION_HOURLY_BUDGET_USD", 100, 1, 100),
            "budget_reserved_usd": calls["reserved"] / 1000000, "budget_actual_usd": calls["actual"] / 1000000,
            "concurrency": desired_workers(sum(counts[s] for s in ACTIVE)), "max_workers": max_workers(),
            "completed_last_hour": hourly.get("completed", 0), "failed_last_hour": hourly.get("failed", 0), "recent": recent}
