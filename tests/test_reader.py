import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from chigua import report, mac
from chigua.core import normalize_messages,validate_reader


def reader():
    return {'title':'示例','deck':'概要','lead':'材料中的争议。','people':[],
      'chapters':[{'title':'经过','paragraphs':[{'text':'甲提出陈述。','source_ids':['M1']}],
       'quote_text':'我付了钱','quote_speaker':'甲','quote_source_id':'M1','image_id':'','image_caption':''}],
      'verdict_title':'判断','verdict':'仍需核对。','verdict_source_ids':['M1'],'open_questions':['凭证在哪？']}


def story():
    return {'central_question':'款项是否已支付？','arc':[{'stage':'提出争议','happened':'甲说付过款。',
        'changed':'双方需要核对凭证。','order_basis':'当事人回述','source_ids':['M1']}],
        'threads':[],'timeline_note':'只有单方叙述，没有完整时间线。'}


class ReaderTests(unittest.TestCase):
    def setUp(self):self.messages=normalize_messages([{'id':'M1','text':'我付了钱','speaker':'甲'}])
    def test_fabricated_quote_rejected(self):
        r=reader();r['chapters'][0]['quote_text']='我没有付钱'
        with self.assertRaisesRegex(ValueError,'原话'):validate_reader(r,self.messages)
    def test_fake_image_rejected(self):
        r=reader();r['chapters'][0]['image_id']='M1'
        with self.assertRaisesRegex(ValueError,'图片'):validate_reader(r,self.messages)
    def test_story_requires_sources(self):
        r=reader();r['story']=story();r['story']['arc'][0]['source_ids']=[]
        with self.assertRaisesRegex(ValueError,'缺少来源'):validate_reader(r,self.messages)
    def test_story_does_not_allow_invented_source(self):
        r=reader();r['story']=story();r['story']['arc'][0]['source_ids']=['absent']
        with self.assertRaisesRegex(ValueError,'不存在'):validate_reader(r,self.messages)
    def test_story_order_basis_is_explicit(self):
        r=reader();r['story']=story();r['story']['arc'][0]['order_basis']='模型猜测为确定事实'
        with self.assertRaisesRegex(ValueError,'选项'):validate_reader(r,self.messages)
    def test_standalone_html_embeds_image_and_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'uploads').mkdir();(root/'uploads'/'sample.png').write_bytes(b'png-content')
            m=copy.deepcopy(self.messages);m[0]['image']='sample.png'
            r=reader();r['title']='<script>bad()</script>';r['chapters'][0]['image_id']='M1'
            with patch.object(report,'DATA',root):
                html=report.report_html({'messages':m},{'report':{'reader':r},'created_at':'2026-11-14T00:00:00+08:00'})
            self.assertIn('data:image/png;base64,',html)
            self.assertNotIn('src="/media/',html);self.assertNotIn('<script>',html)
    def test_parent_cycles_rejected(self):
        with self.assertRaisesRegex(ValueError,'循环'):
            normalize_messages([{'id':'A','text':'a','parent_id':'B'},{'id':'B','text':'b','parent_id':'A'}])
    def test_original_appendix_links_and_scope(self):
        rows=normalize_messages([{'id':'parent','text':'原始容器','speaker':'甲'},
            {'id':'M1','parent_id':'parent','text':'完整原文 <script>不能执行</script>\n第二行','speaker':'乙'},
            {'id':'unrelated','text':'无关私人聊天'},
            {'id':'arc-only','text':'仅主线引用的原文'}])
        r=reader();r['story']=story();r['story']['arc'][0]['source_ids']=['arc-only']
        case={'messages':rows};before=copy.deepcopy(case)
        html=report.reader_html(case,{'report':{'reader':r},'created_at':'2026-11-14T00:00:00Z'})
        self.assertEqual([m['id'] for m in report.cited_sources(case,r)],['parent','M1','arc-only'])
        self.assertIn('href="#source-M002"',html);self.assertIn('id="source-M002"',html)
        self.assertIn('原始容器',html);self.assertIn('仅主线引用的原文',html)
        self.assertIn('&lt;script&gt;不能执行&lt;/script&gt;\n第二行',html)
        self.assertNotIn('无关私人聊天',html);self.assertEqual(before,case)
    def test_appendix_missing_image_and_pdf_destinations(self):
        from pypdf import PdfReader
        rows=copy.deepcopy(self.messages)
        rows[0]['text']='原始材料的完整末尾。'
        rows[0]['source_reference']={'media':[{'status':'unavailable','reason':'missingImage'}]}
        r=reader();r['chapters'][0]['quote_text']=''
        case={'messages':rows};run={'report':{'reader':r},'created_at':'2026-11-14T00:00:00Z'}
        with tempfile.TemporaryDirectory() as d:
            full=Path(d)/'full.pdf';body=Path(d)/'body.pdf'
            report.report_pdf(case,run,full)
            report.report_pdf(case,run,body,include_sources=False)
            pdf=PdfReader(full);draft=PdfReader(body)
            text=''.join(p.extract_text() for p in pdf.pages)
            self.assertIn('原文附录',text);self.assertIn('原始材料的完整末尾。',text)
            self.assertIn('导出包中没有找到对应图片',text)
            self.assertNotIn('原文附录\n以下保留',''.join(p.extract_text() for p in draft.pages))
            self.assertGreater(len(pdf.pages),len(draft.pages))
            links=[a.get_object() for page in pdf.pages for a in page.get('/Annots',[]) if a.get_object().get('/Subtype')=='/Link']
            self.assertTrue(links)
            for link in links:
                destination=link['/Dest'][0]
                page=next(p for p in pdf.pages if p.indirect_reference==destination)
                self.assertIn('原始材料的完整末尾。',page.extract_text())
    def test_editor_layout_does_not_count_original_appendix(self):
        from chigua.editor import layout_probe
        with patch.object(report,'pdf_fonts'),patch.object(report,'report_pdf',return_value={'pages':3}) as render:
            result=layout_probe({'messages':self.messages},{},reader(),Path('unused.pdf'))
        self.assertEqual(result['pages'],3)
        self.assertIs(render.call_args.kwargs['include_sources'],False)
    def test_supplemented_screenshot_is_embedded_and_identified(self):
        from PIL import Image
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'uploads').mkdir()
            Image.new('RGB',(100,60),'blue').save(root/'uploads'/'image.png')
            messages=copy.deepcopy(self.messages);messages[0]['image']='image.png'
            messages[0]['source_reference']={'supplement':{'kind':'screenshot','method':'user_confirmed'}}
            r=reader();r['chapters'][0]['image_id']='M1';r['chapters'][0]['image_caption']='合成测试图'
            case={'messages':messages};run={'report':{'reader':r},'created_at':'2026-11-14T00:00:00Z'}
            with patch.object(report,'DATA',root):
                html=report.reader_html(case,run)
                report.report_pdf(case,run,root/'report.pdf')
            self.assertIn('后补截图',html);self.assertIn('data:image/png;base64,',html)
            pdf=PdfReader(root/'report.pdf');text=''.join(page.extract_text() for page in pdf.pages)
            self.assertIn('后补截图',text);self.assertIn('并非原 ZIP 随附',text)
            self.assertTrue(any(page.get('/Resources',{}).get('/XObject') for page in pdf.pages))
    def test_siblings_inherit_container_source(self):
        rows=normalize_messages([{'id':'A','source_name':'container','children':[
            {'id':'B','text':'b','source_name':'override'}, {'id':'C','text':'c'}]}])
        self.assertEqual(rows[2]['source_name'],'container')
    def test_ocr_timeout_preserves_image_workflow(self):
        import subprocess
        with patch('pathlib.Path.exists',return_value=True),patch.object(mac.subprocess,'run',side_effect=subprocess.TimeoutExpired('ocr',90)):
            lines,note=mac.ocr(Path('example.png'))
        self.assertEqual(lines,[]);self.assertIn('保留原图',note)
    def test_pdf_counts_overview_overflow_instead_of_claiming_first_page(self):
        try:
            report.pdf_fonts()
            from pypdf import PdfReader
        except (ImportError,ValueError):self.skipTest('PDF runtime not available')
        r=reader();r['story']=story()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'layout.pdf'
            case={'messages':self.messages};run={'report':{'reader':r},'created_at':'2026-11-14T00:00:00Z'}
            metrics=report.report_pdf(case,run,path)
            self.assertEqual(metrics['overview_pages'],1)
            self.assertEqual(metrics['pages'],len(PdfReader(path).pages))
            r['story']['arc']=[dict(r['story']['arc'][0]) for _ in range(10)]
            metrics=report.report_pdf(case,run,path)
            self.assertGreater(metrics['overview_pages'],1)


if __name__=='__main__':unittest.main()
