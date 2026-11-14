"""Check explicitly selected exports locally; print counts without chat content."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.wechat_zip import inspect_archive

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives',nargs='+',type=Path)
    args=parser.parse_args()
    try:
        for index,path in enumerate(args.archives,1):
            print(json.dumps({'archive_number':index,**inspect_archive(path)},ensure_ascii=False))
        print('仅检查所选包：文件名对应成功不代表图片可解码；导入时再核对。没有图片文件时请重新导出，不能从文字标记恢复原图。')
    except (ValueError,OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc,ValueError) else '无法读取所选 ZIP，请检查文件权限。')
