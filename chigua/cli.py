from __future__ import annotations
import argparse
import json
import os
import uuid
from pathlib import Path
from .core import DATA, fingerprint, normalize_messages, now, parse_import
from .pipeline import JOBS, load_case, save_case, run_pipeline, list_runs
from .report import report_html, report_pdf


def seed_demo():
    if (DATA/'cases'/'syntheticdemo.json').exists():return
    obj=json.loads((DATA/'samples'/'demo.json').read_text(encoding='utf-8'))
    messages=normalize_messages(obj['messages'])
    save_case({'id':'syntheticdemo','title':obj['title'],'source_note':obj['source_note'],
        'messages':messages,'created_at':now(),'identity':'旁观者',
        'question':'还原主要事件，判断是否有充分证据认定超预算和拒绝报销。',
        'input_hash':fingerprint(messages)})


def main():
    p=argparse.ArgumentParser(description='知瓜本地分析与复现入口')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('seed-demo')
    imp=sub.add_parser('import');imp.add_argument('path',type=Path);imp.add_argument('--title',required=True)
    run=sub.add_parser('analyze');run.add_argument('case_id');run.add_argument('--method',choices=['B0','B1','B2','A1'],default='B2')
    run.add_argument('--provider',choices=['codex','deepseek','api']);run.add_argument('--model');run.add_argument('--identity')
    exp=sub.add_parser('export');exp.add_argument('case_id');exp.add_argument('--format',choices=['html','pdf'],default='html');exp.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.command=='seed-demo':seed_demo();print('syntheticdemo');return
    if args.command=='import':
        messages=parse_import(args.path.read_text(encoding='utf-8'),args.path.name)
        case={'id':uuid.uuid4().hex,'title':args.title,'messages':messages,'created_at':now(),
              'identity':'旁观者','question':'自动发现事件并分析主要争议。',
              'source_note':'用户通过本地命令导入；请核对覆盖范围和来源。','input_hash':fingerprint(messages)}
        save_case(case);print(case['id']);return
    case=load_case(args.case_id)
    if args.command=='analyze':
        if args.provider:os.environ['CHIGUA_PROVIDER']=args.provider
        if args.model:os.environ['CHIGUA_MODEL']=args.model
        if args.identity:case['identity']=args.identity
        rid=uuid.uuid4().hex;JOBS[rid]={'id':rid,'status':'running'}
        print('run_id='+rid,flush=True)
        run_pipeline(rid,case,args.method)
        job=JOBS[rid]
        if job['status']!='completed':raise SystemExit(job.get('error','分析失败'))
        print('completed: '+str(DATA/'runs'/rid/'result.json'))
    else:
        runs=list_runs(case['id'])
        if not runs:raise SystemExit('该案例还没有完成的分析。')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        if args.format=='pdf':report_pdf(case,runs[0],args.output)
        else:args.output.write_text(report_html(case,runs[0]),encoding='utf-8')
        print(args.output)


if __name__=='__main__':main()
