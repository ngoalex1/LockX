import copy
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException

import credit_refunds as refunds
import credit_wallet as credits


CAPTURE = "CAPTURE123456789"
ORDER = "ORDER12345678900"
REFUND = "REFUND1234567890"


@pytest.fixture
def paid(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    for key, value in {"PAYPAL_ENVIRONMENT": "sandbox", "PAYPAL_CLIENT_ID": "test",
                       "PAYPAL_CLIENT_SECRET": "test", "PAYPAL_MERCHANT_ID": "MERCHANT"}.items():
        monkeypatch.setenv(key, value)
    # Refund recovery must keep working even when new purchases are disabled.
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "0")
    with credits.database() as db:
        credits.wallet(db, "alice")
        checkout = str(uuid4())
        db.execute("""INSERT INTO credit_checkouts
            (id,owner_id,pack_id,amount_cents,credits,provider,status,created,request_key,resource_id)
            VALUES (?,'alice','starter',100,2,'paypal_link','awaiting_payment',?,?,?)""",
            (checkout, time.time(), str(uuid4()), "PLB-"+checkout))
        credits.grant_purchase(db, checkout, CAPTURE, 100, "USD", "MERCHANT")
    capture = {"id": CAPTURE, "status": "PARTIALLY_REFUNDED",
        "amount": {"currency_code": "USD", "value": "1.00"},
        "payee": {"merchant_id": "MERCHANT"},
        "supplementary_data": {"related_ids": {"order_id": ORDER}}}
    order = {"id": ORDER, "purchase_units": [{"payee": {"merchant_id": "MERCHANT"},
        "payments": {"captures": [{"id": CAPTURE}], "refunds": [{"id": REFUND,
            "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "0.50"}}]}}]}
    calls = []
    def provider(method, path, **kwargs):
        assert method == "GET"
        calls.append(path)
        if path == "/v2/payments/captures/"+CAPTURE:
            return copy.deepcopy(capture)
        assert path == "/v2/checkout/orders/"+ORDER
        return copy.deepcopy(order)
    monkeypatch.setattr(credits, "paypal_call", provider)
    return capture, order, calls


def wallet_balance():
    with credits.database() as db:
        return credits.wallet(db, "alice")["balance"]


def make_due():
    with credits.database() as db:
        db.execute("UPDATE credit_payment_sync SET checked=0,attempted=0")


def test_missed_partial_then_full_refund_recovers_without_duplicate_debit(paid):
    capture, order, calls = paid
    assert refunds.sync_refunds("alice") == 1
    assert wallet_balance() == 1
    assert refunds.sync_refunds("alice") == 0
    assert len(calls) == 2
    make_due()
    assert refunds.sync_refunds("alice") == 1
    assert wallet_balance() == 1
    make_due()
    capture["status"] = "REFUNDED"
    second = copy.deepcopy(order["purchase_units"][0]["payments"]["refunds"][0])
    second["id"] = "REFUND2345678901"
    order["purchase_units"][0]["payments"]["refunds"].append(second)
    assert refunds.sync_refunds() == 1
    assert wallet_balance() == 0
    make_due()
    assert refunds.sync_refunds("alice") == 0


@pytest.mark.parametrize("change", ["merchant", "capture", "order", "currency", "amount", "pending", "duplicate"])
def test_unconfirmed_or_unrelated_provider_data_never_removes_credits(paid, change):
    capture, order, _ = paid
    unit = order["purchase_units"][0]
    refund = unit["payments"]["refunds"][0]
    if change == "merchant": unit["payee"]["merchant_id"] = "OTHER"
    if change == "capture": unit["payments"]["captures"][0]["id"] = "OTHER1234567890"
    if change == "order": order["id"] = "OTHER1234567890"
    if change == "currency": refund["amount"]["currency_code"] = "EUR"
    if change == "amount": refund["amount"]["value"] = "2.00"
    if change == "pending": refund["status"] = "PENDING"
    if change == "duplicate": unit["payments"]["refunds"].append(copy.deepcopy(refund))
    assert refunds.sync_refunds("alice") == 0
    assert wallet_balance() == 2


def test_owner_scope_and_provider_failure_keep_credits_and_retry(paid, monkeypatch):
    _, _, calls = paid
    assert refunds.sync_refunds("bob") == 0
    assert not calls
    provider = credits.paypal_call
    def unavailable(*args, **kwargs):
        raise HTTPException(503, "Unavailable")
    monkeypatch.setattr(credits, "paypal_call", unavailable)
    assert refunds.sync_refunds("alice") == 0
    assert wallet_balance() == 2
    assert refunds.sync_refunds("alice") == 0
    make_due()
    monkeypatch.setattr(credits, "paypal_call", provider)
    assert refunds.sync_refunds("alice") == 1
    assert wallet_balance() == 1


def test_completed_capture_does_not_fetch_refund_order(paid):
    capture, _, calls = paid
    capture["status"] = "COMPLETED"
    assert refunds.sync_refunds("alice") == 1
    assert len(calls) == 1
    assert wallet_balance() == 2
