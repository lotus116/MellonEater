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


if __name__=='__main__':unittest.main()
