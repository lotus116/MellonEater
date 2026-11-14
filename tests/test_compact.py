import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from chigua import compact,provider,pipeline,core
from chigua.checkpoints import CallFailure
from test_core import valid_report
from test_editor import candidate


def composed(*, compare=False):
    reader = {**candidate(), 'assessment': []}
    draft = compact.map_refs({**valid_report(),'reader':reader},{'M0001':'S001','M1':'S001'})
    if compare:
        for step in draft['reader']['story']['arc']:
            step.update(phase='经过',event_time='')
        draft['reading_choice'] = {
            'options':[{'id':'A','explanation':'付款进度尚未确认。','limits':'只有本人说法。','source_ids':['S001']}],
            'selected_id':'A','notes':'现有材料只覆盖付款说法。',
        }
    return draft


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
            result=compact.execute(self.case,self.folder,version=compact.PREVIOUS_VERSION)
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
            result=compact.execute(self.case,self.folder,version=compact.PREVIOUS_VERSION)
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
            with self.assertRaises(CallFailure) as error:compact.execute(self.case,self.folder,version=compact.PREVIOUS_VERSION)
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
    def test_misplaced_audit_quote_resolves_only_to_a_unique_field_in_its_section(self):
        pack, _, _ = compact.prepare(self.case)
        draft = composed()
        draft['claims'][0]['source_note'] = '甲称跨行转账已经完成'
        for path in ['/claims', '/claims/99/statement', '/claims/0/statement']:
            with self.subTest(path=path):
                review = {**issue(), 'path': path, 'candidate_excerpt': '甲称跨行转账已经完成'}
                audit = {'decision': 'revise', 'issues': [review]}
                self.assertEqual(compact.audit_issues(audit, draft, pack)[0]['path'], '/claims/0/source_note')
        review['path'] = '/events/0/summary'
        with self.assertRaisesRegex(ValueError,'原句不在'):
            compact.audit_issues(audit, draft, pack)
        draft['claims'][0]['reason'] = draft['claims'][0]['source_note']
        review['path'] = '/claims'
        with self.assertRaisesRegex(ValueError,'范围过大'):
            compact.audit_issues(audit, draft, pack)

    def test_saved_audit_retry_reason_keeps_request_stable_after_validator_changes(self):
        path = self.folder/'audit-0-contract-error.json'
        audit = {'decision': 'revise', 'issues': [issue()]}
        self.assertEqual(compact.audit_retry_reason(path, audit, '初次错误'), '初次错误')
        self.assertEqual(compact.audit_retry_reason(path, audit, '校验改进后的错误'), '初次错误')
        self.assertEqual(compact.audit_retry_reason(path, None, '另一份审稿'), '另一份审稿')

    def test_numbered_review_keeps_good_edits_when_another_field_is_invalid(self):
        draft = composed(compare=True)
        fields = compact.numbered_fields(draft)
        code = next(code for code, path in fields.items() if path == '/reader/verdict')
        good = {'field_id':code,'excerpt':'仍需核对。','replacement':'甲称已付款，需补凭证。',
                'evidence':[{'source_id':'S001','quote':'我付了钱'}],'reason':'明确是谁的说法'}
        bad = {**good,'field_id':'invented'}
        with patch.object(provider,'generate',side_effect=[
            (draft,{}),({'issues':[bad,good]},{}),({'issues':[]},{}),
        ]) as calls:
            result = compact.execute(self.case,self.folder)
        self.assertEqual(result['report']['reader']['verdict'],good['replacement'])
        self.assertEqual(result['quality']['status'],'limited')
        self.assertEqual(calls.call_count,3)
        self.assertIn('字段编号未知或重复',result['quality']['limitations'][0])

    def test_unresolved_numbered_review_leaves_readable_draft(self):
        draft = composed(compare=True)
        invalid = {'field_id':'invented','excerpt':'未知','replacement':'改写','reason':'无法定位','evidence':[]}
        with patch.object(provider,'generate',side_effect=[(draft,{}),({'issues':[invalid]}, {})]) as calls:
            result = compact.execute(self.case,self.folder)
        self.assertEqual(calls.call_count,2)
        self.assertEqual(result['quality']['status'],'limited')
        self.assertEqual(result['quality']['revisions'],0)
        self.assertTrue((self.folder/'review-draft.json').exists())
        self.assertFalse((self.folder/'accepted.json').exists())

    def test_final_review_reports_remaining_issue_without_a_second_edit(self):
        draft = composed(compare=True)
        code = next(k for k,v in compact.numbered_fields(draft).items() if v=='/reader/verdict')
        edit = {'field_id':code,'excerpt':'仍需核对。','replacement':'甲称付过钱。',
                'evidence':[{'source_id':'S001','quote':'我付了钱'}],'reason':'交代是谁的说法'}
        remaining = {**edit,'excerpt':edit['replacement'],'replacement':'候选二',
                     'reason':'还需要付款凭证。'}
        with patch.object(provider,'generate',side_effect=[
            (draft,{}),({'issues':[edit]},{}),({'issues':[remaining]},{}),
        ]) as calls:
            result = compact.execute(self.case,self.folder)
        self.assertEqual(calls.call_count,3)
        self.assertEqual(result['report']['reader']['verdict'],edit['replacement'])
        self.assertEqual(result['quality']['status'],'limited')
        self.assertEqual(result['quality']['revisions'],1)
        self.assertIn('还需要付款凭证。',result['quality']['limitations'])

    def test_comparison_reaches_the_auditor_and_stays_out_of_the_report(self):
        draft = composed(compare=True)
        with patch.object(provider,'generate',side_effect=[(draft,{}),({'issues':[]},{})]) as calls:
            result = compact.execute(self.case,self.folder)
        self.assertNotIn('reading_choice',result['report'])
        self.assertEqual(result['report']['reader']['story']['arc'][0]['phase'],'经过')
        self.assertIn('现有材料只覆盖付款说法。',calls.call_args.args[0])
        self.assertIn('后来提起或转发的时间并不等于事件时间',calls.call_args.args[0])
        self.assertNotIn('/reading_choice',json.dumps(compact.numbered_fields(draft)))
        draft['reading_choice']['options'][0]['source_ids'] = ['S404']
        with self.assertRaisesRegex(ValueError,'可回查'):
            compact.mechanical(draft,self.case,{'M0001':'S001'},compare=True)
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
    def test_assessment_repairs_only_the_unique_text_field_and_requires_sources(self):
        pack, ids, _ = compact.prepare(self.case)
        draft = composed()
        draft['reader']['assessment'] = [{
            'title':'先查凭证','observation':'甲说付过钱','source_ids':['S001'],
            'judgment':'可以先提供收据','inference':'可能转错账户',
            'counterpoint':'也可能是银行延迟','conflict_ids':[],
        }]
        review = {**issue(), 'path':'/reader/assessment/0', 'candidate_excerpt':'可能转错账户'}
        blockers = compact.audit_issues({'decision':'revise','issues':[review]}, draft, pack)
        self.assertEqual(blockers[0]['path'], '/reader/assessment/0/inference')
        review['path'] = '/reader/assessment/0/counterpoint'
        blockers = compact.audit_issues({'decision':'revise','issues':[review]}, draft, pack)
        self.assertEqual(blockers[0]['path'], '/reader/assessment/0/inference')
        draft['reader']['assessment'][0]['judgment'] = '可能转错账户，需要回查。'
        with self.assertRaisesRegex(ValueError,'原句不在'):
            compact.audit_issues({'decision':'revise','issues':[review]}, draft, pack)
        _, report, _ = compact.mechanical(draft, self.case, ids)
        self.assertEqual(report['reader']['assessment'][0]['source_ids'], ['M0001'])
        draft['reader']['assessment'][0]['source_ids'] = ['S404']
        with self.assertRaisesRegex(ValueError,'不存在的消息'):
            compact.mechanical(draft, self.case, ids)
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
