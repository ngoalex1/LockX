import asyncio
import json
import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
import recovery_monitor as rm
from lost_found import database


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCKX_DATA_DIR', str(tmp_path))
    for key in ('LOCKX_MARKETPLACE_FEED_DIR','EBAY_CLIENT_ID','EBAY_CLIENT_SECRET','OPENAI_API_KEY','LOCKX_VISION_MODEL','RESEND_API_KEY','LOCKX_ALERT_FROM'):
        monkeypatch.delenv(key,raising=False)
    with database() as db:
        rm.initialize(db)
        db.execute("INSERT INTO reports VALUES('r','alice',?,'active','now')",(json.dumps({'brand':'Rolex','model':'Submariner'}),))
        db.execute("INSERT INTO photos VALUES('p','r','report',?,'hash')",(b'reference',))
    app=FastAPI()
    def identity(authorization: str=Header(default='alice')):
        return authorization
    app.include_router(rm.create_router(identity))
    client=TestClient(app)
    return client,tmp_path


def enable(client, **kw):
    return client.put('/api/v1/lost-found/reports/r/monitor',json={'enabled':True,'photo_analysis_consent':True,**kw})


LISTING={'source':'craigslist','external_id':'123','url':'https://example.org/item','title':'Rolex Submariner','image_urls':['https://example.org/item.jpg']}
async def collect(profile):
    return [LISTING],{'craigslist':{'status':'completed','count':1},'facebook_marketplace':'not_connected','ebay_browse':'not_connected'}

def compare(refs,listing):
    assert refs==[b'reference']
    return {'score':.91,'distinctive_match':True,'serial_conflict':False,'reasons':['Matching engraving and clasp scratch']}


def test_enable_requires_ownership_photos_and_consent(setup):
    c,_=setup
    assert c.put('/api/v1/lost-found/reports/r/monitor',headers={'authorization':'bob'},json={'photo_analysis_consent':True}).status_code==404
    assert enable(c,photo_analysis_consent=False).status_code==422
    with database() as db: db.execute('DELETE FROM photos')
    assert enable(c).status_code==422


def test_schedule_survives_restart_and_deduplicates_year_later(setup):
    c,_=setup
    assert enable(c).status_code==200
    t=1_900_000_000
    assert asyncio.run(rm.run_due(collect,compare,lambda:t))==1
    assert len(c.get('/api/v1/lost-found/recovery-alerts').json())==1
    assert c.get('/api/v1/lost-found/recovery-alerts',headers={'authorization':'bob'}).json()==[]
    assert asyncio.run(rm.run_due(collect,compare,lambda:t+rm.INTERVAL-1))==0
    assert asyncio.run(rm.run_due(collect,lambda *a:pytest.fail('unchanged candidate reanalyzed'),lambda:t+365*86400))==1
    assert len(c.get('/api/v1/lost-found/recovery-alerts').json())==1
    status=c.get('/api/v1/lost-found/reports/r/monitor').json()
    assert status['last_status']=='partial'
    assert status['next_run']==t+365*86400+rm.INTERVAL
    assert status['expires_at'] is None


@pytest.mark.parametrize('result',[{'score':.99,'distinctive_match':False,'serial_conflict':False}, {'score':.99,'distinctive_match':True,'serial_conflict':True}, {'score':.6,'distinctive_match':True,'serial_conflict':False}])
def test_generic_similarity_or_serial_conflict_never_alerts(setup,result):
    c,_=setup;enable(c)
    asyncio.run(rm.run_due(collect,lambda *a:dict(result,reasons=[]),lambda:1_900_000_000))
    assert c.get('/api/v1/lost-found/recovery-alerts').json()==[]


def test_crash_lease_and_pause(setup):
    c,_=setup;enable(c)
    t=1_900_000_000
    with database() as db: db.execute('UPDATE recovery_watches SET lease_until=?',(t+rm.LEASE,))
    assert asyncio.run(rm.run_due(collect,compare,lambda:t))==0
    assert asyncio.run(rm.run_due(collect,compare,lambda:t+rm.LEASE+1))==1
    enable(c,enabled=False)
    assert asyncio.run(rm.run_due(collect,compare,lambda:t+86400))==0


def test_recovered_report_stops_future_scans(setup):
    c,_=setup;enable(c)
    with database() as db: db.execute("UPDATE reports SET status='recovered'")
    assert asyncio.run(rm.run_due(collect,compare,lambda:1_900_000_000))==0


def test_failed_comparison_retries_next_run(setup):
    c,_=setup;enable(c);t=1_900_000_000
    def fail(*a):raise RuntimeError('provider unavailable')
    asyncio.run(rm.run_due(collect,fail,lambda:t))
    assert c.get('/api/v1/lost-found/reports/r/monitor').json()['last_status']=='comparison_failed'
    asyncio.run(rm.run_due(collect,compare,lambda:t+rm.INTERVAL))
    assert len(c.get('/api/v1/lost-found/recovery-alerts').json())==1


def test_disabling_during_comparison_suppresses_alert(setup):
    c,_=setup;enable(c)
    def disable(*args):
        enable(c,enabled=False)
        return compare(*args)
    asyncio.run(rm.run_due(collect,disable,lambda:1_900_000_000))
    assert c.get('/api/v1/lost-found/recovery-alerts').json()==[]


def test_unconnected_sources_are_not_successful_scans(setup):
    c,_=setup;enable(c)
    asyncio.run(rm.run_due(clock=lambda:1_900_000_000))
    assert c.get('/api/v1/lost-found/reports/r/monitor').json()['last_status']=='waiting_for_sources'


def test_feed_freshness_and_isolated_failure(setup,monkeypatch):
    _,root=setup;monkeypatch.setenv('LOCKX_MARKETPLACE_FEED_DIR',str(root))
    (root/'craigslist.json').write_text(json.dumps({'fetched_at':rm.time.time()-rm.INTERVAL-10,'listings':[LISTING]}))
    (root/'facebook_marketplace.json').write_text(json.dumps({'fetched_at':rm.time.time(),'listings':[LISTING]}))
    records,status=asyncio.run(rm.collect(rm.SearchProfile('r','Rolex','Submariner',None,None,None)))
    assert len(records)==1 and records[0]['source']=='facebook_marketplace'
    assert status['craigslist']=='feed_failed_or_stale'


def test_email_failure_retries_without_losing_inbox(setup,monkeypatch):
    c,_=setup;enable(c,notification_email='owner@example.org');t=1_900_000_000
    asyncio.run(rm.run_due(collect,compare,lambda:t))
    monkeypatch.setenv('RESEND_API_KEY','test');monkeypatch.setenv('LOCKX_ALERT_FROM','alerts@lockx.ai')
    calls=[]
    def post(*args,**kwargs):
        calls.append(kwargs)
        class Response:
            def raise_for_status(self):
                if len(calls)==1:raise rm.httpx.ConnectError('offline')
        return Response()
    monkeypatch.setattr(rm.httpx,'post',post)
    rm.deliver_alerts(lambda:t)
    assert c.get('/api/v1/lost-found/recovery-alerts').json()[0]['delivery_status']=='pending'
    rm.deliver_alerts(lambda:t+61)
    assert calls[0]['headers']['Idempotency-Key']==calls[1]['headers']['Idempotency-Key']
    assert c.get('/api/v1/lost-found/recovery-alerts').json()[0]['delivery_status']=='sent'


def test_owner_search_filters_persist_and_reject_external_facebook_url(setup):
    c,_=setup
    assert enable(c,postal='95111',radius=50).status_code==200
    assert c.get('/api/v1/lost-found/reports/r/monitor').json()['search_settings']['postal']=='95111'
    assert enable(c,facebook_url='https://evil.example/marketplace/search/').status_code==422
    assert enable(c,postal='bad').status_code==422


def test_real_comparison_request_contains_both_photo_groups(setup,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test');monkeypatch.setenv('LOCKX_VISION_MODEL','configured-model')
    def post(url,**kw):
        content=kw['json']['input'][0]['content']
        images=[c['image_url'] for c in content if c['type']=='input_image']
        assert images[0].startswith('data:image/jpeg;base64,')
        assert images[1]=='https://example.org/item.jpg'
        assert kw['json']['store'] is False
        class Response:
            def raise_for_status(self): pass
            def json(self):return {'output':[{'content':[{'type':'output_text','text':json.dumps(compare([b'reference'],LISTING))}]}]}
        return Response()
    monkeypatch.setattr(rm.httpx,'post',post)
    assert rm.compare_photos([b'reference'],LISTING)['distinctive_match'] is True


def test_browser_block_detection_and_missing_runtime(setup,monkeypatch):
    import marketplace_browser as mb
    assert mb.blocker('Verify you are human','https://www.craigslist.org')=='blocked_or_challenge'
    assert mb.blocker('Log in','https://facebook.com/checkpoint/')=='sign_in_required'
    assert mb.blocker('Normal public results','https://facebook.com/marketplace/search/') is None


def test_new_listing_a_year_later_is_flagged(setup):
    c,_=setup;enable(c);t=1_900_000_000
    asyncio.run(rm.run_due(collect,compare,lambda:t))
    async def later(profile):
        records,status=await collect(profile)
        return [dict(records[0],external_id='new-a-year-later')],status
    asyncio.run(rm.run_due(later,compare,lambda:t+365*86400))
    assert len(c.get('/api/v1/lost-found/recovery-alerts').json())==2


def test_browser_collector_records_challenge_instead_of_empty_success(setup):
    import marketplace_browser as mb
    class Locator:
        @property
        def first(self):return self
        async def wait_for(self,**kw):raise TimeoutError()
        async def inner_text(self,**kw):return 'Verify you are human'
    class Page:
        url='https://www.craigslist.org/search/sss'
        async def goto(self,*a,**kw):pass
        def locator(self,*a):return Locator()
    records,status=asyncio.run(mb.collect_page(Page(),'craigslist','https://www.craigslist.org/search/sss'))
    assert records==[]
    assert status['status']=='blocked_or_challenge'


def test_preflight_does_not_claim_ready_without_key(setup,monkeypatch):
    monkeypatch.setenv('LOCKX_BROWSER_SEARCH','0')
    monkeypatch.setenv('LOCKX_VISION_MODEL','gpt-4.1')
    status=rm.preflight()
    assert status['vision_key_configured'] is False
    assert status['ready'] is False
    assert status['live_browser_tested'] is False
    assert status['live_vision_tested'] is False


def test_cli_loads_private_env_without_printing_key(setup,monkeypatch,capsys):
    import sys
    _,root=setup
    settings=root/'worker.env'
    settings.write_text('OPENAI_API_KEY=private-test-value\nLOCKX_VISION_MODEL=gpt-4.1\nLOCKX_BROWSER_SEARCH=0\n')
    monkeypatch.setattr(sys,'argv',['recovery_monitor.py','--env-file',str(settings),'--preflight'])
    monkeypatch.setattr(rm,'configured_connectors',lambda:[])
    # load_dotenv mutates this process; register cleanup with monkeypatch.
    monkeypatch.setenv('OPENAI_API_KEY','')
    monkeypatch.delenv('OPENAI_API_KEY')
    monkeypatch.setenv('LOCKX_VISION_MODEL','')
    monkeypatch.delenv('LOCKX_VISION_MODEL')
    monkeypatch.setenv('LOCKX_BROWSER_SEARCH','0')
    assert rm.main()==2
    output=capsys.readouterr().out
    assert 'private-test-value' not in output
    assert json.loads(output)['vision_key_configured'] is True


def test_vision_cli_reports_quota_without_echoing_response_secrets(setup,monkeypatch,capsys):
    import sys
    monkeypatch.setattr(sys,'argv',['recovery_monitor.py','--check-vision'])
    def fail():
        response=rm.httpx.Response(429,json={'error':{'type':'insufficient_quota','code':'credit_balance_exhausted','message':'private credential must never be printed'}},request=rm.httpx.Request('POST','https://api.openai.com/v1/responses'))
        response.raise_for_status()
    monkeypatch.setattr(rm,'vision_smoke_test',fail)
    assert rm.main()==2
    output=capsys.readouterr().out
    assert 'private credential' not in output
    assert json.loads(output)['error_code']=='credit_balance_exhausted'


def test_worker_heartbeat_and_owner_scoped_health(setup,monkeypatch):
    c,_=setup
    assert c.get('/api/v1/lost-found/monitoring-health').json()['worker_healthy'] is False
    async def stop(*a):raise asyncio.CancelledError()
    monkeypatch.setattr(rm.asyncio,'sleep',stop)
    with pytest.raises(asyncio.CancelledError):asyncio.run(rm.worker_heartbeat())
    enable(c)
    health=c.get('/api/v1/lost-found/monitoring-health').json()
    assert health['worker_healthy'] is True
    assert health['your_active_watches']==1
    assert c.get('/api/v1/lost-found/monitoring-health',headers={'authorization':'bob'}).json()['your_active_watches']==0


def test_activity_counts_actual_work_and_skips_duplicates(setup):
    c,_=setup;enable(c);t=1_900_000_000
    asyncio.run(rm.run_due(collect,compare,lambda:t))
    activity=c.get('/api/v1/lost-found/monitoring-health').json()['activity']
    assert activity['totals']=={'listings_checked':1,'photo_comparisons':1,'unchanged_skipped':0,'new_flags':1,'comparison_failures':0}
    assert activity['recent_runs'][0]['status']=='partial'
    asyncio.run(rm.run_due(collect,compare,lambda:t+rm.INTERVAL))
    activity=c.get('/api/v1/lost-found/monitoring-health').json()['activity']
    assert activity['totals']['listings_checked']==2
    assert activity['totals']['photo_comparisons']==1
    assert activity['totals']['unchanged_skipped']==1
    assert activity['totals']['new_flags']==1
    other=c.get('/api/v1/lost-found/monitoring-health',headers={'authorization':'bob'}).json()['activity']
    assert all(v==0 for v in other['totals'].values())
    assert other['recent_runs']==[]


def test_worker_online_does_not_hide_browser_runtime_failure(setup,monkeypatch):
    c,_=setup
    monkeypatch.setenv('LOCKX_BROWSER_SEARCH','1')
    with database() as db:
        db.execute("INSERT INTO recovery_browser_health VALUES(1,'browser_unavailable',?)",(rm.time.time(),))
    health=c.get('/api/v1/lost-found/monitoring-health').json()
    assert health['browser_status']=='browser_unavailable'
    assert health['sources']['craigslist']=='browser_unavailable'
    assert health['sources']['facebook_marketplace']=='browser_unavailable'
