"""Craigslist reveal extends the free signed import without sending messages."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import craigslist_contact as browser
import in_hand as ih
import listing_import as importer
from listing_contacts import validate_contact
from test_buyer_proof import AUTH, BASE, app, funds, image

LISTING='https://sfbay.craigslist.org/sby/ele/d/city-test-item/1234567890.html'
RELAY='fixture-seller@sale.craigslist.org'


@pytest.fixture
def network(monkeypatch):
    state={'reveals':[],'downloads':0,'result':{'status':'revealed','email':RELAY}}
    images=[f'https://images.craigslist.org/fixture-{i}.jpg' for i in range(4)]
    html=('<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Fixture listing','image':images})+'</script>').encode()
    async def fetch(url,*,kind='html'):
        if kind=='html':return state.get('html',html),url,'text/html'
        state['downloads']+=1
        return image(images.index(url)*25),url,'image/jpeg'
    async def reveal(url):
        state['reveals'].append(url)
        if state.get('error'):raise RuntimeError('Fixture browser unavailable')
        if state.get('wait_for_download'):
            while not state['downloads']:await asyncio.sleep(0)
        return state['result']
    monkeypatch.setattr(importer,'fetch_public',fetch)
    monkeypatch.setattr(browser,'reveal_craigslist_contact',reveal)
    return state


def test_reveal_runs_alongside_photo_download_and_retains_four_photos(network):
    network['wait_for_download']=True
    result=asyncio.run(importer.import_listing(LISTING))
    assert result['status']=='ready' and len(result['photos'])==4
    assert network['reveals']==[LISTING]
    contact=result['seller_contact']
    assert contact['reveal_status']=='revealed'
    assert contact['candidates']==[{'email':RELAY,'label':'Craigslist seller relay','source':'craigslist_reply','source_url':LISTING}]
    validated=importer.validate_import_snapshot(result['import_token'],LISTING)
    assert validated['seller_contact']==contact


@pytest.mark.parametrize('status',['blocked','busy','unavailable'])
def test_failed_reveal_keeps_imported_photos_and_honest_reply_fallback(network,status):
    network['result']={'status':status,'email':None}
    result=asyncio.run(importer.import_listing(LISTING))
    assert result['status']=='ready' and len(result['photos'])==4
    assert result['seller_contact']['reveal_status']==status
    assert result['seller_contact']['candidates']==[]
    assert result['seller_contact']['contact_url']==LISTING
    assert importer.validate_import_snapshot(result['import_token'],LISTING)['seller_contact']==result['seller_contact']


@pytest.mark.parametrize('result',[None,[],{'status':'revealed','email':None},{'status':'revealed','email':'seller@gmail.com'},
 {'status':'revealed','email':'seller@sale.craigslist.org.attacker.example'},{'status':'unexpected','email':RELAY}])
def test_browser_failure_never_becomes_an_invented_or_unrelated_relay(network,result):
    network['result']=result
    response=asyncio.run(importer.import_listing(LISTING))
    assert response['seller_contact']['candidates']==[]
    assert response['seller_contact']['reveal_status']=='unavailable'


def test_browser_exception_preserves_successful_photo_import(network):
    network['error']=True
    result=asyncio.run(importer.import_listing(LISTING))
    assert result['status']=='ready' and len(result['photos'])==4
    assert result['seller_contact']['reveal_status']=='unavailable'


def test_other_sites_never_execute_a_browser(network):
    response=asyncio.run(importer.import_listing('https://market.example/items/42'))
    assert response['status']=='ready'
    assert network['reveals']==[]
    assert 'reveal_status' not in response['seller_contact']


def test_visible_seller_email_avoids_unnecessary_browser_work(network):
    network['html']=b'<title>Item</title><div class="seller-contact"><a href="mailto:seller@example.com">Email seller</a></div>'
    result=asyncio.run(importer.import_listing(LISTING))
    assert result['seller_contact']['candidates'][0]['email']=='seller@example.com'
    assert result['seller_contact']['reveal_status']=='not_needed'
    assert network['reveals']==[]


def test_signed_relay_import_defaults_prepared_email_without_spending_or_sending(app,network,monkeypatch):
    monkeypatch.setattr(importer,'time',SimpleNamespace(time=lambda:app[1][0]))
    client=app[0]
    result=client.post(BASE+'/listing-import',json={'url':LISTING}).json()
    assert funds()==3
    payload={'title':'Fixture listing','consent':True,'request_kind':'buyer','listing_url':LISTING,
             'request_key':'craigslist_fixture_request_0123456789','contact_import_token':result['import_token'],
             'import_token':result['import_token'],'imported_photo_indices':[0]}
    photo=base64.b64decode(result['photos'][0]['data_url'].split(',',1)[1])
    created=client.post(BASE+'/requests',headers=AUTH,data={'payload':json.dumps(payload)},files=[('photos',('photo.jpg',photo,'image/jpeg'))])
    assert created.status_code==201,created.text
    record=created.json();assert funds()==2
    response=client.get(BASE+f"/requests/{record['id']}/seller-email",headers=AUTH)
    assert response.status_code==200,response.text
    draft=response.json()
    assert draft['recipient']==RELAY and draft['contact_reveal_status']=='revealed'
    assert record['token'] in draft['body'] and record['manage_key'] not in draft['body']
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_seller_emails').fetchone()[0]==0
    assert funds()==2


def test_reveal_provenance_rejects_a_non_craigslist_listing_or_wrong_relay(network):
    result=asyncio.run(importer.import_listing(LISTING))
    contact=result['seller_contact']
    with pytest.raises(ValueError):validate_contact(contact,'https://market.example/item',contact['detected_at'])
    contact['candidates'][0]['email']='fake@example.com'
    with pytest.raises(ValueError):validate_contact(contact,LISTING,contact['detected_at'])
