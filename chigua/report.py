from __future__ import annotations
from html import escape
from pathlib import Path
import json
import base64
from .core import DATA


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


def reader_html(case,run):
    r=run['report']['reader'];lookup={m['id']:m for m in case['messages']}
    def p(value):return '<p>'+escape(value)+'</p>'
    def refs(ids):return '<small>'+', '.join(escape(i) for i in ids)+'</small>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
      '<title>'+escape(r['title'])+'</title><style>body{margin:0;color:#213047;background:#f2f4f8;font:17px/1.9 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:760px;margin:24px auto;padding:48px;background:white}h1{font-size:32px;line-height:1.5}h2{font-size:23px;margin-top:36px}small,figcaption{font-size:13px;color:#5a687b}blockquote{border-left:3px solid #4350ae;padding-left:20px;color:#4350ae}figure{margin:24px 0;text-align:center}img{max-width:100%;max-height:720px}li{margin-bottom:8px}@media(max-width:640px){main{padding:24px;margin:0}}@media print{main{margin:0;padding:0}body{background:white}figure{break-inside:avoid}}</style><main><small>知瓜 · 私密材料阅读版</small>',
      '<h1>'+escape(r['title'])+'</h1>',p(r['deck']),p(r['lead']),'<h2>先认一下人</h2>']
    for person in r['people']:parts.append(p(person['name']+'：'+person['role']))
    for ch in r['chapters']:
        parts.append('<h2>'+escape(ch['title'])+'</h2>')
        for para in ch['paragraphs']:parts.extend([p(para['text']),refs(para['source_ids'])])
        if ch['quote_text']:parts.append('<blockquote>'+escape(ch['quote_text'])+p('—— '+ch['quote_speaker'])+'</blockquote>')
        if ch['image_id']:
            parts.append('<figure><img src="'+image_uri(lookup[ch['image_id']]['image'])+'" alt="'+escape(ch['image_caption'])+'"><figcaption>'+escape(ch['image_caption'])+' ['+escape(ch['image_id'])+']</figcaption></figure>')
    parts.extend(['<h2>'+escape(r['verdict_title'])+'</h2>',p(r['verdict']),refs(r['verdict_source_ids']),'<h2>还有哪些地方没说清</h2><ul>'])
    parts.extend('<li>'+escape(q)+'</li>' for q in r['open_questions'])
    parts.extend(['</ul><hr>',p(case.get('source_note','')),'<small>整理时间：'+escape(local_time(run['created_at']))+'（香港时间）。材料编号可在本地工作台回查。</small></main></html>'])
    return ''.join(parts)


def audit_pdf(case, run, path: Path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether
    from reportlab.lib.enums import TA_LEFT
    font_path=Path('/Library/Fonts/Arial Unicode.ttf')
    if not font_path.exists():
        font_path=Path('/System/Library/Fonts/STHeiti Light.ttc')
    pdfmetrics.registerFont(TTFont('ChiguaChinese',str(font_path),subfontIndex=0))
    styles = getSampleStyleSheet()
    base = {'fontName':'ChiguaChinese', 'leading':18, 'wordWrap':'CJK', 'spaceAfter':9}
    body = ParagraphStyle('Chinese', fontSize=10.5, **base)
    small = ParagraphStyle('SmallChinese', fontSize=9, textColor=colors.HexColor('#566477'), **base)
    heading = ParagraphStyle('HeadingChinese', fontName='ChiguaChinese', fontSize=15, leading=22, spaceBefore=18, spaceAfter=12, keepWithNext=True)
    title = ParagraphStyle('TitleChinese', fontName='ChiguaChinese', fontSize=25, leading=34, spaceAfter=18)
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
        canvas.setFont('ChiguaChinese',8)
        canvas.setFillColor(colors.HexColor('#566477'))
        canvas.drawString(45,25,'知瓜 · 私密案例 / '+case['title'])
        canvas.drawRightString(550,25,str(doc.page))
    path.parent.mkdir(parents=True,exist_ok=True)
    SimpleDocTemplate(str(path),pagesize=(595.28,841.89),rightMargin=45,leftMargin=45,topMargin=42,bottomMargin=45,
                      title=r['title'],author='知瓜').build(story,onFirstPage=footer,onLaterPages=footer)


def report_pdf(case,run,path):
    if 'reader' not in run['report']:
        return audit_pdf(case,run,path)
    return reader_pdf(case,run,path)


def reader_pdf(case,run,path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether, HRFlowable
    font_path=Path('/Library/Fonts/Arial Unicode.ttf')
    if not font_path.exists():font_path=Path('/System/Library/Fonts/STHeiti Light.ttc')
    pdfmetrics.registerFont(TTFont('ChiguaChinese',str(font_path),subfontIndex=0))
    ink=colors.HexColor('#213047');muted=colors.HexColor('#5a687b');accent=colors.HexColor('#4350ae')
    def style(name,size,leading,**kw):
        return ParagraphStyle(name,fontName='ChiguaChinese',fontSize=size,leading=leading,
                              wordWrap='CJK',textColor=ink,spaceAfter=10,**kw)
    body=style('ReaderBody',11.2,21)
    title=style('ReaderTitle',25,36,spaceBefore=8)
    deck=style('ReaderDeck',13,23)
    heading=style('ReaderHeading',17,26,spaceBefore=18,keepWithNext=True)
    small=style('ReaderSmall',8.5,14);small.textColor=muted
    quote=style('ReaderQuote',13,23,leftIndent=14,rightIndent=14);quote.textColor=accent
    def p(text,s=body):return Paragraph(escape(str(text)).replace('\n','<br/>'),s)
    r=run['report']['reader'];lookup={m['id']:m for m in case['messages']}
    title_text=r['title']
    if len(title_text)>=19 and '：' in title_text:title_text=title_text.replace('：','：\n',1)
    story=[p('知瓜 · 一起把前因后果看明白',small),p(title_text,title),p(r['deck'],deck),
           HRFlowable(width='100%',thickness=.8,color=colors.HexColor('#cfd6e4'),spaceBefore=8,spaceAfter=18),p(r['lead'])]
    if r['people']:
        story.append(p('先认一下人',heading))
        rows=[[p(person['name'],small),p(person['role'],small)] for person in r['people']]
        table=Table(rows,colWidths=[85,410],hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f1f3f9')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
            ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
        story.append(table)
    for chapter in r['chapters']:
        story.append(p(chapter['title'],heading))
        refs=[]
        for para in chapter['paragraphs']:
            story.append(p(para['text']));refs.extend(para['source_ids'])
        if chapter['quote_text']:
            story.append(KeepTogether([p('“'+chapter['quote_text']+'”',quote),p('—— '+chapter['quote_speaker']+' / '+chapter['quote_source_id'],small)]))
        image_id=chapter['image_id']
        if image_id and image_id in lookup:
            m=lookup[image_id];image_path=DATA/'uploads'/Path(m['image']).name
            img=Image(str(image_path));factor=min(315/img.imageWidth,400/img.imageHeight,1)
            img.drawWidth=img.imageWidth*factor;img.drawHeight=img.imageHeight*factor;img.hAlign='CENTER'
            story.append(KeepTogether([Spacer(1,8),img,Spacer(1,7),p(chapter['image_caption']+' ['+image_id+']',small)]))
        if refs:story.append(p('本段材料：'+', '.join(dict.fromkeys(refs)),small))
    story.extend([p(r['verdict_title'],heading),p(r['verdict']),p('判断依据：'+', '.join(r['verdict_source_ids']),small)])
    if r['open_questions']:
        story.append(p('还有哪些地方没说清',heading))
        for x in r['open_questions']:story.append(p('• '+x))
    story.extend([Spacer(1,14),HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#d5dce6'),spaceAfter=12),
        p('关于这份整理',small),p(case.get('source_note',''),small),
        p('这是对现有材料的还原与评价，不是对记录外全部事实的认证。文中编号可在本地工作台回查原文；完整证据清单和运行信息保留在工作台。',small),
        p('整理时间：'+local_time(run['created_at'])+'（香港时间）',small)])
    def footer(canvas,doc):
        canvas.setFont('ChiguaChinese',8);canvas.setFillColor(muted)
        canvas.drawString(50,25,'知瓜 / 私密材料阅读版');canvas.drawRightString(545,25,str(doc.page))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    SimpleDocTemplate(str(path),pagesize=(595.28,841.89),leftMargin=50,rightMargin=50,topMargin=42,bottomMargin=45,
        title=r['title'],author='知瓜').build(story,onFirstPage=footer,onLaterPages=footer)
