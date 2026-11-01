"""Synthetic-only dates and nodes for evidence-based offline planning."""
from __future__ import annotations
import copy

import pytest

from math2_pack.planner import due_retest_candidates, plan_day


def item(iid,node='SYN-N0',family='F6',structure=None,eligible=True):
    return {'id':iid,'nodes':[node],'families':[family],'max_points':10,'expected':{'value':{'kind':'expr','value':'7'}},
            'version_hash':'a'*64,'structure_id':structure or iid,'h0_eligible':eligible,'initial_exposure':'CONFIRMED_UNSEEN',
            'release_status':'FORMATIVE_MACHINE_CHECKED','difficulty':{'claim':'R2_CANDIDATE_UNCALIBRATED','calibration_status':'UNKNOWN'},'source':'SYNTHETIC_TEST_ONLY'}


def attempt(iid,received='2026-01-01T01:00:00Z',**changes):
    value={'item_id':iid,'first_answer':{'raw':'SYNTHETIC_TEST_ONLY actual fixture answer','assets':[],'received_at':received},'hint_level':0,
           'completion':'COMPLETE','abandon_reason':None,'exposure_declaration':'UNSEEN_SELF_DECLARED',
           'grade':{'status':'FORMATIVE_AI_PROVISIONAL','score':10,'max_points':10,'first_divergence':None}}
    value.update(changes);return value


def fixture():
    items=[item('SYN-ORIGIN')]+[item(f'SYN-RET-{n}') for n in range(1,4)]
    state={'attempts':{'SYN-A0':attempt('SYN-ORIGIN')},'exposures':{'SYN-ORIGIN':{'state':'CONFIRMED_SEEN'}},
           'retests':{'SYN-COHORT':{'events':[{'event_id':'SYN-D0','stage':'D0','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A0','at':'2026-01-01T02:00:00Z'}]}},
           'nodes':{'SYN-N0':{'observations':[]}},'imported_returns':{}}
    return items,state


def test_true_local_d0_date_controls_due_not_event_or_build_date():
    items,state=fixture()
    state['attempts']['SYN-A0']['first_answer']['received_at']='2026-01-01T23:30:00Z' # Jan 2 in Shanghai
    state['retests']['SYN-COHORT']['events'][0]['at']='2026-01-01T00:00:00Z'
    before=due_retest_candidates(items,state,'2026-01-04')[0]
    assert before['d0_date']=='2026-01-02' and before['due_date']=='2026-01-05'
    assert before['status']=='NOT_DUE' and not before['actionable']
    due=due_retest_candidates(items,state,'2026-01-05')[0]
    assert due['status']=='READY_DUE' and due['stage']=='D3' and due['actionable']
    assert due['remaining_stages']==3 and due['candidate_item_id']!='SYN-ORIGIN'
    assert due['certification']=='CANDIDATE_NOT_H0_OR_M4'


@pytest.mark.parametrize('received',[None,'2026-01-01T09:00:00','not-a-time'])
def test_unknown_or_unaware_d0_time_never_gets_a_fabricated_date(received):
    items,state=fixture();state['attempts']['SYN-A0']['first_answer']['received_at']=received
    row=due_retest_candidates(items,state,'2026-01-30')[0]
    assert row['status']=='D0_SOURCE_PENDING'
    assert row['d0_date'] is None and row['due_date'] is None and not row['actionable']


def test_missing_d0_and_fake_complete_d14_cannot_skip_earlier_stages():
    items,state=fixture()
    state['retests']['SYN-COHORT']['events']=[{'stage':'D14','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A0'}]
    assert due_retest_candidates(items,state,'2026-01-30')[0]['status']=='D0_SOURCE_PENDING'
    _,state=fixture();state['retests']['SYN-COHORT']['events'].append({'stage':'D14','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A0'})
    row=due_retest_candidates(items,state,'2026-01-30')[0]
    assert row['status']=='BLOCKED_STAGE_SEQUENCE' and not row['actionable']


def test_hinted_or_partial_d0_is_not_a_real_independent_anchor():
    items,state=fixture();state['attempts']['SYN-A0']['hint_level']=1
    assert due_retest_candidates(items,state,'2026-01-30')[0]['status']=='BLOCKED_D0_EVIDENCE'
    state['attempts']['SYN-A0'].update(hint_level=0,completion='PARTIAL')
    assert not due_retest_candidates(items,state,'2026-01-30')[0]['actionable']


def test_d3_actual_pass_advances_next_due_to_real_d0_plus_seven():
    items,state=fixture()
    state['attempts']['SYN-A3']=attempt('SYN-RET-1','2026-01-04T01:00:00Z')
    state['retests']['SYN-COHORT']['events'].append({'stage':'D3','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A3'})
    state['exposures']['SYN-RET-1']={'state':'CONFIRMED_SEEN'}
    row=due_retest_candidates(items,state,'2026-01-08')[0]
    assert row['stage']=='D7' and row['due_date']=='2026-01-08' and row['actionable']
    assert row['candidate_item_id'] not in ('SYN-ORIGIN','SYN-RET-1')


@pytest.mark.parametrize('date3,date7',[('2026-01-08T01:00:00Z','2026-01-08T02:00:00Z'),('2026-01-02T01:00:00Z','2026-01-08T01:00:00Z')])
def test_same_day_or_premature_stages_are_blocked(date3,date7):
    items,state=fixture()
    state['attempts']['SYN-A3']=attempt('SYN-RET-1',date3);state['attempts']['SYN-A7']=attempt('SYN-RET-2',date7)
    state['retests']['SYN-COHORT']['events'] += [{'stage':'D3','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A3'},{'stage':'D7','outcome':'FORMATIVE_PASS','attempt_id':'SYN-A7'}]
    row=due_retest_candidates(items,state,'2026-01-30')[0]
    assert row['status']=='BLOCKED_STAGE_EVIDENCE' and not row['actionable']


@pytest.mark.parametrize('problem',['h0-frozen','same-structure','seen','unknown','content-frozen','different-node','one-item-short'])
def test_insufficient_actual_different_unseen_eligible_items_blocks_assignment(problem):
    items,state=fixture()
    if problem=='h0-frozen':
        for i in items:i['h0_eligible']=False
    elif problem=='same-structure':items[-1]['structure_id']=items[-2]['structure_id']
    elif problem=='seen':state['exposures'][items[-1]['id']]={'state':'CONFIRMED_SEEN'}
    elif problem=='unknown':state['exposures'][items[-1]['id']]={'state':'UNKNOWN_POSSIBLY_EXPOSED'}
    elif problem=='content-frozen':items[-1]['release_status']='FROZEN_PENDING_REVIEW'
    elif problem=='different-node':items[-1]['nodes']=['SYN-OTHER-NODE']
    else:items.pop()
    row=due_retest_candidates(items,state,'2026-01-30')[0]
    assert row['status']=='INSUFFICIENT_VERIFIED_ITEMS' and not row['actionable']
    assert 'candidate_item_id' not in row


def test_failed_or_pending_stage_returns_to_review_instead_of_skipping():
    items,state=fixture()
    state['retests']['SYN-COHORT']['events'].append({'stage':'D3','outcome':'FAIL','attempt_id':'SYN-A0'})
    assert due_retest_candidates(items,state,'2026-01-30')[0]['status']=='REGRESSED_TO_SPECIALTY'
    state['retests']['SYN-COHORT']['events'][-1]['outcome']='PENDING'
    assert due_retest_candidates(items,state,'2026-01-30')[0]['status']=='PENDING_STAGE_REVIEW'


def test_four_real_formative_stages_still_do_not_certify_h0_or_m4():
    items,state=fixture()
    for stage,index,day in [('D3',1,4),('D7',2,8),('D14',3,15)]:
        aid='SYN-A'+stage;state['attempts'][aid]=attempt(f'SYN-RET-{index}',f'2026-01-{day:02}T01:00:00Z')
        state['retests']['SYN-COHORT']['events'].append({'stage':stage,'outcome':'FORMATIVE_PASS','attempt_id':aid})
    original=copy.deepcopy(state)
    row=due_retest_candidates(items,state,'2026-01-15')[0]
    assert row['status']=='FORMATIVE_COHORT_COMPLETE_NOT_CERTIFIED' and not row['actionable']
    assert state==original and row['certification']=='CANDIDATE_NOT_H0_OR_M4'


def test_only_actionable_due_retests_reserve_budget():
    items,state=fixture()
    assert plan_day(items,state,date='2026-01-03')['minutes']['retest']==0
    assert plan_day(items,state,date='2026-01-04')['minutes']['retest']==5
    for i in items:i['h0_eligible']=False
    plan=plan_day(items,state,date='2026-01-30')
    assert plan['minutes']['retest']==0 and plan['ready_due_retests']==[]
    assert sum(plan['minutes'].values())==170
    assert any('INSUFFICIENT_VERIFIED_ITEMS' in warning for warning in plan['warnings'])


def rolling_fixture():
    items=[item(f'SYN-I{n}',f'SYN-N{n}',f'F{n+1}') for n in range(7)]
    state={'attempts':{},'nodes':{f'SYN-N{n}':{'observations':[]} for n in range(67)},'imported_returns':{},'exposures':{},'retests':{}}
    for index,day in [(0,'2026-01-08'),(1,'2026-01-04'),(2,'2026-01-03'),(3,'2026-01-10')]:
        aid=f'SYN-A{index}';state['attempts'][aid]=attempt(f'SYN-I{index}',None)
        state['nodes'][f'SYN-N{index}']['observations']=[{'attempt_id':aid,'date':day}]
        state['imported_returns'][f'SYN-RETURN-{index}']={'date':day,'attempt_count':1}
    state['attempts']['SYN-A3']['completion']='PARTIAL'
    state['attempts']['SYN-A3']['grade'].update(status='PENDING_HUMAN_REVIEW',score=None)
    state['imported_returns']['SYN-PLAN-ONLY']={'date':'2026-01-09','attempt_count':0}
    return items,state


def test_three_and_seven_day_coverage_comes_from_real_imported_attempt_dates():
    items,state=rolling_fixture();before=copy.deepcopy(state)
    plan=plan_day(items,state,date='2026-01-10');rotation=plan['rotation_3_7']
    assert rotation['known_node_count']==67 and rotation['mastery_claimed'] is False
    assert rotation['windows']['3']['covered_nodes']==['SYN-N0','SYN-N3']
    assert rotation['windows']['7']['covered_nodes']==['SYN-N0','SYN-N1','SYN-N3']
    assert 'SYN-N2' in rotation['windows']['7']['uncovered_nodes']
    assert len(rotation['windows']['3']['uncovered_nodes'])==65
    assert rotation['windows']['3']['complete_attempt_nodes']==['SYN-N0']
    assert rotation['training_days_recorded']==4 # not the plan-only Jan 9 card
    assert state==before


def test_unknown_conflicting_and_future_dates_do_not_claim_recent_coverage():
    items,state=rolling_fixture()
    state['attempts']['SYN-UNKNOWN']=attempt('SYN-I4',None)
    state['attempts']['SYN-CONFLICT']=attempt('SYN-I5','2026-01-09T01:00:00Z')
    state['nodes']['SYN-N5']['observations']=[{'attempt_id':'SYN-CONFLICT','date':'2026-01-10'}]
    state['attempts']['SYN-FUTURE']=attempt('SYN-I6','2026-01-11T01:00:00Z')
    state['imported_returns']['SYN-FUTURE']={'date':'2026-01-11'}
    rotation=plan_day(items,state,date='2026-01-10')['rotation_3_7']
    assert set(rotation['unknown_or_conflicting_date_attempts'])=={'SYN-UNKNOWN','SYN-CONFLICT'}
    assert rotation['future_date_attempts_excluded']==['SYN-FUTURE']
    assert not {'SYN-N4','SYN-N5','SYN-N6'} & set(rotation['windows']['7']['covered_nodes'])


def test_recent_node_gap_affects_choice_without_dropping_seven_family_mainline():
    items,state=rolling_fixture()
    items.append(item('SYN-Z-F1-GAP','SYN-N7','F1'))
    plan=plan_day(items,state,date='2026-01-10')
    assert 'SYN-Z-F1-GAP' in plan['schedule'] and 'SYN-I0' not in plan['schedule']
    assert plan['planned_families']==[f'F{n}' for n in range(1,8)]
    assert plan['r3_allowed'] is False
    state['attempts']['SYN-A0']['grade']['first_divergence']={'cause':'Synthetic actual condition error'}
    assert 'SYN-I0' in plan_day(items,state,date='2026-01-10')['schedule']


@pytest.mark.parametrize('date',['2026-02-30','not-a-date',True])
def test_invalid_planning_dates_are_rejected(date):
    items,state=fixture()
    with pytest.raises(ValueError):due_retest_candidates(items,state,date)
    with pytest.raises(ValueError):plan_day(items,state,date=date)
