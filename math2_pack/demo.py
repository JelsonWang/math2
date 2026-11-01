"""A labelled synthetic return roundtrip; never writes the real learner ledger."""
from pathlib import Path
import argparse
import datetime as dt
import json
from .bank import Bank
from .build import build_daily,return_template,verify_daily,jsonl,zip_folder
from .ledger import Ledger
from .util import load_json,write_json,atomic_write,sha,client_date

def run_demo(output,bank=None,date=None):
    bank=bank or Bank();date=date or client_date()
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    ledger=Ledger(root/'SYNTHETIC_TEST_ONLY_RECORDS');initial=ledger.initialize(bank,'SYNTHETIC_TEST_ONLY')
    built=build_daily(bank,ledger,date,root/'DAY_1')
    release=load_json(Path(built['folder'])/'BUILD_CONTEXT_PRIVATE.json')
    card=return_template(release)
    for n,iid in enumerate(release['schedule']):
        item=bank.get(iid)
        values={k:v['value'] for k,v in item['expected'].items()}
        score=item['max_points'];divergence=None
        if n==0:
            key=next(iter(values));values[key]='99999';score=0
            divergence={'location':key,'student':'99999','correction':str(item['expected'][key]['value']),'cause':'SYNTHETIC_TEST_ONLY 明确错误结果用于验证遇错分流，不是用户作答。'}
        aid=f'SYNTHETIC-ATTEMPT-{n+1:03d}'
        card['attempts'].append({'attempt_id':aid,'item_id':iid,'item_version':item['version_hash'],'first_answer':{'raw':json.dumps({'answers':values,'work_text':'SYNTHETIC_TEST_ONLY：软件回归模拟，无真实学生首答或照片。'},ensure_ascii=False),'assets':[],'received_at':None},'hint_level':0,'exposure_declaration':'UNKNOWN_POSSIBLY_EXPOSED','grade':{'status':'FORMATIVE_AI_PROVISIONAL','score':score,'max_points':item['max_points'],'confidence':'LOW','first_divergence':divergence,'step_scores':[{'step_id':'SYNTHETIC_RESULT_SCOPE','earned':score,'maximum':item['max_points'],'reason':'SYNTHETIC_TEST_ONLY 有限结果范围演示，不构成真实过程成绩。'}],'error_codes':['R7'] if n==0 else [],'dimensions':{'R':None,'T':None,'M':None,'C':'BREAKPOINT' if n==0 else 'PROVISIONAL_OBSERVATION','F':None}},'feedback_at':None,'net_seconds':None,'completion':'COMPLETE','abandon_reason':None,'supplements':[]})
        card['presented_items'].append({'item_id':iid,'item_version':item['version_hash'],'presented_at':None,'exposure':'CONFIRMED_SEEN'})
    if card['attempts']:
        card['repair_events'].append({'event_id':'SYNTHETIC-REPAIR-EVENT-001','repair_id':'SYNTHETIC-REPAIR-001','origin_attempt_id':card['attempts'][0]['attempt_id'],'status':'IN_PROGRESS','actual_answer':'SYNTHETIC_TEST_ONLY：模拟学生实际重写局部步骤；未通过独立新题验收。','item_id':card['attempts'][0]['item_id'],'at':None})
    card['review']={'summary':'SYNTHETIC_TEST_ONLY：七族文件闭环演示，全部时间未知；本文件不是用户学习历史。','unresolved':['第一个断点已开始修复，尚未完成新题独立验收','题库真实R2校准与受信教师审核尚缺'],'next_actions':['继续一个主专项','次日按实际曝光与错因调整综合候选题','不授H0/M4']}
    returned=root/'RETURN_CARD_EXAMPLE';returned.mkdir()
    name='DAILY_RETURN_'+date.replace('-','')+'.json';write_json(returned/name,card)
    jsonl(returned/('ATTEMPT_EVENTS_'+date.replace('-','')+'.jsonl'),card['attempts'])
    write_json(returned/('SPECIALTY_STATUS_'+date.replace('-','')+'.json'),{'record_kind':'SYNTHETIC_TEST_ONLY','events':card['repair_events'],'certified_h0':False})
    write_json(returned/'EXPOSURE_DELTA.json',{'record_kind':'SYNTHETIC_TEST_ONLY','presented_items':card['presented_items']})
    atomic_write(returned/('DAILY_REVIEW_'+date.replace('-','')+'.md'),'# SYNTHETIC_TEST_ONLY：每日复盘示例\n\n这不是用户成绩，所有模拟作答仅在本目录隔离账本。\n\n'+card['review']['summary']+'\n\n未完成：\n'+''.join('- '+s+'\n' for s in card['review']['unresolved'])+'\n逐题明细见JSONL；没有假设真实净作答时长、教师签核或陌生H0。\n')
    zip_folder(returned,root/'SYNTHETIC_RETURN_CARD_EXAMPLE.zip')
    result=ledger.import_return(card,release,bank,return_source={'bytes':(returned/name).read_bytes(),'suffix':'.json'})
    second=(dt.date.fromisoformat(date)+dt.timedelta(days=1)).isoformat()
    following=build_daily(bank,ledger,second,root/'DAY_2')
    assert verify_daily(built['folder'])['status']=='PASS'
    assert verify_daily(following['folder'])['status']=='PASS'
    rebuilt=ledger.replay()
    assert len(rebuilt['attempts'])==len(release['schedule'])
    assert rebuilt['history_summary']==initial['history_summary']
    assert all(a['net_seconds'] is None for a in rebuilt['attempts'].values())
    report={'status':'PASS','record_kind':'SYNTHETIC_TEST_ONLY','real_learner_history_touched':False,'first_day':built,'import_result':result,'next_day':following,'attempt_count':len(rebuilt['attempts']),'ledger_events':rebuilt['ledger_events'],'state_hash':rebuilt['source_state_hash'],'return_zip_sha256':sha((root/'SYNTHETIC_RETURN_CARD_EXAMPLE.zip').read_bytes()),'certified_h0':False,'certified_m4':False}
    write_json(root/'DEMO_EXECUTION_REPORT.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--bank');p.add_argument('--date',default=client_date());args=p.parse_args()
    report=run_demo(args.output,Bank(args.bank) if args.bank else Bank(),args.date)
    print(json.dumps(report,ensure_ascii=False,indent=2))
