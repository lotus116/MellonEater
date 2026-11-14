import json,runpy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import core,editor,pipeline

SCRIPT=core.ROOT/'scripts/reader-edition.py'


class ReeditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'runs'/'oldrun';self.folder.mkdir(parents=True)
        self.original={'id':'oldrun','case_id':'case','report':{'summary':'original','reader':{'old':True}}}
        self.snapshot={'messages':[{'id':'M1','text':'original snapshot'}]}
        core.write_json(self.folder/'result.json',self.original);core.write_json(self.folder/'input.json',self.snapshot)
        self.previous={'reader':{'old':True},'purpose':'manual'};core.write_json(self.folder/'reader.json',self.previous)
    def tearDown(self):self.tmp.cleanup()
    def invoke(self):
        with patch.object(core,'DATA',self.root),patch.object(pipeline,'DATA',self.root),patch('sys.argv',['reader-edition.py','oldrun']):
            runpy.run_path(str(SCRIPT),run_name='__main__')
    def test_failed_reedit_never_replaces_previous_edition(self):
        with patch.object(editor,'edit_report',side_effect=ValueError('rejected')):
            with self.assertRaisesRegex(ValueError,'rejected'):self.invoke()
        self.assertEqual(json.loads((self.folder/'reader.json').read_text()),self.previous)
        self.assertEqual(json.loads((self.folder/'result.json').read_text()),self.original)
    def test_repeated_reedit_uses_same_checkpoint_directory(self):
        paths=[]
        def fail(case,analysis,folder,progress):paths.append(folder);raise ValueError('mock failure')
        with patch.object(editor,'edit_report',side_effect=fail):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'mock failure'):self.invoke()
        self.assertEqual(paths[0],paths[1]);self.assertTrue((paths[0]/'manifest.json').exists())
    def test_success_uses_snapshot_and_archives_previous(self):
        accepted={'reader':{'new':True},'workflow_version':'test'}
        def edit(case,analysis,folder,progress):
            folder.mkdir(parents=True,exist_ok=True);return accepted
        with patch.object(editor,'edit_report',side_effect=edit) as mock,patch.object(pipeline,'load_case',side_effect=AssertionError('must use snapshot')):
            self.invoke()
        self.assertEqual(mock.call_args.args[0],self.snapshot)
        self.assertEqual(json.loads(next((self.folder/'editions').glob('*/previous-reader.json')).read_text()),self.previous)
        self.assertEqual(json.loads((self.folder/'result.json').read_text()),self.original)
        self.assertEqual(json.loads((self.folder/'reader.json').read_text())['reader'],{'new':True})


if __name__=='__main__':unittest.main()
