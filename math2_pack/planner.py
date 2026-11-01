"""Offline daily selection; actual presentation and completion come only from returns."""
from __future__ import annotations

FAMILIES={'F1':'极限连续泰勒','F2':'一元微分及证明','F3':'积分及应用','F4':'微分方程','F5':'多元与二重积分','F6':'矩阵向量方程组','F7':'特征值与二次型'}

def family_ids(item):return sorted({f.split('_')[0] for f in item.get('families',[]) if f.split('_')[0] in FAMILIES})

def usable(item):
    return item.get('release_status')=='FORMATIVE_MACHINE_CHECKED' and bool(item.get('expected'))

def plan_day(items,state,budget=170):
    if type(budget) is not int or not 120<=budget<=180:raise ValueError('预算须120–180分钟，含讲解/专项/复盘')
    attempts=state.get('attempts',{})
    seen={iid for iid,row in state.get('exposures',{}).items() if row.get('state')=='CONFIRMED_SEEN'}
    weak={}
    lookup={i['id']:i for i in items}
    for a in attempts.values():
        if a.get('completion')!='COMPLETE' or a.get('grade',{}).get('first_divergence'):
            for node in lookup.get(a['item_id'],{}).get('nodes',[]):weak[node]=weak.get(node,0)+1
    pool=[i for i in items if usable(i) and i['id'] not in seen and str(i.get('difficulty',{}).get('claim','')).startswith('R2')]
    # Weak nodes influence selection without replacing the daily calculus/linear-algebra mainline.
    pool.sort(key=lambda i:(-sum(weak.get(n,0) for n in i.get('nodes',[])),i['id']))
    schedule=[];covered=set()
    for family in FAMILIES:
        if family in covered:continue
        candidate=next((i for i in pool if family in family_ids(i) and i['id'] not in schedule),None)
        if candidate:
            schedule.append(candidate['id']);covered.update(family_ids(candidate))
    missing=sorted(set(FAMILIES)-covered)
    warning=['INSUFFICIENT_VERIFIED_R2_ITEMS：仅有形成性R2候选，尚未完成真实真题难度锚定及教师全文审校。']
    if missing:warning.append('INSUFFICIENT_VERIFIED_ITEMS：缺少 '+','.join(missing)+' 未实际展示的新题候选；不把桥题当日常主线。')
    feedback=40 if budget>=150 else 30;specialty=30 if budget>=150 else 20;review=15
    due=[]
    for cid,cohort in state.get('retests',{}).items():
        if cohort.get('events'):due.append({'cohort_id':cid,'status':'FORMATIVE_SCHEDULE_REQUIRES_REVIEW','events':cohort['events']})
    retest=min(15,len(due)*5)
    minutes={'solve':budget-feedback-specialty-review-retest,'feedback':feedback,'specialty':specialty,'retest':retest,'review':review}
    if len(due)>3:warning.append('RETEST_OVERFLOW：先保留两科主线/一个主专项/日终，余下复测排队，不自动标通过。')
    return {'schedule':schedule,'planned_families':sorted(covered),'missing_families':missing,'minutes':minutes,'budget_minutes':budget,'warnings':warning,'weak_nodes':weak,'due_retests':due,'rotation_3_7':{'training_days_recorded':len({r['date'] for r in state.get('imported_returns',{}).values()}),'three_day_window':3,'seven_day_window':7},'actual_issued_families':[],'actual_answered_families':[],'r2_status':'R2_CANDIDATE_UNCALIBRATED','r3_allowed':False}

def expansion_decision(attempts,remaining_minutes,calibrated_r2=False,r3_available=False):
    if not attempts or any(a.get('completion')!='COMPLETE' or a.get('hint_level',0)>0 or a.get('grade',{}).get('status')=='PENDING_HUMAN_REVIEW' or a.get('grade',{}).get('score')!=a.get('grade',{}).get('max_points') or a.get('abandon_reason') for a in attempts):
        return {'action':'REPAIR_OR_REVIEW','reason':'未完整/待审/放弃，不因快速交卷自动升级'}
    if remaining_minutes<15:return {'action':'END_REVIEW','reason':'保留复盘预算'}
    if calibrated_r2 and r3_available and remaining_minutes>=30:return {'action':'OPTIONAL_R3_TRANSFER','reason':'完整正确且已校准、有余时的有限结构迁移'}
    return {'action':'MORE_R2_TRANSFER','reason':'先同级不同结构候选，不宣称难度已标定'}
