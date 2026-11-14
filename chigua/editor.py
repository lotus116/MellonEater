"""Automatic, bounded editorial workflow shared by the app, CLI and skill."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from pathlib import Path
from . import provider
from .checkpoints import CallFailure
from .core import (STR, STRS, STORY_SCHEMA, READER_SCHEMA, READER_RULES,
                   schema_obj, validate_schema, validate_reader, write_json, now, normalize_reference_ids)

VERSION='editorial-v2.0'
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


def role_labels(reader):
    """Replace names in the selected cast with stable role labels, not identities.

    This does not anonymize original evidence or guarantee share-safe output.
    """
    reader=copy.deepcopy(reader);aliases={};changes=[]
    if len(reader.get('people',[]))>4:return reader,changes
    roles=r'(?:技术队员|发帖队员|其他队员|队员|队长|教授|老师|群成员|管理员|参与者)'
    for person in reader.get('people',[]):
        name=person.get('name','')
        if not isinstance(name,str) or not name or re.fullmatch(roles+r'[甲乙丙丁戊己庚辛壬癸A-D1-4]?',name):continue
        # Role-only Chinese labels and unparsed names are left for semantic
        # review; do not infer whether an arbitrary Chinese string is a name.
        if not re.search(r'[A-Za-z][A-Za-z .-]{2,}',name):continue
        prefix=re.match('^('+roles+')',name)
        label=(prefix.group(1) if prefix else '参与者')+'甲乙丙丁'[len(changes)]
        aliases[name]=label
        # A cast label such as “队员 + Latin display name” often appears without
        # its role elsewhere. Match whole names, never arbitrary substrings.
        for token in re.findall(r'[A-Za-z][A-Za-z .-]{2,}',name):
            token=token.strip()
            aliases[token]=label
            for role in ['队员','技术队员']:aliases[role+token]=label
        changes.append({'original':name,'normalized':label,'rule':'selected_cast_role_label'})
    def replace(text):
        if not aliases:return text
        pattern='|'.join(re.escape(k) for k in sorted(aliases,key=len,reverse=True))
        return re.sub(r'(?<![A-Za-z])(?:'+pattern+r')(?![A-Za-z])',lambda m:aliases[m.group()],text)
    def visit(value,key=''):
        if isinstance(value,dict):return {k:visit(v,k) for k,v in value.items()}
        if isinstance(value,list):return [visit(v,key) for v in value]
        if isinstance(value,str) and not (key.endswith('_ids') or key.endswith('_id') or key=='quote_text'):return replace(value)
        return value
    reader=visit(reader)
    for ch in reader.get('chapters',[]):
        quote=ch.get('quote_text','')
        if isinstance(quote,str) and replace(quote)!=quote:
            changes.append({'rule':'omit_identifying_pull_quote','original':quote})
            ch.update(quote_text='',quote_speaker='',quote_source_id='')
    return reader,changes


def normalize_presentations(reader,messages):
    """Bind exact image filenames and omit unverifiable decorative pull quotes.

    Narrative, claims and original evidence remain unchanged and still require
    semantic review. Never invent a quote or guess an ambiguous image binding.
    """
    reader=copy.deepcopy(reader);repairs=[];lookup={m['id']:m for m in messages}
    compact=lambda s:re.sub(r'\s+','',s)
    for index,ch in enumerate(reader.get('chapters',[])):
        image=ch.get('image_id')
        if image and image not in lookup:
            candidates=[m['id'] for m in messages if m.get('image')==image]
            if len(candidates)==1:
                ch['image_id']=candidates[0]
                repairs.append({'path':f'chapters[{index}].image_id','original':image,
                                'normalized':candidates[0],'rule':'unique_exact_image_filename'})
        quote=ch.get('quote_text');source=lookup.get(ch.get('quote_source_id'))
        if isinstance(quote,str) and quote and (not source or compact(quote) not in compact(source['text'])):
            repairs.append({'path':f'chapters[{index}]','rule':'omit_unverified_pull_quote',
                            'original':{k:ch.get(k) for k in ['quote_text','quote_speaker','quote_source_id']}})
            ch.update(quote_text='',quote_speaker='',quote_source_id='')
    reader,name_repairs=role_labels(reader);repairs.extend(name_repairs)
    return reader,repairs


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
    for field,limit in [('title',28),('deck',100),('lead',160),('verdict',220)]:cap(reader[field],limit,field)
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
        value,repairs=normalize_reference_ids(value,messages)
        if repairs:
            stats={**stats,'local_reference_repairs':repairs}
            write_json(folder/(stage+'.reference-repairs.json'),repairs)
        if schema==READER_SCHEMA:
            value,presentation_repairs=normalize_presentations(value,messages)
            if presentation_repairs:
                stats={**stats,'local_presentation_repairs':presentation_repairs}
                write_json(folder/(stage+'.presentation-repairs.json'),presentation_repairs)
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
        if structural and not issues:
            layout=layout_probe(case,analysis,candidate,folder/f'candidate-{attempt}.pdf')
            # Layout is deterministic: never pay for prose rewriting just to fix pagination.
            review=call(f'editor_review_{attempt}',
                '你是独立审稿人。对照原文逐项审查候选稿，不能只复述提纲或自称通过。'+
                '尤其核查时间与因果、并行事件是否被强行串联、是否又在逐段解读聊天。'+
                '\n提纲：'+plan_text+'\n候选稿：'+json.dumps(candidate,ensure_ascii=False),REVIEW_SCHEMA)
            try:passed=validate_review(review,messages)
            except (ValueError,TypeError,KeyError) as exc:issues.append('审稿输出无效：'+str(exc))
        history.append({'attempt':attempt,'issues':issues,'review':review,'layout':layout})
        write_json(folder/'checks.json',history)
        if passed and not issues:
            if layout['status']=='overflow' or layout.get('overview_pages',1)>1 or layout.get('pages',0)>5:
                write_json(folder/'layout-pending.json',{'reader':candidate,'review':review,'layout':layout,'trace':trace})
                raise CallFailure('内容审稿已通过，但排版需要调整。候选稿与审稿已缓存；继续时会先复验排版，不重写全文。',kind='layout')
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
            '\n反馈：'+json.dumps({'issues':issues,'review':review},ensure_ascii=False),READER_SCHEMA)
    write_json(folder/'rejected.json',{'status':'needs_revision','created_at':now(),'checks':history,'trace':trace})
    raise ValueError('自动编辑两轮返修后仍未通过。分析原稿和候选稿已保留，本次未发布完成报告。')
