"""Buyer-funded invitations in the same SQLite/credit transaction domain."""
import hashlib
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
import credit_wallet as credits


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ih_buyer_requests (
        request_id TEXT PRIMARY KEY REFERENCES ih_requests(id), buyer_id TEXT NOT NULL,
        listing_url TEXT NOT NULL, request_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', UNIQUE(buyer_id,request_key))""")
    db.execute("CREATE INDEX IF NOT EXISTS ih_buyer_pending ON ih_buyer_requests(state)")
    db.execute("CREATE TABLE IF NOT EXISTS ih_buyer_maintenance (id INTEGER PRIMARY KEY, checked REAL NOT NULL)")


def listing_url(value):
    """Canonicalize a reference; network access requires the separate pinned importer."""
    if not isinstance(value,str) or len(value) > 2000 or any(ord(c)<33 for c in value) or '\\' in value:
        raise HTTPException(422,"Paste a valid public listing link")
    try:
        p = urlsplit(value.strip())
        host = p.hostname.encode('idna').decode('ascii').lower() if p.hostname else ''
        if p.scheme.lower() not in {'http','https'} or not host or p.username or p.password or p.port not in {None,80,443}:
            raise ValueError()
        if host=='localhost' or host.endswith(('.localhost','.local','.internal')) or '.' not in host:
            raise ValueError()
        if re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*',host):
            raise ValueError()
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            address=None
        if address is not None:
            raise ValueError()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host):
            raise ValueError()
        return urlunsplit((p.scheme.lower(),host+(':'+str(p.port) if p.port else ''),p.path or '/',p.query,''))
    except (ValueError,UnicodeError):
        raise HTTPException(422,"Use a public HTTP or HTTPS listing link without sign-in details") from None


def fingerprint(listing, photos):
    return hashlib.sha256(json.dumps([listing,[hashlib.sha256(p).hexdigest() for p in photos]],sort_keys=True).encode()).hexdigest()


def find_request(db, buyer_id, request_key, payload_hash):
    schema(db)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_key or ''):
        raise HTTPException(422,"Invalid request reference. Refresh and try again")
    prior=db.execute('SELECT * FROM ih_buyer_requests WHERE buyer_id=? AND request_key=?',(buyer_id,request_key)).fetchone()
    if prior and prior['payload_hash']!=payload_hash:
        raise HTTPException(409,"This request reference belongs to different listing photos")
    return prior


def create_request(db, request_id, buyer_id, url, request_key, payload_hash):
    schema(db)
    row=db.execute('SELECT * FROM ih_requests WHERE id=? AND owner_id=?',(request_id,buyer_id)).fetchone()
    if not row or row['submitted'] or row['status']!='waiting':
        raise HTTPException(409,"Create a fresh buyer request")
    db.execute('INSERT INTO ih_buyer_requests(request_id,buyer_id,listing_url,request_key,payload_hash) VALUES (?,?,?,?,?)',
               (request_id,buyer_id,listing_url(url),request_key,payload_hash))
    credits.reserve_check(db,request_id)


def info(db,request_id):
    schema(db)
    row=db.execute('SELECT b.*,r.status,r.analysis_status,r.submitted,r.expires FROM ih_buyer_requests b JOIN ih_requests r ON r.id=b.request_id WHERE b.request_id=?',(request_id,)).fetchone()
    retake = False
    if not row:
        import capture_attempts
        try:
            root,_=capture_attempts.family(db,request_id)
        except HTTPException:
            return None
        if root['id'] != request_id:
            row=db.execute('SELECT b.*,r.status,r.analysis_status,r.submitted,r.expires FROM ih_buyer_requests b JOIN ih_requests r ON r.id=? WHERE b.request_id=?',(request_id,root['id'])).fetchone()
            retake = row is not None
    if not row:
        return None
    state=row['state']
    if retake and row['status'] in {'cancelled','declined','expired'}:
        state=row['status']
    if row['submitted']:
        state='failed' if row['analysis_status'] in {'failed','unavailable'} else 'submitted' if row['status']=='processing' else 'completed'
    elif state=='pending' and row['expires']<=time.time():
        state='expired'
    check=db.execute('SELECT state FROM credit_checks WHERE request_id=?',(request_id,)).fetchone()
    return {'state':state,'listing_url':row['listing_url'],'credit_reserved':state=='pending' and bool(check and check['state']=='reserved'),
            'credit_state':check['state'] if check else 'not_required',
            'buyer_funded':True,'expires':row['expires'], 'retake':retake,
            'can_cancel':not retake and not row['submitted'] and state=='pending',
            'can_decline':not retake and not row['submitted'] and state=='pending'}


def close(db,request_id,state,*,now=None):
    if state not in {'cancelled','declined','expired'}:
        raise ValueError('Invalid invitation state')
    schema(db)
    row=db.execute('SELECT b.*,r.submitted,r.status FROM ih_buyer_requests b JOIN ih_requests r ON r.id=b.request_id WHERE b.request_id=?',(request_id,)).fetchone()
    if not row:
        # A derived take inherits funding, never the original refundable hold.
        item=info(db,request_id)
        capture=db.execute('SELECT submitted,status FROM ih_requests WHERE id=?',(request_id,)).fetchone()
        if not item or not item.get('retake') or not capture:
            raise HTTPException(404,'Buyer request not found')
        if capture['submitted']:
            raise HTTPException(409,'This recording is already submitted; its comparison will continue')
        if capture['status'] not in {'cancelled','declined','expired'}:
            db.execute('UPDATE ih_requests SET status=? WHERE id=? AND submitted IS NULL',(state,request_id))
            db.execute('DELETE FROM ih_scan_chunks WHERE session_id IN (SELECT id FROM ih_sessions WHERE request_id=?)',(request_id,))
            db.execute('DELETE FROM ih_scan_previews WHERE session_id IN (SELECT id FROM ih_sessions WHERE request_id=?)',(request_id,))
        return info(db,request_id)
    if row['submitted'] or row['status'] not in {'waiting','capturing','expired','cancelled','declined'}:
        raise HTTPException(409,'This recording is already submitted; its comparison will continue')
    if row['state']!='pending':
        return info(db,request_id)
    changed=db.execute("UPDATE ih_buyer_requests SET state=? WHERE request_id=? AND state='pending'",(state,request_id)).rowcount
    if changed:
        now=time.time() if now is None else now
        check=db.execute('SELECT * FROM credit_checks WHERE request_id=?',(request_id,)).fetchone()
        if check and check['state']=='reserved':
            credits.entry(db,check['owner_id'],1,'invitation_release',request_id)
            db.execute("UPDATE credit_checks SET state='refunded',updated=? WHERE request_id=? AND state='reserved'",(now,request_id))
        db.execute('UPDATE ih_requests SET status=? WHERE id=? AND submitted IS NULL',(state,request_id))
        db.execute('DELETE FROM ih_scan_chunks WHERE session_id IN (SELECT id FROM ih_sessions WHERE request_id=?)',(request_id,))
        db.execute('DELETE FROM ih_scan_previews WHERE session_id IN (SELECT id FROM ih_sessions WHERE request_id=?)',(request_id,))
    return info(db,request_id)


def expire_pending(db,owner=None,now=None):
    schema(db)
    now=time.time() if now is None else now
    query="SELECT b.request_id FROM ih_buyer_requests b JOIN ih_requests r ON r.id=b.request_id WHERE b.state='pending' AND r.submitted IS NULL AND r.expires<=?"
    args=[now]
    if owner:
        query+=' AND b.buyer_id=?';args.append(owner)
    for row in db.execute(query,args).fetchall():
        close(db,row['request_id'],'expired',now=now)


def require_capture_open(db,request_id):
    item=info(db,request_id)
    if item and item['state'] not in {'pending','submitted','completed'}:
        raise HTTPException(410,'This buyer request was declined, cancelled or expired')


def maintain(db,now=None):
    """One shared minute-level sweep, called inside the worker transaction."""
    schema(db)
    now=time.time() if now is None else now
    last=db.execute('SELECT checked FROM ih_buyer_maintenance WHERE id=1').fetchone()
    if last and last['checked']>now-60:
        return
    expire_pending(db,now=now)
    db.execute('INSERT INTO ih_buyer_maintenance VALUES(1,?) ON CONFLICT(id) DO UPDATE SET checked=excluded.checked',(now,))
