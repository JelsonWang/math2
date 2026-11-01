"""Build a PRIVATE local handoff, never a public GitHub release upload."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FOLDERS=('math2_pack','schemas','prompts','tests_file','scripts_file','verified_bank','records/private','releases','DAILY_DEMO_001','SPECIALTY_DEMO','RETURN_CARD_EXAMPLE','FILE_WORKFLOW_DEMO_001','evidence/file_workflow','vendor/file_wheels','legacy_webapp','inputs/package_0','historical_evidence','.github')
FILES=('README.md','README_开始使用.md','AGENTS.md','pyproject.toml','requirements-file-workflow.txt','requirements-file-workflow.lock','MIGRATION_NOTES.md','PRIVACY_AND_GITHUB.md','CHATGPT_RUN_PROTOCOL.md','RUN_TODAY_IN_CHATGPT.md','LICENSE','.gitignore')

def package(output):
    files=[]
    for name in FOLDERS:
        folder=ROOT/name
        if folder.exists():files.extend(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.lock' and not p.name.startswith('FAILED_'))
    files.extend(ROOT/name for name in FILES if (ROOT/name).is_file())
    files=sorted(set(files));output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    manifest={'visibility':'PRIVATE_LOCAL_HANDOFF_DO_NOT_UPLOAD_TO_PUBLIC_GITHUB','files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
        z.writestr('PRIVATE_RELEASE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        assert not any(n.startswith('.git/') or n.startswith('.venv/') for n in z.namelist())
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n','utf-8')
    result={'archive':str(output),'sha256':digest,'bytes':output.stat().st_size,'files':len(files)+1,'private_local_handoff':True}
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(ROOT/'dist/MATH2_120_CHATGPT_FILE_WORKFLOW_RELEASE.zip'));args=p.parse_args();package(args.output)
