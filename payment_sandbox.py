"""Temporary public checkout test harness. Never start with live credentials.

Uses the production credit router and a separate disposable test wallet. It does
not load production customer authentication, storage credentials or AI keys.
"""
import os
import asyncio
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import credit_wallet as credits
from credit_refunds import worker_loop


def build_sandbox_app():
    if (os.getenv("LOCKX_SANDBOX_TEST_SERVICE") != "1"
            or os.getenv("PAYPAL_ENVIRONMENT") != "sandbox"):
        raise RuntimeError("This test service requires explicit Sandbox configuration")
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if not domain.endswith(".up.railway.app") or urlparse("https://" + domain).netloc != domain:
        raise RuntimeError("Configure the isolated Railway test domain first")
    if not os.getenv("LOCKX_DATA_DIR", "").startswith("/data/lockx-sandbox-"):
        raise RuntimeError("Configure a separate Sandbox test database")
    credits.origin = lambda: "https://" + domain

    def test_owner():
        return "sandbox-only-test-wallet"

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker_loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="LockX disposable payment Sandbox", lifespan=lifespan)
    app.include_router(credits.create_router(test_owner))

    @app.get("/", response_class=HTMLResponse)
    def home():
        return PAGE

    @app.get("/health")
    def health():
        return {"status": "ok", "environment": "sandbox"}

    return app


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LockX payment Sandbox</title>
<style>
body{font:17px system-ui;background:#f8f0ea;color:#362a28;max-width:650px;margin:40px auto;padding:20px}
h1{font:42px Georgia;margin:20px 0}p{line-height:1.5}strong{color:#783f48}
button{font:inherit;border:0;border-radius:12px;padding:16px;background:#783f48;color:white;cursor:pointer;margin:5px 0;width:100%}
button:disabled{opacity:.5}#status{white-space:pre-wrap}aside{padding:20px;background:#fffaf6;border-radius:16px}
</style>
<p><strong>PAYPAL SANDBOX · TEST FUNDS ONLY</strong></p>
<h1>LockX checkout test.</h1>
<p>This disposable test service cannot grant live LockX credits. All testers share one test wallet. Use only PayPal Sandbox buyer accounts.</p>
<aside><p id="balance">Loading test balance…</p><p id="status" role="status"></p></aside>
<div id="packs"></div><button id="refresh">Refresh test wallet</button>
<script>
const status=document.querySelector('#status'),balance=document.querySelector('#balance');
async function api(path,options={}){const r=await fetch('/api/v1/credits'+path,{...options,cache:'no-store',headers:{'Content-Type':'application/json'}});const data=await r.json();if(!r.ok)throw Error(data.detail||'Test request failed');return data;}
async function refresh(){try{const w=await api('/wallet');balance.textContent=w.balance+' test credits available';}catch(e){status.textContent=e.message;}}
document.querySelector('#refresh').onclick=refresh;
api('/catalog').then(c=>{if(c.environment!=='sandbox')throw Error('Sandbox configuration required');for(const p of c.packs){const b=document.createElement('button');b.textContent='$'+p.amount_cents/100+' → '+p.credits+' test credits';b.onclick=async()=>{b.disabled=true;const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;try{const order=await api('/checkouts',{method:'POST',body:JSON.stringify({pack_id:p.id,provider:'paypal_link',request_key:crypto.randomUUID()})});status.textContent='Waiting for verified Sandbox payment: '+order.id;if(popup)popup.location.replace(order.payment_url);else location.assign(order.payment_url);}catch(e){popup?.close();status.textContent=e.message;}finally{b.disabled=false;}};document.querySelector('#packs').append(b);}}).catch(e=>status.textContent=e.message);
refresh();setInterval(refresh,4000);
</script></html>"""
