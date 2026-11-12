import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import credit_wallet as credits
import in_hand


# Saved checkouts retain their original price and credit count after retirement.
RETIRED_PACKS = {"starter": {"amount_cents": 100, "credits": 2}}


def saved_pack(pack):
    return RETIRED_PACKS[pack] if pack in RETIRED_PACKS else credits.PACKS[pack]


def identity(authorization: str | None = Header(default=None)):
    if authorization not in {"Bearer alice", "Bearer bob"}:
        raise HTTPException(401, "Sign in")
    return authorization.split()[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("credit_refunds.sync_refunds", lambda owner=None: 0)
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "MERCHANT")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "test-webhook")
    monkeypatch.setenv("LOCKX_PAYPAL_LINKS_VALIDATED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(in_hand, "prepare_reference_features", lambda *_: None)
    monkeypatch.setattr(in_hand, "prepare_scan", lambda *_: None)
    in_hand.limited.__globals__.get("_buckets", {}).clear()
    app = FastAPI()
    app.include_router(credits.create_router(identity))
    app.include_router(in_hand.create_router(identity))
    with TestClient(app) as client:
        yield client


def checkout(owner="alice", pack="regular", provider="paypal_link"):
    checkout_id = str(uuid4())
    p = saved_pack(pack)
    with credits.database() as db:
        credits.wallet(db, owner)
        db.execute("""INSERT INTO credit_checkouts
            (id,owner_id,pack_id,amount_cents,credits,provider,status,created,request_key,resource_id)
            VALUES (?,?,?,?,?,?,'awaiting_payment',?,?,?)""",
            (checkout_id,owner,pack,p["amount_cents"],p["credits"],provider,time.time(),str(uuid4()),"PLB-"+checkout_id))
    return checkout_id


def purchase(checkout_id, payment_id="CAPTURE123", pack="regular"):
    p = saved_pack(pack)
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.grant_purchase(db,checkout_id,payment_id,p["amount_cents"],"USD","MERCHANT")


def balance(client, owner="alice"):
    response = client.get("/api/v1/credits/wallet",headers={"Authorization":"Bearer "+owner})
    assert response.status_code == 200, response.text
    return response.json()["balance"]


def create_check(client, owner="alice"):
    image = io.BytesIO()
    Image.new("RGB",(500,500),(80,120,170)).save(image,"JPEG")
    return client.post("/api/v1/in-hand/requests",headers={"Authorization":"Bearer "+owner},
        data={"payload":json.dumps({"title":"Photo verification","consent":True,"auto_publish":True,"publish_matched_photos":True})},
        files=[("photos",("card.jpg",image.getvalue(),"image/jpeg"))])


def test_exact_pack_prices_and_no_client_amount(client):
    data = client.get("/api/v1/credits/catalog").json()
    assert [(p["amount_cents"],p["credits"]) for p in data["packs"]] == [(500,10),(1000,20),(2000,40)]
    assert "test-secret" not in json.dumps(data)
    assert client.post("/api/v1/credits/checkouts",headers={"Authorization":"Bearer alice"},
        json={"pack_id":"regular","request_key":str(uuid4()),"amount_cents":1}).status_code == 422


def test_authentication_and_empty_credit_gate(client):
    assert client.get("/api/v1/credits/wallet").status_code == 401
    assert create_check(client).status_code == 402
    assert balance(client) == 0


@pytest.mark.parametrize("pack,expected", [("starter",2),("regular",10),("frequent",20),("bulk",40)])
def test_purchase_granted_once_for_duplicate_notifications(client,pack,expected):
    identifier=checkout(pack=pack)
    purchase(identifier,pack=pack)
    purchase(identifier,pack=pack)
    assert balance(client) == expected
    assert balance(client,"bob") == 0


def test_reusable_link_adds_credits_for_each_distinct_actual_payment(client):
    identifier=checkout()
    purchase(identifier,"CAPTURE001")
    purchase(identifier,"CAPTURE002")
    purchase(identifier,"CAPTURE001")
    assert balance(client) == 20


@pytest.mark.parametrize("cents,currency,merchant", [(100,"USD","MERCHANT"),(500,"EUR","MERCHANT"),(500,"USD","OTHER")])
def test_wrong_pack_currency_or_recipient_cannot_grant(client,cents,currency,merchant):
    identifier=checkout()
    with pytest.raises(HTTPException):
        with credits.database() as db:
            credits.grant_purchase(db,identifier,"BADPAYMENT",cents,currency,merchant)
    assert balance(client)==0


def test_payment_cannot_be_applied_to_another_customer(client):
    alice=checkout();bob=checkout(owner="bob")
    purchase(alice)
    with pytest.raises(HTTPException):
        purchase(bob)
    assert balance(client)==10
    assert balance(client,"bob")==0


def test_checkout_status_is_owner_scoped_and_return_url_grants_nothing(client):
    identifier=checkout()
    assert client.get("/api/v1/credits/checkouts/"+identifier,headers={"Authorization":"Bearer bob"}).status_code==404
    assert client.get("/api/v1/credits/checkouts/"+identifier,headers={"Authorization":"Bearer alice"}).json()["status"]=="awaiting_payment"
    assert balance(client)==0


def test_atomic_reservation_prevents_concurrent_overspending(client):
    identifier=checkout(pack="starter");purchase(identifier,pack="starter")
    a=create_check(client).json()["id"];b=create_check(client).json()["id"]
    with credits.database() as db:
        credits.entry(db,"alice",-1,"test_adjustment","one-available")
    def reserve(request_id):
        try:
            with credits.database() as db:
                db.execute("BEGIN IMMEDIATE")
                credits.reserve_check(db,request_id)
            return "reserved"
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(reserve,[a,b]))
    assert sorted(results,key=str)==[402,"reserved"]
    assert balance(client)==0


@pytest.mark.parametrize("outcome", ["confirmed","mismatch","inconclusive"])
def test_completed_item_check_spends_one_credit_regardless_of_photo_outcome(client,outcome):
    identifier=checkout();purchase(identifier)
    request_id=create_check(client).json()["id"]
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.reserve_check(db,request_id)
        credits.reserve_check(db,request_id)
        db.execute("UPDATE ih_requests SET status=?,analysis_status='complete' WHERE id=?",(outcome,request_id))
        credits.settle_check(db,request_id)
        credits.settle_check(db,request_id)
    assert balance(client)==9
    client.get("/api/v1/in-hand/requests/"+request_id,headers={"Authorization":"Bearer alice"})
    assert balance(client)==9


def test_technical_failure_returns_credit_once_and_retry_reserves_it_again(client):
    identifier=checkout();purchase(identifier)
    request_id=create_check(client).json()["id"]
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.reserve_check(db,request_id)
        db.execute("UPDATE ih_requests SET analysis_status='failed' WHERE id=?",(request_id,))
        credits.settle_check(db,request_id);credits.settle_check(db,request_id)
    assert balance(client)==10
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.reserve_check(db,request_id)
        db.execute("UPDATE ih_requests SET analysis_status='pending' WHERE id=?",(request_id,))
    assert balance(client)==9


def test_server_approved_quality_retry_is_included(client):
    identifier=checkout();purchase(identifier)
    parent=create_check(client).json()["id"]
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE");credits.reserve_check(db,parent)
        child=str(uuid4())
        db.execute("""INSERT INTO ih_requests(id,owner_id,token,listing,created,expires,plan)
            SELECT ?,owner_id,?,listing,created,expires,plan FROM ih_requests WHERE id=?""",(child,str(uuid4()),parent))
        credits.bind_quality_retry(db,parent,child);credits.reserve_check(db,child)
    assert balance(client)==9


def test_refund_replay_partial_and_full_refund(client):
    identifier=checkout();purchase(identifier)
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.reverse_purchase(db,"CAPTURE123","REFUND1",100)
        credits.reverse_purchase(db,"CAPTURE123","REFUND1",100)
    assert balance(client)==8
    with credits.database() as db:
        credits.reverse_purchase(db,"CAPTURE123","REFUND2",400)
    assert balance(client)==0
    purchase(identifier)
    assert balance(client)==0


def test_refund_after_spending_does_not_enable_free_future_checks(client):
    identifier=checkout(pack="starter");purchase(identifier,pack="starter")
    request_id=create_check(client).json()["id"]
    with credits.database() as db:
        credits.reserve_check(db,request_id)
        db.execute("UPDATE ih_requests SET analysis_status='complete' WHERE id=?",(request_id,))
        credits.settle_check(db,request_id)
        credits.reverse_purchase(db,"CAPTURE123","REFUNDFULL")
    wallet=client.get("/api/v1/credits/wallet",headers={"Authorization":"Bearer alice"}).json()
    assert wallet["balance"]==0 and wallet["credit_debt"]==1
    assert create_check(client).status_code==402


def test_missing_configuration_disables_purchases_without_blocking_old_records(client,monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET")
    assert not client.get("/api/v1/credits/catalog").json()["payment_ready"]
    assert client.post("/api/v1/credits/checkouts",headers={"Authorization":"Bearer alice"},
        json={"pack_id":"regular","request_key":str(uuid4())}).status_code==503
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED","0")
    assert create_check(client).status_code==201


def test_unverified_webhook_never_adds_credits(client,monkeypatch):
    identifier=checkout()
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"FAILURE"})
    response=client.post("/api/v1/credits/paypal/webhook",json={"id":"FAKE","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"custom_id":identifier}},
        headers={"paypal-transmission-id":"x","paypal-transmission-time":"x","paypal-cert-url":"x","paypal-auth-algo":"x","paypal-transmission-sig":"x"})
    assert response.status_code==400
    assert balance(client)==0


def test_verified_capture_resolves_server_order_and_adds_exact_pack(client,monkeypatch):
    identifier=checkout(provider="google_pay")
    with credits.database() as db:
        db.execute("UPDATE credit_checkouts SET resource_id='ORDER123456789' WHERE id=?", (identifier,))
    order={"purchase_units":[{"custom_id":identifier,"payee":{"merchant_id":"MERCHANT"},
        "payments":{"captures":[{"id":"CAPTURE-WEBHOOK","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    def provider(method,path,**kwargs):
        return {"verification_status":"SUCCESS"} if "verify-webhook" in path else order
    monkeypatch.setattr(credits,"paypal_call",provider)
    event={"id":"EVENT1","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"supplementary_data":{"related_ids":{"order_id":"ORDER123456789"}}}}
    headers={"paypal-transmission-id":"x","paypal-transmission-time":"x","paypal-cert-url":"x","paypal-auth-algo":"x","paypal-transmission-sig":"x"}
    for _ in range(2):
        assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=headers).status_code==200
    assert balance(client)==10


def native_link_event(identifier, **changes):
    resource={"payment_resource_id":"PLB-"+identifier,"transaction_id":"77761255S1905934F",
        "transaction_status":"COMPLETED","payee":{"merchant_id":"MERCHANT"},
        "gross_amount":{"currency_code":"USD","value":"5.00"}}
    resource.update(changes)
    return {"id":"NATIVE-EVENT","event_type":"CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED","resource":resource}


def notification_headers():
    return {"paypal-transmission-id":"x","paypal-transmission-time":"x","paypal-cert-url":"x",
        "paypal-auth-algo":"x","paypal-transmission-sig":"x"}


def test_native_link_confirmation_binds_exact_resource_and_deduplicates(client,monkeypatch):
    identifier=checkout()
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"SUCCESS"})
    event=native_link_event(identifier)
    for event_id in ["EVENT1","EVENT1","EVENT2"]:
        event["id"]=event_id
        assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=notification_headers()).status_code==200
    assert balance(client)==10
    assert balance(client,"bob")==0
    event["resource"]["transaction_id"]="88861255S1905934F"
    assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=notification_headers()).status_code==200
    assert balance(client)==20  # A distinct purchase of a reusable link.


@pytest.mark.parametrize("changes,status",[
    ({"transaction_status":"PENDING"},409),
    ({"transaction_id":""},400),
    ({"payee":{"merchant_id":"OTHER"}},400),
    ({"gross_amount":{"currency_code":"EUR","value":"5.00"}},400),
    ({"gross_amount":{"currency_code":"USD","value":"1.00"}},400),
    ({"gross_amount":[]},400),
    ({"payee":None},400),
])
def test_native_link_confirmation_rejects_wrong_payment(client,monkeypatch,changes,status):
    identifier=checkout()
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"SUCCESS"})
    response=client.post("/api/v1/credits/paypal/webhook",json=native_link_event(identifier,**changes),headers=notification_headers())
    assert response.status_code==status
    assert balance(client)==0


def test_native_link_confirmation_ignores_other_resources_and_google_orders(client,monkeypatch):
    identifier=checkout(provider="google_pay")
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"SUCCESS"})
    for ref in [identifier,str(uuid4())]:
        assert client.post("/api/v1/credits/paypal/webhook",json=native_link_event(ref),headers=notification_headers()).status_code==200
    assert balance(client)==0


def test_native_link_confirmation_requires_real_signature(client,monkeypatch):
    identifier=checkout()
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"FAILURE"})
    assert client.post("/api/v1/credits/paypal/webhook",json=native_link_event(identifier),headers=notification_headers()).status_code==400
    assert balance(client)==0


def test_capture_event_does_not_also_grant_hosted_link_purchase(client,monkeypatch):
    identifier=checkout()
    purchase(identifier)
    order={"purchase_units":[{"custom_id":identifier,"payee":{"merchant_id":"MERCHANT"},
        "payments":{"captures":[{"id":"DIFFERENT-CAPTURE","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    monkeypatch.setattr(credits,"paypal_call",lambda method,path,**kwargs:
        {"verification_status":"SUCCESS"} if "verify-webhook" in path else order)
    event={"id":"CAPTURE-EVENT","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{
        "supplementary_data":{"related_ids":{"order_id":"ORDER123456789"}}}}
    assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=notification_headers()).status_code==200
    assert balance(client)==10


@pytest.mark.parametrize("pack,amount,credit_count", [("regular","5.00",10),("frequent","10.00",20),("bulk","20.00",40)])
def test_link_creation_uses_server_pack_and_stable_request_id(client,monkeypatch,pack,amount,credit_count):
    calls=[]
    def provider(method,path,**kwargs):
        calls.append((path,kwargs))
        return {"id":"PLB-TEST","links":[{"rel":"payment_link","href":"https://www.sandbox.paypal.com/ncp/payment/PLB-TEST"}]}
    monkeypatch.setattr(credits,"paypal_call",provider)
    body={"pack_id":pack,"request_key":str(uuid4())}
    response=client.post("/api/v1/credits/checkouts",json=body,headers={"Authorization":"Bearer alice"})
    assert response.status_code==201,response.text
    again=client.post("/api/v1/credits/checkouts",json=body,headers={"Authorization":"Bearer alice"})
    assert response.json()["id"]==again.json()["id"]
    assert len(calls)==1
    assert calls[0][1]["body"]["line_items"][0]["unit_amount"]=={"currency_code":"USD","value":amount}
    assert response.json()["credits"]==credit_count
    assert calls[0][1]["body"]["line_items"][0]["collect_shipping_address"] is False
    assert balance(client)==0


def test_retired_one_dollar_pack_cannot_create_new_checkout(client,monkeypatch):
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:pytest.fail("Retired pack reached PayPal"))
    response=client.post("/api/v1/credits/checkouts",headers={"Authorization":"Bearer alice"},
        json={"pack_id":"starter","request_key":str(uuid4())})
    assert response.status_code==422
    with credits.database() as db:
        assert db.execute("SELECT count(*) FROM credit_checkouts").fetchone()[0]==0


def test_retired_pack_still_honors_saved_payment_and_refund(client,monkeypatch):
    identifier=checkout(pack="starter")
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"SUCCESS"})
    event=native_link_event(identifier,gross_amount={"currency_code":"USD","value":"1.00"})
    assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=notification_headers()).status_code==200
    assert balance(client)==2
    with credits.database() as db:
        credits.reverse_purchase(db,event["resource"]["transaction_id"],"LEGACY-REFUND",100)
    assert balance(client)==0


def test_refund_before_capture_is_retried_then_applied_once(client,monkeypatch):
    identifier=checkout()
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"verification_status":"SUCCESS"})
    event={"id":"REFUND-EVENT","event_type":"PAYMENT.CAPTURE.REFUNDED","resource":{
        "id":"REFUND-RESOURCE","supplementary_data":{"related_ids":{"capture_id":"CAPTURE123"}},
        "amount":{"value":"5.00","currency_code":"USD"}}}
    headers={"paypal-transmission-id":"x","paypal-transmission-time":"x","paypal-cert-url":"x","paypal-auth-algo":"x","paypal-transmission-sig":"x"}
    assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=headers).status_code==409
    purchase(identifier)
    for _ in range(2):
        assert client.post("/api/v1/credits/paypal/webhook",json=event,headers=headers).status_code==200
    assert balance(client)==0


def test_google_pay_capture_is_owner_scoped_and_requires_completed_payment(client,monkeypatch):
    identifier=checkout(provider="google_pay")
    order_id="ORDER123456789"
    with credits.database() as db:
        db.execute("UPDATE credit_checkouts SET resource_id=? WHERE id=?",(order_id,identifier))
    calls=[]
    def provider(method,path,**kwargs):
        calls.append((method,path))
        if method=="GET":
            return {"status":"APPROVED"}
        return {"purchase_units":[{"custom_id":identifier,"payee":{"merchant_id":"MERCHANT"},
            "payments":{"captures":[{"id":"GOOGLE-CAPTURE","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    monkeypatch.setattr(credits,"paypal_call",provider)
    endpoint="/api/v1/credits/checkouts/"+identifier+"/capture"
    body={"order_id":order_id}
    assert client.post(endpoint,json=body,headers={"Authorization":"Bearer bob"}).status_code==404
    assert not calls
    assert client.post(endpoint,json=body,headers={"Authorization":"Bearer alice"}).status_code==200
    assert client.post(endpoint,json=body,headers={"Authorization":"Bearer alice"}).status_code==200
    assert len(calls)==2 and balance(client)==10


def test_pending_google_pay_order_cannot_grant_credits(client,monkeypatch):
    identifier=checkout(provider="google_pay")
    with credits.database() as db:
        row=db.execute("SELECT resource_id FROM credit_checkouts WHERE id=?",(identifier,)).fetchone()
        order_id=row["resource_id"]
    monkeypatch.setattr(credits,"paypal_call",lambda *args,**kwargs:{"status":"CREATED","purchase_units":[{}]})
    response=client.post("/api/v1/credits/checkouts/"+identifier+"/capture",json={"order_id":order_id},headers={"Authorization":"Bearer alice"})
    assert response.status_code==409 and balance(client)==0


def test_payment_link_sku_is_resolved_when_paypal_supplies_default_reference(client):
    identifier=checkout()
    order={"purchase_units":[{"reference_id":"default","items":[{"sku":"LX-"+identifier}],
        "payee":{"merchant_id":"MERCHANT"},"payments":{"captures":[{
            "id":"SKU-CAPTURE","status":"COMPLETED","amount":{"value":"5.00","currency_code":"USD"}}]}}]}
    assert credits.payment_from_order(order)==(identifier,"SKU-CAPTURE",500,"USD","MERCHANT")


@pytest.mark.parametrize("payload", [[], {"resource":[]}])
def test_invalid_webhook_shape_is_rejected(client,payload):
    assert client.post("/api/v1/credits/paypal/webhook",json=payload).status_code==400
