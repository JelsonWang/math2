"""Verify exact delivered ZIP in a fresh directory and environment, with no server."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

def run(archive,output):
    archive=Path(archive).resolve();output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    logs=output.parent/(output.stem+'_logs');logs.mkdir(exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='math2_CHATGPT_FILE_CLEAN_'))
    code=folder/'project';code.mkdir()
    records=[]
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>400*1024*1024:raise ValueError('Unexpected archive size')
        for name in z.namelist():
            if not (code/name).resolve().is_relative_to(code):raise ValueError('Unsafe package member')
        if z.testzip():raise ValueError('CRC failure')
        z.extractall(code)
    manifest=json.loads((code/'PRIVATE_RELEASE_MANIFEST.json').read_text('utf-8'))
    for r in manifest['files']:
        if hashlib.sha256((code/r['path']).read_bytes()).hexdigest()!=r['sha256']:raise ValueError('File mismatch:'+r['path'])
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8');env.pop('PYTHONPATH',None)
    def execute(name,argv,cwd=code):
        r=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        for stream in ('stdout','stderr'):(logs/(name+'.'+stream+'.log')).write_text(getattr(r,stream),'utf-8')
        records.append({'name':name,'argv':[str(x) for x in argv],'cwd':str(cwd),'exit_code':r.returncode,'stdout':str(logs/(name+'.stdout.log')),'stderr':str(logs/(name+'.stderr.log'))})
        print(name+' exit '+str(r.returncode),flush=True)
        if r.returncode:raise RuntimeError(name+' failed; see logs')
    result={'status':'FAIL','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'archive':str(archive),'new_directory':str(code),'fresh_venv':False,'manifest_files_verified':len(manifest['files']),'commands':records,'no_server_required':True,'real_learner_history_touched':False,'started_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        execute('venv',[sys.executable,'-m','venv',code/'.venv'])
        py=code/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python');result['fresh_venv']=True
        install=[py,'-m','pip','install','-r','requirements-file-workflow.lock']
        if os.name=='nt':install+=['--no-index','--find-links','vendor/file_wheels']
        execute('locked_offline_dependencies',install)
        execute('install_project',[py,'-m','pip','install','--no-build-isolation','--no-deps','.'])
        execute('installed_resources_outside_checkout',[py,'-c',"from math2_pack.returns import load_schema; from math2_pack.protocol import coach_protocol; assert load_schema()['additionalProperties'] is False; assert len(coach_protocol())>1000; print('Installed schema and prompts loaded without checkout cwd')"],cwd=folder)
        execute('validate_bank',[py,'-m','math2_pack','validate'])
        execute('all_tests',[py,'-m','pytest','-q','--junitxml='+str(logs/'clean-tests.xml')])
        execute('isolated_end_to_end',[py,'-m','math2_pack.demo','--output',str(folder/'FRESH_SYNTHETIC_ROUNDTRIP')])
        execute('installed_end_to_end_outside_checkout',[py,'-m','math2_pack.demo','--bank',str(code/'verified_bank/private_catalog.json'),'--output',str(folder/'INSTALLED_SYNTHETIC_ROUNDTRIP')],cwd=folder)
        demo=json.loads((folder/'FRESH_SYNTHETIC_ROUNDTRIP/DEMO_EXECUTION_REPORT.json').read_text('utf-8'))
        result['roundtrip']=demo;result['status']='PASS'
    except Exception as exc:result['error']=str(exc)
    result['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'status':result['status'],'archive_sha256':result['archive_sha256'],'evidence':str(output)},ensure_ascii=False))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    result=run(args.archive,args.output);raise SystemExit(0 if result['status']=='PASS' else 1)
