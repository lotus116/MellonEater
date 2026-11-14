from __future__ import annotations
import json
import threading
import uuid
from .core import DATA, REPORT_SCHEMA, DISCOVERY_SCHEMA, build_prompt, now, validate_report, write_json
from . import provider
from .editor import edit_report

JOBS = {}
LOCK = threading.Lock()


def load_case(cid):
    if not cid.isalnum():
        raise ValueError('案例编号无效。')
    return json.loads((DATA / 'cases' / f'{cid}.json').read_text(encoding='utf-8'))


def save_case(case):
    write_json(DATA / 'cases' / (case['id']+'.json'), case)


def run_pipeline(jid, case, method):
    job = JOBS[jid]
    folder = DATA / 'runs' / jid
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / 'input.json', case)
    try:
        plan = [('discover', DISCOVERY_SCHEMA), ('evidence', REPORT_SCHEMA), ('assess', REPORT_SCHEMA), ('review', REPORT_SCHEMA)]
        if method in ['B0', 'B1']:
            plan = [(method, REPORT_SCHEMA)]
        elif method == 'A1':
            plan = [('discover', DISCOVERY_SCHEMA), ('notes', None), ('notes_assess', None), ('review', REPORT_SCHEMA)]
        prior, trace = None, []
        images = list(dict.fromkeys(m['image'] for m in case['messages'] if m.get('image')))
        for index, (stage, schema) in enumerate(plan):
            job.update(stage=stage, step=index+1, total=len(plan),phase='analysis')
            prompt = build_prompt(case, stage, prior)
            # Schema also goes into prompt so providers returning plain text see the contract.
            if schema:
                prompt += '\n输出格式：\n'+json.dumps(schema, ensure_ascii=False)
            prior, stats = provider.generate(prompt, schema, folder, stage, images)
            trace.append({'stage': stage, **stats})
            write_json(folder / f'{stage}.output.json', prior)
        prior.pop('reader',None)
        checks = validate_report(prior, case['messages'])
        write_json(folder/'analysis_report.json',prior)
        write_json(folder/'analysis_trace.json',trace)
        def editorial_progress(stage):
            job.update(stage=stage,phase='editing',step=0,total=0)
        edition=edit_report(case,prior,folder/'editorial',editorial_progress)
        run = {'id': jid, 'case_id': case['id'], 'method': method, 'created_at': now(),
               'origin': 'live_model', 'input_hash': case['input_hash'], 'identity': case.get('identity','旁观者'),
               'report':{**prior,'reader':edition['reader']},'checks': checks,'trace': trace,
               'editorial_trace':edition['trace'],'editorial_quality':edition['quality'],
               'editorial_workflow':edition['workflow_version'],'status': 'completed'}
        write_json(folder / 'result.json', run)
        # Case records are immutable; each run has its own provenance and output.
        job.update(status='completed', result=run)
    except Exception as exc:
        job.update(status='failed', error=str(exc))
        write_json(folder / 'failure.json', {k:v for k,v in job.items() if k != 'result'})


def start(case, method):
    if method not in ['B0', 'B1', 'B2', 'A1']:
        raise ValueError('未知分析方法。')
    if not provider.status()['available']:
        raise ValueError('模型入口尚未配置；示例报告和材料查看仍可使用。')
    with LOCK:
        if any(j['status'] == 'running' for j in JOBS.values()):
            raise ValueError('已有分析正在运行，请等待完成后再开始。')
        jid = uuid.uuid4().hex
        JOBS[jid] = {'id': jid, 'case_id': case['id'], 'status': 'running', 'stage': 'queued', 'step': 0, 'total': 4}
    threading.Thread(target=run_pipeline, args=(jid, case, method), daemon=True).start()
    return JOBS[jid]


def import_result(case, report, origin='当前会话分析'):
    checks = validate_report(report, case['messages'])
    rid = uuid.uuid4().hex
    run = {'id': rid, 'case_id': case['id'], 'method': 'imported', 'created_at': now(),
           'origin': origin, 'input_hash': case['input_hash'], 'report': report,
           'checks': checks, 'trace': [], 'status': 'completed'}
    write_json(DATA / 'runs' / rid / 'result.json', run)
    return run


def list_runs(cid):
    result = []
    for p in (DATA / 'runs').glob('*/result.json'):
        row = json.loads(p.read_text(encoding='utf-8'))
        if row['case_id'] == cid:
            reader_path=p.parent/'reader.json'
            if reader_path.exists():
                edition=json.loads(reader_path.read_text(encoding='utf-8'))
                row['report']['reader']=edition['reader']
                row['reader_updated_at']=edition.get('edited_at',edition.get('created_at',row['created_at']))
                row['reader_trace']=edition.get('trace')
                row['reader_editorial_review']=edition.get('editorial_review')
                if edition.get('workflow_version'):
                    row['editorial_trace']=edition['trace']
                    row['editorial_quality']=edition['quality']
                    row['editorial_workflow']=edition['workflow_version']
            result.append(row)
    return sorted(result, key=lambda r:r['created_at'], reverse=True)
