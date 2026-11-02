from __future__ import annotations
from pathlib import Path
import argparse
import json
import sys
import zipfile
from .util import ROOT,canonical,sha,load_json,write_json,client_date
from .bank import Bank
from .ledger import Ledger
from .build import build_daily,build_specialty,verify_daily
from .planner import plan_day

def read_return(path,with_assets=False):
    path=Path(path)
    if path.stat().st_size>40*1024*1024:raise ValueError('Return file exceeds40MB')
    def attachments(card,read):
        assets={}
        for attempt in card.get('attempts',[]):
            for answer in [attempt.get('first_answer',{})]+attempt.get('supplements',[]):
                for asset in answer.get('assets',[]):
                    name=asset['path']
                    if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name or '\\' in name:raise ValueError('Unsafe photo path')
                    payload=read(name)
                    if len(payload)>20*1024*1024 or sha(payload)!=asset['sha256']:raise ValueError('Photo size/hash mismatch')
                    assets[name]=payload
        return assets
    if path.suffix.lower()!='.zip':
        card=load_json(path)
        def read_local(name):
            target=(path.parent/name).resolve()
            if not target.is_relative_to(path.parent.resolve()) or not target.is_file():raise ValueError('Declared photo is SOURCE_NOT_ATTACHED; do not invent path/hash')
            return target.read_bytes()
        assets=attachments(card,read_local)
        return (card,assets,path.read_bytes()) if with_assets else card
    with zipfile.ZipFile(path) as archive:
        if sum(x.file_size for x in archive.infolist())>100*1024*1024:raise ValueError('Unpacked return exceeds100MB')
        names=archive.namelist()
        if len(names)>1000 or len(names)!=len(set(names)):raise ValueError('Too many or duplicate return ZIP entries')
        for name in names:
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:raise ValueError('Unsafe return ZIP path')
        if archive.testzip():raise ValueError('Return ZIP CRC failure')
        cards=[n for n in names if Path(n).name.startswith('DAILY_RETURN_') and n.lower().endswith('.json') and 'TEMPLATE' not in n.upper()]
        if len(cards)!=1:raise ValueError('Return ZIP must contain exactly one DAILY_RETURN_*.json')
        raw=archive.read(cards[0]).decode('utf-8-sig')
        def pairs(entries):
            out={}
            for key,value in entries:
                if key in out:raise ValueError('Duplicate return key: '+key)
                out[key]=value
            return out
        card=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+x)))
        def read_zip(name):
            if name not in names:raise ValueError('Declared photo absent from ZIP; useSOURCE_NOT_ATTACHED')
            return archive.read(name)
        assets=attachments(card,read_zip)
        return (card,assets,path.read_bytes()) if with_assets else card

def parser():
    p=argparse.ArgumentParser(description='ChatGPT网页版数学训练文件工具；无常驻服务。')
    p.add_argument('--bank',help='本地私有题库JSON（不上传公开GitHub）')
    p.add_argument('--records',default=str(ROOT/'records/private'),help='本地append-only学情目录')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init',help='导入真实来源摘要，创建空真实作答账本');init.add_argument('--synthetic',action='store_true',help='仅初始化隔离合成账本')
    valid=sub.add_parser('validate',help='验证当前题库/日包/结转，不写学习状态');valid.add_argument('--daily-folder');valid.add_argument('--return-card')
    build=sub.add_parser('build-daily',help='生成学生ZIP、教练ZIP、完整运行提示词与空结转模板')
    build.add_argument('--date',default=client_date());build.add_argument('--output');build.add_argument('--budget',type=int,default=170)
    build.add_argument('--mode',choices=['COACH_BUNDLE_LIMITED','ACTIVE_ITEM_STRICT'],default='COACH_BUNDLE_LIMITED');build.add_argument('--allow-unreturned',action='store_true')
    specialty=sub.add_parser('build-specialty',help='生成可交互专项包，不记录已经训练');specialty.add_argument('--topic',required=True);specialty.add_argument('--output',required=True)
    imp=sub.add_parser('import-return',help='校验ChatGPT返回JSON/ZIP并原子导入，可直接生成下一日包');imp.add_argument('--file',required=True);imp.add_argument('--next-date');imp.add_argument('--output');imp.add_argument('--budget',type=int,default=170)
    coverage=sub.add_parser('coverage-report',help='查看真实已发/已答、67节点观察与候选供给');coverage.add_argument('--budget',type=int,default=170);coverage.add_argument('--output')
    export=sub.add_parser('export-history',help='从hash链重算并导出本地历史');export.add_argument('--output',required=True)
    verify=sub.add_parser('verify-release',help='校验发布目录或最终交付清单');verify.add_argument('--folder',required=True)
    supply=sub.add_parser('supply-report',help='七日供题与59节点预测，不改变学情')
    supply.add_argument('--date',default=client_date());supply.add_argument('--budget',type=int,default=170);supply.add_argument('--output',required=True)
    audit=sub.add_parser('import-audit',help='保存有来源的二级训练审计，绝不伪装原始答卷')
    audit.add_argument('--file',required=True);audit.add_argument('--source',required=True);audit.add_argument('--output',required=True)
    candidates=sub.add_parser('review-candidates',help='核验完整新题载荷并输出新私有bank，不覆盖当前版本')
    candidates.add_argument('--file',required=True);candidates.add_argument('--output',required=True)
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        ledger=Ledger(args.records)
        if args.command=='verify-release':result=verify_daily(args.folder)
        elif args.command=='import-audit':
            from .evidence import import_audit,export_audit
            report=load_json(args.file);source=Path(args.source).read_bytes()
            result=import_audit(ledger,report,source)
            result['export']=export_audit(report,source,args.output)
        elif args.command=='export-history':
            state=ledger.export(args.output);result={'status':'EXPORTED','ledger_events':state['ledger_events'],'attempt_count':len(state['attempts']),'path':args.output}
        else:
            bank=Bank(args.bank) if args.bank else Bank()
            if args.command=='review-candidates':
                from .candidates import review_candidates
                result=review_candidates(bank,args.file,args.output)
            elif args.command=='supply-report':
                from .quality import supply_report
                result=supply_report(bank.items(),ledger.replay(),args.date,args.budget)
                write_json(args.output,result)
            elif args.command=='init':
                state=ledger.initialize(bank,'SYNTHETIC_TEST_ONLY' if args.synthetic else 'REAL');result={'status':'INITIALIZED','record_kind':state['record_kind'],'attempt_count':len(state['attempts']),'nodes':len(state['nodes']),'state_hash':state['source_state_hash']}
            elif args.command=='validate':
                if args.daily_folder:result=verify_daily(args.daily_folder)
                elif args.return_card:
                    from .returns import validate_return
                    card=read_return(args.return_card);result=validate_return(card,ledger.release(card['release_id']),{i['id']:i for i in bank.items()},ledger.replay())
                    result=dict(result,status='PASS' if not result['errors'] else 'FAIL');result.pop('normalized',None)
                else:result=bank.validate()
            elif args.command=='build-daily':result=build_daily(bank,ledger,args.date,args.output,args.budget,args.mode,args.allow_unreturned)
            elif args.command=='build-specialty':result=build_specialty(bank,ledger,args.topic,args.output)
            elif args.command=='import-return':
                card,assets,original=read_return(args.file,with_assets=True);release=ledger.release(card['release_id'])
                if release['bank_hash']!=bank.hash:raise ValueError('Current bank differs from release; restore exact reviewed version before importing')
                result=ledger.import_return(card,release,bank,assets=assets,return_source={'bytes':original,'suffix':'.zip' if Path(args.file).suffix.lower()=='.zip' else '.json'})
                if args.next_date:result['next_day']=build_daily(bank,ledger,args.next_date,args.output,args.budget)
            elif args.command=='coverage-report':
                from .session import exam_report
                state=ledger.replay();plan=plan_day(bank.items(),state,args.budget)
                issued={f for a in state['attempts'].values() for f in bank.get(a['item_id']).get('families',[])}
                result={'status':'FORMATIVE_EVIDENCE_ONLY','planned':plan,'actual_answered_families':sorted(issued),'attempt_count':len(state['attempts']),'nodes':state['nodes'],'h0_certified':False,'m4_certified':False}
                result['exam_evidence']=exam_report(bank.items(),state)
                if args.output:write_json(args.output,result)
            else:raise ValueError('Unknown command')
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 1 if result.get('status')=='FAIL' else 0
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc),'type':type(exc).__name__},ensure_ascii=False,indent=2),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
