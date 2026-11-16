"""Bounded public listing previews. No cookies, paid inference, or credit holds."""
import asyncio
import base64
import hashlib
import hmac
import io
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException
from PIL import Image

from buyer_requests import listing_url
from listing_contacts import empty_contact, extract_seller_contact, validate_contact
from lost_found import clean_photo

MAX_PHOTOS = 4
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_CANDIDATES = 24
IMPORT_SECONDS = 14
TOKEN_SECONDS = 20 * 60
_signing_key = secrets.token_bytes(32)
_slots = threading.BoundedSemaphore(4)
_dns_slots = threading.BoundedSemaphore(4)
_photo_slots = threading.BoundedSemaphore(2)
_dns_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix='listing-dns')
_photo_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='listing-photo')
_UNAVAILABLE = 'This listing could not share its photos with LockX. Try a public listing link, or add a screenshot or photos below. No credit was used.'


class ImportUnavailable(Exception):
    """An inaccessible listing is not a failed verification or a charge."""


def normalize_url(value):
    return listing_url(value)


async def _bounded_work(executor, slots, fn, *args):
    if not slots.acquire(blocking=False):
        raise ImportUnavailable()
    try:
        future = executor.submit(fn, *args)
    except BaseException:
        slots.release()
        raise
    # Cancellation of an async request cannot stop a running native worker.
    # Retain its admission slot until the actual DNS/decoder work finishes.
    future.add_done_callback(lambda _: slots.release())
    return await asyncio.wrap_future(future)


def _public_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or any((address.is_multicast, address.is_unspecified,
                                    address.is_loopback, address.is_link_local, address.is_reserved)):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'):
            return False
    return True


async def resolve_public(host):
    try:
        answers = await asyncio.wait_for(_bounded_work(_dns_workers, _dns_slots,
            socket.getaddrinfo, host, None, socket.AF_UNSPEC, socket.SOCK_STREAM), timeout=2)
    except (OSError, asyncio.TimeoutError):
        raise ImportUnavailable() from None
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    # Fail closed on mixed answers; the eventual socket uses only this numeric IP.
    if not addresses or len(addresses) > 16 or not all(_public_address(ip) for ip in addresses):
        raise ImportUnavailable()
    return addresses


async def fetch_public(url, *, kind='html'):
    limit = MAX_HTML_BYTES if kind == 'html' else MAX_IMAGE_BYTES
    current = normalize_url(url)
    for hop in range(MAX_REDIRECTS + 1):
        parsed = httpx.URL(current)
        addresses = await resolve_public(parsed.host)
        # A fresh transport prevents TLS pooling by numeric IP across hostnames.
        headers = {'Host': parsed.netloc.decode('ascii'), 'Accept-Encoding': 'identity',
                   'User-Agent': 'LockX-ListingPreview/1.0 (+https://lockx.ai)',
                   'Accept': 'text/html,application/xhtml+xml' if kind == 'html' else 'image/jpeg,image/png,image/webp'}
        outbound = httpx.Request('GET', parsed.copy_with(host=addresses[0]), headers=headers,
            extensions={'sni_hostname': parsed.host,
                        'timeout': {'connect': 3, 'read': 3, 'write': 3, 'pool': 1}})
        async with httpx.AsyncHTTPTransport(retries=0, trust_env=False, http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as transport:
            response = await transport.handle_async_request(outbound)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if hop == MAX_REDIRECTS or not response.headers.get('location'):
                        raise ImportUnavailable()
                    try:
                        current = normalize_url(urljoin(current, response.headers['location']))
                    except HTTPException:
                        raise ImportUnavailable() from None
                    continue
                if response.status_code != 200:
                    raise ImportUnavailable()
                # Reject compressed responses rather than allocating an unbounded
                # decoded gzip/brotli chunk before the byte limit can be checked.
                if response.headers.get('content-encoding', 'identity').lower().strip() not in {'', 'identity'}:
                    raise ImportUnavailable()
                content_type = response.headers.get('content-type', '').split(';', 1)[0].lower().strip()
                allowed = {'text/html', 'application/xhtml+xml'} if kind == 'html' else {'image/jpeg', 'image/png', 'image/webp', 'image/jpg'}
                if content_type not in allowed:
                    raise ImportUnavailable()
                length = response.headers.get('content-length')
                if length and (len(length) > 12 or not length.isdecimal() or int(length) > limit):
                    raise ImportUnavailable()
                output = bytearray()
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    if len(output) + len(chunk) > limit:
                        raise ImportUnavailable()
                    output.extend(chunk)
                if not output:
                    raise ImportUnavailable()
                return bytes(output), current, content_type
            finally:
                await response.aclose()
    raise ImportUnavailable()


def _text(value, limit=160):
    return ' '.join(str(value or '').replace('\x00', '').split())[:limit]


class _Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []
        self.scripts = []
        self.images = []
        self.title = []
        self.stack = []
        self.in_title = False
        self.script = None

    def handle_starttag(self, tag, pairs):
        attrs = {key.lower(): value or '' for key, value in pairs}
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            name = (attrs.get('property') or attrs.get('name') or '').lower()
            if name in {'og:title', 'twitter:title', 'og:image', 'og:image:url', 'og:image:secure_url', 'twitter:image', 'twitter:image:src'}:
                self.meta.append((name, attrs.get('content', '')[:4000]))
        if tag == 'script' and attrs.get('type', '').split(';')[0].lower() == 'application/ld+json':
            self.script = []
        if tag == 'img' and len(self.images) < MAX_CANDIDATES:
            context = ' '.join([attrs.get('class', ''), attrs.get('id', ''), attrs.get('itemprop', ''), *self.stack[-6:]])
            excluded = re.search(r'\b(header|footer|nav|aside|avatar|logo|icon|recommend|related)\b', context, re.I)
            product = re.search(r'product|listing|gallery|carousel|slide|item.?photo|main.?image|detail', context, re.I)
            tiny = any(attrs.get(k, '').isdigit() and int(attrs[k]) < 100 for k in ('width', 'height'))
            if product and not excluded and not tiny:
                source = attrs.get('data-highres') or attrs.get('data-original') or attrs.get('data-src') or attrs.get('src', '')
                srcset = attrs.get('srcset') or attrs.get('data-srcset')
                if srcset:
                    choices = [parts for v in srcset.split(',')[:32] if (parts := v.strip().split())]
                    def size(choice):
                        try: return float(choice[-1].rstrip('wx')) if len(choice) > 1 else 0
                        except ValueError: return 0
                    if choices:
                        source = max(choices, key=size)[0]
                self.images.append(source)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            if len(self.stack) < 128:
                self.stack.append(' '.join([tag, attrs.get('class', ''), attrs.get('id', '')])[:300])

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        # Tolerate malformed markup without accumulating unlimited ancestor state.
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i].split(' ', 1)[0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        if self.in_title:
            self.title.append(value[:500])
        if self.script is not None:
            self.script.append(value)


def parse_listing(content, base_url):
    parser = _Metadata()
    parser.feed(content.decode('utf-8', errors='replace'))
    candidates, names = [], []

    def image_values(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [url for entry in value[:MAX_CANDIDATES] for url in image_values(entry)][:MAX_CANDIDATES]
        if isinstance(value, dict):
            return image_values(value.get('contentUrl') or value.get('url') or [])
        return []

    def walk(value, depth=0):
        if depth > 12 or len(candidates) >= MAX_CANDIDATES:
            return
        if isinstance(value, list):
            for entry in value[:64]: walk(entry, depth+1)
        elif isinstance(value, dict):
            types = value.get('@type', [])
            if isinstance(types, str): types = [types]
            if isinstance(types, list) and any(str(t).rsplit('/', 1)[-1].lower() in {'product', 'individualproduct', 'vehicle', 'car'} for t in types):
                names.append(_text(value.get('name')))
                candidates.extend(image_values(value.get('image') or value.get('photo')))
            for key in ('@graph', 'mainEntity', 'item', 'itemListElement'):
                if key in value: walk(value[key], depth+1)

    for script in parser.scripts[:16]:
        try: walk(json.loads(script))
        except (ValueError, RecursionError): continue
    og = [value for name, value in parser.meta if name.startswith('og:image')]
    twitter = [value for name, value in parser.meta if name.startswith('twitter:image')]
    if not candidates:
        candidates = og or twitter or parser.images
    names += [value for key, value in parser.meta if key in {'og:title', 'twitter:title'}]
    title = next((name for name in names if name), _text(''.join(parser.title)))
    if re.search(r'^(log\s?in|sign\s?in|access denied|just a moment|security check|verify you are human)\b', title, re.I):
        return '', []
    urls = []
    for value in candidates[:MAX_CANDIDATES]:
        if not isinstance(value, str) or len(value) > 4000:
            continue
        try: url = normalize_url(urljoin(base_url, value.strip()))
        except HTTPException: continue
        if url not in urls:
            urls.append(url)
    return _text(title), urls[:MAX_CANDIDATES]


def _photo(content):
    # Check dimensions before allocating decoded pixels; clean_photo removes EXIF
    # and reencodes only raster formats within the existing 24 MP/1800 px limits.
    try:
        with Image.open(io.BytesIO(content)) as source:
            if min(source.size) < 120 or source.width * source.height > 24_000_000:
                raise ImportUnavailable()
        encoded = clean_photo(content)
        submitted = clean_photo(encoded)
    except (HTTPException, OSError, ValueError, Image.DecompressionBombError):
        raise ImportUnavailable() from None
    return encoded, hashlib.sha256(submitted).hexdigest()


def _sign(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    signature = hmac.new(_signing_key, body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


_INVALID_IMPORT = 'The imported listing photos or seller contact expired or changed. Import the listing again before creating a request. No credit was reserved.'


def _decode_snapshot(token, url, *, now=None):
    if not isinstance(token, str) or not 1 <= len(token) <= 32_000:
        raise HTTPException(422, _INVALID_IMPORT)
    try:
        body, signature = token.rsplit('.', 1)
        if not hmac.compare_digest(signature, hmac.new(_signing_key, body.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        snapshot = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        timestamp = time.time() if now is None else now
        if (snapshot['version'] != 1 or snapshot['listing_url'] != normalize_url(url)
                or type(snapshot['imported_at']) not in {int, float}
                or type(snapshot['expires']) not in {int, float}
                or not snapshot['imported_at'] <= timestamp < snapshot['expires']
                or snapshot['expires'] - snapshot['imported_at'] != TOKEN_SECONDS
                or not isinstance(snapshot['photos'], list) or len(snapshot['photos']) > MAX_PHOTOS):
            raise ValueError()
        resolved = normalize_url(snapshot['resolved_url'])
        snapshot['seller_contact'] = validate_contact(snapshot.get('seller_contact', empty_contact(now=snapshot['imported_at'])),
                                                     resolved, snapshot['imported_at'])
        return snapshot
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, HTTPException):
        raise HTTPException(422, _INVALID_IMPORT) from None


def validate_import_snapshot(token, url, *, now=None):
    """Verify contact provenance independently of any selected listing photos.

    This return value is safe to store; the signing token is intentionally absent.
    Photo provenance still requires validate_selection against uploaded bytes.
    """
    snapshot = _decode_snapshot(token, url, now=now)
    return {'listing_url': snapshot['listing_url'], 'imported_at': snapshot['imported_at'],
            'photos': [], 'seller_contact': snapshot['seller_contact']}


def validate_selection(token, indices, url, photos, *, now=None):
    """Bind uploaded, normalized bytes to the publicly fetched snapshot."""
    if not token and not indices:
        return None
    snapshot = _decode_snapshot(token, url, now=now)
    try:
        if (not isinstance(indices, list) or len(indices) != len(photos)
                or not 1 <= len(photos) <= MAX_PHOTOS):
            raise ValueError()
        selected, seen = [], set()
        for position, index in enumerate(indices):
            if index is None:
                continue
            if type(index) is not int or not 0 <= index < len(snapshot['photos']) or index in seen:
                raise ValueError()
            source = snapshot['photos'][index]
            digest = hashlib.sha256(photos[position]).hexdigest()
            if not hmac.compare_digest(digest, source['submitted_sha256']):
                raise ValueError()
            selected.append({'photo_index': position, 'source_url': source['source_url'], 'sha256': digest})
            seen.add(index)
        if not selected:
            raise ValueError()
        return {'listing_url': snapshot['listing_url'], 'imported_at': snapshot['imported_at'],
                'photos': selected, 'seller_contact': snapshot['seller_contact']}
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, HTTPException):
        raise HTTPException(422, _INVALID_IMPORT) from None


async def import_listing(url):
    original = normalize_url(url)
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, 'Listing imports are busy. Please try again shortly. No credit was used.', headers={'Retry-After': '5'})
    title, photos = '', []
    canonical = original
    seller_contact = None
    reveal_task = None
    try:
        async with asyncio.timeout(IMPORT_SECONDS):
            content, canonical, _ = await fetch_public(original, kind='html')
            title, candidates = parse_listing(content, canonical)
            seller_contact = extract_seller_contact(content, canonical)
            from craigslist_contact import is_craigslist_listing_url, reveal_craigslist_contact
            if is_craigslist_listing_url(canonical):
                seller_contact['contact_url']=seller_contact.get('contact_url') or canonical
                seller_contact['reveal_status']='not_needed' if seller_contact['candidates'] else 'unavailable'
                if not seller_contact['candidates']:
                    async def discover_reply():
                        try:
                            result=await reveal_craigslist_contact(canonical)
                            if not isinstance(result,dict): result={'status':'unavailable'}
                            state=result.get('status','unavailable')
                            if state not in {'revealed','unavailable','blocked','busy'}: state='unavailable'
                            from listing_contacts import clean_email
                            email=clean_email(result.get('email'))
                            if state=='revealed' and email and email.rsplit('@',1)[-1].lower()=='sale.craigslist.org':
                                seller_contact['candidates']=[{'email':email,'label':'Craigslist seller relay','source':'craigslist_reply','source_url':canonical}]
                                seller_contact['reveal_status']='revealed'
                            else:
                                seller_contact['reveal_status']='unavailable' if state=='revealed' else state
                        except Exception:
                            # Optional contact discovery cannot discard an
                            # otherwise usable photo import or spend a credit.
                            seller_contact['reveal_status']='unavailable'
                    reveal_task=asyncio.create_task(discover_reply())
            seen = set()
            # At most two image downloads at once. Never retain more than four.
            for start in range(0, min(len(candidates), 8), 2):
                async def download(source_url):
                    try:
                        content, final, _ = await fetch_public(source_url, kind='image')
                        encoded, submitted_sha = await _bounded_work(_photo_workers, _photo_slots, _photo, content)
                        return encoded, final, submitted_sha
                    except (ImportUnavailable, HTTPException, httpx.HTTPError, OSError):
                        return None
                tasks = [asyncio.create_task(download(u)) for u in candidates[start:start+min(2,MAX_PHOTOS-len(photos))]]
                try:
                    for completed in asyncio.as_completed(tasks):
                        result = await completed
                        if not result:
                            continue
                        encoded, final, digest = result
                        if digest in seen:
                            continue
                        photos.append({'encoded': encoded, 'source_url': final, 'submitted_sha256': digest})
                        seen.add(digest)
                finally:
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                if len(photos) == MAX_PHOTOS:
                    break
            if reveal_task:
                await reveal_task
    except (ImportUnavailable, HTTPException, httpx.HTTPError, OSError, TimeoutError, ValueError):
        # A partial import may still be reviewed if at least one photo finished.
        pass
    finally:
        if reveal_task and not reveal_task.done():
            reveal_task.cancel()
            await asyncio.gather(reveal_task,return_exceptions=True)
        _slots.release()
    now = time.time()
    seller_contact = seller_contact or empty_contact(now=now)
    seller_contact['detected_at'] = now
    has_contact = bool(seller_contact['candidates'] or seller_contact['contact_url'])
    if not photos and not has_contact:
        return {'status': 'unavailable', 'listing_url': original, 'title': title, 'imported_at': now,
                'expires': now, 'import_token': '', 'photos': [], 'seller_contact': seller_contact,
                'message': _UNAVAILABLE, 'max_photos': MAX_PHOTOS}
    payload = {'version': 1, 'listing_url': original, 'resolved_url': canonical, 'title': title,
               'imported_at': now, 'expires': now+TOKEN_SECONDS,
               'seller_contact': seller_contact,
               'photos': [{k:v for k,v in photo.items() if k != 'encoded'} for photo in photos]}
    return {'status': 'ready' if photos else 'unavailable', 'listing_url': original, 'title': title or 'Listing item',
            'imported_at': now, 'expires': now+TOKEN_SECONDS, 'import_token': _sign(payload),
            'seller_contact': seller_contact,
            'photos': [{'index': index, 'mime': 'image/jpeg',
                        'data_url': 'data:image/jpeg;base64,'+base64.b64encode(photo['encoded']).decode()}
                       for index,photo in enumerate(photos)], 'max_photos': MAX_PHOTOS,
            **({'message': _UNAVAILABLE} if not photos else {})}
