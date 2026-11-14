import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from chigua.core import fingerprint, normalize_messages
from chigua.supplements import store_asset, clone_with_images, MAX_ASSET


def png(color='red'):
    out=io.BytesIO();Image.new('RGB',(20,15),color).save(out,'PNG');return out.getvalue()


def sample_case():
    rows=normalize_messages([
        {'id':'M1','speaker':'合成甲','timestamp':'2026-11-14T10:20:00+08:00',
         'text':'[图片] first.png\n[图片] second.png','uncertainty':'图片缺口：missingImage。',
         'source_reference':{'provider':'wechat-native-export','media':[
             {'reference':'first.png','status':'unavailable','reason':'missingImage','archive_path':None},
             {'reference':'second.png','status':'unavailable','reason':'ambiguousImage','archive_path':None}]}},
        {'id':'M2','speaker':'合成乙','text':'[图片] third.png','source_reference':{'media':[
             {'reference':'third.png','status':'unavailable','reason':'missingImage','archive_path':None}]}}
    ])
    return {'id':'a'*32,'title':'合成缺图案例','messages':rows,'created_at':'2026-11-14',
            'input_hash':fingerprint(rows),'capture':{'images':{'requested':3,'unavailable':3}},
            'source_note':'导入时三张图片缺失。','identity':'旁观者','question':'还原经过'}


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'data';self.case=sample_case()
    def tearDown(self):self.temp.cleanup()
    def asset(self,color='red'):return store_asset(png(color),self.data)
    def bind(self,asset,mid='M1',index=0,kind='saved_image'):
        return {'message_id':mid,'media_index':index,'asset_id':asset['id'],'kind':kind,'confirmed':True}
    def cases(self):return list((self.data/'cases').glob('*.json'))
    def test_asset_original_preview_integrity_and_private_permissions(self):
        asset=self.asset();folder=self.data/'private'/'supplements'/asset['id']
        self.assertEqual((folder/(asset['id']+'.original')).read_bytes(),png())
        self.assertEqual((self.data/'uploads'/asset['image']).read_bytes(),png())
        self.assertFalse(asset['original_resolution_verified'])
        for path in self.data.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o077,0)
    def test_single_binding_clones_without_altering_old_case_or_run(self):
        asset=self.asset();before=copy.deepcopy(self.case)
        old=self.data/'cases'/(self.case['id']+'.json');old.parent.mkdir();old.write_text(json.dumps(self.case))
        run=self.data/'runs'/'old'/'input.json';run.parent.mkdir(parents=True);run.write_text(json.dumps(self.case))
        old_bytes=old.read_bytes();run_bytes=run.read_bytes()
        result=clone_with_images(self.case,[self.bind(asset)],self.data)
        self.assertEqual(self.case,before);self.assertEqual(old.read_bytes(),old_bytes);self.assertEqual(run.read_bytes(),run_bytes)
        self.assertNotEqual(result['id'],self.case['id']);self.assertNotEqual(result['input_hash'],self.case['input_hash'])
        self.assertEqual(result['messages'][0]['text'],self.case['messages'][0]['text'])
        self.assertEqual(result['messages'][0]['timestamp'],self.case['messages'][0]['timestamp'])
        self.assertEqual(result['messages'][0]['image'],asset['image'])
        item=result['messages'][0]['source_reference']['media'][0]
        self.assertEqual(item['supplement']['original_missing_reason'],'missingImage')
        self.assertEqual(item['supplement']['method'],'user_confirmed');self.assertEqual(item['origin'],'user_supplement')
        self.assertFalse(item['original_resolution_verified']);self.assertEqual(item['status'],'available')
        self.assertEqual(result['capture']['images'],{'requested':3,'available':1,'unavailable':2})
        self.assertTrue(result['supplement']['requires_new_analysis']);self.assertNotIn('report',result)
        self.assertEqual((self.data/'cases'/(result['id']+'.json')).stat().st_mode & 0o077,0)
        self.assertEqual(len(list((self.data/'runs').iterdir())),1)
    def test_multiple_images_append_child_keep_old_order_and_screenshot_provenance(self):
        one=self.asset();two=self.asset('blue')
        result=clone_with_images(self.case,[self.bind(one),self.bind(two,index=1,kind='screenshot')],self.data)
        rows=result['messages'];self.assertEqual([r['id'] for r in rows[:2]],['M1','M2'])
        self.assertEqual(len(rows),3);child=rows[2];self.assertEqual(child['parent_id'],'M1')
        self.assertEqual(child['image'],two['image']);self.assertEqual(child['source_reference']['supplement']['kind'],'screenshot')
        self.assertEqual(child['source_reference']['supplement']['original_missing_reason'],'ambiguousImage')
        self.assertNotIn('media',child['source_reference']);self.assertIn('截图',child['uncertainty'])
        self.assertEqual(rows[0]['source_reference']['supplement']['kind'],'saved_image')
        self.assertEqual(result['capture']['images'],{'requested':3,'available':2,'unavailable':1})
    def test_already_has_image_adds_child_and_keeps_existing_media(self):
        previous=self.asset();new=self.asset('blue')
        first=clone_with_images(self.case,[self.bind(previous)],self.data)
        result=clone_with_images(first,[self.bind(new,index=1)],self.data)
        self.assertEqual(result['messages'][0]['image'],previous['image'])
        self.assertEqual(result['messages'][-1]['image'],new['image'])
        self.assertEqual(result['capture']['images']['available'],2)
        self.assertEqual(result['title'],first['title'])
        self.assertLessEqual(len(result['title']),100)
    def test_all_bindings_validated_before_case_publication(self):
        asset=self.asset();valid=self.bind(asset)
        invalids=[{**valid,'message_id':'unknown'},{**valid,'media_index':9},
            {**valid,'media_index':True},{**valid,'confirmed':'true'},
            {**valid,'confirmed':False},{**valid,'kind':'guessed'},
            {**valid,'asset_id':'../outside'},valid]
        before=copy.deepcopy(self.case)
        for invalid in invalids:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):clone_with_images(self.case,[valid,invalid],self.data)
                self.assertEqual(self.cases(),[]);self.assertEqual(self.case,before)
    def test_asset_tampering_and_symlink_rejected(self):
        asset=self.asset();original=self.data/'private'/'supplements'/asset['id']/(asset['id']+'.original')
        original.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'大小|校验'):clone_with_images(self.case,[self.bind(asset)],self.data)
        self.assertEqual(self.cases(),[])
        asset=self.asset();preview=self.data/'uploads'/asset['image'];preview.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'校验'):clone_with_images(self.case,[self.bind(asset)],self.data)
        preview.unlink();preview.symlink_to(original)
        with self.assertRaisesRegex(ValueError,'符号链接'):clone_with_images(self.case,[self.bind(asset)],self.data)
        asset=self.asset();meta=self.data/'private'/'supplements'/asset['id']/'asset.json'
        value=json.loads(meta.read_text());value['image']='../outside.png';meta.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'元数据'):clone_with_images(self.case,[self.bind(asset)],self.data)
    def test_missing_available_target_and_invalid_asset_inputs(self):
        with self.assertRaises(ValueError):store_asset(b'',self.data)
        with self.assertRaises(ValueError):store_asset(b'bad picture',self.data)
        out=io.BytesIO();Image.new('RGB',(2,2)).save(out,'GIF')
        with self.assertRaisesRegex(ValueError,'PNG 或 JPG'):store_asset(out.getvalue(),self.data)
        with self.assertRaises(ValueError):store_asset(b'x'*(MAX_ASSET+1),self.data)
        asset=self.asset();result=clone_with_images(self.case,[self.bind(asset)],self.data)
        count=len(self.cases())
        with self.assertRaisesRegex(ValueError,'尚未取得'):clone_with_images(result,[self.bind(asset)],self.data)
        self.assertEqual(len(self.cases()),count)
    def test_managed_directory_symlinks_rejected(self):
        self.data.mkdir();outside=Path(self.temp.name)/'outside';outside.mkdir()
        (self.data/'uploads').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'符号链接'):self.asset()
        self.assertEqual(list(outside.iterdir()),[])


if __name__=='__main__':unittest.main()
