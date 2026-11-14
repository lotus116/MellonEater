import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import compact,core,evaluation,pipeline,provider
from test_compact import composed


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.case={'source_note':'完全虚构的反例','messages':[{'id':'M0001','speaker':'乙','text':'我还没收到退款，等你处理。'}]}
        self.folder=self.root/'runs/synthetic'
        self.run={'status':'completed','editorial_workflow':compact.VERSION,'report':compact.map_refs(composed(),{'S001':'M0001'})}
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):
        core.write_json(self.folder/'input.json',self.case);core.write_json(self.folder/'result.json',self.run)
        core.write_json(self.folder/'editorial/evidence-pack.json',compact.prepare(self.case)[0])
    def test_real_material_and_old_versions_rejected_without_model_calls(self):
        for note,version in [('用户真实聊天',compact.VERSION),('完全虚构','old')]:
            self.case['source_note']=note;self.run['editorial_workflow']=version;self.write()
            with patch.object(core,'DATA',self.root),patch.object(provider,'generate') as gen:
                with self.assertRaises(ValueError):evaluation.false_completion('synthetic')
                gen.assert_not_called()
    def test_negative_control_never_publishes_and_reuses_saved_evaluation(self):
        feedback={'decision':'revise','issues':[{'key':'wrong-ending','severity':'blocking','category':'fact',
            'path':'/verdict','candidate_excerpt':'所有参与者都已收到退款，退款争议已经结束。',
            'source_ids':['S001'],'evidence':[{'source_id':'S001','quote':'我还没收到退款，等你处理。'}],
            'problem':'结局与原文冲突','requested_change':'保留未收到款项的状态'}]}
        before=(self.folder/'result.json').read_bytes()
        with patch.object(core,'DATA',self.root),patch.object(pipeline,'DATA',self.root),patch.object(provider,'config_identity',return_value={}),patch.object(provider,'generate',return_value=(feedback,{})) as gen:
            first=evaluation.false_completion('synthetic');second=evaluation.false_completion('synthetic')
            self.assertTrue(first['passed']);self.assertFalse(first['report_published']);self.assertEqual(first,second)
            gen.assert_called_once()
        self.assertEqual((self.folder/'result.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
