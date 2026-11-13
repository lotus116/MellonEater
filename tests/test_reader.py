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


class ReaderTests(unittest.TestCase):
    def setUp(self):self.messages=normalize_messages([{'id':'M1','text':'我付了钱','speaker':'甲'}])
    def test_fabricated_quote_rejected(self):
        r=reader();r['chapters'][0]['quote_text']='我没有付钱'
        with self.assertRaisesRegex(ValueError,'原话'):validate_reader(r,self.messages)
    def test_fake_image_rejected(self):
        r=reader();r['chapters'][0]['image_id']='M1'
        with self.assertRaisesRegex(ValueError,'图片'):validate_reader(r,self.messages)
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
    def test_siblings_inherit_container_source(self):
        rows=normalize_messages([{'id':'A','source_name':'container','children':[
            {'id':'B','text':'b','source_name':'override'}, {'id':'C','text':'c'}]}])
        self.assertEqual(rows[2]['source_name'],'container')
    def test_ocr_timeout_preserves_image_workflow(self):
        import subprocess
        with patch('pathlib.Path.exists',return_value=True),patch.object(mac.subprocess,'run',side_effect=subprocess.TimeoutExpired('ocr',90)):
            lines,note=mac.ocr(Path('example.png'))
        self.assertEqual(lines,[]);self.assertIn('保留原图',note)


if __name__=='__main__':unittest.main()
