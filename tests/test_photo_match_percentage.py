"""Appearance estimates cannot override conservative individual-item findings."""
import json

import pytest
from pydantic import ValidationError

import in_hand as ih
from test_in_hand import assessment
from test_in_hand_identifiers import identifier
from test_buyer_proof import app, publication


def photo(**changes):
    return {'photo_index':0,'finding':'supported','evidence':'Visible individual marks correspond.','frame_indices':[1],**changes}


@pytest.mark.parametrize('value',[True,False,100.1,'98',-1,101])
def test_percentage_schema_rejects_non_integer_or_out_of_bounds_values(value):
    with pytest.raises(ValidationError):ih.PhotoFinding.model_validate(photo(match_percentage=value))


@pytest.mark.parametrize('value',[None,0,49,95,100])
def test_percentage_schema_is_optional_bounded_and_legacy_compatible(value):
    assert ih.PhotoFinding.model_validate(photo(match_percentage=value)).match_percentage==value
    assert ih.PhotoFinding.model_validate(photo()).match_percentage is None


@pytest.mark.parametrize('indices,selected',[([], [1]),([9],[1]),([0],[1]),([True],[1]),([1],[[1]])])
def test_number_without_valid_supplied_frame_citations_is_not_displayed(indices,selected):
    assert ih.photo_match_percentage({},photo(frame_indices=indices,match_percentage=99),3,selected) is None


def test_no_legacy_categorical_score_is_invented_and_global_concerns_do_not_zero_appearance():
    assert ih.photo_match_percentage({},photo(),3,[1]) is None
    visual={'same_item':'inconclusive','concerns':['An identifier could not be read.'],'identifier_checks':[]}
    assert ih.photo_match_percentage(visual,photo(finding='not_established',match_percentage=95),3,[1])==95


def test_readable_number_contradiction_caps_only_appearance_and_still_mismatches():
    check=identifier(reference_text='0012345',video_text='0012346',frame_indices=[1],finding='supported')
    visual=assessment(identifier_checks=[check],photos=[photo(photo_index=i,match_percentage=99) for i in range(4)])
    ih.align_identifier_photo_findings(visual)
    assert ih.photo_match_percentage(visual.model_dump(),visual.photos[0].model_dump(),3,[1])==49
    assert ih.recommendation(visual,4,{'notes':[],'frame_selection':{'selected_frame_indices':[1]}})=='mismatch'


def test_unreadable_number_can_have_high_visual_similarity_but_remains_unverified():
    check=identifier(reference_text='0012345',video_text='',readability='unclear',finding='not_established',frame_indices=[1])
    visual=assessment(identifier_checks=[check],photos=[photo(photo_index=i,match_percentage=98) for i in range(4)])
    ih.align_identifier_photo_findings(visual)
    assert ih.photo_match_percentage(visual.model_dump(),visual.photos[0].model_dump(),3,[1])==98
    assert ih.recommendation(visual,4,{'notes':[],'frame_selection':{'selected_frame_indices':[1]}})=='inconclusive'


def test_high_appearance_score_cannot_promote_missing_identity_evidence():
    visual=assessment(same_item='inconclusive',concerns=['Insufficient individual evidence.'],photos=[photo(photo_index=i,match_percentage=100) for i in range(4)])
    assert ih.recommendation(visual,4,{'notes':[]})=='inconclusive'


def test_seller_payload_exposes_only_frame_supported_scores_without_rescoring_old_record(publication):
    client=publication['app'][0];record=publication['record'];route='/api/v1/in-hand/seller/'+record['token']+'/result'
    original=client.get(route).json()
    assert all(p['match_percentage'] is None for p in original['photos'])
    with ih.database() as db:
        row=db.execute('SELECT analysis FROM ih_requests WHERE id=?',(record['id'],)).fetchone()
        analysis=json.loads(row['analysis']);analysis['visual']['photos'][0]['match_percentage']=96
        analysis['visual']['photos'][1]['match_percentage']=98
        analysis['visual']['photos'][2]['match_percentage']=99
        analysis['visual']['photos'][2]['frame_indices']=[]
        db.execute('UPDATE ih_requests SET analysis=? WHERE id=?',(json.dumps(analysis),record['id']))
    exposed=client.get(route).json()['photos']
    assert [p['match_percentage'] for p in exposed]==[96,49,None]
