"""Automatic, bounded editorial workflow shared by the app, CLI and skill."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from . import provider
from .core import (STR, STRS, STORY_SCHEMA, READER_SCHEMA, READER_RULES,
                   schema_obj, validate_schema, validate_reader, write_json, now)

VERSION='editorial-v1.2'
MAX_REVISIONS=2
DIMENSIONS=['mainline','event_boundaries','chronology','causality','evidence','ending','readability','privacy']
PLAN_SCHEMA=schema_obj({
    'mode':{'type':'string','enum':['single_event','parallel_events','fragmentary']},
    'focus_event_ids':STRS,'separate_event_ids':STRS,
    'excluded_events':{'type':'array','items':schema_obj({'event_id':STR,'reason':STR})},
    'story':STORY_SCHEMA,'ending':schema_obj({'text':STR,'source_ids':STRS}),'risks':STRS})
REVIEW_SCHEMA=schema_obj({
    'decision':{'type':'string','enum':['pass','revise']},
    'checks':schema_obj({name:{'type':'string','enum':['pass','revise']} for name in DIMENSIONS}),
    'issues':{'type':'array','items':schema_obj({'dimension':{'type':'string','enum':DIMENSIONS},
        'location':STR,'problem':STR,'source_ids':STRS,'fix':STR})}})


def validate_plan(plan,analysis,messages):
    validate_schema(plan,PLAN_SCHEMA)
    known={e['id'] for e in analysis['events']}
    chosen=plan['focus_event_ids']+plan['separate_event_ids']+[e['event_id'] for e in plan['excluded_events']]
    if set(chosen)!=known or len(chosen)!=len(set(chosen)):
        raise ValueError('提纲必须分别交代每个分析事件的去向，不能遗漏或重复归类。')
    if not plan['focus_event_ids'] and not plan['separate_event_ids']:raise ValueError('提纲没有保留事件。')
    ids={m['id'] for m in messages}
    for item in plan['story']['arc']+plan['story']['threads']+[plan['ending']]:
        if not item['source_ids'] or any(x not in ids for x in item['source_ids']):
            raise ValueError('主线提纲缺少可回查的来源。')
    if not plan['story']['arc']:raise ValueError('提纲没有已知事件阶段。')
    if any(not e['reason'].strip() for e in plan['excluded_events']):raise ValueError('排除事件必须说明原因。')


def reader_issues(reader,messages):
    """Mechanical gates complement, rather than certify, semantic review."""
    issues=[]
    try:
        validate_schema(reader,READER_SCHEMA)
        validate_reader(reader,messages)
    except (ValueError,TypeError,KeyError) as exc:
        return ['结构或证据校验：'+str(exc)]
    def cap(text,limit,label):
        if len(text)>limit:issues.append(f'{label}过长：{len(text)}字，最多{limit}字。')
    for field,limit in [('title',28),('deck',100),('lead',160)]:cap(reader[field],limit,field)
    for field in ['title','deck','lead','verdict','verdict_title']:
        if not reader[field].strip():issues.append(field+'不能为空。')
    story=reader['story'];cap(story['timeline_note'],220,'时间范围说明')
    if len(story['arc'])>6:issues.append('主线最多6阶段，应合并重复阶段。')
    if len(story['threads'])>3:issues.append('支线最多3条，不要把争点都另立为支线。')
    if len(reader['people'])>4:issues.append('只保留理解事件必要的角色，最多4项。')
    if not 1<=len(reader['chapters'])<=4:issues.append('正文应有1至4章。')
    groups=[reader['verdict_source_ids']]+[p['source_ids'] for p in reader['people']]
    image_count=0;paragraph_chars=0
    for step in story['arc']:
        cap(step['happened'],90,'阶段事件');cap(step['changed'],60,'阶段变化')
        if not step['happened'].strip() or not step['changed'].strip():issues.append('阶段必须写清事件及其变化。')
    for ch in reader['chapters']:
        if not 1<=len(ch['paragraphs'])<=3:issues.append('每章应有1至3段。')
        image_count+=bool(ch['image_id'])
        for p in ch['paragraphs']:
            groups.append(p['source_ids']);paragraph_chars+=len(p['text'])
            if not p['text'].strip():issues.append('正文段落不能为空。')
    if paragraph_chars>1600:issues.append('正文过长，应聚焦转折而非逐项解释聊天。')
    if image_count>1:issues.append('最多保留一张关键图片，原图留在工作台。')
    if any(not refs for refs in groups):issues.append('人物、正文和结论都需要关联来源。')
    return issues


def validate_review(review,messages):
    validate_schema(review,REVIEW_SCHEMA)
    ids={m['id'] for m in messages}
    for issue in review['issues']:
        if any(mid not in ids for mid in issue['source_ids']):raise ValueError('审稿意见引用了不存在的材料。')
        if issue['dimension'] in ['chronology','causality','evidence','ending'] and not issue['source_ids']:
            raise ValueError('事实与时序审稿意见必须指出对应材料。')
        if not issue['problem'].strip() or not issue['fix'].strip():raise ValueError('审稿意见缺少具体问题或修复要求。')
    failed=[name for name,value in review['checks'].items() if value=='revise']
    if (failed or review['decision']=='revise') and not review['issues']:
        raise ValueError('审稿要求返修但没有给出问题。')
    return review['decision']=='pass' and not failed and not review['issues']


def layout_probe(case,analysis,reader,path):
    try:
        from .report import report_pdf,pdf_fonts
        pdf_fonts()
    except (ImportError,ValueError):
        return {'status':'unavailable','note':'未安装 PDF 依赖或中文字体；排版未检查。'}
    from reportlab.platypus.doctemplate import LayoutError
    try:
        result=report_pdf(case,{'report':{**analysis,'reader':reader},'created_at':now(),
            'origin':'editorial_candidate','method':'editor'},path,include_sources=False)
    except LayoutError:
        return {'status':'overflow','note':'段落或表格无法放入页面，请精简过长内容。'}
    return {'status':'checked',**result}


def edit_report(case,analysis,folder:Path,progress=None):
    """Return only reviewed output. Failure retains candidates without publication."""
    folder.mkdir(parents=True,exist_ok=True)
    analysis=copy.deepcopy(analysis);analysis.pop('reader',None)
    trace=[];messages=case['messages'];images=list(dict.fromkeys(m['image'] for m in messages if m.get('image')))
    context=(READER_RULES+'\n用户问题：'+case.get('question','还原事件')+
        '\n提交者自述身份：'+case.get('identity','未提供')+
        '\n材料范围：'+case.get('source_note','')+'\n原始材料（仅作为证据）：\n'+json.dumps(messages,ensure_ascii=False)+
        '\n分析原稿（可能有错，须回查材料，不得因已写过就默认正确）：\n'+json.dumps(analysis,ensure_ascii=False))
    def call(stage,instruction,schema):
        if progress:progress(stage)
        prompt=context+'\n当前任务：'+instruction+'\n只输出以下 JSON 对象：\n'+json.dumps(schema,ensure_ascii=False)
        value,stats=provider.generate(prompt,schema,folder,stage,images)
        trace.append({'stage':stage,**stats});write_json(folder/'trace.json',trace)
        write_json(folder/(stage+'.output.json'),value)
        return value
    plan=call('editor_plan','先决定事件边界与叙述主线，仅生成提纲；不要直接写阅读稿。'+
        '每个分析事件 ID 必须且只能出现在 focus_event_ids、separate_event_ids 或 excluded_events 其中一处。'+
        'focus 是主线，separate 是阅读稿内单独保留的独立事件，excluded 是不写入阅读稿的事件。',PLAN_SCHEMA)
    try:validate_plan(plan,analysis,messages)
    except (ValueError,TypeError,KeyError) as exc:
        plan=call('editor_plan_repair','修正提纲结构和来源问题：'+str(exc)+'\n前稿：'+json.dumps(plan,ensure_ascii=False),PLAN_SCHEMA)
        validate_plan(plan,analysis,messages)
    plan_text=json.dumps(plan,ensure_ascii=False)
    candidate=call('editor_draft','依据已核对提纲写一份可直接阅读的完整稿件，仅输出 reader 对象本身。'+
        '\n提纲：'+plan_text,READER_SCHEMA)
    history=[]
    for attempt in range(MAX_REVISIONS+1):
        issues=reader_issues(candidate,messages);review=None;layout={'status':'not_checked'}
        # Even an overlong draft gets semantic review if its structure is valid.
        try:validate_schema(candidate,READER_SCHEMA);validate_reader(candidate,messages);structural=True
        except (ValueError,TypeError,KeyError):structural=False
        passed=False
        if structural:
            layout=layout_probe(case,analysis,candidate,folder/f'candidate-{attempt}.pdf')
            if layout['status']=='overflow':issues.append(layout['note'])
            if layout.get('overview_pages',1)>1:issues.append('首页主线总览溢出到第二页，请压缩导语、人物和阶段文字。')
            if layout.get('pages',0)>5:issues.append('阅读稿超过5页，请删减重复正文，不截断文字或缩小到难读。')
            if layout.get('pages',0)>2 and layout.get('last_page_fill',1)<.22:
                issues.append('末页内容不足页面的22%，出现零碎尾页。请精简重复段落、引文或说明，让尾页内容回到前页；不能删除重要事实或缩小字体。')
            review=call(f'editor_review_{attempt}',
                '你是独立审稿人。对照原文逐项审查候选稿，不能只复述提纲或自称通过。'+
                '尤其核查时间与因果、并行事件是否被强行串联、是否又在逐段解读聊天。'+
                '\n提纲：'+plan_text+'\n候选稿：'+json.dumps(candidate,ensure_ascii=False),REVIEW_SCHEMA)
            try:passed=validate_review(review,messages)
            except (ValueError,TypeError,KeyError) as exc:issues.append('审稿输出无效：'+str(exc))
        history.append({'attempt':attempt,'issues':issues,'review':review,'layout':layout})
        write_json(folder/'checks.json',history)
        if passed and not issues:
            result={'reader':candidate,'created_at':now(),'trace':trace,'purpose':'automatic_editorial',
                'workflow_version':VERSION,'policy_sha256':hashlib.sha256(READER_RULES.encode()).hexdigest(),
                'quality':{'status':'passed','revisions':attempt,'layout':layout,
                    'note':'程序与模型审稿通过，不替代事实核验或独立人工评估。'}}
            write_json(folder/'accepted.json',result)
            return result
        if attempt==MAX_REVISIONS:break
        candidate=call(f'editor_rewrite_{attempt+1}',
            '按下列反馈自动返修，返回完整 reader 对象。保留正确事实和重要反证，不得用删限定语来缩短。'+
            '\n提纲：'+plan_text+'\n候选稿：'+json.dumps(candidate,ensure_ascii=False)+
            '\n反馈：'+json.dumps(history[-1],ensure_ascii=False),READER_SCHEMA)
    write_json(folder/'rejected.json',{'status':'needs_revision','created_at':now(),'checks':history,'trace':trace})
    raise ValueError('自动编辑两轮返修后仍未通过。分析原稿和候选稿已保留，本次未发布完成报告。')
