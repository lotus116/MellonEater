"""Paid small synthetic checks through the running localhost app, never real chats.

Example: python scripts/eval-compact-live.py chronology --inject-local-failure
Results and expected answers stay separate from the model input.
"""
import argparse,base64,io,json,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import ROOT,write_json
from chigua.checkpoints import usage_summary
from chigua.compact import VERSION

BASE='http://127.0.0.1:8765'


def stress_fixture():
    """Keep the conflict legible inside a realistic volume of unrelated chat."""
    sample = json.loads((ROOT/'data/samples/compact-conduct.json').read_text())
    sample['title'] = '合成大样本：退款争议与活动通知'
    for index in range(42):
        sample['messages'].append({
            'id': f'N{index+1}', 'speaker': f'志愿者{index%5+1}',
            'timestamp': f'2026-11-14T09:{index:02d}:00+08:00',
            'text': f'活动准备第{index+1}项已在共享清单登记。请负责现场签到的同学对照座位、材料和物资列表，届时以当天的场地通知为准。',
        })
    for index in range(15):
        sample['messages'].append({
            'id': f'I{index+1}', 'speaker': '场地联络人',
            'timestamp': f'2026-11-14T10:{index:02d}:00+08:00',
            'text': f'活动准备的第{index+1}张场地通知。', 'image_fixture': True,
            'synthetic_image_lines': ['SYNTHETIC VENUE NOTICE', f'Checklist attachment {index+1:02d}',
                                      'Workshop setup: chairs and registration desk.'],
        })
    return sample


def api(path,body=None):
    headers={}
    if body is not None:headers={'Content-Type':'application/json','X-Chigua-Token':api('/api/config')['token']}
    req=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=300) as r:return json.load(r)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample',choices=['chronology','parallel','image','conduct','stress','readings','prehistory'])
    parser.add_argument('--inject-local-failure',action='store_true')
    args=parser.parse_args()
    records=ROOT/'data/private/compact-eval';records.mkdir(parents=True,exist_ok=True)
    manifests=list(records.glob(VERSION+'-*.json'))
    spent=sum(sum(usage_summary(ROOT/'data/runs'/json.loads(p.read_text())['run_id'])[k] for k in ['input_tokens','output_tokens']) for p in manifests)
    if spent>=24000:raise SystemExit('This version reached its synthetic suite token threshold; no request sent.')
    output=records/(VERSION+'-'+args.sample+'.json')
    if output.exists():raise SystemExit('This sample already has a recorded run; inspect it rather than re-pay automatically.')
    config=api('/api/config');assert config['model']['provider']=='deepseek' and config['model']['available']
    fixture=stress_fixture() if args.sample=='stress' else json.loads((ROOT/'data/samples'/('compact-'+args.sample+'.json')).read_text())
    messages=fixture['messages']
    for message in messages:
        if not message.pop('image_fixture',False):
            continue
        from PIL import Image,ImageDraw
        im=Image.new('RGB',(850,300),'white');draw=ImageDraw.Draw(im)
        lines = message.pop('synthetic_image_lines', None) or fixture['synthetic_image_lines']
        for i,line in enumerate(lines):draw.text((24,20+53*i),line,font_size=29,fill='black')
        buf=io.BytesIO();im.save(buf,format='PNG')
        asset=api('/api/upload',{'name':'synthetic-notice.png','data':base64.b64encode(buf.getvalue()).decode()})
        message['image']=asset['image']
    case=api('/api/cases',{'title':fixture['title'],'question':fixture['question'],'messages':messages,
                          'source_note':'完全虚构的流程验证材料；未展示的资料不可补造。'})
    limits = {'max_requests':10,'max_total_tokens':42000} if args.sample=='stress' else {
        'max_requests':6,'max_total_tokens':min(16000,24000-spent)}
    job=api('/api/analyze',{'case_id':case['id'],'method':'B1',**limits})
    manifest={'sample':args.sample,'case_id':case['id'],'run_id':job['id'],
              'expected_private_oracle':fixture['expected_private_oracle'],'fault_injected':args.inject_local_failure}
    write_json(output,manifest)
    marker=ROOT/'data/runs'/job['id']/'editorial/compose.output.json'
    if args.inject_local_failure:marker.mkdir(parents=True)
    injected_done=False;previous=None
    while True:
        job=api('/api/jobs/'+job['id']);state=(job['status'],job.get('stage'))
        if state!=previous:print(json.dumps({'run_id':job['id'],'status':state[0],'stage':state[1],'usage':job.get('usage')},ensure_ascii=False),flush=True);previous=state
        if job['status']!='running':
            if args.inject_local_failure and not injected_done and job['status']=='failed' and marker.is_dir() and 'compose.output.json' in job.get('error',''):
                manifest['before_resume_usage']=job['usage'];write_json(output,manifest)
                assert job['usage']['completed_requests']==job['usage']['requests']
                marker.rmdir();job=api('/api/resume',{'job_id':job['id']});injected_done=True;continue
            break
        time.sleep(2)
    manifest.update(status=job['status'],usage=job.get('usage'),error=job.get('error',''))
    if job['status']=='completed':
        assert job['result']['origin']=='live_model' and job['result']['editorial_workflow']==VERSION
        before=job['usage'];duplicate=api('/api/analyze',{'case_id':case['id'],'method':'B1','max_requests':6})
        assert duplicate['id']==job['id'] and duplicate['usage']==before
        manifest['duplicate_new_requests']=0
        manifest['url']=BASE+'/report/'+job['id']+'/html'
        with urllib.request.urlopen(manifest['url']) as r:html=r.read()
        artifact=ROOT/'output'/('compact-'+args.sample+'.html');artifact.parent.mkdir(exist_ok=True)
        artifact.write_bytes(html);artifact.chmod(0o600);manifest['html']=str(artifact)
    write_json(output,manifest)
    print(json.dumps(manifest,ensure_ascii=False),flush=True)
    if job['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
