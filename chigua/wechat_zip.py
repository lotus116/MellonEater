"""Import owner-selected native WeChat exports without database access or model calls.

Format observations: Dukou WeChatTranscriptRecord / WeChatAttachmentKind, 2026-11-14.
An export has minute timestamps and display names, not verified server message IDs.
"""
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid
import zipfile

from .core import fingerprint, normalize_messages, now
from .wechat import window

HEADER = re.compile(r'^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2})\n', re.M)
MARKER = re.compile(r'^\[(图片|圖片|photo|image)\]\s*(.*)$', re.I)
MEDIA_MARKER = re.compile(r'^\[(视频|影片|video|语音|語音|voice|文件|file|聊天记录|聊天記錄)\]', re.I)
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as f:
        f.write(data)


def transcript(text):
    text = text.lstrip('\ufeff').replace('\r\n', '\n')
    matches = list(HEADER.finditer(text))
    if not matches or matches[0].start() != 0:
        raise ValueError('未识别微信原生文字格式；请保留 ZIP 原文件，不要改名或手动拼接正文。')
    records = []
    for i, match in enumerate(matches):
        try:
            date = datetime.strptime(match[2], '%Y年%m月%d日 %H:%M').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
        except ValueError:
            raise ValueError('导出记录包含无效日期，已停止导入。') from None
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        records.append((match[1], date, text[match.end():end].strip(), text.count('\n', 0, match.start())+1))
    return records


def directory(archive):
    entries = archive.infolist()
    if not 1 <= len(entries) <= 5000 or sum(e.file_size for e in entries) > 512*1024*1024:
        raise ValueError('ZIP 文件数量或解压大小超过本地导入上限。')
    files = {}; seen = set()
    for entry in entries:
        name = entry.filename; path = PurePosixPath(name)
        parts = name.rstrip('/').split('/')
        canonical = unicodedata.normalize('NFC', name).casefold()
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (path.is_absolute() or any(p in ['', '.', '..'] for p in parts)
            or '\\' in name or ':' in name or any(ord(c) < 32 for c in name)
            or canonical in seen or mode not in [0, stat.S_IFREG, stat.S_IFDIR]
            or entry.flag_bits & 1 or entry.compress_type not in [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]):
            raise ValueError('ZIP 含有不安全路径、重复条目或不支持的压缩方式。')
        seen.add(canonical)
        if not entry.is_dir(): files[name] = entry
    return files


def native_texts(files):
    # Dukou merged archives retain originals in batches; never ingest root summary twice.
    batches = sorted(n for n in files if re.fullmatch(r'batches/\d{4}/聊天记录\.txt', n))
    if batches: return batches
    if '聊天记录.txt' in files: return ['聊天记录.txt']
    candidates = [n for n in files if PurePosixPath(n).name == '聊天记录.txt']
    if len(candidates) != 1:
        raise ValueError('ZIP 中没有唯一的「聊天记录.txt」；当前只支持已核对的原生中文导出格式。')
    return candidates


def image_path(reference, prefix, files):
    reference = reference.removeprefix('./')
    if not reference or PurePosixPath(reference).is_absolute() or '..' in PurePosixPath(reference).parts:
        return None, 'missingImage'
    exact = prefix + reference
    if exact in files: return exact, None
    if '/' in reference: return None, 'missingImage'
    matches = [n for n in files if n.startswith(prefix) and PurePosixPath(n).name == reference
               and (prefix or not n.startswith('batches/'))]
    if len(matches) == 1: return matches[0], None
    return None, 'ambiguousImage' if matches else 'missingImage'


def preview(blob, uploads, originals, name):
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(blob)) as img:
            if img.width*img.height > 40_000_000: return None, 'imageTooLarge'
            img.load(); animated = getattr(img, 'n_frames', 1) > 1
            original = name+'.original'
            private_write(originals/original, blob)
            converted = img.format not in ['PNG', 'JPEG'] or animated
            ext = '.jpg' if img.format == 'JPEG' else '.png'
            if converted:
                output = BytesIO(); img.seek(0); img.convert('RGB').save(output, 'PNG'); rendered = output.getvalue()
            else: rendered = blob
            filename = name+ext
            private_write(uploads/filename, rendered)
            return {'image':filename, 'sha256':hashlib.sha256(blob).hexdigest(),
                    'width':img.width, 'height':img.height, 'animated':animated,
                    'preview_converted':converted, 'local_original':original,
                    'original_resolution_verified':False}, None
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None, 'imageFormatUnavailable'


def import_archives(paths, *, title, group_label, start, end, data):
    """Returns cases split at demo limits. No guessed deduplication or completeness."""
    since, until = window(start, end)
    if not title.strip() or not group_label.strip(): raise ValueError('请填写标题和所选群名。')
    if not 1 <= len(paths) <= 100: raise ValueError('一次请导入 1 至 100 个 ZIP。')
    data = Path(data); batch_id = uuid.uuid4().hex
    folder = data/'private'/'native-imports'/batch_id; uploads = data/'uploads'
    for p in [folder, uploads, data/'cases']:
        if p.is_symlink(): raise ValueError('本地输出目录不能是符号链接。')
        p.mkdir(parents=True, exist_ok=True, mode=0o700); p.chmod(0o700)
    rows = []; archives = []; seen_archives = set(); duplicate_archives = 0; outside = 0
    images = Counter(); unsupported = 0
    for path in paths:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE: raise ValueError('ZIP 不存在或大于 256 MB。')
        blob = path.read_bytes()
        if len(blob) > MAX_ARCHIVE: raise ValueError('ZIP 大于 256 MB。')
        digest = hashlib.sha256(blob).hexdigest()
        if digest in seen_archives: duplicate_archives += 1; continue
        seen_archives.add(digest)
        try:
            with zipfile.ZipFile(BytesIO(blob)) as archive:
                files = directory(archive)
                for source in native_texts(files):
                    if files[source].file_size > 4*1024*1024: raise ValueError('单份聊天文字超过 4 MB。')
                    text = archive.read(files[source]).decode('utf-8-sig')
                    records = transcript(text)
                    parent = str(PurePosixPath(source).parent)
                    prefix = '' if parent == '.' else parent+'/'
                    for index, (speaker, date, body, line) in enumerate(records):
                        if not since <= date.timestamp() <= until: outside += 1; continue
                        mid = 'Z'+hashlib.sha256(f'{digest}:{source}:{index}'.encode()).hexdigest()[:24]
                        ref = {'provider':'wechat-native-export','archive_sha256':digest,
                               'transcript':source,'record_index':index,'line':line,
                               'time_precision':'minute','timezone_assumption':'Asia/Hong_Kong',
                               'group_asserted_by_user':group_label,'original_message_id_available':False}
                        row = {'id':mid,'speaker':speaker,'timestamp':date.isoformat(),
                               'text':body or '[此导出条目没有可解析正文。]',
                               'source_kind':'微信原生导出（用户手动选取）','source_name':'手动导出 / '+group_label,
                               'source_reference':ref,'unit':'导出条目',
                               'uncertainty':'导出时间精确到分钟，按香港时间解释；显示名不等于已核实身份。'}
                        media = []; image_rows = []
                        for content_line in body.splitlines():
                            match = MARKER.fullmatch(content_line.strip())
                            if not match:
                                if MEDIA_MARKER.match(content_line.strip()): unsupported += 1
                                continue
                            images['requested'] += 1
                            target, error = image_path(match[2], prefix, files)
                            result = None
                            if target:
                                if files[target].file_size > MAX_IMAGE: error = 'imageTooLarge'
                                else:
                                    result, error = preview(archive.read(files[target]), uploads, folder/'media', uuid.uuid4().hex)
                            item = {'reference':match[2], 'archive_path':target,
                                    'status':'available' if result else 'unavailable','reason':error}
                            if result:
                                item.update(result); images['available'] += 1
                                if result['animated']: row['uncertainty'] += ' 动态图片预览为首帧。'
                                if not row.get('image'): row['image'] = result['image']
                                else:
                                    image_rows.append({**row,'id':mid+f'.i{len(media)+1}', 'parent_id':mid,
                                        'text':'[同一导出条目的附图]','image':result['image'],
                                        'source_reference':{**ref,'attachment_reference':match[2]}})
                            else:
                                images['unavailable'] += 1; row['uncertainty'] += ' 图片缺口：'+str(error)+'。'
                            media.append(item)
                        ref['media'] = media
                        rows.append(row); rows.extend(image_rows)
                        if len(rows) > 20000: raise ValueError('本次导入超过 2 万条材料，请按日期分次导入。')
                # Retain only the explicitly supplied export; never search other local files.
                private_write(folder/(digest+'.zip'), blob)
                archives.append({'sha256':digest,'bytes':len(blob)})
        except (zipfile.BadZipFile, UnicodeError, NotImplementedError, RuntimeError):
            raise ValueError('ZIP 校验或文字解码失败，未发布案例；请保留原文件检查。') from None
    if not rows: raise ValueError('导出文件在指定时间内没有可解析条目；不能据此判断群里没有消息。')
    # Keep source ordering within each minute. Repeated text is not proof of duplicate messages.
    rows.sort(key=lambda r:r['timestamp'])
    duplicate_candidates = sum(n-1 for n in Counter((r['speaker'],r['timestamp'],r['text']) for r in rows if not r.get('parent_id')).values() if n>1)
    notes = ('用户手动选择导出的片段；群名由用户指定，导出不提供可验证群 ID。不能据此证明三天完整覆盖。'
             '时间精确到分钟，按香港时间解释；同分钟保持文件顺序，不推断跨批次先后。图片按文件引用对应，不保证原始分辨率。'
             '未解码语音、视频、文件或嵌套转发仅保留原文字标记；重复候选保留待核对。未自动发送给模型。')
    meta = {'provider':'wechat-native-export','start':start,'end':end,'archives':archives,
            'duplicate_archives_skipped':duplicate_archives,'duplicate_candidates_retained':duplicate_candidates,
            'out_of_window_excluded':outside,'images':dict(images),'unsupported_markers':unsupported,
            'window_query_complete':False,'cloud_analysis_started':False,'import_batch_id':batch_id}
    # Keep each parent and its images together across demo-sized cases.
    groups = []
    for row in rows:
        if row.get('parent_id') and groups and groups[-1][0]['id'] == row['parent_id']: groups[-1].append(row)
        else: groups.append([row])
    chunks = []; chunk = []; chars = 0
    for group in groups:
        size = sum(len(r['text']) for r in group)
        if len(group)>2000 or size>150000: raise ValueError('单个导出条目过大，请缩小材料范围。')
        if chunk and (len(chunk)+len(group)>2000 or chars+size>150000): chunks.append(chunk); chunk=[]; chars=0
        chunk.extend(group); chars += size
    if chunk: chunks.append(chunk)
    cases = []
    for i, chunk in enumerate(chunks, 1):
        normalized = normalize_messages(chunk)
        cases.append({'id':uuid.uuid4().hex,'title':title+(f' · 第 {i}/{len(chunks)} 包' if len(chunks)>1 else ''),
                      'created_at':now(),'messages':normalized,'source_note':notes,'capture':meta,
                      'question':'还原主要事件和转折，保留手动选取范围与图文缺口。','identity':'旁观者',
                      'input_hash':fingerprint(normalized)})
    manifest = {**meta,'cases':[c['id'] for c in cases],'materials':len(rows)}
    private_write(folder/'manifest.json', json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    for case in cases:
        private_write(data/'cases'/(case['id']+'.json'),json.dumps(case,ensure_ascii=False,indent=2).encode())
    return cases, manifest
