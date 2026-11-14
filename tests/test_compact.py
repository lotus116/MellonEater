import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import compact,provider,pipeline,core
from chigua.checkpoints import CallFailure
from test_core import valid_report
from test_editor import candidate


def composed():
    return compact.map_refs({**valid_report(),'reader':candidate()},{'M0001':'S001','M1':'S001'})


def issue():
    return {'key':'F1','severity':'blocking','category':'fact','path':'/reader/verdict',
            'candidate_excerpt':'仍需核对。','source_ids':['S001'],
            'evidence':[{'source_id':'S001','quote':'我付了钱'}],
            'problem':'合成问题','requested_change':'写为单方声称付款'}


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)/'editorial'
        self.case={'id':'synthetic','messages':core.normalize_messages([{'id':'M0001','speaker':'测试甲','text':'我付了钱'}]),'input_hash':'test'}
    def tearDown(self):self.tmp.cleanup()
    def run_flow(self,outputs):
        def gen(*args,**kwargs):return copy.deepcopy(next(outputs)),{'model':'test','seconds':0}
        with patch.object(provider,'generate',side_effect=gen) as calls:
            result=compact.execute(self.case,self.folder)
        return result,calls
    def test_text_report_is_new_compose_and_audit_with_lossless_refs(self):
        result,calls=self.run_flow(iter([composed(),{'decision':'pass','issues':[]}]))
        self.assertEqual([c.args[3] for c in calls.call_args_list],['compose','audit_0'])
        self.assertEqual(result['report']['reader']['verdict_source_ids'],['M0001'])
        self.assertTrue((self.folder/'accepted.json').exists())
        self.assertEqual(calls.call_args_list[1].kwargs['options']['thinking'],'disabled')
    def test_invalid_compose_repairs_before_audit_and_publishes_web_report(self):
        invalid=composed()
        invalid['reader']['verdict_source_ids']=['S404']
        result,calls=self.run_flow(iter([invalid,composed(),{'decision':'pass','issues':[]}]))
        self.assertEqual([c.args[3] for c in calls.call_args_list],['compose','compose_repair','audit_0'])
        self.assertEqual(result['quality']['layout']['status'],'web_checked')
        self.assertTrue((self.folder/'accepted.json').exists())
    def test_truncated_audit_is_repaired_without_rewriting_compose(self):
        outputs=[(composed(),{}),CallFailure('截断',kind='output_length'),({'decision':'pass','issues':[]},{})]
        with patch.object(provider,'generate',side_effect=outputs) as calls:
            result=compact.execute(self.case,self.folder)
        self.assertEqual(result['quality']['status'],'passed')
        self.assertEqual([c.args[3] for c in calls.call_args_list],['compose','audit_0','audit_contract_fix_0'])
        self.assertEqual(calls.call_args_list[-1].kwargs['options']['thinking'],'disabled')
    def test_images_only_go_to_observation_and_audit_not_writer(self):
        self.case['messages'][0]['image']='synthetic.png'
        vision={'observations':[{'source_id':'S001','visible_text':'我付了钱','visible_time':'昨天','description':'收据','uncertainty':''}]}
        result,calls=self.run_flow(iter([vision,composed(),{'decision':'pass','issues':[]}]))
        self.assertEqual([list(c.args[4]) for c in calls.call_args_list],[['synthetic.png'],[],['synthetic.png']])
        self.assertIn('visible_time',calls.call_args_list[1].args[0])
        self.assertEqual(calls.call_args_list[0].kwargs['options']['image_labels'],{'synthetic.png':'S001'})
    def test_anchored_patch_changes_only_the_issue_then_requires_review(self):
        change={'changes':[{'path':'/reader/verdict','expected_json':json.dumps('仍需核对。'),
                            'replacement_json':json.dumps('甲声称付款，尚待核对。')}]}
        result,calls=self.run_flow(iter([composed(),{'decision':'revise','issues':[issue()]},change,{'decision':'pass','issues':[]}]))
        self.assertEqual([c.args[3] for c in calls.call_args_list],['compose','audit_0','patch_1','audit_1'])
        self.assertEqual(result['quality']['revisions'],1)
        self.assertNotIn('候选稿：',calls.call_args_list[2].args[0])
    def test_revision_audit_uses_changed_fields_and_only_their_related_images(self):
        self.case['messages'][0]['image']='relevant.png'
        self.case['messages'].append({'id':'M0002','speaker':'乙','text':'无关内容','image':'unrelated.png'})
        vision={'observations':[{'source_id':sid,'visible_text':'读图','visible_time':'',
                                'description':'截图','uncertainty':''} for sid in ['S001','S002']]}
        change={'changes':[{'path':'/reader/verdict','expected_json':json.dumps('仍需核对。'),
                            'replacement_json':json.dumps('甲自述已支付。')}]}
        _,calls=self.run_flow(iter([vision,composed(),{'decision':'revise','issues':[issue()]},
                                    change,{'decision':'pass','issues':[]}]))
        review=calls.call_args_list[-1]
        self.assertEqual(review.args[3],'audit_1')
        self.assertEqual(review.args[4],['relevant.png'])
        self.assertNotIn('无关内容',review.args[0])
        self.assertNotIn('候选稿：',review.args[0])
    def test_invented_critique_is_not_paid_rewrite(self):
        bad=issue();bad['evidence'][0]['quote']='not present'
        with patch.object(provider,'generate',side_effect=[(composed(),{}),({'decision':'revise','issues':[bad]}, {}),({'decision':'revise','issues':[bad]}, {})]) as gen:
            with self.assertRaises(CallFailure) as error:compact.execute(self.case,self.folder)
        self.assertEqual(error.exception.kind,'review_invalid');self.assertEqual(gen.call_count,3)
        self.assertEqual(gen.call_args_list[-1].args[3],'audit_contract_fix_0')
        self.assertFalse((self.folder/'accepted.json').exists())
    def test_patch_cannot_change_other_fields_or_stale_values(self):
        for path,expected,new in [('/title','anything','changed'),('/reader/verdict','wrong','changed'),('/reader/verdict','仍需核对。','仍需核对。')]:
            with self.subTest(path=path,expected=expected),self.assertRaises(ValueError):
                compact.apply_patch(composed(),{'changes':[{'path':path,'expected_json':json.dumps(expected),'replacement_json':json.dumps(new)}]},[issue()])
    def test_critique_cannot_authorize_whole_reader_rewrite(self):
        pack,_,_=compact.prepare(self.case);broad=issue();broad['path']='/reader'
        with self.assertRaisesRegex(ValueError,'范围过大'):
            compact.audit_issues({'decision':'revise','issues':[broad]},composed(),pack)
    def test_exact_paragraph_quote_narrows_patch_to_text_and_keeps_evidence(self):
        pack,_,_=compact.prepare(self.case)
        draft=composed()
        path='/reader/chapters/0/paragraphs/0'
        paragraph=compact.locate(draft,path)
        review={**issue(),'path':path,'candidate_excerpt':paragraph['text']}
        blockers=compact.audit_issues({'decision':'revise','issues':[review]},draft,pack)
        self.assertEqual(blockers[0]['path'],path+'/text')
        self.assertEqual(blockers[0]['original_path'],path)
        fix={'changes':[{'path':path+'/text','expected_json':json.dumps(paragraph['text']),
                         'replacement_json':json.dumps('甲自述已经付款。')}]}
        self.assertEqual(compact.locate(compact.apply_patch(draft,fix,blockers),path),
                         {**paragraph,'text':'甲自述已经付款。'})
        review['candidate_excerpt']='这句不在段落里'
        with self.assertRaisesRegex(ValueError,'范围过大'):
            compact.audit_issues({'decision':'revise','issues':[review]},draft,pack)
    def test_suggestions_do_not_block_and_decision_must_match(self):
        pack,_,_=compact.prepare(self.case);suggestion=issue();suggestion['severity']='suggestion'
        self.assertEqual(compact.audit_issues({'decision':'pass','issues':[suggestion]},composed(),pack),[])
        with self.assertRaises(ValueError):compact.audit_issues({'decision':'revise','issues':[suggestion]},composed(),pack)
        suggestion.update(path='/nonexistent',candidate_excerpt='not a real quote')
        self.assertEqual(compact.audit_issues({'decision':'pass','issues':[suggestion]},composed(),pack),[])
    def test_omitted_reader_wrapper_only_repairs_exact_existing_quote(self):
        pack,_,_=compact.prepare(self.case);short=issue();short['path']='/verdict'
        blockers=compact.audit_issues({'decision':'revise','issues':[short]},composed(),pack)
        self.assertEqual(blockers[0]['path'],'/reader/verdict')
        self.assertEqual(blockers[0]['original_path'],'/verdict')
        self.assertEqual(short['path'],'/verdict') # raw response remains intact
        short['candidate_excerpt']='not in candidate'
        with self.assertRaises((ValueError,KeyError)):
            compact.audit_issues({'decision':'revise','issues':[short]},composed(),pack)
    def test_source_packing_keeps_parent_time_uncertainty_but_not_export_noise(self):
        self.case['messages'][0].update(timestamp='2026-11-14T17:43:00+08:00',uncertainty='昨天日期未知',source_reference={'private_export_noise':'x'})
        pack,ids,assets=compact.prepare(self.case)
        self.assertEqual(pack['messages'][0]['message_time'],'2026-11-14T17:43:00+08:00')
        self.assertEqual(pack['messages'][0]['uncertainty'],'昨天日期未知')
        self.assertEqual(pack['messages'][0]['speaker_label'],'测试甲')
        self.assertNotIn('private_export_noise',compact.dump(pack));self.assertEqual(ids,{'M0001':'S001'})
    def test_exhausted_old_editor_job_cannot_resume_and_has_diagnostics(self):
        folder=Path(self.tmp.name)/'runs/old'
        core.write_json(folder/'job.json',{'id':'old','status':'failed','error':'自动编辑两轮返修后仍未通过。'})
        core.write_json(folder/'editorial/checks.json',[{'issues':['结构问题'],'review':None}])
        with patch.object(pipeline,'DATA',Path(self.tmp.name)),patch.object(pipeline,'JOBS',{}),patch.object(provider,'generate') as gen:
            job=pipeline.get_job('old');self.assertFalse(job['can_resume']);self.assertTrue(job['diagnostics'])
            with self.assertRaisesRegex(ValueError,'原样续跑'):pipeline.resume('old',background=False)
            gen.assert_not_called()


if __name__=='__main__':unittest.main()
