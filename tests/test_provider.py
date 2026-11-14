import json
import os
import tempfile
import subprocess
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from chigua.provider import generate, parse_json, config_identity, normalize_empty_presentation
from chigua.core import READER_SCHEMA,validate_schema


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
            logs=''.join(p.read_text() for p in Path(folder).rglob('*') if p.is_file())
            self.assertNotIn('test-secret-value',logs)
        return captured,out,stats
    def test_deepseek_json_contract_and_usage(self):
        captured,out,stats=self.call('{"ok":true}')
        self.assertEqual(captured['body']['response_format'],{'type':'json_object'})
        self.assertEqual(captured['url'],'https://api.deepseek.com/chat/completions')
        self.assertTrue(out['ok']);self.assertEqual(stats['usage']['prompt_tokens'],4)
        self.assertEqual(captured['body']['thinking'],{'type':'disabled'})
    def test_deepseek_thinking_is_explicit_and_in_checkpoint_identity(self):
        with patch.dict(os.environ,{'CHIGUA_DEEPSEEK_THINKING':'low','CHIGUA_PROVIDER':'deepseek'}):
            captured,_,_=self.call('{"ok":true}')
            low=config_identity()
        self.assertEqual(captured['body']['thinking'],{'type':'enabled'})
        self.assertEqual(captured['body']['reasoning_effort'],'low')
        with patch.dict(os.environ,{'CHIGUA_DEEPSEEK_THINKING':'disabled','CHIGUA_PROVIDER':'deepseek'}):
            self.assertNotEqual(low,config_identity())
    def test_invalid_thinking_setting_stops_before_http(self):
        with patch.dict(os.environ,{'CHIGUA_DEEPSEEK_THINKING':'invalid'}),patch('urllib.request.urlopen') as http:
            with self.assertRaisesRegex(ValueError,'思考设置无效'):self.call('{"ok":true}')
            http.assert_not_called()
    def test_only_empty_optional_presentation_fields_are_normalized(self):
        value={'title':None,'chapters':[{'image_id':None,'image_caption':None,'quote_text':None,'quote_source_id':None,'paragraphs':None}]}
        fixed,repairs=normalize_empty_presentation(value,READER_SCHEMA)
        self.assertEqual(len(repairs),4);self.assertIsNone(fixed['title'])
        self.assertIsNone(fixed['chapters'][0]['paragraphs']);self.assertEqual(fixed['chapters'][0]['image_id'],'')
        self.assertIsNone(value['chapters'][0]['image_id'])
        with self.assertRaises(ValueError):validate_schema(fixed,READER_SCHEMA)
    def test_blank_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'空内容'):self.call('   ')
    def test_truncated_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'上限'):self.call('{"ok":','length')
    def test_fences_allowed_but_garbage_not_silently_salvaged(self):
        self.assertEqual(parse_json('```json\n{"a":1}\n```'),{'a':1})
        with self.assertRaises(ValueError):parse_json('random text {"a":1}')
    def test_codex_initialization_error_is_actionable_and_private(self):
        def fail(args,**kwargs):
            kwargs['stderr'].write('private synthetic content\nError: failed to initialize in-process app-server client: Operation not permitted (os error 1)\n')
            return SimpleNamespace(returncode=1)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CHIGUA_PROVIDER':'codex'}),patch('chigua.provider.shutil.which',return_value='/synthetic/codex'),patch('chigua.provider.subprocess.run',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'启动被系统权限阻止') as error:
                generate('private synthetic prompt',None,Path(folder),'test')
            self.assertNotIn('private synthetic',str(error.exception))
            self.assertIn('无需重新导入',str(error.exception))
    def test_codex_timeout_is_not_misreported_as_login_failure(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CHIGUA_PROVIDER':'codex'}),patch('chigua.provider.shutil.which',return_value='/synthetic/codex'),patch('chigua.provider.subprocess.run',side_effect=subprocess.TimeoutExpired(['codex'],600)):
            with self.assertRaisesRegex(RuntimeError,'超过 10 分钟'):
                generate('synthetic',None,Path(folder),'test')


if __name__=='__main__':unittest.main()
