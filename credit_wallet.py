"""Server-owned credits and PayPal checkout. No browser-supplied balance is trusted."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from typing import Literal

log = logging.getLogger("lockx.credits")
PACKS = {
    "starter": {"name": "Starter", "amount_cents": 100, "credits": 2},
    "regular": {"name": "Regular", "amount_cents": 500, "credits": 10},
    "frequent": {"name": "Frequent", "amount_cents": 1000, "credits": 20},
}


def enabled():
    return os.getenv("LOCKX_CREDITS_ENABLED") == "1"


def paypal_base():
    mode = os.getenv("PAYPAL_ENVIRONMENT", "sandbox")
    if mode not in {"sandbox", "live"}:
        raise HTTPException(503, "Payments are not configured")
    return "https://api-m.paypal.com" if mode == "live" else "https://api-m.sandbox.paypal.com"


def origin():
    value = os.getenv("LOCKX_PUBLIC_APP_ORIGIN", "https://lockx.ai").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc not in {"lockx.ai", "www.lockx.ai"} or parsed.path:
        raise HTTPException(503, "The payment return address is not configured")
    return value


def payment_ready():
    return enabled() and all(os.getenv(k) for k in (
        "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_MERCHANT_ID", "PAYPAL_WEBHOOK_ID"
    )) and os.getenv("LOCKX_PAYPAL_LINKS_VALIDATED") == "1"


def google_ready():
    return payment_ready() and bool(os.getenv("PAYPAL_GOOGLE_PAY_MERCHANT_ID"))


def catalog():
    return {
        "credits_required": enabled(), "payment_ready": payment_ready(),
        "google_pay_ready": google_ready(), "currency": "USD", "credits_per_verification": 1,
        "packs": [{"id": key, **pack} for key, pack in PACKS.items()],
        "paypal_client_id": os.getenv("PAYPAL_CLIENT_ID", "") if google_ready() else "",
        "google_merchant_id": os.getenv("PAYPAL_GOOGLE_PAY_MERCHANT_ID", "") if google_ready() else "",
        "environment": os.getenv("PAYPAL_ENVIRONMENT", "sandbox"),
    }


def schema(db):
    # execute(), not executescript(): callers may already own a transaction.
    for statement in (
        """CREATE TABLE IF NOT EXISTS credit_wallets (
           owner_id TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS credit_checkouts (
           id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES credit_wallets(owner_id),
           pack_id TEXT NOT NULL, amount_cents INTEGER NOT NULL, credits INTEGER NOT NULL,
           provider TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
           request_key TEXT NOT NULL, resource_id TEXT UNIQUE, payment_url TEXT,
           payment_id TEXT UNIQUE, refunded_cents INTEGER NOT NULL DEFAULT 0,
           reversed_credits INTEGER NOT NULL DEFAULT 0, UNIQUE(owner_id,request_key))""",
        """CREATE TABLE IF NOT EXISTS credit_ledger (
           id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES credit_wallets(owner_id),
           delta INTEGER NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL,
           created REAL NOT NULL, UNIQUE(kind,reference))""",
        """CREATE TABLE IF NOT EXISTS credit_payments (
           payment_id TEXT PRIMARY KEY, checkout_id TEXT NOT NULL REFERENCES credit_checkouts(id),
           owner_id TEXT NOT NULL, amount_cents INTEGER NOT NULL, credits INTEGER NOT NULL,
           refunded_cents INTEGER NOT NULL DEFAULT 0, reversed_credits INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS credit_checks (
           request_id TEXT PRIMARY KEY REFERENCES ih_requests(id),
           owner_id TEXT NOT NULL REFERENCES credit_wallets(owner_id),
           state TEXT NOT NULL DEFAULT 'new', parent_request_id TEXT, updated REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS credit_ledger_owner ON credit_ledger(owner_id,created)",
    ):
        db.execute(statement)


@contextmanager
def database():
    from in_hand import database as inspection_database
    with inspection_database() as db:
        schema(db)
        yield db


def wallet(db, owner):
    db.execute("INSERT OR IGNORE INTO credit_wallets(owner_id,created) VALUES (?,?)", (owner, time.time()))
    return db.execute("SELECT * FROM credit_wallets WHERE owner_id=?", (owner,)).fetchone()


def entry(db, owner, delta, kind, reference):
    wallet(db, owner)
    changed = db.execute("INSERT OR IGNORE INTO credit_ledger VALUES (?,?,?,?,?,?)",
                         (str(uuid4()), owner, delta, kind, reference, time.time(),)).rowcount
    if changed:
        db.execute("UPDATE credit_wallets SET balance=balance+? WHERE owner_id=?", (delta, owner))
    return bool(changed)


def bind_check(db, request_id, owner):
    if not enabled():
        return
    schema(db)
    if not owner or owner.startswith("guest:"):
        raise HTTPException(401, "Sign in with your email to use your credits")
    if wallet(db, owner)["balance"] < 1:
        raise HTTPException(402, "Buy credits to start a verification")
    db.execute("INSERT INTO credit_checks(request_id,owner_id,updated) VALUES (?,?,?)",
               (request_id, owner, time.time()))


def bind_quality_retry(db, parent_id, child_id):
    schema(db)
    parent = db.execute("SELECT * FROM credit_checks WHERE request_id=?", (parent_id,)).fetchone()
    if parent:
        # Only the existing server-approved, one-time same-photo retry gets this exemption.
        db.execute("INSERT INTO credit_checks VALUES (?,?, 'included',?,?)",
                   (child_id, parent["owner_id"], parent_id, time.time()))


def reserve_check(db, request_id):
    schema(db)
    record = db.execute("SELECT * FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()
    if not record:
        # Inspections created before the paid launch keep working.
        return
    if record["state"] in {"reserved", "consumed", "included"}:
        return
    owner = record["owner_id"]
    if wallet(db, owner)["balance"] < 1:
        raise HTTPException(402, "You need one available credit to submit this verification")
    reference = request_id + ":" + str(uuid4())
    entry(db, owner, -1, "verification", reference)
    db.execute("UPDATE credit_checks SET state='reserved',updated=? WHERE request_id=?", (time.time(), request_id))


def settle_check(db, request_id):
    schema(db)
    row = db.execute("""SELECT c.*,r.analysis_status FROM credit_checks c
                        JOIN ih_requests r ON r.id=c.request_id WHERE c.request_id=?""", (request_id,)).fetchone()
    if not row or row["state"] != "reserved":
        return
    if row["analysis_status"] == "complete":
        db.execute("UPDATE credit_checks SET state='consumed',updated=? WHERE request_id=?", (time.time(), request_id))
    elif row["analysis_status"] in {"failed", "unavailable"}:
        # One refund for each reserved attempt; a technical retry may reserve again.
        entry(db, row["owner_id"], 1, "technical_refund", request_id + ":" + str(row["updated"]))
        db.execute("UPDATE credit_checks SET state='refunded',updated=? WHERE request_id=?", (time.time(), request_id))


def reconcile(db, owner):
    from in_hand import cleanup_scan_media
    cleanup_scan_media(db,time.time())
    rows = db.execute("""SELECT c.request_id FROM credit_checks c JOIN ih_requests r ON r.id=c.request_id
                         WHERE c.owner_id=? AND c.state='reserved'
                         AND r.analysis_status IN ('complete','failed','unavailable')""", (owner,)).fetchall()
    for row in rows:
        settle_check(db, row["request_id"])


def money_cents(value):
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Invalid payment amount")


def paypal_call(method, path, *, body=None, request_id=None):
    client_id, secret = os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_CLIENT_SECRET")
    if not client_id or not secret:
        raise HTTPException(503, "Payments are not available yet")
    try:
        with httpx.Client(timeout=25) as client:
            auth = client.post(paypal_base() + "/v1/oauth2/token", auth=(client_id, secret),
                               data={"grant_type": "client_credentials"})
            auth.raise_for_status()
            token = auth.json()["access_token"]
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            response = client.request(method, paypal_base() + path, headers=headers, json=body)
            response.raise_for_status()
            return response.json() if response.content else {}
    except (httpx.HTTPError, KeyError, ValueError):
        # Do not return/log provider bodies or credentials.
        raise HTTPException(503, "PayPal could not confirm this request. Please try again.")


def checked_payment_url(value):
    url = urlparse(value or "")
    host = "www.paypal.com" if os.getenv("PAYPAL_ENVIRONMENT", "sandbox") == "live" else "www.sandbox.paypal.com"
    if url.scheme != "https" or url.hostname != host or not url.path.startswith("/ncp/payment/") or url.username:
        raise HTTPException(503, "PayPal returned an unexpected checkout address")
    return value


def checkout_view(row):
    return {"id": row["id"], "pack_id": row["pack_id"], "credits": row["credits"],
            "amount_cents": row["amount_cents"], "status": row["status"], "provider": row["provider"],
            "payment_url": row["payment_url"], "paypal_order_id": row["resource_id"] if row["provider"] == "google_pay" else None}


def grant_purchase(db, checkout_id, payment_id, cents, currency, merchant_id):
    if currency != "USD" or not merchant_id or merchant_id != os.getenv("PAYPAL_MERCHANT_ID"):
        raise HTTPException(400, "Payment recipient or currency did not match")
    row = db.execute("SELECT * FROM credit_checkouts WHERE id=?", (checkout_id,)).fetchone()
    if not row or row["amount_cents"] != cents:
        raise HTTPException(400, "Payment did not match the selected credit pack")
    used = db.execute("SELECT checkout_id FROM credit_payments WHERE payment_id=?", (payment_id,)).fetchone()
    if used and used["checkout_id"] != checkout_id:
        raise HTTPException(409, "This payment has already been applied")
    if used:
        return
    db.execute("INSERT INTO credit_payments(payment_id,checkout_id,owner_id,amount_cents,credits) VALUES (?,?,?,?,?)",
               (payment_id, checkout_id, row["owner_id"], cents, row["credits"]))
    entry(db, row["owner_id"], row["credits"], "purchase", payment_id)
    db.execute("UPDATE credit_checkouts SET status='paid',payment_id=? WHERE id=?", (payment_id, checkout_id))


def reverse_purchase(db, payment_id, refund_id, cents=None):
    row = db.execute("SELECT * FROM credit_payments WHERE payment_id=?", (payment_id,)).fetchone()
    if not row:
        raise HTTPException(409, "The original payment is not available yet; retry notification")
    if db.execute("SELECT 1 FROM credit_ledger WHERE kind='payment_refund' AND reference=?", (refund_id,)).fetchone():
        return
    refunded = min(row["amount_cents"], row["refunded_cents"] + (cents if cents is not None else row["amount_cents"]))
    target = (row["credits"] * refunded + row["amount_cents"] - 1) // row["amount_cents"]
    entry(db, row["owner_id"], -(target-row["reversed_credits"]), "payment_refund", refund_id)
    db.execute("UPDATE credit_payments SET refunded_cents=?,reversed_credits=? WHERE payment_id=?", (refunded,target,payment_id))
    db.execute("UPDATE credit_checkouts SET refunded_cents=?,reversed_credits=?,status=? WHERE id=? AND payment_id=?",
               (refunded, target, "refunded" if refunded == row["amount_cents"] else "partially_refunded", row["checkout_id"], payment_id))


def payment_from_order(order):
    units = order.get("purchase_units", [])
    if len(units) != 1:
        raise HTTPException(400, "Unexpected purchase contents")
    unit = units[0]
    captures = unit.get("payments", {}).get("captures", [])
    if len(captures) != 1 or captures[0].get("status") != "COMPLETED":
        raise HTTPException(409, "Payment is still awaiting confirmation")
    capture = captures[0]
    # PayPal can supply reference_id='default'. Never let that mask the
    # server-generated product SKU when resolving a Payment Link purchase.
    items = unit.get("items", [])
    sku = items[0].get("sku", "") if len(items) == 1 else ""
    candidates = [unit.get("custom_id"), unit.get("reference_id"), sku.removeprefix("LX-") if sku.startswith("LX-") else None]
    checkout_id = next((value for value in candidates if isinstance(value,str) and
        re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",value)),None)
    return (checkout_id, capture["id"], money_cents(capture["amount"]["value"]),
            capture["amount"]["currency_code"], unit.get("payee", {}).get("merchant_id"))


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_id: Literal["starter", "regular", "frequent"]
    provider: Literal["paypal_link", "google_pay"] = "paypal_link"
    request_key: str


class GoogleCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str


def create_router(authenticate):
    router = APIRouter(prefix="/api/v1/credits", tags=["Credit wallet"])

    @router.get("/catalog")
    def get_catalog():
        return JSONResponse(catalog(), headers={"Cache-Control": "no-store"})

    @router.get("/wallet")
    def get_wallet(owner=Depends(authenticate)):
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            reconcile(db, owner)
            record = wallet(db, owner)
            history = [dict(r) for r in db.execute(
                "SELECT delta,kind,created FROM credit_ledger WHERE owner_id=? ORDER BY created DESC LIMIT 30", (owner,))]
            return JSONResponse({"balance": max(0, record["balance"]), "credit_debt": max(0, -record["balance"]),
                                 "history": history}, headers={"Cache-Control": "private, no-store"})

    @router.post("/checkouts", status_code=201)
    def create_checkout(data: CheckoutCreate, owner=Depends(authenticate)):
        from lost_found import limited
        if not payment_ready() or (data.provider == "google_pay" and not google_ready()):
            raise HTTPException(503, "Credit purchases are not available yet")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", data.request_key):
            raise HTTPException(422, "Invalid checkout reference")
        limited("credit-checkout:" + owner, 12)
        pack = PACKS[data.pack_id]
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            wallet(db, owner)
            prior = db.execute("SELECT * FROM credit_checkouts WHERE owner_id=? AND request_key=?", (owner, data.request_key)).fetchone()
            if prior:
                if prior["pack_id"] != data.pack_id or prior["provider"] != data.provider:
                    raise HTTPException(409, "This checkout reference belongs to a different purchase")
                if prior["resource_id"]:
                    return checkout_view(prior)
                checkout_id = prior["id"]
            else:
                checkout_id = str(uuid4())
                db.execute("""INSERT INTO credit_checkouts
                    (id,owner_id,pack_id,amount_cents,credits,provider,status,created,request_key)
                    VALUES (?,?,?,?,?,?,'creating',?,?)""", (checkout_id, owner, data.pack_id,
                    pack["amount_cents"], pack["credits"], data.provider, time.time(), data.request_key))
        amount = f"{pack['amount_cents']/100:.2f}"
        return_url = origin() + "/?" + urlencode({"wallet": "return", "checkout": checkout_id})
        if data.provider == "paypal_link":
            result = paypal_call("POST", "/v1/checkout/payment-resources", request_id=checkout_id, body={
                "integration_mode": "LINK", "type": "BUY_NOW", "reusable": "MULTIPLE",
                "return_url": return_url,
                "line_items": [{"name": f"LockX — {pack['credits']} verification credits", "product_id": "LX-" + checkout_id,
                    "description": "One credit covers one item verification. One-time purchase. No subscription.",
                    "unit_amount": {"currency_code": "USD", "value": amount}, "collect_shipping_address": False}],
            })
            payment_url = next((x.get("href") for x in result.get("links", []) if x.get("rel") == "payment_link"), None)
            payment_url = checked_payment_url(payment_url)
        else:
            result = paypal_call("POST", "/v2/checkout/orders", request_id=checkout_id, body={
                "intent": "CAPTURE", "purchase_units": [{"reference_id": checkout_id, "custom_id": checkout_id,
                    "payee": {"merchant_id": os.environ["PAYPAL_MERCHANT_ID"]},
                    "description": f"LockX — {pack['credits']} verification credits",
                    "amount": {"currency_code": "USD", "value": amount}}],
                "application_context": {"shipping_preference": "NO_SHIPPING"},
                "payment_source": {"google_pay": {"attributes": {"verification": {"method": "SCA_WHEN_REQUIRED"}}}},
            })
            payment_url = None
        if not result.get("id"):
            raise HTTPException(503, "PayPal could not create the checkout")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE credit_checkouts SET resource_id=?,payment_url=?,status='awaiting_payment' WHERE id=? AND status='creating'",
                       (result["id"], payment_url, checkout_id))
            return checkout_view(db.execute("SELECT * FROM credit_checkouts WHERE id=?", (checkout_id,)).fetchone())

    @router.get("/checkouts/{checkout_id}")
    def get_checkout(checkout_id: str, owner=Depends(authenticate)):
        with database() as db:
            row = db.execute("SELECT * FROM credit_checkouts WHERE id=? AND owner_id=?", (checkout_id, owner)).fetchone()
            if not row:
                raise HTTPException(404, "Checkout not found")
            return JSONResponse(checkout_view(row), headers={"Cache-Control": "private, no-store"})

    @router.post("/checkouts/{checkout_id}/capture")
    def capture_google(checkout_id: str, data: GoogleCapture, owner=Depends(authenticate)):
        with database() as db:
            row = db.execute("SELECT * FROM credit_checkouts WHERE id=? AND owner_id=?", (checkout_id, owner)).fetchone()
            if not row or row["provider"] != "google_pay" or row["resource_id"] != data.order_id:
                raise HTTPException(404, "Checkout not found")
            if row["status"] == "paid":
                return {"status": "paid"}
        # Only capture a genuine approved Google Pay order, not a client assertion.
        details = paypal_call("GET", "/v2/checkout/orders/" + data.order_id)
        if details.get("status") == "APPROVED":
            details = paypal_call("POST", "/v2/checkout/orders/" + data.order_id + "/capture",
                                  request_id="capture-" + checkout_id, body={})
        parsed = payment_from_order(details)
        if parsed[0] != checkout_id:
            raise HTTPException(400, "Order reference did not match")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            grant_purchase(db, *parsed)
        return {"status": "paid"}

    @router.post("/paypal/webhook")
    async def paypal_webhook(request: Request):
        raw = await request.body()
        if len(raw) > 256_000:
            raise HTTPException(413, "Notification too large")
        try:
            event = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid notification")
        if not isinstance(event, dict) or not isinstance(event.get("resource", {}), dict):
            raise HTTPException(400, "Invalid notification")
        webhook_id = os.getenv("PAYPAL_WEBHOOK_ID")
        if not webhook_id:
            raise HTTPException(503, "Payment notifications are not configured")
        signature = {
            "transmission_id": request.headers.get("paypal-transmission-id"),
            "transmission_time": request.headers.get("paypal-transmission-time"),
            "cert_url": request.headers.get("paypal-cert-url"),
            "auth_algo": request.headers.get("paypal-auth-algo"),
            "transmission_sig": request.headers.get("paypal-transmission-sig"),
            "webhook_id": webhook_id, "webhook_event": event,
        }
        if any(not value for value in signature.values()):
            raise HTTPException(400, "Missing notification signature")
        verified = await run_in_threadpool(paypal_call, "POST", "/v1/notifications/verify-webhook-signature", body=signature)
        if verified.get("verification_status") != "SUCCESS":
            raise HTTPException(400, "Invalid notification signature")
        resource = event.get("resource", {})
        kind = event.get("event_type")
        if kind == "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED":
            # Hosted Payment Links identify the exact resource we created.
            # Never infer the owner from an amount, email address or item label.
            resource_id = resource.get("payment_resource_id")
            if not isinstance(resource_id, str) or not resource_id:
                raise HTTPException(400, "Missing payment link reference")
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT id FROM credit_checkouts WHERE resource_id=? AND provider='paypal_link'",
                                 (resource_id,)).fetchone()
                if not row:
                    return {"received": True}
                payment_id = resource.get("transaction_id")
                if resource.get("transaction_status") != "COMPLETED":
                    raise HTTPException(409, "Payment is still awaiting confirmation")
                if not isinstance(payment_id, str) or not re.fullmatch(r"[A-Z0-9]{10,32}", payment_id):
                    raise HTTPException(400, "Missing payment transaction reference")
                amount, payee = resource.get("gross_amount"), resource.get("payee")
                if not isinstance(amount, dict) or not isinstance(payee, dict):
                    raise HTTPException(400, "Invalid payment details")
                grant_purchase(db, row["id"], payment_id, money_cents(amount.get("value")),
                               amount.get("currency_code"), payee.get("merchant_id"))
        elif kind == "PAYMENT.CAPTURE.COMPLETED":
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            if not order_id or not re.fullmatch(r"[A-Z0-9]{10,32}", order_id):
                raise HTTPException(400, "Missing payment order reference")
            parsed = payment_from_order(await run_in_threadpool(paypal_call, "GET", "/v2/checkout/orders/" + order_id))
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                # Ignore this account's other products; never attach them by amount/email.
                # Payment Links use their native event above. Processing both
                # event families could grant a hosted purchase twice.
                if not db.execute("SELECT 1 FROM credit_checkouts WHERE id=? AND provider='google_pay' AND resource_id=?",
                                  (parsed[0], order_id)).fetchone():
                    return {"received": True}
                grant_purchase(db, *parsed)
        elif kind in {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}:
            ids = resource.get("supplementary_data", {}).get("related_ids", {})
            payment_id = ids.get("capture_id") or (resource.get("id") if kind.endswith("REVERSED") else None)
            if not payment_id:
                # PayPal refund representations may expose their capture as an up link.
                for link in resource.get("links", []):
                    match = re.search(r"/v2/payments/captures/([A-Z0-9]+)$", link.get("href", ""))
                    if link.get("rel") == "up" and match:
                        payment_id = match.group(1)
            if payment_id:
                with database() as db:
                    db.execute("BEGIN IMMEDIATE")
                    # Ask PayPal to retry if a refund arrived before its capture.
                    # Acknowledge only after the reversal is durably recorded.
                    amount = resource.get("amount", {})
                    if amount.get("currency_code", "USD") != "USD" or not resource.get("id"):
                        raise HTTPException(400, "Invalid payment refund")
                    reverse_purchase(db, payment_id, resource["id"], money_cents(amount["value"]) if "value" in amount else None)
        return {"received": True}

    @router.post("/paypal/ipn")
    async def paypal_ipn(request: Request):
        raw = await request.body()
        if len(raw) > 64_000:
            raise HTTPException(413, "Notification too large")
        host = "https://ipnpb.paypal.com" if os.getenv("PAYPAL_ENVIRONMENT", "sandbox") == "live" else "https://ipnpb.sandbox.paypal.com"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                verified = await client.post(host + "/cgi-bin/webscr", content=b"cmd=_notify-validate&" + raw,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                verified.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "Notification verification unavailable")
        if verified.text.strip() != "VERIFIED":
            raise HTTPException(400, "Invalid payment notification")
        try:
            fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            raise HTTPException(400, "Invalid notification encoding")
        if any(len(values) != 1 for values in fields.values()):
            raise HTTPException(400, "Duplicate notification fields")
        data = {key: values[0] for key, values in fields.items()}
        expected_test = os.getenv("PAYPAL_ENVIRONMENT", "sandbox") != "live"
        if bool(data.get("test_ipn")) != expected_test:
            raise HTTPException(400, "Payment environment did not match")
        reference = data.get("item_number") or data.get("item_number1")
        if not reference or not reference.startswith("LX-"):
            return {"received": True}
        checkout_id = reference.removeprefix("LX-")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            if data.get("payment_status") == "Completed":
                grant_purchase(db, checkout_id, data["txn_id"], money_cents(data.get("mc_gross")),
                               data.get("mc_currency"), data.get("receiver_id"))
            elif data.get("payment_status") in {"Refunded", "Reversed"}:
                if data.get("receiver_id") != os.getenv("PAYPAL_MERCHANT_ID") or data.get("mc_currency") != "USD":
                    raise HTTPException(400, "Payment recipient or currency did not match")
                try:
                    amount = abs(Decimal(data.get("mc_gross", "0")))
                except InvalidOperation:
                    raise HTTPException(400, "Invalid payment amount")
                reverse_purchase(db, data.get("parent_txn_id"), data["txn_id"], money_cents(amount) if amount else None)
        return {"received": True}

    return router
