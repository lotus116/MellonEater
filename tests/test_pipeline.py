import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from chigua import pipeline
from chigua.core import fingerprint,parse_text
from test_core import valid_report


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patch=patch.object(pipeline,'DATA',self.root);self.patch.start()
        self.messages=parse_text('【甲】：他没有给我钱。')
        self.case={'id':'synthetic','messages':self.messages,'input_hash':fingerprint(self.messages)}
        pipeline.JOBS.clear();pipeline.JOBS['test']={'id':'test','status':'running'}
    def tearDown(self):
        pipeline.JOBS.clear();self.patch.stop();self.tmp.cleanup()
    def test_four_stages_keep_original_input(self):
        stats={'provider':'test','model':'test','seconds':0,'usage':None,'cost':None}
        from test_reader import reader,story
        r=reader();r['story']=story()
        report=valid_report();report['reader']=json.loads(json.dumps(r,ensure_ascii=False).replace('M1','M0001').replace('我付了钱','他没有给我钱'))
        with patch.object(pipeline.provider,'generate',return_value=(report,stats)) as gen:
            pipeline.run_pipeline('test',self.case,'B2')
        self.assertEqual([c.args[3] for c in gen.call_args_list],['discover','evidence','assess','review'])
        self.assertEqual(pipeline.JOBS['test']['status'],'completed')
        self.assertEqual(json.loads((self.root/'runs/test/input.json').read_text()),self.case)
        self.assertEqual(len(pipeline.JOBS['test']['result']['trace']),4)
    def test_failure_does_not_become_success(self):
        with patch.object(pipeline.provider,'generate',side_effect=RuntimeError('simulated outage')):
            pipeline.run_pipeline('test',self.case,'B1')
        self.assertEqual(pipeline.JOBS['test']['status'],'failed')
        self.assertTrue((self.root/'runs/test/failure.json').exists())
        self.assertFalse((self.root/'runs/test/result.json').exists())
    def test_invalid_citations_do_not_become_success(self):
        from test_reader import reader,story
        r=reader();r['story']=story()
        report=valid_report();report['reader']=json.loads(json.dumps(r,ensure_ascii=False).replace('M1','M0001').replace('我付了钱','他没有给我钱'));report['claims'][0]['support_ids']=['missing']
        with patch.object(pipeline.provider,'generate',return_value=(report,{})):
            pipeline.run_pipeline('test',self.case,'B1')
        self.assertEqual(pipeline.JOBS['test']['status'],'failed')
        self.assertFalse((self.root/'runs/test/result.json').exists())
    def test_missing_reader_does_not_become_published_report(self):
        with patch.object(pipeline.provider,'generate',return_value=(valid_report(),{})):
            pipeline.run_pipeline('test',self.case,'B1')
        self.assertEqual(pipeline.JOBS['test']['status'],'failed')
        self.assertIn('reader',pipeline.JOBS['test']['error'])
    def test_active_job_prevents_concurrent_start(self):
        with patch.object(pipeline.provider,'status',return_value={'available':True}):
            with self.assertRaisesRegex(ValueError,'已有分析'):pipeline.start(self.case,'B1')


if __name__=='__main__':unittest.main()
