"""Check the exact staged tree before uploading only generic public code."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ALLOWED_DIRS={'math2_pack','schemas','prompts','tests_file','scripts_file','.github','verified_bank'}
ALLOWED_FILES={'AGENTS.md','README.md','README_开始使用.md','MIGRATION_NOTES.md','PRIVACY_AND_GITHUB.md','CHATGPT_RUN_PROTOCOL.md','pyproject.toml','requirements-file-workflow.txt','requirements-file-workflow.lock','LICENSE','.gitignore'}

def main():
    names=subprocess.check_output(['git','diff','--cached','--name-only','-z'],cwd=ROOT).decode('utf-8').split('\0')
    names=[n for n in names if n];errors=[]
    if not names:errors.append('No staged files')
    for name in names:
        p=Path(name)
        if p.parts[0] not in ALLOWED_DIRS and name not in ALLOWED_FILES:errors.append('Not in public allowlist:'+name)
        if p.parts[0]=='verified_bank' and (len(p.parts)!=2 or p.name!='README.md'):errors.append('Private bank material:'+name)
        if p.suffix in ('.zip','.png','.jpg','.jpeg','.sqlite3','.db','.jsonl') or p.name.startswith('private_'):errors.append('Sensitive artifact type:'+name)
        raw=subprocess.check_output(['git','show',':'+name],cwd=ROOT)
        text=raw.decode('utf-8-sig')
        # Literal credential formats; do not print any candidate secret.
        if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})',text):errors.append('Potential credential:'+name)
        if re.search(r'[A-Za-z]:\\Users\\\w+\\|/Users/\w+/',text):errors.append('Personal absolute path:'+name)
    result={'status':'PASS' if not errors else 'FAIL','staged_files':len(names),'files':names,'errors':errors,'policy':'GENERIC_CODE_SCHEMA_PROMPTS_SYNTHETIC_TESTS_ONLY'}
    out=ROOT/'evidence/file_workflow/public_commit_audit.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'status':result['status'],'staged_files':len(names),'errors':errors},ensure_ascii=False,indent=2))
    raise SystemExit(0 if not errors else 1)

if __name__=='__main__':main()
