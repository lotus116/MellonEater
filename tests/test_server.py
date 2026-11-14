import json
import io
import zipfile
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from chigua import core,pipeline,server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for folder in ['cases','runs','uploads']:(self.root/folder).mkdir()
        self.patches=[patch.object(m,'DATA',self.root) for m in [core,pipeline,server]]
        self.patches.append(patch.dict(os.environ,{'CHIGUA_PROVIDER':'manual'},clear=False))
        for p in self.patches:p.start()
        pipeline.JOBS.clear()
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_port}'
    def tearDown(self):
        self.http.shutdown();self.http.server_close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def request(self,path,data=None,token=True,headers=None):
        h={'Content-Type':'application/json'}
        if token:h['X-Chigua-Token']=server.TOKEN
        h.update(headers or {})
        req=urllib.request.Request(self.base+path,data=data if isinstance(data,bytes) else json.dumps(data).encode() if data is not None else None,headers=h)
        try:
            with urllib.request.urlopen(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_import_roundtrip_and_original_immutable(self):
        status,c=self.request('/api/cases',{'title':'合成测试','text':'【甲】：声明\n\n【乙】：反驳'})
        self.assertEqual(status,201)
        code,data=self.request('/api/cases/'+c['id'])
        self.assertEqual(len(data['case']['messages']),2)
        self.assertEqual(data['case']['messages'][1]['speaker'],'乙')
        self.assertEqual(data['case']['messages'][1]['timestamp'],None)
        code,data=self.request('/api/analyze',{'case_id':c['id'],'method':'B1'})
        self.assertEqual(code,400)
        self.assertTrue((self.root/'cases'/f"{c['id']}.json").exists())
    def test_resume_endpoint_has_same_auth_and_preserves_explicit_retry_choice(self):
        payload={'job_id':'syntheticjob','allow_uncertain':True,'max_requests':25}
        with patch.object(pipeline,'resume',return_value={'id':'syntheticjob','status':'running'}) as resume:
            self.assertEqual(self.request('/api/resume',payload,token=False)[0],403);resume.assert_not_called()
            self.assertEqual(self.request('/api/resume',payload,headers={'Origin':'https://foreign.test'})[0],403);resume.assert_not_called()
            self.assertEqual(self.request('/api/resume',payload)[0],202)
            resume.assert_called_once_with('syntheticjob',allow_uncertain=True,max_requests=25)
    def test_failed_job_visible_from_disk_without_model_call(self):
        core.write_json(self.root/'runs'/'stopped'/'job.json',{'id':'stopped','case_id':'synthetic','status':'failed','stage':'B1','error':'模拟中断'})
        with patch.object(pipeline.provider,'generate') as gen:
            code,job=self.request('/api/jobs/stopped');self.assertEqual(code,200);self.assertEqual(job['status'],'failed');gen.assert_not_called()

    def test_cross_origin_and_missing_token_rejected(self):
        payload={'title':'x','text':'x'}
        self.assertEqual(self.request('/api/cases',payload,token=False)[0],403)
        self.assertEqual(self.request('/api/cases',payload,headers={'Origin':'https://example.com'})[0],403)
    def test_invalid_host_rejected(self):
        self.assertEqual(self.request('/api/config',headers={'Host':'evil.example'})[0],403)
    def test_empty_input_rejected(self):
        self.assertEqual(self.request('/api/cases',{'title':'Empty'})[0],400)
    def test_uploaded_paths_must_be_managed(self):
        result=self.request('/api/cases',{'title':'x','messages':[{'text':'x','image':'../../.env'}]})
        self.assertEqual(result[0],400)
    def test_endpoint_switch_clears_old_secret(self):
        self.request('/api/settings',{'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':'example-test-key'})
        code,config=self.request('/api/config')
        self.assertTrue(config['model']['has_key']);self.assertNotIn('example-test-key',json.dumps(config))
        self.request('/api/settings',{'provider':'api','model':'other','base_url':'https://example.com/v1'})
        self.assertFalse(self.request('/api/config')[1]['model']['has_key'])
    def test_thinking_change_preserves_secret_and_rejects_invalid_mode(self):
        settings={'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com'}
        self.request('/api/settings',{**settings,'api_key':'synthetic-secret','deepseek_thinking':'low'})
        code,result=self.request('/api/settings',{**settings,'deepseek_thinking':'disabled'})
        self.assertEqual(code,200);self.assertTrue(result['has_key'])
        self.assertEqual(result['deepseek_thinking'],'disabled')
        self.assertNotIn('synthetic-secret',json.dumps(result))
        self.assertEqual(self.request('/api/settings',{**settings,'deepseek_thinking':'invalid'})[0],400)
    def test_invalid_result_never_becomes_run(self):
        _,case=self.request('/api/cases',{'title':'x','text':'【甲】：x'})
        code,data=self.request('/api/import-result',{'case_id':case['id'],'report':{'title':'bad'}})
        self.assertEqual(code,400);self.assertEqual(list((self.root/'runs').glob('*/result.json')),[])
    def test_no_static_path_traversal(self):
        self.assertEqual(self.request('/%2e%2e/.env')[0],404)
    def zip_payload(self):
        from PIL import Image
        picture=io.BytesIO();Image.new('RGB',(10,12),'blue').save(picture,'PNG')
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w') as archive:
            archive.writestr('聊天记录.txt','·合成甲\n2026年11月1日 12:00\n正文\n\n·合成乙\n2026年11月1日 12:01\n[图片] one.png\n')
            archive.writestr('media/one.png',picture.getvalue())
        return blob.getvalue()
    def test_browser_zip_upload_import_roundtrip_no_model(self):
        code,upload=self.request('/api/wechat-zip/upload',self.zip_payload(),headers={'Content-Type':'application/zip'})
        self.assertEqual(code,201)
        file=self.root/'private/zip-uploads'/(upload['id']+'.zip')
        self.assertEqual(file.stat().st_mode&0o077,0)
        with patch('chigua.provider.generate') as generate:
            code,result=self.request('/api/wechat-zip/import',{'title':'合成 ZIP','group':'合成群','start':'2026-11-01T00:00:00+08:00','end':'2026-11-01T23:59:59+08:00','uploads':[upload['id']]})
            generate.assert_not_called()
        self.assertEqual(code,201);self.assertEqual(result['materials'],2);self.assertEqual(result['images']['available'],1)
        case=self.request('/api/cases/'+result['cases'][0]['id'])[1]['case']
        self.assertTrue((self.root/'uploads'/case['messages'][1]['image']).is_file())
        self.assertFalse(file.exists());self.assertFalse(case['capture']['cloud_analysis_started'])
    def test_zip_upload_guard_and_corrupt_file(self):
        for options in [{'token':False},{'headers':{'Origin':'https://example.com'}}]:
            self.assertEqual(self.request('/api/wechat-zip/upload',self.zip_payload(),**options)[0],403)
        self.assertEqual(self.request('/api/wechat-zip/upload',b'bad zip')[0],400)
        self.assertEqual(list((self.root/'private/zip-uploads').glob('*.zip')),[])
    def test_zip_import_rejects_local_paths_and_bad_scope(self):
        payload={'title':'Test','group':'Synthetic','start':'bad','end':'bad','uploads':['../../.env']}
        self.assertEqual(self.request('/api/wechat-zip/import',payload)[0],400)
        _,upload=self.request('/api/wechat-zip/upload',self.zip_payload())
        payload['uploads']=[upload['id']]
        self.assertEqual(self.request('/api/wechat-zip/import',payload)[0],400)
        self.assertEqual(list((self.root/'cases').glob('*.json')),[])
    def test_zip_defaults_expose_only_scope(self):
        folder=self.root/'private/wechat-setup';folder.mkdir(parents=True)
        (folder/'scope.json').write_text(json.dumps({'group_name':'合成群','start':'2026-11-01T00:00:00+08:00','end':'2026-11-02T23:59:59+08:00','private_extra':'not-returned'}))
        code,result=self.request('/api/wechat-zip/defaults')
        self.assertEqual(result,{'group':'合成群','start':'2026-11-01','end':'2026-11-02'})

    def test_supplement_roundtrip_keeps_old_case_and_never_analyzes(self):
        import base64
        from PIL import Image
        code,old=self.request('/api/cases',{'title':'合成缺图','messages':[{'id':'A','text':'[图片] missing.png',
            'source_reference':{'media':[{'reference':'missing.png','status':'unavailable','reason':'missingImage'}]}}]})
        self.assertEqual(code,201)
        picture=io.BytesIO();Image.new('RGB',(20,12),'blue').save(picture,'PNG')
        payload={'data':base64.b64encode(picture.getvalue()).decode()}
        self.assertEqual(self.request('/api/supplements/upload',payload,token=False)[0],403)
        self.assertEqual(self.request('/api/supplements/upload',{'data':base64.b64encode(b'not a picture').decode()})[0],400)
        with patch('chigua.provider.generate') as generate:
            code,asset=self.request('/api/supplements/upload',payload);self.assertEqual(code,201)
            binding={'message_id':'A','media_index':0,'asset_id':asset['id'],'kind':'screenshot','confirmed':True}
            code,new=self.request('/api/supplements/apply',{'case_id':old['id'],'bindings':[binding]})
            generate.assert_not_called()
        self.assertEqual(code,201);self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(self.request('/api/cases/'+old['id'])[1]['case'],old)
        self.assertTrue(new['messages'][0]['image']);self.assertEqual(new['messages'][0]['text'],old['messages'][0]['text'])
        self.assertEqual(self.request('/api/cases/'+new['id'])[1]['runs'],[])
        self.assertEqual(self.request('/api/supplements/apply',{'case_id':new['id'],'bindings':[binding]})[0],400)


if __name__=='__main__':unittest.main()
