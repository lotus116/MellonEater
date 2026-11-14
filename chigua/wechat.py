"""Bounded, local-only adapter for an independently initialized GreenBubbles CLI.

No setup, key extraction, contact enumeration, or model calls.
Contract source: GreenBubbles query.v1 / live_query.rs, checked 2026-11-14.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import subprocess
from .core import normalize_messages
from .wechat_io import GreenBubbles


def window(start, end):
    values=[]
    for value in [start,end]:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:raise ValueError('起止时间必须包含时区，例如 +08:00。')
        values.append(int(date.timestamp()))
    if not 0 <= values[1]-values[0] <= 31*86400:
        raise ValueError('请指定不超过 31 天的有效时间范围。')
    return values


def group_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}@chatroom',value):
        raise ValueError('需要精确的群 ID（以 @chatroom 结尾），不能使用模糊群名。')
    return value


def decode_page(page, conversation, since, until):
    group_id(conversation)
    if (not isinstance(page,dict) or page.get('schema')!='greenbubbles.query.v1'
        or page.get('formatVersion')!=1 or page.get('operation')!='messages.list'
        or page.get('ok') is not True):
        raise ValueError('不是受支持的 GreenBubbles messages.list 完整 JSON。')
    items=page.get('items');paging=page.get('page',{})
    if not isinstance(items,list) or len(items)>500 or paging.get('returned')!=len(items):
        raise ValueError('消息页数量与声明不一致。')
    if not isinstance(paging.get('hasMore'),bool):raise ValueError('缺少分页完整性标记。')
    if paging['hasMore'] and not isinstance(paging.get('nextCursor'),str):
        raise ValueError('后续页缺少有效游标。')
    source=page.get('source',{}).get('identity')
    if not isinstance(source,str) or not source:raise ValueError('缺少来源标识。')
    rows=[];unsupported=0
    for item in items:
        if item.get('conversationId')!=conversation:raise ValueError('返回内容越过指定群范围，已停止导入。')
        stamp=item.get('createdAtUnix')
        if type(stamp) is not int or not since<=stamp<=until:
            raise ValueError('返回消息越过时间范围或时间无效，已停止导入。')
        original=item.get('id')
        if not isinstance(original,str) or not original:raise ValueError('消息缺少原始编号。')
        content=item.get('content');notes=[];text=None;kind='Unknown'
        if isinstance(content,dict) and len(content)==1:
            kind,value=next(iter(content.items()))
            if kind in ['Text','System','Revoke'] and isinstance(value,str):text=value
            elif kind=='Image':text='[图片消息：尚未读取本机图像。]'
        if text is None or not text.strip():
            unsupported+=1;text='[此消息尚未解码；请在微信核对引用、合并转发或媒体原文。]'
            notes.append('原始载荷留在本机采集记录中；此占位不代表消息没有内容。')
        if item.get('contentTruncated') is not False:notes.append('正文可能被截断或截断状态未知。')
        ref=hashlib.sha256(json.dumps([source,conversation,original]).encode()).hexdigest()
        rows.append({'id':'W'+ref[:24],'speaker':str(item.get('senderDisplayName') or item.get('sender') or '身份未知'),
            'text':text,'timestamp':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
            'source_kind':'微信本地数据库（GreenBubbles）','source_name':'指定群 / 指定时间范围',
            'source_reference':{'provider':'greenbubbles','source_identity':source,'conversation_id':conversation,'message_id':original,
                'sender_id':item.get('sender'),'sort_sequence':item.get('sortSequence'),
                'server_id':item.get('serverId'),'message_type':item.get('messageType'),'content_kind':kind,
                'decode_state':item.get('contentDecodeState'),'content_truncated':item.get('contentTruncated')},
            'unit':'消息','uncertainty':' '.join(notes)})
    complete=page.get('consistency',{}).get('coverageComplete') is True
    warnings=page.get('warnings')
    return rows,{'source':source,'has_more':paging['hasMore'],'cursor':paging.get('nextCursor'),
        'coverage_complete':complete,'warning_count':len(warnings) if isinstance(warnings,list) else 1,
        'unsupported':unsupported}


def capture(conversation,start,end,max_messages=500,*,client=None):
    """Explicit CLI action only. Returns scoped pages for local storage and review."""
    group_id(conversation);since,until=window(start,end)
    if type(max_messages) is not int or not 1<=max_messages<=2000:raise ValueError('每次最多获取 2000 条消息。')
    client=client or GreenBubbles()
    rows=[];pages=[];seen={};cursors=set();cursor=None;source=None;infos=[]
    for _ in range(20):
        args=['messages','list','--conversation',conversation,'--since',str(since),'--until',str(until),
              '--limit',str(min(200,max_messages-len(rows))),'--json']
        if cursor:args+=['--cursor',cursor]
        page=client.run(args)
        batch,info=decode_page(page,conversation,since,until)
        if source and source!=info['source']:raise ValueError('分页期间数据来源变化，已停止导入。')
        source=info['source']
        for row in batch:
            if row['id'] in seen:
                if seen[row['id']]!=row:raise ValueError('分页期间同一消息发生变化，已停止导入。')
                continue
            seen[row['id']]=row;rows.append(row)
        if len(rows)>max_messages:raise ValueError('工具返回数量超过指定限制。')
        if sum(len(r['text']) for r in rows)>150000:raise ValueError('材料超过 demo 的 15 万字符限制，请缩小范围。')
        pages.append(page);infos.append(info)
        if not info['has_more'] or len(rows)>=max_messages:break
        cursor=info['cursor']
        if not cursor or cursor in cursors:raise ValueError('分页游标未前进，已停止导入。')
        cursors.add(cursor)
    if not rows:raise ValueError('指定范围没有可导入消息；不能据此认定历史记录不存在。')
    # The source order is newest first; reverse so ties retain the source's order.
    messages=normalize_messages(list(reversed(rows)))
    complete=all(i['coverage_complete'] and not i['warning_count'] for i in infos) and not infos[-1]['has_more']
    metadata={'provider':'greenbubbles','source_identity':source,'conversation_id':conversation,'start':start,'end':end,
        'pages':len(pages),'returned':len(messages),'window_query_complete':complete,
        'has_more':infos[-1]['has_more'],'unsupported_messages':sum(i['unsupported'] for i in infos),
        'warning_count':sum(i['warning_count'] for i in infos),'cloud_analysis_started':False}
    return messages,pages,metadata


def capture_to_case(conversation,start,end,*,client=None,title='微信指定范围采集',max_messages=2000,
                    include_images=True,max_images=300,progress=None):
    import os,uuid
    from .core import DATA,fingerprint,now,write_json
    from .pipeline import save_case
    from .wechat_media import attach_images
    os.umask(0o077);client=client or GreenBubbles()
    messages,pages,metadata=capture(conversation,start,end,max_messages,client=client)
    cid=uuid.uuid4().hex;folder=DATA/'private'/'captures'/cid
    folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    for index,page in enumerate(pages,1):write_json(folder/f'page-{index:03}.json',page)
    write_json(folder/'capture.json',metadata)
    try:
        if include_images:attach_images(messages,metadata,client,folder/'media',DATA/'uploads',max_images=max_images,progress=progress)
    except Exception:
        write_json(folder/'failure.json',{'status':'image_association_failed','cloud_analysis_started':False})
        raise
    write_json(folder/'capture.json',metadata)
    state='指定窗口查询已结束' if metadata['window_query_complete'] else '查询有缺口或仍有后续页'
    media=metadata.get('images',{})
    note=(f'本机指定群采集；{start} 至 {end}；{state}。未解码消息 {metadata["unsupported_messages"]} 条。'
          f'图片已关联 {media.get("available",0)} 张，未取得 {media.get("unavailable",0)} 张，超过上限 {media.get("limit_reached",0)} 张。'
          '不保证图片均为原始分辨率；未展开的转发、音频等明确保留为缺口。只反映此 Mac 已有记录，未自动发送给模型。')
    case={'id':cid,'title':title,'created_at':now(),'source_note':note,'messages':messages,
          'identity':'旁观者','question':'根据所选范围还原事件，注意图文来源及材料缺口。',
          'input_hash':fingerprint(messages),'capture':metadata}
    save_case(case)
    return case
