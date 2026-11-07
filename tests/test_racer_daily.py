"""Invented official-format archives; no live provider or production secrets."""
from datetime import datetime,timezone
import hashlib,json,unittest
from tests.test_boat_venue_history import archive
from tests.test_boat_entry_observations import uncompressed_lzh
from race_ai.official_lzh_extract import extract_daily_lzh
try:
    from race_ai.racer_daily import DailyStore,seal,unseal
except ModuleNotFoundError:
    DailyStore=seal=unseal=None

NOW=datetime(2026,11,7,2,tzinfo=timezone.utc)
ROSTER=[dict(registration='4001',name='架空選手一'),dict(registration='4006',name='架空選手六'),dict(registration='4999',name='架空未出走')]

class DailyTests(unittest.TestCase):
    def make(self):
        self.assertIsNotNone(DailyStore,'daily results must connect to a persisted aggregate')
        store=DailyStore(clock=lambda:NOW);self.addCleanup(store.close);return store

    def test_real_parser_actual_courses_period_and_unknown_appearances(self):
        s=self.make();self.assertTrue(s.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z'))
        d=s.catalogue(ROSTER,as_of=NOW.isoformat());p=d['people'][0]
        self.assertEqual(d['period'],dict(start='2026-08-09',end='2026-11-06',days=90))
        self.assertEqual(p['summary']['starts'],3);self.assertEqual(p['courses'][1]['starts'],1)
        self.assertEqual(p['summary']['st_samples'],3);self.assertEqual(p['summary']['average_st'],.12)
        self.assertEqual(d['coverage']['missing_days_count'],89);self.assertFalse(d['coverage']['complete'])
        self.assertIsNone(d['people'][2]['summary']['win_percent'])
        self.assertNotIn('raw',json.dumps(d));self.assertNotIn('ordered_top8',json.dumps(d))

    def test_f_disposition_remains_in_rate_denominator_and_st_has_own_sample(self):
        raw=extract_daily_lzh(archive(),'K261104.TXT')
        line=next(line for line in raw.splitlines() if b' 06 6 4006' in line)
        raw=raw.replace(line,line.replace(b' 06 6 4006',b' F 6 4006').replace(b'0.12',b'F0.02'),1)
        s=self.make();s.record('2026-11-04',uncompressed_lzh(raw,'K261104.TXT'),captured_at='2026-11-05T00:00:00Z')
        p=s.catalogue(ROSTER,as_of=NOW.isoformat())['people'][1]
        self.assertEqual(p['summary']['starts'],3);self.assertEqual(p['summary']['st_samples'],2)
        self.assertEqual(p['summary']['dispositions']['F'],1)
        self.assertAlmostEqual(p['summary']['win_percent'],100/3)

    def test_idempotence_revision_snapshot_and_corruption(self):
        s=self.make();a=archive();s.record('2026-11-04',a,captured_at='2026-11-05T00:00:00Z')
        self.assertFalse(s.record('2026-11-04',a,captured_at='2026-11-06T00:00:00Z'))
        self.assertTrue(s.record('2026-11-04',archive(18),captured_at='2026-11-06T00:00:00Z'))
        self.assertEqual(s.revisions,2)
        raw=s.serialize();copy=DailyStore.restore(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),clock=lambda:NOW);self.addCleanup(copy.close)
        self.assertEqual(copy.catalogue(ROSTER,as_of=NOW.isoformat()),s.catalogue(ROSTER,as_of=NOW.isoformat()))
        self.assertEqual(copy.catalogue(ROSTER,as_of=NOW.isoformat())['people'][0]['summary']['starts'],3)
        with self.assertRaises(ValueError):DailyStore.restore(raw+b'x',expected_sha256=hashlib.sha256(raw).hexdigest(),clock=lambda:NOW)

    def test_bad_revision_and_future_capture_never_replace_valid_state(self):
        s=self.make();s.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');before=s.serialize()
        for day,raw,captured in [('2026-11-04',b'broken','2026-11-06T00:00:00Z'),('2026-11-05',archive(),'2026-11-08T00:00:00Z'),('20261104',archive(),'2026-11-06T00:00:00Z')]:
            with self.assertRaises(ValueError):s.record(day,raw,captured_at=captured)
            self.assertEqual(s.serialize(),before)
    def test_unknown_finish_is_a_source_gap_instead_of_a_zero_performance(self):
        s=self.make();raw=extract_daily_lzh(archive(),'K261104.TXT').replace(b' 06 6 4006',b' 00 6 4006',1)
        with self.assertRaisesRegex(ValueError,'DAILY_UNKNOWN_FINISH_NOT_ADMITTED'):
            s.record('2026-11-04',uncompressed_lzh(raw,'K261104.TXT'),captured_at='2026-11-05T00:00:00Z')
        self.assertEqual(s.revisions,0)

    def test_authenticated_checkpoint_is_bound_to_daily_namespace_and_generation(self):
        s=self.make();s.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        key=bytes(range(32));cipher,head=seal(s.serialize(),generation=1,previous=None,key=key)
        self.assertNotIn(b'SQLite format',cipher);self.assertNotIn(b'4001',cipher)
        self.assertEqual(unseal(cipher,head,key=key),s.serialize())
        with self.assertRaises(ValueError):unseal(cipher,{**head,'generation':2},key=key)
        with self.assertRaises(ValueError):unseal(cipher+b'x',head,key=key)

