"""Bind locally decoded images to exact scoped messages, never by nearby timestamps."""
from pathlib import Path
import hashlib
import os
import uuid
from .core import write_json
from .wechat import group_id,window
from .wechat_io import WeChatReadError

MAX_IMAGE_BYTES=32*1024*1024


def envelope(value,operation):
    if (not isinstance(value,dict) or value.get('schema')!='greenbubbles.attachment.v1'
        or value.get('formatVersion')!=1 or value.get('operation')!=operation
        or value.get('ok') is not True or value.get('kind')!='image'):
        raise ValueError('图片工具返回了不匹配的响应。')


def attach_images(messages,metadata,client,folder,uploads,*,max_images=300,progress=None):
    """Missing media stays as a visible gap. Integrity/scope failures stop the run."""
    from datetime import datetime
    from PIL import Image,UnidentifiedImageError
    group=group_id(metadata['conversation_id']);since,until=window(metadata['start'],metadata['end'])
    if not 1<=max_images<=1000:raise ValueError('图片上限必须为 1 至 1000。')
    selected=[]
    for m in messages:
        ref=m.get('source_reference') or {}
        stamp=datetime.fromisoformat(m['timestamp']).timestamp()
        if (ref.get('conversation_id')!=group or ref.get('source_identity')!=metadata['source_identity']
            or not since<=stamp<=until):raise ValueError('图片关联越过本次采集范围，已停止。')
        if ref.get('content_kind')=='Image' or ref.get('message_type')==3:selected.append(m)
    folder=Path(folder);uploads=Path(uploads)
    for p in [folder,uploads]:
        if p.is_symlink():raise ValueError('图片输出目录不能是符号链接。')
        p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
    summary={'requested':len(selected),'available':0,'unavailable':0,'limit_reached':0}
    records=[]
    for index,m in enumerate(selected):
        ref=m['source_reference'];record={'message_id':ref['message_id'],'local_id':m['id'],'status':'pending'}
        if index>=max_images:
            record['status']='limitReached';summary['limit_reached']+=1
            m['text']='[图片消息：超过本次图片数量上限，尚未读取。]'
        else:
            if progress:progress(index+1,len(selected))
            args=['--conversation',group,'--message',ref['message_id'],'--kind','image']
            raw=folder/(uuid.uuid4().hex+'.original')
            try:
                inspected=client.run(['attachment','inspect',*args]);envelope(inspected,'attachment.inspect')
                if inspected.get('availability')!='downloaded':raise WeChatReadError('notDownloaded')
                aid=inspected.get('preferredAttachmentId')
                if not isinstance(aid,str) or not aid:raise ValueError('图片缺少与消息绑定的附件编号。')
                size=inspected.get('preferredSourceByteCount')
                if type(size) is not int or size>MAX_IMAGE_BYTES:raise WeChatReadError('imageTooLarge')
                result=client.run(['attachment','materialize',*args,'--attachment',aid,'--output',str(raw.resolve())],timeout=90)
                envelope(result,'attachment.materialize')
                if raw.is_symlink() or not raw.is_file() or raw.stat().st_size>MAX_IMAGE_BYTES:
                    raise ValueError('图片输出文件无效或超过大小限制。')
                blob=raw.read_bytes();digest=hashlib.sha256(blob).hexdigest()
                if (result.get('attachmentId')!=aid or result.get('decodedByteCount')!=len(blob)
                    or result.get('decodedSha256')!=digest):raise ValueError('图片与附件响应不一致，已停止关联。')
                raw.chmod(0o600)
                with Image.open(raw) as img:
                    if img.width*img.height>40_000_000:raise WeChatReadError('imageTooLarge')
                    img.load();width,height=img.size;animated=getattr(img,'n_frames',1)>1
                    suffix='.jpg' if img.format=='JPEG' else '.png'
                    name=uuid.uuid4().hex+suffix;preview=uploads/name
                    if img.format in ['JPEG','PNG'] and not animated:
                        with preview.open('xb') as f:f.write(blob)
                        converted=False
                    else:
                        img.seek(0);img.convert('RGB').save(preview,'PNG');converted=True
                preview.chmod(0o600)
                source_md5=inspected.get('sourceMd5')
                same=bool(source_md5) and hashlib.md5(blob).hexdigest()==source_md5
                record.update(status='available',attachment_id=aid,sha256=digest,bytes=len(blob),
                    width=width,height=height,image=name,source_md5_matches=same,
                    quality='sourceChecksumMatched' if same else 'originalResolutionUnverified',
                    preview_converted=converted,animated=animated,local_original=raw.name)
                m['image']=name;m['text']='[图片消息：本机图像已按原始消息编号关联，可查看图片。]'
                m['uncertainty']=' '.join(filter(None,[m.get('uncertainty'),
                    '' if same else '工具未证明这是原始分辨率；可能是本机缓存图或缩略图。',
                    '动态图片预览仅展示首帧，完整文件保留在本机。' if animated else '']))
                summary['available']+=1
            except WeChatReadError as exc:
                record.update(status='unavailable',reason=exc.code);summary['unavailable']+=1
                m['text']='[图片消息：本机暂未取得可用图像；不代表消息没有图片。]'
                m['uncertainty']=' '.join(filter(None,[m.get('uncertainty'),'图片缺口：'+exc.code]))
            except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
                record.update(status='unavailable',reason='imageFormatUnavailable');summary['unavailable']+=1
                m['text']='[图片消息：本机文件无法生成预览，原始记录已保留。]'
        ref['media']=record;records.append(record)
        write_json(folder/'manifest.json',{'summary':summary,'items':records})
    metadata['images']=summary
    metadata['image_association_complete']=summary['unavailable']==0 and summary['limit_reached']==0
    return summary
