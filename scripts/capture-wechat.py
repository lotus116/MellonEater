"""Explicitly capture one group/time window, save locally, never analyze automatically."""
import argparse
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA,fingerprint,now,write_json
from chigua.pipeline import save_case
from chigua.wechat import capture

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--conversation',required=True,help='精确群 ID，不接受模糊群名')
p.add_argument('--start',required=True,help='含时区的起始时间，例如 2026-11-01T00:00:00+08:00')
p.add_argument('--end',required=True,help='含时区的结束时间（包含边界）')
p.add_argument('--limit',type=int,default=500)
p.add_argument('--title',default='微信指定范围采集')
args=p.parse_args()
os.umask(0o077)
try:
    messages,pages,metadata=capture(args.conversation,args.start,args.end,args.limit)
    cid=uuid.uuid4().hex
    folder=DATA/'private'/'captures'/cid
    for index,page in enumerate(pages,1):write_json(folder/f'page-{index:03}.json',page)
    write_json(folder/'capture.json',metadata)
    state='指定窗口查询已结束' if metadata['window_query_complete'] else '查询有缺口或仍有后续页'
    note=(f'本机指定群采集；{args.start} 至 {args.end}；{state}。'
        f'未解码消息 {metadata["unsupported_messages"]} 条。未自动获取图片、音频或展开合并转发；'
        '只反映此 Mac 已有记录。完整分页原始结果仅存于本机。')
    case={'id':cid,'title':args.title,'created_at':now(),'source_note':note,'messages':messages,
        'identity':'旁观者','question':'根据所选范围还原事件，注意材料缺口。','input_hash':fingerprint(messages),
        'capture':metadata}
    save_case(case)
    print(f'本地保存 {len(messages)} 条材料；未发送给模型。')
    print(f'http://127.0.0.1:8765/?case={cid}')
except (ValueError,RuntimeError) as e:raise SystemExit(str(e))
