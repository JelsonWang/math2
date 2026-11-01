"""Capture actual commands/outcomes for the active offline workflow only."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def source_snapshot():
    files=[]
    for name in ('math2_pack','schemas','prompts','tests_file','scripts_file'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.md','.json'))
    files.extend(ROOT/n for n in ('pyproject.toml','requirements-file-workflow.lock','AGENTS.md'))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

def main():
    out=ROOT/'evidence/file_workflow';out.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='math2_file_validation_'))
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    specs=[('pytest',[sys.executable,'-m','pytest','-q','--junitxml=evidence/file_workflow/tests.xml']),('private_bank_qa',[sys.executable,'-m','math2_pack','validate']),('cli_help',[sys.executable,'-m','math2_pack','--help']),('synthetic_full_roundtrip',[sys.executable,'-m','math2_pack.demo','--output',str(temp/'ROUNDTRIP')])]
    records=[]
    for name,argv in specs:
        print('Running '+name,flush=True)
        result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        for stream in ('stdout','stderr'):(out/(name+'.'+stream+'.log')).write_text(getattr(result,stream),'utf-8')
        records.append({'name':name,'argv':argv,'exit_code':result.returncode,'stdout':f'evidence/file_workflow/{name}.stdout.log','stderr':f'evidence/file_workflow/{name}.stderr.log'})
        print(name+' exit '+str(result.returncode),flush=True)
    xml=ET.parse(out/'tests.xml');cases=xml.findall('.//testcase')
    passed=[c for c in cases if c.find('failure') is None and c.find('error') is None and c.find('skipped') is None]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*') if p.is_file() and p.name!='validation_run.json'}
    report={'status':'PASS' if all(r['exit_code']==0 for r in records) and len(cases)==len(passed) and cases else 'FAIL','scope':'OFFLINE_FILE_WORKFLOW; SYNTHETIC_ROUNDTRIP_NOT_REAL_CHATGPT_LEARNING','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'commands':records,'tests':{'collected':len(cases),'passed':len(passed),'failed':len(xml.findall('.//failure'))+len(xml.findall('.//error')),'skipped':len(xml.findall('.//skipped'))},'source_sha256':source_snapshot(),'evidence_sha256':hashes,'roundtrip_report':str(temp/'ROUNDTRIP/DEMO_EXECUTION_REPORT.json'),'real_learner_attempts_written':0,'human_teacher_reviews':0,'certified_h0':False,'certified_m4':False,'r2_calibration':'INCOMPLETE','webapp':'NOT_IN_ACTIVE_WORKFLOW'}
    (out/'validation_run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:report[k] for k in ('status','tests','scope')},ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['status']=='PASS' else 1)

if __name__=='__main__':main()
