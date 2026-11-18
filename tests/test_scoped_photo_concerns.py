"""Structured local negatives cannot erase global evidence or promote identity."""
import json

import pytest
from pydantic import ValidationError

import in_hand as ih
from test_in_hand import assessment, setup
from test_in_hand_identifiers import seed_pending, enable_model, selected_labels, private_detail, identifier
from test_buyer_proof import app, publication


def issue(**changes):
    return {'photo_index':0,'reason':'local_visibility','frame_indices':[1],
            'evidence':'The relevant photographed detail is obscured in this cited view.',**changes}


def write_visual(publication, mutate):
    with ih.database() as db:
        row=db.execute('SELECT * FROM ih_requests WHERE id=?',(publication['record']['id'],)).fetchone()
        analysis=json.loads(row['analysis'])
        mutate(analysis['visual'])
        db.execute('UPDATE ih_requests SET analysis=? WHERE id=?',(json.dumps(analysis),row['id']))
        updated=db.execute('SELECT * FROM ih_requests WHERE id=?',(row['id'],)).fetchone()
        return ih.photo_eligibility(db,updated)


def test_legacy_absent_local_field_keeps_global_text_concern_fail_closed(publication):
    def legacy(visual):
        visual.pop('photo_concerns',None)
        visual['concerns']=['A serial number could not be established.']
    assert write_visual(publication,legacy)['eligible_photo_indices']==[]
    assert write_visual(publication,lambda visual:visual.update(photo_concerns=[issue(photo_index=1)]))['eligible_photo_indices']==[]


def test_valid_local_issue_only_removes_affected_independently_supported_photo(publication):
    before=write_visual(publication,lambda visual:None)
    after=write_visual(publication,lambda visual:visual.update(photo_concerns=[issue(photo_index=2,frame_indices=[4])]))
    assert before['eligible_photo_indices']==[0,2]
    assert after['eligible_photo_indices']==[0]
    response=publication['app'][0].get('/api/v1/in-hand/seller/'+publication['record']['token']+'/result').json()
    assert response['photos'][2]['finding']=='not_established'
    assert response['photos'][1]['finding']=='contradicted'


@pytest.mark.parametrize('same_item',['inconclusive','contradicted'])
def test_local_negative_cannot_bypass_preexisting_inconsistent_all_supported_guard(publication,same_item):
    def inconsistent(visual):
        visual['same_item']=same_item
        visual['photo_concerns']=[]
        for photo in visual['photos']:photo['finding']='supported'
    assert write_visual(publication,inconsistent)['eligible_photo_indices']==[]
    after=write_visual(publication,lambda visual:visual.update(photo_concerns=[issue(photo_index=1)]))
    assert after['eligible_photo_indices']==[]


@pytest.mark.parametrize('change',[
    {'reason':'identity_confirmed'},{'photo_index':True},{'photo_index':-1},
    {'frame_indices':[]},{'frame_indices':[True]},{'frame_indices':['1']},
    {'evidence':''},{'evidence':'  '},{'unknown':'untrusted'},
])
def test_malformed_local_scope_is_rejected_instead_of_silently_discarded(change):
    with pytest.raises(ValidationError):ih.PhotoConcern.model_validate(issue(**change))


@pytest.mark.parametrize('change',[{'photo_index':3},{'frame_indices':[99]}, {'frame_indices':[2]}])
def test_persisted_out_of_scope_or_unsupplied_citations_fail_closed(publication,change):
    result=write_visual(publication,lambda visual:visual.update(photo_concerns=[issue(**change)]))
    assert result['eligible_photo_indices']==[]


def test_readable_mismatch_remains_mismatch_and_high_percentage_never_promotes():
    value=assessment(photo_concerns=[issue()],identifier_checks=[identifier(reference_text='0012345',video_text='0012346',frame_indices=[1])])
    for photo in value.photos:photo.match_percentage=100
    assert ih.recommendation(value,4,{'notes':[],'frame_selection':{'selected_frame_indices':[0,1,2,3]}})=='mismatch'
    assert ih.recommendation(assessment(photo_concerns=[issue()]),4,{'notes':[]})=='inconclusive'


def test_strict_provider_schema_binds_local_issues_to_actual_photos_and_frames():
    schema=ih.strict_vision_schema(ih.VisualAssessment,[1,7,18],4)
    definition=schema['$defs']['PhotoConcern']
    assert definition['additionalProperties'] is False
    assert definition['properties']['photo_index']['enum']==[0,1,2,3]
    assert definition['properties']['frame_indices']['items']['enum']==[1,7,18]
    assert 'photo_concerns' in schema['required']
    assert ih.VisualAssessment.model_validate(assessment().model_dump(exclude={'photo_concerns'})).photo_concerns==[]


def test_same_recording_comparison_uses_structured_prompt_without_second_ai_call(setup):
    client,_,_,monkeypatch=setup
    record,_,_,_=seed_pending(setup)
    calls=[]
    def compare(schema,instructions,content,**kwargs):
        indices=selected_labels(content)
        calls.append(indices)
        assert 'Use photo_concerns' in instructions
        assert 'cannot cancel a global concern' in instructions
        assert 'readable different identifier' in instructions
        photos=[{'photo_index':i,'finding':'supported','evidence':'Distinctive corresponding marks are visible.','frame_indices':[indices[-1]]} for i in range(4)]
        return assessment(photos=photos,photo_concerns=[issue(photo_index=1,frame_indices=[indices[-1]])])
    enable_model(monkeypatch,compare)
    ih.analyze(record['id'])
    result=private_detail(client,record)
    assert len(calls)==1 and len(calls[0])<=12
    assert result['status']=='inconclusive'
    assert 1 not in result['eligible_photo_indices']
    assert result['analysis']['visual']['photos'][1]['finding']=='supported','The base assessment is retained; local negatives do not rewrite it'


def test_new_model_local_citation_not_sent_to_model_cannot_commit_a_result(setup):
    client,_,_,monkeypatch=setup
    record,_,_,_=seed_pending(setup)
    def compare(schema,instructions,content,**kwargs):
        indices=selected_labels(content)
        omitted=next(i for i in range(20) if i not in indices)
        photos=[{'photo_index':i,'finding':'supported','evidence':'A corresponding mark.','frame_indices':[indices[-1]]} for i in range(4)]
        return assessment(photos=photos,photo_concerns=[issue(frame_indices=[omitted])])
    enable_model(monkeypatch,compare)
    ih.analyze(record['id'])
    result=private_detail(client,record)
    assert result['analysis_status']=='failed'
    assert result['eligible_photo_indices']==[]
