"""Build files for ChatGPT web. No UI, server, online grader or network call."""
from __future__ import annotations
from pathlib import Path
import datetime as dt
import json
import re
import zipfile
from .util import ROOT,canonical,sha,load_json,write_json,atomic_write,client_date
from .planner import plan_day,family_ids,usable

def jsonl(path,rows):atomic_write(path,''.join(canonical(r)+'\n' for r in rows))

def zip_folder(folder,target):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(folder).rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(folder).as_posix())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip():raise ValueError('Generated ZIP failed CRC')

def return_template(release):
    return {'version':'1.0','record_kind':release['record_kind'],'release_id':release['release_id'],'date':release['date'],'source_state_hash':release['source_state_hash'],
            'presented_items':[],'attempts':[],'repair_events':[],'retest_events':[],
            'time_summary':{'activity_window_seconds':None,'verified_net_seconds':None,'feedback_seconds':None,'specialty_seconds':None,'review_seconds':None},
            'review':{'summary':'空结转模板：尚未训练；必须根据真实对话填写，禁止直接作为已训练记录导入。','unresolved':[],'next_actions':[]},
            'declarations':{'teacher_signatures':False,'official_exam_score':None,'certified_h0':False,'certified_m4':False}}

def _eligibility(state,item,mode):
    known=state.get('exposures',{}).get(item['id'],{}).get('state')
    if known=='CONFIRMED_SEEN':return 'CONFIRMED_SEEN'
    # User possession/upload of both archives cannot provide server-grade secrecy.
    return 'UNKNOWN_POSSIBLY_EXPOSED'

def _verify_no_unsupported_paths(folder):
    for p in folder.rglob('*'):
        if p.is_symlink():raise ValueError('No symlink allowed in a release')

def build_daily(bank,ledger,date=None,output=None,budget=170,mode='COACH_BUNDLE_LIMITED',allow_unreturned=False):
    from .protocol import render_run_prompt,coach_protocol,student_start
    date=date or client_date();dt.date.fromisoformat(date)
    if mode not in ('COACH_BUNDLE_LIMITED','ACTIVE_ITEM_STRICT'):raise ValueError('Unknown exposure mode')
    qa=bank.validate()
    if qa['status']!='PASS':raise ValueError('Bank exact-version QA failed: '+str(qa.get('errors')))
    state=ledger.replay()
    previous=[]
    # Same-day releases are alternatives. Only an actual imported return counts
    # as training evidence; unused versions must neither block the next day nor
    # be recorded as having been practised.
    returned_dates={row['date'] for row in state.get('imported_returns',{}).values()}
    for file in (ledger.folder/'releases').glob('*.json'):
        row=load_json(file)
        if row.get('date','')<date and row.get('date') not in returned_dates:previous.append(row['release_id'])
    if previous and not allow_unreturned:raise ValueError('MISSING_PREVIOUS_RETURN：此前训练包尚无真实结转；导入后再生成，或显式--allow-unreturned生成未更新基线。')
    plan=plan_day(bank.items(),state,budget,date=date)
    base=Path(output or ROOT/'releases')
    if output and not base.exists():
        folder=base
        version=1
    else:
        base.mkdir(parents=True,exist_ok=True);version=1
        while (base/f"DAILY_{date.replace('-','')}_v{version}").exists():version+=1
        folder=base/f"DAILY_{date.replace('-','')}_v{version}"
    folder.mkdir(parents=True,exist_ok=False)
    rid=f"DAILY_{date.replace('-','')}_v{version}"
    while (ledger.folder/'releases'/f'{rid}.json').exists():
        version+=1;rid=f"DAILY_{date.replace('-','')}_v{version}"
    main=[bank.get(i) for i in plan['schedule']]
    # Teaching reserves are explicit local candidates, not automatically certified new tests.
    all_items=bank.items();superseded={i.get('supersedes') for i in all_items}
    reserves=[i for i in all_items if usable(i) and i['id'] not in plan['schedule']
              and i['id'] not in superseded and _eligibility(state,i,mode)!='CONFIRMED_SEEN'
              and state.get('exposures',{}).get(i.get('supersedes'),{}).get('state')!='CONFIRMED_SEEN'][:4]
    selected=main+reserves
    release={'version':'1.0','release_id':rid,'date':date,'record_kind':state['record_kind'],'source_state_hash':state['source_state_hash'],'bank_hash':bank.hash,'mode':mode,'budget_minutes':budget,'minutes':plan['minutes'],'schedule':plan['schedule'],'units':plan['units'],'categories':plan['categories'],'budget_ledger':plan['budget_ledger'],'capacity_status':plan['capacity_status'],
             'item_refs':[{'item_id':i['id'],'item_version':i['version_hash'],'role':'MAINLINE' if i in main else 'BRIDGE' if 'BRIDGE' in i['id'] else 'TRANSFER','families':family_ids(i),'nodes':i.get('nodes',[]),'max_points':i['max_points'],'exposure_eligibility':_eligibility(state,i,mode)} for i in selected],
             'student_zip':f'STUDENT_{rid}.zip','coach_zip':f'COACH_{rid}.zip','active_item_id':main[0]['id'] if main else None,'warnings':plan['warnings'],'adaptation_status':'PARTIAL_REPORT_EXPOSURE_ONLY' if state.get('reported_sessions') and not state.get('attempts') else 'BASELINE_NO_NEW_RETURN' if previous else 'FROM_ACTUAL_IMPORTED_STATE',
             'certification':'FORMATIVE_ONLY_NO_INSTRUCTOR_SIGNATURE_OR_H0_M4'}
    student=folder/'student';coach=folder/'coach';student.mkdir();coach.mkdir()
    public=[{'public_id':f'ITEM_{n:03d}','order':n,'max_points':i['max_points'],'problem':i['problem']} for n,i in enumerate(main,1)]
    if mode=='ACTIVE_ITEM_STRICT':public=public[:1]
    for row in public:
        atomic_write(student/'problems'/f"{row['public_id']}.md",f"# 第{row['order']}题（{row['max_points']}分）\n\n{row['problem']}\n\n按题意提交过程与终式；无需强制追加验算练习。\n")
    jsonl(student/'problems_student.jsonl',public)
    write_json(student/'daily_plan_public.json',{'release_id':rid,'date':date,'budget_minutes':budget,'minutes':plan['minutes'],'planned_problem_count':len(public),'coverage_goal':'高数与线代综合，七族均须实际展示/作答才计实绩','actual_answered':0,'capacity_status':plan['capacity_status'],'budget_ledger':plan['budget_ledger'],'difficulty_status':plan['r2_status'],'exposure_mode':mode,'warnings':plan['warnings']})
    atomic_write(student/'CHATGPT_STUDENT_START.md',student_start())
    atomic_write(student/'README_今天怎么练.md','打开ChatGPT网页版新聊天，上传当天学生ZIP与教练ZIP，粘贴RUN_TODAY_IN_CHATGPT.md。全程在聊天里作答、拍照和接受讲解，无需安装或打开其他练习软件。\n\n学生ZIP含候选题，教练ZIP含答案；用户可查看文件，因此本模式只能采用可能曝光的形成性记录。请不要提前浏览未来题与答案；这不是密码隔离。ACTIVE_ITEM_STRICT时只上传ACTIVE_COACH包而不上传整套教练包，后续须取得下一题文件。\n')
    teacher_items=[{'item_id':i['id'],'item_version':i['version_hash'],'public_id':next((p['public_id'] for p in public if p['order']<=len(main) and main[p['order']-1]['id']==i['id']),None),'problem':i['problem'],'max_points':i['max_points'],'nodes':i.get('nodes',[]),'families':family_ids(i),'difficulty':i.get('difficulty'),'release_status':i['release_status'],'structure_id':i.get('structure_id'),'role':next(r['role'] for r in release['item_refs'] if r['item_id']==i['id'])} for i in selected]
    jsonl(coach/'teacher_items.jsonl',teacher_items)
    jsonl(coach/'solutions_and_rubrics.jsonl',[{'item_id':i['id'],'item_version':i['version_hash'],'solution':i['solution'],'expected':i['expected'],'rubric':i.get('rubric'),'eligibility':'FORMATIVE_ONLY'} for i in selected])
    jsonl(coach/'hint_ladders.jsonl',[{'item_id':i['id'],'levels':i.get('hints',[])} for i in selected])
    jsonl(coach/'independent_transfer_candidates.jsonl',[{'item_id':i['id'],'item_version':i['version_hash'],'structure_id':i.get('structure_id'),'exposure':_eligibility(state,i,mode),'h0_eligible':False,'independence':'CANDIDATE_REQUIRES_EXPOSURE_AND_STRUCTURE_REVIEW'} for i in reserves if 'BRIDGE' not in i['id'] and _eligibility(state,i,mode)!='CONFIRMED_SEEN'])
    write_json(coach/'error_branching_and_specialty_rules.json',{'states':['PLANNED','STARTED','IN_PROGRESS','ATTEMPTED','FORMATIVE_PASSED','DELAYED_PENDING'],'micro_repair':'仅建议第一错的可选修复；用户下一题时立即继续，未做不得计通过。','deep_specialty':'入口/对象/条件断点：原理→最小反例→学生局部回答→完整新题候选→反馈。','one_primary_specialty_at_a_time':True,'lesson_blueprints':bank.specialties(),'state_change_requires_actual_response':True,'current_private_repair_backlog':state.get('repairs',{}),'never_grant_h0_or_m4':True})
    write_json(coach/'exposure_preconditions.json',{'mode':mode,'items':{r['item_id']:r['exposure_eligibility'] for r in release['item_refs']},'seen_history':state['exposures'],'physical_secrecy':False,'required_rule':'显示题面或答案即登记曝光；未知不视作未见；同族换数字不充当独立新结构验收。'})
    write_json(coach/'private_history_context.json',{'historical_summary':state['history_summary'],'nodes':state['nodes'],'pending_repairs':state['repairs'],'due_retest_candidates':plan['due_retests'],'no_synthetic_attempts':state['record_kind']=='REAL','secondary_reported_sessions':state.get('reported_sessions',{}),'secondary_reports_are_not_first_answers':True})
    write_json(coach/'release_context.json',release)
    atomic_write(coach/'CHATGPT_COACH_PROTOCOL.md',coach_protocol())
    from .returns import load_schema
    schema_text=json.dumps(load_schema(),ensure_ascii=False,indent=2)
    atomic_write(coach/'return_card_schema.json',schema_text)
    write_json(coach/'DAILY_RETURN_TEMPLATE.json',return_template(release))
    write_json(coach/'QA_AND_ELIGIBILITY_REPORT.json',{'bank_validation':qa,'plan':plan,'h0_certified':False,'m4_certified':False,'teacher_review':'NOT_PERFORMED','source_state_hash':state['source_state_hash']})
    write_json(coach/'RELEASE_MANIFEST.json',{'release':release,'scope':'INNER_COACH_CONTENT_CONTEXT; outer archive has full file hashes','files':[{'path':p.relative_to(coach).as_posix(),'sha256':sha(p.read_bytes())} for p in sorted(coach.rglob('*')) if p.is_file()]})
    atomic_write(folder/'RUN_TODAY_IN_CHATGPT.md',render_run_prompt(release))
    if public:
        atomic_write(folder/'ACTIVE_ITEM_001.md',(student/'problems/ITEM_001.md').read_text('utf-8'))
        active=folder/'active_coach';active.mkdir()
        for name,rows in [('teacher_items.jsonl',teacher_items[:1]),('solutions_and_rubrics.jsonl',[{'item_id':main[0]['id'],'item_version':main[0]['version_hash'],'solution':main[0]['solution'],'expected':main[0]['expected'],'rubric':main[0].get('rubric')}])]:jsonl(active/name,rows)
        atomic_write(active/'CHATGPT_COACH_PROTOCOL.md',coach_protocol())
        write_json(active/'ACTIVE_LIMITS.json',{'item_id':main[0]['id'],'no_future_items_included':True,'next_item_requires_builder':True,'whole_chat_still_not_secret_from_learner':True})
        active_release=dict(release,item_refs=release['item_refs'][:1],schedule=release['schedule'][:1],units=plan['units'][:1],categories={plan['units'][0]['category']:[main[0]['id']]})
        write_json(active/'RELEASE_MANIFEST.json',{'release':active_release,'scope':'ACTIVE_ITEM_ONLY'})
        write_json(active/'DAILY_RETURN_TEMPLATE.json',return_template(release))
        atomic_write(active/'return_card_schema.json',schema_text)
        zip_folder(active,folder/'ACTIVE_COACH_001.zip')
    _verify_no_unsupported_paths(folder)
    zip_folder(student,folder/release['student_zip']);zip_folder(coach,folder/release['coach_zip'])
    write_json(folder/'BUILD_CONTEXT_PRIVATE.json',release)
    write_json(folder/'QA_AND_ELIGIBILITY_REPORT.json',{'bank_validation':qa,'plan':plan,'record_kind':state['record_kind'],'h0_certified':False,'m4_certified':False,'mathematical_teaching_execution':'NOT_EXECUTED_BY_BUILD; user training will occur in ChatGPT','teacher_review':'NOT_PERFORMED','source_state_hash':state['source_state_hash']})
    files=[p for p in folder.rglob('*') if p.is_file()]
    manifest={'release':release,'files':[{'path':p.relative_to(folder).as_posix(),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(files)]}
    write_json(folder/'RELEASE_MANIFEST.json',manifest)
    ledger.register_release(release)
    return {'release_id':rid,'folder':str(folder.resolve()),'student_zip':str((folder/release['student_zip']).resolve()),'coach_zip':str((folder/release['coach_zip']).resolve()),'prompt':str((folder/'RUN_TODAY_IN_CHATGPT.md').resolve()),'source_state_hash':state['source_state_hash'],'warnings':plan['warnings']}

def build_specialty(bank,ledger,topic,output):
    from .protocol import coach_protocol
    if topic not in bank.specialties():raise ValueError('Unknown specialty')
    qa=bank.validate()
    if qa['status']!='PASS':raise ValueError('Bank QA failed')
    folder=Path(output);folder.mkdir(parents=True,exist_ok=False)
    blueprint=bank.specialties()[topic]
    write_json(folder/'SPECIALTY_PLAN_PRIVATE.json',{'topic':topic,'status':'PLANNED','actual_training_events':[],'D0':None,'blueprint':blueprint,'evidence_rule':'构建不改变学情；必须学生真实回答后通过结转导入。'})
    atomic_write(folder/'CHATGPT_SPECIALTY_RUN.md',coach_protocol()+'\n\n现在按SPECIALTY_PLAN_PRIVATE.json只开展'+topic+'一项；先给原理与当前互动题，等学生作答再推进；不要预先泄露完整迁移题解或把本文件生成计为训练。\n')
    refs={s.get('item_id') for s in blueprint.get('steps',[]) if s.get('item_id')}
    jsonl(folder/'specialty_items_private.jsonl',[bank.get(i) for i in refs])
    zip_folder(folder,folder.parent/f'SPECIALTY_{topic}.zip')
    return {'topic':topic,'folder':str(folder.resolve()),'zip':str((folder.parent/f'SPECIALTY_{topic}.zip').resolve()),'status':'PLANNED_NOT_TRAINED'}

def verify_daily(folder):
    folder=Path(folder);manifest=load_json(folder/'RELEASE_MANIFEST.json');errors=[]
    for row in manifest['files']:
        path=(folder/row['path']).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or sha(path.read_bytes())!=row['sha256']:errors.append('MISSING_OR_CHANGED:'+row['path'])
    for kind in ('student_zip','coach_zip'):
        path=folder/manifest['release'][kind]
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():errors.append('ZIP_CRC:'+kind)
                if kind=='student_zip':
                    banned=('solutions_and_rubrics','teacher_items','hint_ladders','expected','rubric','private_history')
                    if any(any(b in n for b in banned) for n in archive.namelist()):errors.append('TEACHER_FILE_IN_STUDENT_ZIP')
        except (OSError,zipfile.BadZipFile):errors.append('INVALID_ZIP:'+kind)
    return {'status':'PASS' if not errors else 'FAIL','files_checked':len(manifest['files']),'release_id':manifest['release']['release_id'],'errors':errors,'secrecy':'ChatGPT uploaded archives are user-viewable; no absolute isolation claim'}
