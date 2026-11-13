from __future__ import annotations
import argparse
import base64
import json
import mimetypes
import os
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from .core import ROOT, DATA, REPORT_SCHEMA, build_prompt, fingerprint, normalize_messages, now, parse_import, parse_text, write_json
from . import mac, pipeline, provider
from .report import report_html, report_pdf

TOKEN = secrets.token_urlsafe(32)
STATIC = ROOT/'static'
MAX_BODY = 30*1024*1024


def safe_id(value):
    if not isinstance(value,str) or not value.isalnum():
        raise ValueError('编号无效。')
    return value


def get_run(rid):
    rid=safe_id(rid)
    result=json.loads((DATA/'runs'/rid/'result.json').read_text(encoding='utf-8'))
    reader=DATA/'runs'/rid/'reader.json'
    if reader.exists():result['report']['reader']=json.loads(reader.read_text(encoding='utf-8'))['reader']
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
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
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
            if len(bits)==3 and bits[:2]==['api','cases']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send({'case':c,'runs':pipeline.list_runs(c['id'])})
            if len(bits)==3 and bits[:2]==['api','jobs']:
                jid=safe_id(bits[2])
                if jid in pipeline.JOBS:
                    return self.send(pipeline.JOBS[jid])
                try:
                    return self.send({'status':'completed','result':get_run(jid)})
                except FileNotFoundError:
                    raise ValueError('任务已停止或不存在，请重新开始分析。')
            if len(bits)==3 and bits[:2]==['api','prompts']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send(build_prompt(c,'B1')+'\nJSON 格式：\n'+json.dumps(REPORT_SCHEMA,ensure_ascii=False,indent=2),ctype='text/plain; charset=utf-8',filename='analysis-request.txt')
            if len(bits)==3 and bits[:2]==['api','export']:
                c=pipeline.load_case(safe_id(bits[2]))
                return self.send(c,filename='case-evidence.json')
            if len(bits)==3 and bits[0]=='report':
                rid=safe_id(bits[1]); run=get_run(rid); c=pipeline.load_case(run['case_id'])
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
            if length<=0 or length>MAX_BODY:
                raise ValueError('请求为空或超过 30 MB。')
            obj=json.loads(self.rfile.read(length))
            path=urlsplit(self.path).path
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
                return self.send(pipeline.start(case,obj.get('method','B2')),202)
            if path=='/api/import-result':
                case=pipeline.load_case(safe_id(obj['case_id']))
                return self.send(pipeline.import_result(case,obj['report'],'用户导入分析结果'))
            if path=='/api/settings':
                if any(j['status']=='running' for j in pipeline.JOBS.values()):
                    raise ValueError('分析期间不能切换模型，避免同一次运行混用模型。')
                kind=obj.get('provider')
                if kind not in ['codex','deepseek','api','manual']:
                    raise ValueError('模型入口无效。')
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
