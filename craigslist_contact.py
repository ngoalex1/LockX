"""Reveal the email in Craigslist's public Reply UI, without contacting the seller.

This optional adapter uses a fresh anonymous browser. The browser itself has no
working network path: every accepted HTTP request is fulfilled by a bounded,
public-IP-pinned Python transport. It never follows a mailto or webmail link.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
import zlib
from urllib.parse import unquote, urljoin, urlsplit

import httpx

TOTAL_SECONDS = 8
WORK_SECONDS = 7
MAX_REQUESTS = 48
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024
MAX_TOTAL_REQUEST_BYTES = 256 * 1024
MAX_REDIRECTS = 3
_slots = threading.BoundedSemaphore(1)
_workers = set()
_HOST = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*craigslist\.org$')
_LISTING = re.compile(r'^/(?:view/d/[^/]+/[A-Za-z0-9_-]{6,80}|(?:[a-z]{3}/)?[a-z]{3}/d/[^/]+/[0-9]{6,20}\.html)/?$')
_CHALLENGE_URL = re.compile(r'(?:captcha|challenge|checkpoint|/login(?:[/?]|$)|/signin(?:[/?]|$)|/blocked(?:[/?]|$))', re.I)
_CHALLENGE_TEXT = re.compile(r'(?:verify (?:that )?you are (?:a )?human|unusual traffic|complete the security check|temporarily blocked|access denied|\bcaptcha\b|^\s*(?:sign in|log in|just a moment|security check)\b)', re.I)
_RESOURCES = {'document', 'script', 'stylesheet', 'xhr', 'fetch'}
_MIMES = {'text/html', 'application/xhtml+xml', 'text/css', 'text/javascript',
          'application/javascript', 'application/x-javascript', 'application/json',
          'text/json', 'text/plain'}


class _Unavailable(Exception):
    pass


def _official_url(value):
    """Only HTTPS URLs within Craigslist's hostname boundary, with no ambiguity."""
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise _Unavailable()
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or '\\' in value:
        raise _Unavailable()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() != 'https' or not parsed.hostname
                or not _HOST.fullmatch(parsed.hostname.lower())
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443}):
            raise _Unavailable()
        decoded = unquote(value)
        if any(ord(char) <= 32 or ord(char) == 127 for char in decoded) or '\\' in decoded:
            raise _Unavailable()
        # Encoded path separators cannot acquire a different meaning downstream.
        if re.search(r'%(?:2f|5c|25)', parsed.path, re.I):
            raise _Unavailable()
        host = parsed.hostname.lower()
        return 'https://' + host + (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
    except (ValueError, UnicodeError):
        raise _Unavailable() from None


def is_craigslist_listing_url(value):
    """A pure URL check; searches, reply endpoints, and other sites are ineligible."""
    try:
        return bool(_LISTING.fullmatch(urlsplit(_official_url(value)).path))
    except _Unavailable:
        return False


def _result(status, email=None):
    return {'status': status, 'email': email}


class _Traffic:
    def __init__(self, deadline, expected_listing=None):
        self.deadline = deadline
        self.requests = 0
        self.bytes = 0
        self.wire_bytes = 0
        self.request_bytes = 0
        self.blocked = False
        self.page = None
        self.expected_listing = expected_listing
        self.fetch_slots = asyncio.Semaphore(2)

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Unavailable()
        return remaining

    async def fetch(self, request):
        """Fetch only this observed browser request; follow no browser redirects."""
        # Lazy import avoids the listing_import -> adapter -> listing_import cycle.
        from listing_import import resolve_public

        current = _official_url(request.url)
        if request.resource_type == 'document' and self.expected_listing and current != self.expected_listing:
            raise _Unavailable()
        method = request.method.upper()
        if method not in {'GET', 'HEAD', 'POST'}:
            raise _Unavailable()
        body = request.post_data_buffer or b''
        if len(body) > MAX_REQUEST_BYTES:
            raise _Unavailable()
        observed = request.headers
        # No credentials or ambient proxy settings. Cookies can only come from
        # this newly-created context and are discarded with it after this visit.
        headers = {'Accept-Encoding': 'gzip, deflate'}
        for name in ('accept', 'accept-language', 'user-agent', 'content-type', 'x-requested-with', 'cookie'):
            value = observed.get(name)
            if value and len(value) <= 4096:
                headers[name] = value
        for name in ('origin', 'referer'):
            value = observed.get(name)
            if value:
                try:
                    normalized = _official_url(value)
                    headers[name] = ('https://' + urlsplit(normalized).hostname) if name == 'origin' else normalized
                except _Unavailable:
                    pass
        async with asyncio.timeout(min(4.5, self._remaining())):
            for hop in range(MAX_REDIRECTS + 1):
                self._remaining()
                if (self.requests >= MAX_REQUESTS or self.bytes >= MAX_TOTAL_BYTES
                        or self.wire_bytes >= MAX_TOTAL_BYTES):
                    raise _Unavailable()
                if self.request_bytes + len(body) > MAX_TOTAL_REQUEST_BYTES:
                    raise _Unavailable()
                self.requests += 1
                self.request_bytes += len(body)
                parsed = httpx.URL(current)
                addresses = await resolve_public(parsed.host)
                headers['Host'] = parsed.netloc.decode('ascii')
                outbound = httpx.Request(method, parsed.copy_with(host=addresses[0]),
                    headers=headers, content=body,
                    extensions={'sni_hostname': parsed.host,
                                'timeout': {'connect': 2, 'read': 2, 'write': 2, 'pool': 0.5}})
                async with httpx.AsyncHTTPTransport(retries=0, trust_env=False, http2=False,
                        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as transport:
                    response = await transport.handle_async_request(outbound)
                    try:
                        status = response.status_code
                        if status in {301, 302, 303, 307, 308}:
                            if hop == MAX_REDIRECTS or not response.headers.get('location'):
                                raise _Unavailable()
                            target = _official_url(urljoin(current, response.headers['location']))
                            if _CHALLENGE_URL.search(target):
                                self.blocked = True
                                raise _Unavailable()
                            if request.resource_type == 'document' and not is_craigslist_listing_url(target):
                                raise _Unavailable()
                            if request.resource_type == 'document' and self.expected_listing and target != self.expected_listing:
                                raise _Unavailable()
                            if httpx.URL(target).host != parsed.host:
                                # Anonymous session cookies never cross hosts via
                                # this manually followed redirect.
                                headers.pop('cookie', None)
                                headers.pop('origin', None)
                                headers.pop('referer', None)
                            current = target
                            if status == 303 or (status in {301, 302} and method == 'POST'):
                                method, body = 'GET', b''
                                headers.pop('content-type', None)
                            continue
                        if status in {401, 403, 407, 429}:
                            self.blocked = True
                            raise _Unavailable()
                        if not 200 <= status < 300:
                            raise _Unavailable()
                        encoding = response.headers.get('content-encoding', '').lower().strip()
                        if encoding not in {'', 'identity', 'gzip', 'deflate'}:
                            raise _Unavailable()
                        mime = response.headers.get('content-type', '').split(';', 1)[0].lower().strip()
                        if mime not in _MIMES:
                            raise _Unavailable()
                        if request.resource_type == 'document' and mime not in {'text/html', 'application/xhtml+xml'}:
                            raise _Unavailable()
                        length = response.headers.get('content-length')
                        if length and (len(length) > 12 or not length.isdecimal()
                                       or int(length) > min(MAX_RESPONSE_BYTES, MAX_TOTAL_BYTES - self.wire_bytes)):
                            raise _Unavailable()
                        output = bytearray()
                        wire_count = 0
                        decoder = zlib.decompressobj(31 if encoding == 'gzip' else 15) if encoding in {'gzip', 'deflate'} else None
                        async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                            self._remaining()
                            if wire_count + len(chunk) > MAX_RESPONSE_BYTES or self.wire_bytes + len(chunk) > MAX_TOTAL_BYTES:
                                raise _Unavailable()
                            wire_count += len(chunk)
                            self.wire_bytes += len(chunk)
                            remaining = min(MAX_RESPONSE_BYTES - len(output), MAX_TOTAL_BYTES - self.bytes)
                            try:
                                decoded = decoder.decompress(chunk, remaining + 1) if decoder else chunk
                            except zlib.error:
                                raise _Unavailable() from None
                            if len(decoded) > remaining or decoder and decoder.unconsumed_tail:
                                raise _Unavailable()
                            self.bytes += len(decoded)
                            output.extend(decoded)
                        # Never call unbounded decompress()/flush(). Incomplete
                        # streams and concatenated/trailing payloads fail closed.
                        if decoder and (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
                            raise _Unavailable()
                        # Never pass a redirect to Chromium: its routing can skip
                        # later redirect hops. Every hop above used a pinned IP.
                        response_headers = {key: value for key, value in response.headers.items()
                            if key.lower() not in {'content-encoding', 'content-length', 'transfer-encoding',
                                                   'connection', 'alt-svc', 'location', 'refresh'}}
                        return status, response_headers, bytes(output)
                    finally:
                        await response.aclose()
        raise _Unavailable()

    async def route(self, route):
        request = route.request
        try:
            _official_url(request.url)
            if _CHALLENGE_URL.search(request.url):
                self.blocked = True
                raise _Unavailable()
            if request.resource_type not in _RESOURCES:
                raise _Unavailable()
            if request.frame.page != self.page:
                raise _Unavailable()
            if request.resource_type == 'document':
                if (request.frame.parent_frame is not None or not is_craigslist_listing_url(request.url)
                        or self.expected_listing and _official_url(request.url) != self.expected_listing):
                    raise _Unavailable()
            async with self.fetch_slots:
                status, headers, body = await self.fetch(request)
            await route.fulfill(status=status, headers=headers, body=body)
        except asyncio.CancelledError:
            try:
                await route.abort()
            except Exception:
                pass
            finally:
                raise
        except Exception:
            # There is deliberately no route.continue() fallback.
            try:
                await route.abort()
            except Exception:
                pass


_INSPECT = r'''() => ({
  title: document.title.slice(0, 500),
  text: (document.body?.innerText || '').slice(0, 18000),
  challenge: [...document.querySelectorAll('iframe,[id*="captcha" i],[class*="captcha" i]')].slice(0,64).some(e => {
    const clue = [e.id, e.className, e.getAttribute('src'), e.getAttribute('title')].join(' ');
    const s = getComputedStyle(e);
    const bounds = e.getBoundingClientRect();
    return /captcha|challenge|verify.*human/i.test(clue) && bounds.width > 0 && bounds.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0;
  })
})'''


async def _blocked(page, traffic):
    if traffic.blocked:
        return True
    frames = list(page.frames)
    if len(frames) > 12:
        return True
    for frame in frames:
        if _CHALLENGE_URL.search(frame.url):
            return True
        try:
            state = await frame.evaluate(_INSPECT)
        except Exception:
            continue
        if state.get('challenge') or _CHALLENGE_TEXT.search(state.get('title', '')) or _CHALLENGE_TEXT.search(state.get('text', '')):
            return True
    return False


async def _visible_email(page):
    from listing_contacts import clean_email

    links = page.locator('div.reply-email-address > a[href^="mailto:"]')
    for index in range(min(await links.count(), 3)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        rendered = await link.evaluate(r'''element => {
          let node = element, depth = 0;
          while (node && depth++ < 64) {
            const style = getComputedStyle(node);
            if (node.hidden || node.inert || node.getAttribute('aria-hidden') === 'true' ||
                style.display === 'none' || style.visibility === 'hidden' ||
                style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
            node = node.parentElement;
          }
          return !node && !!element.getClientRects().length;
        }''')
        if not rendered:
            continue
        href = await link.get_attribute('href')
        if not isinstance(href, str) or len(href) > 4000 or not href.lower().startswith('mailto:'):
            continue
        mailbox = clean_email(unquote(href[7:].split('?', 1)[0]))
        if mailbox and mailbox.rsplit('@', 1)[1] == 'sale.craigslist.org':
            return mailbox
    return None


async def _click_one(locator):
    await locator.first.wait_for(state='visible', timeout=3000)
    visible = []
    for index in range(min(await locator.count(), 8)):
        candidate = locator.nth(index)
        if await candidate.is_visible() and await candidate.is_enabled():
            visible.append(candidate)
    if len(visible) != 1:
        raise _Unavailable()
    await visible[0].click(timeout=4500, no_wait_after=True)


async def _reveal(page, traffic, url):
    await page.goto(url, wait_until='domcontentloaded', timeout=4500)
    if _official_url(page.url) != url:
        return _result('unavailable')
    if await _blocked(page, traffic):
        return _result('blocked')
    await _click_one(page.get_by_role('button', name=re.compile(r'^reply$', re.I)))
    if _official_url(page.url) != url:
        return _result('unavailable')
    if await _blocked(page, traffic):
        return _result('blocked')
    email = await _visible_email(page)
    if not email:
        option = page.locator('button.reply-option-header').filter(has_text=re.compile(r'^\s*email\s*$', re.I))
        await _click_one(option)
        if _official_url(page.url) != url:
            return _result('unavailable')
        if await _blocked(page, traffic):
            return _result('blocked')
        # Wait only for the public UI to finish rendering its observed reply.
        await page.locator('div.reply-email-address > a[href^="mailto:"]').first.wait_for(state='visible', timeout=1400)
        if await _blocked(page, traffic):
            return _result('blocked')
        email = await _visible_email(page)
    if _official_url(page.url) != url:
        return _result('unavailable')
    return _result('revealed', email) if email else _result('unavailable')


async def _run(url, state):
    manager = driver = browser = context = None
    start_task = launch_task = None
    release = True
    result = _result('unavailable')
    traffic = _Traffic(time.monotonic() + WORK_SECONDS, expected_listing=url)
    try:
        from playwright.async_api import async_playwright

        manager = async_playwright()
        async with asyncio.timeout(WORK_SECONDS):
            # Shield acquisition so cancellation cannot lose a late-created
            # browser handle. Cleanup below retains the slot until it settles.
            start_task = asyncio.create_task(manager.start())
            driver = await asyncio.shield(start_task)
            runtime_names = {'PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'LC_CTYPE',
                             'TZ', 'SYSTEMROOT', 'WINDIR'}
            options = {'headless': True, 'chromium_sandbox': True, 'timeout': 1800,
                'env': {name: value for name, value in os.environ.items() if name in runtime_names},
                'proxy': {'server': 'http://127.0.0.1:9', 'bypass': ''},
                'args': ['--proxy-bypass-list=<-loopback>', '--disable-quic',
                         '--disable-background-networking', '--disable-component-update',
                         '--disable-domain-reliability', '--no-pings',
                         '--host-resolver-rules=MAP * ~NOTFOUND',
                         '--force-webrtc-ip-handling-policy=disable_non_proxied_udp']}
            executable = os.environ.get('LOCKX_LISTING_BROWSER_EXECUTABLE')
            if executable:
                options['executable_path'] = executable
            launch_task = asyncio.create_task(driver.chromium.launch(**options))
            browser = await asyncio.shield(launch_task)
            context = await browser.new_context(service_workers='block', accept_downloads=False,
                                                java_script_enabled=True)
            await context.route('**/*', traffic.route)
            await context.route_web_socket('**/*', lambda socket: socket.close())
            page = await context.new_page()
            traffic.page = page
            page.set_default_timeout(1400)
            page.set_default_navigation_timeout(4500)

            async def close_popup(other):
                if other != page:
                    await other.close()

            context.on('page', close_popup)
            page.on('download', lambda download: download.cancel())
            result = await _reveal(page, traffic, url)
    except asyncio.CancelledError:
        raise
    except Exception:
        result = _result('blocked' if traffic.blocked else 'unavailable')
    finally:
        state['closing'] = True
        # The caller has its own deadline and can return while this bounded
        # single worker closes. A new request stays busy until closure is real.
        try:
            if driver is None and start_task is not None:
                driver = await asyncio.shield(start_task)
            if browser is None and launch_task is not None:
                browser = await asyncio.shield(launch_task)
        except Exception:
            pass
        except asyncio.CancelledError:
            release = False
        closed = browser is None and launch_task is None
        if browser is not None:
            try:
                if context is not None:
                    await context.unroute_all(behavior='ignoreErrors')
                await browser.close()
                closed = True
            except Exception:
                pass
        if driver is not None:
            try:
                await driver.stop()
                closed = True
            except Exception:
                pass
        if release and closed:
            _slots.release()
    return result


async def reveal_craigslist_contact(url):
    """Return {status, email}; statuses: revealed, unavailable, blocked, busy."""
    if not is_craigslist_listing_url(url):
        return _result('unavailable')
    if not _slots.acquire(blocking=False):
        return _result('busy')
    state = {'closing': False}
    worker = asyncio.create_task(_run(_official_url(url), state))
    _workers.add(worker)
    worker.add_done_callback(_workers.discard)
    try:
        return await asyncio.wait_for(asyncio.shield(worker), timeout=TOTAL_SECONDS)
    except asyncio.TimeoutError:
        if not state['closing']:
            worker.cancel()
        return _result('unavailable')
    except asyncio.CancelledError:
        if not state['closing']:
            worker.cancel()
        raise
