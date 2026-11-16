"""Import is free; signed source snapshots bind selected normalized uploads."""
import base64
import json
from types import SimpleNamespace

import pytest

import in_hand as ih
import listing_import as importer
from test_buyer_proof import AUTH, BASE, app, create, funds, image


@pytest.fixture
def preview(app):
    client, clock, monkeypatch = app
    monkeypatch.setattr(importer, 'time', SimpleNamespace(time=lambda:clock[0]))
    urls = [f'https://cdn.example/photo-{index}.jpg' for index in range(4)]
    structured = {'@type':'Product', 'name':'Imported collector card', 'image':urls}
    html = ('<script type="application/ld+json">'+json.dumps(structured)+'</script>').encode()
    async def fetch(url, *, kind='html'):
        if kind == 'html': return html,url,'text/html'
        index = urls.index(url)
        return image(index*25),url,'image/jpeg'
    monkeypatch.setattr(importer,'fetch_public',fetch)
    response = client.post(BASE+'/listing-import',json={'url':'https://market.example/items/123?variant=green'})
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    record=response.json()
    assert len(record['photos'])==4
    yield record


def create_import(app, preview, *, selected=(0,1), indices=None, replacements=None, **changes):
    client,*_=app
    from uuid import uuid4
    payload={'title':preview['title'],'consent':True,'request_kind':'buyer',
        'listing_url':preview['listing_url'],'request_key':str(uuid4()),
        'auto_publish':True,'publish_matched_photos':True,
        'import_token':preview['import_token'],
        'imported_photo_indices':list(selected) if indices is None else indices,**changes}
    photos=[base64.b64decode(preview['photos'][i]['data_url'].split(',',1)[1]) for i in selected]
    if replacements is not None:photos=replacements
    return client.post(BASE+'/requests',headers=AUTH,data={'payload':json.dumps(payload)},
        files=[('photos',(f'photo-{i}.jpg',data,'image/jpeg')) for i,data in enumerate(photos)])


def test_import_requires_no_authentication_and_reserves_no_credit(app,preview):
    assert preview['status']=='ready' and preview['max_photos']==4
    assert funds()==3
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_requests').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM credit_checks WHERE state='reserved'").fetchone()[0]==0


def test_selected_imported_and_manual_photos_save_bound_source_without_signing_token(app,preview):
    decoded=lambda i:base64.b64decode(preview['photos'][i]['data_url'].split(',',1)[1])
    response=create_import(app,preview,selected=(2,0),indices=[2,None,0],replacements=[decoded(2),image(77),decoded(0)])
    assert response.status_code==201,response.text
    record=response.json();assert funds()==2
    assert 'import_token' not in record and 'imported_photo_indices' not in record
    source=record['listing_import']
    assert source['listing_url']==preview['listing_url']
    assert source['imported_at']==preview['imported_at']
    assert [photo['photo_index'] for photo in source['photos']]==[0,2]
    with ih.database() as db:
        row=db.execute('SELECT * FROM ih_requests WHERE id=?',(record['id'],)).fetchone()
        stored=json.loads(row['listing'])
        assert 'import_token' not in stored and 'imported_photo_indices' not in stored
        ih.StoredListing.model_validate_json(row['listing'])
        photos=[dict(r) for r in db.execute("SELECT sha256 FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid",(record['id'],))]
        assert all(photos[entry['photo_index']]['sha256']==entry['sha256'] for entry in source['photos'])


@pytest.mark.parametrize('bad', ['token','url','bytes','expired','index','duplicate','bool','length','empty','no_token'])
def test_invalid_import_selection_fails_before_credit_hold(app,preview,bad):
    options={}
    if bad=='token':options['import_token']=preview['import_token']+'x'
    if bad=='url':options['listing_url']='https://different.example/item'
    if bad=='bytes':options['replacements']=[image(99),image(100)]
    if bad=='expired':app[1][0]=preview['expires']
    if bad=='index':options['indices']=[0,9]
    if bad=='duplicate':options['indices']=[0,0]
    if bad=='bool':options['indices']=[True,1]
    if bad=='length':options['indices']=[0]
    if bad=='empty':options['indices']=[None,None]
    if bad=='no_token':options['import_token']=''
    response=create_import(app,preview,**options)
    assert response.status_code==422,response.text
    assert funds()==3
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_requests').fetchone()[0]==0


def test_ambiguous_creation_retry_recovers_existing_request_even_after_import_expires(app,preview):
    key='stable_buyer_import_retry_0123456789'
    first=create_import(app,preview,request_key=key)
    assert first.status_code==201,first.text
    app[1][0]=preview['expires']+1
    again=create_import(app,preview,request_key=key)
    assert again.status_code==201,again.text
    assert again.json()['id']==first.json()['id'] and funds()==2


def test_plain_photo_request_keeps_prior_release_fingerprint_and_no_import_required(app):
    key='previous_release_retry_0123456789'
    first=create(app,key=key)
    assert first.status_code==201
    with ih.database() as db:
        row=db.execute('SELECT listing FROM ih_requests WHERE id=?',(first.json()['id'],)).fetchone()
        assert 'import_token' not in json.loads(row['listing'])
    again=create(app,key=key)
    assert again.status_code==201 and again.json()['id']==first.json()['id'] and funds()==2


def test_unsafe_import_url_is_rejected_without_network_or_credit(app,monkeypatch):
    async def forbidden(*args,**kwargs):raise AssertionError('Unsafe URL reached network')
    monkeypatch.setattr(importer,'fetch_public',forbidden)
    response=app[0].post(BASE+'/listing-import',json={'url':'http://127.0.0.1/private'})
    assert response.status_code==422
    assert funds()==3
