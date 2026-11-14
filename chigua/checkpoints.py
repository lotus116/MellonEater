"""Private, exact-input checkpoints and an append-only model-attempt ledger."""
from __future__ import annotations
import hashlib
import fcntl
import os
import json
import time
import random
from pathlib import Path
from .core import write_json, now

VERSION='checkpoint-v1'


class CallFailure(RuntimeError):
    def __init__(self,message,*,kind='request',retryable=False,uncertain=False,retry_after=0):
        super().__init__(message)
        self.kind=kind;self.retryable=retryable;self.uncertain=uncertain;self.retry_after=retry_after


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def media_hashes(images,root):
    result=[]
    for name in images:
        if not isinstance(name,str) or Path(name).name!=name:
            raise ValueError('图片路径无效。')
        p=root/'uploads'/name
        if p.is_symlink() or not p.is_file():raise ValueError('图片缺失，请先修复材料；尚未调用模型。')
        result.append({'name':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return result


def run_root(folder):
    return folder.parent if folder.name=='editorial' else folder


def usage_summary(folder):
    rows=[]
    for p in folder.rglob('attempt-*/attempt.json'):
        try:
            row=json.loads(p.read_text())
            meta=p.parent/'usage.json'
            raw=json.loads(meta.read_text()) if meta.exists() else None
            row['usage']=raw if isinstance(raw,dict) else None
            rows.append(row)
        except (ValueError,OSError):continue
    def number(u,*keys):
        return next((u[k] for k in keys if isinstance(u.get(k),int)),0)
    def complete_usage(u):
        return isinstance(u,dict) and any(isinstance(u.get(k),int) for k in ['prompt_tokens','input_tokens']) and any(isinstance(u.get(k),int) for k in ['completion_tokens','output_tokens'])
    def cached(u):
        details=u.get('prompt_tokens_details') or {}
        return number(u,'prompt_cache_hit_tokens') or (number(details,'cached_tokens') if isinstance(details,dict) else 0)
    return {'requests':len(rows),'completed_requests':sum(r.get('status')=='completed' for r in rows),
        'unknown_usage_requests':sum(not complete_usage(r.get('usage')) for r in rows),
        'input_tokens':sum(number(r.get('usage') or {},'prompt_tokens','input_tokens') for r in rows),
        'output_tokens':sum(number(r.get('usage') or {},'completion_tokens','output_tokens') for r in rows),
        'cached_input_tokens':sum(cached(r.get('usage') or {}) for r in rows)}


def call(prompt,schema,folder,stage,images,config,media,execute,recover=None):
    root=run_root(Path(folder));root.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(root/'.model-call.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise CallFailure('该任务已有模型请求正在处理，请等待后继续。',kind='busy') from None
        return _call_locked(prompt,schema,folder,stage,images,config,media,execute,recover)
    finally:os.close(fd)


def _call_locked(prompt,schema,folder,stage,images,config,media,execute,recover=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=digest({'version':VERSION,'prompt':prompt,'schema':schema,'images':media,'config':config})
    cache_dir=folder/'.calls'/key;cache_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    cache=cache_dir/'completed.json'
    if cache.exists():
        try:
            saved=json.loads(cache.read_text())
            if saved['key']!=key or saved['checksum']!=digest(saved['value']):raise ValueError()
            return saved['value'],{**saved['stats'],'cached':True,'seconds':0,'checkpoint':key}
        except (KeyError,ValueError):
            raise CallFailure('阶段缓存损坏，已停止以避免重复计费。请检查本机缓存。',kind='cache') from None
    root=run_root(folder);manifest=root/'manifest.json'
    policy=json.loads(manifest.read_text()) if manifest.exists() else {}
    limit=policy.get('max_requests',20)
    attempts=sorted(cache_dir.glob('attempt-*/attempt.json'))
    # A request interrupted after dispatch might already have been billed.
    if attempts:
        last=json.loads(attempts[-1].read_text())
        if last.get('status')=='running' and recover:
            try:recovered=recover(attempts[-1].parent)
            except (ValueError,KeyError,TypeError,OSError):recovered=None
            if recovered:
                value,stats=recovered
                stats={**stats,'cached':True,'checkpoint':key}
                write_json(cache,{'key':key,'value':value,'checksum':digest(value),'stats':stats})
                write_json(attempts[-1],{**last,'status':'completed','recovered_response':True,'ended_at':now()})
                return value,stats
        if (last.get('status')=='running' or last.get('uncertain')) and not policy.get('retry_uncertain'):
            raise CallFailure('上次请求中断，当前阶段是否已计费未知。确认后可仅重试这一步。',kind='interrupted',uncertain=True)
    if policy.get('retry_uncertain'):
        policy.pop('retry_uncertain');write_json(manifest,policy)
    for retry in range(3):
        usage=usage_summary(root)
        if usage['requests']>=limit:
            raise CallFailure(f'已达到本次 {limit} 次请求上限；进度已保存，未继续调用。',kind='budget')
        attempt=cache_dir/f'attempt-{len(list(cache_dir.glob("attempt-*")))+1:04d}'
        attempt.mkdir(mode=0o700)
        record={'stage':stage,'status':'running','started_at':now(),'key':key}
        write_json(attempt/'attempt.json',record)
        try:
            value,stats=execute(attempt)
            stats={**stats,'cached':False,'checkpoint':key}
            write_json(cache,{'key':key,'value':value,'checksum':digest(value),'stats':stats})
            write_json(attempt/'attempt.json',{**record,'status':'completed','ended_at':now()})
            return value,stats
        except Exception as exc:
            kind=getattr(exc,'kind','invalid_output')
            write_json(attempt/'attempt.json',{**record,'status':'failed','ended_at':now(),
                'kind':kind,'uncertain':getattr(exc,'uncertain',False)})
            if not getattr(exc,'retryable',False) or retry==2 or getattr(exc,'retry_after',0)>30:raise
            time.sleep(max(getattr(exc,'retry_after',0),min(2**retry+random.random(),8)))
    raise AssertionError('unreachable')
