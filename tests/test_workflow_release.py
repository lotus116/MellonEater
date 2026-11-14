"""Exercise HTTP provider, cached stages, publication and recovery together."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chigua import core, evidence_first, pipeline, provider, report
from chigua.checkpoints import usage_summary
from test_evidence_first import dispute, event, ledger, prose
from test_provider import Response


class WorkflowReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = {'CHIGUA_PROVIDER':'deepseek','CHIGUA_MODEL':'fixture-model',
                       'CHIGUA_API_KEY':'fixture-key','CHIGUA_BASE_URL':'https://example.test'}
        env = patch.dict(os.environ,environment,clear=True)
        env.start()
        self.addCleanup(env.stop)
        for module in (pipeline,provider,report):
            change = patch.object(module,'DATA',self.root)
            change.start()
            self.addCleanup(change.stop)
        pipeline.JOBS.clear()
        self.addCleanup(pipeline.JOBS.clear)
        messages = core.normalize_messages([
            {'id':'A','speaker':'甲','text':'在布置群请先填写单据。'},
            {'id':'B','speaker':'甲','text':'我记得两天。'},
            {'id':'C','speaker':'乙','text':'我记得四天。'},
        ])
        self.case = {'id':'sample','messages':messages,'input_hash':core.fingerprint(messages)}
        self.binding = ledger([event('前情','S001','在布置群请先填写单据。',scene='小群',scene_quote='布置群')],
                              [{'topic':'等了多久','limit':'缺少完整凭证。',
                                'accounts':[dispute('S002','两天'),dispute('S003','四天')]}])
        self.binding['limits'] = ['什么时候到账需要补流水。']

    def response(self, value, *, finish='stop', usage=10):
        content = json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
        return Response(json.dumps({'choices':[{'finish_reason':finish,'message':{'content':content}}],
                                    'usage':{'prompt_tokens':usage,'completion_tokens':1}}).encode())

    def html(self, job):
        html = report.report_html(self.case,job['result'])
        self.assertTrue(set(re.findall(r'href="#source-([^"]+)"',html)) <=
                        set(re.findall(r'id="source-([^"]+)"',html)))
        return html

    def test_partial_payload_is_published_without_a_rewrite(self):
        incomplete = prose('S001')
        incomplete.pop('open_questions')
        incomplete['chapters'][0]['source_ids'] = ['S999']
        incomplete['chapters'][0]['paragraphs'].append({'text':'应删除的无依据断言','source_ids':['S001',None]})
        incomplete['assessment'] = None
        with patch('urllib.request.urlopen',side_effect=[
            self.response(self.binding),self.response(incomplete),
        ]) as requests:
            done = pipeline.start(self.case,background=False)
        self.assertEqual(done['status'],'completed',done.get('error'))
        self.assertEqual(requests.call_count,2)
        html = self.html(done)
        self.assertIn('双方给了不同说法',html)
        self.assertIn('两天',html)
        self.assertIn('四天',html)
        self.assertNotIn('应删除的无依据断言',html)
        self.assertEqual(done['result']['editorial_quality']['status'],'limited')

    def test_truncated_responses_publish_evidence_and_restart_offline_without_key(self):
        with patch('urllib.request.urlopen',side_effect=[
            self.response(self.binding),self.response('{"lead":',finish='length'),
            self.response('{"chapters":',finish='length'),
        ]) as requests:
            done = pipeline.start(self.case,background=False)
        self.assertEqual(requests.call_count,3)
        self.assertEqual(done['status'],'completed',done.get('error'))
        self.assertEqual(done['result']['editorial_quality']['status'],'limited')
        html = self.html(done)
        self.assertIn('阅读版未能完整生成',html)
        self.assertIn('什么时候到账需要补流水',html)
        self.assertIn('两天',html)
        self.assertIn('四天',html)
        run = self.root/'runs'/done['id']
        before = usage_summary(run)
        (run/'result.json').unlink()
        state = json.loads((run/'job.json').read_text())
        core.write_json(run/'job.json',{**state,'status':'running','stage':'compose_repair'})
        pipeline.JOBS.clear()
        with patch.dict(os.environ,{'CHIGUA_PROVIDER':'manual','CHIGUA_API_KEY':''}),              patch('urllib.request.urlopen',side_effect=AssertionError('unexpected network')) as requests:
            recovered = pipeline.resume(done['id'],background=False,local_only=True)
        requests.assert_not_called()
        self.assertEqual(recovered['status'],'completed',recovered.get('error'))
        self.assertEqual(recovered['usage'],before)
        self.assertEqual(recovered['result']['report'],done['result']['report'])

    def test_budget_keeps_evidence_visible_and_unbilled(self):
        with patch('urllib.request.urlopen',side_effect=[self.response(self.binding,usage=1000)]) as requests:
            done = pipeline.start(self.case,background=False,max_total_tokens=1000)
        self.assertEqual(requests.call_count,1)
        self.assertEqual(done['status'],'completed',done.get('error'))
        self.assertIn('token 阈值',self.html(done))
        self.assertIn('各方怎么说',self.html(done))

    def test_unknown_connection_keeps_draft_and_never_redispatches_offline(self):
        with patch('urllib.request.urlopen',side_effect=[self.response(self.binding),ConnectionError()]):
            stopped = pipeline.start(self.case,background=False)
        self.assertEqual(stopped['status'],'failed')
        self.assertTrue(stopped['uncertain'])
        self.assertTrue(stopped['draft_available'])
        run = self.root/'runs'/stopped['id']
        before = usage_summary(run)
        self.assertTrue((run/'editorial/review-draft.json').is_file())
        pipeline.JOBS.clear()
        with patch('urllib.request.urlopen',side_effect=AssertionError('unexpected network')) as net:
            resumed = pipeline.resume(stopped['id'],local_only=True,background=False)
        net.assert_not_called()
        self.assertEqual(resumed['usage'],before)
        self.assertTrue(resumed['uncertain'])
        self.assertTrue(resumed['draft_available'])

    def test_locked_worker_cannot_leave_a_ghost_job(self):
        fd = pipeline.worker_lock()
        try:
            with self.assertRaisesRegex(ValueError,'正在运行'):
                pipeline.start(self.case,background=False)
        finally:
            os.close(fd)
        self.assertEqual(list((self.root/'runs').glob('*/manifest.json')),[])

    def test_resume_cannot_change_policy_while_worker_lock_is_held(self):
        with patch('urllib.request.urlopen',side_effect=[self.response(self.binding),ConnectionError()]):
            stopped = pipeline.start(self.case,background=False)
        manifest = self.root/'runs'/stopped['id']/'manifest.json'
        before = manifest.read_bytes()
        fd = pipeline.worker_lock()
        try:
            with self.assertRaisesRegex(ValueError,'正在运行'):
                pipeline.resume(stopped['id'],local_only=True,background=False)
        finally:
            os.close(fd)
        self.assertEqual(manifest.read_bytes(),before)

    def test_source_excerpt_recovers_an_inner_scene_without_using_outer_group(self):
        event = {'source_ids':['S001'],'excerpt':'【社员群，补贴私信后半段】甲：我很难堪。乙：我只是活跃气氛。',
                 'attribution':'据负责人回述 · 协调人','mode':'后来回述','scene':'未知','kind':'事后解释'}
        data = {'events':[event]}
        result = evidence_first.publication_ledger(data,{'messages':[{'id':'S001'}]})
        self.assertEqual(result['events'][0]['scene'],'私聊')
        self.assertIn('私聊',result['events'][0]['attribution'])
        self.assertNotIn('社员群',result['events'][0]['attribution'])
