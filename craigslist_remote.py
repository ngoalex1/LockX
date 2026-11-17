"""One-use authorization for the fixed, isolated Craigslist contact worker.

Tickets are minted only by server code. Claiming a ticket performs no browser or
provider work, and a public caller cannot choose the listing or purpose there.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException, Request
import httpx
from starlette.concurrency import run_in_threadpool

REMOTE_ENDPOINT = 'https://lockx.ai/api/craigslist-contact'
REMOTE_SECONDS = 10
MAX_RESPONSE_BYTES = 8 * 1024
MAX_CLAIM_BYTES = 512
TICKET_SECONDS = 60
RATE_SECONDS = 60 * 60
MAX_LOOKUPS_PER_HOUR = 30
_TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
_remote_slots = threading.BoundedSemaphore(1)
router = APIRouter()


class TicketBusy(Exception):
    """The bounded lookup budget or active lease is already in use."""


class TicketUnavailable(Exception):
    """Ticket storage is unavailable; no remote work is authorized."""


def _canonical(url):
    from craigslist_contact import _official_url, is_craigslist_listing_url
    if not is_craigslist_listing_url(url):
        raise ValueError('A public Craigslist listing is required')
    return _official_url(url)


@contextmanager
def _database():
    configured, mount = os.getenv('LOCKX_DATA_DIR'), os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    if os.getenv('RAILWAY_ENVIRONMENT_ID') and not (configured or mount):
        raise TicketUnavailable()
    root = Path(configured or (str(Path(mount) / 'lockx') if mount else '.lockx-data'))
    db = None
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / 'craigslist-contact-tickets.sqlite3'
        db = sqlite3.connect(path, timeout=0.25, isolation_level=None)
        os.chmod(path, 0o600)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=250')
        db.execute('''CREATE TABLE IF NOT EXISTS contact_tickets (
            digest TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE,
            listing_url TEXT NOT NULL, purpose TEXT NOT NULL,
            created INTEGER NOT NULL, expires INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'issued')''')
        db.execute('CREATE INDEX IF NOT EXISTS contact_ticket_created ON contact_tickets(created)')
        db.execute('CREATE INDEX IF NOT EXISTS contact_ticket_active ON contact_tickets(expires, state)')
        yield db
    except (sqlite3.Error, OSError):
        raise TicketUnavailable() from None
    finally:
        if db is not None:
            db.close()


def _digest(ticket):
    return hashlib.sha256(ticket.encode('ascii')).hexdigest()


def _valid_ticket(ticket):
    return isinstance(ticket, str) and bool(_TOKEN.fullmatch(ticket))


def _binding(row):
    return {'version': 1, 'nonce': row['nonce'], 'listing_url': row['listing_url'],
            'purpose': row['purpose'], 'expires': row['expires']}


def issue_ticket(url, purpose='lookup'):
    """Internal-only mint; return the bearer ticket and its expected binding.

    Bootstrap is intentionally reachable only from trusted Python setup code.
    The public router exposes no mint or purpose-selection operation.
    """
    canonical = _canonical(url)
    if purpose not in {'lookup', 'bootstrap', 'diagnostic'}:
        raise ValueError('Invalid contact lookup purpose')
    now = int(time.time())
    ticket, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with _database() as db:
        db.execute('BEGIN IMMEDIATE')
        # Keep the entire rate window, including consumed/failed attempts.
        # Bounded deletion cannot monopolize SQLite after a quiet period.
        db.execute('''DELETE FROM contact_tickets WHERE digest IN (
            SELECT digest FROM contact_tickets WHERE created < ? ORDER BY created LIMIT 64)''',
            (now - RATE_SECONDS,))
        if db.execute("SELECT 1 FROM contact_tickets WHERE expires > ? AND state != 'finished' LIMIT 1", (now,)).fetchone():
            raise TicketBusy()
        if purpose in {'lookup', 'diagnostic'} and db.execute("SELECT COUNT(*) FROM contact_tickets WHERE purpose IN ('lookup','diagnostic') AND created >= ?",
                (now - RATE_SECONDS,)).fetchone()[0] >= MAX_LOOKUPS_PER_HOUR:
            raise TicketBusy()
        row = {'nonce': nonce, 'listing_url': canonical, 'purpose': purpose, 'expires': now + TICKET_SECONDS}
        db.execute('''INSERT INTO contact_tickets(digest,nonce,listing_url,purpose,created,expires,state)
            VALUES(?,?,?,?,?,?,'issued')''', (_digest(ticket), nonce, canonical, purpose, now, row['expires']))
        db.commit()
    return {'ticket': ticket, **_binding(row)}


def claim_ticket(ticket):
    """Atomically consume one valid bearer ticket, with a uniform auth failure."""
    if not _valid_ticket(ticket):
        raise HTTPException(401, 'Invalid contact lookup ticket')
    now = int(time.time())
    with _database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM contact_tickets WHERE digest=?', (_digest(ticket),)).fetchone()
        if row is None or row['state'] != 'issued' or row['expires'] <= now:
            raise HTTPException(401, 'Invalid contact lookup ticket')
        db.execute("UPDATE contact_tickets SET state='claimed' WHERE digest=? AND state='issued'", (_digest(ticket),))
        db.commit()
        return _binding(row)


def _finish_ticket(ticket):
    with _database() as db:
        changed = db.execute("UPDATE contact_tickets SET state='finished' WHERE digest=? AND state='claimed'", (_digest(ticket),)).rowcount
        return changed == 1


def _abandon_ticket(ticket):
    # An uncertain remote job retains its lease until expiry. Prevent a late
    # claim if the ticket had not yet been used when the caller gave up.
    try:
        with _database() as db:
            db.execute("UPDATE contact_tickets SET state='revoked' WHERE digest=? AND state='issued'", (_digest(ticket),))
    except TicketUnavailable:
        pass


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def _json(content):
    def invalid_number(_):
        raise ValueError('Invalid JSON number')
    return json.loads(content, object_pairs_hook=_pairs,
                      parse_constant=invalid_number)


@router.post('/api/v1/in-hand/contact-lookup/claim')
async def claim_contact_lookup(request: Request):
    # Bound bytes before JSON parsing; this endpoint never accepts a URL or
    # purpose from an unauthenticated caller and never issues another ticket.
    try:
        if request.headers.get('content-encoding', '').lower().strip() not in {'', 'identity'}:
            raise ValueError()
        mime = request.headers.get('content-type', '').split(';', 1)[0].lower().strip()
        if mime != 'application/json':
            raise ValueError()
        length = request.headers.get('content-length')
        if length and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > MAX_CLAIM_BYTES):
            raise ValueError()
        body = bytearray()
        async with asyncio.timeout(2):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_CLAIM_BYTES:
                    raise ValueError()
                body.extend(chunk)
        value = _json(bytes(body))
        if type(value) is not dict or set(value) != {'ticket'} or not _valid_ticket(value['ticket']):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError, TimeoutError):
        raise HTTPException(401, 'Invalid contact lookup ticket') from None
    try:
        binding = await run_in_threadpool(claim_ticket, value['ticket'])
    except TicketUnavailable:
        raise HTTPException(503, 'Contact lookup is temporarily unavailable') from None
    return binding


def _validate_result(value, expected):
    from listing_contacts import clean_email
    keys = {'version', 'nonce', 'listing_url', 'purpose', 'expires', 'status', 'email'}
    if type(value) is not dict or set(value) != keys:
        raise ValueError()
    if (type(value['version']) is not int or value['version'] != 1
            or type(value['expires']) is not int or value['expires'] != expected['expires']
            or not _valid_ticket(value['nonce']) or not hmac.compare_digest(value['nonce'], expected['nonce'])
            or type(value['listing_url']) is not str or value['listing_url'] != expected['listing_url']
            or type(value['purpose']) is not str or value['purpose'] != 'lookup'
            or type(value['status']) is not str or value['status'] not in {'revealed', 'unavailable', 'blocked', 'busy'}):
        raise ValueError()
    email = value['email']
    if value['status'] == 'revealed':
        cleaned = clean_email(email)
        if cleaned is None or cleaned != email or cleaned.rsplit('@', 1)[1] != 'sale.craigslist.org':
            raise ValueError()
    elif email is not None:
        raise ValueError()
    return {'status': value['status'], 'email': email}


async def reveal_remote_craigslist_contact(url):
    """Ask only the fixed Vercel worker; failures preserve the normal fallback."""
    try:
        canonical = _canonical(url)
    except ValueError:
        return {'status': 'unavailable', 'email': None}
    if not _remote_slots.acquire(blocking=False):
        return {'status': 'busy', 'email': None}
    ticket = None
    finished = False
    try:
        async with asyncio.timeout(REMOTE_SECONDS):
            expected = issue_ticket(canonical)
            ticket = expected['ticket']
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(8, connect=2, pool=1),
                    headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'}) as client:
                async with client.stream('POST', REMOTE_ENDPOINT, json={'ticket': ticket}) as response:
                    if response.status_code != 200:
                        raise ValueError()
                    if response.headers.get('content-encoding', '').lower().strip() not in {'', 'identity'}:
                        raise ValueError()
                    if response.headers.get('content-type', '').split(';', 1)[0].lower().strip() != 'application/json':
                        raise ValueError()
                    length = response.headers.get('content-length')
                    if length and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > MAX_RESPONSE_BYTES):
                        raise ValueError()
                    output = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=1024):
                        if len(output) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ValueError()
                        output.extend(chunk)
                    result = _validate_result(_json(bytes(output)), expected)
            if not _finish_ticket(ticket):
                raise ValueError()
            finished = True
            return result
    except asyncio.CancelledError:
        raise
    except TicketBusy:
        return {'status': 'busy', 'email': None}
    except (TicketUnavailable, httpx.HTTPError, OSError, ValueError, TypeError, RecursionError, TimeoutError):
        return {'status': 'unavailable', 'email': None}
    finally:
        if ticket is not None and not finished:
            _abandon_ticket(ticket)
        _remote_slots.release()
