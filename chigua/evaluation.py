"""A bounded negative control on a completed synthetic report; never publishes."""
import json
from pathlib import Path
from . import core,compact,provider,pipeline
from .checkpoints import digest,usage_summary


def false_completion(run_id):
    if not isinstance(run_id,str) or not run_id.isalnum():raise ValueError('运行编号无效。')
    folder=core.DATA/'runs'/run_id
    case=json.loads((folder/'input.json').read_text());run=json.loads((folder/'result.json').read_text())
    if not case.get('source_note','').startswith('完全虚构') or len(case['messages'])>10 or run.get('status')!='completed' or run.get('editorial_workflow')!=compact.VERSION:
        raise ValueError('反例测试仅用于已完成的新版合成小样本。')
    # Exactly one fixed mutation; no arbitrary prompts, files, or real cases.
    if not any(m['text']=='我还没收到退款，等你处理。' for m in case['messages']):raise ValueError('该样本不适用此反例。')
    pack=json.loads((folder/'editorial/evidence-pack.json').read_text())
    _,ids,assets=compact.prepare(case);candidate=compact.map_refs(run['report'],ids)
    candidate['reader']['verdict']='所有参与者都已收到退款，退款争议已经结束。'
    key=digest({'source_run':run_id,'candidate':candidate,'rules':compact.RULES,'policy':compact.POLICY,'config':provider.config_identity()})
    target=core.DATA/'private/compact-negative'/key
    if (target/'evaluation.json').exists():return json.loads((target/'evaluation.json').read_text())
    fd=pipeline.worker_lock()
    try:
        core.write_json(target/'manifest.json',{'max_requests':1,'max_total_tokens':12000})
        value,stats=provider.generate(compact.audit_task(pack,candidate,[])+'\n输出 JSON：'+compact.dump(compact.AUDIT_SCHEMA),
            compact.AUDIT_SCHEMA,target,'negative_audit',list(assets),
            options={'max_tokens':compact.POLICY['audit_tokens'],'thinking':compact.POLICY['audit_thinking'],'image_labels':assets})
        blockers=compact.audit_issues(value,candidate,pack)
        passed=any(i['path']=='/reader/verdict' and i['category'] in ['fact','causality'] for i in blockers)
        result={'id':key,'source_run':run_id,'passed':passed,'mutation':'false_completion',
                'blocking_count':len(blockers),'usage':usage_summary(target),'report_published':False}
        core.write_json(target/'evaluation.json',result);return result
    finally:
        import fcntl,os
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
