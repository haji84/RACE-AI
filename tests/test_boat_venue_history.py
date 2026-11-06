"""Fictional venue/racer histories, explicit observed-vs-complete semantics."""
from datetime import datetime,timezone
import unittest
from copy import deepcopy
from race_ai.boat_venue_history import VenueHistory
from tests.test_boat_racer_database import term_archive
from tests.test_boat_entry_observations import daily_pair,uncompressed_lzh

NOW='2030-01-01T00:00:00+00:00'

def archive(venue=17,day='2026-11-04'):
    _,k=daily_pair();k=k.replace(b'17KBGN',f'{venue:02}KBGN'.encode()).replace(b'17KEND',f'{venue:02}KEND'.encode())
    k=k.replace(b'2026/11/04',day.replace('-','/').encode())
    return uncompressed_lzh(k,'K'+day[2:4]+day[5:7]+day[8:]+'.TXT')

class VenueHistoryTests(unittest.TestCase):
    def test_unreported_venue_cannot_prove_no_start_but_other_venue_can_be_complete(self):
        from tests.test_official_k_special_blocks import packet
        extra='02KBGN\n2030/01/01\n[払戻金]\n'+'\n'.join(f'{n}R' for n in range(1,13))+'\n02KEND'
        h=VenueHistory(start='2030-01-01',end='2030-01-01',roster=['4999'],clock=lambda:datetime(2030,1,2,tzinfo=timezone.utc))
        h.add_archive(uncompressed_lzh(packet(extra=extra),'K300101.TXT'),day='2030-01-01',captured_at='2030-01-02T00:00:00Z')
        self.assertEqual(h.profile('4999','02',as_of='2030-01-02T00:00:00Z')['coverage_status'],'INCOMPLETE_NO_OBSERVATIONS')
        self.assertEqual(h.profile('4999','01',as_of='2030-01-02T00:00:00Z')['coverage_status'],'COMPLETE_NO_OBSERVATIONS')
        self.assertFalse(h.summary(as_of='2030-01-02T00:00:00Z')['all_venue_player_history_complete'])

    def make(self):return VenueHistory(start='2026-11-04',end='2026-11-05',roster=['4001','4999'],clock=lambda:datetime(2030,1,1,tzinfo=timezone.utc))
    def test_full_grid_no_data_is_unobserved_not_zero_performance(self):
        h=self.make();out=list(h.profiles(as_of=NOW))
        self.assertEqual(len(out),48)
        self.assertEqual(out[0]['coverage_status'],'INCOMPLETE_NO_OBSERVATIONS')
        self.assertIsNone(out[0]['stats']['win_rate_numeric'])
        self.assertEqual(out[0]['history_completeness'],False)
    def test_groups_by_racer_venue_course_and_retains_counts_methods_and_st(self):
        h=self.make();h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        rows=list(h.profiles(as_of=NOW));self.assertEqual(len(rows),7*24)
        p=h.profile('4001','17',as_of=NOW)
        self.assertEqual(p['stats']['opportunities'],3)
        self.assertEqual(p['stats']['numeric_finish_n'],3)
        self.assertAlmostEqual(p['stats']['top3_rate_numeric'],2/3)
        self.assertEqual(p['stats']['st_n'],3);self.assertAlmostEqual(p['stats']['mean_st'],.12)
        self.assertEqual(p['coverage_status'],'PARTIAL_OBSERVED')
        self.assertIsNone(p['official_local_win_rate'])
        self.assertEqual(h.profile('4001','01',as_of=NOW)['stats']['opportunities'],0)
    def test_identical_day_is_idempotent_conflicting_day_requires_rebuild(self):
        h=self.make();h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        self.assertEqual(h.summary(as_of=NOW)['observed_starts'],18)
        with self.assertRaises(ValueError):h.add_archive(archive(18),day='2026-11-04',captured_at=NOW)
    def test_complete_source_window_can_distinguish_no_appearance(self):
        h=VenueHistory(start='2026-11-04',end='2026-11-04',roster=['4999'],clock=lambda:datetime(2030,1,1,tzinfo=timezone.utc))
        h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        p=h.profile('4999','17',as_of=NOW)
        self.assertEqual(p['coverage_status'],'COMPLETE_NO_OBSERVATIONS')
        self.assertTrue(p['history_completeness']);self.assertIsNone(p['stats']['win_rate_numeric'])
    def test_capture_after_asof_or_wrong_day_is_not_admitted(self):
        h=self.make();h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        with self.assertRaises(ValueError):h.profile('4001','17',as_of='2029-12-31T00:00:00Z')
        with self.assertRaises(ValueError):h.add_archive(archive(),day='2026-11-05',captured_at=NOW)

    def test_future_capture_claim_rejected_before_any_data_mutation(self):
        h=VenueHistory(start='2026-11-04',end='2026-11-05',clock=lambda:datetime(2030,1,1,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):h.add_archive(archive(),day='2026-11-04',captured_at='2030-01-02T00:00:00Z')
        self.assertEqual(h.summary(as_of=NOW)['observed_starts'],0)
    def test_f_disposition_remains_visible_and_st_is_not_imputed(self):
        from race_ai.official_lzh_extract import extract_daily_lzh
        raw=extract_daily_lzh(archive(),'K261104.TXT').replace(b' 01 6 4006',b' F 6 4006').replace(b'6.80 1 0.12',b'6.80 1 F0.02',1)
        # Keep registered frame and ST disposition; the course is never replaced by its frame.
        h=self.make();h.add_archive(uncompressed_lzh(raw,'K261104.TXT'),day='2026-11-04',captured_at=NOW)
        p=h.profile('4006','17',as_of=NOW)
        self.assertEqual(p['stats']['dispositions']['F'],1)
        self.assertEqual(p['stats']['opportunities'],3)
        self.assertEqual(p['stats']['numeric_finish_n'],2)
        self.assertEqual(p['stats']['st_n'],2)

    def test_noncanonical_day_alias_cannot_double_count_or_complete_window(self):
        h=self.make();h.add_archive(archive(),day='2026-11-04',captured_at=NOW)
        with self.assertRaises(ValueError):h.add_archive(archive(),day='20261104',captured_at=NOW)
        self.assertEqual(h.summary(as_of=NOW)['observed_starts'],18)
        self.assertFalse(h.profile('4999','17',as_of=NOW)['history_completeness'])
