"""Re-edit a completed run through the same reviewed workflow as new analyses."""
import argparse,json,sys,shutil,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA, write_json
from chigua.pipeline import load_case
from chigua.editor import edit_report


def main():
    p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args()
    if not args.run_id.isalnum():raise SystemExit('运行编号无效。')
    folder=DATA/'runs'/args.run_id
    run=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    snapshot=folder/'input.json'
    case=json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.exists() else load_case(run['case_id'])
    original=folder/'analysis_report.json'
    analysis=json.loads(original.read_text(encoding='utf-8')) if original.exists() else run['report']
    edition_folder=folder/'editions'/uuid.uuid4().hex
    result=edit_report(case,analysis,edition_folder,lambda stage:print(stage,flush=True))
    # A failed revision never changes the currently published edition.
    if (folder/'reader.json').exists():shutil.copy2(folder/'reader.json',edition_folder/'previous-reader.json')
    result['original_run']=run['id']
    write_json(folder/'reader.json',result)
    print('Reader edition saved:',folder/'reader.json')


if __name__=='__main__':main()
