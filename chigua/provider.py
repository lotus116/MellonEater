from __future__ import annotations
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from .core import DATA, write_json, validate_schema
from .checkpoints import CallFailure


def status():
    provider = os.getenv('CHIGUA_PROVIDER', 'manual')
    return {'provider': provider,
            'available': (provider == 'codex' and bool(shutil.which('codex'))) or
                         (provider in ['api', 'deepseek'] and bool(os.getenv('CHIGUA_API_KEY')) and bool(os.getenv('CHIGUA_MODEL'))),
            'model': os.getenv('CHIGUA_MODEL', '本机 Codex 默认模型' if provider == 'codex' else '未配置'),
            'base_url': os.getenv('CHIGUA_BASE_URL', ''),
            'has_key': bool(os.getenv('CHIGUA_API_KEY')),
            'deepseek_thinking': os.getenv('CHIGUA_DEEPSEEK_THINKING','disabled'),
            'note': '云端分析会发送当前案例的文字与所选图片；不会自动读取其他聊天。'}


def parse_json(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)


def codex_failure(stderr_path):
    """Expose an actionable category, never raw stderr or submitted material."""
    try:
        with stderr_path.open('rb') as f:
            f.seek(max(0,stderr_path.stat().st_size-65536))
            diagnostic=f.read().decode('utf-8',errors='replace').lower()
    except OSError:diagnostic=''
    if ('failed to initialize in-process app-server client' in diagnostic and 'operation not permitted' in diagnostic):
        return 'Codex 启动被系统权限阻止，分析尚未开始。请关闭旧服务，再双击 start.command 从终端启动 demo；材料已保留，无需重新导入。'
    if any(s in diagnostic for s in ['not logged in','authentication failed','refresh token','401 unauthorized']):
        return 'Codex 登录状态不可用，请在本机重新登录后重试；材料已保留。'
    if any(s in diagnostic for s in ['rate limit','usage limit','429 too many requests']):
        return 'Codex 暂时达到使用限额，请稍后重试；材料已保留。'
    if any(s in diagnostic for s in ['connection refused','failed to connect','dns error','network is unreachable']):
        return 'Codex 连接服务失败，请检查网络后重试；材料已保留。'
    return 'Codex 未返回完整结果；材料和本机错误记录已保留。请重试，若再次失败可据错误记录排查。'


def api_base():
    kind=os.getenv('CHIGUA_PROVIDER','manual')
    base=(os.getenv('CHIGUA_BASE_URL') or ('https://api.deepseek.com' if kind=='deepseek' else 'https://api.openai.com/v1')).rstrip('/')
    parsed=urlsplit(base)
    if kind in ['api','deepseek'] and (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=='https' or parsed.scheme=='http' and parsed.hostname in ['127.0.0.1','localhost'])):
        raise ValueError('模型地址须为不含密钥、账号或查询参数的 HTTPS 地址；本机接口可使用 HTTP。')
    return base


def config_identity():
    s=status()
    config={'provider':s['provider'],'model':s['model'],
        'base_url':api_base(),
        'max_tokens':12000,'transport_version':3}
    if s['provider']=='deepseek':config['deepseek_options']=deepseek_options()
    return config


def deepseek_options():
    mode=os.getenv('CHIGUA_DEEPSEEK_THINKING','disabled')
    if mode not in ['disabled','low','high']:
        raise ValueError('DeepSeek 思考设置无效，尚未发出请求。')
    if mode=='disabled':return {'thinking':{'type':'disabled'}}
    return {'thinking':{'type':'enabled'},'reasoning_effort':mode}


def generate(prompt, schema, run_dir: Path, stage, images=()):
    from .checkpoints import call,media_hashes
    if not status()['available']:raise ValueError('还未配置模型入口，尚未发出请求。')
    return call(prompt,schema,run_dir,stage,images,config_identity(),media_hashes(images,DATA),
        lambda attempt:_generate_once(prompt,schema,attempt,stage,images),
        recover=lambda attempt:recover_response(schema,attempt,stage))


def recover_response(schema,attempt,stage):
    """Recover a durably received response after a crash before checkpoint commit."""
    response=attempt/'raw-response.json'
    if not response.exists():return None
    obj=json.loads(response.read_text());choice=obj['choices'][0]
    if choice.get('finish_reason') not in ['stop',None]:return None
    raw=choice['message']['content']
    if not raw or not raw.strip():return None
    value=parse_json(raw) if schema else raw
    if schema:validate_schema(value,schema)
    config=status()
    return value,{'provider':config['provider'],'model':config['model'],'seconds':0,
        'usage':obj.get('usage'),'cost':None,'recovered_response':True}


def _generate_once(prompt, schema, run_dir: Path, stage, images=()):
    config = status()
    if not config['available']:
        raise ValueError('还未配置模型入口。可以先查看示例报告，或导出分析请求在当前聊天完成。')
    write_json(run_dir / f'{stage}.request.json', {'prompt': prompt, 'schema': schema, 'images': list(images)})
    started = time.monotonic()
    usage = None
    if config['provider'] == 'codex':
        out = run_dir / f'{stage}.response.txt'
        args = [shutil.which('codex'), 'exec', '--skip-git-repo-check', '--ephemeral',
                '--ignore-user-config', '--sandbox', 'read-only', '--color', 'never', '--json',
                '--disable', 'shell_tool', '--disable', 'unified_exec', '--disable', 'multi_agent',
                '-C', str(run_dir), '-o', str(out)]
        if os.getenv('CHIGUA_MODEL'):
            args += ['-m', os.environ['CHIGUA_MODEL']]
        if schema:
            schema_path = run_dir / f'{stage}.schema.json'
            write_json(schema_path, schema)
            args += ['--output-schema', str(schema_path)]
        for path in images:
            args += ['-i', str(DATA / 'uploads' / Path(path).name)]
        args += ['-']
        # Fixed argv and stdin: imported content is never interpreted by a shell.
        event_path=run_dir / f'{stage}.events.jsonl'
        stderr_path=run_dir / f'{stage}.stderr.txt'
        try:
            with event_path.open('w',encoding='utf-8') as stdout, stderr_path.open('w',encoding='utf-8') as stderr:
                result = subprocess.run(args, input=prompt, stdout=stdout, stderr=stderr, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise CallFailure('Codex 本阶段超过 10 分钟，已停止等待。此前阶段已保存；本次计费未知，确认后仅重试当前阶段。',kind='timeout',uncertain=True) from None
        if result.returncode or not out.exists():
            raise RuntimeError(codex_failure(stderr_path))
        raw = out.read_text(encoding='utf-8')
        if not raw.strip():raise RuntimeError('Codex 返回了空结果，未发布报告；材料已保留，可重试。')
        for line in event_path.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'turn.completed':
                usage = event.get('usage')
            item = event.get('item', {})
            if item.get('type') in ['command_execution', 'mcp_tool_call', 'web_search']:
                raise RuntimeError('本次分析尝试调用额外工具，结果未被采纳。请检查模型配置。')
    else:
        base = api_base()
        if not (base.startswith('https://') or base.startswith('http://127.0.0.1:') or base.startswith('http://localhost:')):
            raise ValueError('模型地址需要使用 HTTPS；本机服务可使用 HTTP。')
        content = []
        for path in images:
            img = DATA / 'uploads' / Path(path).name
            mime = 'image/png' if img.suffix == '.png' else 'image/jpeg'
            content.append({'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,' + base64.b64encode(img.read_bytes()).decode()}})
        content.append({'type':'text','text':prompt})
        payload = {'max_tokens':12000,'model': config['model'], 'messages': [{'role': 'user', 'content': content if images else prompt}]}
        if schema:
            payload['response_format'] = ({'type': 'json_object'} if config['provider'] == 'deepseek' else
                {'type': 'json_schema', 'json_schema': {'name': 'chigua_output', 'strict': True, 'schema': schema}})
        if config['provider'] == 'deepseek':
            payload.update(deepseek_options())
        req = urllib.request.Request(base+'/chat/completions', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+os.environ['CHIGUA_API_KEY']})
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                body=response.read()
                (run_dir/'response-body.txt').write_bytes(body)
                obj=json.loads(body)
        except urllib.error.HTTPError as exc:
            try:delay=float(exc.headers.get('Retry-After','0'))
            except (ValueError,AttributeError):delay=0
            raise CallFailure(f'模型接口返回 HTTP {exc.code}；已保留进度。请检查接口、权限、余额或稍后继续。',
                kind='http_'+str(exc.code),retryable=exc.code in [429,500,502,503],uncertain=exc.code==504,retry_after=delay) from None
        except (TimeoutError,urllib.error.URLError,ConnectionError,OSError):
            raise CallFailure('连接中断或等待超时，服务端可能已处理本次请求。进度已保存；确认后仅重试当前阶段。',kind='connection',uncertain=True) from None
        write_json(run_dir/'usage.json',obj.get('usage'))
        write_json(run_dir/'raw-response.json',obj)
        choice = obj['choices'][0]
        if choice.get('finish_reason') == 'length':
            details=(obj.get('usage') or {}).get('completion_tokens_details') or {}
            note=(' 本次尚未返回正文，思考已用 '+str(details['reasoning_tokens'])+' token；可在设置中关闭深度思考后明确新建分析。'
                  if not choice.get('message',{}).get('content') and details.get('reasoning_tokens') else '')
            raise CallFailure('模型输出达到长度上限，原始响应与用量已保存。请调整输出要求，避免原样重试再次截断。'+note,kind='output_length')
        raw = choice['message']['content']
        if not raw or not raw.strip():
            raise RuntimeError('模型返回了空内容，未生成报告。可以重试或调整模型。')
        usage = obj.get('usage')
        (run_dir / f'{stage}.response.txt').write_text(raw, encoding='utf-8')
    write_json(run_dir/'usage.json',usage)
    value=parse_json(raw) if schema else raw
    if schema:validate_schema(value,schema)
    return value, {'provider': config['provider'], 'model': config['model'],
        'seconds': round(time.monotonic()-started, 2), 'usage': usage, 'cost': None}
