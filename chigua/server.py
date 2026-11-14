from __future__ import annotations
import argparse
import hashlib
import base64
import json
import mimetypes
import os
import secrets
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from .core import ROOT, DATA, REPORT_SCHEMA, build_prompt, fingerprint, normalize_messages, now, parse_import, parse_text, write_json
from . import mac, pipeline, provider
from .report import report_html, report_pdf

TOKEN = secrets.token_urlsafe(32)
STATIC = ROOT/'static'
MAX_BODY = 30*1024*1024
ZIP_IMPORT_LOCK = threading.Lock()


def safe_id(value):
    if not isinstance(value,str) or not value.isalnum():
        raise ValueError('编号无效。')
    return value


def get_run(rid):
    rid=safe_id(rid)
    result=json.loads((DATA/'runs'/rid/'result.json').read_text(encoding='utf-8'))
    reader=DATA/'runs'/rid/'reader.json'
    if reader.exists():
        edition=json.loads(reader.read_text(encoding='utf-8'))
        result['report']['reader']=edition['reader']
        result['reader_updated_at']=edition.get('edited_at',edition.get('created_at',result['created_at']))
        result['reader_trace']=edition.get('trace')
        result['reader_editorial_review']=edition.get('editorial_review')
        if edition.get('workflow_version'):
            result['editorial_trace']=edition['trace']
            result['editorial_quality']=edition['quality']
            result['editorial_workflow']=edition['workflow_version']
    return result


def cases():
    rows=[]
    for p in (DATA/'cases').glob('*.json'):
        c=json.loads(p.read_text(encoding='utf-8'))
        rows.append({k:c[k] for k in ['id','title','created_at','source_note']})
        rows[-1]['count']=len(c['messages'])
    return sorted(rows,key=lambda c:c['created_at'],reverse=True)


class Handler(BaseHTTPRequestHandler):
    server_version='Chigua/0.1'
    def log_message(self,*args):
        pass

    def send(self,body,status=200,ctype='application/json; charset=utf-8',filename=None):
        if isinstance(body,(dict,list)):
            body=json.dumps(body,ensure_ascii=False).encode()
        elif isinstance(body,str):
            body=body.encode()
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        script_hash=base64.b64encode(hashlib.sha256((STATIC/'reader.js').read_bytes()).digest()).decode()
        self.send_header('Content-Security-Policy',f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'sha256-{script_hash}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def guard(self,write=False):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in allowed:
            raise PermissionError('仅允许本机访问。')
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in allowed}:
            raise PermissionError('拒绝跨站请求。')
        if write and not secrets.compare_digest(self.headers.get('X-Chigua-Token',''),TOKEN):
            raise PermissionError('页面会话已失效，请刷新后再试。')

    def do_GET(self):
        try:
            self.guard()
            path=unquote(urlsplit(self.path).path)
            bits=path.strip('/').split('/')
            if path=='/api/config':
                return self.send({'token':TOKEN,'model':provider.status(),'mac':mac.probe(),'version':'0.1.0',
                    'active_jobs':[{k:v for k,v in j.items() if k!='result'} for j in pipeline.JOBS.values() if j['status']=='running']})
            if path=='/api/cases':
                return self.send(cases())
            if path=='/api/wechat-zip/defaults':
                scope_file=DATA/'private'/'wechat-setup'/'scope.json'
                scope=json.loads(scope_file.read_text()) if scope_file.is_file() else {}
                return self.send({'group':scope.get('group_name',''),
                                  'start':scope.get('start','')[:10],'end':scope.get('end','')[:10]})
            if len(bits)==3 and bits[:2]==['api','cases']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send({'case':c,'runs':pipeline.list_runs(c['id']),'jobs':pipeline.list_jobs(c['id'])})
            if len(bits)==3 and bits[:2]==['api','jobs']:
                return self.send(pipeline.get_job(safe_id(bits[2])))
            if len(bits)==3 and bits[:2]==['api','prompts']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send(build_prompt(c,'B1')+'\nJSON 格式：\n'+json.dumps(REPORT_SCHEMA,ensure_ascii=False,indent=2),ctype='text/plain; charset=utf-8',filename='analysis-request.txt')
            if len(bits)==3 and bits[:2]==['api','export']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send(c,filename='case-evidence.json')
            if len(bits)==3 and bits[0]=='report':
                rid=safe_id(bits[1])
                if bits[2]=='draft':
                    job = pipeline.get_job(rid)
                    if not job.get('draft_available'):
                        return self.send({'error':'暂无待复核稿。'},404)
                    folder = DATA/'runs'/rid
                    case = json.loads((folder/'input.json').read_text())
                    draft = json.loads((folder/'editorial/review-draft.json').read_text())
                    run = {'report':draft,'created_at':job['created_at'],'draft':True,
                           'draft_reason':job.get('error','')}
                    return self.send(report_html(case,run),ctype='text/html; charset=utf-8')
                run=get_run(rid); c=pipeline.load_case(run['case_id'])
                if bits[2]=='html':
                    return self.send(report_html(c,run),ctype='text/html; charset=utf-8')
                if bits[2]=='json':
                    return self.send(run,filename='analysis-result.json')
                if bits[2]=='pdf':
                    p=DATA/'runs'/rid/'report.pdf'
                    report_pdf(c,run,p)
                    return self.send(p.read_bytes(),ctype='application/pdf',filename='chigua-report.pdf')
            if len(bits)==2 and bits[0]=='media':
                name=bits[1]
                if Path(name).name!=name or not name.endswith(('.png','.jpg','.jpeg')):
                    raise ValueError('图片路径无效。')
                p=DATA/'uploads'/name
                return self.send(p.read_bytes(),ctype=mimetypes.guess_type(p.name)[0])
            name='index.html' if path=='/' else path.lstrip('/')
            if name not in ['index.html','app.js','style.css']:
                return self.send({'error':'页面不存在。'},404)
            p=STATIC/name
            return self.send(p.read_bytes(),ctype={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name])
        except PermissionError as e:
            self.send({'error':str(e)},403)
        except FileNotFoundError:
            self.send({'error':'文件或案例不存在。'},404)
        except Exception as e:
            self.send({'error':str(e)},400)

    def do_POST(self):
        try:
            self.guard(write=True)
            length=int(self.headers.get('Content-Length','0'))
            path=urlsplit(self.path).path
            if path=='/api/wechat-zip/upload':
                from .wechat_zip import MAX_ARCHIVE
                if not 0<length<=MAX_ARCHIVE:raise ValueError('每个 ZIP 需要小于 256 MB。')
                inbox=DATA/'private'/'zip-uploads'
                if inbox.is_symlink():raise ValueError('上传目录无效。')
                inbox.mkdir(parents=True,exist_ok=True,mode=0o700);inbox.chmod(0o700)
                uid=uuid.uuid4().hex;target=inbox/(uid+'.zip')
                try:
                    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:
                        remaining=length
                        while remaining:
                            chunk=self.rfile.read(min(remaining,1024*1024))
                            if not chunk:raise ValueError('文件传输未完成，请重新选择 ZIP。')
                            f.write(chunk);remaining-=len(chunk)
                    if not zipfile.is_zipfile(target):raise ValueError('文件不是有效的 ZIP，请选择 Dukou 导出的原始压缩包。')
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                return self.send({'id':uid,'bytes':length},201)
            if length<=0 or length>MAX_BODY:
                raise ValueError('请求为空或超过 30 MB。')
            obj=json.loads(self.rfile.read(length))
            if path=='/api/supplements/upload':
                from .supplements import store_asset
                raw=base64.b64decode(obj.get('data',''),validate=True)
                return self.send(store_asset(raw,DATA),201)
            if path=='/api/supplements/apply':
                from .supplements import clone_with_images
                case=pipeline.load_case(safe_id(obj.get('case_id')))
                return self.send(clone_with_images(case,obj.get('bindings'),DATA),201)
            if path=='/api/wechat-zip/import':
                from .wechat_zip import import_archives,MAX_ARCHIVE
                ids=obj.get('uploads')
                if not isinstance(ids,list) or not 1<=len(ids)<=100:raise ValueError('请选择 1 至 100 个 ZIP。')
                paths=[DATA/'private'/'zip-uploads'/(safe_id(uid)+'.zip') for uid in ids]
                if any(p.is_symlink() or not p.is_file() for p in paths):raise ValueError('上传文件已失效，请重新选择。')
                if sum(p.stat().st_size for p in paths)>MAX_ARCHIVE:raise ValueError('本次 ZIP 总大小超过 256 MB，请分批导入。')
                title=str(obj.get('title','')).strip()[:100];group=str(obj.get('group','')).strip()[:200]
                if not title or not group:raise ValueError('请填写案例名称和群名。')
                if not ZIP_IMPORT_LOCK.acquire(blocking=False):return self.send({'error':'另一份 ZIP 正在导入，请稍后重试。'},409)
                try:
                    imported,manifest=import_archives(paths,title=title,group_label=group,
                        start=str(obj.get('start','')),end=str(obj.get('end','')),data=DATA)
                    for p in set(paths):p.unlink(missing_ok=True)
                finally:ZIP_IMPORT_LOCK.release()
                return self.send({'cases':[{'id':c['id'],'title':c['title']} for c in imported],
                    'materials':manifest['materials'],'images':manifest['images'],
                    'excluded':manifest['out_of_window_excluded'],
                    'duplicates':manifest['duplicate_candidates_retained']},201)
            if path=='/api/upload':
                name=Path(str(obj.get('name',''))).name
                ext=Path(name).suffix.lower()
                if ext not in ['.png','.jpg','.jpeg']:
                    raise ValueError('截图暂时支持 PNG、JPG 和 JPEG。')
                raw=base64.b64decode(obj['data'],validate=True)
                if not raw or len(raw)>8*1024*1024:
                    raise ValueError('每张图片需要小于 8 MB。')
                if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):
                    raise ValueError('文件内容不是有效的 PNG 或 JPEG。')
                filename=uuid.uuid4().hex+ext
                p=DATA/'uploads'/filename; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
                lines,note=mac.ocr(p)
                return self.send({'image':filename,'source_name':name,'text':'\n'.join(x['text'] for x in lines),
                    'ocr_lines':lines,'uncertainty':note,'source_kind':'截图 OCR','speaker':'图内身份待核对'})
            if path=='/api/cases':
                title=str(obj.get('title','')).strip()[:100]
                if not title:
                    raise ValueError('请填写案例名称。')
                if obj.get('messages'):
                    messages=normalize_messages(obj['messages'])
                elif str(obj.get('text','')).strip():
                    messages=parse_import(obj['text'],obj.get('filename','粘贴文字.txt'))
                else:
                    messages=[]
                for att in obj.get('attachments',[]):
                    image=str(att.get('image',''))
                    if Path(image).name!=image or not (DATA/'uploads'/image).is_file():
                        raise ValueError('图片尚未上传。')
                    row=dict(att); row['id']=f'I{len(messages)+1:04d}'; messages.append(row)
                if not messages:
                    raise ValueError('请添加文字记录或至少一张截图。')
                messages=normalize_messages(messages)
                # Only managed uploaded images may be referenced in imported JSON.
                for m in messages:
                    if m.get('image') and (Path(str(m['image'])).name!=m['image'] or not (DATA/'uploads'/m['image']).exists()):
                        raise ValueError('JSON 中的图片需要先通过本页面上传。')
                if sum(len(m['text']) for m in messages)>150000:
                    raise ValueError('本版文字总量上限为 15 万字符，请缩小材料范围。')
                case={'id':uuid.uuid4().hex,'title':title,'messages':messages,'created_at':now(),
                    'question':str(obj.get('question') or '请自动发现主要事件，整理经过并分析争议。'),
                    'identity':str(obj.get('identity') or '旁观者'),
                    'source_note':str(obj.get('source_note') or '用户导入的材料包；覆盖范围、原始时间和图片识别结果需核对。'),
                    'input_hash':fingerprint(messages)}
                pipeline.save_case(case)
                return self.send(case,201)
            if path=='/api/analyze':
                case=pipeline.load_case(safe_id(obj['case_id']))
                if obj.get('identity'):
                    case['identity']=str(obj['identity'])[:200]
                return self.send(pipeline.start(case,obj.get('method','B1'),force=obj.get('force') is True,max_requests=obj.get('max_requests',20),max_total_tokens=obj.get('max_total_tokens',60000),reuse_vision_from=obj.get('reuse_vision_from')),202)
            if path=='/api/maintenance/reload':
                return self.send(reload_worker())
            if path=='/api/evaluations/false-completion':
                from .evaluation import false_completion
                return self.send(false_completion(safe_id(obj.get('run_id'))))
            if path=='/api/resume':
                return self.send(pipeline.resume(safe_id(obj['job_id']),allow_uncertain=obj.get('allow_uncertain') is True,max_requests=obj.get('max_requests'),max_total_tokens=obj.get('max_total_tokens'),local_only=obj.get('local_only') is True),202)
            if path=='/api/import-result':
                case=pipeline.load_case(safe_id(obj['case_id']))
                return self.send(pipeline.import_result(case,obj['report'],'用户导入分析结果'))
            if path=='/api/settings':
                if any(j['status']=='running' for j in pipeline.JOBS.values()):
                    raise ValueError('分析期间不能切换模型，避免同一次运行混用模型。')
                kind=obj.get('provider')
                if kind not in ['codex','deepseek','api','manual']:
                    raise ValueError('模型入口无效。')
                thinking=obj.get('deepseek_thinking','disabled')
                if thinking not in ['disabled','low','high']:raise ValueError('DeepSeek 思考设置无效。')
                model=str(obj.get('model','')).strip()
                if kind in ['api','deepseek'] and not model:
                    raise ValueError('请填写模型名称。')
                base=str(obj.get('base_url','')).strip().rstrip('/')
                if kind=='deepseek' and not base:
                    base='https://api.deepseek.com'
                if kind in ['api','deepseek'] and not (base.startswith('https://') or base.startswith('http://127.0.0.1:') or base.startswith('http://localhost:')):
                    raise ValueError('请填写 HTTPS 接口地址；本机服务可使用 HTTP。')
                if kind!=os.environ.get('CHIGUA_PROVIDER') or base!=os.environ.get('CHIGUA_BASE_URL',''):
                    os.environ.pop('CHIGUA_API_KEY',None)
                os.environ['CHIGUA_PROVIDER']=kind
                os.environ['CHIGUA_DEEPSEEK_THINKING']=thinking
                if model: os.environ['CHIGUA_MODEL']=model
                else: os.environ.pop('CHIGUA_MODEL',None)
                os.environ['CHIGUA_BASE_URL']=base
                if obj.get('api_key'):
                    os.environ['CHIGUA_API_KEY']=str(obj['api_key']).strip()
                return self.send(provider.status())
            return self.send({'error':'接口不存在。'},404)
        except PermissionError as e:
            self.send({'error':str(e)},403)
        except Exception as e:
            self.send({'error':str(e)},400)


def reload_worker():
    """Authenticated local maintenance; never exports credentials or starts work."""
    import importlib
    import fcntl
    if any(j['status']=='running' for j in pipeline.JOBS.values()):raise ValueError('任务运行时不能更新流程。')
    fd=pipeline.worker_lock()
    try:
        for name in ['core','checkpoints','provider','editor','report','event_sequence','evidence_first','compact','pipeline','evaluation']:
            importlib.reload(importlib.import_module('chigua.'+name))
        import sys
        # Keep the live handler's existing guard/token. Refresh its POST routes
        # so later maintenance does not require exporting an in-memory key.
        owner=sys.modules.get('__main__')
        if owner and getattr(owner,'Handler',None) and owner.Handler.__module__=='__main__':
            updated=importlib.reload(importlib.import_module('chigua.server'))
            updated.TOKEN=owner.TOKEN
            owner.Handler.do_POST=updated.Handler.do_POST
            owner.Handler.do_GET=updated.Handler.do_GET
        return {'workflow':pipeline.compact.VERSION,'status':'reloaded','model_requests':0}
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    for folder in ['cases','runs','uploads']:
        (DATA/folder).mkdir(parents=True,exist_ok=True)
    if not any((DATA/'cases').glob('*.json')):
        from .cli import seed_demo
        seed_demo()
    # Config contains only settings explicitly saved by the owner; never evaluate shell text.
    envfile=ROOT/'.env'
    if envfile.exists():
        for line in envfile.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line: continue
            key,value=line.split('=',1)
            if key.strip().startswith('CHIGUA_'):
                os.environ.setdefault(key.strip(),value.strip().strip('\"\''))
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'知瓜已启动：http://127.0.0.1:{args.port}',flush=True)
    server.serve_forever()


if __name__=='__main__':
    main()
