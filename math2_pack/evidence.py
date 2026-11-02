"""Secondary audit preservation; never impersonates original first answers."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from .util import canonical, sha, write_json, atomic_bytes, atomic_write, file_lock


def validate_audit(report, release, source):
    errors=[]
    text=source.decode('utf-8-sig')
    for key in ('release_id','source_state_hash'):
        if report.get(key)!=release.get(key):errors.append('RELEASE_BINDING:'+key)
    if report.get('release_date')!=release.get('date'):errors.append('RELEASE_DATE_CHANGED')
    try:
        day=dt.date.fromisoformat(report['actual_training_date'])
        if day<dt.date.fromisoformat(release['date']):errors.append('TRAINING_BEFORE_RELEASE')
    except (ValueError,KeyError,TypeError):errors.append('INVALID_TRAINING_DATE')
    if report.get('source_sha256')!=sha(source):errors.append('SOURCE_SHA256_MISMATCH')
    if report.get('record_kind')!=release.get('record_kind'):errors.append('REAL_SYNTHETIC_ISOLATION')
    refs={r['item_id']:r for r in release['item_refs']}
    entries=report.get('reported_entries',[]);ids=[r.get('item_id') for r in entries]
    if len(ids)!=len(set(ids)):errors.append('DUPLICATE_REPORTED_ITEM')
    for row in entries:
        ref=refs.get(row.get('item_id'))
        if not ref or ref['item_version']!=row.get('item_version'):errors.append('ITEM_VERSION')
        if not row.get('source_quote') or row['source_quote'] not in text:errors.append('SOURCE_QUOTE_NOT_FOUND')
        if row.get('assets')!=[] or row.get('original_answer_status')!='SOURCE_NOT_ATTACHED':errors.append('REPORT_IS_NOT_ORIGINAL_ANSWER')
        if row.get('net_seconds') is not None:errors.append('UNPROVEN_NET_TIME')
    for row in report.get('score_revisions',[]):
        if row.get('item_id') not in ids or not row.get('reason') or row.get('at') is not None:
            errors.append('INVALID_SECONDARY_REVISION')
        if not row.get('source_quote') or row['source_quote'] not in text:errors.append('REVISION_SOURCE_MISSING')
    if report.get('verified_net_seconds') is not None or report.get('certified_h0') is not False or report.get('certified_m4') is not False:
        errors.append('UNSUPPORTED_CERTIFICATION')
    timing=report.get('reported_time',{})
    if timing and (timing.get('source')!='USER_REPORTED' or not timing.get('quote') or timing['quote'] not in text):
        errors.append('TIME_SOURCE_MISSING')
    missing=sorted(set(release['schedule'])-set(ids))
    if missing:errors.append('INCOMPLETE_ATTEMPT_COVERAGE')
    return {'errors':errors,'missing_reported_items':missing,'reported_count':len(entries),
            'original_attempt_count':0,'status':'PARTIAL_STATE_ONLY',
            'warnings':['SOURCE_NOT_ATTACHED','REPORT_NOT_A_COMPLETE_DAILY_RETURN']}


def apply_audit(state, payload):
    report=payload['report'];key=payload['report_hash']
    from .ledger import Ledger
    if report['source_state_hash']==Ledger.state_hash(state):
        state.setdefault('pending_audit_release_bases',{})[report['release_id']]=report['source_state_hash']
    state.setdefault('reported_sessions',{})[key]=report
    # Full archive possession is uncertain exposure; actual presentation is seen.
    for iid in report.get('possibly_exposed_ids',[]):
        if state['exposures'].get(iid,{}).get('state')!='CONFIRMED_SEEN':
            state['exposures'][iid]={'state':'UNKNOWN_POSSIBLY_EXPOSED','source':'SECONDARY_AUDIT','at':None}
    for row in report['reported_entries']:
        state['exposures'][row['item_id']]={'state':'CONFIRMED_SEEN','item_version':row['item_version'],
                                          'source':'SECONDARY_AUDIT_REPORTED_PRESENTATION','at':None}
    state.setdefault('score_revisions',[]).extend(report.get('score_revisions',[]))
    state.setdefault('system_incidents',[]).extend(report.get('system_incidents',[]))


def import_audit(ledger, report, source):
    release=ledger.release(report['release_id'])
    validated=validate_audit(report,release,source)
    if validated['errors']:raise ValueError(str(validated))
    key=sha(canonical(report))
    with file_lock(ledger.folder):
        state=ledger.replay()
        if state['record_kind']!=report['record_kind']:raise ValueError('REAL_SYNTHETIC_ISOLATION')
        if key in state.get('reported_sessions',{}):return dict(validated,import_status='IDEMPOTENT_ALREADY_IMPORTED')
        path='source_audits/'+sha(source)+'.md'
        atomic_bytes(ledger.folder/path,source)
        ledger._append(ledger._events(),'SECONDARY_AUDIT_IMPORTED',{'report':report,'report_hash':key,'source_path':path})
        write_json(ledger.folder/'state.json',ledger.replay())
    return dict(validated,import_status='SECONDARY_REPORT_PRESERVED',report_hash=key)


def export_audit(report,source,folder):
    from .build import zip_folder
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    write_json(folder/'REPORTED_SESSION.json',report)
    atomic_bytes(folder/'SOURCE_REVIEW.md',source)
    atomic_write(folder/'README.md','# PARTIAL_STATE_ONLY\n\n报告所述全部题目的二级证据已保存；原始答卷未附，不能冒充严格 DAILY_RETURN 或已验证学情。\n')
    for p in folder.iterdir():
        if p.suffix=='.json':
            import json
            assert json.loads(p.read_text('utf-8'))==report
    write_json(folder/'MANIFEST.json',{'files':[{'path':p.name,'sha256':sha(p.read_bytes())} for p in folder.iterdir() if p.is_file()]})
    target=folder.parent/(folder.name+'.zip');zip_folder(folder,target)
    return {'folder':str(folder.resolve()),'zip':str(target.resolve()),'sha256':sha(target.read_bytes())}
