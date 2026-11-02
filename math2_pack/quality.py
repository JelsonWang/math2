"""Version-bound curriculum and supply checks. Labels never certify difficulty."""
from __future__ import annotations

import copy
import datetime as dt
import json
from functools import lru_cache
from collections import Counter, defaultdict
from .mathsafe import digest, item_digest, validate_math


@lru_cache(maxsize=512)
def _math_check(payload):
    try:
        validate_math(json.loads(payload))
        return True
    except Exception:
        return False


def node_fields(item):
    """Only explicit, reviewed subquestions count; legacy tags are not evidence."""
    mapping = item.get('node_fields', {})
    expected = item.get('expected', {})
    return {n: fields for n, fields in mapping.items()
            if n in item.get('nodes', []) and not n.startswith('MAP-C')
            and isinstance(fields, list) and fields and set(fields) <= set(expected)}


def answered_nodes(item, attempt):
    import json
    try:
        raw = json.loads(attempt.get('first_answer', {}).get('raw', ''))
        fields = raw.get('answers', raw) if isinstance(raw, dict) else {}
    except (ValueError, TypeError):
        fields = {}
    # A photo-only submission needs explicit subquestion evidence from review.
    fields = (set(fields) if isinstance(fields,dict) else set()) | set(attempt.get('submitted_fields', []))
    return {n for n, required in node_fields(item).items() if set(required) <= fields}


def mapping_errors(item):
    errors = []
    mapped = node_fields(item)
    if item.get('node_fields') and set(mapped) != set(item['node_fields']):
        errors.append('INVALID_SUBQUESTION_NODE_MAPPING')
    typ = item.get('model', {}).get('type')
    families={f.split('_')[0] for f in item.get('families', [])}
    for node in item.get('nodes', []):
        if node.startswith('MAP-H') and node[5:].isdigit():
            n=int(node[5:]);family='F1' if n<=6 else 'F2' if n<=15 else 'F3' if n<=27 else 'F5' if n<=36 else 'F4'
            # Some cross-family compound questions explicitly test a second family.
            if family not in families:errors.append('NODE_FAMILY_MISMATCH:'+node)
    # Whole compound nodes must not be credited for a simpler constituent skill.
    forbidden = {'integral_volume': {'MAP-H19'}, 'double_chain': {'MAP-H34'},
                 'parameter_kernel': {'MAP-L14'}}.get(typ, set())
    if typ == 'ode' and len(item['model'].get('coeffs', [])) <= 2:
        forbidden |= {'MAP-H38', 'MAP-H39', 'MAP-H40', 'MAP-H41'}
    for n in sorted(forbidden & set(item.get('nodes', []))):
        errors.append('NODE_TAG_MISMATCH:' + n)
    required = set(item.get('required_outputs', []))
    if '标准形' in item.get('problem', ''):
        required.add('standard_form')
    scored = {r.get('field') for r in item.get('rubric', [])}
    for field in sorted(required - (set(item.get('expected', {})) & scored)):
        errors.append('UNSCORED_REQUIRED_OUTPUT:' + field)
    return errors


def calibration(item):
    """Evaluate evidence requirements, with absent evidence retained as a gap."""
    proof = item.get('calibration_evidence', {})
    gaps = []
    if item_digest(item) != item.get('version_hash'):
        gaps.append('VERSION_MISMATCH')
    anchor = proof.get('anchor', {})
    if not all(anchor.get(k) for k in ('source_url', 'question_ref', 'comparison')):
        gaps.append('EXAM_ANCHOR_MISSING')
    if not _math_check(json.dumps(item,ensure_ascii=False,sort_keys=True)):
        gaps.append('INDEPENDENT_MATH_CHECK_MISSING')
    teacher = proof.get('teacher_review', {})
    if not all(teacher.get(k) for k in ('reviewer', 'source_ref', 'content_sha256')):
        gaps.append('TEACHER_REVIEW_NOT_PERFORMED')
    elif teacher['content_sha256'] != digest({k: item.get(k) for k in ('problem', 'model', 'expected', 'solution', 'rubric')}):
        gaps.append('TEACHER_REVIEW_CONTENT_MISMATCH')
    timing = proof.get('timing_observations', [])
    if not timing or not all(type(t.get('seconds')) in (int, float) and t['seconds'] > 0
                             and t.get('source_ref') and t.get('independent') is True for t in timing):
        gaps.append('ACTUAL_INDEPENDENT_TIMING_MISSING')
    if mapping_errors(item):
        gaps.append('CURRICULUM_OR_RUBRIC_QA')
    return {'eligible_r2': not gaps, 'gaps': gaps,
            'status': 'EVIDENCE_CALIBRATED_R2' if not gaps else 'FORMATIVE_UNCALIBRATED'}


def semantic_key(item):
    # Coefficient variants share a structure; identical models cannot gain novelty
    # by changing IDs or structure labels. Pairwise grouping uses both keys below.
    return item.get('semantic_group') or item.get('structure_id') or digest(item.get('model', item.get('problem')))


def duplicate_groups(items):
    groups = defaultdict(list)
    for item in items:
        groups['structure:' + semantic_key(item)].append(item['id'])
        if item.get('model'):
            groups['model:' + digest(item['model'])].append(item['id'])
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def supply_report(items, state, date, budget=170):
    from .planner import plan_day
    trial = copy.deepcopy(state)
    plans = []
    for offset in range(7):
        day = (dt.date.fromisoformat(date) + dt.timedelta(days=offset)).isoformat()
        plan = plan_day(items, trial, budget, day)
        plans.append({'date': day, 'schedule': plan['schedule'], 'units': plan['units'],
                      'status': plan['capacity_status'], 'gaps': plan['capacity_gaps'],
                      'budget_ledger': plan['budget_ledger']})
        for iid in plan['schedule']:
            trial.setdefault('exposures', {})[iid] = {'state': 'CONFIRMED_SEEN', 'source': 'SIMULATION_ONLY'}
    nodes = sorted(n for n in state.get('nodes', {}) if n.startswith(('MAP-H', 'MAP-L')))
    lookup = {i['id']: i for i in items}
    matrix = {n: [any(n in node_fields(lookup[i]) for i in p['schedule']) for p in plans] for n in nodes}
    qualified = [i for i in items if i.get('release_status') == 'FORMATIVE_MACHINE_CHECKED']
    return {'status': 'FORECAST_ONLY_NOT_TRAINING', 'seven_day_supply':
            'READY' if all(p['status'] == 'READY_CALIBRATED' for p in plans) else 'INSUFFICIENT_VERIFIED_ITEMS',
            'inventory': dict(Counter(i.get('release_status') for i in items)),
            'eligible_r2': sum(calibration(i)['eligible_r2'] for i in qualified),
            'required_week_slots': {'short_7_families':49,'long_chain_minimum':14,'cold_probe':7},
            'allocated_week_slots':dict(Counter(u['category'] for p in plans for u in p['units'])),
            'plans': plans, 'subject_node_matrix': matrix, 'subject_node_count': len(nodes),
            'uncovered_subject_nodes': [n for n, v in matrix.items() if not any(v)],
            'node_mapping_review': [{'id': i['id'], 'version': i.get('version_hash'),
                                    'tags': i.get('nodes', []), 'verified_subquestions': node_fields(i),
                                    'issues': mapping_errors(i)} for i in qualified],
            'difficulty_anchors': [{'id': i['id'], 'evidence': i.get('calibration_evidence', {}),
                                    **calibration(i)} for i in qualified],
            'duplicate_groups': duplicate_groups(qualified),
            'cross_module_rules': {
                'MAP-C01': 'actual condition/target translation in submitted work',
                'MAP-C02': 'actual independent method choice before feedback',
                'MAP-C03': 'first-answer symbols and boundary evidence',
                'MAP-C04': 'submitted intermediate and final forms',
                'MAP-C05': 'dated timer logs, pauses, actual 90/180 minute completion',
                'MAP-C06': 'exposure, hints, structure novelty and dated delayed submissions',
                'MAP-C07': 'objective item scores and individual timer evidence',
                'MAP-C08': 'subjective rubric, written process and missing final outputs'},
            'certified_h0': False, 'stable_120_claim': False}
