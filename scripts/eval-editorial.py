"""Live synthetic regression: outputs stay local and are never manually repaired."""
import argparse,json,os,sys,threading,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import ROOT,DATA,normalize_messages,fingerprint,now,write_json
from chigua.pipeline import JOBS,run_pipeline,save_case
from chigua.report import report_pdf


def main():
    p=argparse.ArgumentParser();p.add_argument('--provider',default='codex',choices=['codex','deepseek','api'])
    p.add_argument('--model');p.add_argument('--case',choices=['venue','parallel','fragment']);args=p.parse_args()
    os.environ['CHIGUA_PROVIDER']=args.provider
    if args.model:os.environ['CHIGUA_MODEL']=args.model
    manifest={'created_at':now(),'synthetic':True,'runs':[]}
    stamp=uuid.uuid4().hex[:10];manifest_path=DATA/'private'/f'editorial-eval-{stamp}.json'
    for name in ([args.case] if args.case else ['venue','parallel','fragment']):
        fixture=json.loads((DATA/'samples'/f'editorial-{name}.json').read_text(encoding='utf-8'))
        messages=normalize_messages(fixture['messages'])
        case={'id':uuid.uuid4().hex,'title':fixture['title'],'messages':messages,'created_at':now(),
              'source_note':'完全虚构的自动编辑回归样例，不是真实聊天。','identity':'旁观者',
              'question':fixture['question'],'input_hash':fingerprint(messages)}
        save_case(case);rid=uuid.uuid4().hex;JOBS[rid]={'id':rid,'status':'running'}
        worker=threading.Thread(target=run_pipeline,args=(rid,case,'B1'));worker.start();previous=None
        while worker.is_alive():
            stage=JOBS[rid].get('stage','starting')
            if stage!=previous:print(name,rid,stage,flush=True);previous=stage
            worker.join(2)
        job=JOBS[rid];row={'name':name,'case_id':case['id'],'run_id':rid,'status':job['status']}
        if job['status']=='completed':
            out=ROOT/'output'/'pdf'/f'editorial-{name}-{stamp}.pdf'
            row['layout']=report_pdf(case,job['result'],out);out.chmod(0o600)
            row.update(pdf=str(out),quality=job['result']['editorial_quality'],
                calls=len(job['result']['trace'])+len(job['result']['editorial_trace']))
        else:row['error']=job.get('error')
        manifest['runs'].append(row);write_json(manifest_path,manifest)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    print('manifest='+str(manifest_path),flush=True)
    if any(r['status']!='completed' for r in manifest['runs']):raise SystemExit(1)


if __name__=='__main__':main()
