"""Recover missed PayPal refund notifications from authenticated order records."""
import asyncio
import logging
import os
import re
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

import credit_wallet as credits

log = logging.getLogger("lockx.credits.refunds")
PROVIDER_ID = re.compile(r"[A-Z0-9]{10,32}")


def confirmed_refunds(payment):
    """Read only the saved capture; never accept a browser-supplied refund."""
    payment_id = payment["payment_id"]
    if not PROVIDER_ID.fullmatch(payment_id):
        raise ValueError("Invalid saved capture")
    capture = credits.paypal_call("GET", "/v2/payments/captures/" + payment_id)
    if (capture.get("id") != payment_id
            or capture.get("amount", {}).get("currency_code") != "USD"
            or credits.money_cents(capture.get("amount", {}).get("value")) != payment["amount_cents"]
            or capture.get("payee", {}).get("merchant_id") != os.getenv("PAYPAL_MERCHANT_ID")):
        raise ValueError("Capture did not match saved payment")
    if capture.get("status") == "COMPLETED":
        return []
    if capture.get("status") not in {"PARTIALLY_REFUNDED", "REFUNDED"}:
        raise ValueError("Capture is not confirmed")
    order_id = capture.get("supplementary_data", {}).get("related_ids", {}).get("order_id", "")
    if not PROVIDER_ID.fullmatch(order_id):
        raise ValueError("Missing confirmed order")
    order = credits.paypal_call("GET", "/v2/checkout/orders/" + order_id)
    units = order.get("purchase_units", [])
    if order.get("id") != order_id or len(units) != 1:
        raise ValueError("Unexpected order")
    unit = units[0]
    captures = unit.get("payments", {}).get("captures", [])
    if (len(captures) != 1 or captures[0].get("id") != payment_id
            or unit.get("payee", {}).get("merchant_id") != os.getenv("PAYPAL_MERCHANT_ID")):
        raise ValueError("Order did not match capture")
    refunds = []
    for refund in unit.get("payments", {}).get("refunds", []):
        if refund.get("status") != "COMPLETED":
            continue
        refund_id, amount = refund.get("id", ""), refund.get("amount", {})
        cents = credits.money_cents(amount.get("value"))
        if not PROVIDER_ID.fullmatch(refund_id) or amount.get("currency_code") != "USD" or cents <= 0:
            raise ValueError("Invalid confirmed refund")
        refunds.append((refund_id, cents))
    total = sum(cents for _, cents in refunds)
    if (not refunds or len({ref for ref, _ in refunds}) != len(refunds)
            or total > payment["amount_cents"]
            or (capture["status"] == "REFUNDED" and total != payment["amount_cents"])):
        raise ValueError("Refund history is incomplete")
    return refunds


def sync_refunds(owner=None):
    """Bounded sweep: active wallets every five minutes, other payments daily.

    Network requests run outside SQLite transactions. A persisted claim prevents
    wallet refreshes and multiple workers from repeatedly polling the same row.
    Fully refunded payments are excluded. Webhooks remain the immediate path.
    """
    if not all(os.getenv(key) for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_MERCHANT_ID")):
        return 0
    now, interval = time.time(), 300 if owner is not None else 86400
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("""SELECT p.* FROM credit_payments p
            LEFT JOIN credit_payment_sync s ON s.payment_id=p.payment_id
            WHERE p.refunded_cents<p.amount_cents
              AND (? IS NULL OR p.owner_id=?)
              AND COALESCE(s.checked,0)<? AND COALESCE(s.attempted,0)<?
            ORDER BY COALESCE(s.attempted,0),COALESCE(s.checked,0),p.payment_id LIMIT 10""",
            (owner, owner, now-interval, now-60)).fetchall()
        payments = [dict(row) for row in rows]
        for payment in payments:
            db.execute("""INSERT INTO credit_payment_sync(payment_id,checked,attempted)
                VALUES (?,0,?) ON CONFLICT(payment_id) DO UPDATE SET attempted=excluded.attempted""",
                (payment["payment_id"], now))
    confirmed = 0
    for payment in payments:
        try:
            refunds = confirmed_refunds(payment)
            with credits.database() as db:
                db.execute("BEGIN IMMEDIATE")
                for refund_id, cents in refunds:
                    credits.reverse_purchase(db, payment["payment_id"], refund_id, cents)
                db.execute("UPDATE credit_payment_sync SET checked=? WHERE payment_id=?",
                           (time.time(), payment["payment_id"]))
            confirmed += 1
        except (HTTPException, ValueError, TypeError, KeyError):
            # Do not expose credentials, customer data or provider response bodies.
            log.warning("PayPal refund reconciliation awaiting provider confirmation")
    return confirmed


async def worker_loop():
    while True:
        try:
            await run_in_threadpool(sync_refunds)
        except Exception:
            log.error("PayPal refund reconciliation will retry")
        await asyncio.sleep(60)
