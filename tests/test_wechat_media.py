import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from chigua.core import ROOT
from chigua.wechat import capture, window
from chigua.wechat_io import GreenBubbles
from chigua.wechat_media import attach_images

GROUP='synthetic@chatroom';START='2026-11-01T00:00:00+08:00';END='2026-11-01T23:59:59+08:00'
SINCE,UNTIL=window(START,END)
BINARY=ROOT/'tmp/greenbubbles-tool/release/greenbubbles-0.10.0-macos-arm64/bin/greenbubbles'


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        output=io.BytesIO();Image.new('RGB',(12,8),'blue').save(output,'PNG');self.blob=output.getvalue()
        self.meta={'source_identity':'fixture','conversation_id':GROUP,'start':START,'end':END}
        self.messages=[{'id':'W1','timestamp':START,'text':'[图片]', 'source_reference':{
            'source_identity':'fixture','conversation_id':GROUP,'message_id':'opaque-1','content_kind':'Image','message_type':3}}]
    def tearDown(self):self.tmp.cleanup()
    def fake(self,args,**kwargs):
        self.assertIn('opaque-1',args);self.assertIn(GROUP,args)
        if args[1]=='inspect':return {'schema':'greenbubbles.attachment.v1','formatVersion':1,'operation':'attachment.inspect',
            'ok':True,'kind':'image','availability':'downloaded','preferredAttachmentId':'bound-id',
            'preferredSourceByteCount':len(self.blob),'sourceMd5':hashlib.md5(self.blob).hexdigest()}
        Path(args[args.index('--output')+1]).write_bytes(self.blob)
        return {'schema':'greenbubbles.attachment.v1','formatVersion':1,'operation':'attachment.materialize',
            'ok':True,'kind':'image','attachmentId':'bound-id','decodedByteCount':len(self.blob),
            'decodedSha256':hashlib.sha256(self.blob).hexdigest()}
    def test_exact_message_binding_and_hash(self):
        meta=copy.deepcopy(self.meta)
        attach_images(self.messages,meta,SimpleNamespace(run=self.fake),self.root/'private',self.root/'uploads')
        self.assertEqual(meta['images']['available'],1);self.assertTrue(meta['image_association_complete'])
        self.assertEqual((self.root/'uploads'/self.messages[0]['image']).read_bytes(),self.blob)
    def test_cross_scope_fails_before_tools(self):
        with patch.object(SimpleNamespace(),'run',create=True) as run:
            self.messages[0]['source_reference']['conversation_id']='other@chatroom'
            with self.assertRaises(ValueError):attach_images(self.messages,self.meta,SimpleNamespace(run=run),self.root/'p',self.root/'u')
            run.assert_not_called()
    def test_hash_mismatch_never_associates(self):
        def bad(args,**kwargs):
            result=self.fake(args,**kwargs)
            if args[1]=='materialize':result['decodedSha256']='bad'
            return result
        with self.assertRaises(ValueError):attach_images(self.messages,self.meta,SimpleNamespace(run=bad),self.root/'p',self.root/'u')
        self.assertNotIn('image',self.messages[0])
    def test_unavailable_is_reported(self):
        def missing(args,**kwargs):
            result=self.fake(args,**kwargs);result['availability']='notDownloaded';return result
        attach_images(self.messages,self.meta,SimpleNamespace(run=missing),self.root/'p',self.root/'u')
        self.assertFalse(self.meta['image_association_complete']);self.assertEqual(self.meta['images']['unavailable'],1)
    def test_secret_file_stdin_and_permissions(self):
        key=self.root/'credential';key.write_text('synthetic-secret');key.chmod(0o600)
        client=GreenBubbles('/fixture/bin',self.root,key)
        def run(args,**kwargs):
            self.assertNotIn('synthetic-secret',str(args));self.assertEqual(kwargs['stdin'].read(),b'synthetic-secret')
            self.assertEqual(args[2],'find');self.assertEqual(args[3],'synthetic name');self.assertEqual(args[4],str(self.root.resolve()))
            return SimpleNamespace(stdout='[]',stderr='',returncode=0)
        with patch('chigua.wechat_io.subprocess.run',side_effect=run):client.run(['conversations','find','synthetic name'])
        key.chmod(0o644)
        with patch('chigua.wechat_io.subprocess.run') as run:
            with self.assertRaises(ValueError):client.run(['messages','list'])
            run.assert_not_called()
        link=self.root/'link';link.symlink_to(key)
        with self.assertRaises(ValueError):GreenBubbles('/fixture/bin',self.root,link).run(['messages','list'])

    @unittest.skipUnless(BINARY.is_file(),'Optional signed GreenBubbles v0.10.0 is not installed locally')
    def test_real_binary_synthetic_database_text_and_image(self):
        account=self.root/'account';db=account/'db_storage'
        for name in ['contact','session','message','media','hardlink']:(db/name).mkdir(parents=True)
        with sqlite3.connect(db/'contact/contact.db') as conn:
            conn.executescript("CREATE TABLE contact(username TEXT PRIMARY KEY,remark TEXT,nick_name TEXT,alias TEXT); INSERT INTO contact VALUES ('sender','Synthetic Sender','','');")
            conn.execute('INSERT INTO contact VALUES (?,?,?,?)',(GROUP,'Synthetic Group','',''))
        with sqlite3.connect(db/'session/session.db') as conn:
            conn.execute('CREATE TABLE SessionTable(username TEXT,sort_timestamp INTEGER,summary BLOB)')
            conn.execute('INSERT INTO SessionTable VALUES (?,?,?)',(GROUP,SINCE+1,b'synthetic'))
        md5=hashlib.md5(self.blob).hexdigest();packed=b'\x08\x6a\x10\x0e\x1a\x22\x22\x20'+md5.encode()
        with sqlite3.connect(db/'message/message_0.db') as conn:
            conn.executescript("CREATE TABLE Name2Id(user_name TEXT); INSERT INTO Name2Id(rowid,user_name) VALUES (1,'sender');")
            for group in [GROUP,'other@chatroom']:
                table='Msg_'+hashlib.md5(group.encode()).hexdigest()
                conn.execute(f'CREATE TABLE [{table}](server_id INTEGER,sort_seq INTEGER,local_type INTEGER,real_sender_id INTEGER,create_time INTEGER,status INTEGER,message_content BLOB,packed_info_data BLOB,WCDB_CT_message_content INTEGER,compress_content BLOB)')
                for sid,stamp,kind,body,info in [(1,SINCE+1,1,b'synthetic text',b''),(2,SINCE+2,3,b'',packed),(3,UNTIL+1,1,b'out of time',b'')]:
                    conn.execute(f'INSERT INTO [{table}] VALUES (?,?,?,1,?,0,?,?,0,NULL)',(sid,stamp,kind,stamp,body,info))
        images=account/'msg/attach'/hashlib.md5(GROUP.encode()).hexdigest()/'2026-11/Img';images.mkdir(parents=True)
        (images/(md5+'_h.dat')).write_bytes(bytes(b^0x5a for b in self.blob))
        client=GreenBubbles(BINARY,db,decrypted=True)
        rows,pages,meta=capture(GROUP,START,END,client=client)
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['text'],'synthetic text')
        attach_images(rows,meta,client,self.root/'output',self.root/'uploads')
        self.assertEqual(meta['images']['available'],1);self.assertEqual(meta['images']['unavailable'],0)
        self.assertEqual((self.root/'uploads'/rows[1]['image']).read_bytes(),self.blob)
        names=client.run(['conversations','find','Synthetic Group','--limit','20'])
        self.assertEqual(len(names),1);self.assertEqual(names[0]['id'],GROUP)


if __name__=='__main__':unittest.main()
