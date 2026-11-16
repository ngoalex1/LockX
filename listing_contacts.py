"""Conservative seller contact hints from one public listing, never page-wide email scraping.

HTML and JSON-LD remain inert data. This module neither fetches contact links nor
attempts to recover private or obfuscated addresses.
"""
import json
import math
import re
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from fastapi import HTTPException

from buyer_requests import listing_url

MAX_CONTACTS = 3
_MAX_NODES = 12_000
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_INERT = {'script', 'style', 'template', 'noscript', 'svg', 'canvas'}
_EXCLUDED = re.compile(r'(?<![a-z])(footer|header|nav|aside|support|privacy|legal|help|recommend\w*|related|newsletter|social)(?![a-z])', re.I)
_SELLER = re.compile(r'(?<![a-z])(seller|vendor|listing[\s_-]*owner)(?![a-z])', re.I)
_CONTACT = re.compile(r'(?<![a-z])(contact|email|e-mail|message|ask)(?![a-z])', re.I)
_BLOCKED = re.compile(r'^(log\s?in|sign\s?in|access denied|just a moment|security check|verify you are human)\b', re.I)
_EMAIL = re.compile(r"[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+(?:\.[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+)*@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_ROLE = re.compile(r'^(support|help|privacy|legal|noreply|no[._-]reply|donotreply|do[._-]not[._-]reply|abuse|webmaster|security)(?:[+._-].*)?$', re.I)


def _text(value, limit=100):
    return ' '.join(str(value or '').replace('\x00', '').split())[:limit]


def _attribute_context(attrs, *keys):
    value = ' '.join(attrs.get(key, '') for key in keys)
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', value)


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


def safe_contact_url(value, base_url):
    """Only an observed public URL on the listing's own origin is eligible."""
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        url = listing_url(urljoin(base_url, value))
        base, target = urlsplit(base_url), urlsplit(url)
        origin = lambda p: (p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80))
        if origin(base) != origin(target) or re.search(r'/(?:log[-_]?in|sign[-_]?in|auth)(?:/|$)', target.path, re.I):
            return None
        # Encoded controls and backslashes cannot become a different link when opened.
        decoded = unquote(url)
        if any(ord(c) < 33 for c in decoded) or '\\' in decoded:
            return None
        return url
    except (HTTPException, ValueError):
        return None


def empty_contact(*, now=None):
    return {'candidates': [], 'contact_url': None, 'detected_at': time.time() if now is None else now}


class _Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.parts = []
        context = tag + ' ' + _attribute_context(attrs, 'class', 'id', 'role', 'data-testid')
        style = re.sub(r'\s+', '', attrs.get('style', '').lower())
        own_hidden = ('hidden' in attrs or attrs.get('aria-hidden', '').lower() == 'true'
                      or tag in _INERT or 'display:none' in style or 'visibility:hidden' in style
                      or 'visibility:collapse' in style or 'content-visibility:hidden' in style
                      or re.search(r'(?:^|;)opacity:0(?:\.0*)?(?:[;!]|$)', style)
                      or re.search(r'(?<![a-z])(hidden|invisible|d-none|visually-hidden|sr-only)(?![a-z])', context, re.I))
        self.hidden = bool(own_hidden or (parent and parent.hidden))
        self.excluded = bool(_EXCLUDED.search(context) or (parent and parent.excluded))

    def text(self):
        return _text(' '.join(self.parts), 1200)


class _Contacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('root', {})
        self.stack, self.nodes, self.scripts, self.title = [self.root], [], [], []
        self.script = None
        self.overflow = 0

    def handle_starttag(self, tag, pairs):
        attrs = {k.lower(): v or '' for k, v in pairs}
        if self.overflow or len(self.nodes) >= _MAX_NODES or len(self.stack) >= 128:
            if tag not in _VOID:
                self.overflow += 1
            return
        node = _Node(tag, attrs, self.stack[-1])
        self.nodes.append(node)
        if tag == 'script' and attrs.get('type', '').split(';', 1)[0].strip().lower() == 'application/ld+json':
            # JSON-LD itself is inert, but an explicitly hidden parent is ineligible.
            declared_hidden = ('hidden' in attrs or attrs.get('aria-hidden', '').lower() == 'true'
                               or re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style', ''), re.I))
            if not declared_hidden and not self.stack[-1].hidden and not self.stack[-1].excluded and len(self.scripts) < 16:
                self.script = []
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.overflow:
            self.overflow -= 1
            return
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if any(node.tag == 'title' for node in self.stack):
            self.title.append(data[:500])
        if self.stack[-1].hidden or self.stack[-1].excluded:
            return
        for node in self.stack:
            if len(node.parts) < 128 and sum(map(len, node.parts)) < 2000:
                node.parts.append(data[:500])


def _seller_context(node):
    current = node
    for depth in range(4):
        if current is None or current.tag in {'body', 'html', 'root'}:
            break
        attrs = current.attrs
        context = _attribute_context(attrs, 'class', 'id', 'itemprop', 'aria-label', 'data-testid')
        if _SELLER.search(context):
            return True
        # Short, local contact cards can label a following link via a heading.
        if depth <= 2 and current.tag not in {'main', 'article'}:
            visible = current.text()
            if len(visible) <= 500 and _SELLER.search(visible) and _CONTACT.search(visible):
                return True
        current = current.parent
    return False


def _mailto(value):
    if not isinstance(value, str) or len(value) > 2000 or not value.lower().startswith('mailto:'):
        return None
    decoded = unquote(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        return None
    mailbox = decoded[7:].split('?', 1)[0]
    return clean_email(mailbox)


def _structured_sellers(scripts, base_url):
    """Inspect only direct seller fields on a primary listing entity, never arbitrary keys."""
    roots = []
    for script in scripts:
        try:
            value = json.loads(script)
        except (ValueError, RecursionError):
            continue
        roots.extend(entry for entry in (value[:32] if isinstance(value, list) else [value]) if isinstance(entry, dict))
    entries = list(roots)
    for root in roots:
        if isinstance(root.get('@graph'), list):
            entries.extend(entry for entry in root['@graph'][:64] if isinstance(entry, dict))

    def product(entity):
        types = entity.get('@type', [])
        types = [types] if isinstance(types, str) else types
        return isinstance(types, list) and any(str(t).rsplit('/', 1)[-1].lower() in {'product', 'individualproduct', 'vehicle', 'car'} for t in types)

    def matches(entity):
        for key in ('url', '@id'):
            if isinstance(entity.get(key), str):
                try:
                    if listing_url(urljoin(base_url, entity[key])) == base_url:
                        return True
                except HTTPException:
                    pass
        return False

    # Resolve only references already present in the same bounded JSON document.
    identifiers = {entry['@id']: entry for entry in entries if isinstance(entry.get('@id'), str)}
    main_entities = []
    for entry in entries:
        main = entry.get('mainEntity')
        if isinstance(main, dict):
            reference = main.get('@id')
            main_entities.append(identifiers.get(reference, main) if isinstance(reference, str) else main)
    products = [entry for entry in entries if product(entry)]
    primary = main_entities or products
    primary = list({id(entry): entry for entry in primary}.values())
    if len(primary) > 1:
        # Without a matching listing URL, multiple products may be recommendations.
        primary = [entry for entry in primary if matches(entry)]
    entities = [(entry, bool(main_entities)) for entry in primary]
    entities.extend((root, False) for root in roots if not product(root) and 'sellerContact' in root)
    for entity, main in entities[:16]:
        sellers = []
        if main:
            sellers.append(entity.get('seller'))
        sellers.append(entity.get('sellerContact'))
        offers = entity.get('offers', [])
        offers = offers[:8] if isinstance(offers, list) else [offers]
        sellers.extend(offer.get('seller') for offer in offers if isinstance(offer, dict))
        for seller in sellers:
            for item in (seller[:8] if isinstance(seller, list) else [seller]):
                if isinstance(item, dict):
                    email = clean_email(item.get('email'))
                    if email:
                        name = item.get('name')
                        yield email, _text(name if isinstance(name, str) else 'Listing seller', 100)


def extract_seller_contact(content, base_url, *, now=None):
    result = empty_contact(now=now)
    parser = _Contacts()
    try:
        parser.feed(content.decode('utf-8', errors='replace') if isinstance(content, bytes) else content)
        parser.close()
    except (ValueError, RecursionError):
        return result
    if _BLOCKED.search(_text(' '.join(parser.title), 200)):
        return result
    seen = set()

    def add(email, label, source):
        if email and email.lower() not in seen and len(result['candidates']) < MAX_CONTACTS:
            result['candidates'].append({'email': email, 'label': _text(label or 'Listing seller', 100),
                                         'source': source, 'source_url': base_url})
            seen.add(email.lower())

    for node in parser.nodes:
        if node.hidden or node.excluded or not _seller_context(node):
            continue
        visible = node.text()
        if node.tag == 'a' and visible:
            add(_mailto(node.attrs.get('href')), visible, 'listing_mailto')
            if result['contact_url'] is None and _CONTACT.search(visible):
                result['contact_url'] = safe_contact_url(node.attrs.get('href'), base_url)
        # Visible, explicitly named seller contact fields only; never all page text.
        attrs = node.attrs
        field = _attribute_context(attrs, 'class', 'id', 'itemprop', 'aria-label')
        named_field = _CONTACT.search(field) or re.match(r'^(?:seller|vendor)\s+(?:e-?mail|contact)\s*:', visible, re.I)
        if len(visible) <= 500 and named_field and node.tag not in {'a', 'body', 'html', 'main', 'article'}:
            for match in _EMAIL.finditer(visible):
                add(clean_email(match.group()), 'Listing seller', 'listing_mailto')
    for email, label in _structured_sellers(parser.scripts, base_url):
        add(email, label, 'structured_seller')
    return result


def validate_contact(value, base_url, imported_at):
    """Revalidate the bounded contact metadata before saving signed provenance."""
    if not isinstance(value, dict) or not isinstance(value.get('candidates'), list) or len(value['candidates']) > MAX_CONTACTS:
        raise ValueError('Invalid seller contacts')
    detected = value.get('detected_at')
    if type(detected) not in {int, float} or not math.isfinite(detected) or detected != imported_at:
        raise ValueError('Invalid contact timestamp')
    result = empty_contact(now=detected)
    for item in value['candidates']:
        if (not isinstance(item, dict) or not clean_email(item.get('email'))
                or clean_email(item.get('email')) != item.get('email')
                or item.get('source') not in {'listing_mailto', 'structured_seller'}
                or item.get('source_url') != base_url or not isinstance(item.get('label'), str)
                or _text(item['label'], 100) != item['label']):
            raise ValueError('Invalid seller contact')
        if any(entry['email'].lower() == item['email'].lower() for entry in result['candidates']):
            raise ValueError('Duplicate seller contact')
        result['candidates'].append({key: item[key] for key in ('email', 'label', 'source', 'source_url')})
    contact_url = value.get('contact_url')
    if contact_url is not None and safe_contact_url(contact_url, base_url) != contact_url:
        raise ValueError('Invalid seller contact link')
    result['contact_url'] = contact_url
    return result
