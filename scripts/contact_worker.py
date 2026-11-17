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
import time
import types
from pathlib import Path
from urllib.parse import urlsplit

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


def _diagnostic_error(error):
    name = type(error).__name__
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name):
        name = 'Error'
    message = str(error).splitlines()[0][:500] if str(error) else 'Operation failed'
    if (not re.match(r'^(?:BrowserType\.launch|Page\.goto|Locator\.(?:wait_for|click|count|is_visible|is_enabled|evaluate|get_attribute)|Timeout \d+ms exceeded|Target page|net::ERR_)',message)
            or re.search(r'authorization|cookie|password|secret|post.?data|post.?body|headers?|fingerprint|[<>]', message, re.I)):
        message = 'Operation failed'
    message = re.sub(r'(?:https?|wss?|mailto):[^\s\x22\x27<>]+', '[url]', message, flags=re.I)
    message = re.sub(r'[^\s<>\x22\x27]+@[^\s<>\x22\x27]+', '[email]', message)
    message = re.sub(r'\S*[?&]\S*', '[query]', message)
    message = re.sub(r'[A-Za-z0-9_-]{24,}', '[redacted]', message)
    message = re.sub(r'[\x00-\x1f\x7f]', ' ', message)
    return {'error':name, 'message':message[:120]}


def diagnostic(path):
    """Operator-only timing trace; no relay address or page content is returned."""
    expected = Path(__file__).resolve().with_name('job.json')
    if Path(path).resolve() != expected or expected.is_symlink():
        raise ValueError('Invalid diagnostic job path')
    raw = expected.read_bytes()
    if len(raw) > 8192:
        raise ValueError('Oversized job')
    job = json.loads(raw)
    if (not isinstance(job,dict) or set(job) != {'version','nonce','listing_url'}
            or type(job.get('version')) is not int or job['version'] != 1
            or not isinstance(job.get('nonce'),str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}',job['nonce'])):
        raise ValueError('Invalid job')
    install_guards()
    os.environ['LOCKX_CRAIGSLIST_CONTACT_MODE'] = 'local'
    os.environ.pop('LOCKX_LISTING_BROWSER_EXECUTABLE',None)
    import craigslist_contact as helper
    if not helper.is_craigslist_listing_url(job.get('listing_url')):
        raise ValueError('Invalid listing')
    started = time.monotonic()
    events, patches = [], []
    output = {'version':1,'nonce':job['nonce'],'url':job['listing_url'],'status':'diagnostic'}
    budget = max(0,6000-len(json.dumps(output).encode()))
    used = 0

    def event(stage,at,**fields):
        nonlocal used
        value = {'stage':stage,'elapsed_s':round(time.monotonic()-at,3),**fields}
        size = len(json.dumps(value,separators=(',',':')).encode())+1
        if len(events)<32 and used+size<=budget:
            events.append(value)
            used += size

    def patch(owner,name,replacement):
        original = getattr(owner,name)
        patches.append((owner,name,original))
        setattr(owner,name,replacement)
        return original

    def timed(owner,name,stage):
        original = getattr(owner,name)
        async def wrapped(*args,**kwargs):
            at = time.monotonic()
            try:
                value = await original(*args,**kwargs)
                # Never include a returned mailbox, locator, browser or page.
                event(stage,at)
                return value
            except BaseException as error:
                event(stage,at,**_diagnostic_error(error))
                raise
        patch(owner,name,wrapped)

    original_fetch = helper._Traffic.fetch
    original_visible = helper._visible_email
    original_click = helper._click_one

    async def click(locator):
        at = time.monotonic()
        try:
            value = await original_click(locator)
            event('click',at)
            return value
        except BaseException as error:
            event('click',at,**_diagnostic_error(error))
            page = getattr(locator,'page',None)
            if page is not None:
                check = time.monotonic()
                try:
                    present = bool(await asyncio.wait_for(original_visible(page),timeout=.25))
                    event('late-relay-present' if present else 'late-relay-absent',check)
                except BaseException as check_error:
                    event('late-relay-check',check,error=_diagnostic_error(check_error)['error'])
                check = time.monotonic()
                try:
                    option = page.locator('button.reply-option-header').filter(has_text=re.compile(r'^\s*email\s*$',re.I))
                    present = bool(await asyncio.wait_for(option.count(),timeout=.25))
                    event('email-option-present' if present else 'email-option-absent',check)
                except BaseException as check_error:
                    event('email-option-check',check,error=_diagnostic_error(check_error)['error'])
            raise

    def reply_json(body,at):
        # Observability only: never return response values, messages, tokens,
        # relay addresses or nested content. Only bounded identifier keys and
        # exact, known machine error codes can leave this process.
        if len(body)>16384:
            return
        try:
            value = json.loads(body)
        except (ValueError,UnicodeError,TypeError):
            return
        if not isinstance(value,dict):
            return
        keys = sorted(key for key in value if isinstance(key,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,31}',key))[:8]
        known = {
            'captcha':'captcha','captcha_required':'captcha','challenge_required':'captcha','verify_human':'captcha',
            'login_required':'login','sign_in_required':'login','signin_required':'login','authentication_required':'login',
            'rate_limit':'rate_limit','rate_limited':'rate_limit','rate_limit_exceeded':'rate_limit','too_many_requests':'rate_limit',
            'blocked':'blocked','access_denied':'blocked','ip_blocked':'blocked',
            'expired':'token_invalid','token_expired':'token_invalid','invalid_token':'token_invalid','invalid_reply_token':'token_invalid',
            'not_found':'unavailable','no_reply':'unavailable','reply_unavailable':'unavailable'}
        code = 'unknown'
        for key in ('code','error_code','error','errors','status','reason'):
            candidate = value.get(key)
            if isinstance(candidate,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,31}',candidate):
                classified = known.get(candidate.lower().replace('-','_'))
                if classified:
                    code = classified
                    break
            elif type(candidate) is int and candidate in {401,403,429}:
                code = {401:'login',403:'blocked',429:'rate_limit'}[candidate]
                break
        event('reply-response',at,error=('keys_'+'_'.join(keys))[:190],resource='code_'+code)

    async def fetch(traffic,request):
        at = time.monotonic()
        try:
            value = await original_fetch(traffic,request)
            host = urlsplit(request.url).hostname or ''
            host = host.lower() if re.fullmatch(r'(?:[a-z0-9-]+\.)*craigslist\.org',host.lower()) else '[other]'
            resource = request.resource_type if request.resource_type in {'document','script','stylesheet','xhr','fetch'} else 'other'
            event('fetch',at,host=host,resource=resource,
                  http_status=value[0] if type(value[0]) is int else None,bytes=len(value[2]))
            if resource in {'xhr','fetch'}:
                reply_json(value[2],at)
            return value
        except BaseException as error:
            # Network exceptions may embed request/response data. Class only.
            event('fetch',at,error=_diagnostic_error(error)['error'])
            raise

    result = {'status':'unavailable','email':None}
    try:
        patch(helper._Traffic,'fetch',fetch)
        timed(helper,'_reveal','reveal')
        patch(helper,'_click_one',click)
        timed(helper,'_visible_email','visible-email')
        from playwright.async_api import BrowserType
        timed(BrowserType,'launch','browser-launch')
        result = asyncio.run(helper.reveal_craigslist_contact(job['listing_url']))
    except BaseException as error:
        event('worker',started,**_diagnostic_error(error))
    finally:
        for owner,name,original in reversed(patches):
            setattr(owner,name,original)
    status = result.get('status') if isinstance(result,dict) else 'unavailable'
    if status not in {'revealed','unavailable','blocked','busy'}:
        status = 'unavailable'
    email = clean_email(result.get('email')) if isinstance(result,dict) else None
    output['trace'] = {'result_status':status,
        'relay_present':bool(status=='revealed' and email and email.rsplit('@',1)[-1]=='sale.craigslist.org'),
        'elapsed_s':round(time.monotonic()-started,3),'events':events}
    return output


def main():
    # Only this process's one bounded JSON result reaches stdout. Browser/driver
    # messages and traces are never part of the public worker protocol.
    try:
        with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            if len(sys.argv) == 2 and sys.argv[1] == '--probe':
                result = probe()
            elif len(sys.argv) == 2 and sys.argv[1] == str(Path(__file__).resolve().with_name('job.json')):
                result = lookup(sys.argv[1])
            elif len(sys.argv) == 3 and sys.argv[1] == '--diagnostic':
                result = diagnostic(sys.argv[2])
            else:
                raise ValueError('Invalid worker arguments')
        encoded = json.dumps(result, separators=(',',':'))
        if len(encoded.encode()) > (7000 if result.get('status')=='diagnostic' else 4096):
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
