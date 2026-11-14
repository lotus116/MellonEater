from __future__ import annotations
from html import escape
from pathlib import Path
import json
import base64
from .core import DATA


def pdf_fonts():
    """Embed local Chinese faces; never distribute operating-system font files."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates={
        'body': [('SongtiSC','/System/Library/Fonts/Supplemental/Songti.ttc',6)],
        'heading': [('HeitiSCMedium','/System/Library/Fonts/STHeiti Medium.ttc',1)],
        'ui': [('HeitiSCLight','/System/Library/Fonts/STHeiti Light.ttc',1)],
        'quote': [('SongtiSCBold','/System/Library/Fonts/Supplemental/Songti.ttc',1)],
    }
    fallback=[('ArialUnicode','/Library/Fonts/Arial Unicode.ttf',0),
              ('ArialUnicode','/System/Library/Fonts/Supplemental/Arial Unicode.ttf',0)]
    result={}
    for role,faces in candidates.items():
        for name,path,index in faces+fallback:
            if not Path(path).is_file():continue
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name,path,subfontIndex=index))
            result[role]=name;break
        else:raise ValueError('缺少可嵌入的中文字体，请在 Mac 安装宋体或 Arial Unicode。')
    return result


def local_time(value):
    from datetime import datetime, timedelta, timezone
    try:return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H:%M')
    except (ValueError,TypeError):return str(value)


def report_html(case, run):
    if 'reader' in run['report']:
        return reader_html(case, run)
    r = run['report']
    def refs(ids):
        return ' '.join(f'<a class="ref" href="#msg-{escape(i)}">{escape(i)}</a>' for i in ids)
    parts = [f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(r['title'])} · 知瓜</title><style>
body{{font:16px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#1d2b39;background:#f5f7fa;margin:0}}
main{{max-width:880px;background:white;margin:32px auto;padding:56px}} h1{{font-size:32px;line-height:1.4}} h2{{margin-top:38px;font-size:23px}} h3{{font-size:18px}}
.meta,.muted{{color:#576576;font-size:13px}} .summary{{font-size:18px;border-left:4px solid #4b55c6;padding-left:22px}}
.claim{{padding:24px 0;border-top:1px solid #dce1ea;break-inside:avoid}}.status{{color:#3845a0;font-weight:600}}
.ref{{font-size:12px;color:#3949a8;margin-right:6px}}.message{{border-top:1px solid #e3e7ee;padding:18px 0;scroll-margin-top:16px}}pre{{white-space:pre-wrap;font:inherit}}img{{max-width:100%;max-height:620px}}
@media print{{body{{background:white}}main{{margin:0;padding:0;max-width:none}}.no-print{{display:none}}a{{color:inherit}}}}
@media(max-width:640px){{main{{margin:0;padding:24px}}}}
</style><main><div class="meta">知瓜 / 事件与证据报告</div><h1>{escape(r['title'])}</h1>
<p class="meta">生成时间：{escape(run['created_at'])}　方法：{escape(run['method'])}　来源：{escape(run['origin'])}</p>
<p class="summary">{escape(r['summary'])}</p><p class="muted">{escape(case.get('source_note',''))}</p>
<p class="muted">引用编号已校验；证据是否支持结论仍需人工核对。本报告不证明记录外的现实真相。</p>
<p class="no-print muted">可使用浏览器的打印功能存储为 PDF。</p><h2>事件经过</h2>''']
    for event in r['events']:
        parts.append(f"<h3>{escape(event['title'])}</h3><p>{escape(event['summary'])}</p>{refs(event['message_ids'])}")
    parts.append('<h2>逐条判断</h2>')
    for c in r['claims']:
        parts.append(f'''<section class="claim"><span class="status">{escape(c['status'])}</span><h3>{escape(c['statement'])}</h3>
<p>{escape(c['reason'])}</p><p><strong>评价标准：</strong>{escape(c['standard'])}</p>
<p>支持材料：{refs(c['support_ids']) or '尚缺'}　冲突材料：{refs(c['conflict_ids']) or '未识别'}</p>
<p class="muted">来源说明：{escape(c['source_note'])}</p>
<p><strong>尚待确认：</strong>{escape('；'.join(c['unknowns']) or '无额外列项')}</p>
<p><strong>何时应改变判断：</strong>{escape(c['would_change_if'])}</p></section>''')
    parts.append('<h2>时间线</h2>')
    for t in r['timeline']:
        parts.append(f"<p><strong>{escape(t['time_label'])}</strong>　{escape(t['description'])} {refs(t['message_ids'])}</p>")
    parts.append('<h2>材料限制</h2><ul>'+''.join('<li>'+escape(x)+'</li>' for x in r['limitations'])+'</ul>')
    parts.append('<h2>原始材料索引</h2>')
    for m in case['messages']:
        parts.append(f'''<section class="message" id="msg-{escape(m['id'])}"><div class="meta">{escape(m['id'])}　{escape(m['speaker'])}　{escape(str(m['timestamp'] or '原始时间未知'))}</div><pre>{escape(m['text'])}</pre></section>''')
        if m.get('image'):
            parts.append(f'<img src="{image_uri(m["image"])}" alt="{escape(m["source_name"])} 原始截图">')
    parts.append('</main></html>')
    return ''.join(parts)


def image_uri(name):
    path=DATA/'uploads'/Path(name).name
    mime='image/png' if path.suffix.lower()=='.png' else 'image/jpeg'
    return f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode()


def source_labels(case):
    """Display aliases only; immutable evidence IDs remain in the stored result."""
    return {m['id']:f'M{i:03d}' for i,m in enumerate(case['messages'],1)}


def cited_sources(case, reader, extra_ids=()):
    ids=set(extra_ids)
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.endswith('source_ids') or key=='conflict_ids':ids.update(item)
                elif key in ('quote_source_id','image_id') and item:ids.add(item)
                else:visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(reader)
    lookup={m['id']:m for m in case['messages']}
    if ids-lookup.keys():raise ValueError('报告引用包含不存在的材料，无法导出原文。')
    pending=list(ids)
    while pending:
        parent=lookup[pending.pop()].get('parent_id')
        if parent and parent not in ids:
            if parent not in lookup:raise ValueError('原文的父材料不存在。')
            ids.add(parent);pending.append(parent)
    return [m for m in case['messages'] if m['id'] in ids]


def source_note(case):
    return case.get('source_note','').replace('未自动发送给模型。','导入步骤本身未启动模型分析。')


def media_note(message):
    reasons={'missingImage':'导出包中没有找到对应图片',
             'ambiguousImage':'存在多个同名图片，无法确定对应关系',
             'imageTooLarge':'图片超过处理上限',
             'imageFormatUnavailable':'图片格式暂时无法读取'}
    missing=[m for m in (message.get('source_reference') or {}).get('media',[]) if m.get('status')=='unavailable']
    return '；'.join(dict.fromkeys(reasons.get(m.get('reason'),'图片未取得') for m in missing))


def supplement_note(message):
    reference=message.get('source_reference') or {}
    records=[reference.get('supplement')]+[m.get('supplement') for m in reference.get('media',[])
        if m.get('image')==message.get('image')]
    kinds={r.get('kind') for r in records if isinstance(r,dict)}
    if not kinds:return ''
    label='截图' if 'screenshot' in kinds else '单独保存的图片'
    return '后补'+label+'：对应关系由用户核对确认，并非原 ZIP 随附；原始分辨率及完整性未核验。'


def reader_html(case,run):
    r=run['report']['reader'];lookup={m['id']:m for m in case['messages']}
    assessment = r.get('assessment', [])
    labels=source_labels(case);sources=cited_sources(case,r)
    def p(value):return '<p>'+escape(value)+'</p>'
    def refs(ids):
        if not ids:
            return ''
        return '<small class="refs">'+''.join(f'<a href="#source-{labels[i]}" aria-label="核对材料 {labels[i]}">{labels[i]}</a>' for i in dict.fromkeys(ids))+'</small>'
    def picture(m,caption):
        try:
            uri=image_uri(m['image'])
        except FileNotFoundError:
            return '<p class="muted">本机图片文件已缺失。可继续核对文字记录。</p>'
        return '<button type="button" class="zoom-image" aria-label="放大 '+escape(caption)+'"><img src="'+uri+'" alt="'+escape(caption)+'"></button>'
    def questions():
        if not r['open_questions']:
            return ''
        return ('<section id="unresolved"><h2>还有哪些事没说清</h2><ul>'+
                ''.join('<li>'+escape(q)+'</li>' for q in r['open_questions'])+'</ul></section>')
    asset_root=Path(__file__).resolve().parents[1]/'static'
    css=(asset_root/'reader.css').read_text();js=(asset_root/'reader.js').read_text()
    reading_length = len(r['lead']+r['verdict']) + sum(len(p['text']) for c in r['chapters'] for p in c['paragraphs'])
    reading_length += sum(len(item['judgment']) for item in assessment)
    minutes = max(1, (reading_length + 449) // 450)
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
      '<link rel="icon" href="data:,"><title>'+escape(r['title'])+'</title><style>'+css+'</style><main id="top">',
      '<header class="masthead"><span>知瓜 <small>约 '+str(minutes)+' 分钟</small></span><button id="print-report" type="button" hidden>打印 / 存为 PDF</button></header>',
      '<div class="opening"><h1>'+escape(r['title'])+'</h1><p class="lead">'+escape(r['lead'])+'</p></div>',
      '<section class="now" id="now"><small>目前进展</small><h2>'+escape(r['verdict_title'])+'</h2>',p(r['verdict']),refs(r['verdict_source_ids']),'</section>',
      '<nav class="reader-nav" aria-label="阅读导航">'+('<a href="#turns">关键转折</a>' if r.get('story') else '')+
      ('<a href="#assessment">怎么看双方的做法</a>' if assessment else '')+
      ('<a href="#unresolved">待确认</a>' if r['open_questions'] else '')+
      '<a href="#details">详细经过</a><a href="#originals">核对原文</a></nav>']
    if r.get('story'):
        story=r['story']
        parts.extend(['<section id="turns"><h2>事情怎么发展</h2>',p(story['central_question'])])
        for i,step in enumerate(story['arc'],1):
            parts.extend(['<details class="turn"><summary><span class="turn-number">'+str(i)+'</span><span><strong>'+escape(step['stage'])+'</strong><span class="turn-brief">'+escape(step['happened'])+'</span></span></summary>',
                          '<div class="turn-detail">'+p(step['changed'])+'<small>'+escape(step['order_basis'])+'</small>'+refs(step['source_ids'])+'</div></details>'])
        parts.append('<details class="scope"><summary>这些时间如何确定</summary>'+p(story['timeline_note'])+'</details></section>')
    if assessment:
        parts.append('<section id="assessment"><h2>怎么看双方的做法</h2>')
        for item in assessment:
            parts.extend(['<article class="assessment-item"><h3>'+escape(item['title'])+'</h3>',
                          '<p class="behavior-judgment"><strong>行为判断</strong> '+escape(item['judgment'])+'</p>',
                          '<details class="assessment-basis"><summary>看依据'+('和推测' if item['inference'] else '')+'</summary>',
                          '<p><strong>记录里看到的</strong> '+escape(item['observation'])+'</p>',refs(item['source_ids'])])
            if item['inference']:
                parts.append('<p><strong>一种解释</strong> '+escape(item['inference'])+'</p>')
            if item['counterpoint']:
                parts.extend(['<p><strong>还要考虑</strong> '+escape(item['counterpoint'])+'</p>',refs(item['conflict_ids'])])
            parts.append('</details></article>')
        parts.extend(['</section>',questions()])
    if r['people']:
        parts.append('<section id="people"><h2>谁是谁</h2><div class="people">')
        for person in r['people']:parts.extend(['<div class="person"><strong>'+escape(person['name'])+'</strong>',p(person['role']),refs(person.get('source_ids',[])),'</div>'])
        parts.append('</div></section>')
    parts.append('<section id="details"><div class="section-heading"><h2>详细经过</h2><button id="expand-story" type="button" aria-expanded="false">展开详细经过</button></div>')
    for ch in r['chapters']:
        parts.append('<details class="chapter"><summary>'+escape(ch['title'])+'</summary>')
        for para in ch['paragraphs']:parts.extend([p(para['text']),refs(para['source_ids'])])
        if ch['quote_text']:parts.append('<blockquote>'+escape(ch['quote_text'])+p('—— '+ch['quote_speaker'])+refs([ch['quote_source_id']])+'</blockquote>')
        if ch['image_id']:parts.append('<figure>'+picture(lookup[ch['image_id']],ch['image_caption'])+'<figcaption>'+escape(ch['image_caption'])+refs([ch['image_id']])+p(supplement_note(lookup[ch['image_id']]))+'</figcaption></figure>')
        parts.append('</details>')
    parts.append('</section>')
    selected={m['id'] for m in sources}
    claims=[] if assessment else [c for c in run['report'].get('claims',[]) if selected.intersection(c['support_ids']+c['conflict_ids'])][:4]
    sources=cited_sources(case,r,[mid for c in claims for mid in c['support_ids']+c['conflict_ids']])
    if claims and not assessment:
        parts.append('<section><h2>关键说法与依据</h2>')
        for c in claims:parts.extend(['<details class="dispute"><summary>'+escape(c['statement'])+'<small>'+escape(c['status'])+'</small></summary>',p(c['reason']),refs(c['support_ids']),p('反证与不同说法')+refs(c['conflict_ids']) if c['conflict_ids'] else '', '</details>'])
        parts.append('</section>')
    if r.get('story',{}).get('threads'):
        parts.append('<details class="scope"><summary>相关线索</summary>')
        for thread in r['story']['threads']:parts.extend([p(thread['name']+'：'+thread['role_in_story']),refs(thread['source_ids'])])
        parts.append('</details>')
    if not assessment:
        parts.append(questions())
    parts.extend(['<details class="scope"><summary>整理范围与来源说明</summary>',p(source_note(case)),'<small>整理时间：'+escape(local_time(run.get('reader_updated_at',run['created_at'])))+'（香港时间）。</small></details>',
        '<section id="originals"><h2>原文附录 · 按需核对</h2>',p('以下为文中引用的完整材料及其父材料，不代表全部群记录。显示名、原文与图片可能含个人信息，仅供私下核对；编号表示本包顺序，不代表事件先后。'),
        '<div class="source-controls"><label for="source-search">搜索原文或发言者</label><input id="source-search" type="search" placeholder="例如：材料编号、关键词或名字"><p id="source-count" class="muted" role="status">共 '+str(len(sources))+' 条材料，点击展开</p></div>'])
    for m in sources:
        parts.extend([f'<details class="original" id="source-{labels[m["id"]]}"><summary><strong>'+labels[m['id']]+' · '+escape(m['speaker'])+'</strong><small>'+escape(local_time(m.get('timestamp') or '原始时间未知'))+'</small></summary>',
            '<pre>'+escape(m['text'])+'</pre>'])
        if m.get('parent_id'):parts.append('所属材料 '+refs([m['parent_id']]))
        if m.get('image'):parts.append(picture(m,'材料 '+labels[m['id']]+' 图片'))
        if supplement_note(m):parts.append(p(supplement_note(m)))
        if media_note(m):parts.append(p('图片缺口：'+media_note(m)+'；未据此补写图片内容。'))
        parts.append('</details>')
    parts.append('</section><a class="jump-top" href="#top">回到事件概况</a></main><dialog id="image-viewer" aria-label="图片原文"><button type="button">关闭图片</button><p></p><img alt=""></dialog><script>'+js+'</script></html>')
    return ''.join(parts)


def audit_pdf(case, run, path: Path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether
    from reportlab.lib.enums import TA_LEFT
    fonts=pdf_fonts()
    styles = getSampleStyleSheet()
    base = {'fontName':fonts['body'], 'leading':18, 'wordWrap':'CJK', 'spaceAfter':9}
    body = ParagraphStyle('Chinese', fontSize=10.5, **base)
    small = ParagraphStyle('SmallChinese', fontSize=9, textColor=colors.HexColor('#566477'), **base)
    heading = ParagraphStyle('HeadingChinese', fontName=fonts['heading'], fontSize=15, leading=22, spaceBefore=18, spaceAfter=12, keepWithNext=True)
    title = ParagraphStyle('TitleChinese', fontName=fonts['heading'], fontSize=25, leading=34, spaceAfter=18)
    story=[]
    def p(text, style=body):
        return Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    r=run['report']
    story += [p('知瓜 / 事件与证据报告',small),p(r['title'],title),p(r['summary']),
              p('方法：'+run['method']+'；来源：'+run['origin']+'；时间：'+run['created_at'],small),
              p(case.get('source_note',''),small),p('引用编号有效不代表结论已被证实；语义支持关系需人工核对。',small)]
    story.append(p('事件经过',heading))
    for e in r['events']:
        story += [p(e['title']),p(e['summary']),p('材料：'+', '.join(e['message_ids']),small)]
    story.append(p('逐条判断',heading))
    for c in r['claims']:
        story += [p(c['status']+' | '+c['statement'],heading),p(c['reason']),p('标准：'+c['standard']),
                  p('支持：'+(', '.join(c['support_ids']) or '尚缺')+'；冲突：'+(', '.join(c['conflict_ids']) or '未识别'),small),
                  p('来源：'+c['source_note'],small),p('未知：'+('；'.join(c['unknowns']) or '无额外列项')),
                  p('改变条件：'+c['would_change_if'])]
    story.append(p('时间线与材料限制',heading))
    for t in r['timeline']:
        story.append(p(t['time_label']+'：'+t['description']+' ['+', '.join(t['message_ids'])+']'))
    for x in r['limitations']:
        story.append(p('• '+x))
    story.append(p('原始材料索引',heading))
    for m in case['messages']:
        story += [p(m['id']+' | '+m['speaker']+' | '+str(m['timestamp'] or '原始时间未知'),heading),p(m['text'])]
        if m.get('image'):
            image_path=DATA/'uploads'/Path(m['image']).name
            if image_path.exists():
                img=Image(str(image_path))
                factor=min(450/img.imageWidth,580/img.imageHeight,1)
                img.drawWidth=img.imageWidth*factor; img.drawHeight=img.imageHeight*factor
                story.append(img)
    def footer(canvas,doc):
        canvas.setFont(fonts['ui'],8)
        canvas.setFillColor(colors.HexColor('#566477'))
        canvas.drawString(45,25,'知瓜 · 私密案例 / '+case['title'])
        canvas.drawRightString(550,25,str(doc.page))
    path.parent.mkdir(parents=True,exist_ok=True)
    SimpleDocTemplate(str(path),pagesize=(595.28,841.89),rightMargin=45,leftMargin=45,topMargin=42,bottomMargin=45,
                      title=r['title'],author='知瓜').build(story,onFirstPage=footer,onLaterPages=footer)


def report_pdf(case,run,path,*,include_sources=True):
    if 'reader' not in run['report']:
        return audit_pdf(case,run,path)
    return reader_pdf(case,run,path,include_sources=include_sources)


def reader_pdf(case,run,path,*,include_sources=True):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether, HRFlowable, PageBreak, Flowable
    metrics={'pages':0,'overview_pages':0,'last_page_fill':0}
    class ReaderDocument(SimpleDocTemplate):
        def afterFlowable(self,flowable):
            if isinstance(flowable,(Paragraph,Table,Image,HRFlowable)):
                metrics['last_page_fill']=round((self.frame._y2-self.frame._topPadding-self.frame._y)/self.frame._aH,3)
    class OverviewEnd(Flowable):
        def wrap(self,*args):return (0,0)
        def draw(self):metrics['overview_pages']=self.canv.getPageNumber()
    class Outline(Flowable):
        def __init__(self,label,key):super().__init__();self.label=label;self.key=key
        def wrap(self,*args):return (0,0)
        def draw(self):
            self.canv.bookmarkPage(self.key)
            self.canv.addOutlineEntry(self.label,self.key,level=0)
    fonts=pdf_fonts()
    ink=colors.HexColor('#213047');muted=colors.HexColor('#5a687b');accent=colors.HexColor('#4350ae')
    def style(name,size,leading,**kw):
        return ParagraphStyle(name,fontName=fonts['body'],fontSize=size,leading=leading,
                              wordWrap='CJK',textColor=ink,spaceAfter=7,**kw)
    body=style('ReaderBody',11.7,19.5)
    title=style('ReaderTitle',25,36,spaceBefore=8)
    deck=style('ReaderDeck',13,23)
    heading=style('ReaderHeading',17,26,spaceBefore=14,keepWithNext=True)
    small=style('ReaderSmall',8.5,14);small.textColor=muted
    quote=style('ReaderQuote',13,23,leftIndent=14,rightIndent=14);quote.textColor=accent
    for s in [title,heading]:s.fontName=fonts['heading']
    for s in [deck,small]:s.fontName=fonts['ui']
    quote.fontName=fonts['quote']
    def p(text,s=body):return Paragraph(escape(str(text)).replace('\n','<br/>'),s)
    r=run['report']['reader'];lookup={m['id']:m for m in case['messages']}
    labels=source_labels(case);sources=cited_sources(case,r)
    def references(ids,prefix='材料：'):
        links=[]
        for mid in dict.fromkeys(ids):
            label=labels[mid]
            links.append(f'<link href="#source-{label}" color="#4350ae">{label}</link>' if include_sources else label)
        return Paragraph(escape(prefix)+' / '.join(links),small)
    title_text=r['title']
    if len(title_text)>=19 and '：' in title_text:title_text=title_text.replace('：','：\n',1)
    story=[Outline('先看事件与当前结果','overview'),p('知瓜 · 私密阅读版',small),p(title_text,title),p(r['deck'],deck),
           HRFlowable(width='100%',thickness=.8,color=colors.HexColor('#cfd6e4'),spaceBefore=8,spaceAfter=18),p(r['lead'])]
    state=Table([[p('目前进展',small)],[p(r['verdict_title'],deck)],[p(r['verdict'])],[references(r['verdict_source_ids'],'依据：')]],colWidths=[495],hAlign='LEFT')
    state.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#eff6f3')),
        ('LINEBEFORE',(0,0),(0,-1),3,colors.HexColor('#276b61')),
        ('LEFTPADDING',(0,0),(-1,-1),14),('RIGHTPADDING',(0,0),(-1,-1),14),
        ('TOPPADDING',(0,0),(-1,0),10),('BOTTOMPADDING',(0,-1),(-1,-1),8)]))
    story.extend([Spacer(1,8),state])
    if r['people']:
        story.append(p('这件事里都有谁',heading))
        for person in r['people']:story.append(p(person['name']+'：'+person['role'],body))
    story.append(p('接着看关键转折与详细经过。文末保留引用原文和图片，可按需核对；点击材料编号即可跳转。',small))
    story.extend([OverviewEnd(),PageBreak(),Outline('关键转折与详细经过','story')])
    if r.get('story'):
        spine=r['story']
        story.extend([p('事情是怎样走到这一步的',heading),p(spine['central_question'])])
        arc_label=ParagraphStyle('ArcLabel',parent=small,fontName=fonts['heading'],fontSize=10.5,leading=17)
        arc_body=ParagraphStyle('ArcBody',parent=body,fontSize=10.8,leading=18,spaceAfter=5)
        rows=[]
        for index,step in enumerate(spine['arc'],1):
            rows.append([[p(str(index)+' / '+step['stage'],arc_label),p(step['order_basis'],small)],
                         [p(step['happened'],arc_body),p('变化：'+step['changed'],small),references(step['source_ids'],'')]])
        table=Table(rows,colWidths=[116,379],hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,-2),.5,colors.HexColor('#dfe4ed')),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),9),
            ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.extend([table,Spacer(1,8)])
    for chapter in r['chapters']:
        story.append(p(chapter['title'],heading))
        refs=[]
        for para in chapter['paragraphs']:
            story.append(p(para['text']));refs.extend(para['source_ids'])
        if chapter['quote_text']:
            story.append(KeepTogether([p('“'+chapter['quote_text']+'”',quote),references([chapter['quote_source_id']],'—— '+chapter['quote_speaker']+' / ')]))
        image_id=chapter['image_id']
        if image_id and image_id in lookup:
            m=lookup[image_id];image_path=DATA/'uploads'/Path(m['image']).name
            img=Image(str(image_path));factor=min(315/img.imageWidth,400/img.imageHeight,1)
            img.drawWidth=img.imageWidth*factor;img.drawHeight=img.imageHeight*factor;img.hAlign='CENTER'
            story.append(KeepTogether([Spacer(1,8),img,Spacer(1,7),references([image_id],chapter['image_caption']+' / ')]))
            if supplement_note(m):story.append(p(supplement_note(m),small))
        if refs:story.append(references(refs,'本段材料：'))
    if r.get('story',{}).get('threads'):
        story.append(p('把支线放回主线',heading))
        for thread in r['story']['threads']:
            story.extend([p(thread['name']+'：'+thread['role_in_story']),references(thread['source_ids'])])

    if r['open_questions']:
        story.append(KeepTogether([p('还有哪些地方没说清',heading)]+[p('• '+x) for x in r['open_questions']]))
    story.append(KeepTogether([Spacer(1,14),HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#d5dce6'),spaceAfter=12),
        p('关于这份整理',small),p(r.get('story',{}).get('timeline_note',''),small),p(source_note(case),small),
        p('这是对现有材料的还原与评价，不是对记录外全部事实的认证。文中短编号对应文末原文附录；完整证据清单和运行信息保留在工作台。',small),
        p('整理时间：'+local_time(run.get('reader_updated_at',run['created_at']))+'（香港时间）',small)]))
    if include_sources and sources:
        story.extend([PageBreak(),Outline('原文与图片 · 按需核对','originals'),p('原文附录 · 按需核对',title)])
        story.append(p('以下保留文中引用的原始材料及其父材料，不代表全部群记录。原文、显示名与时间可能含个人信息，仅供私下核对。编号表示本包顺序，不代表事件先后。',small))
        source_heading=ParagraphStyle('SourceHeading',parent=heading,fontSize=12,leading=20,spaceBefore=12,spaceAfter=6)
        source_body=ParagraphStyle('SourceBody',parent=body,fontSize=11,leading=19,spaceAfter=0)
        source_time=ParagraphStyle('SourceTime',parent=small,keepWithNext=True)
        for m in sources:
            entry=[]
            label=labels[m['id']]
            entry.append(Paragraph(f'<a name="source-{label}"/>'+escape(label+' · '+m['speaker']),source_heading))
            entry.append(p(local_time(m.get('timestamp') or '原始时间未知'),source_time))
            # Separate original lines so a heading does not drag an entire long
            # message to a new page. Preserve empty lines; never shorten quotes.
            for line in m['text'].split('\n'):entry.append(p(line or '\u00a0',source_body))
            entry.append(Spacer(1,10))
            if m.get('parent_id'):entry.append(references([m['parent_id']],'所属材料：'))
            if m.get('image'):
                img=Image(str(DATA/'uploads'/Path(m['image']).name))
                factor=min(450/img.imageWidth,480/img.imageHeight,1)
                img.drawWidth=img.imageWidth*factor;img.drawHeight=img.imageHeight*factor
                entry.append(img)
            # Keep a short attachment label beside its image. Long original
            # messages remain splittable so no source text is truncated.
            if m.get('image') and len(m['text'])<=300 and m['text'].count('\n')<=4:
                story.append(KeepTogether(entry))
            else:
                story.extend(entry)
            if supplement_note(m):story.append(p(supplement_note(m),small))
            if media_note(m):story.append(p('图片缺口：'+media_note(m)+'；未据此补写图片内容。',small))
    def footer(canvas,doc):
        metrics['pages']=max(metrics['pages'],doc.page)
        canvas.setFont(fonts['ui'],8);canvas.setFillColor(muted)
        canvas.drawString(50,25,'知瓜 / 私密材料阅读版');canvas.drawRightString(545,25,str(doc.page))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    ReaderDocument(str(path),pagesize=(595.28,841.89),leftMargin=50,rightMargin=50,topMargin=42,bottomMargin=45,
        title=r['title'],author='知瓜').build(story,onFirstPage=footer,onLaterPages=footer)
    return metrics
