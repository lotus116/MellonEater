import copy
import unittest
from chigua.core import normalize_reference_ids


class ReferenceNormalizationTests(unittest.TestCase):
    def test_only_complete_hash_with_one_extra_hex_is_repaired_and_logged(self):
        mid='Z'+'0123456789abcdef01234567'
        value={'claims':[{'support_ids':[mid+'c'],'statement':mid+'c'}]}
        before=copy.deepcopy(value)
        fixed,repairs=normalize_reference_ids(value,[{'id':mid}])
        self.assertEqual(value,before)
        self.assertEqual(fixed['claims'][0]['support_ids'],[mid])
        self.assertEqual(fixed['claims'][0]['statement'],mid+'c')
        self.assertEqual(repairs,[{'path':'$.claims[0].support_ids[0]','original':mid+'c',
                                  'normalized':mid,'rule':'one_extra_hex_after_complete_zip_id'}])

    def test_unknown_ids_short_ids_missing_or_changed_characters_are_not_guessed(self):
        mid='Z'+'0123456789abcdef01234567'
        refs=[mid[:-1],mid[:-1]+'8',mid+'ab',mid+'x','M1a','Z'+'f'*25]
        value={'source_ids':refs}
        fixed,repairs=normalize_reference_ids(value,[{'id':mid},{'id':'M1'}])
        self.assertEqual(fixed,value);self.assertEqual(repairs,[])

    def test_existing_longer_id_and_non_reference_fields_are_unchanged(self):
        mid='Z'+'0123456789abcdef01234567'
        value={'source_ids':[mid+'a'],'id':mid+'b','event_id':mid+'b'}
        fixed,repairs=normalize_reference_ids(value,[{'id':mid},{'id':mid+'a'}])
        self.assertEqual(fixed,value);self.assertEqual(repairs,[])


if __name__=='__main__':unittest.main()
