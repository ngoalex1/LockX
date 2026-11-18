"""Included fresh recordings are bounded; previous evidence is never a retry input."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import capture_attempts as attempts
import credit_wallet as credits
import in_hand as ih
from test_buyer_proof import AUTH, BASE, app, create, funds, image, publication


def failed(record, *, state='mismatch', analysis_status='complete'):
    with ih.database() as db:
        db.execute("UPDATE ih_requests SET status=?,analysis_status=?,submitted=1,analysis=? WHERE id=?",
                   (state,analysis_status,json.dumps({'result':state,'video':{'notes':[]}}),record['id']))
        credits.settle_check(db,record['id'])


def retry(client, record):
    return client.post(BASE+'/seller/'+record['token']+'/retry-capture',json={'consent':True})


def child(client, record):
    response=retry(client,record)
    assert response.status_code==201,response.text
    return response.json()


def snapshot(record):
    with ih.database() as db:
        row=dict(db.execute('SELECT * FROM ih_requests WHERE id=?',(record['id'],)).fetchone())
        media=[tuple(row) for row in db.execute('SELECT * FROM ih_media WHERE request_id=? ORDER BY rowid',(record['id'],))]
        return row,media


def project_analysis(db,raw,request_id,root_id):
    value=json.loads(raw)
    count=len(attempts.references(db,root_id))
    mapping=attempts.projection(db,request_id,root_id,count)
    originals=value['visual']['photos']
    value['visual']['photos']=[{**originals[root_index],'photo_index':local,'finding':'supported'}
                               for local,root_index in enumerate(mapping)]
    value['visual']['same_item']='supported'
    return json.dumps(value)


def test_three_attempts_are_one_credit_and_old_parent_resume_is_idempotent(app):
    client=app[0];root=create(app).json();failed(root)
    original=snapshot(root)
    second=child(client,root)
    assert second['capture_retry']['attempt_number']==2
    assert second['capture_retry']['remaining_attempts']==1
    assert 'capture_retry_reason' not in second
    failed(second,state='inconclusive')
    third=child(client,second)
    assert third['capture_retry']['attempt_number']==3
    assert third['capture_retry']['remaining_attempts']==0
    failed(third)
    assert retry(client,third).status_code==409
    replay=child(client,root)
    assert replay['id']==second['id'] and replay['token']==second['token']
    assert replay['capture_retry']['action']=='none'
    assert replay['capture_retry']['remaining_attempts']==0
    assert snapshot(root)==original
    assert funds()==2
    with ih.database() as db:
        checks=[dict(row) for row in db.execute('SELECT * FROM credit_checks ORDER BY rowid')]
        assert [(row['state'],row['parent_request_id']) for row in checks]==[
            ('consumed',None),('included',root['id']),('included',root['id'])]
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification'").fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM ih_capture_retries').fetchone()[0]==2


def test_concurrent_clicks_create_only_one_same_photo_child_without_session_or_consent(app):
    client=app[0];root=create(app).json();failed(root)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses=list(pool.map(lambda _:retry(client,root),range(6)))
    assert {r.status_code for r in responses}=={201}
    assert len({r.json()['id'] for r in responses})==1
    second=responses[0].json()
    with ih.database() as db:
        original=attempts.references(db,root['id'],verify_bytes=True)
        assert attempts.references(db,second['id'],verify_bytes=True)==original
        row=db.execute('SELECT * FROM ih_requests WHERE id=?',(second['id'],)).fetchone()
        assert row['session_id'] is None and row['submitted'] is None and row['analysis'] is None
        assert {r[0] for r in db.execute('SELECT role FROM ih_media WHERE request_id=?',(second['id'],))}=={'listing'}
        for table in ['ih_access_keys','ih_sessions','ih_evidence_consent']:
            column='request_id'
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?',(second['id'],)).fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM ih_session_locations WHERE session_id IN (SELECT id FROM ih_sessions WHERE request_id=?)',(second['id'],)).fetchone()[0]==0
    assert funds()==2


def test_buyer_root_history_latest_and_capture_forwarding_keep_original_private_access(app):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    management={'X-LockX-Manage-Key':root['manage_key']}
    detail=client.get(BASE+'/requests/'+root['id'],headers=management).json()
    history=detail['capture_attempts']
    assert detail['status']=='mismatch'
    assert history['latest_request_id']==second['id']
    assert [a['attempt_number'] for a in history['attempts']]==[1,2]
    assert history['latest_attempt']['status']=='waiting'
    assert history['latest_attempt']['buyer_request']['buyer_funded'] is True
    assert history['latest_attempt']['buyer_request']['can_cancel'] is False
    assert history['latest_attempt']['buyer_request']['can_decline'] is False
    forwarded=client.get(BASE+'/seller/'+root['token']).json()
    assert forwarded['capture_redirect']=={'id':second['id'],'token':second['token'],'attempt_number':2,'recording_sequence_number':2,'root_photo_indices':second['root_photo_indices']}
    assert root['manage_key'] not in json.dumps(forwarded)
    direct=client.get(BASE+'/requests/'+second['id'],headers=management)
    assert direct.status_code==200
    media=direct.json()['media'][0]['id']
    assert client.get(BASE+'/media/'+media,headers=management).status_code==200
    assert direct.json()['management_read_only'] is False
    assert direct.json()['can_withdraw'] is True
    assert client.post(BASE+f"/requests/{second['id']}/analyze",headers=management,json={}).status_code==409
    assert client.post(BASE+f"/requests/{second['id']}/publish",headers=management,json={'publish_selected_photos':True}).status_code==409
    other=create(app,key='another_buyer_request_key_456').json()
    assert client.get(BASE+'/requests/'+second['id'],headers={'X-LockX-Manage-Key':other['manage_key']}).status_code==404
    assert client.get(BASE+'/requests/'+second['id'],headers={'X-LockX-Manage-Key':second['token']}).status_code==404
    assert client.get(BASE+'/requests/'+second['id']+'/seller-email',headers=AUTH).status_code==404
    assert client.delete(BASE+'/requests/'+second['id']+'/publication',headers=management).status_code==200
    with ih.database() as db:
        assert db.execute('SELECT revoked FROM ih_publications WHERE request_id=?',(second['id'],)).fetchone()[0] is not None
    assert funds()==1  # Two original checks; withdrawal did not refund the consumed first check.


def test_new_buyer_attempt_requires_fresh_share_consent(app):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    route=BASE+'/seller/'+second['token']+'/video/start'
    assert client.post(route,json={'share_evidence':False}).status_code==422
    started=client.post(route,json={'share_evidence':True})
    assert started.status_code==200
    assert started.json()['recording_seconds']==10
    with ih.database() as db:
        consent=db.execute('SELECT * FROM ih_evidence_consent WHERE request_id=?',(second['id'],)).fetchone()
        assert consent['session_id']==started.json()['session_id']
        assert consent['share_evidence']==1


def test_original_private_key_can_retry_child_technical_processing_without_another_debit(app,monkeypatch):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    failed(second,state='inconclusive',analysis_status='failed')
    calls=[]
    monkeypatch.setattr(ih,'visual_ready',lambda:True)
    monkeypatch.setattr(ih,'analyze',lambda identifier:calls.append(identifier))
    response=client.post(BASE+'/requests/'+second['id']+'/analyze',headers={'X-LockX-Manage-Key':root['manage_key']},json={})
    assert response.status_code==202,response.text
    assert calls==[second['id']]
    assert funds()==2


def test_descendant_capability_never_controls_its_ancestor(app):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    key='C'*43
    with ih.database() as db:
        db.execute('INSERT INTO ih_access_keys VALUES (?,?)',(second['id'],ih.access_digest(key)))
    headers={'X-LockX-Manage-Key':key}
    assert client.get(BASE+'/requests/'+root['id'],headers=headers).status_code==404
    assert client.delete(BASE+'/requests/'+root['id']+'/publication',headers=headers).status_code==404


@pytest.mark.parametrize('operation',['cancel','decline'])
def test_closing_an_unsubmitted_included_take_never_refunds_or_rewrites_original(app,operation):
    client=app[0];root=create(app).json();failed(root);before=snapshot(root);second=child(client,root)
    if operation=='cancel':
        response=client.post(BASE+'/requests/'+second['id']+'/cancel',headers={'X-LockX-Manage-Key':root['manage_key']},json={'consent':True})
    else:
        response=client.post(BASE+'/seller/'+second['token']+'/decline',json={'consent':True})
    assert response.status_code==200,response.text
    assert response.json()['state']=={'cancel':'cancelled','decline':'declined'}[operation]
    assert snapshot(root)==before
    assert funds()==2
    assert retry(client,root).status_code==409


@pytest.mark.parametrize('analysis_status',['failed','unavailable','pending','processing','queued'])
def test_technical_or_inflight_comparison_cannot_mint_a_fresh_included_attempt(app,analysis_status):
    client=app[0];root=create(app).json();failed(root,state='inconclusive',analysis_status=analysis_status)
    assert retry(client,root).status_code==409
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_capture_retries').fetchone()[0]==0
    assert funds()==(3 if analysis_status in {'failed','unavailable'} else 2)


def test_any_confirmed_attempt_stops_new_recordings_but_old_link_can_open_existing_child(app):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    failed(second,state='confirmed')
    assert retry(client,second).status_code==409
    assert child(client,root)['id']==second['id']


def test_legacy_retry_edge_is_attempt_two_and_remaining_slot_is_global(app):
    client=app[0];root=create(app).json();failed(root);second=child(client,root)
    with ih.database() as db:
        db.execute("UPDATE ih_capture_retries SET reason='low_light' WHERE request_id=?",(second['id'],))
    current=client.get(BASE+'/seller/'+second['token']).json()
    assert current['capture_retry_reason']=='low_light'
    assert current['capture_retry']['light_assist_reason']=='low_light'
    failed(second)
    third=child(client,second)
    old=client.get(BASE+'/seller/'+root['token']+'/result').json()
    assert old['capture_retry']['remaining_attempts']==0
    assert old['capture_retry']['action']=='resume'
    assert old['capture_retry']['next_attempt_number']==3
    assert third['capture_retry']['attempt_number']==3


def test_partial_active_proof_is_immutable_when_fresh_attempt_is_created(publication):
    client=publication['app'][0];root=publication['record']
    before=snapshot(root)
    proof=client.get(BASE+'/public/'+publication['id']).json()
    second=child(client,root)
    assert snapshot(root)==before
    assert client.get(BASE+'/public/'+publication['id']).json()==proof
    assert client.get(BASE+'/seller/'+second['token']+'/result').json()['verified_count']==0
    assert client.delete(BASE+'/requests/'+root['id']+'/publication',headers=AUTH).status_code==200
    assert retry(client,root).status_code==409
    assert client.post(BASE+'/seller/'+second['token']+'/video/start',json={'share_evidence':True}).status_code==410


def test_withdrawal_during_child_render_fences_new_publication_commit(publication,monkeypatch):
    client=publication['app'][0];root=publication['record'];second=child(client,root)
    started=client.post(BASE+'/seller/'+second['token']+'/video/start',json={'share_evidence':True}).json()
    with ih.database() as db:
        parent=db.execute('SELECT * FROM ih_requests WHERE id=?',(root['id'],)).fetchone()
        for media in db.execute("SELECT * FROM ih_media WHERE request_id=? AND role IN ('video','frame') ORDER BY rowid",(root['id'],)).fetchall():
            ih.store_media(db,second['id'],media['role'],media['mime'],media['content'],media['seconds'],media['label'])
        db.execute('UPDATE ih_sessions SET finished=2 WHERE id=?',(started['session_id'],))
        db.execute("UPDATE ih_requests SET status='mismatch',analysis_status='complete',analysis=?,submitted=2 WHERE id=?",(project_analysis(db,parent['analysis'],second['id'],root['id']),second['id']))
    def render(snapshot,preparation=None):
        with ih.database() as db:
            db.execute('UPDATE ih_publications SET revoked=3 WHERE id=?',(publication['id'],))
        return 'child-must-not-publish',{i:b'local-marked' for i in snapshot['eligibility']['eligible_photo_indices']}
    monkeypatch.setattr(ih,'render_publication',render)
    response=client.post(BASE+'/requests/'+second['id']+'/publish',headers=AUTH,json={'publish_selected_photos':True})
    assert response.status_code==409
    with ih.database() as db:
        assert db.execute('SELECT 1 FROM ih_publications WHERE request_id=?',(second['id'],)).fetchone() is None


def test_original_key_can_publish_and_withdraw_derived_partial_proof_without_rebinding_history(publication,monkeypatch):
    client=publication['app'][0];root=publication['record'];second=child(client,root)
    old_proof=client.get(BASE+'/public/'+publication['id']).json()
    started=client.post(BASE+'/seller/'+second['token']+'/video/start',json={'share_evidence':True}).json()
    with ih.database() as db:
        analysis=db.execute('SELECT analysis FROM ih_requests WHERE id=?',(root['id'],)).fetchone()[0]
        for media in db.execute("SELECT * FROM ih_media WHERE request_id=? AND role IN ('video','frame') ORDER BY rowid",(root['id'],)).fetchall():
            ih.store_media(db,second['id'],media['role'],media['mime'],media['content'],media['seconds'],media['label'])
        db.execute('UPDATE ih_sessions SET finished=2 WHERE id=?',(started['session_id'],))
        db.execute("UPDATE ih_requests SET status='mismatch',analysis_status='complete',analysis=?,submitted=2 WHERE id=?",(project_analysis(db,analysis,second['id'],root['id']),second['id']))
    monkeypatch.setattr(ih,'render_publication',lambda snapshot,preparation=None:('separate-child-proof',{i:b'new-child-export' for i in snapshot['eligibility']['eligible_photo_indices']}))
    management={'X-LockX-Manage-Key':root['manage_key']}
    published=client.post(BASE+'/requests/'+second['id']+'/publish',headers=management,json={'publish_selected_photos':True})
    assert published.status_code==201,published.text
    child_proof=client.get(BASE+'/public/separate-child-proof').json()
    assert child_proof['eligible_photo_indices']==[0]
    assert child_proof['total_count']==1
    assert child_proof['photos'][0]['root_photo_index']==1
    assert {p['id'] for p in child_proof['photos']}.isdisjoint({p['id'] for p in old_proof['photos']})
    assert client.get(BASE+'/public/'+publication['id']).json()==old_proof
    assert client.delete(BASE+'/requests/'+second['id']+'/publication',headers=management).status_code==200
    withdrawn=client.get(BASE+'/public/separate-child-proof').json()
    assert withdrawn['status']=='withdrawn' and withdrawn['photos']==[]
    assert client.get(BASE+'/public/separate-child-proof/photos/'+child_proof['photos'][0]['id']).status_code==404
    assert client.get(BASE+'/public/'+publication['id']).status_code==200


@pytest.mark.parametrize('mutation',['photo','listing','owner'])
def test_changed_child_cannot_create_more_attempts_or_expand_root_read_access(app,mutation):
    client=app[0];root=create(app).json();failed(root);second=child(client,root);failed(second)
    with ih.database() as db:
        if mutation=='photo':db.execute("UPDATE ih_media SET sha256='changed' WHERE request_id=?",(second['id'],))
        elif mutation=='owner':db.execute("UPDATE ih_requests SET owner_id='other-owner' WHERE id=?",(second['id'],))
        else:
            listing=json.loads(db.execute('SELECT listing FROM ih_requests WHERE id=?',(second['id'],)).fetchone()[0]);listing['title']='different item'
            db.execute('UPDATE ih_requests SET listing=? WHERE id=?',(json.dumps(listing),second['id']))
    assert retry(client,second).status_code==409
    assert client.get(BASE+'/requests/'+second['id'],headers={'X-LockX-Manage-Key':root['manage_key']}).status_code==404


def selected(client,record,indices,key):
    return client.post(BASE+'/seller/'+record['token']+'/retry-capture',json={'consent':True,'photo_indices':indices,'request_key':key})


def test_subset_projection_copies_only_selected_root_bytes_and_locks_shared_item_slot(app):
    client=app[0];root=create(app,count=4).json();failed(root)
    key='subset_intent_000000000001'
    response=selected(client,root,[3],key)
    assert response.status_code==201,response.text
    take=response.json()
    assert take['root_photo_indices']==[3]
    assert take['capture_retry']['limit_scope']=='item'
    assert take['capture_retry']['remaining_attempts']==1
    with ih.database() as db:
        assert attempts.references(db,take['id'],verify_bytes=True)==[attempts.references(db,root['id'],verify_bytes=True)[3]]
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=?",(take['id'],)).fetchone()[0]==1
    child_view=client.get(BASE+'/seller/'+take['token']).json()
    assert child_view['root_photo_indices']==[3]
    assert [p['photo_index'] for p in child_view['root_photos']]==[3]
    assert child_view['capture_retry']['retryable_photo_indices']==[3]
    assert [p['photo_index'] for p in child_view['capture_retry']['photo_attempts']]==[3]
    assert client.get(BASE+'/seller/'+take['token']+'/root-photos/0').status_code==404
    assert client.get(BASE+'/seller/'+take['token']+'/root-photos/3').status_code==200
    assert selected(client,take,[0],'outside_projection_000001').status_code==403
    assert selected(client,root,[2],key).status_code==409
    assert funds()==2


def test_single_and_all_failed_overlap_cannot_mint_two_active_captures_and_aliases_replay_after_completion(app):
    client=app[0];root=create(app,count=4).json();failed(root)
    take=selected(client,root,[1],'single_photo_intent_000001').json()
    overlap=selected(client,root,[0,1,2,3],'all_failed_intent_0000001')
    assert overlap.status_code==409
    assert overlap.json()['detail']['code']=='active_capture'
    assert overlap.json()['detail']['active_attempt']['id']==take['id']
    alias=selected(client,root,[1],'same_subset_alias_0000001')
    assert alias.status_code==201 and alias.json()['id']==take['id']
    failed(take)
    next_take=selected(client,root,[2],'different_photo_intent_001').json()
    replay=selected(client,root,[1],'same_subset_alias_0000001')
    assert replay.status_code==201 and replay.json()['id']==take['id']
    assert replay.json()['capture_retry']['remaining_attempts']==0
    # A child can neither select nor learn the capture token of a sibling subset.
    conflict=selected(client,take,[1],'child_own_scope_intent_001')
    assert conflict.status_code==409
    assert 'active_attempt' not in conflict.json()['detail']
    assert next_take['token'] not in conflict.text
    assert 'capture_redirect' not in client.get(BASE+'/seller/'+take['token']).json()
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_capture_retries').fetchone()[0]==2
    assert funds()==2


def test_partial_passed_targets_rejected_and_unverified_supported_findings_remain_selectable(publication):
    client=publication['app'][0];root=publication['record']
    assert selected(client,root,[0],'passed_photo_reject_00001').status_code==409
    take=selected(client,root,[1],'failed_photo_accept_00001')
    assert take.status_code==201 and take.json()['root_photo_indices']==[1]
    overview=client.get(BASE+'/seller/'+root['token']+'/result').json()
    assert overview['latest_capture']['id']==take.json()['id']
    assert [p['photo_index'] for p in overview['root_photos']]==[0,1,2]


def test_confirmed_subset_does_not_lock_other_root_photos_and_one_or_all_share_same_cap(app,monkeypatch):
    client=app[0];root=create(app,count=4).json();failed(root)
    take=selected(client,root,[1],'subset_can_confirm_000001').json();failed(take,state='confirmed')
    original=ih.photo_eligibility
    def eligibility(db,row):
        if row['id']==take['id']:
            return {'eligible_photo_indices':[0],'verified_count':1,'total_count':1,'partial':False}
        return original(db,row)
    monkeypatch.setattr(ih,'photo_eligibility',eligibility)
    overview=client.get(BASE+'/seller/'+root['token']+'/result').json()
    assert overview['capture_retry']['retryable_photo_indices']==[0,2,3]
    assert overview['capture_retry']['allowed'] is True
    assert overview['capture_retry']['remaining_attempts']==1
    last=selected(client,root,[0,2,3],'all_remaining_photos_00001')
    assert last.status_code==201 and last.json()['root_photo_indices']==[0,2,3]
    failed(last.json())
    assert selected(client,root,[0],'no_fourth_recording_00001').status_code==409


@pytest.mark.parametrize('indices',[[],[0,0],[-1],[4],[True],['1']])
def test_invalid_selected_indices_do_not_allocate_or_spend(app,indices):
    client=app[0];root=create(app,count=4).json();failed(root)
    assert selected(client,root,indices,'bad_selection_intent_0001').status_code==422
    with ih.database() as db:
        assert db.execute('SELECT COUNT(*) FROM ih_capture_retries').fetchone()[0]==0
    assert funds()==2
