import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from chigua.wechat_zip import import_archives, transcript

START='2026-11-01T00:00:00+08:00'; END='2026-11-01T23:59:59+08:00'


def record(body='合成正文', who='合成甲', date='2026年11月1日 12:00'):
    return f'·{who}\n{date}\n{body}\n\n'


def png(color='red'):
    output=io.BytesIO();Image.new('RGB',(16,12),color).save(output,'PNG');return output.getvalue()


class NativeZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'data'
    def tearDown(self):self.tmp.cleanup()
    def archive(self, entries, name='source.zip'):
        path=self.root/name
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for key,value in entries:z.writestr(key,value)
        return path
    def run_import(self,*paths):
        return import_archives(list(paths),title='合成导出',group_label='合成群',start=START,end=END,data=self.data)
    def test_text_image_scope_and_private_storage(self):
        path=self.archive([('聊天记录.txt',record('[图片] one.png')+record('范围外',date='2026年11月2日 12:00')),
                           ('聊天记录内的图片、视频和文件/one.png',png()),('index.html','<script>do not execute</script>')])
        cases,meta=self.run_import(path);row=cases[0]['messages'][0]
        self.assertEqual(len(cases[0]['messages']),1);self.assertEqual(meta['out_of_window_excluded'],1)
        self.assertEqual(row['speaker'],'合成甲');self.assertEqual(row['timestamp'],'2026-11-01T12:00:00+08:00')
        self.assertEqual(meta['images']['available'],1);self.assertFalse(meta['window_query_complete'])
        self.assertFalse(meta['cloud_analysis_started']);self.assertNotIn('index.html',[p.name for p in self.data.rglob('*')])
        self.assertEqual((self.data/'uploads'/row['image']).read_bytes(),png())
        for p in self.data.rglob('*'):
            if p.is_file():self.assertEqual(p.stat().st_mode & 0o077,0)
    def test_merged_batches_do_not_cross_match_same_filename(self):
        path=self.archive([('聊天记录.txt','聊天：synthetic\nnot a native transcript'),
            ('batches/0001/聊天记录.txt',record('[图片] same.png')),
            ('batches/0002/聊天记录.txt',record('[图片] same.png','合成乙')),
            ('batches/0001/media/same.png',png('red')),('batches/0002/media/same.png',png('blue'))])
        cases,meta=self.run_import(path);rows=cases[0]['messages']
        self.assertEqual(len(rows),2);self.assertEqual(meta['images']['available'],2)
        self.assertNotEqual((self.data/'uploads'/rows[0]['image']).read_bytes(),(self.data/'uploads'/rows[1]['image']).read_bytes())
    def test_missing_ambiguous_and_multiple_images(self):
        path=self.archive([('聊天记录.txt',record('[图片] no.png\n[图片] dup.png\n[图片] a.png\n[图片] b.png')),
            ('a/dup.png',png()),('b/dup.png',png()),('a.png',png()),('b.png',png('blue'))])
        cases,meta=self.run_import(path);rows=cases[0]['messages']
        self.assertEqual(meta['images']['unavailable'],2);self.assertEqual(meta['images']['available'],2)
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['parent_id'],rows[0]['id'])
        self.assertIn('ambiguousImage',rows[0]['uncertainty'])
    def test_only_exact_archives_deduplicated_not_repeated_messages(self):
        path=self.archive([('聊天记录.txt',record('同一分钟重复')+record('同一分钟重复'))])
        cases,meta=self.run_import(path,path)
        self.assertEqual(len(cases[0]['messages']),2);self.assertEqual(meta['duplicate_archives_skipped'],1)
        self.assertEqual(meta['duplicate_candidates_retained'],1)
    def test_paths_symlinks_and_duplicate_entries_rejected(self):
        symlink=zipfile.ZipInfo('link');symlink.create_system=3;symlink.external_attr=(stat.S_IFLNK|0o777)<<16
        for entry in ['../outside.png','/absolute.png','a/../../outside.png',symlink]:
            with self.subTest(entry=str(entry)):
                path=self.archive([('聊天记录.txt',record()),(entry,b'data')])
                with self.assertRaises(ValueError):self.run_import(path)
        path=self.archive([('聊天记录.txt',record()),('a.png',png()),('A.png',png())])
        with self.assertRaises(ValueError):self.run_import(path)
        self.assertEqual(list((self.data/'cases').glob('*.json')),[])
    def test_unknown_format_or_bad_date_fails_without_case(self):
        for body in ['unknown export',record(date='2026年2月30日 12:00')]:
            with self.assertRaises(ValueError):self.run_import(self.archive([('聊天记录.txt',body)]))
        self.assertEqual(list((self.data/'cases').glob('*.json')),[])
    def test_bad_image_is_visible_gap(self):
        cases,meta=self.run_import(self.archive([('聊天记录.txt',record('[图片] bad.png')),('bad.png',b'invalid')]))
        self.assertEqual(meta['images']['unavailable'],1);self.assertIsNone(cases[0]['messages'][0]['image'])
    def test_large_input_splits_without_dropping(self):
        cases,meta=self.run_import(self.archive([('聊天记录.txt',''.join(record(str(i)) for i in range(2001)))]))
        self.assertEqual([len(c['messages']) for c in cases],[2000,1]);self.assertEqual(meta['materials'],2001)
        self.assertEqual(len({r['id'] for c in cases for r in c['messages']}),2001)


if __name__=='__main__':unittest.main()
