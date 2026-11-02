"""Portable session decisions; ChatGPT still receives the actual student work."""
from __future__ import annotations
import copy
from .planner import expansion_decision


def advance(plan, state, command='', reported_elapsed=None):
    result=copy.deepcopy(state)
    if any(s in command for s in ('不要验证','不要额外验证','不要验算','不做专项','下一题')):
        result['extra_practice_opt_out']=True
    if '恢复专项' in command:result['extra_practice_opt_out']=False
    stopped=any(s in command for s in ('结束','停止','出报告'))
    if reported_elapsed is not None:
        if type(reported_elapsed) not in (float,int) or not 0<=reported_elapsed<=1440:
            raise ValueError('Invalid reported activity time')
        result['reported_elapsed_minutes']=reported_elapsed
        result['time_source']='USER_REPORTED'
    elapsed=result.get('reported_elapsed_minutes')
    remaining=None if elapsed is None else max(0,plan['budget_minutes']-elapsed)
    attempts=result.get('attempts',[])
    answered={a['item_id'] for a in attempts}
    left=[i for i in plan['schedule'] if i not in answered]
    if stopped:decision={'action':'END_REVIEW'}
    elif left and (remaining is None or remaining>plan['minutes']['review']):
        decision={'action':'NEXT_MAINLINE','item_id':left[0]}
    else:
        decision=expansion_decision(attempts,remaining,
            calibrated_r2=plan.get('capacity_status')=='READY_CALIBRATED',
            r3_available=bool(plan.get('categories',{}).get('optional_r3')),
            time_source=result.get('time_source','UNKNOWN'),willing_r3=result.get('willing_r3',False))
    result['decision']=decision
    result['progress']={'submitted':len(answered & set(plan['schedule'])),'planned':len(plan['schedule']),
                        'remaining_mainline':len(left),'pending_specialties':result.get('pending_specialties',[]),
                        'review_pending':not result.get('review_completed',False),
                        'nominal_remaining_minutes':remaining,'time_source':result.get('time_source','UNKNOWN'),
                        'verified_net_seconds':None,'mandatory_extra_practice':False}
    return result


def exam_report(items, state):
    """Separate objective and subjective observations; no proportional prediction."""
    lookup={i['id']:i for i in items};groups={k:[] for k in ('OBJECTIVE_80','SUBJECTIVE_70')}
    for aid,a in state.get('attempts',{}).items():
        item=lookup.get(a['item_id'],{})
        kind='OBJECTIVE_80' if item.get('format') in ('CHOICE','FILL') else 'SUBJECTIVE_70'
        grade=a.get('grade',{})
        if grade.get('score') is not None:
            groups[kind].append({'attempt_id':aid,'score':grade['score'],'maximum':grade['max_points'],
                                'hint_level':a.get('hint_level'),'net_seconds':a.get('net_seconds'),
                                'exposure':a.get('exposure_declaration')})
    return {'groups':{k:{'observations':v,'observed_score_rate':
                        sum(x['score'] for x in v)/sum(x['maximum'] for x in v) if v else None}
                       for k,v in groups.items()},
            'timed_180_minute_exam_evidence':state.get('exam_sessions',[]),
            'stable_120':'INSUFFICIENT_EXAM_EVIDENCE','predicted_150_score':None,
            'reason':'Daily formative observations do not establish unseen, zero-hint, fully timed whole-paper stability.'}
