"""A bounded same-photo attempt family. Never changes an earlier decision."""
import hashlib
import json

from fastapi import HTTPException

MAX_ATTEMPTS = 3
MAX_RECORDINGS = MAX_ATTEMPTS


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ih_capture_selections (
        request_id TEXT PRIMARY KEY REFERENCES ih_requests(id),
        root_request_id TEXT NOT NULL REFERENCES ih_requests(id), root_photo_indices TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS ih_capture_retry_keys (
        root_request_id TEXT NOT NULL REFERENCES ih_requests(id), request_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL, request_id TEXT NOT NULL REFERENCES ih_requests(id),
        PRIMARY KEY(root_request_id,request_key))''')


def projection(db, request_id, root_id, count):
    selected=db.execute('SELECT root_request_id,root_photo_indices FROM ih_capture_selections WHERE request_id=?',(request_id,)).fetchone()
    if selected is None:
        return list(range(count))  # Existing full-reference quality retries.
    try:
        indices=json.loads(selected['root_photo_indices'])
        if (selected['root_request_id'] != root_id or not isinstance(indices,list) or not indices
                or len(indices)>4 or any(type(i) is not int or not 0<=i<count for i in indices)
                or indices != sorted(set(indices))):
            raise ValueError()
        return indices
    except (ValueError,TypeError):
        raise HTTPException(409,'Invalid reference selection history') from None


def project_listing(value,indices,root_count):
    listing=json.loads(value)
    notes=listing.get('photo_notes') or []
    if indices != list(range(root_count)) and 'photo_notes' in listing:
        listing['photo_notes']=[notes[i] if i<len(notes) else '' for i in indices] if notes else []
    return listing


def _listing(value):
    listing = json.loads(value)
    # An owner may independently opt an old partial result into publication.
    # That consent flag is not a change to its item claims or reference photos.
    listing.pop('publish_matched_photos', None)
    return listing


def references(db, request_id, *, verify_bytes=False):
    columns = 'mime,sha256' + (',content' if verify_bytes else '')
    rows = db.execute(f"SELECT {columns} FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid", (request_id,)).fetchall()
    if verify_bytes and any(hashlib.sha256(row['content']).hexdigest() != row['sha256'] for row in rows):
        raise HTTPException(409, 'Saved reference photos changed; create a new check')
    return [(row['mime'], row['sha256']) for row in rows]


def family(db, request_id):
    """Derive a bounded linear family from existing/legacy unique retry edges."""
    root_id, seen = request_id, set()
    for _ in range(MAX_RECORDINGS):
        if root_id in seen:
            raise HTTPException(409, 'Invalid attempt history')
        seen.add(root_id)
        edge = db.execute('SELECT parent_request_id FROM ih_capture_retries WHERE request_id=?', (root_id,)).fetchone()
        if not edge:
            break
        root_id = edge['parent_request_id']
    else:
        raise HTTPException(409, 'Invalid attempt history')
    rows, current, seen = [], root_id, set()
    for _ in range(MAX_RECORDINGS):
        if current in seen:
            raise HTTPException(409, 'Invalid attempt history')
        seen.add(current)
        row = db.execute('SELECT * FROM ih_requests WHERE id=?', (current,)).fetchone()
        if not row:
            raise HTTPException(409, 'Invalid attempt history')
        rows.append(row)
        edge = db.execute('SELECT request_id FROM ih_capture_retries WHERE parent_request_id=?', (current,)).fetchone()
        if not edge:
            break
        current = edge['request_id']
    else:
        raise HTTPException(409, 'Invalid attempt history')
    root = rows[0]
    try:
        photos=references(db,root['id'])
        for row in rows[1:]:
            selected=projection(db,row['id'],root['id'],len(photos))
            expected=project_listing(root['listing'],selected,len(photos))
            expected.pop('publish_matched_photos',None)
            if (row['owner_id'] != root['owner_id'] or _listing(row['listing']) != expected
                    or references(db,row['id']) != [photos[i] for i in selected]):
                raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, 'Attempt photos or listing claims changed') from None
    if request_id not in {row['id'] for row in rows}:
        raise HTTPException(409, 'Invalid attempt history')
    return root, rows


def blocked(db, rows):
    if any(row['status'] in {'cancelled', 'declined'} for row in rows):
        return 'request_closed'
    ids = [row['id'] for row in rows]
    placeholders = ','.join('?' for _ in ids)
    if db.execute(f'SELECT 1 FROM ih_publications WHERE request_id IN ({placeholders}) AND revoked IS NOT NULL', ids).fetchone():
        return 'publication_withdrawn'
    return None


def publication_allowed(db, row):
    """Called again in the writer transaction after rendering has finished."""
    try:
        _, rows = family(db, row['id'])
        return blocked(db, rows) is None
    except HTTPException:
        return False


def require_capture_open(db, row):
    _, rows = family(db, row['id'])
    if reason := blocked(db, rows):
        raise HTTPException(410, 'This attempt family is closed')
    # An old link must never submit a different attempt's recording.
    if rows[-1]['id'] != row['id'] and row['status'] in {'waiting', 'capturing'}:
        raise HTTPException(409, 'Open the latest recording attempt')


def descendant(db, ancestor_id, request_id):
    try:
        _, rows = family(db, request_id)
        ids = [row['id'] for row in rows]
        return ancestor_id in ids and request_id in ids and ids.index(ancestor_id) <= ids.index(request_id)
    except HTTPException:
        return False


def photo_states(db, root, rows):
    from in_hand import photo_eligibility
    count=len(references(db,root['id']))
    result=[{'photo_index':i,'attempts_used':0,'max_attempts':None,'remaining_attempts':None,
             'allowed':False,'verified':False,'publication_id':None,'source_request_id':None} for i in range(count)]
    for row in rows:
        mapping=projection(db,row['id'],root['id'],count)
        eligible=set(photo_eligibility(db,row)['eligible_photo_indices'])
        publication=db.execute('SELECT id FROM ih_publications WHERE request_id=? AND revoked IS NULL',(row['id'],)).fetchone()
        for local,original in enumerate(mapping):
            result[original]['attempts_used']+=1
            if local in eligible and not result[original]['verified']:
                result[original].update(verified=True,source_request_id=row['id'],
                                        publication_id=publication['id'] if publication else None)
    return result


def budget_reason(db, root, rows, indices):
    # Selecting one or all failed references consumes one shared item slot.
    return 'attempt_limit' if len(rows)>=MAX_ATTEMPTS else None


def selection_fingerprint(root, indices, refs):
    return hashlib.sha256(json.dumps([root['id'],_listing(root['listing']),indices,
        [refs[i] for i in indices]],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prepare_selection(db, row, requested, request_key):
    root,rows=family(db,row['id'])
    refs=references(db,root['id'])
    permitted=set(projection(db,row['id'],root['id'],len(refs)))
    if requested is None and not request_key:
        prior=db.execute('SELECT request_id FROM ih_capture_retries WHERE parent_request_id=?',(row['id'],)).fetchone()
        if prior and not blocked(db,rows) and set(projection(db,prior['request_id'],root['id'],len(refs)))<=permitted:
            indices=projection(db,prior['request_id'],root['id'],len(refs))
            return root,rows,indices,selection_fingerprint(root,indices,refs),prior['request_id']
    if not 1<=len(refs)<=4:
        raise HTTPException(409,'Choose up to four reference photos for a fresh check')
    states=photo_states(db,root,rows)
    retryable=[item['photo_index'] for item in states if not item['verified'] and item['photo_index'] in permitted]
    indices=retryable if requested is None else requested
    if (not isinstance(indices,list) or not indices or len(indices)>4
            or any(type(i) is not int or not 0<=i<len(refs) for i in indices)
            or len(set(indices))!=len(indices)):
        raise HTTPException(422,'Choose one or more unverified original photo indices')
    indices=sorted(indices)
    if any(index not in permitted for index in indices):
        raise HTTPException(403,{'code':'selection_scope','message':'Open the original item check to choose other photos'})
    fingerprint=selection_fingerprint(root,indices,refs)
    if request_key:
        prior=db.execute('SELECT request_id,fingerprint FROM ih_capture_retry_keys WHERE root_request_id=? AND request_key=?',(root['id'],request_key)).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise HTTPException(409,{'code':'retry_reference_conflict','message':'This retry reference belongs to different selected photos'})
            return root,rows,indices,fingerprint,prior['request_id']
    elif requested is not None:
        raise HTTPException(422,'A stable retry request key is required for selected photos')
    if reason:=blocked(db,rows):
        raise HTTPException(409,{'code':reason,'message':'This verification group is closed'})
    # Legacy callers resume their direct child; they cannot allocate another
    # child merely because an earlier response was lost.
    if requested is None and not request_key:
        prior=db.execute('SELECT request_id FROM ih_capture_retries WHERE parent_request_id=?',(row['id'],)).fetchone()
        if prior and set(projection(db,prior['request_id'],root['id'],len(refs)))<=permitted:
            return root,rows,indices,fingerprint,prior['request_id']
    active=rows[-1]
    if active['id'] != root['id'] and active['status'] in {'waiting','capturing','processing'}:
        active_indices=projection(db,active['id'],root['id'],len(refs))
        if active_indices==indices:
            if request_key:
                bind_key(db,root['id'],request_key,fingerprint,active['id'])
            return root,rows,indices,fingerprint,active['id']
        detail={'code':'active_capture','message':'Finish or close the active recording before choosing different photos'}
        if set(active_indices)<=permitted:
            detail['active_attempt']={'id':active['id'],'token':active['token'],'root_photo_indices':active_indices,'recording_sequence_number':len(rows)}
        raise HTTPException(409,detail)
    if any(index not in retryable for index in indices):
        raise HTTPException(409,{'code':'photo_already_verified','message':'A selected photo has already passed; refresh this check'})
    if any(item['status']=='confirmed' and item['analysis_status']=='complete'
           and projection(db,item['id'],root['id'],len(refs))==list(range(len(refs))) for item in rows):
        raise HTTPException(409,'This item check has already been confirmed')
    if len(rows)>=MAX_RECORDINGS:
        raise HTTPException(409,'The recording history is full')
    if active['analysis_status'] != 'complete' or active['status'] not in {'mismatch','inconclusive','confirmed'}:
        raise HTTPException(409,'Complete the current comparison before starting a fresh recording')
    check=db.execute('SELECT state FROM credit_checks WHERE request_id=?',(root['id'],)).fetchone()
    if check and check['state'] not in {'consumed','reserved'}:
        raise HTTPException(409,'The original credit does not cover a fresh recording')
    if reason:=budget_reason(db,root,rows,indices):
        raise HTTPException(409,{'code':reason,'message':'This item check includes three recordings total'})
    return root,rows,indices,fingerprint,None


def bind_key(db, root_id, request_key, fingerprint, request_id):
    db.execute('INSERT INTO ih_capture_retry_keys VALUES (?,?,?,?)',(root_id,request_key,fingerprint,request_id))


def metadata(db, row, quality_reason=None):
    output={'attempt_number':1,'recording_sequence_number':1,'max_attempts':MAX_ATTEMPTS,'remaining_attempts':0,
            'limit_scope':'item','allowed':False,'action':'none','next_attempt_number':None,
            'light_assist_reason':None,'blocked_reason':'invalid_attempt_history',
            'retryable_photo_indices':[],'photo_attempts':[]}
    try:
        root,rows=family(db,row['id'])
    except HTTPException:
        return output
    ids=[item['id'] for item in rows]
    output.update(attempt_number=ids.index(row['id'])+1,recording_sequence_number=ids.index(row['id'])+1,
                  remaining_attempts=max(0,MAX_ATTEMPTS-len(rows)))
    states=photo_states(db,root,rows)
    permitted=set(projection(db,row['id'],root['id'],len(states)))
    states=[item for item in states if item['photo_index'] in permitted]
    retryable=[item['photo_index'] for item in states if not item['verified']]
    output.update(photo_attempts=states,retryable_photo_indices=retryable)
    source=db.execute('SELECT reason FROM ih_capture_retries WHERE request_id=?',(row['id'],)).fetchone()
    if source and source['reason'] in {'low_light','motion_blur'}:
        output['light_assist_reason']=source['reason']
    if reason:=blocked(db,rows):
        output['blocked_reason']=reason
        return output
    active=rows[-1]
    if active['id']!=root['id'] and active['status'] in {'waiting','capturing','processing'}:
        active_indices=projection(db,active['id'],root['id'],len(references(db,root['id'])))
        if set(active_indices)<=permitted:
            output.update(allowed=True,action='resume',next_attempt_number=len(rows),blocked_reason=None)
        else:
            output['blocked_reason']='other_active_capture'
        return output
    reason=None
    if any(item['status']=='confirmed' and item['analysis_status']=='complete'
           and projection(db,item['id'],root['id'],len(references(db,root['id'])))==list(range(len(references(db,root['id'])))) for item in rows):
        reason='already_confirmed'
    elif not retryable:
        reason='all_photos_verified'
    elif active['analysis_status'] != 'complete' or active['status'] not in {'mismatch','inconclusive','confirmed'}:
        reason='processing_retry' if active['analysis_status'] in {'failed','unavailable'} else 'comparison_not_complete'
    elif len(references(db,root['id']))>4:
        reason='photo_limit'
    else:
        check=db.execute('SELECT state FROM credit_checks WHERE request_id=?',(root['id'],)).fetchone()
        if check and check['state'] not in {'consumed','reserved'}:
            reason='credit_not_consumed'
        else:
            reason=budget_reason(db,root,rows,retryable)
    output['blocked_reason']=reason
    if reason is None:
        output.update(allowed=True,action='create',next_attempt_number=len(rows)+1,
                      light_assist_reason=quality_reason if quality_reason in {'low_light','motion_blur'} else None)
        for state in states:
            state['allowed']=not state['verified']
    return output


def redirect(db, row):
    root, rows = family(db, row['id'])
    count=len(references(db,root['id']))
    permitted=set(projection(db,row['id'],root['id'],count))
    latest=projection(db,rows[-1]['id'],root['id'],count)
    if len(rows)>1 and rows[-1]['id'] != row['id'] and not blocked(db, rows) and set(latest)<=permitted:
        return {'id':rows[-1]['id'], 'token':rows[-1]['token'], 'attempt_number':len(rows), 'recording_sequence_number':len(rows), 'root_photo_indices':projection(db,rows[-1]['id'],rows[0]['id'],len(references(db,rows[0]['id'])))}
    return None


def history(db, row, summarize):
    root, rows = family(db, row['id'])
    return {'root_request_id':root['id'], 'latest_request_id':rows[-1]['id'],
            'attempts':[dict(summarize(item), attempt_number=index+1, recording_sequence_number=index+1, root_photo_indices=projection(db,item['id'],root['id'],len(references(db,root['id']))), is_latest=index==len(rows)-1)
                        for index,item in enumerate(rows)]}
