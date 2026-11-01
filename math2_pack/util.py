from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def sha(value):
    return hashlib.sha256(value.encode('utf-8') if isinstance(value,str) else value).hexdigest()

def load_json(path):
    def pairs(values):
        output={}
        for key,value in values:
            if key in output:raise ValueError('Duplicate JSON key: '+key)
            output[key]=value
        return output
    return json.loads(Path(path).read_text('utf-8-sig'),object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+x)))

def utc_now():return dt.datetime.now(dt.timezone.utc).isoformat()
def client_date():return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()

def atomic_write(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def write_json(path,value):atomic_write(path,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def atomic_bytes(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

_locks={}
_locks_guard=threading.Lock()

@contextmanager
def file_lock(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    key=str(folder.resolve())
    with _locks_guard:
        lock=_locks.setdefault(key,threading.RLock())
    with lock:
        with (folder/'.lock').open('a+b') as stream:
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:
                stream.seek(0)
                if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream,fcntl.LOCK_UN)
