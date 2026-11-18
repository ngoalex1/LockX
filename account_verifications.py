"""Authenticated account dashboard; never returns recording or management keys."""
import base64
import io
import json
import math
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from PIL import Image

import verification_notifications as notifications

_thumbnails = OrderedDict()
_thumbnail_lock = threading.Lock()


def _database():
    from in_hand import database
    return database()


def _cursor(created, identifier):
    return base64.urlsafe_b64encode(json.dumps([created, identifier], separators=(",", ":")).encode()).decode().rstrip("=")


def _decode(value):
    if value is None:
        return None
    try:
        if len(value) > 180:
            raise ValueError()
        created, identifier = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        if type(created) not in {int, float} or not math.isfinite(created) or created < 0 or not notifications.owner_uuid(identifier):
            raise ValueError()
        return created, identifier
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "Invalid page cursor") from None


def _url(value):
    try:
        parsed = urlsplit(value or "")
        if len(value) <= 2000 and parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not any(ord(c) < 33 for c in value):
            return value
    except (ValueError, TypeError):
        pass
    return None


def group(db, row):
    import capture_attempts
    listing = json.loads(row["listing"])
    root, family = capture_attempts.family(db, row["id"])
    attempts = [notifications.attempt_summary(db, attempt) for attempt in family]
    latest = attempts[-1]
    preview = db.execute("SELECT id FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid LIMIT 1", (root["id"],)).fetchone()
    count = db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='listing'", (root["id"],)).fetchone()[0]
    buyer = db.execute("SELECT 1 FROM ih_buyer_requests WHERE request_id=?", (root["id"],)).fetchone()
    return {"id": root["id"], "kind": "buyer" if buyer else "seller", "title": str(listing.get("title") or "Your item")[:160],
            "listing_url": _url(listing.get("listing_url")), "created": root["created"], "updated": latest["updated"],
            "status": latest["status"], "analysis_status": latest["analysis_status"], "outcome": latest["outcome"],
            "verified_count": latest["verified_count"], "total_count": latest["total_count"], "root_total_count": count,
            "preview_media_id": preview["id"] if preview else None, "latest_attempt": latest, "attempts": attempts,
            "preview_url": "/account/verifications/" + root["id"] + "/thumbnail" if preview else None,
            "unread_count": notifications.unread_count(db, root["owner_id"], root["id"])}


def create_router(authenticate):
    router = APIRouter(prefix="/api/v1/account", tags=["account verifications"])

    def owner(value=Depends(authenticate)):
        identifier = notifications.owner_uuid(value)
        if not identifier:
            raise HTTPException(401, "Sign in to your LockX account")
        return identifier

    def private(response):
        response.headers["Cache-Control"] = "private, no-store"

    @router.get("/verifications")
    def dashboard(response: Response, kind: str = Query("all", pattern="^(all|buyer|seller)$"), limit: int = Query(20, ge=1, le=50), cursor: str | None = None, owner_id=Depends(owner)):
        private(response)
        position = _decode(cursor)
        args = [owner_id]
        query = """WITH owned AS (
            SELECT r.*,COALESCE(grand.parent_request_id,parent.parent_request_id,r.id) AS group_id
            FROM ih_requests r
            LEFT JOIN ih_capture_retries parent ON parent.request_id=r.id
            LEFT JOIN ih_capture_retries grand ON grand.request_id=parent.parent_request_id
            WHERE r.owner_id=?),
            activity AS (SELECT group_id,MAX(MAX(created,COALESCE(submitted,0),
                COALESCE((SELECT MAX(completed_at) FROM verification_notification_assessments a WHERE a.request_id=owned.id),0),
                COALESCE((SELECT MAX(created) FROM ih_events e WHERE e.request_id=owned.id),0),
                COALESCE((SELECT MAX(COALESCE(ready_at,created)) FROM verification_notifications n WHERE n.attempt_id=owned.id),0))) AS activity_at
                FROM owned GROUP BY group_id)
            SELECT r.*,a.activity_at FROM owned r JOIN activity a ON a.group_id=r.id
            WHERE r.group_id=r.id"""
        if kind != "all":
            query += (" AND " if kind == "buyer" else " AND NOT ") + "EXISTS(SELECT 1 FROM ih_buyer_requests b WHERE b.request_id=r.id)"
        if position:
            query += " AND (a.activity_at<? OR (a.activity_at=? AND r.id<?))"
            args += [position[0], position[0], position[1]]
        query += " ORDER BY a.activity_at DESC,r.id DESC LIMIT ?"
        args.append(limit + 1)
        with _database() as db:
            notifications.schema(db)
            rows = db.execute(query, args).fetchall()
            items = [group(db, row) for row in rows[:limit]]
            next_cursor = _cursor(rows[limit - 1]["activity_at"], rows[limit - 1]["id"]) if len(rows) > limit else None
            return {"items": items, "next_cursor": next_cursor, "unread_count": notifications.unread_count(db, owner_id)}

    @router.get("/verifications/{root_id}/thumbnail")
    def thumbnail(root_id: str, owner_id=Depends(owner)):
        with _database() as db:
            media = db.execute("""SELECT m.id,m.sha256 FROM ih_requests r JOIN ih_media m ON m.request_id=r.id AND m.role='listing'
                WHERE r.id=? AND r.owner_id=? AND NOT EXISTS(SELECT 1 FROM ih_capture_retries c WHERE c.request_id=r.id)
                ORDER BY m.rowid LIMIT 1""", (root_id, owner_id)).fetchone()
            if not media:
                raise HTTPException(404, "Verification image not found")
            key = (owner_id, root_id, media["sha256"])
            with _thumbnail_lock:
                content = _thumbnails.get(key)
                if content is not None:
                    _thumbnails.move_to_end(key)
            if content is None:
                original = db.execute("SELECT content FROM ih_media WHERE id=? AND request_id=?", (media["id"], root_id)).fetchone()[0]
                try:
                    with Image.open(io.BytesIO(original)) as image:
                        image.thumbnail((256, 256))
                        output = io.BytesIO()
                        image.convert("RGB").save(output, "JPEG", quality=75)
                        content = output.getvalue()
                except (OSError, ValueError, Image.DecompressionBombError):
                    raise HTTPException(404, "Verification image is unavailable") from None
                if len(content) <= 100000:
                    with _thumbnail_lock:
                        _thumbnails[key] = content
                        _thumbnails.move_to_end(key)
                        while len(_thumbnails) > 32:
                            _thumbnails.popitem(last=False)
        return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @router.post("/verifications/{root_id}/read")
    def read_group(root_id: str, response: Response, owner_id=Depends(owner)):
        private(response)
        with _database() as db:
            notifications.schema(db)
            row = db.execute("""SELECT id FROM ih_requests WHERE id=? AND owner_id=?
                AND NOT EXISTS(SELECT 1 FROM ih_capture_retries WHERE request_id=ih_requests.id)""", (root_id, owner_id)).fetchone()
            if not row:
                raise HTTPException(404, "Verification not found")
            updated = db.execute("""UPDATE verification_notifications SET read_at=?
                WHERE owner_id=? AND root_request_id=? AND ready_at IS NOT NULL AND read_at IS NULL""", (time.time(), owner_id, root_id)).rowcount
            return {"updated": updated, "unread_count": notifications.unread_count(db, owner_id)}

    @router.get("/notifications")
    def events(response: Response, limit: int = Query(20, ge=1, le=50), cursor: str | None = None, owner_id=Depends(owner)):
        private(response)
        position = _decode(cursor)
        args = [owner_id]
        query = "SELECT * FROM verification_notifications WHERE owner_id=? AND ready_at IS NOT NULL"
        if position:
            query += " AND (created<? OR (created=? AND id<?))"
            args += [position[0], position[0], position[1]]
        query += " ORDER BY created DESC,id DESC LIMIT ?"
        args.append(limit + 1)
        with _database() as db:
            notifications.schema(db)
            rows = db.execute(query, args).fetchall()
            allowed = ("id", "root_request_id", "attempt_id", "kind", "outcome", "title", "verified_count", "total_count", "created", "read_at")
            return {"items": [{key: row[key] for key in allowed} for row in rows[:limit]],
                    "next_cursor": _cursor(rows[limit - 1]["created"], rows[limit - 1]["id"]) if len(rows) > limit else None,
                    "unread_count": notifications.unread_count(db, owner_id)}

    @router.post("/notifications/{notification_id}/read")
    def read_event(notification_id: str, response: Response, owner_id=Depends(owner)):
        private(response)
        with _database() as db:
            notifications.schema(db)
            row = db.execute("SELECT id FROM verification_notifications WHERE id=? AND owner_id=? AND ready_at IS NOT NULL", (notification_id, owner_id)).fetchone()
            if not row:
                raise HTTPException(404, "Notification not found")
            updated = db.execute("UPDATE verification_notifications SET read_at=? WHERE id=? AND owner_id=? AND read_at IS NULL", (time.time(), notification_id, owner_id)).rowcount
            return {"updated": updated, "unread_count": notifications.unread_count(db, owner_id)}

    return router
