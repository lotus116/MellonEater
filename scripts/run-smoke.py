"""Run prepared synthetic variants; expectations never enter model input."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA,write_json
from chigua.pipeline import JOBS,load_case,run_pipeline

p=argparse.ArgumentParser()
p.add_argument('--provider',choices=['codex','deepseek','api'],required=True)
p.add_argument('--model')
p.add_argument('--method',choices=['B0','B1','B2','A1'],default='B1')
args=p.parse_args()
os.environ['CHIGUA_PROVIDER']=args.provider
if args.model:os.environ['CHIGUA_MODEL']=args.model
manifest_path=DATA/'private/smoke-manifest.json'
if not manifest_path.exists():raise SystemExit('先运行 scripts/prepare-variants.py。')
manifest=json.loads(manifest_path.read_text())
for variant in manifest['variants']:
    rid=uuid.uuid4().hex
    JOBS[rid]={'id':rid,'status':'running'}
    print(variant['variant'],rid,flush=True)
    run_pipeline(rid,load_case(variant['case_id']),args.method)
    variant.update(run_id=rid,run_status=JOBS[rid]['status'],method=args.method)
    write_json(manifest_path,manifest)
    print(JOBS[rid]['status'],JOBS[rid].get('error',''),flush=True)
