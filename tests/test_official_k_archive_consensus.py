"""Synthetic archives: accept common typed facts, retain disputed payouts."""
import unittest
from tests.test_official_k_special_blocks import packet
from tests.test_boat_entry_observations import uncompressed_lzh

def multi(*bodies):
    return b''.join(uncompressed_lzh(b,'K300101.TXT')[:-1] for b in bodies)+b'\0'

class ConsensusTests(unittest.TestCase):
    def parse(self,raw):
        from race_ai.official_k_archive import parse_archive
        return parse_archive(raw,day='2030-01-01')
    def test_duplicate_names_compare_each_member_not_last_by_name(self):
        p=self.parse(multi(packet(),packet().replace(b'TEST',b'OTHER')))
        self.assertEqual(len(p['rows']),6)
        self.assertEqual(len(p['archive_member_sha256']),2)
        self.assertEqual(p['payout_conflict_races'],[])
    def test_conflicting_result_never_chooses_last(self):
        with self.assertRaises(ValueError):self.parse(multi(packet(),packet().replace(b'0.12',b'0.13')))
    def test_only_disputed_payouts_are_withheld(self):
        a=packet().replace(b'01KEND',b'3\x98A\x92P 1-2-3 1000 \x90l\x8bC 1\n01KEND')
        b=a.replace(b'1000',b'2000')
        p=self.parse(multi(a,b))
        self.assertEqual(p['payout_conflict_races'],['20300101-01-01'])
        self.assertEqual(p['payouts']['20300101-01-01'],[])
        self.assertEqual(len(p['rows']),6)
    def test_unexpected_member_is_rejected(self):
        raw=uncompressed_lzh(packet(),'K300101.TXT')[:-1]+uncompressed_lzh(packet(),'K300102.TXT')
        with self.assertRaises(ValueError):self.parse(raw)
