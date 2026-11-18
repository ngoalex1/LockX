"""Actual result/publication/queue hooks; local evidence and mocked mail only."""
import asyncio
import json
import time

import httpx

import in_hand as ih
import verification_notifications as notify
import verification_queue as queue
from test_in_hand import assessment
from test_verification_notifications import OWNER, local, profile, seed


def queued_request(monkeypatch, *, auto=True):
    monkeypatch.setenv('LOCKX_VERIFICATION_QUEUE_ENABLED','1')
    monkeypatch.setenv('LOCKX_IN_HAND_VISION_MODEL','gpt-4.1')
    with ih.database() as db:
        identifier=seed(db,auto=auto,created=time.time()-30)
        raw=json.loads(db.execute('SELECT listing FROM ih_requests WHERE id=?',(identifier,)).fetchone()[0])
        listing=ih.StoredListing.model_validate({**raw,'consent':True})
        db.execute('UPDATE ih_requests SET listing=? WHERE id=?',(listing.model_dump_json(),identifier))
        notify.bind_identity(db,profile())
        ih.store_media(db,identifier,'video','video/webm',b'local-integration-video')
        db.execute("UPDATE ih_requests SET status='processing',analysis_status='pending' WHERE id=?",(identifier,))
        queue.enqueue(db,identifier)
    claim=queue.claim_job('local-notification-integration')
    assert claim and claim['request_id']==identifier
    with ih.database() as db:
        db.execute("UPDATE ih_requests SET analysis_status='pending' WHERE id=?",(identifier,))
    return identifier,claim


def test_actual_analysis_and_publication_wait_for_queue_commit_then_email_once(local,monkeypatch):
    identifier,claim=queued_request(monkeypatch)
    monkeypatch.setattr(ih,'visual_ready',lambda:True)
    monkeypatch.setattr(ih,'vision_call',lambda *_a,**_k:assessment(count=2))
    monkeypatch.setattr(ih,'auto_publish_confirmed',lambda *_a,**_k:None)
    ih.analyze(identifier,queue_claim=claim)
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM verification_notification_assessments').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM verification_notifications').fetchone()[0]==0
        row=db.execute('SELECT * FROM ih_requests WHERE id=?',(identifier,)).fetchone()
        assert row['analysis_status']=='complete'
        ih.publish_confirmed_photos(db,row,require_auto=True,queue_claim=claim)
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM verification_notifications').fetchone()[0]==0
    assert queue.finish_job(claim)
    calls=[]
    async def accepted(payload,key):
        # An independent writer can start while the provider call is in flight.
        with ih.database() as db:
            db.execute('BEGIN IMMEDIATE')
        calls.append((payload,key))
        return {'state':'accepted','provider_id':'local-provider-id'}
    async def current_profile(owner):
        assert owner==OWNER
        with ih.database() as db:
            db.execute('BEGIN IMMEDIATE')
        return profile()
    monkeypatch.setattr(notify,'deliver',accepted)
    monkeypatch.setattr(notify,'resolve_identity',current_profile)
    assert asyncio.run(notify.drain_once(ih.database))
    assert len(calls)==1
    assert '?account=1' in calls[0][0]['text']
    assert identifier in calls[0][0]['text']
    assert calls[0][0]['to']==['buyer@example.test']
    assert not asyncio.run(notify.drain_once(ih.database))
    with ih.database() as db:
        row=db.execute('SELECT * FROM verification_notifications').fetchone()
        assert row['owner_id']==OWNER and row['attempt_id']==identifier
        assert row['email_state']=='accepted'


def test_temporary_queue_errors_do_not_email_but_final_failure_does(local,monkeypatch):
    identifier,claim=queued_request(monkeypatch,auto=False)
    assert queue.finish_job(claim,httpx.ConnectError('local temporary failure'))
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM verification_notifications').fetchone()[0]==0
        db.execute('UPDATE verification_jobs SET next_run=? WHERE request_id=?',(time.time()-1,identifier))
    second=queue.claim_job('local-notification-integration-final')
    assert second
    assert queue.finish_job(second,ValueError('local permanent failure'))
    with ih.database() as db:
        event=db.execute('SELECT * FROM verification_notifications').fetchone()
        assert event['kind']=='processing_failed'
        assert event['owner_id']==OWNER and event['attempt_id']==identifier


def test_old_publication_queue_resume_cannot_generate_historical_email(local,monkeypatch):
    identifier,claim=queued_request(monkeypatch)
    with ih.database() as db:
        db.execute("UPDATE ih_requests SET analysis_status='complete',status='confirmed' WHERE id=?",(identifier,))
    with ih.database() as db:
        row=db.execute('SELECT * FROM ih_requests WHERE id=?',(identifier,)).fetchone()
        ih.publish_confirmed_photos(db,row,require_auto=True,queue_claim=claim)
    assert queue.finish_job(claim)
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM verification_notifications').fetchone()[0]==0


def test_main_auth_binds_only_verified_supabase_profile(local,monkeypatch):
    import main
    monkeypatch.setenv('SUPABASE_URL','https://auth.example.test')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','local-not-a-key')
    trusted=profile(user_metadata={'email':'attacker@example.test'})
    monkeypatch.setattr(main.httpx,'get',lambda *_a,**_k:httpx.Response(200,json=trusted))
    assert main.authenticated_identity('Bearer local-verified-user')['id']==OWNER
    with ih.database() as db:
        assert db.execute('SELECT email FROM verification_identities WHERE owner_id=?',(OWNER,)).fetchone()[0]=='buyer@example.test'
    trusted['email_confirmed_at']=None
    assert main.authenticated_identity('Bearer local-verified-user')['id']==OWNER
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM verification_identities').fetchone()[0]==0
