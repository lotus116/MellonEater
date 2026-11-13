from __future__ import annotations
import json
import plistlib
import shutil
import subprocess
from pathlib import Path
from .core import ROOT


def probe():
    p = Path('/Applications/WeChat.app/Contents/Info.plist')
    version = None
    if p.exists():
        version = plistlib.loads(p.read_bytes()).get('CFBundleShortVersionString')
    return {'platform': 'macOS', 'wechat_version': version,
        'direct_history': 'not_connected', 'greenbubbles_installed': bool(shutil.which('greenbubbles')),
        'ocr_available': (ROOT/'tmp'/'ocr').exists(),
        'message': '支持导入文字、规范 JSON 和截图。微信历史自动读取尚未连接。'}


def ocr(path):
    binary = ROOT/'tmp'/'ocr'
    if not binary.exists():
        return [], '本地文字识别尚未就绪；原图已保存，可由视觉模型分析。'
    try:
        result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=90)
        if result.returncode:raise ValueError('OCR failed')
        lines = json.loads(result.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return [], '本地文字识别失败；保留原图，不能视为没有内容。'
    return lines, '截图文字由本地 OCR 提取；发言者、引用和时间需结合原图核对。'
