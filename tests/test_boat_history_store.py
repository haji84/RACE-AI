"""Actual LZH/B/K parsing into append-only private historical facts."""
from datetime import date
from pathlib import Path
import hashlib
import tempfile
import unittest

from tests.test_boat_entry_observations import daily_pair, uncompressed_lzh

DAY=date(2026,11,4)
CAP='2026-11-05T18:00:00+09:00'
ASOF='2026-11-06T01:00:00+09:00'


def archives(*, start='0.12', captured=CAP, motor=55):
    b,k=daily_pair()
    text=b.decode('cp932')
    for lane in range(1,7):
        text=text.replace(f' {lane} {4000+lane} TEST',
            f' {lane} {4000+lane}TEST 30東京52A1 6.50 45.00 5.50 30.00 {motor+lane-1:02d} 35.00 {32+lane:02d} 30.00')
    b=text.encode('cp932')
    text=k.decode('cp932')
    for lane in range(1,7):
        text=text.replace(f' {lane} {4000+lane} TEST 55 33',f' {lane} {4000+lane} TEST {motor+lane-1:02d} {32+lane:02d}')
    k=text.encode('cp932')
    if start!='0.12':k=k.replace(b'0.12',start.encode(),1)
    raw={kind:uncompressed_lzh(body,f'{kind}261104.TXT') for kind,body in [('B',b),('K',k)]}
    sources={kind:dict(source_url=f'https://www1.mbrace.or.jp/od2/{kind}/202611/{kind.lower()}261104.lzh',
        source_sha256=hashlib.sha256(value).hexdigest(),captured_at=captured) for kind,value in raw.items()}
    return raw,sources


class HistoricalStoreTests(unittest.TestCase):
    def setUp(self):
        try:from race_ai.boat_history_store import HistoryStore
        except ImportError:HistoryStore=None
        self.assertIsNotNone(HistoryStore,'private official history intake is not implemented')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=HistoryStore(Path(self.tmp.name)/'history.sqlite')
        self.addCleanup(self.store.close)

    def ingest(self, **kwargs):
        raw,proofs=archives(**kwargs)
        return self.store.ingest_day(DAY,raw['B'],raw['K'],proofs['B'],proofs['K'])

    def test_racer_actual_course_recent_form_and_start_samples_are_joined_by_id(self):
        result=self.ingest()
        self.assertEqual(result['normal_races'],3)
        p=self.store.racer_profile('4001',ASOF)
        self.assertEqual(p['starts'],3)
        self.assertEqual(p['normal_starts'],3)
        self.assertEqual(p['recent_10']['mean_finish'],7/3)
        self.assertAlmostEqual(p['recent_10']['mean_st'],.12)
        self.assertEqual(p['by_actual_course']['2']['starts'],1)
        self.assertEqual(p['by_actual_course']['1']['starts'],2)
        self.assertEqual(p['by_actual_course']['1']['wins'],1)
        self.assertFalse(p['source_publication_time_verified'])
        self.assertEqual(p['last_program']['name'],'TEST')
        self.assertEqual(p['last_program']['age'],30)
        self.assertEqual(p['last_program']['branch'],'東京')
        self.assertEqual(p['last_program']['program_day'],DAY.isoformat())

    def test_reingesting_same_bytes_is_idempotent_and_unknown_racer_stays_unknown(self):
        self.ingest();repeated=self.ingest(captured='2026-11-05T19:00:00+09:00')
        self.assertTrue(repeated['reused'])
        self.assertEqual(self.store.racer_profile('4001',ASOF)['starts'],3)
        empty=self.store.racer_profile('4999',ASOF)
        self.assertEqual(empty['starts'],0)
        self.assertIsNone(empty['recent_10']['mean_finish'])

    def test_source_capture_availability_is_not_backdated_to_the_race_day(self):
        self.ingest()
        p=self.store.racer_profile('4001','2026-11-05T17:00:00+09:00')
        self.assertEqual(p['starts'],0)

    def test_latest_visible_revision_replaces_samples_without_double_counting(self):
        self.ingest();self.ingest(start='0.20',captured='2026-11-05T20:00:00+09:00')
        early=self.store.racer_profile('4001','2026-11-05T19:00:00+09:00')
        late=self.store.racer_profile('4001',ASOF)
        self.assertEqual(early['starts'],3);self.assertEqual(late['starts'],3)
        self.assertAlmostEqual(early['recent_10']['mean_st'],.12)
        self.assertAlmostEqual(late['recent_10']['mean_st'],(.20+.12+.12)/3)

    def test_parser_upgrade_retains_old_import_and_selects_new_interpretation(self):
        import json
        from race_ai.boat_history_store import day_payload,wire
        raw,proof=archives(start='BROKEN')
        legacy=day_payload(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        legacy.pop('parser_revision');legacy['facts']=[r for r in legacy['facts'] if r['participation']!='UNRESOLVED']
        with self.store.db:self.store.db.execute('INSERT INTO imports VALUES (?,?,?,?,?,?)',
            ('legacy-import',DAY.isoformat(),legacy['available_at'],proof['B']['source_sha256'],proof['K']['source_sha256'],wire(legacy)))
        self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.assertEqual(self.store.inventory()['day_revisions'],2)
        self.assertEqual(len(self.store.history_rows(['4001'],ASOF)),3)

    def test_conflicting_source_bodies_at_same_capture_are_not_resolved_by_parser_version(self):
        self.ingest();self.ingest(start='0.20')
        with self.assertRaisesRegex(ValueError,'CAPTURE_CONFLICT'):self.store.history_rows(['4001'],ASOF)

    def test_f_start_is_retained_and_is_not_silently_a_normal_finish(self):
        result=self.ingest(start='F.02')
        self.assertEqual(result['excluded_races'],1)
        p=self.store.racer_profile('4001',ASOF)
        self.assertEqual(p['starts'],3)
        self.assertEqual(p['normal_starts'],2)
        self.assertEqual(p['st_dispositions']['F'],1)
        self.assertIsNone(p['recent_10']['mean_finish'])

    def test_unreadable_result_keeps_program_opportunity_without_inventing_start(self):
        self.ingest(start='BROKEN')
        rows=self.store.history_rows(['4001'],ASOF)
        self.assertEqual(len(rows),3)
        p=self.store.racer_profile('4001',ASOF)
        self.assertEqual(p['opportunities'],3)
        self.assertEqual(p['starts'],2)
        self.assertEqual(p['unresolved_opportunities'],1)
        self.assertIsNone(p['recent_10']['mean_finish'])
        self.assertIsNone(p['recent_10']['mean_st'])

    def test_motor_performance_is_venue_scoped_and_epoch_is_not_invented(self):
        self.ingest()
        m=self.store.motor_profile('17',55,ASOF)
        self.assertEqual(m['normal_starts'],3)
        self.assertEqual(m['top2'],2)
        self.assertEqual(m['top2_rate'],2/3)
        self.assertFalse(m['motor_epoch_verified'])
        self.assertFalse(m['usable_as_lifetime_motor_record'])
        self.assertEqual(self.store.motor_profile('18',55,ASOF)['starts'],0)

    def test_tight_motor_100_percent_field_does_not_become_a_different_motor_number(self):
        raw,proof=archives(motor=62)
        # Repack a real-layout tight two-digit motor / 100.00 rate boundary.
        from race_ai.boat_entry_observations import extract_daily_lzh
        body=extract_daily_lzh(raw['B'],'B261104.TXT').replace(b'62 35.00',b'62100.00')
        raw['B']=uncompressed_lzh(body,'B261104.TXT');proof['B']['source_sha256']=hashlib.sha256(raw['B']).hexdigest()
        self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.assertEqual(self.store.motor_profile('17',62,ASOF)['normal_starts'],3)

    def test_hash_or_source_identity_mismatch_cannot_create_history(self):
        for change in ('bytes','url'):
            raw,proof=archives()
            if change=='bytes':raw['K']+=b'changed'
            else:proof['K']['source_url']='https://boaters-boatrace.com/race'
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.assertEqual(self.store.racer_profile('4001',ASOF)['starts'],0)

    def test_three_digit_boat_column_can_touch_motor_rate_without_changing_motor(self):
        raw,proof=archives()
        from race_ai.boat_entry_observations import extract_daily_lzh
        for kind in ('B','K'):
            body=extract_daily_lzh(raw[kind],f'{kind}261104.TXT')
            body=body.replace(b'55 35.00 33 30.00',b'55 35.00161 30.00') if kind=='B' else body.replace(b'55 33 6.80',b'55 161 6.80')
            raw[kind]=uncompressed_lzh(body,f'{kind}261104.TXT');proof[kind]['source_sha256']=hashlib.sha256(raw[kind]).hexdigest()
        self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.assertEqual(self.store.motor_profile('17',55,ASOF)['normal_starts'],3)

    def test_database_is_private_and_a_symlink_is_not_followed(self):
        p=Path(self.tmp.name)/'linked.sqlite'
        p.symlink_to(Path(self.tmp.name)/'history.sqlite')
        from race_ai.boat_history_store import HistoryStore
        with self.assertRaises(ValueError):HistoryStore(p)
        self.assertEqual((Path(self.tmp.name)/'history.sqlite').stat().st_mode&0o077,0)

    def test_dated_venue_without_result_races_does_not_erase_other_venues(self):
        raw,proof=archives()
        from race_ai.boat_entry_observations import extract_daily_lzh
        b=extract_daily_lzh(raw['B'],'B261104.TXT')
        k=extract_daily_lzh(raw['K'],'K261104.TXT')
        second=b.decode('cp932').split('17BBGN\n',1)[1].split('17BEND',1)[0]
        b+=('\n18BBGN\n'+second+'18BEND\n').encode('cp932')
        k+='\n18KBGN\n2026/11/04\nレース成績なし\n18KEND\n'.encode('cp932')
        for kind,body in [('B',b),('K',k)]:
            raw[kind]=uncompressed_lzh(body,f'{kind}261104.TXT');proof[kind]['source_sha256']=hashlib.sha256(raw[kind]).hexdigest()
        result=self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.assertEqual(result['normal_races'],3)
        self.assertEqual(result['excluded_races'],3)
        self.assertEqual(result['fact_rows'],36)

    def test_parent_symlink_cannot_hide_a_public_git_checkout(self):
        repo=Path(self.tmp.name)/'repository';repo.mkdir(mode=0o700)
        (repo/'.git').mkdir(mode=0o700);private=repo/'private';private.mkdir(mode=0o700)
        alias=Path(self.tmp.name)/'alias';alias.symlink_to(private,target_is_directory=True)
        from race_ai.boat_history_store import HistoryStore
        with self.assertRaises(ValueError):
            other=HistoryStore(alias/'leak.sqlite');other.close()
        self.assertFalse((private/'leak.sqlite').exists())
