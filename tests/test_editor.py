import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import editor
from chigua.core import normalize_messages
from test_reader import reader,story
from test_core import valid_report


def candidate():
    r=reader();r['story']=story();return r


def plan():
    return {'mode':'fragmentary','focus_event_ids':['E1'],'separate_event_ids':[],
        'excluded_events':[],'story':story(),'ending':{'text':'没有后续','source_ids':['M1']},'risks':[]}


def review(ok=True):
    r={'decision':'pass' if ok else 'revise','checks':{n:'pass' for n in editor.DIMENSIONS},'issues':[]}
    if not ok:
        r['checks']['chronology']='revise'
        r['issues']=[{'dimension':'chronology','location':'主线','problem':'只有回述却写为确切先后',
            'source_ids':['M1'],'fix':'标记回述并保留未知'}]
    return r


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.case={'messages':normalize_messages([{'id':'M1','speaker':'甲','text':'我付了钱','image':'synthetic.png'}])}
        self.analysis=valid_report()
        self.layout=patch.object(editor,'layout_probe',return_value={'status':'checked','pages':2,'overview_pages':1})
        self.layout_mock=self.layout.start()
    def tearDown(self):self.layout.stop();self.tmp.cleanup()
    def run_edit(self,outputs):
        def generate(*args):return copy.deepcopy(next(outputs)),{'provider':'mock','model':'mock','seconds':0}
        with patch.object(editor.provider,'generate',side_effect=generate) as gen:
            result=editor.edit_report(self.case,self.analysis,self.folder)
        return result,gen
    def test_clean_pass_includes_originals_in_every_call_and_keeps_analysis(self):
        before=copy.deepcopy(self.analysis)
        result,gen=self.run_edit(iter([plan(),candidate(),review()]))
        self.assertEqual(result['quality']['revisions'],0);self.assertEqual(self.analysis,before)
        self.assertEqual([c.args[3] for c in gen.call_args_list],['editor_plan','editor_draft','editor_review_0'])
        for call in gen.call_args_list:
            self.assertIn('我付了钱',call.args[0]);self.assertEqual(call.args[4],['synthetic.png'])
        self.assertTrue((self.folder/'accepted.json').exists())
    def test_semantic_repair_is_automatically_reviewed_again(self):
        result,gen=self.run_edit(iter([plan(),candidate(),review(False),candidate(),review()]))
        self.assertEqual(result['quality']['revisions'],1)
        self.assertEqual(gen.call_args_list[-2].args[3],'editor_rewrite_1')
        self.assertIn('只有回述',gen.call_args_list[-2].args[0])
        self.assertEqual(gen.call_args_list[-1].args[3],'editor_review_1')
    def test_invalid_reference_is_repaired_before_semantic_review(self):
        bad=candidate();bad['chapters'][0]['paragraphs'][0]['source_ids']=['MISSING']
        result,gen=self.run_edit(iter([plan(),bad,candidate(),review()]))
        self.assertEqual(result['quality']['revisions'],1)
        self.assertNotIn('editor_review_0',[c.args[3] for c in gen.call_args_list])
        self.assertIn('MISSING',gen.call_args_list[2].args[0])
    def test_pure_layout_failure_never_pays_for_prose_rewrite(self):
        self.layout_mock.return_value={'status':'checked','pages':3,'overview_pages':2}
        with self.assertRaisesRegex(RuntimeError,'排版需要调整'):
            self.run_edit(iter([plan(),candidate(),review()]))
        trace=json.loads((self.folder/'trace.json').read_text())
        self.assertEqual([t['stage'] for t in trace],['editor_plan','editor_draft','editor_review_0'])
        self.assertTrue((self.folder/'layout-pending.json').exists())
        self.assertFalse((self.folder/'accepted.json').exists())
    def test_exhausted_rewrites_do_not_publish(self):
        with self.assertRaisesRegex(ValueError,'两轮返修'):
            self.run_edit(iter([plan(),candidate(),review(False),candidate(),review(False),candidate(),review(False)]))
        self.assertFalse((self.folder/'accepted.json').exists());self.assertTrue((self.folder/'rejected.json').exists())
        trace=json.loads((self.folder/'trace.json').read_text());self.assertEqual(len(trace),7)
    def test_small_trailing_page_does_not_spend_tokens_rewriting_approved_text(self):
        self.layout_mock.return_value={'status':'checked','pages':3,'overview_pages':1,'last_page_fill':.1}
        result,gen=self.run_edit(iter([plan(),candidate(),review()]))
        self.assertEqual(result['quality']['revisions'],0);self.assertEqual(gen.call_count,3)
    def test_length_error_repaired_before_paid_semantic_review(self):
        bad=candidate();bad['lead']='长'*170
        result,gen=self.run_edit(iter([plan(),bad,candidate(),review()]))
        self.assertEqual(result['quality']['revisions'],1)
        self.assertNotIn('editor_review_0',[c.args[3] for c in gen.call_args_list])
    def test_pass_label_cannot_override_issues(self):
        r=review(False);r['decision']='pass';r['checks']['chronology']='pass'
        self.assertFalse(editor.validate_review(r,self.case['messages']))
    def test_factual_feedback_needs_sources(self):
        r=review(False);r['issues'][0]['source_ids']=[]
        with self.assertRaisesRegex(ValueError,'对应材料'):editor.validate_review(r,self.case['messages'])
    def test_all_events_must_have_a_place(self):
        analysis=copy.deepcopy(self.analysis);analysis['events'].append({**analysis['events'][0],'id':'E2'})
        with self.assertRaisesRegex(ValueError,'遗漏'):editor.validate_plan(plan(),analysis,self.case['messages'])
        p=plan();p['separate_event_ids']=['E2'];p['mode']='parallel_events'
        editor.validate_plan(p,analysis,self.case['messages'])
    def test_short_material_does_not_require_fake_phases_or_threads(self):
        self.assertEqual(editor.reader_issues(candidate(),self.case['messages']),[])
    def test_invalid_plan_has_one_bounded_repair(self):
        bad=plan();bad['focus_event_ids']=['absent']
        result,gen=self.run_edit(iter([bad,plan(),candidate(),review()]))
        self.assertEqual(gen.call_args_list[1].args[3],'editor_plan_repair')
        self.assertEqual(result['quality']['status'],'passed')


if __name__=='__main__':unittest.main()
