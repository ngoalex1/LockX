"""Remote contact authorization and validation, without provider/browser calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import secrets
import stat
import threading
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

import craigslist_contact as contact
import craigslist_remote as remote

LISTING = 'https://www.craigslist.org/view/d/example-listing/ExampleListingToken'
OTHER = 'https://www.craigslist.org/view/d/other-listing/OtherListingToken'
RELAY = 'unit-test-remote@sale.craigslist.org'
CLAIM = '/api/v1/in-hand/contact-lookup/claim'


def run(value):
    return asyncio.run(value)


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    clock = [1_800_000_000]
    monkeypatch.setenv('LOCKX_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('LOCKX_CRAIGSLIST_CONTACT_MODE', raising=False)
    monkeypatch.setattr(remote, 'time', SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(remote, '_remote_slots', threading.BoundedSemaphore(1))
    return {'clock': clock, 'root': tmp_path}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(remote.router)
    return TestClient(app)


def test_internal_ticket_is_random_bound_hashed_and_claimed_once(store):
    issued = remote.issue_ticket(LISTING)
    assert len(issued['ticket']) == 43 and issued['nonce'] != issued['ticket']
    assert issued['expires'] == store['clock'][0] + 60
    binding = remote.claim_ticket(issued['ticket'])
    assert binding == {key: value for key, value in issued.items() if key != 'ticket'}
    assert binding['version'] == 1 and binding['listing_url'] == LISTING and binding['purpose'] == 'lookup'
    with remote._database() as db:
        row = db.execute('SELECT * FROM contact_tickets').fetchone()
        assert row['digest'] == hashlib.sha256(issued['ticket'].encode()).hexdigest()
        assert row['digest'] != issued['ticket']
    path = store['root'] / 'craigslist-contact-tickets.sqlite3'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(HTTPException) as replay:
        remote.claim_ticket(issued['ticket'])
    assert replay.value.status_code == 401


def test_bootstrap_is_an_internal_bound_purpose(client):
    issued = remote.issue_ticket(LISTING, purpose='bootstrap')
    response = client.post(CLAIM, json={'ticket': issued['ticket']})
    assert response.status_code == 200 and response.json()['purpose'] == 'bootstrap'
    assert client.post(CLAIM, json={'listing_url': LISTING, 'purpose': 'bootstrap'}).status_code == 401
    assert client.post('/api/v1/in-hand/contact-lookup/issue', json={'listing_url': LISTING}).status_code == 404


@pytest.mark.parametrize('url', ['https://example.test/item', 'https://www.craigslist.org/search/sss',
    'https://user:secret@www.craigslist.org/view/d/example/ExampleListingToken',
    'http://127.0.0.1/item', 'https://www.craigslist.org.evil.test/view/d/example/ExampleListingToken', None])
def test_issuer_cannot_authorize_nonlisting_or_foreign_urls(url):
    with pytest.raises(ValueError):
        remote.issue_ticket(url)


def test_invalid_ticket_and_expired_or_replayed_ticket_have_same_auth_failure(client, store):
    issued = remote.issue_ticket(LISTING)
    store['clock'][0] += remote.TICKET_SECONDS
    expired = client.post(CLAIM, json={'ticket': issued['ticket']})
    unknown = client.post(CLAIM, json={'ticket': secrets.token_urlsafe(32)})
    malformed = client.post(CLAIM, json={'ticket': 'not-a-ticket'})
    assert expired.status_code == unknown.status_code == malformed.status_code == 401
    assert expired.json() == unknown.json() == malformed.json()


@pytest.mark.parametrize('body,headers', [
    (b'{"ticket":true}', {'content-type': 'application/json'}),
    (b'{"ticket":"x"}', {'content-type': 'application/json', 'content-encoding': 'gzip'}),
    (b'{"ticket":"x"}', {'content-type': 'text/plain'}),
    (b'x' * 513, {'content-type': 'application/json'}),
    (b'{"ticket":null}', {'content-type': 'application/json', 'content-length': '513'}),
    (b'{"ticket":NaN}', {'content-type': 'application/json'}),
])
def test_claim_rejects_malformed_or_oversized_bodies_before_authorizing(client, body, headers):
    assert client.post(CLAIM, content=body, headers=headers).status_code == 401


def test_claim_forbids_url_purpose_extra_fields_and_duplicate_keys_without_consuming(client):
    issued = remote.issue_ticket(LISTING)
    ticket = issued['ticket']
    for extra in ({'listing_url': OTHER}, {'purpose': 'bootstrap'}, {'url': 'http://127.0.0.1'}):
        assert client.post(CLAIM, json={'ticket': ticket, **extra}).status_code == 401
    duplicate = ('{"ticket":"' + ticket + '","ticket":"' + ticket + '"}').encode()
    assert client.post(CLAIM, content=duplicate, headers={'content-type': 'application/json'}).status_code == 401
    assert client.post(CLAIM, json={'ticket': ticket}).status_code == 200
    assert client.post(CLAIM, json={'ticket': ticket}).status_code == 401


def test_claim_race_has_exactly_one_winner():
    issued = remote.issue_ticket(LISTING)
    def claim():
        try:
            return remote.claim_ticket(issued['ticket'])
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert results.count(401) == 1


def test_global_active_lease_survives_claim_until_completion_or_expiry(store):
    issued = remote.issue_ticket(LISTING)
    with pytest.raises(remote.TicketBusy):
        remote.issue_ticket(OTHER)
    remote.claim_ticket(issued['ticket'])
    with pytest.raises(remote.TicketBusy):
        remote.issue_ticket(OTHER)
    assert remote._finish_ticket(issued['ticket']) is True
    second = remote.issue_ticket(OTHER)
    assert second['nonce'] != issued['nonce']
    store['clock'][0] += remote.TICKET_SECONDS
    assert remote.issue_ticket(LISTING)['listing_url'] == LISTING


def test_rate_limit_counts_finished_attempts_for_the_entire_hour(store):
    for _ in range(remote.MAX_LOOKUPS_PER_HOUR):
        issued = remote.issue_ticket(LISTING)
        remote.claim_ticket(issued['ticket'])
        assert remote._finish_ticket(issued['ticket'])
    with pytest.raises(remote.TicketBusy):
        remote.issue_ticket(LISTING)
    with remote._database() as db:
        assert db.execute('SELECT COUNT(*) FROM contact_tickets').fetchone()[0] == 30
    store['clock'][0] += remote.RATE_SECONDS + 1
    assert remote.issue_ticket(LISTING)['purpose'] == 'lookup'


def test_cleanup_deletes_only_a_bounded_old_batch(store):
    old = store['clock'][0] - remote.RATE_SECONDS - 1
    with remote._database() as db:
        for index in range(70):
            db.execute('INSERT INTO contact_tickets VALUES(?,?,?,?,?,?,?)',
                (f'old-{index}', f'nonce-{index}', LISTING, 'lookup', old, old + 60, 'finished'))
    remote.issue_ticket(LISTING)
    with remote._database() as db:
        assert db.execute('SELECT COUNT(*) FROM contact_tickets WHERE created=?', (old,)).fetchone()[0] == 6


class Response:
    def __init__(self, state, payload):
        self.state = state
        self.status_code = state.get('status_code', 200)
        self.headers = {'content-type': 'application/json', **state.get('headers', {})}
        self.payload = state.get('raw', json.dumps(payload).encode())

    async def aiter_raw(self, **kwargs):
        if self.state.get('hang_body'):
            self.state['started'].set()
            await asyncio.Event().wait()
        for index in range(0, len(self.payload), 1024):
            yield self.payload[index:index + 1024]


@pytest.fixture
def worker(monkeypatch):
    state = {'requests': [], 'closed': False}
    class ResponseContext:
        def __init__(self, request):
            self.request = request

        async def __aenter__(self):
            ticket = self.request['json']['ticket']
            if state.get('skip_claim'):
                with remote._database() as db:
                    binding = remote._binding(db.execute('SELECT * FROM contact_tickets WHERE digest=?', (remote._digest(ticket),)).fetchone())
            else:
                binding = remote.claim_ticket(ticket)
            state['binding'] = binding
            payload = {**binding, 'status': 'revealed', 'email': RELAY}
            if state.get('mutate'):
                payload = state['mutate'](payload)
            return Response(state, payload)

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **options):
            state['options'] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state['closed'] = True

        def stream(self, method, url, **kwargs):
            value = {'method': method, 'url': url, **kwargs}
            state['requests'].append(value)
            if state.get('network_error'):
                raise httpx.ConnectError('simulated network failure')
            return ResponseContext(value)
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    return state


def test_remote_client_uses_fixed_endpoint_only_ticket_and_no_ambient_proxy(worker, monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('LOCKX_CRAIGSLIST_REMOTE_URL', 'https://evil.test')
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'revealed', 'email': RELAY}
    request, = worker['requests']
    assert request['url'] == 'https://lockx.ai/api/craigslist-contact' and request['method'] == 'POST'
    assert set(request['json']) == {'ticket'}
    assert worker['options']['trust_env'] is False and worker['options']['follow_redirects'] is False
    assert worker['options']['headers']['Accept-Encoding'] == 'identity'
    assert worker['closed']
    # Confirmed completion releases the persistent lease, but leaves rate history.
    assert remote.issue_ticket(OTHER)['purpose'] == 'lookup'


@pytest.mark.parametrize('changes', [
    {'version': True}, {'version': 2}, {'nonce': 'x' * 43}, {'listing_url': OTHER},
    {'listing_url': ['wrong']}, {'purpose': 'bootstrap'}, {'expires': True}, {'expires': 42},
    {'status': 'unexpected'}, {'status': []}, {'email': 'seller@example.test'},
    {'email': 'seller@sale.craigslist.org.evil.test'}, {'email': 'a@sale.craigslist.org,b@sale.craigslist.org'},
    {'email': 'a%0d%0aBcc:b@example.test@sale.craigslist.org'},
    {'email': None}, {'email': [RELAY]}, {'status': 'blocked', 'email': RELAY},
    {'extra_email': 'foreign@example.test'},
])
def test_remote_result_binding_schema_and_mailbox_are_strict(worker, changes):
    worker['mutate'] = lambda payload: {**payload, **changes}
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}
    with pytest.raises(remote.TicketBusy):
        remote.issue_ticket(OTHER)


@pytest.mark.parametrize('status', ['blocked', 'busy', 'unavailable'])
def test_legitimate_unavailable_status_has_no_email(worker, status):
    worker['mutate'] = lambda payload: {**payload, 'status': status, 'email': None}
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': status, 'email': None}


@pytest.mark.parametrize('state', [
    {'status_code': 302, 'headers': {'location': 'http://169.254.169.254/secret'}},
    {'status_code': 500}, {'headers': {'content-encoding': 'gzip'}},
    {'headers': {'content-type': 'text/html'}}, {'headers': {'content-length': '8193'}},
    {'raw': b'x' * 8193}, {'raw': b'[]'}, {'raw': b'{not json'},
    {'raw': b'[' * 2000 + b']' * 2000},
])
def test_redirects_errors_encodings_sizes_and_nested_json_fail_closed(worker, state):
    worker.update(state)
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}
    assert len(worker['requests']) == 1 and worker['closed']


def test_duplicate_json_keys_cannot_hide_an_extra_foreign_recipient(worker):
    def encode(payload):
        worker['raw'] = (json.dumps(payload)[:-1] + ',"email":"foreign@example.test"}').encode()
        return payload
    worker['mutate'] = encode
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}


def test_even_a_correct_binding_without_atomic_claim_is_not_accepted(worker):
    worker['skip_claim'] = True
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}
    ticket = worker['requests'][0]['json']['ticket']
    with pytest.raises(HTTPException):
        remote.claim_ticket(ticket)


def test_network_failure_revokes_unclaimed_ticket_and_retains_uncertain_lease(worker):
    worker['network_error'] = True
    assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}
    ticket = worker['requests'][0]['json']['ticket']
    with pytest.raises(HTTPException):
        remote.claim_ticket(ticket)
    with pytest.raises(remote.TicketBusy):
        remote.issue_ticket(OTHER)


def test_total_deadline_closes_client_and_retains_consumed_lease(worker, monkeypatch):
    worker['hang_body'] = True
    monkeypatch.setattr(remote, 'REMOTE_SECONDS', 0.02)
    async def scenario():
        worker['started'] = asyncio.Event()
        result = await remote.reveal_remote_craigslist_contact(LISTING)
        assert result == {'status': 'unavailable', 'email': None}
        assert worker['closed']
        assert await remote.reveal_remote_craigslist_contact(OTHER) == {'status': 'busy', 'email': None}
    run(scenario())


def test_cancellation_keeps_claimed_lease_and_releases_http_resources(worker):
    worker['hang_body'] = True
    async def scenario():
        worker['started'] = asyncio.Event()
        task = asyncio.create_task(remote.reveal_remote_craigslist_contact(LISTING))
        await worker['started'].wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker['closed']
        assert await remote.reveal_remote_craigslist_contact(OTHER) == {'status': 'busy', 'email': None}
    run(scenario())


def test_process_slot_is_failfast_without_issuing_ticket(worker):
    remote._remote_slots.acquire()
    try:
        assert run(remote.reveal_remote_craigslist_contact(LISTING)) == {'status': 'busy', 'email': None}
        assert not worker['requests']
    finally:
        remote._remote_slots.release()


def test_remote_dispatch_needs_explicit_mode_and_never_touches_local_browser(monkeypatch):
    monkeypatch.setenv('LOCKX_CRAIGSLIST_CONTACT_MODE', 'remote')
    calls = []
    async def remote_lookup(url):
        calls.append(url)
        return {'status': 'revealed', 'email': RELAY}
    async def local_browser(*args):
        pytest.fail('Remote mode must not launch a local browser')
    monkeypatch.setattr(remote, 'reveal_remote_craigslist_contact', remote_lookup)
    monkeypatch.setattr(contact, '_run', local_browser)
    assert run(contact.reveal_craigslist_contact(LISTING)) == {'status': 'revealed', 'email': RELAY}
    assert calls == [LISTING]
    assert run(contact.reveal_craigslist_contact('https://example.test/item'))['status'] == 'unavailable'
    assert calls == [LISTING]


def test_unknown_mode_fails_closed_without_remote_request(worker, monkeypatch):
    monkeypatch.setenv('LOCKX_CRAIGSLIST_CONTACT_MODE', 'https://evil.test')
    assert run(contact.reveal_craigslist_contact(LISTING)) == {'status': 'unavailable', 'email': None}
    assert not worker['requests']


def test_claim_route_is_registered_in_production_app():
    from main import app
    assert TestClient(app).post(CLAIM, json={'ticket': 'invalid'}).status_code == 401
