from __future__ import annotations
import json
import threading
import uuid
import os
import fcntl
import copy
from .core import DATA, REPORT_SCHEMA, DISCOVERY_SCHEMA, build_prompt, now, validate_report, write_json, normalize_reference_ids
from . import provider
from .editor import edit_report, VERSION as EDITOR_VERSION
from .core import RULES, READER_RULES
from .checkpoints import digest, media_hashes, usage_summary, CallFailure
from . import compact

JOBS = {}
LOCK = threading.Lock()


def load_case(cid):
    if not cid.isalnum():
        raise ValueError('案例编号无效。')
    return json.loads((DATA / 'cases' / f'{cid}.json').read_text(encoding='utf-8'))


def save_case(case):
    write_json(DATA / 'cases' / (case['id']+'.json'), case)


DEFAULT_TOKEN_LIMIT=150_000
WORKFLOW_VERSION='resumable-v1'


def selected_workflow(method,workflow=None):
    return workflow or (os.getenv('CHIGUA_WORKFLOW') or compact.VERSION if method=='B1' else WORKFLOW_VERSION)


def signature(case,method,workflow=None,*,config=None):
    images=list(dict.fromkeys(m['image'] for m in case['messages'] if m.get('image')))
    workflow = selected_workflow(method,workflow)
    config=provider.config_identity() if config is None else config
    if workflow in compact.SUPPORTED_VERSIONS:
        components = {'case':case,'method':method,'media':media_hashes(images,DATA),
                      'config':config,'workflow':workflow,'rules':compact.RULES,'policy':compact.POLICY}
        if workflow in compact.COMPARATIVE_VERSIONS:
            components['reading_rules'] = compact.READING_RULES
            components['context_rule'] = compact.CONTEXT_RULE
        if workflow in compact.TIMED_VERSIONS:
            components['chronology_rule'] = compact.CHRONOLOGY_RULE
        if workflow in compact.ANCHORED_VERSIONS:
            components['source_rules'] = compact.SOURCE_RULES
        if workflow in compact.ACTION_VERSIONS:
            components['sequence_rules'] = compact.event_sequence.RULES
        if workflow == compact.CROSSCHECK_VERSION:
            components['review_crosscheck'] = compact.REVIEW_CROSSCHECK
        if workflow in compact.EVIDENCE_FIRST_VERSIONS:
            components['binding_rules'] = compact.evidence_first.RULES
            components['writer_rules'] = compact.evidence_first.WRITE_RULES
        return digest(components)
    return digest({'case':case,'method':method,'media':media_hashes(images,DATA),
        'config':config,'workflow':WORKFLOW_VERSION,'editor':EDITOR_VERSION,
        'rules':RULES,'reader_rules':READER_RULES})


def persist(job):
    write_json(DATA/'runs'/job['id']/'job.json',{k:v for k,v in job.items() if k!='result'})


def get_job(jid):
    if not jid.isalnum():raise ValueError('任务编号无效。')
    folder=DATA/'runs'/jid
    if jid in JOBS:job=copy.deepcopy(JOBS[jid])
    elif (folder/'job.json').exists():
        job=json.loads((folder/'job.json').read_text())
        if job['status']=='running':
            job.update(status='interrupted',error='服务曾中断。已完成步骤仍在，点击继续可从断点恢复。',uncertain=True)
    elif (folder/'result.json').exists():
        return {'id':jid,'status':'completed','result':json.loads((folder/'result.json').read_text())}
    else:raise ValueError('任务不存在。')
    if (folder/'result.json').exists():
        job.update(status='completed',result=json.loads((folder/'result.json').read_text()),error='',uncertain=False)
        job.pop('error_kind',None)
        job.pop('diagnostics',None)
    job['usage']=usage_summary(folder)
    job['cached_steps']=sum(1 for _ in folder.rglob('completed.json'))
    if job.get('status')=='failed' and '两轮返修后仍未通过' in job.get('error',''):
        job['error_kind']='editorial_exhausted'
        check=folder/'editorial/checks.json'
        if check.exists():
            history=json.loads(check.read_text())
            if history:
                last=history[-1];job['diagnostics']=(last.get('review') or {}).get('issues',[])+[{'problem':x} for x in last.get('issues',[])]
    job['can_resume']=job.get('error_kind') not in ['editorial_exhausted','review_invalid','structure','visual_mapping','workflow_changed','cache','output_length']
    if job['status'] in {'running','failed','interrupted'} and (folder/'editorial/review-draft.json').is_file():
        job['draft_available'] = True
    if (job['status']=='failed' and job.get('workflow')==compact.PREVIOUS_VERSION
            and job.get('error_kind')=='review_invalid'
            and compact.can_recover_audit(folder/'editorial',job.get('stage',''))):
        job['can_resume']=True
        job['error']='已从逐字引文恢复审稿定位。可以从已保存的步骤继续局部修改和复核。'
    return job


def list_jobs(cid):
    jobs=[]
    for p in (DATA/'runs').glob('*/job.json'):
        j=get_job(p.parent.name)
        if j.get('case_id')==cid:
            j.pop('result',None);jobs.append(j)
    return sorted(jobs,key=lambda j:j.get('created_at',''),reverse=True)


def worker_lock():
    root=DATA/'private';root.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(root/'analysis.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd);raise ValueError('已有分析正在运行，请等待完成后再开始。') from None
    return fd


def run_pipeline(jid, case, method):
    job = JOBS[jid]
    folder = DATA / 'runs' / jid
    folder.mkdir(parents=True, exist_ok=True,mode=0o700)
    if not (folder/'input.json').exists():write_json(folder / 'input.json', case)
    try:
        workflow = job.get('workflow','')
        if workflow.startswith('compact-') and workflow not in compact.SUPPORTED_VERSIONS:
            raise CallFailure('流程版本已更新，旧任务不混用新步骤；原结果保留，未发出请求。',kind='workflow_changed')
        if workflow in compact.SUPPORTED_VERSIONS:
            def progress(stage):
                job.update(stage=stage,phase='editing',step=0,total=0);persist(job)
            edition=compact.execute(case,folder/'editorial',progress,version=workflow)
            run={'id':jid,'case_id':case['id'],'method':method,'created_at':now(),
                'origin':'live_model','input_hash':case['input_hash'],'identity':case.get('identity','旁观者'),
                'report':edition['report'],'checks':validate_report(edition['report'],case['messages']),
                'trace':[],'editorial_trace':edition['trace'],'editorial_quality':edition['quality'],
                'editorial_workflow':edition['workflow_version'],'status':'completed','usage':usage_summary(folder)}
            write_json(folder/'result.json',run)
            job.update(status='completed',result=run,error='',uncertain=False);persist(job);return
        plan = [('discover', DISCOVERY_SCHEMA), ('evidence', REPORT_SCHEMA), ('assess', REPORT_SCHEMA), ('review', REPORT_SCHEMA)]
        if method in ['B0', 'B1']:
            plan = [(method, REPORT_SCHEMA)]
        elif method == 'A1':
            plan = [('discover', DISCOVERY_SCHEMA), ('notes', None), ('notes_assess', None), ('review', REPORT_SCHEMA)]
        prior, trace = None, []
        images = list(dict.fromkeys(m['image'] for m in case['messages'] if m.get('image')))
        for index, (stage, schema) in enumerate(plan):
            job.update(stage=stage, step=index+1, total=len(plan),phase='analysis');persist(job)
            prompt = build_prompt(case, stage, prior)
            if schema:prompt += '\n输出格式：\n'+json.dumps(schema, ensure_ascii=False)
            prior, stats = provider.generate(prompt, schema, folder, stage, images)
            prior,repairs=normalize_reference_ids(prior,case['messages'])
            if repairs:
                stats={**stats,'local_reference_repairs':repairs}
                write_json(folder/f'{stage}.reference-repairs.json',repairs)
            trace.append({'stage': stage, **stats})
            write_json(folder / f'{stage}.output.json', prior)
            write_json(folder/'analysis_trace.json',trace)
        prior=copy.deepcopy(prior);prior.pop('reader',None)
        checks = validate_report(prior, case['messages'])
        write_json(folder/'analysis_report.json',prior)
        def editorial_progress(stage):
            job.update(stage=stage,phase='editing',step=0,total=0);persist(job)
        edition=edit_report(case,prior,folder/'editorial',editorial_progress)
        run = {'id': jid, 'case_id': case['id'], 'method': method, 'created_at': now(),
               'origin': 'live_model', 'input_hash': case['input_hash'], 'identity': case.get('identity','旁观者'),
               'report':{**prior,'reader':edition['reader']},'checks': checks,'trace': trace,
               'editorial_trace':edition['trace'],'editorial_quality':edition['quality'],
               'editorial_workflow':edition['workflow_version'],'status': 'completed','usage':usage_summary(folder)}
        write_json(folder / 'result.json', run)
        job.update(status='completed', result=run,error='',uncertain=False)
    except Exception as exc:
        job.update(status='failed', error=str(exc),error_kind=getattr(exc,'kind','validation'),uncertain=getattr(exc,'uncertain',False))
        if getattr(exc,'diagnostics',None):job['diagnostics']=exc.diagnostics
        failure={k:v for k,v in job.items() if k != 'result'}
        write_json(folder/'failures'/(uuid.uuid4().hex+'.json'),failure)
        write_json(folder / 'failure.json',failure)
    persist(job)


def _launch(job,case,method,background,*,policy=None):
    fd=worker_lock()
    try:
        folder=DATA/'runs'/job['id']
        if not (folder/'input.json').exists():write_json(folder/'input.json',case)
        if policy is not None:write_json(folder/'manifest.json',policy)
        persist(job)
        JOBS[job['id']]=job
    except BaseException:
        os.close(fd)
        raise
    def work():
        try:run_pipeline(job['id'],case,method)
        finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    if background:threading.Thread(target=work,daemon=True).start()
    else:work()
    return get_job(job['id'])


def start(case, method='B1', *, force=False, max_requests=20, background=True,workflow=None,max_total_tokens=DEFAULT_TOKEN_LIMIT,
          reuse_vision_from=None,recover_binding_from=None,recovery_focus=None,recovery_targets=None,
          recovery_review_from=None,recovery_visual_from=None):
    if method not in ['B0', 'B1', 'B2', 'A1']:raise ValueError('未知分析方法。')
    if not isinstance(max_requests,int) or not 4<=max_requests<=100:raise ValueError('请求上限应为 4 至 100 次。')
    workflow=selected_workflow(method,workflow)
    if not isinstance(max_total_tokens,int) or not 1000<=max_total_tokens<=1000000:raise ValueError('token 阈值应为 1,000 至 1,000,000。')
    recovery = None
    if recover_binding_from is not None:
        if workflow != compact.VERSION or method != 'B1':
            raise ValueError('截断恢复需使用当前标准流程。')
        if not isinstance(recover_binding_from,str) or not recover_binding_from.isalnum():
            raise ValueError('原任务编号无效。')
        if (not isinstance(recovery_focus,list) or not 1 <= len(recovery_focus) <= 24
                or any(not isinstance(s,str) for s in recovery_focus)):
            raise ValueError('请指定 1 至 24 个需核对的材料编号。')
        prior = DATA/'runs'/recover_binding_from
        source = json.loads((prior/'input.json').read_text())
        if source['id']!=case['id'] or source['messages']!=case['messages']:
            raise ValueError('恢复任务必须对应同一案例和原始材料。')
        recovery = {'run':recover_binding_from,'focus':list(dict.fromkeys(recovery_focus))}
        if recovery_targets is not None:
            if (not isinstance(recovery_targets,dict) or not recovery_targets
                    or set(recovery_targets)-set(compact.evidence_first.KIND_PHASE)
                    or any(not isinstance(ids,list) or not ids
                           or any(not isinstance(s,str) or s not in recovery['focus'] for s in ids)
                           for ids in recovery_targets.values())):
                raise ValueError('事件复核的引文须在已选重点材料内。')
            recovery['targets'] = recovery_targets
        for key, run_id in (('review_from',recovery_review_from),('visual_from',recovery_visual_from)):
            if run_id is None:
                continue
            if not isinstance(run_id,str) or not run_id.isalnum():
                raise ValueError('缓存任务编号无效。')
            cache = DATA/'runs'/run_id
            if not (cache/'input.json').is_file():
                raise ValueError('找不到缓存任务。')
            if key=='review_from':
                recorded = json.loads((cache/'input.json').read_text())
                if recorded['id']!=case['id'] or recorded['messages']!=case['messages']:
                    raise ValueError('文案复核缓存必须与原始材料一致。')
                if not compact.recovery_reviews(cache/'editorial'):
                    raise ValueError('没有已保存的文案复核响应。')
            elif not (cache/'editorial/evidence-pack.json').is_file():
                raise ValueError('没有已保存的读图描述。')
            recovery[key] = run_id
        reuse_vision_from = recover_binding_from
        compact.saved_binding(prior/'editorial')
        if not set(recovery['focus']) <= set(compact.prepare(case)[1].values()):
            raise ValueError('恢复范围含未知材料编号。')
    key=signature(case,method,workflow)
    if recovery:
        key=digest({'signature':key,'binding_recovery':recovery})
    with LOCK:
        if not force:
            for p in sorted((DATA/'runs').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                manifest=json.loads(p.read_text())
                if manifest.get('signature')==key and any(
                        (p.parent/name).is_file() for name in ('job.json','result.json')):
                    return get_job(p.parent.name)
        if any(j['status']=='running' for j in JOBS.values()):raise ValueError('已有分析正在运行，请等待完成后再开始。')
        if not provider.status()['available']:raise ValueError('模型入口尚未配置；示例报告和材料查看仍可使用。')
        if reuse_vision_from is not None:
            if not isinstance(reuse_vision_from,str) or not reuse_vision_from.isalnum():
                raise ValueError('读图来源编号无效。')
            source = json.loads((DATA/'runs'/reuse_vision_from/'input.json').read_text())
            if source['id'] != case['id'] or source['messages'] != case['messages']:
                raise ValueError('读图来源必须为同一案例与同一份材料。')
        jid=uuid.uuid4().hex
        policy={'signature':key,'method':method,'config':provider.config_identity(),
            'max_requests':max_requests,'max_total_tokens':max_total_tokens,'created_at':now(),'workflow':workflow,
            'reuse_vision_from':reuse_vision_from,'binding_recovery':recovery}
        job={'id':jid,'case_id':case['id'],'status':'running','stage':'queued','step':0,
             'total':1 if method in ['B0','B1'] else 4,'created_at':now(),'max_requests':max_requests,'method':method,'workflow':workflow,'max_total_tokens':max_total_tokens}
        return _launch(job,case,method,background,policy=policy)


def resume(jid,*,allow_uncertain=False,max_requests=None,max_total_tokens=None,background=True,local_only=False):
    with LOCK:
        job=get_job(jid)
        if job['status'] in ['completed','running']:return job
        if (job.get('error_kind') in ['editorial_exhausted','review_invalid','structure','visual_mapping','workflow_changed']
                and job.get('can_resume') is False and not local_only):
            raise ValueError('这次失败需要修正具体问题，原样续跑不会改善，已停止追加调用。请查看问题详情；新版流程须明确新建任务。')
        if job.get('error_kind') in ['cache','output_length'] and not local_only:
            raise ValueError('该问题需要先修复缓存或输出长度设置，原样继续可能重复失败；已停止追加请求。')
        if any(j['status']=='running' for j in JOBS.values()):raise ValueError('已有分析正在运行，请等待完成后再继续。')
        folder=DATA/'runs'/jid
        if not (folder/'manifest.json').exists():raise ValueError('旧版本任务没有可靠检查点，请新建分析；原记录保留。')
        manifest=json.loads((folder/'manifest.json').read_text());case=json.loads((folder/'input.json').read_text())
        config = manifest.get('config') if local_only else None
        key=signature(case,manifest['method'],manifest.get('workflow',WORKFLOW_VERSION),config=config)
        if manifest.get('binding_recovery'):
            key=digest({'signature':key,'binding_recovery':manifest['binding_recovery']})
        if key!=manifest['signature']:
            raise ValueError('模型、材料或流程规则已改变。为避免混用结果，请恢复原设置，或明确新建分析。')
        if not local_only and not provider.status()['available']:raise ValueError('请先配置原模型入口，密钥可以重新填写。')
        if job.get('uncertain') and not (allow_uncertain or local_only):
            raise ValueError('中断的请求可能已计费。请确认仅重试未完成阶段。')
        if max_requests is not None:
            if not isinstance(max_requests,int) or not manifest['max_requests']<=max_requests<=100:
                raise ValueError('继续时只能明确提高请求上限，最多 100 次。')
            manifest['max_requests']=max_requests
        if max_total_tokens is not None:
            if not isinstance(max_total_tokens,int) or not manifest.get('max_total_tokens',1000)<=max_total_tokens<=1000000:
                raise ValueError('继续时只能明确提高已记录 token 阈值，最多 1,000,000。')
            manifest['max_total_tokens']=max_total_tokens
        manifest['retry_uncertain']=allow_uncertain and not local_only
        manifest['local_only']=local_only
        job.pop('error_kind',None)
        job.pop('diagnostics',None)
        job.update(status='running',error='',uncertain=False,max_requests=manifest['max_requests'],max_total_tokens=manifest.get('max_total_tokens'))
        return _launch(job,case,manifest['method'],background,policy=manifest)


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
