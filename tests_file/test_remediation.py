"""AT01–AT11 public synthetic acceptance cases; private history never embedded."""
import copy
import json
import pytest
from math2_pack.mathsafe import item_digest, check_answer, validate_math
from math2_pack.quality import mapping_errors, calibration, answered_nodes, supply_report
from math2_pack.planner import plan_day, expansion_decision
from math2_pack.session import advance, exam_report
from math2_pack.evidence import validate_audit, import_audit
from math2_pack.util import sha
from test_workflow import SyntheticBank, card_for
from math2_pack.ledger import Ledger
from math2_pack.build import build_daily
from math2_pack.returns import validate_return


def scalar_item():
    i=SyntheticBank().items()[0]
    i['model']={'type':'scalar_double','expr':'x+2*y','x_bounds':[0,1],'y_bounds':['0','x']}
    i['expected']={'value':{'kind':'expr','value':'2/3','dimension':'C'}}
    i['version_hash']=item_digest(i)
    return i


def test_AT03_wrong_integral_full_score_and_reference_conflict():
    i=scalar_item()
    bad=check_answer(i,'{"value":"5/6"}')
    assert bad['correct'] is False and bad['score']<bad['max_points']
    assert check_answer(i,'{"value":"4/6"}')['correct'] is True
    i['expected']['value']['value']='5/6';i['version_hash']=item_digest(i)
    assert check_answer(i,'{"value":"5/6"}')['error_codes']==['REFERENCE_MATH_CONFLICT']


def test_candidate_review_requires_actual_math_and_cannot_grant_teacher_status():
    from math2_pack.candidates import review_candidate
    i=scalar_item();i.update(source='LOCAL_REVIEWED_EXTENSION',teacher_review='NOT_PERFORMED',
                            training_roles=['short_7_families'])
    i['version_hash']=item_digest(i)
    assert review_candidate(i)['status']=='PASS'
    i['expected']['value']['value']='5/6';i['version_hash']=item_digest(i)
    assert review_candidate(i)['status']=='FAIL'
    i['teacher_review']='FABRICATED';i['version_hash']=item_digest(i)
    assert 'NO_TEACHER_OR_H0_AUTHORIZATION' in review_candidate(i)['errors']


def test_AT04_output_mapping_and_equivalent_span():
    from math2_pack.mathsafe import compare
    f={'kind':'span','value':[[-2],[1]],'matrix':[[1,2]]}
    assert compare([[4],[-2]],f) and not compare([[0],[0]],f)
    i=scalar_item();i['problem']='提交标准形';i['required_outputs']=['standard_form']
    assert 'UNSCORED_REQUIRED_OUTPUT:standard_form' in mapping_errors(i)
    i['expected']['standard_form']={'kind':'expr','value':'x**2','dimension':'F'}
    i['rubric'].append({'field':'standard_form','points':1})
    assert not mapping_errors(i)


def test_AT05_next_item_persists_for_three_subsequent_answers():
    items=SyntheticBank().items();plan=plan_day(items,{},date='2026-01-01')
    state=advance(plan,{},'不要额外验证，下一题')
    for iid in plan['schedule'][:3]:
        state.setdefault('attempts',[]).append({'item_id':iid})
        state=advance(plan,state)
        assert state['extra_practice_opt_out'] is True
        assert state['decision']['action']=='NEXT_MAINLINE'
        assert state['progress']['mandatory_extra_practice'] is False
    assert advance(plan,state,'结束')['decision']['action']=='END_REVIEW'


def test_AT06_difficulty_label_does_not_fill_missing_long_chain():
    bank=SyntheticBank();items=bank.items();state={'nodes':{},'attempts':{}}
    plan=plan_day(items,state,date='2026-01-01')
    assert len(plan['schedule'])==7
    assert plan['categories']['long_chain']==[] and plan['categories']['cold_probe']==[]
    assert plan['capacity_status']=='DEGRADED_FORMATIVE_ONLY'
    assert sum(x['budget_minutes'] for x in plan['budget_ledger'])==170
    assert sum(x['unfilled_minutes'] for x in plan['budget_ledger'])>0
    for item in items:item['difficulty']['claim']='R2_CERTIFIED'
    assert not any(calibration(i)['eligible_r2'] for i in items)
    # Positive supply case: explicit actual candidate records, no certified label.
    for n,role in enumerate(['long_chain']*3+['cold_probe']):
        item=copy.deepcopy(items[0]);item['id']=f'SYN-EXTRA-{n}';item['structure_id']=item['id']
        item['training_roles']=[role];item['model']['expr']=f'x+{n+201}';item['expected']['value']['value']=str(n+201);item['version_hash']=item_digest(item);items.append(item)
    plan=plan_day(items,state,date='2026-01-01')
    assert len(plan['categories']['long_chain'])==3 and len(plan['categories']['cold_probe'])==1
    assert plan['capacity_status']=='DEGRADED_FORMATIVE_ONLY'  # no invented calibration


def test_AT07_subquestion_presence_controls_coverage_and_bad_node_is_caught():
    i=scalar_item();i['nodes']=['MAP-H36'];i['node_fields']={'MAP-H36':['value']}
    assert answered_nodes(i,{'first_answer':{'raw':'{"value":"2/3"}'}})=={'MAP-H36'}
    assert answered_nodes(i,{'first_answer':{'raw':'photo only'}})==set()
    i['model']['type']='double_chain';i['nodes'].append('MAP-H34')
    assert 'NODE_TAG_MISMATCH:MAP-H34' in mapping_errors(i)


def test_AT08_AT09_seen_variants_and_seven_day_exhaustion():
    items=SyntheticBank().items();state={'nodes':{},'exposures':{},'attempts':{}}
    revised=copy.deepcopy(items[0]);revised.update(id='SYN-REV',supersedes=items[0]['id'])
    items.append(revised);state['exposures'][items[0]['id']]={'state':'CONFIRMED_SEEN'}
    assert 'SYN-REV' not in plan_day(items,state,date='2026-01-01')['schedule']
    report=supply_report(SyntheticBank().items(),{'nodes':{}},'2026-01-01')
    assert len(report['plans'][0]['schedule'])==len(report['plans'][1]['schedule'])==7
    assert report['plans'][2]['schedule']==[]
    assert report['seven_day_supply']=='INSUFFICIENT_VERIFIED_ITEMS'


def test_AT10_fast_wrong_does_not_upgrade_or_force_duration():
    attempts=[{'completion':'COMPLETE','hint_level':0,'grade':{'status':'FORMATIVE_AI_PROVISIONAL','score':3,'max_points':5}}]
    assert expansion_decision(attempts,110,True,True)['action']=='REPAIR_OR_REVIEW'
    assert expansion_decision(attempts,110,user_stopped=True)['action']=='END_REVIEW'
    attempts[0]['grade']['score']=5
    assert expansion_decision(attempts,110,True,True)['action']=='MORE_R2_TRANSFER'
    assert expansion_decision(attempts,40,True,True,willing_r3=True,time_source='USER_REPORTED')['action']=='OPTIONAL_R3_TRANSFER'
    assert exam_report([],{'attempts':{}})['predicted_150_score'] is None


def setup(tmp_path):
    bank=SyntheticBank();ledger=Ledger(tmp_path/'SYNTHETIC_TEST_ONLY')
    ledger.initialize(bank,'SYNTHETIC_TEST_ONLY')
    built=build_daily(bank,ledger,'2026-01-01',tmp_path/'daily')
    release=ledger.release(built['release_id'])
    return bank,ledger,release


def test_AT01_AT02_complete_date_binding_and_missing_attempts(tmp_path):
    bank,ledger,release=setup(tmp_path);card=card_for(release,bank)
    card.update(submission_scope='COMPLETE_SESSION',reported_answered_item_ids=release['schedule'],
                release_date='2026-01-01',date='2026-01-02')
    def check():return validate_return(card,release,{i['id']:i for i in bank.items()},ledger.replay())
    assert not check()['errors']
    card['attempts']=card['attempts'][:2]
    assert 'INCOMPLETE_ATTEMPT_COVERAGE' in {e['code'] for e in check()['errors']}
    # A genuinely early stop can still export every actual answer; it must not
    # manufacture attempts for the remaining planned questions.
    card['reported_answered_item_ids']=[a['item_id'] for a in card['attempts']]
    assert not check()['errors']
    card['release_date']='2026-01-02'
    assert 'RELEASE_BINDING' in {e['code'] for e in check()['errors']}


def test_AT11_secondary_report_atomic_append_and_export(tmp_path):
    bank,ledger,release=setup(tmp_path)
    source=b'SYNTHETIC_TEST_ONLY report states each item was answered.'
    entries=[{'item_id':i,'item_version':bank.get(i)['version_hash'],'source_quote':'each item was answered',
              'assets':[],'original_answer_status':'SOURCE_NOT_ATTACHED','net_seconds':None} for i in release['schedule']]
    report={'release_id':release['release_id'],'release_date':release['date'],'actual_training_date':'2026-01-02',
            'source_state_hash':release['source_state_hash'],'source_sha256':sha(source),
            'record_kind':'SYNTHETIC_TEST_ONLY','reported_entries':entries,'score_revisions':[],
            'verified_net_seconds':None,'certified_h0':False,'certified_m4':False}
    original=ledger.path.read_bytes()
    partial=copy.deepcopy(report);partial['reported_entries']=entries[:2]
    with pytest.raises(ValueError,match='INCOMPLETE_ATTEMPT_COVERAGE'):import_audit(ledger,partial,source)
    assert ledger.path.read_bytes()==original
    result=import_audit(ledger,report,source)
    assert result['status']=='PARTIAL_STATE_ONLY'
    assert ledger.path.read_bytes().startswith(original)
    assert ledger.replay()['attempts']=={} and ledger.replay()['imported_returns']=={}
    assert import_audit(ledger,report,source)['import_status']=='IDEMPOTENT_ALREADY_IMPORTED'
    # Later genuine originals can complete the original release without changing
    # its source hash. A real return, unlike an audit, consumes that exception.
    card=card_for(release,bank)
    assert not validate_return(card,release,{i['id']:i for i in bank.items()},ledger.replay())['errors']
    from math2_pack.evidence import export_audit
    exported=export_audit(report,source,tmp_path/'report')
    from pathlib import Path
    assert Path(exported['zip']).is_file()
    report['source_sha256']='0'*64
    assert 'SOURCE_SHA256_MISMATCH' in validate_audit(report,release,source)['errors']
