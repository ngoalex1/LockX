"""Refresh old pending drafts after contact lookup becomes available; never send mail."""
from collections import OrderedDict
import json
import os
import time

_cache = OrderedDict()
_active = set()
MAX_CACHE = 128


def _listing(row, draft):
    if (os.getenv('LOCKX_CRAIGSLIST_CONTACT_MODE', 'local') != 'remote'
            or draft.get('recipient_locked') or draft.get('status') != 'draft'
            or draft.get('send_ready') is not True
            or draft.get('contacts') or row['submitted'] is not None
            or row['status'] != 'waiting' or row['expires'] <= time.time()):
        return None
    try:
        from craigslist_contact import is_craigslist_listing_url, _official_url
        listing = json.loads(row['listing'])
        source = listing.get('listing_import') or {}
        original = listing.get('listing_url')
        # Both the submitted listing and its stored canonical source must be
        # Craigslist. This is internal stored provenance, never a request URL.
        canonical = source.get('listing_url') or original
        if not is_craigslist_listing_url(original) or not is_craigslist_listing_url(canonical):
            return None
        return _official_url(canonical)
    except (ValueError, TypeError, AttributeError):
        return None


async def lookup(row, draft):
    url = _listing(row, draft)
    if not url:
        return None
    now = time.monotonic()
    cached = _cache.get(url)
    if cached and cached[0] > now:
        _cache.move_to_end(url)
        return cached[1]
    if url in _active:
        return None
    _active.add(url)
    try:
        from craigslist_contact import reveal_craigslist_contact
        from listing_contacts import clean_email
        result = await reveal_craigslist_contact(url)
        email = clean_email(result.get('email')) if isinstance(result, dict) else None
        found = ({'listing_url': url, 'email': email}
                 if result.get('status') == 'revealed' and email
                 and email.rsplit('@', 1)[1] == 'sale.craigslist.org' else None) if isinstance(result, dict) else None
        _cache[url] = (now + (300 if found else 30), found)
        _cache.move_to_end(url)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)
        return found
    except Exception:
        return None
    finally:
        _active.discard(url)


def apply(row, draft, found):
    # Recheck a fresh database row after network I/O. A cancellation or email
    # attempt that happened meanwhile must keep its current state/recipient.
    if not found or _listing(row, draft) != found.get('listing_url'):
        return draft
    from listing_contacts import clean_email
    email = clean_email(found.get('email'))
    if not email or email.rsplit('@', 1)[1] != 'sale.craigslist.org':
        return draft
    return {**draft, 'recipient': email, 'contact_url': found['listing_url'],
            'contact_reveal_status': 'revealed',
            'contacts': [{'email': email, 'label': 'Craigslist seller relay', 'source': 'craigslist_reply'}]}
