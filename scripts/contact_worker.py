"""Standalone contact-only sandbox worker. Never imports the API or its secrets."""
import asyncio
import concurrent.futures
import contextlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import types
from pathlib import Path

# These pure guards are copied verbatim from the API modules. The regression
# suite compares their ASTs so changes cannot silently weaken this boundary.
from concurrent.futures import ThreadPoolExecutor
_dns_slots = threading.BoundedSemaphore(4)
_dns_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix='listing-dns')

class ImportUnavailable(Exception):
    """An inaccessible listing is not a failed verification or a charge."""

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

_EMAIL = re.compile(r"[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+(?:\.[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+)*@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")

_ROLE = re.compile(r'^(support|help|privacy|legal|noreply|no[._-]reply|donotreply|do[._-]not[._-]reply|abuse|webmaster|security)(?:[+._-].*)?$', re.I)

def clean_email(value):
    """One bounded ASCII mailbox, without display names, headers or recipient lists."""
    if not isinstance(value, str) or len(value) > 254 or value != value.strip():
        return None
    if not value.isascii() or not _EMAIL.fullmatch(value):
        return None
    local, domain = value.rsplit('@', 1)
    if len(local) > 64 or _ROLE.fullmatch(local) or len(domain) > 253:
        return None
    labels = domain.lower().split('.')
    if (len(labels) < 2 or not labels[-1].isalpha() or len(labels[-1]) < 2
            or labels[-1] in {'local', 'localhost', 'internal'}
            or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in labels)):
        return None
    return local + '@' + domain.lower()


def install_guards():
    transport = types.ModuleType('listing_import')
    transport.resolve_public = resolve_public
    contacts = types.ModuleType('listing_contacts')
    contacts.clean_email = clean_email
    sys.modules['listing_import'] = transport
    sys.modules['listing_contacts'] = contacts


def probe():
    # A successful VM boundary does not imply Chromium's nested sandbox works.
    # Require both an unprivileged user namespace and a real sandboxed launch.
    if os.name != 'posix' or os.geteuid() == 0:
        raise RuntimeError('Unprivileged user required')
    subprocess.run(['unshare', '--user', '--map-root-user', 'true'], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=3)
    async def launch():
        from playwright.async_api import async_playwright
        async with async_playwright() as driver:
            browser = await driver.chromium.launch(headless=True, chromium_sandbox=True,
                timeout=6000, proxy={'server':'http://127.0.0.1:9','bypass':''},
                args=['--proxy-bypass-list=<-loopback>', '--disable-quic',
                      '--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND'])
            await browser.close()
    asyncio.run(launch())
    return {'version':1, 'status':'ready', 'sandbox':True, 'userns':True}


def lookup(path):
    raw = Path(path).read_bytes()
    if len(raw) > 8192:
        raise ValueError('Oversized job')
    job = json.loads(raw)
    if (not isinstance(job, dict) or set(job) != {'version','nonce','listing_url'}
            or type(job.get('version')) is not int or job['version'] != 1
            or not isinstance(job.get('nonce'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', job['nonce'])):
        raise ValueError('Invalid job')
    install_guards()
    # This worker is the terminal local browser executor, never another API
    # client. In particular it must not inherit the API's remote dispatch mode.
    os.environ['LOCKX_CRAIGSLIST_CONTACT_MODE'] = 'local'
    os.environ.pop('LOCKX_LISTING_BROWSER_EXECUTABLE', None)
    import craigslist_contact
    if not craigslist_contact.is_craigslist_listing_url(job.get('listing_url')):
        raise ValueError('Invalid listing')
    result = asyncio.run(craigslist_contact.reveal_craigslist_contact(job['listing_url']))
    status = result.get('status') if isinstance(result,dict) else 'unavailable'
    email = clean_email(result.get('email')) if isinstance(result,dict) else None
    if status not in {'revealed','unavailable','blocked','busy'}:
        status = 'unavailable'
    if status == 'revealed' and (not email or email.rsplit('@',1)[-1] != 'sale.craigslist.org'):
        status = 'unavailable'
    return {'version':1, 'nonce':job['nonce'], 'url':job['listing_url'],
            'status':status, 'email':email if status == 'revealed' else None}


def main():
    # Only this process's one bounded JSON result reaches stdout. Browser/driver
    # messages and traces are never part of the public worker protocol.
    try:
        with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            if len(sys.argv) == 2 and sys.argv[1] == '--probe':
                result = probe()
            elif len(sys.argv) == 2 and sys.argv[1] == '/vercel/sandbox/lockx-contact/job.json':
                result = lookup(sys.argv[1])
            else:
                raise ValueError('Invalid worker arguments')
        encoded = json.dumps(result, separators=(',',':'))
        if len(encoded.encode()) > 4096:
            raise ValueError('Oversized result')
        print(encoded, flush=True)
        return 0
    except Exception:
        # The wrapper already has the bound claim and supplies unavailable;
        # malformed jobs cannot cause reflection of arbitrary values or traces.
        return 1
    finally:
        _dns_workers.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    raise SystemExit(main())
