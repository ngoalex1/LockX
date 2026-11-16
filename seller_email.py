"""Explicit buyer-triggered seller invitations; no email from reads or imports."""
import hashlib
import json
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException

from credit_admin import normalized_email

RETRY_SECONDS = 23 * 3600  # Resend retains idempotency keys for only 24 hours.
LEASE_SECONDS = 30
SUBJECT = 'Buyer request: verify your listing with LockX'


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ih_seller_emails (
        request_id TEXT PRIMARY KEY REFERENCES ih_requests(id), recipient TEXT NOT NULL,
        payload TEXT NOT NULL, draft_digest TEXT NOT NULL, state TEXT NOT NULL,
        first_attempt REAL NOT NULL, last_attempt REAL NOT NULL, inflight_until REAL NOT NULL,
        claim_id TEXT NOT NULL, provider_id TEXT, message TEXT NOT NULL DEFAULT '',
        next_attempt REAL NOT NULL DEFAULT 0)''')
    db.execute('CREATE INDEX IF NOT EXISTS ih_seller_email_recipient ON ih_seller_emails(recipient,first_attempt)')


def configured():
    return (os.getenv('LOCKX_SELLER_EMAIL_ENABLED', '1') != '0'
            and bool(os.getenv('LOCKX_SELLER_EMAIL_RESEND_KEY') or os.getenv('RESEND_API_KEY'))
            and bool(os.getenv('LOCKX_SELLER_EMAIL_FROM') or os.getenv('LOCKX_ALERT_FROM')))


def _sender():
    sender = os.getenv('LOCKX_SELLER_EMAIL_FROM') or os.getenv('LOCKX_ALERT_FROM') or ''
    if not sender or len(sender)>254 or any(ord(c)<32 for c in sender):
        raise HTTPException(503, 'Email sending is not configured. Open the prepared email in your email app instead.')
    return sender


def _origin():
    origin = os.getenv('LOCKX_PUBLIC_APP_ORIGIN', 'https://lockx.ai').rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or parsed.hostname not in {'lockx.ai','www.lockx.ai'}
            or parsed.username or parsed.password or parsed.port not in {None,443}
            or parsed.path or parsed.query or parsed.fragment):
        raise HTTPException(503, 'The LockX email link is not configured correctly.')
    return origin


def _pending(db, row):
    buyer = db.execute('SELECT * FROM ih_buyer_requests WHERE request_id=?',(row['id'],)).fetchone()
    if not buyer:
        raise HTTPException(404, 'A buyer verification request is required.')
    return buyer['state']=='pending' and row['submitted'] is None and row['status']=='waiting' and row['expires']>time.time()


def _contact(row):
    listing = json.loads(row['listing'])
    source = listing.get('listing_import') or {}
    contact = source.get('seller_contact') or {}
    candidates = []
    for entry in contact.get('candidates',[])[:3]:
        if not isinstance(entry,dict) or entry.get('source') not in {'listing_mailto','structured_seller','craigslist_reply'}:
            continue
        try: email = normalized_email(entry.get('email',''))
        except (ValueError,TypeError,AttributeError): continue
        if email in [c['email'] for c in candidates]: continue
        candidates.append({'email':email,'label':' '.join(str(entry.get('label') or 'Seller contact').split())[:100],
                           'source':entry['source']})
    contact_url = contact.get('contact_url')
    try:
        parsed = urlsplit(contact_url or '')
        if parsed.scheme not in {'https','http'} or not parsed.hostname or parsed.username or parsed.password:
            contact_url = None
    except ValueError: contact_url = None
    return candidates,contact_url


def _template(row):
    listing = json.loads(row['listing'])
    title = ' '.join(str(listing.get('title') or 'your item').split())[:160]
    listing_url = listing.get('listing_url') or ''
    capture = _origin()+'/#in-hand/capture/'+row['token']
    return {'subject':SUBJECT,'text':(
        f'Hello,\n\nA buyer has requested a LockX verification for your listing: {title}.\n\n'
        f'Listing: {listing_url}\n\n'
        'Please record a fresh 10-second video showing the same item and the details in the selected listing photos. '
        'The buyer has paid for the check. Recording is free for you and needs no account.\n\n'
        f'Review the request and record here:\n{capture}\n\n'
        'Please review the recording and public-sharing permissions before starting. '
        'You can decline on that page. The recording link expires 24 hours after the request was created.\n\n'
        'LockX compares visible details at capture time. It does not certify authenticity, ownership or delivery.\n\n'
        'This is a buyer-requested invitation, not a payment request. No reminders are sent automatically.\n'
        'LockX.ai')}


def _digest(row, template):
    return hashlib.sha256(json.dumps([row['id'],template],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def draft(db, row):
    schema(db)
    pending = _pending(db,row)
    existing = db.execute('SELECT * FROM ih_seller_emails WHERE request_id=?',(row['id'],)).fetchone()
    contacts,contact_url = _contact(row)
    template = json.loads(existing['payload']) if existing else _template(row)
    status = existing['state'] if existing else 'draft'
    # A rejected attempt is safe to retry only with its unchanged recipient/body.
    public_status = 'draft' if status=='rejected' else status
    if status=='sending' and existing['inflight_until']<=time.time(): public_status='uncertain'
    expired = bool(existing and time.time()-existing['first_attempt']>=RETRY_SECONDS)
    result = {'contacts':contacts,'contact_url':contact_url,
              'recipient':existing['recipient'] if existing else contacts[0]['email'] if len(contacts)==1 else '',
              'subject':template['subject'],'body':template['text'],
              'draft_digest':existing['draft_digest'] if existing else _digest(row,template),
              'status':public_status,'recipient_locked':bool(existing),
              'send_ready':bool(configured() and pending and not expired and public_status not in {'accepted','sending'}
                                and not (existing and existing['next_attempt']>time.time()))}
    contact_source=(json.loads(row['listing']).get('listing_import') or {}).get('seller_contact') or {}
    reveal_status=contact_source.get('reveal_status')
    if reveal_status in {'revealed','unavailable','blocked','busy','not_needed'}:
        result['contact_reveal_status']=reveal_status
    if existing and existing['next_attempt']>time.time():
        result['retry_after']=max(1,int(existing['next_attempt']-time.time()+.999))
    if existing:
        if status=='accepted':
            result.update(sent_to=existing['recipient'],message='Your email was accepted for sending. Delivery is not yet confirmed.')
        elif expired:
            result['message']='The email retry window ended. Check the seller conversation before sending another invitation.'
        else: result['message']=existing['message'] or 'The email status is not confirmed. Retry only this same invitation.'
    elif not pending: result['message']='This request is no longer awaiting a seller recording.'
    elif not configured(): result['message']='Open this prepared message in your email app, review it, and press Send.'
    return result


def claim(db,row,recipient,draft_digest,*,now=None):
    """Caller holds BEGIN IMMEDIATE. Commit this reservation before network I/O."""
    schema(db)
    now = time.time() if now is None else now
    try: recipient=normalized_email(recipient)
    except (ValueError,TypeError,AttributeError): raise HTTPException(422,'Enter one valid seller email address.') from None
    preview=draft(db,row)
    if not _pending(db,row): raise HTTPException(409,'This request is no longer awaiting a seller recording.')
    if draft_digest!=preview['draft_digest']:
        raise HTTPException(409,'The prepared message changed. Reload it before sending.')
    prior=db.execute('SELECT * FROM ih_seller_emails WHERE request_id=?',(row['id'],)).fetchone()
    if prior:
        if recipient!=prior['recipient']:
            raise HTTPException(409,'This invitation already has a recipient. Retry the same prepared email only.')
        if prior['state']=='accepted' or (prior['state']=='sending' and prior['inflight_until']>now):
            return preview,None,None
        if now-prior['first_attempt']>=RETRY_SECONDS:
            raise HTTPException(409,'This email cannot be safely retried after its retry window. Check the seller conversation first.')
        if prior['next_attempt']>now:
            raise HTTPException(429,'Please wait before retrying this same email.',headers={'Retry-After':str(max(1,int(prior['next_attempt']-now+.999)))})
        payload=json.loads(prior['payload'])
    else:
        buyer_count=db.execute('''SELECT COUNT(*) FROM ih_seller_emails e JOIN ih_requests r ON r.id=e.request_id
            WHERE r.owner_id=? AND e.first_attempt>?''',(row['owner_id'],now-3600)).fetchone()[0]
        recipient_count=db.execute('SELECT COUNT(*) FROM ih_seller_emails WHERE recipient=? AND first_attempt>?',(recipient,now-86400)).fetchone()[0]
        if buyer_count>=10 or recipient_count>=3:
            raise HTTPException(429,'Too many invitations. Use your existing seller conversation or try again later.')
        payload={**_template(row),'from':_sender(),'to':[recipient]}
    if not configured():
        raise HTTPException(503,'Direct email sending is unavailable. Open the prepared email in your email app instead.')
    claim_id=str(uuid4())
    if prior:
        db.execute("UPDATE ih_seller_emails SET state='sending',last_attempt=?,inflight_until=?,claim_id=?,message='' WHERE request_id=?",
                   (now,now+LEASE_SECONDS,claim_id,row['id']))
    else:
        db.execute('''INSERT INTO ih_seller_emails(request_id,recipient,payload,draft_digest,state,first_attempt,last_attempt,inflight_until,claim_id)
            VALUES (?,?,?,?,'sending',?,?,?,?)''',
            (row['id'],recipient,json.dumps(payload,sort_keys=True,separators=(',',':')),draft_digest,now,now,now+LEASE_SECONDS,claim_id))
    return draft(db,row),payload,'lockx-seller-email-'+row['id']


async def deliver(payload,idempotency_key):
    key=os.getenv('LOCKX_SELLER_EMAIL_RESEND_KEY') or os.getenv('RESEND_API_KEY')
    if not key:
        return {'status':'rejected','message':'Email sending is unavailable. No email was submitted.'}
    try:
        async with httpx.AsyncClient(timeout=8,trust_env=False,follow_redirects=False) as client:
            response=await client.post('https://api.resend.com/emails',
                headers={'Authorization':'Bearer '+key,'Idempotency-Key':idempotency_key},json=payload)
        if response.status_code in {200,201,202}:
            try: data=response.json()
            except ValueError: data={}
            if isinstance(data,dict) and isinstance(data.get('id'),str) and 1<=len(data['id'])<=100:
                return {'status':'accepted','provider_id':data['id']}
        elif response.status_code in {400,401,403,404,422,429}:
            result={'status':'rejected','message':'The email service did not accept this invitation. Retry the same email later or use your seller conversation.'}
            if response.status_code==429:
                delay=response.headers.get('retry-after','60')
                result['retry_after']=min(3600,max(1,int(delay))) if len(delay)<=6 and delay.isdecimal() else 60
            return result
        # Timeout, 409 or a server failure may follow acceptance. Preserve the
        # original payload/key and never claim a definitive delivery failure.
        return {'status':'uncertain','message':'Sending is not confirmed. Retry this same invitation to check it without creating a new email.'}
    except (httpx.HTTPError,ValueError):
        return {'status':'uncertain','message':'Sending is not confirmed. Retry this same invitation to check it without creating a new email.'}


def complete(db,request_id,claim_id,result):
    schema(db)
    row=db.execute('SELECT * FROM ih_requests WHERE id=?',(request_id,)).fetchone()
    status=result.get('status')
    if status not in {'accepted','uncertain','rejected'}: status='uncertain'
    # Completion is fenced: a late first response cannot overwrite a new claim.
    delay=result.get('retry_after',0)
    delay=min(3600,max(0,delay)) if type(delay) is int else 0
    message={'accepted':'Your email was accepted for sending. Delivery is not yet confirmed.',
             'uncertain':'Sending is not confirmed. Retry only this same invitation.',
             'rejected':'The email service did not accept this invitation. Retry the same email later or use your seller conversation.'}[status]
    db.execute('''UPDATE ih_seller_emails SET state=?,inflight_until=0,provider_id=?,message=?,next_attempt=?
        WHERE request_id=? AND claim_id=? AND state='sending' ''',
        (status,result.get('provider_id') if status=='accepted' else None,
         message,time.time()+delay,request_id,claim_id))
    return draft(db,row)
