"""Boundary tests for the standalone web-root observation contract."""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from web.race_contract import canonical,program_digest,validate_record,validate_summary
from tests import test_race_update_merge as fixtures
from tests.test_official_race_updates import DAY,odds
from race_ai.official_race_updates import parse_update,endpoint


NOW=datetime.fromisoformat('2026-10-15T10:00:00+09:00')


class RaceCloudContractTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixtures.RaceUpdateMergeTests()
        self.race=self.helper.feed()['venues'][0]['races'][0]

    def rehash(self,record):
        record['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in record.items() if k not in {'snapshot_id','saved_at','storage_eligible_pre_race'}})).hexdigest()
        return record

    def record(self,kind='beforeinfo',**kwargs):
        if kind=='raceresult': kwargs.setdefault('capture','2026-10-15T09:00:00+09:00');kwargs.setdefault('saved','2026-10-15T09:01:00+09:00')
        return self.helper.observation(kind,**kwargs)

    def test_current_parser_shapes_and_pending_dispositions_validate(self):
        for record in [self.record(),self.record('odds3t'),self.record('raceresult'),
                self.record('odds3t',body=odds(missing=True)),
                self.record('raceresult',body='<p>結果はまだありません。</p>'),
                self.record('raceresult',body='<span class="heading1_mainLabel">レース中止</span>'),
                self.record('raceresult',body='<span class="heading1_mainLabel">レース延期</span>')]:
            with self.subTest(kind=record['kind'],status=record['status']):
                self.assertEqual(validate_record(record,self.race,NOW),record)
        pending=parse_update('<p>データがありません。</p>'.encode(),kind='beforeinfo',day=DAY,venue='18',race_no=1,
            source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at='2026-10-15T07:00:00+09:00')
        pending.update(saved_at='2026-10-15T07:01:00+09:00',storage_eligible_pre_race=False)
        self.rehash(pending)
        self.assertEqual(validate_record(pending,self.race,NOW),pending)

    def test_extra_fields_bool_nonfinite_and_result_fields_rejected_even_after_rehash(self):
        mutations=[lambda r:r.update(unreviewed=True),lambda r:r.update(schema_version=True),
            lambda r:r['data']['boats'][0].update(lane=True),
            lambda r:r['data']['boats'][0].update(display_time=True),
            lambda r:r['data']['boats'][0].update(display_time=-1),
            lambda r:r['data']['boats'][0].update(actual_st=.1),
            lambda r:r['data'].update(payouts=[]),
            lambda r:r['data']['weather'].update(reported_at='2026-10-15T08:00:00+09:00')]
        for mutation in mutations:
            record=self.record();mutation(record);self.rehash(record)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(record,self.race,NOW)
        record=self.record();record['data']['boats'][0]['display_time']=float('nan')
        with self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_program_registration_name_cutoff_and_endpoint_must_match(self):
        for mutation in [lambda r:r['data']['boats'][0].update(racer_registration_id='4999'),
                lambda r:r['data']['boats'][0].update(name='別選手'),
                lambda r:r.update(closed_at='2026-10-15T09:43:00+09:00'),
                lambda r:r.update(source_url=r['source_url']+'&secret=x')]:
            record=self.record();mutation(record);self.rehash(record)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_body_null_status_and_information_phase_are_consistent(self):
        for mutation in [lambda r:r.update(data=None,status='AVAILABLE'),
                lambda r:r.update(body_identity_verified=False,eligible_pre_race=False,storage_eligible_pre_race=False),
                lambda r:r.update(information_phase='official_result'),
                lambda r:r.update(available_at='2026-10-15T06:00:00+09:00'),
                lambda r:r.update(upstream_published_at='2026-10-15T06:00:00+09:00')]:
            record=self.record();mutation(record);self.rehash(record)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_future_and_cross_day_cloud_times_rejected_without_removing_offline_history(self):
        late=self.record(capture='2026-10-15T09:00:00+09:00',saved='2026-10-15T09:01:00+09:00')
        late['captured_at']=late['available_at']='2026-10-16T09:00:00+09:00';late['saved_at']='2026-10-16T09:01:00+09:00';self.rehash(late)
        later=datetime.fromisoformat('2026-10-16T10:00:00+09:00')
        self.assertEqual(validate_record(late,self.race,later),late)
        with self.assertRaises(ValueError): validate_record(late,self.race,later,require_same_day=True)
        with self.assertRaises(ValueError): validate_record(late,self.race,NOW)
        record=self.record();record['saved_at']='2026-10-15T10:00:01+09:00'
        with self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_invalid_timezone_offset_is_not_normalized_into_valid_capture(self):
        record=self.record()
        record['captured_at']=record['available_at']='2026-10-15T08:39:00+09:99'
        record['saved_at']='2026-10-15T08:40:00+09:99';self.rehash(record)
        with self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_verified_placeholder_null_retains_six_program_identity_proofs(self):
        record=self.record();racers=[{k:b[k] for k in ('lane','racer_registration_id','name')} for b in record['data']['boats']]
        record.update(data=None,status='PENDING',missing_reason='OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID',observed_racers=racers);self.rehash(record)
        self.assertEqual(validate_record(record,self.race,NOW),record)
        for mutation in (lambda r:r['observed_racers'][0].update(racer_registration_id='4999'),
                         lambda r:r.pop('observed_racers'),lambda r:r.update(body_identity_verified=False)):
            changed=copy.deepcopy(record);mutation(changed);self.rehash(changed)
            with self.assertRaises(ValueError): validate_record(changed,self.race,NOW)
        odds_record=self.record('odds3t')
        racers=[{k:b[k] for k in ('lane','racer_registration_id','name')} for b in odds_record['data']['racers']]
        odds_record.update(data=None,status='PENDING',missing_reason='OFFICIAL_ODDS_ALL_ZERO_PLACEHOLDER',observed_racers=racers);self.rehash(odds_record)
        self.assertEqual(validate_record(odds_record,self.race,NOW),odds_record)
        odds_record['observed_racers'][0]['racer_registration_id']='4001';self.rehash(odds_record)
        with self.assertRaises(ValueError): validate_record(odds_record,self.race,NOW)

    def test_all120_odds_identity_value_availability_and_source_racers_checked(self):
        mutations=[lambda r:r['data']['odds'][0].update(combination=[True,2,3]),
            lambda r:r['data']['odds'][0].update(odds=15.5),
            lambda r:r['data']['odds'][0].update(availability='PENDING'),
            lambda r:r['data']['racers'][0].update(name='別選手'),
            lambda r:r['data']['racers'][0].update(racer_registration_id='4001'),
            lambda r:r['data'].pop('racers'),lambda r:r['data']['odds'].pop()]
        for mutation in mutations:
            record=self.record('odds3t');mutation(record);self.rehash(record)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_zero_placeholder_slot_reason_requires_verified_current_clock_profile(self):
        record=self.record('odds3t')
        record['data']['source_reported_time_label']='オッズ更新時間 7:06'
        record['status']='PARTIAL'
        for row in record['data']['odds'][9:]: row.update(odds=None,availability='PENDING',missing_reason='SOURCE_ZERO_PLACEHOLDER')
        self.rehash(record)
        self.assertEqual(validate_record(record,self.race,NOW),record)
        mutations=[lambda r:r['data']['odds'][9].pop('missing_reason'),
            lambda r:r['data']['odds'][9].update(missing_reason=True),
            lambda r:r['data']['odds'][9].update(missing_reason='NO_BETS'),
            lambda r:r['data']['odds'][0].update(missing_reason='SOURCE_ZERO_PLACEHOLDER'),
            lambda r:r['data'].update(source_reported_time_label='08:00現在'),
            lambda r:r['data'].update(source_reported_time_label='オッズ更新時間 7:99'),
            lambda r:r['data'].update(source_reported_time_label='締切時オッズ',odds_phase='final')]
        for mutation in mutations:
            changed=copy.deepcopy(record);mutation(changed);self.rehash(changed)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(changed,self.race,NOW)
        all_zero=copy.deepcopy(record)
        for row in all_zero['data']['odds']: row.update(odds=None,availability='PENDING',missing_reason='SOURCE_ZERO_PLACEHOLDER')
        all_zero['status']='PENDING';self.rehash(all_zero)
        with self.assertRaises(ValueError): validate_record(all_zero,self.race,NOW)

    def test_payout_types_winner_coverage_and_derived_readiness_are_checked(self):
        mutations=[lambda r:r['data'].update(confirmed=True,settlement_ready=True),
            lambda r:r['data']['verified_market_types'].append('win'),
            lambda r:r['data']['payouts'][0].update(payout_per_100_yen=True),
            lambda r:r['data']['payouts'][0].update(combination=[3,2,1]),
            lambda r:r['data']['results'][0].update(actual_st=True),
            lambda r:r['data']['results'][0].update(name='別選手'),
            lambda r:r['data'].update(top3=[True,2,3])]
        for mutation in mutations:
            record=self.record('raceresult');mutation(record);self.rehash(record)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_record(record,self.race,NOW)

    def test_program_digest_binds_identity_but_ignores_display_fields(self):
        original=program_digest(self.race);race=copy.deepcopy(self.race)
        race['boats'].reverse();race['boats'][0]['name']='  選手 ６ ';race['boats'][0]['display_time']=123
        race['closed_at']='2026-10-14T23:43:00Z'
        self.assertEqual(program_digest(race),original)
        for field,value in [('name','別選手'),('racer_registration_id','4999')]:
            changed=copy.deepcopy(self.race);changed['boats'][0][field]=value
            self.assertNotEqual(program_digest(changed),original)

    def test_summary_checks_metadata_and_cannot_be_submitted_as_full_record(self):
        summary=self.helper.merge(self.helper.feed(),[self.record()])['venues'][0]['races'][0]['official_updates']['records'][0]
        self.assertEqual(validate_summary(summary,self.race,NOW),summary)
        with self.assertRaises(ValueError): validate_record(summary,self.race,NOW)
        summary['storage_eligible_pre_race']=False
        with self.assertRaises(ValueError): validate_summary(summary,self.race,NOW)

    def test_module_loads_standalone_with_no_repository_package_imports(self):
        path=Path(__file__).resolve().parents[1]/'web/race_contract.py'
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'race.json';fixture.write_text(json.dumps(self.race,ensure_ascii=False),encoding='utf-8')
            script="import json,runpy,sys; contract=runpy.run_path(sys.argv[1]); print(contract['program_digest'](json.load(open(sys.argv[2],encoding='utf-8'))))"
            result=subprocess.run([sys.executable,'-I','-S','-c',script,str(path),str(fixture)],cwd=folder,capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),program_digest(self.race))
