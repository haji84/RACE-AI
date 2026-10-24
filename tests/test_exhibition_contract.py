"""Synthetic display-only research comparisons; never live betting evidence."""
import copy
from datetime import timedelta
import hashlib
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

from tests.test_live_evaluation_contract import fixture as frozen_fixture, rehash, PRE_RACE
from web import race_contract as facts

NOW = PRE_RACE + timedelta(minutes=1)
ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return frozen_fixture(kind='beforeinfo', capture=PRE_RACE)


def refresh(bundle):
    record = bundle['records'][0]['record']; rehash(record)
    bundle['latest']['beforeinfo'] = record['snapshot_id']


def sha(value):
    return hashlib.sha256(facts.canonical(value)).hexdigest()


class ExhibitionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.contract = importlib.import_module('web.exhibition_contract')
        except ModuleNotFoundError: cls.contract = None

    def setUp(self):
        self.assertIsNotNone(self.contract, 'pure post-exhibition contract must exist')
        self.baseline, self.bundle, self.race = fixture()

    def build(self, now=NOW):
        return self.contract.build_post_exhibition_bundle(self.baseline, self.bundle, self.race, now)

    def test_equal_display_times_retain_frozen_baseline_and_complete_deltas(self):
        post = self.build(); base = self.baseline['snapshot']['models'][1]
        self.assertEqual(post['phase'], 'post_exhibition')
        self.assertEqual(post['model']['model_id'], 'official-beforeinfo-display-pl')
        self.assertEqual(post['model']['model_version'], '1')
        self.assertEqual(post['model']['parameters'], dict(display_coefficient_per_second=1.0,
            log_strength_min=-20.0, log_strength_max=20.0, rating_floor=0.01))
        self.assertEqual(len(post['model']['triples']), 120)
        self.assertEqual(len(post['model']['marginals']), 6)
        self.assertAlmostEqual(math.fsum(r['probability'] for r in post['model']['triples']), 1, places=13)
        self.assertAlmostEqual(math.fsum(r['delta_probability'] for r in post['deltas']['triples']), 0, places=13)
        self.assertAlmostEqual(post['model']['triples'][0]['probability'], base['triples'][0]['probability'], places=14)
        self.assertAlmostEqual(post['deltas']['marginals'][0]['first']['delta_probability'], 0, places=14)
        self.assertEqual(post['purchase_decision'], 'skip'); self.assertEqual(post['purchase_recommendations'], [])
        self.assertTrue(post['research_only']); self.assertEqual(post['validation_status'], 'UNVALIDATED')

    def test_display_adjustment_matches_hand_calculated_strengths(self):
        rows = self.bundle['records'][0]['record']['data']['boats']
        for row, value in zip(rows, [6.0, 6.2, 6.4, 6.6, 6.8, 7.0]): row['display_time'] = value
        refresh(self.bundle); post = self.build()
        base_strength = self.baseline['snapshot']['models'][1]['strengths'][0]['strength']
        self.assertAlmostEqual(post['boats'][0]['display_delta_seconds'], 0.5, places=12)
        self.assertAlmostEqual(post['boats'][0]['adjusted_strength'], base_strength * math.exp(.5), places=12)
        first = post['deltas']['triples'][0]
        self.assertEqual(first['combination'], [1, 2, 3])
        self.assertAlmostEqual(first['delta_probability'], first['post_probability']-first['baseline_probability'], places=14)
        self.assertGreater(post['deltas']['marginals'][0]['first']['delta_probability'], 0)

    def test_links_pin_receipts_and_separate_archive_and_roster_digests(self):
        post = self.build(); receipt = self.bundle['records'][0]
        self.assertEqual(post['baseline_link'], dict(request_id='123456-1', snapshot_id=self.baseline['snapshot']['snapshot_id'],
            receipt_sha256=sha(self.baseline), cloud_saved_at=self.baseline['cloud_saved_at'], model_id='official-program-rating-pl'))
        self.assertEqual(post['beforeinfo_link']['receipt_sha256'], sha(receipt))
        self.assertEqual(post['beforeinfo_link']['snapshot_id'], self.bundle['latest']['beforeinfo'])
        self.assertEqual(post['b_program_sha256'], self.baseline['program_sha256'])
        self.assertEqual(post['program_identity_sha256'], facts.program_digest(self.race))
        self.assertNotEqual(post['b_program_sha256'], post['program_identity_sha256'])

    def test_available_st_only_preview_cannot_generate_forecast(self):
        for row in self.bundle['records'][0]['record']['data']['boats']: row['display_time'] = None
        refresh(self.bundle)
        self.assertEqual(self.bundle['records'][0]['record']['status'], 'AVAILABLE')
        with self.assertRaisesRegex(ValueError, '^DISPLAY_INCOMPLETE$'): self.build()

    def test_missing_baseline_missing_preview_and_pending_have_fixed_reasons(self):
        with self.assertRaisesRegex(ValueError, '^BASELINE_MISSING$'):
            self.contract.build_post_exhibition_bundle(None, self.bundle, self.race, NOW)
        with self.assertRaisesRegex(ValueError, '^PREVIEW_NOT_OBTAINED$'):
            self.contract.build_post_exhibition_bundle(self.baseline, None, self.race, NOW)
        record = self.bundle['records'][0]['record']
        record.update(status='PENDING', data=None, missing_reason='OFFICIAL_PAGE_HAS_NO_DATA',
            body_identity_verified=False, eligible_pre_race=False, storage_eligible_pre_race=False)
        record.pop('closed_at'); self.bundle['records'][0]['cloud_eligible_pre_race'] = False; refresh(self.bundle)
        with self.assertRaisesRegex(ValueError, '^PREVIEW_PENDING$'): self.build()

    def test_missing_rating_uses_explicit_frozen_uniform_reference(self):
        # Rebuild a real canonical B snapshot with absent national rating, rather
        # than inventing a missing-rating flag in a stored deterministic bundle.
        from tests.test_live_research_contract import fixture as program_fixture
        from web import research_contract
        feed, race = program_fixture()
        race.update(race_id=self.race['race_id'], closed_at=self.race['closed_at'])
        feed['venues'][0]['venue'] = '18'
        for row in race['boats']: row['name'] = '選手' + str(row['lane'])
        race['boats'][0]['national_win_rate'] = None
        snapshot = research_contract.build_research_bundle(feed, race, PRE_RACE)
        self.baseline.update(snapshot=snapshot, program_sha256=snapshot['program_sha256'])
        post = self.build()
        self.assertEqual(post['baseline_link']['model_id'], 'official-program-uniform-pl')
        self.assertTrue(all(row['base_strength'] == 1 for row in post['boats']))

    def test_st_weather_original_and_video_are_honestly_unused(self):
        post = self.build(); statuses = post['feature_status']
        self.assertEqual(statuses['display_time'], dict(status='AVAILABLE', used=True, reason=None))
        self.assertEqual(statuses['preview_st']['status'], 'OBSERVED_UNUSED')
        self.assertEqual(statuses['weather']['status'], 'SOURCE_TIME_UNVERIFIED_UNUSED')
        self.assertEqual(statuses['original_exhibition']['status'], 'MISSING')
        self.assertEqual(statuses['exhibition_video']['status'], 'MISSING')
        self.assertTrue(all(not value['used'] for key, value in statuses.items() if key != 'display_time'))
        rows = self.bundle['records'][0]['record']['data']['boats']
        rows[0].update(preview_st=None, preview_st_status='PENDING', preview_raw_st='--')
        refresh(self.bundle); partial = self.build()
        self.assertEqual(partial['feature_status']['preview_st']['status'], 'PARTIAL_UNUSED')
        self.assertEqual(partial['model']['triples'], post['model']['triples'])
        for row in rows: row.update(preview_st=None, preview_st_status='PENDING', preview_raw_st='--')
        self.bundle['records'][0]['record']['data']['weather']['wind_speed_mps'] = 30
        refresh(self.bundle); missing = self.build()
        self.assertEqual(missing['feature_status']['preview_st']['status'], 'MISSING')
        self.assertEqual(missing['model']['triples'], post['model']['triples'])

    def test_clamped_extremes_remain_finite_and_replayable(self):
        for row, value in zip(self.bundle['records'][0]['record']['data']['boats'], [.01, 100, 100, 100, 100, 100]): row['display_time'] = value
        refresh(self.bundle); post = self.build()
        self.assertEqual(post['boats'][0]['adjusted_strength'], math.exp(20))
        self.assertTrue(all(math.isfinite(r['probability']) and r['probability'] >= 0 for r in post['model']['triples']))

    def test_explicit_exhibition_false_start_is_observed_unused_not_missing(self):
        row=self.bundle['records'][0]['record']['data']['boats'][0]
        row.update(preview_st=None,preview_st_status='F',preview_raw_st='F.01')
        refresh(self.bundle)
        self.assertEqual(self.build()['feature_status']['preview_st']['status'],'OBSERVED_UNUSED')

    def test_rehashed_model_link_feature_and_probability_tampering_rejected(self):
        mutations = [lambda p: p['model']['parameters'].update(display_coefficient_per_second=2),
            lambda p: p['model']['triples'][0].update(probability=.5),
            lambda p: p['deltas']['triples'][0].update(delta_probability=.5),
            lambda p: p['baseline_link'].update(request_id='654321-1'),
            lambda p: p['beforeinfo_link'].update(source_sha256='b'*64),
            lambda p: p['boats'][0].update(display_time_seconds=5),
            lambda p: p['feature_status']['exhibition_video'].update(used=True),
            lambda p: p.update(b_program_sha256=p['program_identity_sha256'])]
        for mutate in mutations:
            post = self.build(); mutate(post); post['snapshot_id'] = sha({k:v for k,v in post.items() if k != 'snapshot_id'})
            with self.subTest(mutate=repr(mutate)), self.assertRaises(ValueError):
                self.contract.validate_post_exhibition_bundle(post, self.baseline, self.bundle['records'][0], self.race, NOW)

    def test_cloud_source_and_baseline_clocks_rejected_without_trusting_flags(self):
        mutations = [lambda: self.bundle['records'][0].update(cloud_saved_at=self.race['closed_at']),
            lambda: self.bundle['records'][0].update(cloud_saved_at='2026-10-15T07:33:00+09:00'),
            lambda: self.bundle['records'][0].update(cloud_eligible_pre_race=False),
            lambda: self.bundle.update(program_sha256='b'*64),
            lambda: self.baseline.update(cloud_saved_at=self.race['closed_at'])]
        for mutate in mutations:
            self.baseline, self.bundle, self.race = fixture(); mutate()
            with self.subTest(mutate=repr(mutate)), self.assertRaises(ValueError): self.build()

    def test_no_generation_at_close_naive_future_or_wrong_day(self):
        close = facts._time(self.race['closed_at'])
        for now in [close, close+timedelta(seconds=1), NOW.replace(tzinfo=None), NOW+timedelta(days=1)]:
            with self.subTest(now=now), self.assertRaises(ValueError): self.build(now)
        self.bundle['published_at'] = facts.stamp(NOW+timedelta(seconds=1))
        with self.assertRaises(ValueError): self.build()

    def test_stored_replay_after_close_uses_frozen_rating_and_receipts(self):
        post = self.build(); self.race['boats'][0]['national_win_rate'] = .2
        replay = self.contract.validate_post_exhibition_bundle(post, self.baseline, self.bundle['records'][0], self.race,
            facts._time(self.race['closed_at'])+timedelta(minutes=1))
        self.assertEqual(replay, post)
        self.race['boats'][0]['racer_registration_id'] = '4999'
        with self.assertRaises(ValueError):
            self.contract.validate_post_exhibition_bundle(post, self.baseline, self.bundle['records'][0], self.race, NOW)

    def test_sources_rehashed_but_not_canonical_and_result_inputs_are_rejected(self):
        for mutation in [lambda r: r.update(source_url='https://attacker.example/'),
                         lambda r: r['data']['boats'][0].update(racer_registration_id='4999'),
                         lambda r: r['data']['boats'][0].update(actual_course=1)]:
            self.baseline, self.bundle, self.race = fixture(); mutation(self.bundle['records'][0]['record']); refresh(self.bundle)
            with self.assertRaises(ValueError): self.build()
        self.baseline, self.bundle, self.race = fixture()
        _, result, _ = frozen_fixture()
        with self.assertRaises(ValueError):
            self.contract.build_post_exhibition_bundle(self.baseline, result, self.race, NOW)

    def test_inputs_and_returned_nested_arrays_are_detached(self):
        original = copy.deepcopy((self.baseline, self.bundle, self.race)); post = self.build()
        self.assertEqual((self.baseline, self.bundle, self.race), original)
        post['model']['triples'][0]['combination'][0] = 6
        post['boats'][0]['display_time_seconds'] = 0
        self.assertEqual((self.baseline, self.bundle, self.race), original)

    def test_standalone_import_and_replay_do_not_require_storage_or_optional_packages(self):
        script = '''import sys,json,datetime
sys.path.insert(0,sys.argv[1]);import exhibition_contract as e
d=json.load(sys.stdin);r=e.build_post_exhibition_bundle(d['p'],d['b'],d['r'],datetime.datetime.fromisoformat(d['now']))
assert not any(k.startswith(('race_ai','api.','cv2','sqlite3')) for k in sys.modules)
print(json.dumps({'phase':r['phase'],'triples':len(r['model']['triples'])}))'''
        run = subprocess.run([sys.executable,'-I','-S','-c',script,str(ROOT/'web')],
            input=json.dumps(dict(p=self.baseline,b=self.bundle,r=self.race,now=NOW.isoformat())),
            text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), dict(phase='post_exhibition', triples=120))


if __name__ == '__main__': unittest.main()
