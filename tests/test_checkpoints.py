import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import provider,pipeline,core,editor
from chigua.checkpoints import CallFailure,usage_summary
from test_provider import Response
from test_core import valid_report
from test_editor import candidate,plan,review

ENV={'CHIGUA_PROVIDER':'deepseek','CHIGUA_MODEL':'synthetic-model','CHIGUA_BASE_URL':'https://example.test/v1','CHIGUA_API_KEY':'private-test-key'}
STATS={'provider':'deepseek','model':'synthetic-model','seconds':1,'usage':{'prompt_tokens':10,'completion_tokens':5},'cost':None}

class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'runs'/'one'
        self.patches=[patch.dict(os.environ,ENV),patch.object(provider,'DATA',self.root),patch.object(pipeline,'DATA',self.root)]
        for p in self.patches:p.start()
        pipeline.JOBS.clear()
    def tearDown(self):
        pipeline.JOBS.clear()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def generate(self,prompt='json',schema=None,images=()):return provider.generate(prompt,schema,self.folder,'stage',images)
    def test_completed_step_is_zero_request_cache_and_changed_inputs_invalidate(self):
        with patch.object(provider,'_generate_once',return_value=({'ok':1},STATS)) as gen:
            a=self.generate();b=self.generate()
            self.assertFalse(a[1]['cached']);self.assertTrue(b[1]['cached']);self.assertEqual(gen.call_count,1)
            self.generate('changed');self.assertEqual(gen.call_count,2)
            with patch.dict(os.environ,{'CHIGUA_MODEL':'other'}):self.generate();self.assertEqual(gen.call_count,3)
            with patch.dict(os.environ,{'CHIGUA_BASE_URL':'https://different.test'}):self.generate();self.assertEqual(gen.call_count,4)
            self.generate(schema={'type':'object'});self.assertEqual(gen.call_count,5)
    def test_image_bytes_in_cache_key_and_missing_images_stop_before_call(self):
        (self.root/'uploads').mkdir();img=self.root/'uploads'/'a.png';img.write_bytes(b'first')
        with patch.object(provider,'_generate_once',return_value=({},STATS)) as gen:
            self.generate(images=['a.png']);img.write_bytes(b'second');self.generate(images=['a.png'])
            self.assertEqual(gen.call_count,2);img.unlink()
            with self.assertRaisesRegex(ValueError,'图片缺失'):self.generate(images=['a.png'])
            self.assertEqual(gen.call_count,2)
    def test_429_retries_bounded_and_records_every_attempt(self):
        with patch.object(provider,'_generate_once',side_effect=[CallFailure('limited',kind='429',retryable=True),({},STATS)]) as gen,patch('chigua.checkpoints.time.sleep') as sleep:
            self.generate();self.assertEqual(gen.call_count,2);sleep.assert_called_once()
        self.assertEqual(usage_summary(self.folder)['requests'],2)
    def test_auth_timeout_bad_json_do_not_automatically_retry(self):
        for err in [CallFailure('auth',kind='401'),CallFailure('timeout',kind='timeout',uncertain=True),ValueError('bad json')]:
            with patch.object(provider,'_generate_once',side_effect=err) as gen:
                with self.assertRaises(type(err)):self.generate(prompt=str(err))
                self.assertEqual(gen.call_count,1)
    def test_request_budget_survives_repeated_resume(self):
        core.write_json(self.folder/'manifest.json',{'max_requests':2})
        with patch.object(provider,'_generate_once',side_effect=CallFailure('outage',retryable=True)),patch('chigua.checkpoints.time.sleep'):
            with self.assertRaisesRegex(CallFailure,'请求上限'):self.generate()
        with patch.object(provider,'_generate_once') as gen:
            with self.assertRaisesRegex(CallFailure,'请求上限'):self.generate()
            gen.assert_not_called()
    def test_corrupted_cache_stops_without_paid_request(self):
        with patch.object(provider,'_generate_once',return_value=({},STATS)):self.generate()
        cache=next(self.folder.rglob('completed.json'));cache.write_text('{broken')
        with patch.object(provider,'_generate_once') as gen:
            with self.assertRaisesRegex(CallFailure,'缓存损坏'):self.generate()
            gen.assert_not_called()
    def test_crash_inflight_requires_explicit_retry(self):
        with patch.object(provider,'_generate_once',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.generate()
        with patch.object(provider,'_generate_once',return_value=({},STATS)) as gen:
            with self.assertRaisesRegex(CallFailure,'计费未知'):self.generate()
            gen.assert_not_called()
            core.write_json(self.folder/'manifest.json',{'max_requests':4,'retry_uncertain':True})
            self.generate();self.assertEqual(gen.call_count,1)
    def test_usage_retained_for_invalid_paid_output_and_no_secret_logged(self):
        obj={'choices':[{'finish_reason':'length','message':{'content':'{"unfinished":'}}],'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':50}}
        with patch('urllib.request.urlopen',return_value=Response(json.dumps(obj).encode())):
            with self.assertRaisesRegex(RuntimeError,'长度上限'):self.generate(schema={'type':'object'})
        usage=usage_summary(self.folder);self.assertEqual(usage['input_tokens'],100);self.assertEqual(usage['output_tokens'],20);self.assertEqual(usage['cached_input_tokens'],50)
        self.assertEqual(usage['unknown_usage_requests'],0)
        for p in self.folder.rglob('*.json'):self.assertNotIn(ENV['CHIGUA_API_KEY'],p.read_text());self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_no_partial_json_after_atomic_replacement(self):
        path=self.folder/'job.json';core.write_json(path,{'a':1});core.write_json(path,{'b':2})
        self.assertEqual(json.loads(path.read_text()),{'b':2});self.assertEqual(list(self.folder.glob('*.tmp')),[])
    def test_pipeline_restart_resume_skips_paid_analysis_and_completed_editor_steps(self):
        messages=core.normalize_messages([{'id':'M1','speaker':'甲','text':'我付了钱'}])
        case={'id':'synthetic','messages':messages,'input_hash':core.fingerprint(messages)}
        called=[];fail=[True]
        def once(prompt,schema,folder,stage,images):
            called.append(stage)
            if stage=='editor_draft' and fail[0]:fail[0]=False;raise CallFailure('timeout',kind='timeout',uncertain=True)
            value={'B1':json.loads(json.dumps(valid_report()).replace('M0001','M1')),'editor_plan':plan(),'editor_draft':candidate(),'editor_review_0':review()}[stage]
            core.write_json(folder/'usage.json',STATS['usage'])
            return copy.deepcopy(value),STATS
        with patch.object(provider,'_generate_once',side_effect=once),patch.object(editor,'layout_probe',return_value={'status':'checked','pages':2,'overview_pages':1}):
            job=pipeline.start(case,'B1',background=False);jid=job['id']
            self.assertEqual(job['status'],'failed');self.assertTrue(job['uncertain'])
            pipeline.JOBS.clear() # Simulate server restart: no in-memory progress remains.
            self.assertEqual(pipeline.get_job(jid)['status'],'failed')
            same=pipeline.start(case,'B1',background=False);self.assertEqual(same['id'],jid)
            with self.assertRaisesRegex(ValueError,'可能已计费'):pipeline.resume(jid,background=False)
            completed=pipeline.resume(jid,allow_uncertain=True,background=False)
            self.assertEqual(completed['status'],'completed',completed)
            self.assertEqual(called,['B1','editor_plan','editor_draft','editor_draft','editor_review_0'])
            self.assertEqual(completed['usage']['requests'],5)
            self.assertEqual(completed['usage']['input_tokens'],40)
            self.assertEqual(completed['usage']['unknown_usage_requests'],1)
            self.assertEqual(pipeline.start(case,'B1',background=False)['id'],jid)
            self.assertEqual(len(called),5)
    def test_resume_blocks_changed_model_and_preserves_failed_run(self):
        case={'id':'synthetic','messages':[],'input_hash':'test'}
        with patch.object(provider,'_generate_once',side_effect=CallFailure('auth')):
            j=pipeline.start(case,'B1',background=False)
        with patch.dict(os.environ,{'CHIGUA_MODEL':'changed'}),patch.object(provider,'_generate_once') as gen:
            with self.assertRaisesRegex(ValueError,'已改变'):pipeline.resume(j['id'],background=False)
            gen.assert_not_called()
        self.assertTrue((self.root/'runs'/j['id']/'failure.json').exists())

    def test_received_response_recovered_after_crash_without_new_call(self):
        def crash(prompt,schema,folder,stage,images):
            obj={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':STATS['usage']}
            core.write_json(folder/'raw-response.json',obj);core.write_json(folder/'usage.json',STATS['usage'])
            raise KeyboardInterrupt()
        with patch.object(provider,'_generate_once',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):self.generate(schema={'type':'object'})
        with patch.object(provider,'_generate_once') as gen:
            value,stats=self.generate(schema={'type':'object'})
            self.assertTrue(value['ok']);self.assertTrue(stats['recovered_response']);gen.assert_not_called()
        self.assertEqual(usage_summary(self.folder)['requests'],1)
    def test_nullable_or_partial_provider_usage_remains_honest(self):
        for index,u in enumerate([{'prompt_tokens':5,'completion_tokens':3,'prompt_tokens_details':None},{'total_tokens':9},{}]):
            p=self.folder/'.calls'/'test'/f'attempt-{index}'
            core.write_json(p/'attempt.json',{'status':'completed'});core.write_json(p/'usage.json',u)
        result=usage_summary(self.folder)
        self.assertEqual(result['input_tokens'],5);self.assertEqual(result['output_tokens'],3)
        self.assertEqual(result['unknown_usage_requests'],2);self.assertEqual(result['cached_input_tokens'],0)
    def test_reasoning_usage_is_a_subset_of_output_not_added_twice(self):
        p=self.folder/'.calls'/'reasoning'/'attempt-0001'
        core.write_json(p/'attempt.json',{'status':'failed'})
        core.write_json(p/'usage.json',{'prompt_tokens':10,'completion_tokens':12000,'completion_tokens_details':{'reasoning_tokens':12000}})
        usage=usage_summary(self.folder)
        self.assertEqual(usage['output_tokens'],12000)
        self.assertEqual(usage['reasoning_tokens'],12000)
        self.assertEqual(usage['unknown_usage_requests'],0)
    def test_fixed_local_parser_recovers_failed_paid_response_without_network(self):
        schema={'type':'object','properties':{'image_id':{'type':'string'}},'required':['image_id']}
        obj={'choices':[{'finish_reason':'stop','message':{'content':'{"image_id":null}'}}],
             'usage':{'prompt_tokens':10,'completion_tokens':5}}
        with patch('chigua.provider.normalize_empty_presentation',side_effect=lambda v,s:(v,[])),patch('urllib.request.urlopen',return_value=Response(json.dumps(obj).encode())):
            with self.assertRaises(ValueError):self.generate(schema=schema)
        with patch.object(provider,'_generate_once') as gen:
            value,stats=self.generate(schema=schema)
            gen.assert_not_called();self.assertEqual(value,{'image_id':''});self.assertTrue(stats['recovered_response'])
        self.assertEqual(usage_summary(self.folder)['requests'],1)
    def test_rotated_key_reuses_completed_result_and_never_stores_secret(self):
        with patch.object(provider,'_generate_once',return_value=({},STATS)) as gen:
            self.generate()
            with patch.dict(os.environ,{'CHIGUA_API_KEY':'replacement-key'}):self.generate()
            self.assertEqual(gen.call_count,1)
        for p in self.folder.rglob('*.json'):self.assertNotIn('replacement-key',p.read_text())
    def test_api_http_retry_classification_and_limit(self):
        import urllib.error
        for code,expected in [(429,3),(503,3),(400,1),(401,1),(402,1),(504,1)]:
            with self.subTest(code=code),patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://example.test',code,'private upstream text',{},None)) as http,patch('chigua.checkpoints.time.sleep'):
                with self.assertRaisesRegex(CallFailure,str(code)) as error:self.generate(prompt=str(code))
                self.assertEqual(http.call_count,expected);self.assertNotIn('private upstream text',str(error.exception))
    def test_retry_after_long_delay_stops_instead_of_ignoring_header(self):
        import urllib.error
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://example.test',429,'limited',{'Retry-After':'90'},None)) as http,patch('chigua.checkpoints.time.sleep') as sleep:
            with self.assertRaises(CallFailure):self.generate()
            self.assertEqual(http.call_count,1);sleep.assert_not_called()
    def test_inflight_disk_state_is_visible_after_restart_without_requests(self):
        core.write_json(self.folder/'job.json',{'id':'one','case_id':'synthetic','status':'running','stage':'editor_draft'})
        with patch.object(provider,'generate') as gen:
            job=pipeline.get_job('one');self.assertEqual(job['status'],'interrupted');self.assertTrue(job['uncertain'])
            self.assertEqual(len(pipeline.list_jobs('synthetic')),1);gen.assert_not_called()
    def test_cached_steps_do_not_consume_exhausted_request_budget(self):
        core.write_json(self.folder/'manifest.json',{'max_requests':1})
        with patch.object(provider,'_generate_once',return_value=({},STATS)) as gen:
            self.generate();self.generate();self.assertEqual(gen.call_count,1)
            with self.assertRaisesRegex(CallFailure,'请求上限'):self.generate('new request')
    def test_concurrent_same_task_never_dispatches_second_paid_request(self):
        import threading
        entered=threading.Event();release=threading.Event();errors=[]
        def slow(*args):entered.set();release.wait(3);return {},STATS
        def first():
            try:self.generate()
            except Exception as exc:errors.append(exc)
        with patch.object(provider,'_generate_once',side_effect=slow) as gen:
            worker=threading.Thread(target=first);worker.start();self.assertTrue(entered.wait(2))
            try:
                with self.assertRaisesRegex(CallFailure,'正在处理'):self.generate()
            finally:release.set();worker.join(3)
            self.assertEqual(gen.call_count,1);self.assertFalse(errors)

if __name__=='__main__':unittest.main()
