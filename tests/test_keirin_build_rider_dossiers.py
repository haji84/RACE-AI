"""Invented SQLite/registry identities; plaintext output remains owner-local."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import importlib
import json
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

DAY='2026-11-25'
NOW=datetime(2026,11,25,16,tzinfo=timezone.utc)


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def database(path,rows):
    with sqlite3.connect(path) as con:
        con.executescript('''
        CREATE TABLE races(race_date TEXT,venue_code TEXT,rno INTEGER,is_girls INTEGER,fetched_at TEXT,PRIMARY KEY(race_date,venue_code,rno));
        CREATE TABLE entries(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,racer_name TEXT,kyu TEXT,prefecture TEXT,racer_class TEXT,fetched_at TEXT,PRIMARY KEY(race_date,venue_code,rno,kumiban));
        CREATE TABLE results(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,racer_name TEXT,rank TEXT,is_incident INTEGER,fetched_at TEXT,PRIMARY KEY(race_date,venue_code,rno,kumiban));
        CREATE TABLE line_predictions(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,line_no INTEGER,position_in_line INTEGER,line_size INTEGER,role TEXT,PRIMARY KEY(race_date,venue_code,rno,kumiban));
        ''')
        for day,number,finish,cohort,pref,grade,result_name in rows:
            key=(day,'21',number)
            con.execute('INSERT INTO races VALUES(?,?,?,?,?)',(*key,0,'2026-11-24T12:00:00'))
            con.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)',(*key,1,'架空 選手',cohort,pref,grade,'2026-11-24T12:00:00'))
            con.execute('INSERT INTO line_predictions VALUES(?,?,?,?,?,?,?,?)',(*key,1,1,1,1,'追込'))
            if finish is not None:
                con.execute('INSERT INTO results VALUES(?,?,?,?,?,?,?,?)',(*key,1,result_name or '架空選手',str(finish),int(finish=='落'),'2026-11-24T12:20:00'))
    path.chmod(0o600)


class RiderDossierAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        self.first=self.root/'earlier.db';self.second=self.root/'later.db'
        rows=[('20251001',1,3,'100','東京','A1',None),('20261001',1,2,'100','東京','S1',None),
              ('20261124',1,1,'100','東京','A2',None),('20261125',1,4,'100','東京','S2',None),
              ('20261126',1,1,'100','東京','S2',None),('20261123',1,2,'100','東京','A1','別の選手'),
              ('20261122',1,None,'100','東京','S1',None),('20261121',1,'落','100','東京','A1',None),
              ('20261120',1,1,'A1','東京','S2',None)]
        database(self.first,rows)
        database(self.second,[rows[1]])
        self.registry=dict(schema='KEIRIN_OFFICIAL_CURRENT_REGISTRY_V1',complete=True,
            scope='NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT',
            retrieval_started_at=DAY+'T15:00:00+00:00',retrieval_completed_at=DAY+'T15:01:00+00:00',
            riders=[dict(registration='012345',name='架空選手',prefecture_or_country='東京都',cohort=100,
                **{'class':'S2'},class_source_label='現級班',gender='male',district='架空地区',
                source_url='https://keirin.jp/pc/dfw/dataplaza/guest/membctl?clear=1',source_sha256='a'*64,
                captured_at=DAY+'T15:00:30+00:00',index_updated_at_jst=DAY,
                knowledge_scope='NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT'),
                dict(registration='054321',name='履歴なし選手',prefecture_or_country='大阪府',cohort=101,
                **{'class':'A1'},class_source_label='現級班',gender='male',district='架空地区',
                source_url='https://keirin.jp/pc/dfw/dataplaza/guest/membctl?clear=1',source_sha256='a'*64,
                captured_at=DAY+'T15:00:30+00:00',index_updated_at_jst=DAY,
                knowledge_scope='NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT')])
        self.refresh_manifest()

    def module(self):
        try:return importlib.import_module('scripts.keirin_build_rider_dossiers')
        except ModuleNotFoundError:self.fail('The existing-history private dossier adapter is missing.')

    def refresh_manifest(self):
        self.manifest=dict(schema='KEIRIN_PUBLIC_GITHUB_DOWNLOAD_V1',started_at=DAY+'T12:00:00+00:00',
            completed_at=DAY+'T12:01:00+00:00',sources=[dict(file=p.name,sha256=sha256(p.read_bytes()).hexdigest(),
                bytes=p.stat().st_size,url='https://raw.githubusercontent.com/example/data/'+'b'*40+'/data/'+p.name)
                for p in (self.first,self.second)])

    def build(self,**options):
        raw=encode(self.registry)
        return self.module().build_dossiers([self.first,self.second],raw,encode(self.manifest),
            expected_registry_sha256=sha256(raw).hexdigest(),as_of_day=DAY,clock=lambda:NOW,**options)

    def observation(self):
        identity=dict(race_id='202611242101',car=1,registration='012345')
        observed=dict(identity,sha256='c'*64,url='https://keirin.kdreams.jp/race/one',
            available_at='2026-11-24T09:00:00Z')
        verified=dict(identity,sha256='d'*64,url='https://keirin.netkeiba.com/race/result/?race_id=202611242101',
            available_at='2026-11-24T09:30:00Z',finish=1)
        return dict(identity,event_id='outer-pass',ability='tactical_switch',source='video',
            outcome='success',measurement='relative_position',reviewed_at='2026-11-24T10:00:00Z',
            published_at=None,observation_receipt=observed,identity_receipt=verified)

    def tactical_packet(self,episodes):
        raw=encode(dict(schema='KEIRIN_REVIEWED_TACTICAL_EPISODES_V1',
            scope='PRIVATE_RETROSPECTIVE_TACTICAL_OBSERVATIONS',prepared_at='2026-11-25T10:00:00Z',episodes=episodes))
        return dict(tactical_raw=raw,expected_tactical_sha256=sha256(raw).hexdigest())

    def test_pinned_reviewed_observation_is_attached_without_changing_basic_history(self):
        original,_=self.build()
        options=self.tactical_packet([self.observation()])
        private,summary=self.build(**options)
        person=private['dossiers'][0]
        profile=person['tactical_observations']
        self.assertEqual(len(profile['abilities']),6)
        self.assertEqual(profile['abilities']['tactical_switch']['observed_successes'],1)
        self.assertEqual(profile['abilities']['follower_acceleration']['state'],'unobserved')
        self.assertIsNone(profile['predictive_rating'])
        self.assertEqual(person['finish_history'],original['dossiers'][0]['finish_history'])
        self.assertNotIn('tactical_observations',private['dossiers'][1])
        self.assertNotIn('tactical_observations',original)
        self.assertEqual(summary['tactical_observations']['source_sha256'],options['expected_tactical_sha256'])
        self.assertEqual(summary['tactical_observations']['admitted_rows'],1)
        self.assertNotIn('012345',json.dumps(summary))

    def test_missing_or_substituted_tactical_pin_is_rejected(self):
        options=self.tactical_packet([self.observation()])
        with self.assertRaisesRegex(ValueError,'TACTICAL_SHA_MISMATCH'):
            self.build(tactical_raw=options['tactical_raw'])
        with self.assertRaisesRegex(ValueError,'TACTICAL_SHA_MISMATCH'):
            self.build(tactical_raw=options['tactical_raw'],expected_tactical_sha256='f'*64)
        with self.assertRaisesRegex(ValueError,'TACTICAL_SHA_MISMATCH'):
            self.build(expected_tactical_sha256=options['expected_tactical_sha256'])
        unscoped=json.loads(options['tactical_raw']);unscoped['scope']='FORECAST_INPUT'
        raw=encode(unscoped)
        with self.assertRaisesRegex(ValueError,'TACTICAL_SCHEMA'):
            self.build(tactical_raw=raw,expected_tactical_sha256=sha256(raw).hexdigest())

    def test_late_or_unbound_reviews_are_held_without_inventing_outcomes(self):
        valid=self.observation()
        late=dict(valid,event_id='after-cutoff',reviewed_at='2026-11-24T15:00:00Z')
        wrong=dict(valid,event_id='mismatch',identity_receipt=dict(valid['identity_receipt'],registration='054321'))
        same_source=dict(valid,event_id='same-source',identity_receipt=dict(valid['identity_receipt'],sha256=valid['observation_receipt']['sha256']))
        future=dict(valid,event_id='future',race_id='202611252101')
        future['observation_receipt']=dict(valid['observation_receipt'],race_id=future['race_id'])
        future['identity_receipt']=dict(valid['identity_receipt'],race_id=future['race_id'])
        unresolved=dict(valid,event_id='result-unconfirmed',ability='inside_outside',side='outside',finish=2)
        del unresolved['outcome'],unresolved['measurement']
        _,summary=self.build(**self.tactical_packet([valid,late,wrong,same_source,future,unresolved]))
        tactical=summary['tactical_observations']
        self.assertEqual(tactical['admitted_rows'],1)
        self.assertEqual(tactical['held_by_reason'],{'REVIEW_NOT_AVAILABLE':1,'RECEIPT_UNBOUND':3,'RACE_NOT_HISTORICAL':1})

    def test_conflicting_verified_finishes_leave_that_starter_missing(self):
        valid=self.observation()
        other=dict(valid,event_id='same-race',identity_receipt=dict(valid['identity_receipt'],finish=2))
        private,summary=self.build(**self.tactical_packet([valid,other]))
        self.assertNotIn('tactical_observations',private['dossiers'][0])
        self.assertEqual(summary['tactical_observations']['held_by_reason'],{'STARTER_CONFLICT':2})

    def test_existing_identity_and_history_authorities_keep_cohort_grade_and_current_class_separate(self):
        private,summary=self.build()
        person=next(p for p in private['dossiers'] if p['registration']=='012345')
        history=person['finish_history']
        self.assertEqual(history['periods']['all']['observed_count'],3)
        self.assertEqual(history['periods']['all']['finish_counts'][1],1)
        self.assertEqual(set(history['periods']),{'all','3_years','1_year','6_months','4_months','3_months','1_month'})
        self.assertEqual(set(history['last_starts']),{30,20,10,5})
        self.assertEqual(person['registry_class']['value'],'S2')
        self.assertEqual(person['archived_classes_on_latest_finish_day'],['A2'])
        self.assertEqual(person['historical_grade_counts'],{'A':2,'S':1})
        self.assertEqual(summary['duplicate_same_count'],1)
        self.assertEqual(summary['registered_riders'],2)
        self.assertIs(summary['historical_as_of_authenticated'],False)
        self.assertIs(summary['frozen_forecasts_modified'],False)

    def test_same_day_future_unknown_and_mismatched_result_rows_are_not_invented_finishes(self):
        private,summary=self.build();person=private['dossiers'][0]
        self.assertEqual(person['finish_history']['periods']['all']['latest_observed_day'],'2026-11-24')
        self.assertIsNone(person['finish_history']['periods']['all']['missing_finish_count'])
        self.assertEqual(summary['held_by_reason']['RESULT_NAME_MISMATCH'],1)
        self.assertEqual(summary['held_by_reason']['RESULT_MISSING'],1)
        self.assertEqual(summary['held_by_reason']['INCIDENT_OR_NONNUMERIC_FINISH'],1)
        self.assertEqual(summary['held_by_reason']['IDENTITY_UNRESOLVED'],1)
        empty=private['dossiers'][1]['finish_history']
        self.assertEqual(empty['periods']['all']['observed_count'],0)
        self.assertIsNone(empty['periods']['all']['finish_rates'])
        self.assertEqual(empty['last_starts'][30]['unfilled_slots'],30)

    def test_current_registry_knowledge_after_cutoff_is_explicitly_retrospective(self):
        private,summary=self.build()
        self.assertEqual(private['identity_knowledge_as_of'],self.registry['retrieval_completed_at'])
        self.assertTrue(private['registry_captured_after_history_cutoff'])
        self.assertFalse(summary['complete_lifetime_history'])
        self.assertFalse(summary['complete_three_year_history'])
        self.assertEqual(summary['calendar_months_observed'],3)
        self.assertEqual(summary['coverage_span_calendar_months'],14)
        self.assertEqual(summary['history_end_day'],'2026-11-24')
        self.assertIn('RETROSPECTIVE',private['scope'])

    def test_incomplete_or_hash_substituted_registry_is_refused(self):
        self.registry['complete']=False
        with self.assertRaisesRegex(ValueError,'REGISTRY_INCOMPLETE'):self.build()
        self.registry['complete']=True
        with self.assertRaisesRegex(ValueError,'REGISTRY_SHA'):
            self.module().build_dossiers([self.first],encode(self.registry),encode(self.manifest),
                expected_registry_sha256='f'*64,as_of_day=DAY,clock=lambda:NOW)

    def test_reused_earlier_official_capture_retains_its_clock_without_backdating_complete_registry(self):
        self.registry['riders'][0]['captured_at']=DAY+'T14:59:00+00:00'
        private,summary=self.build()
        self.assertEqual(private['dossiers'][0]['registry_class']['captured_at'],DAY+'T14:59:00+00:00')
        self.assertEqual(private['identity_knowledge_as_of'],DAY+'T15:01:00+00:00')

    def test_conflicting_archives_hold_both_numeric_records_instead_of_choosing_one(self):
        with sqlite3.connect(self.second) as con:con.execute("UPDATE results SET rank='1'")
        self.refresh_manifest()
        private,summary=self.build()
        self.assertEqual(private['dossiers'][0]['finish_history']['periods']['all']['observed_count'],2)
        self.assertEqual(summary['duplicate_conflict_count'],1)

    def test_database_sha_mismatch_is_refused_without_modifying_any_input(self):
        before={p:p.read_bytes() for p in (self.first,self.second)}
        self.manifest['sources'][0]['sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'DATABASE_SHA'):self.build()
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertFalse(any(self.root.glob('*-wal')))

    def test_private_output_modes_and_public_summary_do_not_disclose_profiles(self):
        module=self.module();private,summary=self.build();out=self.root/'output'
        files=module.write_private(out,private,summary)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode),0o700)
        for p in files.values():self.assertEqual(stat.S_IMODE(Path(p).stat().st_mode),0o600)
        self.assertNotIn('架空',json.dumps(summary,ensure_ascii=False))
        self.assertNotIn('012345',json.dumps(summary))
        with self.assertRaises((ValueError,FileExistsError)):module.write_private(out,private,summary)
        unsafe=self.root/'public';unsafe.mkdir(mode=0o755);unsafe.chmod(0o755)
        with self.assertRaises(ValueError):module.write_private(unsafe,private,summary)

    def test_parent_producer_reuses_the_same_book_and_identity_index(self):
        book,index,summary=self.module().load_archive_book([self.first,self.second],self.registry,DAY,archive_manifest=self.manifest,clock=lambda:NOW)
        self.assertEqual(index.bind(('架空選手',100,'東京')),'012345')
        self.assertEqual(book.finish_history('012345',race_id='202611252101')['periods']['all']['observed_count'],3)
        self.assertEqual(len(summary['archive_sha256s']),2)

    def test_book_facade_does_not_admit_registry_knowledge_from_the_future(self):
        self.registry['retrieval_completed_at']='2099-11-25T15:01:00+00:00'
        with self.assertRaisesRegex(ValueError,'REGISTRY_CAPTURE_AFTER_BUILD'):
            self.module().load_archive_book([self.first],self.registry,DAY,archive_manifest=self.manifest)

    def test_book_facade_does_not_backdate_a_future_archive_capture(self):
        self.manifest['completed_at']='2099-11-25T15:01:00+00:00'
        with self.assertRaisesRegex(ValueError,'SOURCE_CAPTURE_CLOCK'):
            self.module().load_archive_book([self.first],self.registry,DAY,archive_manifest=self.manifest,clock=lambda:NOW)


if __name__=='__main__':unittest.main()
