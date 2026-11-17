"""Public Reply adapter checks. All browser and network traffic is simulated."""
import asyncio
import gzip
import socket
import threading
import zlib
from types import SimpleNamespace

import httpx
import pytest

import craigslist_contact as contact


LISTING = 'https://www.craigslist.org/view/d/example-listing/ExampleListingToken'
RELAY = 'unit-test-relay@sale.craigslist.org'
PUBLIC_IP = '93.184.216.34'


def run(value):
    return asyncio.run(value)


@pytest.mark.parametrize('url', [LISTING, 'https://sfbay.craigslist.org/pho/d/example/1234567890.html',
                                  'https://sfbay.craigslist.org/sby/pho/d/example/1234567890.html'])
def test_recognizes_only_official_listing_paths(url):
    assert contact.is_craigslist_listing_url(url)


@pytest.mark.parametrize('url', [
    'https://www.craigslist.org/search/sss', 'https://www.craigslist.org/reply/1234',
    'https://www.craigslist.org/contactinfo/1234', 'https://craigslist.org.evil.test/pho/d/a/1234567890.html',
    'https://evilcraigslist.org/pho/d/a/1234567890.html', 'http://www.craigslist.org/pho/d/a/1234567890.html',
    'https://127.0.0.1/pho/d/a/1234567890.html', 'https://www.craigslist.org:8080/pho/d/a/1234567890.html',
    'https://user:secret@www.craigslist.org/pho/d/a/1234567890.html',
    'https://www.craigslist.org/pho/d/a%2fb/1234567890.html',
    'https://www.craigslist.org/pho/d/a%252fb/1234567890.html',
    'https://www.craigslist.org/pho/d/a%0d/1234567890.html',
    'https://www.craigslist.org\\@localhost/pho/d/a/1234567890.html', None,
])
def test_invalid_initial_url_does_not_start_worker(monkeypatch, url):
    async def unexpected(*args):
        pytest.fail('No browser should start for this URL')
    monkeypatch.setattr(contact, '_run', unexpected)
    assert not contact.is_craigslist_listing_url(url)
    assert run(contact.reveal_craigslist_contact(url)) == {'status': 'unavailable', 'email': None}


class RawStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.fixture
def network(monkeypatch):
    import listing_import
    state = {'requests': [], 'dns': {}, 'routes': {}, 'streams': [], 'transports': []}

    def resolve(host, port, *args):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))
                for ip in state['dns'].get(host, [PUBLIC_IP])]

    class Transport:
        def __init__(self, **options):
            state['transports'].append(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def handle_async_request(self, request):
            state['requests'].append(request)
            status, headers, chunks = state['routes'][(request.headers['host'], request.url.path)]
            stream = RawStream(chunks if isinstance(chunks, list) else [chunks])
            state['streams'].append(stream)
            return httpx.Response(status, headers=headers, stream=stream, request=request)

    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', Transport)
    return state


def request(url=LISTING, *, resource='document', method='GET', body=None, page=None,
            headers=None, actual_headers=None):
    provisional = headers if headers is not None else {'user-agent': 'TestBrowser', 'authorization': 'secret',
            'proxy-authorization': 'secret', 'cookie': 'anonymous_visit=1'}
    async def all_headers():
        return actual_headers if actual_headers is not None else provisional
    return SimpleNamespace(url=url, method=method, post_data_buffer=body,
        resource_type=resource, headers=provisional, all_headers=all_headers,
        frame=SimpleNamespace(page=page, parent_frame=None))


def traffic():
    import time
    return contact._Traffic(time.monotonic() + 5)


def test_every_connection_is_pinned_and_authorization_is_never_forwarded(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, {'content-type': 'text/html'}, b'<button>reply</button>')
    status, headers, body = run(traffic().fetch(request()))
    assert status == 200 and body == b'<button>reply</button>'
    outbound, = network['requests']
    assert outbound.url.host == PUBLIC_IP
    assert outbound.headers['host'] == 'www.craigslist.org'
    assert outbound.extensions['sni_hostname'] in {'www.craigslist.org', b'www.craigslist.org'}
    assert 'authorization' not in outbound.headers and 'proxy-authorization' not in outbound.headers
    assert outbound.headers['accept-encoding'] == 'gzip, deflate'
    assert all(item['trust_env'] is False for item in network['transports'])


def test_actual_anonymous_cookie_is_forwarded_when_provisional_headers_omit_it(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, {'content-type': 'text/html'}, b'public listing')
    observed = request(headers={'user-agent': 'TestBrowser'}, actual_headers={
        'user-agent': 'TestBrowser', 'cookie': 'anonymous_visit=1; public_reply_session=fixture',
        'authorization': 'Bearer never-forward', 'proxy-authorization': 'never-forward',
        'x-service-secret': 'never-forward',
    })
    assert 'cookie' not in observed.headers
    run(traffic().fetch(observed))
    outbound, = network['requests']
    assert outbound.headers['cookie'] == 'anonymous_visit=1; public_reply_session=fixture'
    assert 'authorization' not in outbound.headers and 'proxy-authorization' not in outbound.headers
    assert 'x-service-secret' not in outbound.headers


def test_actual_forwarded_header_values_keep_the_existing_length_cap(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, {'content-type': 'text/html'}, b'public listing')
    run(traffic().fetch(request(headers={}, actual_headers={
        'cookie': 'x' * 4097, 'user-agent': 'x' * 4097, 'x-requested-with': 'x' * 4097,
        'accept-language': 'x' * 4096,
    })))
    outbound, = network['requests']
    assert 'cookie' not in outbound.headers and 'user-agent' not in outbound.headers
    assert 'x-requested-with' not in outbound.headers
    assert outbound.headers['accept-language'] == 'x' * 4096


def test_distinct_set_cookie_headers_preserve_expires_commas_for_browser_fulfillment(network):
    first = 'anonymous_visit=fixture; Path=/; Secure; HttpOnly; Expires=Wed, 09 Jun 2027 10:18:14 GMT'
    second = 'public_reply_session=fixture; Domain=.craigslist.org; Path=/; Secure; SameSite=Lax'
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, [('content-type', 'text/html'), ('set-cookie', first), ('set-cookie', second)], b'listing')
    _, headers, _ = run(traffic().fetch(request()))
    assert headers['set-cookie'] == first + '\n' + second
    assert headers['set-cookie'].split('\n') == [first, second]


@pytest.mark.parametrize('target', [
    'https://evil.test/secret', 'https://www.craigslist.org.evil.test/secret',
    'http://www.craigslist.org/secret', 'http://169.254.169.254/secret',
    'https://user:pass@www.craigslist.org/secret',
])
def test_redirect_escapes_are_not_fulfilled_or_followed(network, target):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        302, {'location': target}, b'')
    with pytest.raises(contact._Unavailable):
        run(traffic().fetch(request()))
    assert len(network['requests']) == 1
    assert all(item.closed for item in network['streams'])


def test_each_redirect_is_validated_and_pinned_before_final_fulfillment(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        302, {'location': 'https://sfbay.craigslist.org/pho/d/example/1234567890.html'}, b'')
    network['routes'][('sfbay.craigslist.org', '/pho/d/example/1234567890.html')] = (
        200, {'content-type': 'text/html'}, b'final')
    status, _, body = run(traffic().fetch(request(headers={'user-agent': 'TestBrowser'}, actual_headers={
        'cookie': 'anonymous_visit=1', 'origin': 'https://www.craigslist.org', 'referer': LISTING})))
    assert status == 200 and body == b'final'
    assert len(network['requests']) == 2
    assert all(item.url.host == PUBLIC_IP for item in network['requests'])
    assert 'cookie' not in network['requests'][1].headers
    assert 'origin' not in network['requests'][1].headers and 'referer' not in network['requests'][1].headers


def test_same_host_redirect_keeps_only_the_allowed_anonymous_headers(network):
    network['routes'][('www.craigslist.org', '/first-script.js')] = (
        302, {'location': '/final-script.js'}, b'')
    network['routes'][('www.craigslist.org', '/final-script.js')] = (
        200, {'content-type': 'application/javascript'}, b'void 0;')
    run(traffic().fetch(request('https://www.craigslist.org/first-script.js', resource='script',
        headers={}, actual_headers={'cookie': 'anonymous_visit=1', 'origin': 'https://www.craigslist.org',
            'referer': LISTING, 'authorization': 'never-forward'})))
    assert len(network['requests']) == 2
    for outbound in network['requests']:
        assert outbound.headers['cookie'] == 'anonymous_visit=1'
        assert outbound.headers['origin'] == 'https://www.craigslist.org'
        assert outbound.headers['referer'] == LISTING
        assert 'authorization' not in outbound.headers


def test_dns_mixed_with_private_address_never_connects(network):
    network['dns']['www.craigslist.org'] = [PUBLIC_IP, '127.0.0.1']
    with pytest.raises(Exception):
        run(traffic().fetch(request()))
    assert not network['requests']


def test_private_redirect_dns_never_connects(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        302, {'location': 'https://sfbay.craigslist.org/pho/d/example/1234567890.html'}, b'')
    network['dns']['sfbay.craigslist.org'] = ['169.254.169.254']
    with pytest.raises(Exception):
        run(traffic().fetch(request()))
    assert len(network['requests']) == 1


def test_production_document_cannot_redirect_to_another_valid_listing(network):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        302, {'location': '/view/d/different-listing/DifferentListingToken'}, b'')
    import time
    policy = contact._Traffic(time.monotonic() + 5, expected_listing=LISTING)
    with pytest.raises(contact._Unavailable):
        run(policy.fetch(request()))
    assert len(network['requests']) == 1


def test_production_document_cannot_navigate_to_another_valid_listing(network):
    import time
    policy = contact._Traffic(time.monotonic() + 5, expected_listing=LISTING)
    with pytest.raises(contact._Unavailable):
        run(policy.fetch(request('https://www.craigslist.org/view/d/different/DifferentListingToken')))
    assert not network['requests']


@pytest.mark.parametrize('headers,chunks', [
    ({'content-type': 'text/html', 'content-encoding': 'gzip'}, [b'compressed']),
    ({'content-type': 'text/html', 'content-encoding': 'br'}, [b'unsupported']),
    ({'content-type': 'text/html', 'content-length': str(contact.MAX_RESPONSE_BYTES + 1)}, [b'x']),
    ({'content-type': 'text/html'}, [b'x' * contact.MAX_RESPONSE_BYTES, b'x']),
    ({'content-type': 'application/octet-stream'}, [b'binary']),
])
def test_response_limits_and_mime_are_enforced(network, headers, chunks):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (200, headers, chunks)
    with pytest.raises(contact._Unavailable):
        run(traffic().fetch(request()))
    assert all(item.closed for item in network['streams'])


@pytest.mark.parametrize('encoding,compress', [('gzip', gzip.compress), ('deflate', zlib.compress)])
def test_bounded_decompression_accepts_the_normal_compressed_assets(network, encoding, compress):
    content = b'<html>public listing</html>' * 10
    payload = compress(content)
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, {'content-type': 'text/html', 'content-encoding': encoding, 'content-length': str(len(payload))},
        [payload[:10], payload[10:]])
    policy = traffic()
    status, headers, body = run(policy.fetch(request()))
    assert status == 200 and body == content
    assert policy.bytes == len(content) and policy.wire_bytes == len(payload)
    assert 'content-encoding' not in headers and 'content-length' not in headers


@pytest.mark.parametrize('payload', [
    gzip.compress(b'x' * (contact.MAX_RESPONSE_BYTES + 1)),
    gzip.compress(b'normal')[:-2],
    gzip.compress(b'normal') + b'trailing',
    gzip.compress(b'normal') + gzip.compress(b'second stream'),
])
def test_bombs_truncated_and_extra_compressed_streams_fail_closed(network, payload):
    network['routes'][('www.craigslist.org', '/view/d/example-listing/ExampleListingToken')] = (
        200, {'content-type': 'text/html', 'content-encoding': 'gzip'}, payload)
    with pytest.raises(contact._Unavailable):
        run(traffic().fetch(request()))
    assert all(item.closed for item in network['streams'])


def test_post_body_and_request_count_are_bounded(network):
    with pytest.raises(contact._Unavailable):
        run(traffic().fetch(request(body=b'x' * (contact.MAX_REQUEST_BYTES + 1), method='POST')))
    limited = traffic()
    limited.requests = contact.MAX_REQUESTS
    with pytest.raises(contact._Unavailable):
        run(limited.fetch(request()))
    limited = traffic()
    limited.request_bytes = contact.MAX_TOTAL_REQUEST_BYTES
    with pytest.raises(contact._Unavailable):
        run(limited.fetch(request(body=b'x', method='POST')))
    limited = traffic()
    limited.wire_bytes = contact.MAX_TOTAL_BYTES
    with pytest.raises(contact._Unavailable):
        run(limited.fetch(request()))
    assert not network['requests']


def test_route_aborts_unaccepted_resources_and_popup_without_continue(monkeypatch):
    class Route:
        def __init__(self, req):
            self.request = req
            self.aborted = False

        async def abort(self):
            self.aborted = True

        async def fulfill(self, **kwargs):
            pytest.fail('Unexpected fulfill')

    async def scenario():
        policy = traffic()
        policy.page = object()
        for resource, page in [('image', policy.page), ('font', policy.page), ('media', policy.page), ('document', object())]:
            route = Route(request(resource=resource, page=page))
            await policy.route(route)
            assert route.aborted
    run(scenario())


class Locator:
    def __init__(self, page, name):
        self.page, self.name = page, name
        self.first = self

    def nth(self, index):
        return self

    def filter(self, **kwargs):
        return self

    async def count(self):
        return int(await self.is_visible())

    async def is_visible(self):
        return (self.name == 'reply' or self.name == 'email' and self.page.step >= 1
                or self.name == 'address' and self.page.step >= 2)

    async def is_enabled(self):
        return True

    async def wait_for(self, **kwargs):
        if not await self.is_visible():
            raise TimeoutError()

    async def click(self, **kwargs):
        self.page.clicks.append(self.name)
        assert self.name in {'reply', 'email'}
        self.page.step += 1

    async def get_attribute(self, name):
        return 'mailto:' + self.page.email + '?subject=Sample&body=Sample'

    async def evaluate(self, expression):
        return self.page.rendered


class Page:
    def __init__(self, *, email=RELAY, challenge_at=None):
        self.step, self.clicks, self.email = 0, [], email
        self.challenge_at = challenge_at
        self.url = LISTING
        self.frames = [self]
        self.rendered = True

    async def goto(self, url, **kwargs):
        self.url = url

    async def evaluate(self, expression):
        return {'title': 'Listing', 'text': '', 'challenge': self.challenge_at == self.step}

    def get_by_role(self, role, **kwargs):
        assert role == 'button'
        return Locator(self, 'reply')

    def locator(self, selector):
        return Locator(self, 'email' if selector == 'button.reply-option-header' else 'address')


def test_only_reply_and_email_buttons_are_clicked_and_mailto_is_read():
    page = Page()
    assert run(contact._reveal(page, traffic(), LISTING)) == {'status': 'revealed', 'email': RELAY}
    assert page.clicks == ['reply', 'email']


@pytest.mark.parametrize('email', ['seller@example.test', 'a@sale.craigslist.org.evil.test',
                                   'a@sale.craigslist.org,b@sale.craigslist.org',
                                   'a%0d%0aBcc:b@example.test@sale.craigslist.org'])
def test_only_one_valid_craigslist_relay_can_be_returned(email):
    page = Page(email=email)
    assert run(contact._reveal(page, traffic(), LISTING)) == {'status': 'unavailable', 'email': None}


def test_transparent_or_hidden_relay_is_not_accepted():
    page = Page()
    page.rendered = False
    assert run(contact._reveal(page, traffic(), LISTING)) == {'status': 'unavailable', 'email': None}


@pytest.mark.parametrize('step,clicks', [(0, []), (1, ['reply']), (2, ['reply', 'email'])])
def test_challenge_stops_before_any_further_clicks(step, clicks):
    page = Page(challenge_at=step)
    assert run(contact._reveal(page, traffic(), LISTING)) == {'status': 'blocked', 'email': None}
    assert page.clicks == clicks


def test_challenges_in_child_frames_are_detected_before_clicking():
    page = Page()
    child = Page(challenge_at=0)
    page.frames.append(child)
    assert run(contact._reveal(page, traffic(), LISTING))['status'] == 'blocked'
    assert not page.clicks


def test_busy_is_failfast_and_does_not_start_another_worker(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(contact, '_slots', slots)
    assert run(contact.reveal_craigslist_contact(LISTING)) == {'status': 'busy', 'email': None}


def test_cancellation_keeps_slot_until_browser_is_closed(monkeypatch):
    import playwright.async_api
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(contact, '_slots', slots)
    monkeypatch.setenv('OPENAI_API_KEY', 'never-pass-to-renderer')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'never-pass-to-renderer')

    async def scenario():
        closing, allow_close = asyncio.Event(), asyncio.Event()

        class Browser:
            async def new_context(self, **kwargs):
                await asyncio.Event().wait()

            async def close(self):
                closing.set()
                await allow_close.wait()

        class Chromium:
            async def launch(self, **kwargs):
                assert kwargs['proxy']['server'] == 'http://127.0.0.1:9'
                assert kwargs['chromium_sandbox'] is True
                assert 'OPENAI_API_KEY' not in kwargs['env']
                assert 'SUPABASE_SERVICE_ROLE_KEY' not in kwargs['env']
                return Browser()

        class Driver:
            chromium = Chromium()

            async def stop(self):
                pass

        class Manager:
            async def start(self):
                return Driver()

        monkeypatch.setattr(playwright.async_api, 'async_playwright', Manager)
        caller = asyncio.create_task(contact.reveal_craigslist_contact(LISTING))
        for _ in range(10):
            await asyncio.sleep(0)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        await closing.wait()
        assert await contact.reveal_craigslist_contact(LISTING) == {'status': 'busy', 'email': None}
        allow_close.set()
        await asyncio.gather(*list(contact._workers), return_exceptions=True)
        assert slots.acquire(blocking=False)
        slots.release()
    run(scenario())
