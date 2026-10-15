"""Loopback-only preview, isolated from the production API and Supabase.

Run: python dev_server.py [--demo] [--port 8080]
Never deploy this module: it deliberately substitutes a local preview identity.
"""
import argparse
import json
import os
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse, HTMLResponse

ROOT = Path(__file__).resolve().parent
os.environ["LOCKX_DATA_DIR"] = str(ROOT / ".lockx-data" / "preview")
# Preview must not silently use live messaging or paid analysis credentials.
for key in ("TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID", "LOCKX_MMS_NUMBER", "OPENAI_API_KEY"):
    os.environ.pop(key, None)

from main import app, current_user as who, authenticated_identity
from lost_found import database, match_sighting, now


def preview_identity():
    return "local-preview-owner"


app.dependency_overrides[who] = preview_identity
app.dependency_overrides[authenticated_identity] = lambda: {"id":"local-preview-owner","email":"preview@example.test","email_confirmed_at":"2026-01-01"}


@app.get("/", response_class=HTMLResponse)
def index():
    html = (ROOT / "index.html").read_text()
    return html.replace('<script src="app.js">', '<script>window.LOCKX_LOCAL_PREVIEW=true;window.LOCKX_API_BASE="/api/v1";</script><script src="app.js">')


@app.get("/{asset}")
def asset(asset: str):
    if asset not in {"app.js", "styles.css", "lost-found.js", "lost-found.css", "landing.css", "landing-asset.css", "lockx-city-watch-hero.png"}:
        from fastapi import HTTPException
        raise HTTPException(404)
    return FileResponse(ROOT / asset)


def seed_demo():
    reports = [
        ("demo-watch", {"title":"Rolex Submariner", "category":"Watch", "incident":"stolen", "brand":"Rolex", "model":"Submariner", "color":"Black / steel", "location":"Marina District, San Francisco", "value":1200000, "details":"Black dial, steel bracelet, small scratch near the clasp.", "serial":"DEMO-WATCH-01", "private_details":"Sample ownership evidence — demonstration only."}),
        ("demo-camera", {"title":"Leica Q3 · black", "category":"Camera", "incident":"lost", "brand":"Leica", "model":"Q3", "color":"Black", "location":"Hayes Valley, San Francisco", "value":600000, "details":"Black camera with a brown leather strap and lens hood."}),
        ("demo-bag", {"title":"Loewe Puzzle bag", "category":"Bag", "incident":"lost", "brand":"Loewe", "model":"Puzzle", "color":"Tan", "location":"SoHo, New York", "value":240000, "details":"Tan leather bag with shoulder strap and a small mark on the base."})
    ]
    with database() as db:
        for report_id, data in reports:
            data.update({"incident_date":"2026-10-14", "reward_percent":30, "publish":True})
            db.execute("INSERT OR IGNORE INTO reports(id,owner_id,data,created_at) VALUES (?,?,?,?)", (report_id,"local-preview-owner",json.dumps(data),now()))
        db.execute("INSERT OR IGNORE INTO sightings(id,data,source,analysis_status,created_at) VALUES (?,?,?,?,?)", ("demo-sighting",json.dumps({"kind":"sighted","category":"Watch","brand":"Rolex","model":"Submariner","color":"Black / steel","description":"Sample lead: black dial, steel bracelet, scratch near clasp.","location":"San Francisco · example location"}),"web","manual_review",now()))
    match_sighting("demo-sighting")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.demo:
        seed_demo()
    print(f"Local preview: http://127.0.0.1:{args.port}/#lost-found", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
