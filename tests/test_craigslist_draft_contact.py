import asyncio
import copy
import json
import time

import pytest

import craigslist_contact
import craigslist_draft_contact as refresh
import in_hand as ih
from test_buyer_proof import app, create, AUTH, BASE, funds
from test_seller_email import provider, ledger

URL = 'https://www.craigslist.org/view/d/example-listing/ExampleListingToken'
RELAY = 'draft-test@sale.craigslist.org'


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv('LOCKX_CRAIGSLIST_CONTACT_MODE', 'remote')
    refresh._cache.clear()
    refresh._active.clear()
    yield
    refresh._cache.clear()
    refresh._active.clear()


def record(url=URL):
    return {'listing': json.dumps({'listing_url': url, 'listing_import': {
        'listing_url': url, 'imported_at': 1, 'photos': [{'source_url': 'original-photo'}]}}),
        'status': 'waiting', 'submitted': None, 'expires': time.time()+100}


def draft():
    return {'contacts': [], 'recipient': '', 'recipient_locked': False,
            'status': 'draft', 'send_ready': True, 'draft_digest': 'unchanged-digest'}


def test_old_pending_draft_gets_recipient_without_changing_photo_provenance(monkeypatch):
    calls = []
    async def reveal(url):
        calls.append(url)
        return {'status': 'revealed', 'email': RELAY}
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', reveal)
    row, preview = record(), draft()
    before = copy.deepcopy((row, preview))
    found = asyncio.run(refresh.lookup(row, preview))
    enriched = refresh.apply(row, preview, found)
    assert calls == [URL]
    assert enriched['recipient'] == RELAY
    assert enriched['contact_reveal_status'] == 'revealed'
    assert enriched['draft_digest'] == preview['draft_digest']
    assert (row, preview) == before


@pytest.mark.parametrize('change', ['local', 'locked', 'accepted', 'cancelled', 'has-contact', 'submitted', 'expired', 'foreign'])
def test_ineligible_drafts_never_trigger_contact_work(monkeypatch, change):
    row, preview = record(), draft()
    if change == 'local': monkeypatch.setenv('LOCKX_CRAIGSLIST_CONTACT_MODE', 'local')
    elif change == 'locked': preview['recipient_locked'] = True
    elif change == 'accepted': preview['status'] = 'accepted'
    elif change == 'cancelled': preview['send_ready'] = False
    elif change == 'has-contact': preview['contacts'] = [{'email': 'known@example.test'}]
    elif change == 'submitted': row['submitted'] = time.time()
    elif change == 'expired': row['expires'] = 1
    else: row = record('https://example.test/item')
    async def unexpected(_): raise AssertionError('No lookup allowed')
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', unexpected)
    assert asyncio.run(refresh.lookup(row, preview)) is None


def test_refresh_reuses_bounded_short_cache(monkeypatch):
    calls = []
    async def reveal(url):
        calls.append(url)
        return {'status': 'revealed', 'email': RELAY}
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', reveal)
    assert asyncio.run(refresh.lookup(record(), draft()))
    assert asyncio.run(refresh.lookup(record(), draft()))
    assert calls == [URL]
    assert len(refresh._cache) <= refresh.MAX_CACHE


@pytest.mark.parametrize('response', [
    {'status': 'revealed', 'email': 'wrong@example.test'},
    {'status': 'unavailable', 'email': RELAY},
    {'status': 'revealed', 'email': RELAY+'\r\nBcc:other@example.test'},
    None])
def test_unavailable_or_invalid_relay_never_becomes_a_recipient(monkeypatch, response):
    async def reveal(_): return response
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', reveal)
    assert asyncio.run(refresh.lookup(record(), draft())) is None


@pytest.mark.parametrize('change', ['locked', 'cancelled', 'different-listing', 'expired'])
def test_state_is_rechecked_after_lookup_before_prefilling(change):
    row, preview = record(), draft()
    found = {'listing_url': URL, 'email': RELAY}
    if change == 'locked': preview.update(recipient_locked=True, recipient='locked@example.test')
    elif change == 'cancelled': preview['send_ready'] = False
    elif change == 'different-listing': row = record(URL.replace('example-listing', 'other-listing'))
    else: row['expires'] = 1
    assert refresh.apply(row, preview, found) is preview


def test_existing_buyer_request_route_prefills_relay_without_sending_or_charging(app, provider, monkeypatch):
    response = create(app, listing_url=URL, count=4)
    assert response.status_code == 201, response.text
    item = response.json()
    with ih.database() as db:
        saved = db.execute('SELECT listing FROM ih_requests WHERE id=?', (item['id'],)).fetchone()['listing']
    before = ledger()
    calls = []
    async def reveal(url):
        calls.append(url)
        return {'status': 'revealed', 'email': RELAY}
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', reveal)
    target = BASE+f"/requests/{item['id']}/seller-email"
    first = app[0].get(target, headers=AUTH)
    assert first.status_code == 200, first.text
    assert first.json()['recipient'] == RELAY
    assert first.json()['contact_reveal_status'] == 'revealed'
    assert app[0].get(target, headers=AUTH).json()['recipient'] == RELAY
    assert calls == [URL]
    assert not provider['calls'] and ledger() == before and funds() == 2
    assert item['manage_key'] not in first.text
    with ih.database() as db:
        assert db.execute('SELECT listing FROM ih_requests WHERE id=?', (item['id'],)).fetchone()['listing'] == saved


def test_draft_refresh_requires_existing_private_request_access(app, provider, monkeypatch):
    item = create(app, listing_url=URL).json()
    calls = []
    async def reveal(url):
        calls.append(url)
        return {'status': 'revealed', 'email': RELAY}
    monkeypatch.setattr(craigslist_contact, 'reveal_craigslist_contact', reveal)
    target = BASE+f"/requests/{item['id']}/seller-email"
    assert app[0].get(target).status_code in {401,403,404}
    assert app[0].get(target, headers={'Authorization':'Bearer capturer'}).status_code in {401,403,404}
    assert calls == [] and not provider['calls']
