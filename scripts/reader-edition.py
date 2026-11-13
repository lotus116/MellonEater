"""Add a separately logged reader edition without changing original research output."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA, READER_SCHEMA, READER_RULES, RULES, validate_reader, write_json, now
from chigua.pipeline import load_case
from chigua.server import get_run
from chigua.provider import generate

p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args()
run=get_run(args.run_id);case=load_case(run['case_id']);folder=DATA/'runs'/args.run_id
prompt=RULES+'\n'+READER_RULES+'\n本次仅输出 reader 对象本身，不要嵌套reader键。\n原始材料：\n'+json.dumps(case,ensure_ascii=False)+'\n已有分析（需要核对）：\n'+json.dumps(run['report'],ensure_ascii=False)+'\n输出 JSON 格式：\n'+json.dumps(READER_SCHEMA,ensure_ascii=False)
images=[m['image'] for m in case['messages'] if m.get('image')]
reader,stats=generate(prompt,READER_SCHEMA,folder,'reader',images)
validate_reader(reader,case['messages'])
write_json(folder/'reader.json',{'reader':reader,'created_at':now(),'trace':stats,'purpose':'presentation_only','original_run':run['id']})
print('Reader edition saved:',folder/'reader.json')
