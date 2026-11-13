import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from chigua.provider import generate, parse_json


class Response(BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class ProviderTests(unittest.TestCase):
    def call(self,content,finish='stop'):
        captured={}
        def fake(req,timeout):
            captured['body']=json.loads(req.data);captured['url']=req.full_url
            return Response(json.dumps({'choices':[{'message':{'content':content},'finish_reason':finish}],'usage':{'prompt_tokens':4,'completion_tokens':2}}).encode())
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'CHIGUA_PROVIDER':'deepseek','CHIGUA_MODEL':'deepseek-flash','CHIGUA_BASE_URL':'https://api.deepseek.com','CHIGUA_API_KEY':'test-secret-value'}), patch('urllib.request.urlopen',fake):
            out,stats=generate('Return JSON.',{'type':'object'},Path(folder),'test')
            logs=''.join(p.read_text() for p in Path(folder).glob('*'))
            self.assertNotIn('test-secret-value',logs)
        return captured,out,stats
    def test_deepseek_json_contract_and_usage(self):
        captured,out,stats=self.call('{"ok":true}')
        self.assertEqual(captured['body']['response_format'],{'type':'json_object'})
        self.assertEqual(captured['url'],'https://api.deepseek.com/chat/completions')
        self.assertTrue(out['ok']);self.assertEqual(stats['usage']['prompt_tokens'],4)
    def test_blank_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'空内容'):self.call('   ')
    def test_truncated_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'上限'):self.call('{"ok":','length')
    def test_fences_allowed_but_garbage_not_silently_salvaged(self):
        self.assertEqual(parse_json('```json\n{"a":1}\n```'),{'a':1})
        with self.assertRaises(ValueError):parse_json('random text {"a":1}')


if __name__=='__main__':unittest.main()
