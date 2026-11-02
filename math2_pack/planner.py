"""Offline daily selection; actual presentation and completion come only from returns."""
from __future__ import annotations
import datetime as dt
from .util import client_date
from .quality import node_fields, answered_nodes, calibration, semantic_key
from .mathsafe import digest

FAMILIES={'F1':'极限连续泰勒','F2':'一元微分及证明','F3':'积分及应用','F4':'微分方程','F5':'多元与二重积分','F6':'矩阵向量方程组','F7':'特征值与二次型'}

def family_ids(item):return sorted({f.split('_')[0] for f in item.get('families',[]) if f.split('_')[0] in FAMILIES})

def usable(item):
    return item.get('release_status')=='FORMATIVE_MACHINE_CHECKED' and bool(item.get('expected'))


def _date(value):
    if not isinstance(value,str):return None
    try:return dt.date.fromisoformat(value)
    except ValueError:return None


def _received_date(attempt):
    value=attempt.get('first_answer',{}).get('received_at')
    if not isinstance(value,str):return None
    try:
        moment=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if moment.tzinfo is None:return None
        return moment.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    except ValueError:return None


def _formative_pass(attempt):
    grade=attempt.get('grade',{})
    return bool(attempt and attempt.get('completion')=='COMPLETE' and not attempt.get('hint_level',0)
                and not attempt.get('abandon_reason') and grade.get('status')=='FORMATIVE_AI_PROVISIONAL'
                and grade.get('score') is not None and grade.get('score')==grade.get('max_points')
                and attempt.get('exposure_declaration')=='UNSEEN_SELF_DECLARED')


def due_retest_candidates(items,state,date):
    """Plan only from an actual dated D0; never manufacture a pass or due date.

    A catalog flag is a content precondition, not a teacher signature. Even a
    READY_DUE row is only a candidate awaiting an actual independent submission.
    All current local formative items have h0_eligible=False and therefore cannot
    become trusted delayed-test assignments through this planner.
    """
    asof=_date(date)
    if asof is None:raise ValueError('复测日期必须是有效ISO日期')
    lookup={i['id']:i for i in items};attempts=state.get('attempts',{})
    stages=('D0','D3','D7','D14');result=[];reserved=set()
    for cid,cohort in sorted(state.get('retests',{}).items()):
        row={'cohort_id':cid,'as_of_date':asof.isoformat(),'stage':None,'d0_date':None,'due_date':None,
             'status':'D0_SOURCE_PENDING','actionable':False,'certification':'CANDIDATE_NOT_H0_OR_M4'}
        events=cohort.get('events',[]) if isinstance(cohort,dict) else []
        by_stage={};duplicate=False
        for event in events:
            stage=event.get('stage')
            if stage in by_stage:duplicate=True
            by_stage[stage]=event
        d0=by_stage.get('D0');origin=attempts.get(d0.get('attempt_id'),{}) if d0 else {}
        d0_date=_received_date(origin)
        if not d0 or d0.get('outcome')!='FORMATIVE_PASS' or d0_date is None:
            row['reason']='缺少D0形成性通过及其真实首答received_at；不从活动窗口或生成日期推算。'
            result.append(row);continue
        row['d0_date']=d0_date.isoformat()
        if duplicate or any(stage not in stages for stage in by_stage):
            row.update(status='BLOCKED_STAGE_EVIDENCE',reason='阶段重复或不受支持，必须先核对原始证据。');result.append(row);continue
        if not _formative_pass(origin) or d0_date>asof:
            row.update(status='BLOCKED_D0_EVIDENCE',reason='D0首答不满足完整、无提示、满分形成性及未见声明，或日期在未来。');result.append(row);continue
        passed=[];used_items=set();used_structures=set();last_date=None;blocked=None
        for index,stage in enumerate(stages):
            event=by_stage.get(stage)
            if event is None:
                if any(s in by_stage for s in stages[index+1:]):
                    blocked=('BLOCKED_STAGE_SEQUENCE','存在后续阶段但缺少前序阶段，不补造D3/D7。')
                break
            if event.get('outcome')=='FAIL':
                blocked=('REGRESSED_TO_SPECIALTY','本cohort已有失败，先回到专项；不能继续向M4推进。');break
            if event.get('outcome')!='FORMATIVE_PASS':
                blocked=('PENDING_STAGE_REVIEW','本阶段仍待审；不能用新安排绕过未完成的阶段。');break
            attempt=attempts.get(event.get('attempt_id'),{});day=_received_date(attempt)
            item=lookup.get(attempt.get('item_id'),{});structure=item.get('structure_id',attempt.get('item_id'))
            offset=0 if stage=='D0' else int(stage[1:])
            if (day is None or not _formative_pass(attempt) or day<d0_date+dt.timedelta(days=offset)
                    or day>asof or (last_date is not None and day<=last_date)
                    or attempt.get('item_id') in used_items or structure in used_structures):
                blocked=('BLOCKED_STAGE_EVIDENCE','阶段须真实到期、不同日期、不同题和结构，且首答确实完整无提示。');break
            passed.append(stage);used_items.add(attempt.get('item_id'));used_structures.add(structure);last_date=day
        row['completed_stages']=passed
        if blocked:
            row.update(status=blocked[0],reason=blocked[1]);result.append(row);continue
        if len(passed)==len(stages):
            row.update(status='FORMATIVE_COHORT_COMPLETE_NOT_CERTIFIED',reason='四阶段只有形成性记录；本规划器不授予H0或M4。');result.append(row);continue
        next_stage=stages[len(passed)];due=d0_date+dt.timedelta(days=int(next_stage[1:]))
        row.update(stage=next_stage,due_date=due.isoformat())
        origin_item=lookup.get(origin.get('item_id'),{})
        nodes=set(origin_item.get('nodes',[]));eligible=[];candidate_structures=set(used_structures)
        for candidate in sorted(items,key=lambda i:i['id']):
            iid=candidate['id'];structure=candidate.get('structure_id',iid)
            exposure=state.get('exposures',{}).get(iid,{})
            exposure=exposure.get('state') if isinstance(exposure,dict) else exposure
            initial=candidate.get('initial_exposure')
            released=candidate.get('release_status') in ('FORMATIVE_MACHINE_CHECKED','VERIFIED_ITEM_H0','INSTRUCTOR_VERIFIED_CONTENT')
            if (not released or not candidate.get('expected') or candidate.get('h0_eligible') is not True
                    or iid in used_items|reserved or structure in candidate_structures
                    or not nodes.intersection(candidate.get('nodes',[]))
                    or exposure in ('CONFIRMED_SEEN','UNKNOWN_POSSIBLY_EXPOSED','UNKNOWN_REQUIRES_EVIDENCE')
                    or initial not in ('CONFIRMED_UNSEEN','NEW_GENERATED_UNSEEN')):continue
            eligible.append(candidate);candidate_structures.add(structure)
        needed=len(stages)-len(passed)
        row.update(remaining_stages=needed,eligible_different_structures=len(eligible))
        if len(eligible)<needed:
            row.update(status='INSUFFICIENT_VERIFIED_ITEMS',reason='缺少足量当前版本合规、h0_eligible、真未见且不同结构的剩余阶段题；不安排受信复测。')
        elif due>asof:
            row.update(status='NOT_DUE',reason='尚未到实际D0推导的日期；不提前安排、不提前认通过。')
        else:
            row.update(status='READY_DUE',actionable=True,candidate_item_id=eligible[0]['id'],candidate_version=eligible[0]['version_hash'],reason='仅规划到期候选；实际作答、曝光与可靠批改仍需另行提供。')
            reserved.update(i['id'] for i in eligible[:needed])
        result.append(row)
    return result


def _rolling_coverage(items,state,asof):
    lookup={i['id']:i for i in items};all_nodes=set(state.get('nodes',{}))|{n for i in items for n in i.get('nodes',[])}
    imported={d for row in state.get('imported_returns',{}).values() if (d:=_date(row.get('date'))) is not None}
    observed={}
    for node in state.get('nodes',{}).values():
        for record in node.get('observations',[]):
            day=_date(record.get('date'))
            if day is not None:observed.setdefault(record.get('attempt_id'),set()).add(day)
    dated=[];unknown=[];future=[]
    for aid,attempt in state.get('attempts',{}).items():
        dates=set(observed.get(aid,set()))
        received=_received_date(attempt)
        if received is not None:dates.add(received)
        if len(dates)!=1 or not dates.intersection(imported):unknown.append(aid);continue
        day=next(iter(dates))
        if day>asof:future.append(aid);continue
        item=lookup.get(attempt.get('item_id'))
        if item is None:unknown.append(aid);continue
        dated.append((aid,day,attempt,answered_nodes(item,attempt)))
    windows={}
    for length in (3,7):
        start=asof-dt.timedelta(days=length-1);inside=[r for r in dated if start<=r[1]<=asof]
        covered=set().union(*(r[3] for r in inside)) if inside else set()
        complete=set().union(*(r[3] for r in inside if r[2].get('completion')=='COMPLETE')) if any(r[2].get('completion')=='COMPLETE' for r in inside) else set()
        windows[str(length)]={'from_date':start.isoformat(),'through_date':asof.isoformat(),'covered_nodes':sorted(covered),'uncovered_nodes':sorted(all_nodes-covered),
                              'complete_attempt_nodes':sorted(complete),'attempt_ids':[r[0] for r in inside],
                              'coverage_meaning':'已导入真实作答触达，不代表正确、精通或H0/M4；待审/未完整另保留。'}
    return {'training_days_recorded':len({r[1] for r in dated}),'three_day_window':3,'seven_day_window':7,'as_of_date':asof.isoformat(),
            'windows':windows,'unknown_or_conflicting_date_attempts':sorted(unknown),'future_date_attempts_excluded':sorted(future),'known_node_count':len(all_nodes),'mastery_claimed':False}


def plan_day(items,state,budget=170,date=None):
    if type(budget) is not int or not 120<=budget<=180:raise ValueError('预算须120–180分钟，含讲解/专项/复盘')
    date=date or client_date();asof=_date(date)
    if asof is None:raise ValueError('训练日期必须是有效ISO日期')
    attempts=state.get('attempts',{})
    seen={iid for iid,row in state.get('exposures',{}).items() if row.get('state')=='CONFIRMED_SEEN'}
    weak={}
    lookup={i['id']:i for i in items}
    for a in attempts.values():
        if a.get('completion')!='COMPLETE' or a.get('grade',{}).get('first_divergence'):
            for node in lookup.get(a['item_id'],{}).get('nodes',[]):weak[node]=weak.get(node,0)+1
    # Reports can conservatively record exposure, but never fabricate attempts.
    seen |= {i['id'] for i in items if i.get('initial_exposure') == 'CONFIRMED_SEEN'}
    seen_models={digest(i['model']) for i in items if i['id'] in seen and i.get('model')}
    pool=[i for i in items if usable(i) and i['id'] not in seen
          and i['id'] not in {j.get('supersedes') for j in items}
          and i.get('supersedes') not in seen and i.get('difficulty',{}).get('claim')!='R1_REPAIR']
    pool=[i for i in pool if not i.get('model') or digest(i['model']) not in seen_models]
    rotation=_rolling_coverage(items,state,asof)
    missing3=set(rotation['windows']['3']['uncovered_nodes']);missing7=set(rotation['windows']['7']['uncovered_nodes'])
    ever_submitted={n for a in attempts.values() for n in answered_nodes(lookup.get(a.get('item_id'),{}),a)}
    def priority(item):
        nodes=set(node_fields(item))
        return 6*sum(weak.get(n,0) for n in nodes)+2*len(nodes&missing3)+len(nodes&missing7)
    pool.sort(key=lambda i:(-priority(i),i['id']))
    qualified={i['id']:calibration(i)['eligible_r2'] for i in pool}
    schedule=[];units=[];covered=set();structures=set();models=set()
    # Budget slots remain visible if a source is missing. Missing time is not
    # silently converted into feedback or marked as delivered training.
    review=15;feedback=25 if budget>=150 else 20
    due=due_retest_candidates(items,state,date)
    ready=[row for row in due if row['actionable']]
    retest=min(15,len(ready)*5)
    solve=budget-review-feedback-retest
    short_cap=35 if budget>=150 else 28
    probe_cap=20 if budget>=150 else 15
    long_cap=solve-short_cap-probe_cap
    long_count=3 if long_cap>=60 else 2
    targets={'short_7_families':short_cap,'long_chain':long_cap,'cold_probe':probe_cap,
             'retest':retest,'optional_r3':0,'day_end_review':review,'feedback':feedback}
    def add(candidate,category,target):
        if candidate is None:return
        iid=candidate['id'];schedule.append(iid);structures.add(semantic_key(candidate))
        if candidate.get('model'):models.add(digest(candidate['model']))
        covered.update(family_ids(candidate))
        units.append({'item_id':iid,'item_version':candidate['version_hash'],'category':category,
                      'target_minutes':int(candidate.get('difficulty',{}).get('time_target',target)),'time_source':'DESIGN_ESTIMATE_NOT_OBSERVED',
                      'format':candidate.get('format','SUBJECTIVE'),
                      'difficulty_status':'EVIDENCE_CALIBRATED_R2' if qualified.get(iid) else 'FORMATIVE_UNCALIBRATED',
                      'node_fields':node_fields(candidate),'status':'PLANNED_NOT_STARTED'})
    def pick(category,family=None,unmeasured=False,max_minutes=None):
        choices=[i for i in pool if i['id'] not in schedule and semantic_key(i) not in structures
                 and (not i.get('model') or digest(i['model']) not in models)
                 and category in i.get('training_roles',['short_7_families'])
                 and (max_minutes is None or i.get('difficulty',{}).get('time_target',max_minutes)<=max_minutes)
                 and (family is None or family in family_ids(i))
                 and (not unmeasured or set(node_fields(i))-ever_submitted)]
        choices.sort(key=lambda i:(not qualified[i['id']],-priority(i),i['id']))
        return choices[0] if choices else None
    for n,family in enumerate(FAMILIES):
        add(pick('short_7_families',family,max_minutes=short_cap//7+(n<short_cap%7)),'short_7_families',short_cap//7+(n<short_cap%7))
    for n in range(long_count):
        add(pick('long_chain',max_minutes=long_cap//long_count+(n<long_cap%long_count)),'long_chain',long_cap//long_count+(n<long_cap%long_count))
    add(pick('cold_probe',unmeasured=True,max_minutes=probe_cap),'cold_probe',probe_cap)
    for row in ready[:3]:
        candidate=lookup.get(row['candidate_item_id'])
        if candidate and candidate['id'] not in schedule and candidate.get('difficulty',{}).get('time_target',5)<=5:add(candidate,'retest',5)
    missing=sorted(set(FAMILIES)-covered)
    certified_long=sum(u['category']=='long_chain' and qualified.get(u['item_id'],False) for u in units)
    gaps=[]
    if missing:gaps.append('MISSING_FAMILIES:'+','.join(missing))
    short_families={f for u in units if u['category']=='short_7_families' for f in family_ids(lookup[u['item_id']])}
    if set(FAMILIES)-short_families:gaps.append('MISSING_SHORT_FAMILY_SLOTS:'+','.join(sorted(set(FAMILIES)-short_families)))
    if certified_long<2:gaps.append('INSUFFICIENT_VERIFIED_LONG_CHAIN:need_at_least_2')
    probes=[u for u in units if u['category']=='cold_probe']
    if not probes:gaps.append('MISSING_HIGH_VALUE_COLD_PROBE')
    # Whole-bundle delivery never proves a probe was previously unseen.
    # Probe status is provisional; full archive exposure never certifies novelty.
    r2_minutes=sum(u['target_minutes'] for u in units if qualified.get(u['item_id'],False))
    if r2_minutes<0.70*solve:gaps.append('R2_TIME_SHARE_BELOW_70_PERCENT')
    ledger=[]
    for category,target in targets.items():
        delivered=sum(u['target_minutes'] for u in units if u['category']==category)
        if category in ('feedback','day_end_review'):delivered=target
        ledger.append({'category':category,'budget_minutes':target,'sourced_minutes':delivered,
                       'unfilled_minutes':target-delivered,'actual_minutes':None})
    warning=list(gaps)
    if sum(row['sourced_minutes'] for row in ledger)<120:
        gaps.append('SOURCED_TOTAL_BELOW_120');warning.append('SOURCED_TOTAL_BELOW_120')
    if not all(qualified.values()) or not pool:warning.append('INSUFFICIENT_VERIFIED_R2_ITEMS:未校准题只供形成性教学，不能冒称真题级。')
    if any(r['unfilled_minutes'] for r in ledger):warning.append('INSUFFICIENT_VERIFIED_ITEMS:预算槽位没有足量合格题源，允许提前结束并记录缺口。')
    if len(ready)>3:warning.append('RETEST_OVERFLOW:到期任务排队，不挤占全部主线。')
    warning.extend(row['status'] for row in due if row['status'] in ('D0_SOURCE_PENDING','INSUFFICIENT_VERIFIED_ITEMS'))
    minutes={'solve':solve,'feedback':feedback,'specialty':0,'retest':retest,'review':review}
    return {'schedule':schedule,'units':units,'categories':{k:[u['item_id'] for u in units if u['category']==k] for k in targets},
            'planned_families':sorted(covered),'missing_families':missing,'minutes':minutes,'budget_minutes':budget,
            'budget_ledger':ledger,'capacity_status':'DEGRADED_FORMATIVE_ONLY' if gaps else 'READY_CALIBRATED',
            'capacity_gaps':gaps,'r2_solve_share':r2_minutes/solve if solve else 0,
            'warnings':warning,'weak_nodes':weak,'due_retests':due,'ready_due_retests':ready,'rotation_3_7':rotation,
            'selection_priority':{iid:priority(lookup[iid]) for iid in schedule},'actual_issued_families':[],
            'actual_answered_families':[],'r2_status':'R2_CANDIDATE_UNCALIBRATED' if gaps else 'EVIDENCE_CALIBRATED_R2','r3_allowed':False}


def expansion_decision(attempts,remaining_minutes,calibrated_r2=False,r3_available=False, user_stopped=False, time_source="UNKNOWN", willing_r3=False):
    if user_stopped:return {"action":"END_REVIEW","reason":"用户结束，不强制补足预算"}
    if remaining_minutes is None:return {"action":"ASK_AVAILABLE_TIME_OR_REVIEW","reason":"时间未知，不推造余量"}
    if remaining_minutes<15:return {'action':'END_REVIEW','reason':'保留复盘预算'}
    if not attempts or any(a.get('completion')!='COMPLETE' or a.get('hint_level',0)>0 or a.get('grade',{}).get('status')=='PENDING_HUMAN_REVIEW' or a.get('grade',{}).get('score')!=a.get('grade',{}).get('max_points') or a.get('abandon_reason') for a in attempts):
        return {'action':'REPAIR_OR_REVIEW','reason':'未完整/待审/放弃，不因快速交卷自动升级'}
    if calibrated_r2 and r3_available and remaining_minutes>=30 and willing_r3 and time_source!='UNKNOWN':return {'action':'OPTIONAL_R3_TRANSFER','reason':'完整正确且已校准、有余时的有限结构迁移'}
    return {'action':'MORE_R2_TRANSFER','reason':'先同级不同结构候选，不宣称难度已标定'}
