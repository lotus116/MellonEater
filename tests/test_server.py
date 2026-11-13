import json
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
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=h)
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


if __name__=='__main__':unittest.main()
