import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from chigua.wechat import capture,decode_page,window

CHAT='synthetic@chatroom'
START='2026-11-01T00:00:00+08:00'
END='2026-11-02T00:00:00+08:00'
SINCE,UNTIL=window(START,END)


def page(mid='one',stamp=SINCE+100,more=False):
    return {'schema':'greenbubbles.query.v1','formatVersion':1,'operation':'messages.list','ok':True,
        'source':{'identity':'synthetic-source'},'consistency':{'coverageComplete':True},'warnings':[],
        'page':{'returned':1,'hasMore':more,'nextCursor':'next' if more else None},
        'items':[{'id':mid,'conversationId':CHAT,'createdAtUnix':stamp,'sender':'synthetic-id',
                  'senderDisplayName':'合成甲','content':{'Text':'这是合成文字'},'contentTruncated':False}]}


class WeChatTests(unittest.TestCase):
    def test_explicit_timezone_and_bounded_window(self):
        with self.assertRaises(ValueError):window('2026-11-01','2026-11-02')
        with self.assertRaises(ValueError):window(START,'2027-01-01T00:00:00+08:00')
    def test_unknown_format_rejected(self):
        obj=page();obj['formatVersion']=2
        with self.assertRaises(ValueError):decode_page(obj,CHAT,SINCE,UNTIL)
    def test_cross_group_and_time_rejected(self):
        obj=page();obj['items'][0]['conversationId']='other@chatroom'
        with self.assertRaises(ValueError):decode_page(obj,CHAT,SINCE,UNTIL)
        with self.assertRaises(ValueError):decode_page(page(stamp=UNTIL+1),CHAT,SINCE,UNTIL)
    def test_original_id_and_truncation_preserved(self):
        obj=page();obj['items'][0]['contentTruncated']=True
        rows,info=decode_page(obj,CHAT,SINCE,UNTIL)
        self.assertEqual(rows[0]['source_reference']['message_id'],'one')
        self.assertIn('截断',rows[0]['uncertainty'])
    def test_forward_and_media_not_misrepresented_as_empty(self):
        obj=page();obj['items'][0]['content']={'Forward':{'file':'/private/example'}}
        rows,info=decode_page(obj,CHAT,SINCE,UNTIL)
        self.assertEqual(info['unsupported'],1);self.assertIn('尚未解码',rows[0]['text'])
        self.assertNotIn('/private/example',rows[0]['text'])
    def run_capture(self,pages,limit=500):
        results=[SimpleNamespace(returncode=0,stdout=json.dumps(x),stderr='') for x in pages]
        with patch('chigua.wechat.shutil.which',return_value='/synthetic/greenbubbles'),patch('chigua.wechat.subprocess.run',side_effect=results) as run:
            result=capture(CHAT,START,END,limit)
            return result,run.call_args_list
    def test_paging_repeats_scope_and_preserves_source_order(self):
        (messages,raw,meta),calls=self.run_capture([page('new',SINCE+200,True),page('old',SINCE+100)])
        self.assertEqual([m['source_reference']['message_id'] for m in messages],['old','new'])
        self.assertTrue(meta['window_query_complete']);self.assertFalse(meta['cloud_analysis_started'])
        for c in calls:
            self.assertIn(CHAT,c.args[0]);self.assertIn(str(SINCE),c.args[0]);self.assertIn(str(UNTIL),c.args[0])
            self.assertNotIn('shell',c.kwargs)
        self.assertIn('--cursor',calls[1].args[0])
    def test_limit_marks_remaining_pages(self):
        (messages,raw,meta),_=self.run_capture([page(more=True)],1)
        self.assertFalse(meta['window_query_complete']);self.assertTrue(meta['has_more'])
    def test_source_coverage_warning_not_complete(self):
        obj=page();obj['consistency']['coverageComplete']=False
        (_,_,meta),_=self.run_capture([obj]);self.assertFalse(meta['window_query_complete'])
    def test_changed_duplicate_fails(self):
        first=page(more=True);second=page();second['items'][0]['content']={'Text':'changed'}
        with self.assertRaisesRegex(ValueError,'发生变化'):self.run_capture([first,second])
    def test_source_changes_between_pages_fail(self):
        second=page('older',SINCE+10);second['source']['identity']='another-source'
        with self.assertRaisesRegex(ValueError,'来源变化'):self.run_capture([page(more=True),second])
    def test_error_does_not_expose_tool_stderr(self):
        with patch('chigua.wechat.shutil.which',return_value='/synthetic/greenbubbles'),patch('chigua.wechat.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='private example key')):
            with self.assertRaises(RuntimeError) as error:capture(CHAT,START,END)
        self.assertNotIn('private example key',str(error.exception))
    def test_no_implicit_install_or_name_search(self):
        with patch('chigua.wechat.shutil.which',return_value=None),patch('chigua.wechat.subprocess.run') as run:
            with self.assertRaises(ValueError):capture(CHAT,START,END)
            with self.assertRaises(ValueError):capture('模糊群名',START,END)
            run.assert_not_called()


if __name__=='__main__':unittest.main()
