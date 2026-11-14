"""Re-edit a completed run through the same reviewed workflow as new analyses."""
import argparse,json,sys,shutil,uuid,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA, write_json
from chigua.pipeline import load_case,worker_lock
from chigua import provider
from chigua.checkpoints import digest,media_hashes
from chigua.core import READER_RULES
from chigua.editor import VERSION
from chigua.editor import edit_report


def main():
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('--force',action='store_true');p.add_argument('--allow-uncertain',action='store_true');p.add_argument('--max-requests',type=int);args=p.parse_args()
    if not args.run_id.isalnum():raise SystemExit('运行编号无效。')
    folder=DATA/'runs'/args.run_id
    run=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    snapshot=folder/'input.json'
    case=json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.exists() else load_case(run['case_id'])
    original=folder/'analysis_report.json'
    analysis=json.loads(original.read_text(encoding='utf-8')) if original.exists() else run['report']
    key=digest({'case':case,'analysis':analysis,'config':provider.config_identity(),'version':VERSION,'rules':READER_RULES,
        'images':media_hashes([m['image'] for m in case['messages'] if m.get('image')],DATA)})
    edition_folder=folder/'editions'/(uuid.uuid4().hex if args.force else key)
    policy_file=edition_folder/'manifest.json'
    policy=json.loads(policy_file.read_text()) if policy_file.exists() else {'max_requests':20}
    if args.max_requests is not None:
        if not 4<=args.max_requests<=100 or (policy_file.exists() and args.max_requests<policy['max_requests']):raise SystemExit('请求上限无效。')
        policy['max_requests']=args.max_requests
    policy['retry_uncertain']=args.allow_uncertain
    write_json(policy_file,policy)
    fd=worker_lock()
    try:result=edit_report(case,analysis,edition_folder,lambda stage:print(stage,flush=True))
    finally:os.close(fd)
    # A failed revision never changes the currently published edition.
    if (folder/'reader.json').exists():shutil.copy2(folder/'reader.json',edition_folder/'previous-reader.json')
    result['original_run']=run['id']
    write_json(folder/'reader.json',result)
    print('Reader edition saved:',folder/'reader.json')


if __name__=='__main__':main()
