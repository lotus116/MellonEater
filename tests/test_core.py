import copy
import json
import unittest
from chigua.core import normalize_messages, parse_text, parse_import, validate_report, fingerprint
from chigua.report import report_html


def valid_report():
    return {'title':'示例','summary':'某人提出了一项尚未证明的说法。',
      'events':[{'id':'E1','title':'分配争议','summary':'双方争论规则。','message_ids':['M0001']}],
      'claims':[{'id':'C1','event_id':'E1','statement':'钱被故意扣留','claimant':'甲','kind':'事实',
      'status':'无法判断','support_ids':['M0001'],'conflict_ids':[],
      'source_note':'仅有甲的陈述','reason':'缺少付款凭证。','standard':'记录内支持',
      'unknowns':['到账时间'],'would_change_if':'提供付款记录。'}],
      'timeline':[],'limitations':['只有一段文字。']}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.messages=parse_text('【甲】：他没有给我钱。')
    def test_no_invented_time(self):
        rows=parse_text('【甲】：第一段\n\n第二段\n【乙】：回复')
        self.assertEqual([m['speaker'] for m in rows],['甲','甲','乙'])
        self.assertTrue(all(m['timestamp'] is None for m in rows))
        self.assertEqual(rows[0]['unit'],'段落摘录')
    def test_timestamped_input(self):
        rows=parse_text('[2026-11-14 09:30] 甲：收到\n[2026-11-14 09:31] 乙：好的')
        self.assertEqual(rows[1]['speaker'],'乙')
        self.assertEqual(rows[0]['timestamp'],'2026-11-14 09:30')
    def test_nested_forward_keeps_original_times(self):
        rows=normalize_messages([{'id':'F1','speaker':'分享者','timestamp':'2026-11-14','text':'转发',
            'children':[{'id':'A1','speaker':'图内甲','timestamp':'2026-10-01','text':'原始内容'}]}])
        self.assertEqual(rows[1]['parent_id'],'F1')
        self.assertEqual(rows[1]['timestamp'],'2026-10-01')
        self.assertNotEqual(rows[0]['speaker'],rows[1]['speaker'])
    def test_repeated_text_not_assumed_independent_or_deduplicated(self):
        rows=normalize_messages([{'speaker':'甲','text':'听说他拿了钱'},{'speaker':'乙','text':'听说他拿了钱'}])
        self.assertEqual(len(rows),2)
        self.assertTrue(all(m['source_root'] is None for m in rows))
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError): normalize_messages([{'id':'X','text':'a'},{'id':'X','text':'b'}])
    def test_missing_parent_rejected(self):
        with self.assertRaises(ValueError): normalize_messages([{'text':'x','parent_id':'absent'}])
    def test_missing_citation_rejected(self):
        r=valid_report(); r['claims'][0]['support_ids']=['M9999']
        with self.assertRaisesRegex(ValueError,'不存在'):validate_report(r,self.messages)
    def test_valid_citation_does_not_certify_semantics(self):
        c=validate_report(valid_report(),self.messages)
        self.assertEqual(c['semantic_check'],'needs_human_review')
        self.assertEqual(c['reference_check'],'passed')
    def test_supported_claim_needs_evidence(self):
        r=valid_report();r['claims'][0]['status']='有依据';r['claims'][0]['support_ids']=[]
        with self.assertRaises(ValueError):validate_report(r,self.messages)
    def test_evaluation_requires_standard(self):
        r=valid_report();r['claims'][0]['kind']='行为评价';r['claims'][0]['standard']=''
        with self.assertRaises(ValueError):validate_report(r,self.messages)
    def test_empty_analysis_not_success(self):
        r=valid_report();r['claims']=[]
        with self.assertRaises(ValueError):validate_report(r,self.messages)
    def test_report_escapes_untrusted_html(self):
        r=valid_report();r['summary']='<script>alert(1)</script>'
        result=report_html({'messages':self.messages}, {'report':r,'created_at':'now','method':'B1','origin':'test'})
        self.assertNotIn('<script>alert',result);self.assertIn('&lt;script&gt;',result)
    def test_input_fingerprint_changes(self):
        m=copy.deepcopy(self.messages);m[0]['text']='changed'
        self.assertNotEqual(fingerprint(m),fingerprint(self.messages))
    def test_json_import_keeps_identity_and_root(self):
        rows=parse_import(json.dumps({'messages':[{'id':'A','speaker':'转述者','text':'说法','source_root':'外部未知原帖'}]}),'x.json')
        self.assertEqual(rows[0]['source_root'],'外部未知原帖')


if __name__=='__main__':unittest.main()
