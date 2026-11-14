"""Verify that event cards use the right source passage and clock."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chigua import compact, core, event_sequence, provider
from test_compact import composed


def node(position, sid, quote, origin, clock, *, mode='当时记录', medium='text', basis='相对顺序可确认'):
    return {
        'position':str(position), 'stage':f'动作 {position}', 'happened':quote,
        'changed':'改变了接下来讨论的内容。', 'order_basis':basis, 'phase':'升级', 'source_ids':[sid],
        'source_check':{'actor':'当事人', 'scene':'对话', 'mode':mode,
                        'anchor':{'source_id':sid,'quote':quote,'from':medium},
                        'time_origin':origin,'time_quote':clock,'basis':'核对对应原文'},
    }


class EventSequenceTests(unittest.TestCase):
    def test_one_web_card_per_action_across_scenes(self):
        messages = core.normalize_messages([
            {'id':'M0001','speaker':'测试甲','text':'我付了钱'},
            {'id':'M0002','speaker':'测试乙','text':'我公开贴出来了','timestamp':'2026-04-07T20:00:00+08:00'},
            {'id':'M0003','speaker':'测试乙','text':'贴完我私信回他：你先给凭证','timestamp':'2026-04-10T11:15:00+08:00'},
            {'id':'M0004','speaker':'测试甲','text':'【补贴旧对话】我只是开玩笑','timestamp':'2026-04-10T11:17:00+08:00'},
        ])
        draft = composed(compare=True)
        draft['reader']['assessment'] = [{
            'title':'付款判断','observation':'甲自述付款','source_ids':['S001'],
            'judgment':'需要凭证','inference':'','counterpoint':'','conflict_ids':['S002'],
        }]
        story = draft['reader']['story']
        del story['arc']
        del draft['timeline']
        story['actions'] = {
            '原始言行':[node(1,'S001','我付了钱','未知','')],
            '公开披露':[node(2,'S002','我公开贴出来了','消息时间','2026-04-07T20:00:00+08:00')],
            '回击':[node(3,'S003','贴完我私信回他：你先给凭证','原文所述时间','贴完',mode='后来回述')],
            '事后解释':[node(4,'S004','我只是开玩笑','消息时间','2026-04-10T11:17:00+08:00')],
            '其他':[],
        }
        case = {'id':'synthetic','messages':messages,'input_hash':'test'}
        with tempfile.TemporaryDirectory() as temp, patch.object(provider,'generate',side_effect=[
            (draft,{}),({'issues':[]},{}),
        ]) as generate:
            result = compact.execute(case,Path(temp))
        arc = result['report']['reader']['story']['arc']
        self.assertEqual(generate.call_count,2)
        self.assertEqual(result['report']['reader']['assessment'][0]['conflict_ids'],['M0002'])
        self.assertEqual(len(arc),4)
        self.assertEqual([step['source_ids'] for step in arc],[[m['id']] for m in messages])
        self.assertEqual([step['event_time'] for step in arc],['','4月7日 20:00','',''])
        self.assertEqual(result['report']['timeline'],compact.derived_timeline(arc))
        self.assertEqual(result['quality']['status'],'limited')
        self.assertNotIn('source_check',arc[0])
        self.assertIn('公开披露',generate.call_args.args[0])
        self.assertIn('第一次在一处公开贴出和后来补贴旧材料',generate.call_args.args[0])

    def test_local_review_does_not_insert_already_stated_explanation(self):
        draft = {'reader':{'lead':'她没有回应，但私信解释只是活跃一下气氛。'}}
        edits = {'issues':[{'field_id':'F001','excerpt':'她没有回应',
                            'replacement':'私信解释只是活跃一下气氛。',
                            'evidence':[{'source_id':'S001','quote':'我就活跃一下气氛'}],
                            'reason':'资料包含事后解释'}]}
        pack = {'messages':[{'id':'S001','text':'我就活跃一下气氛'}],'image_observations':[]}
        changes, rejected = compact.checked_edits(edits,{'F001':'/reader/lead'},draft,pack,contextual=True)
        self.assertEqual(changes,[])
        self.assertTrue(rejected)

    def test_only_inner_clock_governing_the_quote_is_allowed(self):
        row = node(1,'S001','先答应再谈','图内时间','昨天 21:25',medium='image',basis='时间戳可确认')
        row['action_kind'] = '原始言行'
        pack = {
            'messages':[{'id':'S001','image_observation_ref':'S001','message_time':'2026-04-10T17:52:00+08:00'}],
            'image_observations':[{'source_id':'S001','visible_text':'17:52\n昨天 21:25\n先答应再谈\n昨天 21:31\n另一个话题',
                                   'visible_time':'17:52; 昨天 21:25; 昨天 21:31'}],
        }
        draft = {'reader':{'story':{'arc':[row]}}}
        self.assertFalse(event_sequence.normalize(draft,pack)[0])
        self.assertEqual(row['event_time'],'昨天 21:25（图内）')
        for value in ('17:52','昨天 21:31','4月10日 17:52'):
            with self.subTest(value=value):
                wrong = copy.deepcopy(row)
                wrong['source_check']['time_quote'] = value
                issue, *_ = event_sequence.normalize({'reader':{'story':{'arc':[wrong]}}},pack)
                self.assertTrue(issue)
                self.assertEqual(wrong['event_time'],'')

    def test_duplicate_positions_do_not_merge_actions(self):
        first = node(1,'S001','甲发言','未知','')
        second = node(1,'S002','乙公开贴出','未知','')
        with self.assertRaisesRegex(ValueError,'position 重复'):
            event_sequence.flatten({'原始言行':[first],'公开披露':[second],'回击':[],'事后解释':[],'其他':[]})

    def test_only_dated_neighbors_can_swap_without_crossing_an_undated_reply(self):
        recent = node(1,'S002','今天我再发一次','消息时间','2026-04-10T12:00:00+08:00')
        older = node(2,'S001','我当时问他','原文所述时间','4月7日晚',mode='后来回述')
        undated = node(3,'S001','我当时问他','未知','',mode='后来回述')
        for row in (recent, older, undated):
            row['action_kind'] = '原始言行'
        pack = {'messages':[
            {'id':'S001','text':'【补贴旧对话】4月7日晚，我当时问他','message_time':'2026-04-11T12:00:00+08:00'},
            {'id':'S002','text':'今天我再发一次','message_time':'2026-04-10T12:00:00+08:00'},
        ], 'image_observations':[]}
        for rows, ordered in (([recent,older,undated],[older,recent,undated]),
                              ([recent,undated,older],[recent,undated,older])):
            limits, _, _, dated = event_sequence.normalize({'reader':{'story':{'arc':rows}}},pack)
            self.assertFalse(limits)
            event_sequence.order_dated(rows,dated)
            self.assertEqual(rows,ordered)
            self.assertEqual(older['event_time'],'4月7日晚（据回述）')
