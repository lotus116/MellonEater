"""Local, explicitly selected WeChat ZIP import; never starts model analysis."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA
from chigua.wechat_zip import import_archives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='*', type=Path)
    parser.add_argument('--choose', action='store_true')
    parser.add_argument('--group'); parser.add_argument('--start'); parser.add_argument('--end')
    parser.add_argument('--title', default='微信手动导出材料')
    args = parser.parse_args(); os.umask(0o077)
    scope_file = DATA/'private'/'wechat-setup'/'scope.json'
    scope = json.loads(scope_file.read_text()) if scope_file.is_file() else {}
    group = args.group or scope.get('group_name')
    start = args.start or scope.get('start'); end = args.end or scope.get('end')
    if not all([group, start, end]):
        raise ValueError('需要指定群名和起止时间：--group 群名 --start 含时区时间 --end 含时区时间。')
    paths = args.archives
    if args.choose:
        script = '''set chosen to choose file with prompt "选择刚才手动导出的微信 ZIP（可多选）" of type {"public.zip-archive"} with multiple selections allowed
set resultPaths to ""
repeat with itemPath in chosen
set resultPaths to resultPaths & (POSIX path of itemPath) & linefeed
end repeat
return resultPaths'''
        result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, text=True)
        if result.returncode:
            print('未选择文件，未导入。'); return
        paths = [Path(p) for p in result.stdout.splitlines() if p]
    if not paths: raise ValueError('请选择或指定至少一个微信原生 ZIP。')
    print(f'限定群：{group}\n限定时间：{start} 至 {end}')
    print('正在本地解析所选 ZIP；不会发送给模型，也不会读取微信数据库。', flush=True)
    cases, manifest = import_archives(paths,title=args.title,group_label=group,start=start,end=end,data=DATA)
    count = manifest['images']
    print(f'已导入 {manifest["materials"]} 条材料，分为 {len(cases)} 包。')
    print(f'图片已对应 {count.get("available",0)} 张，未取得 {count.get("unavailable",0)} 张。')
    print(f'排除范围外条目 {manifest["out_of_window_excluded"]} 条；重复候选 {manifest["duplicate_candidates_retained"]} 条保留待核对。')
    print('手动选取不能证明三天记录完整；请核对首尾、分批边界和缺图。')
    print('双击 start.command 启动工作台后，打开：')
    for case in cases: print('http://127.0.0.1:8765/?case='+case['id'])


if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: raise SystemExit('\n已取消，未启动模型分析。')
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, ValueError) else '文件读写未完成，请检查本地文件权限。')
