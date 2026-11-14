"""Explicit owner-confirmed image supplements; existing evidence stays immutable."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
import uuid
from .core import fingerprint, normalize_messages, now
from .wechat_zip import private_write, preview

MAX_ASSET=8*1024*1024
ID=re.compile(r'[0-9a-f]{32}')


def _directory(data, path):
    data=Path(data);path=Path(path)
    current=data
    for part in [None,*path.relative_to(data).parts]:
        if part is not None:current=current/part
        if current.is_symlink():raise ValueError('本地补图目录不能是符号链接。')
        current.mkdir(exist_ok=True,parents=True,mode=0o700)
        if not current.is_dir():raise ValueError('本地补图目录无效。')
        current.chmod(0o700)
    return path


def _regular(path, root):
    path=Path(path);root=Path(root)
    current=root
    if current.is_symlink():raise ValueError('补图存储路径无效。')
    for part in path.relative_to(root).parts:
        current=current/part
        if current.is_symlink():raise ValueError('补图文件不能是符号链接。')
    if not path.is_file():raise ValueError('补图文件不存在，请重新上传。')
    return path


def store_asset(raw:bytes,data)->dict:
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_ASSET:
        raise ValueError('每张补图需要大于 0 且不超过 8 MB。')
    if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):
        raise ValueError('补图仅支持 PNG 或 JPG，请另存图片后重试。')
    data=Path(data);asset_id=uuid.uuid4().hex
    folder=_directory(data,data/'private'/'supplements'/asset_id)
    uploads=_directory(data,data/'uploads')
    result,error=preview(raw,uploads,folder,asset_id)
    if not result:
        raise ValueError('图片超过像素上限或无法读取，请保存为 PNG 或 JPG 后重试。')
    rendered=_regular(uploads/result['image'],data).read_bytes()
    asset={**result,'id':asset_id,'created_at':now(),'bytes':len(raw),
           'preview_sha256':hashlib.sha256(rendered).hexdigest()}
    private_write(folder/'asset.json',json.dumps(asset,ensure_ascii=False,indent=2).encode())
    return asset


def _asset(asset_id,data):
    if not isinstance(asset_id,str) or not ID.fullmatch(asset_id):raise ValueError('补图编号无效。')
    folder=data/'private'/'supplements'/asset_id
    path=_regular(folder/'asset.json',data)
    if path.stat().st_size>16384:raise ValueError('补图元数据无效。')
    try:asset=json.loads(path.read_text())
    except (ValueError,UnicodeError):raise ValueError('补图元数据无效。') from None
    if (not isinstance(asset,dict) or asset.get('id')!=asset_id or
        asset.get('image') not in [asset_id+'.png',asset_id+'.jpg'] or
        asset.get('local_original')!=asset_id+'.original'):
        raise ValueError('补图元数据与文件不一致。')
    original=_regular(folder/(asset_id+'.original'),data)
    rendered=_regular(data/'uploads'/asset['image'],data)
    if not 0<original.stat().st_size<=MAX_ASSET or original.stat().st_size!=asset.get('bytes'):
        raise ValueError('补图原文件大小不一致，请重新上传。')
    if rendered.stat().st_size>160*1024*1024:raise ValueError('补图预览超过处理上限。')
    if (hashlib.sha256(original.read_bytes()).hexdigest()!=asset.get('sha256') or
        hashlib.sha256(rendered.read_bytes()).hexdigest()!=asset.get('preview_sha256')):
        raise ValueError('补图文件校验失败，请重新上传。')
    return asset


def clone_with_images(case,bindings,data)->dict:
    if not isinstance(bindings,list) or not 1<=len(bindings)<=100:
        raise ValueError('请逐条选择并确认 1 至 100 张补图。')
    data=Path(data);result=copy.deepcopy(case)
    rows=result['messages'];lookup={m['id']:m for m in rows};used=set();prepared=[]
    # Validate every target and asset before mutating the clone or publishing it.
    for binding in bindings:
        if not isinstance(binding,dict) or binding.get('confirmed') is not True:
            raise ValueError('请先确认图片与这条原文对应。')
        mid=binding.get('message_id');index=binding.get('media_index');kind=binding.get('kind')
        if not isinstance(mid,str) or mid not in lookup or type(index) is not int or index<0:
            raise ValueError('待补图片条目不存在。')
        row=lookup[mid];media=(row.get('source_reference') or {}).get('media',[])
        if row.get('parent_id') or index>=len(media) or not isinstance(media[index],dict) or media[index].get('status')!='unavailable':
            raise ValueError('只能为尚未取得的原始图片条目补图。')
        if (mid,index) in used:raise ValueError('同一图片条目不能重复绑定。')
        if kind not in ['saved_image','screenshot']:raise ValueError('请选择另存图片或截图来源。')
        asset=_asset(binding.get('asset_id'),data)
        used.add((mid,index));prepared.append((row,index,kind,asset))
    additions=[];existing_ids=set(lookup);created_at=now()
    for row,index,kind,asset in prepared:
        ref=row['source_reference'];item=ref['media'][index]
        supplement={'kind':kind,'method':'user_confirmed','asset_id':asset['id'],
                    'confirmed_at':created_at,'original_missing_reason':item.get('reason')}
        item.update({k:asset[k] for k in ('image','sha256','width','height','animated','preview_converted')})
        item.update(status='available',reason=None,origin='user_supplement',supplement=supplement,
                    original_resolution_verified=False)
        note='后补图片由用户确认对应；未独立核实为同一原图。'+('此附件为截图，可能包含裁剪或缩放。' if kind=='screenshot' else '')
        if not row.get('image'):
            row['image']=asset['image'];ref['supplement']=copy.deepcopy(supplement)
            row['uncertainty']=(row.get('uncertainty','')+' 原缺图说明为导入时的历史记录。'+note).strip()
        else:
            child_id='S'+uuid.uuid4().hex
            while child_id in existing_ids:child_id='S'+uuid.uuid4().hex
            existing_ids.add(child_id)
            child_ref={k:copy.deepcopy(v) for k,v in ref.items() if k not in ('media','supplement')}
            child_ref.update(attachment_reference=item.get('reference'),supplement=copy.deepcopy(supplement))
            additions.append({'id':child_id,'parent_id':row['id'],'speaker':row['speaker'],
                'timestamp':row.get('timestamp'),'forwarded_at':row.get('forwarded_at'),
                'source_root':row.get('source_root'),'source_name':row.get('source_name'),
                'source_kind':'用户后补截图' if kind=='screenshot' else '用户后补图片',
                'unit':'后补附图','text':'[用户确认对应的后补附图]','image':asset['image'],
                'source_reference':child_ref,'uncertainty':note})
    result['messages']=normalize_messages(rows+additions)
    image_counts={'requested':0,'available':0,'unavailable':0}
    for row in result['messages']:
        if row.get('parent_id'):continue
        for item in (row.get('source_reference') or {}).get('media',[]):
            image_counts['requested']+=1
            image_counts['available' if item.get('status')=='available' else 'unavailable']+=1
    result.setdefault('capture',{})['images']=image_counts
    result['id']=uuid.uuid4().hex;result['created_at']=created_at
    suffix=' · 补图版';title=str(case.get('title','材料'))
    while title.endswith(suffix):title=title[:-len(suffix)]
    result['title']=title[:100-len(suffix)]+suffix
    result['input_hash']=fingerprint(result['messages'])
    result['supplement']={'parent_case_id':case['id'],'created_at':created_at,
                          'binding_count':len(bindings),'requires_new_analysis':True,
                          'bindings':[{'message_id':r['id'],'media_index':i,'asset_id':a['id'],'kind':k} for r,i,k,a in prepared]}
    result['source_note']=(case.get('source_note','')+' 原导入缺图描述为历史记录；本次后补图由用户确认对应，未独立核实为同一原图。旧报告没有分析这些后补图片，请重新生成分析报告。').strip()
    # Do not carry cached analysis fields into a new evidence case.
    for key in ('runs','report','analysis','latest_run','latest_run_id'):result.pop(key,None)
    cases=_directory(data,data/'cases')
    private_write(cases/(result['id']+'.json'),json.dumps(result,ensure_ascii=False,indent=2).encode())
    return result
