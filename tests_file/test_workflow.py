"""End-to-end file workflow tests using invented, synthetic-only bank content.

The fixtures contain no actual learner history or unpublished private questions.
They test offline packaging/state rules; the separate private bank QA checks the
real mathematical source when it is supplied locally.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from math2_pack.build import build_daily, build_specialty, return_template, verify_daily
from math2_pack.ledger import Ledger
from math2_pack.planner import expansion_decision, plan_day
from math2_pack.util import canonical, sha, load_json


class SyntheticBank:
    """Protocol-compatible fixture, explicitly not a reviewed production bank."""
    def __init__(self):
        self._items=[]
        for family in range(1,8):
            for variant in ("A","B","BRIDGE"):
                iid=f"SYN-F{family}-{variant}"
                value=100+family
                row={"id":iid,"problem":f"SYNTHETIC_TEST_ONLY. Define p(t)=t+{value}; compute p(0). Fixture {iid}.","nodes":[f"SYN-NODE-{family}"],"families":[f"F{family}"],"max_points":10,
                     "source":"SYNTHETIC_TEST_ONLY","tier":"SYNTHETIC_TEST_ONLY","release_status":"FORMATIVE_MACHINE_CHECKED","initial_exposure":"NEW_GENERATED_UNSEEN","h0_eligible":False,"structure_id":f"SYN-STRUCTURE-{family}-{variant}",
                     "difficulty":{"claim":"R1_REPAIR" if variant=="BRIDGE" else "R2_CANDIDATE_UNCALIBRATED","calibration_status":"UNKNOWN"},
                     "expected":{"value":{"kind":"expr","value":str(value),"dimension":"F"}},
                     "solution":{"conceptual_core":"SYNTHETIC_TEACHER_ONLY_"+iid,"solution_steps":[{"result":"Substitute zero in the synthetic function."}]},
                     "rubric":[{"field":"value","points":10}],"hints":[{"level":1,"text":"SYNTHETIC_HINT_ONLY_"+iid}]}
                row["version_hash"]=sha(canonical(row));self._items.append(row)

    def items(self):return copy.deepcopy(self._items)
    def get(self,iid):return next(copy.deepcopy(i) for i in self._items if i['id']==iid)
    def nodes(self):return [{"id":f"SYN-NODE-{n}","name":f"Synthetic family {n}","module":"SYNTHETIC_TEST_ONLY"} for n in range(1,8)]
    def pilot_summary(self):return {}  # No real PILOT fixture, marks, times or exposure.
    def validate(self):return {"status":"PASS","scope":"SYNTHETIC_TEST_ONLY_INTERFACE_FIXTURE","errors":[],"human_reviews":0,"h0_certified":0}
    @property
    def hash(self):return sha(canonical(self._items))
    def specialties(self):
        return {topic:{"topic":topic,"status":"PLANNED","steps":[{"title":"Synthetic explanation","explanation":"Read the current synthetic concept.","problem":"Explain substitution in your own words.","expected":None,"status":"NOT_STARTED"},{"title":"Synthetic bridge","item_id":"SYN-F1-BRIDGE","expected":None,"status":"NOT_STARTED"},{"title":"Synthetic new candidate","item_id":"SYN-F1-B","expected":None,"status":"NOT_STARTED"}]} for topic in ("Q03","Q06")}


@pytest.fixture
def workflow(tmp_path):
    bank=SyntheticBank();ledger=Ledger(tmp_path/'synthetic-records')
    ledger.initialize(bank,record_kind="SYNTHETIC_TEST_ONLY")
    return bank,ledger,tmp_path


def build_one(bank,ledger,root,date="2026-01-01",**kw):
    outcome=build_daily(bank,ledger,date=date,output=root/'daily-packs',**kw)
    folder=Path(outcome['folder'])
    release=load_json(folder/'BUILD_CONTEXT_PRIVATE.json')
    return folder,release


def card_for(release,bank,all_main=True):
    card=return_template(release)
    selected=release['schedule'] if all_main else release['schedule'][:1]
    for n,iid in enumerate(selected):
        item=bank.get(iid)
        card['presented_items'].append({"item_id":iid,"item_version":item['version_hash'],"presented_at":None,"exposure":"CONFIRMED_SEEN"})
        card['attempts'].append({"attempt_id":f"SYN-ATTEMPT-{release['release_id']}-{n}","item_id":iid,"item_version":item['version_hash'],
            "first_answer":{"raw":json.dumps({k:v['value'] for k,v in item['expected'].items()}),"assets":[],"received_at":None},
            "hint_level":0,"exposure_declaration":"UNKNOWN_POSSIBLY_EXPOSED","grade":{"status":"FORMATIVE_AI_PROVISIONAL","score":item['max_points'],"max_points":item['max_points'],"confidence":"LOW","first_divergence":None,"step_scores":[{"step_id":"SYN-STEP-1","earned":item['max_points'],"maximum":item['max_points'],"reason":"SYNTHETIC_TEST_ONLY substitution verified in a fixture, no real student grade."}]},
            "feedback_at":None,"net_seconds":None,"completion":"COMPLETE","abandon_reason":None,"supplements":[]})
    card['review']={"summary":"SYNTHETIC_TEST_ONLY offline roundtrip; no real learning or certification.","unresolved":[],"next_actions":["Build next synthetic candidate day"]}
    return card


def test_build_return_import_next_day_uses_actual_imported_state(workflow):
    bank,ledger,root=workflow
    initial=ledger.replay()
    folder,release=build_one(bank,ledger,root)
    assert verify_daily(folder)['status']=='PASS'
    assert len(release['schedule'])==7
    assert ledger.replay()['source_state_hash']==initial['source_state_hash']
    result=ledger.import_return(card_for(release,bank),release,bank)
    assert result['status']=='IMPORTED_FORMATIVE_ONLY'
    state=ledger.replay()
    assert len(state['attempts'])==7 and state['record_kind']=='SYNTHETIC_TEST_ONLY'
    assert all(a['net_seconds'] is None for a in state['attempts'].values())
    assert all(len(node['observations'])==1 for node in state['nodes'].values())
    _,next_release=build_one(bank,ledger,root,date="2026-01-02")
    assert not set(next_release['schedule']) & set(release['schedule'])
    assert len(next_release['schedule'])==7
    assert next_release['source_state_hash']==state['source_state_hash']
    assert next_release['adaptation_status']=='FROM_ACTUAL_IMPORTED_STATE'


def test_seen_items_are_not_relabelled_as_independent_unknown_candidates(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root)
    ledger.import_return(card_for(release,bank),release,bank)
    folder,next_release=build_one(bank,ledger,root,date='2026-01-02')
    lines=(folder/'coach/independent_transfer_candidates.jsonl').read_text(encoding='utf-8').splitlines()
    candidates=[json.loads(line) for line in lines]
    previous_seen=set(release['schedule'])
    for row in candidates:
        assert row['item_id'] not in previous_seen, 'Known seen questions cannot become independent unknown candidates.'


def test_generation_and_specialty_zip_do_not_record_learning(workflow):
    bank,ledger,root=workflow
    before=ledger.path.read_bytes();state=ledger.replay()
    folder,release=build_one(bank,ledger,root)
    result=build_specialty(bank,ledger,'Q03',root/'specialty')
    assert result['status']=='PLANNED_NOT_TRAINED'
    specialty=load_json(Path(result['folder'])/'SPECIALTY_PLAN_PRIVATE.json')
    assert specialty['status']=='PLANNED' and specialty['actual_training_events']==[] and specialty['D0'] is None
    assert ledger.path.read_bytes()==before
    assert ledger.replay()['attempts']=={} and ledger.replay()['exposures']=={}
    assert ledger.replay()['source_state_hash']==state['source_state_hash']
    public=load_json(folder/'student/daily_plan_public.json')
    assert public['actual_answered']==0


def test_student_zip_has_only_problems_generic_instructions_and_no_teacher_payload(workflow):
    bank,ledger,root=workflow
    folder,release=build_one(bank,ledger,root)
    with zipfile.ZipFile(folder/release['student_zip']) as z:
        text='\n'.join(z.read(n).decode('utf-8') for n in z.namelist())
        assert 'SYNTHETIC_TEACHER_ONLY_' not in text
        assert 'SYNTHETIC_HINT_ONLY_' not in text
        assert '"expected"' not in text and '"rubric"' not in text
        assert 'SYN-F1-B' not in text
        assert len([n for n in z.namelist() if n.startswith('problems/')])==7
    with zipfile.ZipFile(folder/release['coach_zip']) as z:
        assert 'solutions_and_rubrics.jsonl' in z.namelist()
        assert 'SYNTHETIC_TEACHER_ONLY_' in z.read('solutions_and_rubrics.jsonl').decode()
    assert all(ref['exposure_eligibility']=='UNKNOWN_POSSIBLY_EXPOSED' for ref in release['item_refs'])


def test_active_item_pack_does_not_include_future_problems_or_solutions(workflow):
    bank,ledger,root=workflow
    folder,release=build_one(bank,ledger,root,mode='ACTIVE_ITEM_STRICT')
    with zipfile.ZipFile(folder/release['student_zip']) as z:
        rows=[json.loads(line) for line in z.read('problems_student.jsonl').decode().splitlines()]
        assert len(rows)==1
    with zipfile.ZipFile(folder/'ACTIVE_COACH_001.zip') as z:
        text='\n'.join(z.read(n).decode('utf-8') for n in z.namelist())
        for iid in release['schedule'][1:]:
            assert bank.get(iid)['problem'] not in text
            assert 'SYNTHETIC_TEACHER_ONLY_'+iid not in text


def test_missing_previous_return_stops_and_override_does_not_claim_adaptation(workflow):
    bank,ledger,root=workflow
    build_one(bank,ledger,root)
    before=ledger.replay()['source_state_hash']
    with pytest.raises(ValueError,match='MISSING_PREVIOUS_RETURN'):
        build_one(bank,ledger,root,date='2026-01-02')
    _,release=build_one(bank,ledger,root,date='2026-01-02',allow_unreturned=True)
    assert release['adaptation_status']=='BASELINE_NO_NEW_RETURN'
    assert ledger.replay()['source_state_hash']==before


def test_unknown_times_survive_import_and_fake_net_time_is_rejected(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root)
    card=card_for(release,bank,False)
    bad=copy.deepcopy(card);bad['attempts'][0]['net_seconds']=30
    before=ledger.path.read_bytes()
    with pytest.raises(ValueError,match='NET_TIME_WITHOUT_EVIDENCE'):
        ledger.import_return(bad,release,bank)
    assert ledger.path.read_bytes()==before
    ledger.import_return(card,release,bank)
    state=ledger.replay();a=next(iter(state['attempts'].values()))
    assert a['net_seconds'] is None and a['first_answer']['received_at'] is None and a['feedback_at'] is None


def test_replay_ignores_cache_deletion_or_forged_cache_and_detects_event_tamper(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root)
    ledger.import_return(card_for(release,bank,False),release,bank)
    correct=ledger.replay()
    (ledger.folder/'state.json').unlink()
    assert ledger.replay()==correct
    (ledger.folder/'state.json').write_text('{"certified_m4": true}',encoding='utf-8')
    assert ledger.replay()==correct
    text=ledger.path.read_text(encoding='utf-8');ledger.path.write_text(text.replace('GENESIS','GENESIX',1),encoding='utf-8')
    with pytest.raises(ValueError,match='hash/sequence'):
        ledger.replay()


def test_identical_return_retries_are_idempotent_even_with_deleted_cache(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    first=ledger.import_return(card,release,bank);before=ledger.path.read_bytes()
    (ledger.folder/'state.json').unlink()
    retried=ledger.import_return(copy.deepcopy(card),release,bank)
    assert retried['status']=='IDEMPOTENT_ALREADY_IMPORTED'
    assert retried['card_hash']==first['card_hash']
    assert ledger.path.read_bytes()==before and ledger.replay()['ledger_events']==2


def test_same_return_concurrent_import_commits_once(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:ledger.import_return(copy.deepcopy(card),release,bank),range(6)))
    assert sum(r['status']=='IMPORTED_FORMATIVE_ONLY' for r in results)==1
    assert ledger.replay()['ledger_events']==2
    assert len(ledger.replay()['attempts'])==1


def test_different_concurrent_cards_from_same_state_cannot_both_apply(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);a=card_for(release,bank,False);b=copy.deepcopy(a)
    b['attempts'][0]['attempt_id']+='-ALT'
    def attempt(card):
        try:return ledger.import_return(card,release,bank)['status']
        except ValueError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[a,b]))
    assert results.count('IMPORTED_FORMATIVE_ONLY')==1
    assert any('STALE_STATE' in row for row in results)
    assert ledger.replay()['ledger_events']==2


def test_failure_before_commit_leaves_no_history_then_retry_succeeds(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    before=ledger.path.read_bytes()
    with pytest.raises(OSError,match='before atomic history commit'):
        ledger.import_return(card,release,bank,inject_failure=True)
    assert ledger.path.read_bytes()==before and ledger.replay()['attempts']=={}
    assert ledger.import_return(card,release,bank)['status']=='IMPORTED_FORMATIVE_ONLY'


def test_crash_after_event_commit_can_replay_and_retry_without_duplicate(workflow,monkeypatch):
    import math2_pack.ledger as ledger_module
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    actual_write=ledger_module.write_json
    def fail_cache(path,value):
        if Path(path).name=='state.json':raise OSError('SYNTHETIC cache write failure after durable event commit')
        return actual_write(path,value)
    monkeypatch.setattr(ledger_module,'write_json',fail_cache)
    with pytest.raises(OSError,match='after durable event commit'):
        ledger.import_return(card,release,bank)
    assert ledger.replay()['ledger_events']==2 and len(ledger.replay()['attempts'])==1
    monkeypatch.setattr(ledger_module,'write_json',actual_write)
    assert ledger.import_return(card,release,bank)['status']=='IDEMPOTENT_ALREADY_IMPORTED'
    assert ledger.replay()['ledger_events']==2


def test_duplicate_specialty_interaction_ids_across_returns_do_not_count_twice(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    event={"event_id":"SYN-INTERACTION-ONCE","repair_id":"SYN-REPAIR","origin_attempt_id":card['attempts'][0]['attempt_id'],"status":"ATTEMPTED","actual_answer":"SYNTHETIC_TEST_ONLY: my one actual correction.","item_id":None,"at":None}
    card['repair_events']=[event]
    ledger.import_return(card,release,bank)
    _,next_release=build_one(bank,ledger,root,date='2026-01-02');next_card=card_for(next_release,bank,False)
    next_card['repair_events']=[copy.deepcopy(event)]
    before=ledger.path.read_bytes()
    with pytest.raises(ValueError,match='DUPLICATE|REUSED|already|重复'):
        ledger.import_return(next_card,next_release,bank)
    assert ledger.path.read_bytes()==before
    assert len(ledger.replay()['repairs']['SYN-REPAIR']['actual_answers'])==1


def test_prompt_only_card_cannot_claim_specialty_started_without_actual_response(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=return_template(release)
    card['repair_events']=[{"event_id":"SYN-PROMPT-ONLY","repair_id":"SYN-REPAIR","origin_attempt_id":None,"status":"STARTED","actual_answer":None,"item_id":None,"at":None}]
    before=ledger.path.read_bytes()
    with pytest.raises(ValueError,match='REPAIR_NOT_TRAINED|actual|真实|互动'):
        ledger.import_return(card,release,bank)
    assert ledger.path.read_bytes()==before


@pytest.mark.parametrize('budget',[120,150,170,180])
def test_budget_seven_real_family_refs_and_no_planned_actual_credit(workflow,budget):
    bank,ledger,root=workflow
    plan=plan_day(bank.items(),ledger.replay(),budget)
    assert plan['planned_families']==[f'F{n}' for n in range(1,8)]
    assert len(plan['schedule'])==7 and sum(plan['minutes'].values())==budget
    assert plan['minutes']['review']>=15 and plan['minutes']['specialty']>=20
    assert plan['actual_issued_families']==plan['actual_answered_families']==[]
    assert plan['r3_allowed'] is False
    for iid in plan['schedule']:assert bank.get(iid)['release_status']=='FORMATIVE_MACHINE_CHECKED'


@pytest.mark.parametrize('budget',[119,181,-1,True,170.5])
def test_invalid_budgets_fail_closed(workflow,budget):
    bank,ledger,root=workflow
    with pytest.raises(ValueError):plan_day(bank.items(),ledger.replay(),budget)


def test_missing_family_pool_is_explicit_and_never_uses_bridge_as_mainline(workflow):
    bank,ledger,root=workflow
    items=[i for i in bank.items() if i['families']!=['F7'] or 'BRIDGE' in i['id']]
    plan=plan_day(items,ledger.replay())
    assert plan['missing_families']==['F7']
    assert all('BRIDGE' not in iid for iid in plan['schedule'])
    assert any('INSUFFICIENT_VERIFIED_ITEMS' in row for row in plan['warnings'])


def test_fast_abandon_or_pending_never_upgrades_r3(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    attempts=card['attempts']
    assert expansion_decision(attempts,60)['action']=='MORE_R2_TRANSFER'
    assert expansion_decision(attempts,60,True,True)['action']=='OPTIONAL_R3_TRANSFER'
    attempts[0]['completion']='ABANDONED';attempts[0]['abandon_reason']='SYNTHETIC early stop'
    assert expansion_decision(attempts,120,True,True)['action']=='REPAIR_OR_REVIEW'
    attempts[0]['completion']='COMPLETE';attempts[0]['abandon_reason']=None
    attempts[0]['grade'].update(status='PENDING_HUMAN_REVIEW',score=None)
    assert expansion_decision(attempts,120,True,True)['action']=='REPAIR_OR_REVIEW'


def test_hinted_full_answer_does_not_trigger_harder_independent_transfer(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);attempts=card_for(release,bank,False)['attempts']
    attempts[0]['hint_level']=1
    assert expansion_decision(attempts,60,True,True)['action']=='REPAIR_OR_REVIEW'


def test_empty_generated_template_cannot_be_imported_as_completed_training(workflow):
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);before=ledger.path.read_bytes()
    with pytest.raises(ValueError,match='EMPTY_RETURN_NOT_LEARNING_EVIDENCE'):
        ledger.import_return(return_template(release),release,bank)
    assert ledger.path.read_bytes()==before


def test_mutated_artifact_fails_release_integrity(workflow):
    bank,ledger,root=workflow
    folder,_=build_one(bank,ledger,root)
    path=folder/'student/problems/ITEM_001.md';path.write_text('SYNTHETIC mutation',encoding='utf-8')
    assert verify_daily(folder)['status']=='FAIL'


def test_json_return_cannot_invent_an_unattached_photo(tmp_path):
    from math2_pack.__main__ import read_return
    card={"attempts":[{"first_answer":{"assets":[{"path":"photos/SYN-missing.png","sha256":sha(b'SYNTHETIC_TEST_ONLY absent evidence')}]},"supplements":[]}]}
    target=tmp_path/'DAILY_RETURN_SYN.json';target.write_text(json.dumps(card),encoding='utf-8')
    with pytest.raises(ValueError,match='photo|Photo|asset|Asset|附件|照片|missing|absent'):
        read_return(target)


def test_return_archive_photo_bytes_are_hash_checked(tmp_path):
    from math2_pack.__main__ import read_return
    payload=b'SYNTHETIC_TEST_ONLY evidence bytes'
    card={"attempts":[{"first_answer":{"assets":[{"path":"photos/SYN-page.png","sha256":sha(payload)}]},"supplements":[]}]}
    target=tmp_path/'synthetic-return.zip'
    with zipfile.ZipFile(target,'w') as z:
        z.writestr('DAILY_RETURN_SYN.json',json.dumps(card));z.writestr('photos/SYN-page.png',payload)
    assert read_return(target)==card
    with zipfile.ZipFile(target,'w') as z:
        z.writestr('DAILY_RETURN_SYN.json',json.dumps(card));z.writestr('photos/SYN-page.png',payload+b'mutated')
    with pytest.raises(ValueError,match='hash'):
        read_return(target)


def test_import_persists_photo_and_original_archive_after_input_is_deleted(workflow):
    from math2_pack.__main__ import read_return
    bank,ledger,root=workflow
    _,release=build_one(bank,ledger,root);card=card_for(release,bank,False)
    photo=b'SYNTHETIC_TEST_ONLY original evidence bytes; no real handwriting'
    asset_name='photos/SYN-original-page.png'
    card['attempts'][0]['first_answer']['assets']=[{'path':asset_name,'sha256':sha(photo)}]
    card['attempts'][0]['grade'].update(status='PENDING_HUMAN_REVIEW',score=None,confidence='UNKNOWN',step_scores=[])
    source=root/'original-synthetic-return.zip'
    with zipfile.ZipFile(source,'w') as z:
        z.writestr('DAILY_RETURN_SYN.json',json.dumps(card));z.writestr(asset_name,photo)
    parsed,assets,original=read_return(source,with_assets=True)
    with pytest.raises(ValueError,match='ASSET_BYTES'):
        ledger.import_return(parsed,release,bank)
    result=ledger.import_return(parsed,release,bank,assets=assets,return_source={'bytes':original,'suffix':'.zip'})
    assert result['status']=='IMPORTED_FORMATIVE_ONLY'
    source.unlink()
    evidence=ledger._events()[-1]['payload']
    stored=evidence['asset_evidence'][asset_name]
    assert (ledger.folder/stored['stored_path']).read_bytes()==photo
    archived=evidence['source_artifact']
    archive_path=ledger.folder/archived['path']
    assert sha(archive_path.read_bytes())==archived['sha256']==sha(original)
    with zipfile.ZipFile(archive_path) as z:assert z.read(asset_name)==photo
    restored=next(iter(ledger.replay()['attempts'].values()))
    assert restored['grade']['score'] is None
    assert restored['first_answer']['assets'][0]['sha256']==sha(photo)


def test_cli_help_when_cli_is_available():
    main=Path(__file__).resolve().parents[1]/'math2_pack/__main__.py'
    if not main.exists():pytest.skip('CLI is being integrated by the root agent.')
    run=subprocess.run([sys.executable,'-m','math2_pack','--help'],capture_output=True,text=True,encoding='utf-8')
    assert run.returncode==0,run.stderr
    assert 'build-daily' in run.stdout and 'import-return' in run.stdout
