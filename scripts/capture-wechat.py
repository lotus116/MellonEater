"""Explicit capture of one group/time window with message-bound local images."""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.wechat import capture_to_case
from chigua.wechat_io import GreenBubbles


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--conversation',required=True,help='精确群 ID')
    p.add_argument('--start',required=True,help='含时区的起始时间')
    p.add_argument('--end',required=True,help='含时区的结束时间（包含边界）')
    p.add_argument('--limit',type=int,default=2000)
    p.add_argument('--max-images',type=int,default=300)
    p.add_argument('--text-only',action='store_true')
    p.add_argument('--title',default='微信指定范围采集')
    p.add_argument('--binary',type=Path);p.add_argument('--source-root',type=Path);p.add_argument('--credential-file',type=Path)
    args=p.parse_args();os.umask(0o077)
    client=GreenBubbles(args.binary,args.source_root,args.credential_file)
    case=capture_to_case(args.conversation,args.start,args.end,client=client,title=args.title,
        max_messages=args.limit,include_images=not args.text_only,max_images=args.max_images,
        progress=lambda n,total:print(f'本地关联图片 {n}/{total}',flush=True))
    print(f'本地保存 {len(case["messages"])} 条材料；未发送给模型。')
    print(f'http://127.0.0.1:8765/?case={case["id"]}')


if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError) as e:raise SystemExit(str(e))
