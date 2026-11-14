import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chigua import compact, core, evidence_first, provider, report


def event(kind, sid, quote, *, actor='P1', actor_quote='', scene='未知', scene_quote='',
          mode='当时记录', medium='text', time_origin='未知', time_quote=''):
    return {'kind':kind,'label':kind,'action':'整理动作','actual_actor':actor,'actor_quote':actor_quote,
            'scene':scene,'scene_quote':scene_quote,'mode':mode,
            'source':{'source_id':sid,'medium':medium,'quote':quote},
            'time_origin':time_origin,'time_quote':time_quote,'basis':'对应原文',
            'order_basis':'相对顺序可确认','impact':'说明讨论为何变化'}


def dispute(sid, quote):
    return {'source':{'source_id':sid,'medium':'text','quote':quote},'stance':'关于付款间隔的说法'}


def ledger(events, disputes=()):
    return {'roles':[{'speaker':'P1','role':'协调人'},{'speaker':'P2','role':'负责人'}],
            'events':events,'disputes':list(disputes),'limits':[]}


def prose(ref):
    return {'title':'押金争执','lead':'此前已有分工摩擦，押金催问又起争执。',
            'verdict':'转账间隔待核对。','verdict_source_ids':[ref],'central_question':'争执如何扩大？',
            'timeline_note':'缺少的具体时间留空。','open_questions':[],
            'chapters':[{'title':'经过','paragraphs':[{'text':'双方给了不同说法。','source_ids':[ref]}]}],
            'assessment':[]}


class EvidenceFirstTests(unittest.TestCase):
    def test_bind_before_writer_and_render_competing_accounts_without_writer(self):
        case = {'id':'sample','messages':core.normalize_messages([
            {'id':'A','speaker':'协调人','text':'【布置群】单子漏填了。'},
            {'id':'B','speaker':'协调人','text':'【社员群】那笔款过了两天才转。'},
            {'id':'C','speaker':'负责人','text':'【社员群】到你账户到转出去是四天。'},
            {'id':'D','speaker':'旁观者','text':'没选中的大段闲聊。'},
        ])}
        evidence = ledger([event('前情','S001','单子漏填了。',scene='小群')],
                          [{'topic':'转账间隔','limit':'缺少流水。',
                            'accounts':[dispute('S002','过了两天才转'),dispute('S003','是四天')]}])
        with tempfile.TemporaryDirectory() as work, patch.object(provider,'generate',side_effect=[
            (evidence,{}),(json.dumps(prose('S001')),{}),
        ]) as model:
            result = compact.execute(case,Path(work))
            self.assertTrue((Path(work)/'bound-evidence.json').exists())
        self.assertEqual([x.args[3] for x in model.call_args_list],['bind_sources','compose'])
        self.assertNotIn('没选中的大段闲聊',model.call_args.args[0])
        self.assertFalse(result['report']['reader']['assessment'])
        page = report.reader_html(case,{'report':result['report'],'created_at':core.now()})
        compare = page.split('id="competing-accounts"',1)[1].split('</section>',1)[0]
        self.assertIn('协调人</strong> 过了两天才转',compare)
        self.assertIn('负责人</strong> 是四天',compare)
        self.assertEqual(result['report']['reader']['story']['arc'][0]['phase'],'前情')
        self.assertEqual(result['report']['reader']['story']['arc'][0]['source_ids'],['A'])

    def test_image_sender_and_scene_have_to_match_same_turn(self):
        pack = {'messages':[
            {'id':'S001','speaker':'P2','speaker_label':'转发者','text':'转发图','image_observation_ref':'S001',
             'message_time':'2026-04-10T17:52:00+08:00'},
            {'id':'S002','speaker':'P1','speaker_label':'陈同学','text':'其他对话'},
        ],'image_observations':[{'source_id':'S001','description':'群聊“布置群”界面',
                                'visible_time':'17:52; 昨天 21:25',
                                'visible_text':'17:52\n布置群\n昨天 21:25\n陈同学\n先道歉再谈。'}]}
        row = event('原始言行','S001','先道歉再谈。',actor_quote='陈同学',scene='小群',medium='image',
                    time_origin='图内时间',time_quote='昨天 21:25')
        good = evidence_first.build(ledger([row]),pack)['events'][0]
        self.assertEqual((good['actor'],good['scene'],good['time']),('协调人','小群','昨天 21:25（图内）'))
        wrong = {**row,'scene':'私聊','actual_actor':'P2','time_origin':'消息时间',
                 'time_quote':'2026-04-10T17:52:00+08:00'}
        safe = evidence_first.build(ledger([wrong]),pack)['events'][0]
        self.assertEqual(safe['scene'],'小群')
        self.assertEqual(safe['actor'],'说话者待确认')
        self.assertEqual(safe['time'],'')
        self.assertFalse(safe['bound'])
        self.assertNotIn('整理动作',safe['action'])

        # Quoting the full screenshot turn (including the sender) must
        # resolve to the same actor and clock as quoting the words alone.
        row['source']['quote'] = '陈同学\n先道歉再谈。'
        whole_turn = evidence_first.build(ledger([row]),pack)['events'][0]
        self.assertEqual((whole_turn['actor'],whole_turn['time']),('协调人','昨天 21:25（图内）'))
        private = {**row,'scene':'私聊'}
        self.assertFalse(evidence_first.build(ledger([private]),pack)['events'][0]['bound'])

    def test_composer_can_link_to_checked_dispute_by_topic_without_rewriting(self):
        case = {'id':'sample','messages':core.normalize_messages([
            {'id':'A','speaker':'协调人','text':'等了两天。'},
            {'id':'B','speaker':'负责人','text':'我等了四天。'},
        ])}
        source = ledger([event('原始言行','S001','等了两天。')],
                        [{'topic':'到账到转出的间隔','limit':'无凭证。',
                          'accounts':[dispute('S001','等了两天。'),dispute('S002','等了四天。')]}])
        draft = prose('S001')
        draft['chapters'][0]['paragraphs'].append({'text':'无法核对的归责应略去。','source_ids':['S404']})
        draft['verdict_source_ids'] = ['S404']
        draft['assessment'] = [
            {'title':'检查间隔','observation':'协调人说两天。','judgment':'应拿出凭证。',
             'source_ids':['S001'],'conflict_ids':['到账到转出的间隔'],'inference':'','counterpoint':'另有人说四天。'},
            {'title':'无依据的断言','observation':'另一个人同时在场。','judgment':'他应负责。',
             'source_ids':['S404'],'conflict_ids':[],'inference':'','counterpoint':''},
        ]
        before = copy.deepcopy(draft)
        with tempfile.TemporaryDirectory() as work, patch.object(provider,'generate',side_effect=[
            (source,{}),(json.dumps(draft),{}),
        ]) as model:
            result = compact.execute(case,Path(work))
        self.assertEqual([call.args[3] for call in model.call_args_list],['bind_sources','compose'])
        self.assertEqual(draft,before)
        reader = result['report']['reader']
        self.assertEqual(len(reader['chapters'][0]['paragraphs']),1)
        self.assertEqual(reader['verdict_source_ids'],[])
        self.assertEqual(len(reader['assessment']),1)
        self.assertEqual(reader['assessment'][0]['conflict_ids'],['A','B'])
        self.assertEqual(result['quality']['status'],'limited')

    def test_missing_all_prose_citations_uses_ledger_and_does_not_guess_at_links(self):
        draft = prose('S404')
        draft['assessment'] = [
            {'title':'可核对的判断','observation':'原文有这句话。','judgment':'应当交代进度。',
             'source_ids':['S001'],'conflict_ids':['同名争议','S404'],'inference':'','counterpoint':''},
        ]
        data = {'events':[{'source_ids':['S001'],'bound':True,'action':'群里有人问了付款进度。'}],
                'disputes':[{'topic':'同名争议','accounts':[{'source_ids':['S001','S002']}]},
                            {'topic':'同名争议','accounts':[{'source_ids':['S003','S004']}]}]}
        findings = evidence_first.reconcile_prose(draft,data)
        self.assertTrue(findings)
        self.assertEqual(draft['chapters'][0]['paragraphs'],[
            {'text':'群里有人问了付款进度。','source_ids':['S001']},
        ])
        self.assertEqual(draft['assessment'][0]['conflict_ids'],[])

    def test_repeated_scenes_and_question_are_not_promoted_to_retaliation(self):
        pack = {'messages':[
            {'id':'S001','speaker':'P1','speaker_label':'协调人','text':'【社员群，补贴私信】负责人：为什么要我认错？',
             'message_time':'2026-04-10T17:52:00+08:00'},
            {'id':'S002','speaker':'P2','speaker_label':'负责人','text':'贴完你才来私信，我回你也先认错。'},
        ],'image_observations':[]}
        wrong = event('回击','S001','负责人：为什么要我认错？',actor='P2',scene='私聊',
                      scene_quote='私信',actor_quote='负责人')
        right = event('回击','S002','贴完你才来私信，我回你也先认错。',actor='P2',actor_quote='我',
                      scene='私聊',scene_quote='私信',mode='后来回述')
        bound = evidence_first.build(ledger([wrong,right]),pack)
        self.assertEqual([e['source_ids'] for e in bound['events']],[['S002']])
        self.assertEqual(bound['events'][0]['actor'],'负责人')
        self.assertTrue(bound['findings'])
