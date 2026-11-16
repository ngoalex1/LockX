"""Consented, immutable supporting evidence scoped to an approved publication."""
import hashlib
import json
import math
import re
import time

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

HEADERS = {"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff", "Referrer-Policy":"no-referrer"}


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ih_evidence_consent (
        session_id TEXT PRIMARY KEY REFERENCES ih_sessions(id), request_id TEXT NOT NULL,
        share_evidence INTEGER NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS ih_publication_evidence (
        publication_id TEXT PRIMARY KEY REFERENCES ih_publications(id),
        payload TEXT NOT NULL, sha256 TEXT NOT NULL)""")


def record_capture_consent(db,request_id,session_id,share_evidence):
    ensure_schema(db)
    session=db.execute('SELECT * FROM ih_sessions WHERE id=? AND request_id=?',(session_id,request_id)).fetchone()
    if not session or session['finished'] or type(share_evidence) is not bool:
        raise HTTPException(409,'Recording sharing must be chosen before capture begins')
    db.execute('INSERT INTO ih_evidence_consent VALUES (?,?,?,?)',(session_id,request_id,int(share_evidence),time.time()))


def _safe_text(value,limit=280):
    text=' '.join(str(value or '').split())[:limit]
    if re.search(r'barcode|\bqr\b|password|credential|redemption|access.?code|https?://',text,re.I):
        return 'Compare the visible details in the listing photo and this cited frame.'
    return text


def prepare(db,row,approved_indices):
    ensure_schema(db)
    consent=db.execute('SELECT * FROM ih_evidence_consent WHERE session_id=? AND request_id=? AND share_evidence=1',(row['session_id'],row['id'])).fetchone()
    if not consent:
        return None
    session=db.execute('SELECT * FROM ih_sessions WHERE id=? AND request_id=?',(row['session_id'],row['id'])).fetchone()
    if not session or not session['finished']:
        raise HTTPException(409,'Complete the same recording before publishing its evidence')
    listing=json.loads(row['listing'])
    if listing.get('capture_mode')=='digital':
        return None
    analysis=json.loads(row['analysis'] or '{}')
    visual=analysis.get('visual') or {}
    media=[dict(m) for m in db.execute('SELECT id,role,mime,sha256,seconds,label,LENGTH(content) AS bytes FROM ih_media WHERE request_id=? ORDER BY rowid',(row['id'],))]
    refs=[m for m in media if m['role']=='listing']
    frames=[m for m in media if m['role']=='frame']
    videos=[m for m in media if m['role']=='video']
    if len(videos)!=1 or not frames:
        raise HTTPException(409,'The recording evidence is incomplete')
    if videos[0]['mime'] not in {'video/mp4','video/webm'} or any(m['mime']!='image/jpeg' for m in [*refs,*frames]):
        raise HTTPException(409,'Supporting media has an unsupported format')
    findings={f.get('photo_index'):f for f in visual.get('photos',[]) if isinstance(f,dict)}
    assets={'video':videos[0]}
    photos=[]
    for index in approved_indices:
        finding=findings.get(index,{})
        if not 0<=index<len(refs) or finding.get('finding')!='supported':
            raise HTTPException(409,'Only approved reference photos may share supporting evidence')
        citations=[]
        for fi in finding.get('frame_indices',[]):
            if type(fi) is not int or not 0<=fi<len(frames):
                raise HTTPException(409,'The supporting frame reference is invalid')
            frame=frames[fi]
            if frame['seconds'] is None or not math.isfinite(frame['seconds']) or frame['seconds']<0:
                continue
            key=f'frame-{fi}'
            assets[key]=frame
            if fi not in [f['frame_index'] for f in citations]:
                citations.append({'frame_index':fi,'seconds':frame['seconds'],'media_key':key})
        if not citations:
            raise HTTPException(409,'Approved photos need actual supporting video frames')
        reference_key=f'reference-{index}'
        assets[reference_key]=refs[index]
        regions=[]
        for region in analysis.get('evidence_regions',[]) if isinstance(analysis.get('evidence_regions',[]),list) else []:
            if (not isinstance(region,dict) or type(region.get('photo_index')) is not int or type(region.get('frame_index')) is not int
                    or region.get('photo_index')!=index or region.get('frame_index') not in [f['frame_index'] for f in citations]
                    or region.get('reference_sha256')!=refs[index]['sha256']
                    or region.get('frame_sha256')!=frames[region['frame_index']]['sha256']
                    or region.get('provenance')!='ai_highlight_geometrically_supported'):
                continue
            if not all(k in region for k in ('label','evidence','reference_box','frame_box')):
                continue
            boxes=[region['reference_box'],region['frame_box']]
            if any(not isinstance(b,dict) or set(b)!={'x','y','width','height'}
                   or any(type(b[k]) not in {int,float} or not math.isfinite(b[k]) for k in b)
                   or min(b['x'],b['y'])<0 or min(b['width'],b['height'])<=0
                   or b['x']+b['width']>1 or b['y']+b['height']>1 for b in boxes):
                continue
            regions.append({**{k:region[k] for k in ('photo_index','frame_index','reference_box','frame_box','provenance')},
                            'label':_safe_text(region['label'],80),'evidence':_safe_text(region['evidence'],240)})
        photos.append({'photo_index':index,'reference_key':reference_key,'finding':'supported',
                       'evidence':_safe_text(finding.get('evidence')),'frames':citations,'regions':regions[:3]})
    return {'version':1,'request_id':row['id'],'session_id':row['session_id'],'captured':session['finished'],
            'video_key':'video','photos':photos,'media':assets,
            'listing_url':listing.get('listing_url') or None}


def store(db,publication_id,prepared):
    if prepared is None:
        return
    payload=json.dumps(prepared,sort_keys=True,separators=(',',':'),allow_nan=False)
    db.execute('INSERT INTO ih_publication_evidence VALUES (?,?,?)',(publication_id,payload,hashlib.sha256(payload.encode()).hexdigest()))


def _bound(db,publication_id,current_manifest):
    pub=db.execute('SELECT * FROM ih_publications WHERE id=? AND revoked IS NULL',(publication_id,)).fetchone()
    if not pub or not current_manifest:
        raise HTTPException(404,'Supporting evidence is not available')
    stored=db.execute('SELECT * FROM ih_publication_evidence WHERE publication_id=?',(publication_id,)).fetchone()
    if not stored:
        return None
    if hashlib.sha256(stored['payload'].encode()).hexdigest()!=stored['sha256']:
        raise HTTPException(410,'This supporting evidence record is no longer valid')
    data=json.loads(stored['payload'])
    row=db.execute('SELECT session_id FROM ih_requests WHERE id=?',(pub['request_id'],)).fetchone()
    session=db.execute('SELECT finished FROM ih_sessions WHERE id=? AND request_id=?',(data['session_id'],pub['request_id'])).fetchone()
    consent=db.execute('SELECT 1 FROM ih_evidence_consent WHERE session_id=? AND request_id=? AND share_evidence=1',(data['session_id'],pub['request_id'])).fetchone()
    indices={p['photo_index'] for p in data['photos']}
    if (not row or row['session_id']!=data['session_id'] or data['request_id']!=pub['request_id'] or not consent
            or not session or session['finished']!=data['captured']
            or indices!=set(current_manifest['eligible_photo_indices'])):
        raise HTTPException(410,'This supporting evidence record is no longer valid')
    for media in data['media'].values():
        current=db.execute('SELECT request_id,role,mime,sha256,seconds,label,LENGTH(content) AS bytes FROM ih_media WHERE id=?',(media['id'],)).fetchone()
        if not current or any(current[k]!=media[k] for k in ('role','mime','sha256','bytes','seconds','label')) or current['request_id']!=pub['request_id']:
            raise HTTPException(410,'Supporting media changed after publication')
    return data


def get_payload(db,publication_id,current_manifest):
    data=_bound(db,publication_id,current_manifest)
    if data is None:
        return {'available':False,'photos':[]}
    return {'available':True,'version':1,'captured':data['captured'],'video_key':data['video_key'],
            'listing_url':data['listing_url'],'photos':data['photos'],
            'scope':'AI-highlighted details are explanatory regions. Compare the original views yourself. They do not certify authenticity or ownership.'}


def _range(header,length):
    if not header:
        return 0,length-1,200
    if not isinstance(header,str) or len(header)>100:
        raise HTTPException(416,'Use one bounded byte range',headers={'Content-Range':f'bytes */{length}'})
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
    if not match or not any(match.groups()):
        raise HTTPException(416,'Use one valid byte range',headers={'Content-Range':f'bytes */{length}'})
    start,end=match.groups()
    if not start:
        count=int(end)
        if count<=0:
            raise HTTPException(416,'Invalid byte range',headers={'Content-Range':f'bytes */{length}'})
        start,end=max(0,length-count),length-1
    else:
        start,end=int(start),int(end) if end else length-1
    if start>=length or end<start:
        raise HTTPException(416,'Range outside recording',headers={'Content-Range':f'bytes */{length}'})
    return start,min(end,length-1),206


def get_media_response(db,publication_id,media_key,current_manifest,*,range_header=None,reader_factory=None):
    data=_bound(db,publication_id,current_manifest)
    media=(data or {}).get('media',{}).get(media_key)
    if not media:
        raise HTTPException(404,'Supporting media not found')
    length=media['bytes']
    start,end,status=_range(range_header,length)
    headers={**HEADERS,'Accept-Ranges':'bytes','Content-Length':str(end-start+1)}
    if status==206:
        headers['Content-Range']=f'bytes {start}-{end}/{length}'
    if reader_factory is None:
        content=db.execute('SELECT substr(content,?,?) FROM ih_media WHERE id=?',(start+1,end-start+1,media['id'])).fetchone()[0]
        return Response(content,status_code=status,media_type=media['mime'],headers=headers)
    def chunks():
        offset=start
        while offset<=end:
            with reader_factory(read_only=True) as reader:
                active=reader.execute('SELECT 1 FROM ih_publications WHERE id=? AND revoked IS NULL',(publication_id,)).fetchone()
                if not active:
                    return
                content=reader.execute('SELECT substr(content,?,?) FROM ih_media WHERE id=? AND request_id=? AND sha256=?',
                                       (offset+1,min(65536,end-offset+1),media['id'],data['request_id'],media['sha256'])).fetchone()
            if not content or not content[0]:
                return
            yield content[0]
            offset+=len(content[0])
    return StreamingResponse(chunks(),status_code=status,media_type=media['mime'],headers=headers)
