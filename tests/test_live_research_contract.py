"""Server-generated research contract tests use synthetic program facts only."""
import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


NOW = datetime(2026, 10, 15, 7, 33, tzinfo=timezone(timedelta(hours=9)))
CAPTURE = '2026-10-15T07:00:00+09:00'
CLOSE = '2026-10-15T08:35:00+09:00'
B_URL = 'https://www1.mbrace.or.jp/od2/B/202610/b261015.lzh'
ROOT = Path(__file__).resolve().parents[1]


def fixture():
    race = dict(race_id='20261015-01-01', closed_at=CLOSE,
        program_source_url=B_URL, program_source_sha256='a' * 64, program_observed_at=CAPTURE,
        boats=[dict(lane=lane, racer_registration_id=str(4000 + lane), name='試験選手' + str(lane),
                    national_win_rate=float(7 - lane)) for lane in range(1, 7)])
    feed = dict(date_jst='2026-10-15', redistribution_authorized=True,
        publication_review='user-confirmation-2026-10-15-official-facts',
        sources=[dict(source_url=B_URL, source_sha256='a' * 64, first_observed_at=CAPTURE)],
        venues=[dict(venue='01', races=[race])])
    return feed, race


class LiveResearchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.c = importlib.import_module('web.research_contract')
        except ModuleNotFoundError:
            cls.c = None

    def setUp(self):
        self.assertIsNotNone(self.c, 'standalone server research contract must exist')

    def build(self, feed=None, race=None, now=NOW):
        if feed is None:
            feed, race = fixture()
        return self.c.build_research_bundle(feed, race, now)

    def test_build_freezes_approved_source_identity_and_two_untrained_models(self):
        bundle = self.build()
        self.assertEqual(bundle['schema_version'], 1)
        self.assertEqual(bundle['program_sha256'], 'a' * 64)
        self.assertEqual(bundle['program_source'], dict(source_url=B_URL, source_sha256='a' * 64,
                                                       captured_at='2026-10-14T22:00:00.000000+00:00'))
        self.assertEqual([m['model_id'] for m in bundle['models']], ['official-program-uniform-pl', 'official-program-rating-pl'])
        self.assertTrue(bundle['research_only'])
        self.assertEqual(bundle['validation_status'], 'UNVALIDATED')
        self.assertEqual(bundle['purchase_decision'], 'skip')
        self.assertEqual(bundle['purchase_recommendations'], [])
        self.assertEqual(bundle, self.build())
        for model in bundle['models']:
            self.assertEqual(model['model_version'], '1')
            self.assertEqual(len(model['triples']), 120)
            self.assertEqual(len(model['marginals']), 6)
            self.assertAlmostEqual(sum(row['probability'] for row in model['triples']), 1, places=12)
            self.assertEqual(model['purchase_recommendations'], [])
        rating = bundle['models'][1]
        self.assertEqual([b['strength'] for b in rating['inputs']['boats']], [6., 5., 4., 3., 2., 1.])
        self.assertIn('points', rating['selection_reason'])
        self.assertIn('not a first-place probability', rating['selection_reason'])

    def test_pure_functions_are_shared_with_existing_prediction_module(self):
        from race_ai import prediction
        self.assertIs(prediction.PredictionError, self.c.PredictionError)
        self.assertIs(prediction.plackett_luce, self.c.plackett_luce)
        self.assertIs(prediction.build_prediction, self.c.build_prediction)

    def test_missing_rating_omits_rating_model_without_imputing_points(self):
        feed, race = fixture()
        race['boats'][0]['national_win_rate'] = None
        bundle = self.build(feed, race)
        self.assertEqual([m['model_id'] for m in bundle['models']], ['official-program-uniform-pl'])
        self.assertIsNone(bundle['program_boats'][0]['national_win_rate'])
        self.assertEqual(self.c.validate_research_bundle(bundle, race, NOW), bundle)

    def test_zero_rating_uses_explicit_positive_floor(self):
        feed, race = fixture()
        race['boats'][0]['national_win_rate'] = 0
        self.assertEqual(self.build(feed, race)['models'][1]['inputs']['boats'][0]['strength'], .01)

    def test_invalid_nonfinite_bool_and_out_of_range_points_rejected(self):
        for value in (True, False, float('nan'), float('inf'), -1, 10.01, '6.00', {}, []):
            feed, race = fixture()
            race['boats'][0]['national_win_rate'] = value
            with self.subTest(rating=repr(value)), self.assertRaises(self.c.PredictionError):
                self.build(feed, race)

    def test_program_source_must_match_same_day_approved_b_archive_and_hash(self):
        for changes in (
            dict(program_source_url='https://attacker.example/B'),
            dict(program_source_url=B_URL + '?x=1'),
            dict(program_source_url=B_URL.replace('b261015', 'b261014')),
            dict(program_source_sha256='b' * 64),
            dict(program_source_sha256='not-a-sha'),
            dict(program_observed_at='2026-10-15T07:34:00+09:00'),
        ):
            feed, race = fixture()
            race.update(changes)
            with self.subTest(changes=changes), self.assertRaises(self.c.PredictionError):
                self.build(feed, race)
        for changes in (dict(redistribution_authorized=False), dict(date_jst='2026-10-14')):
            feed, race = fixture()
            feed.update(changes)
            with self.subTest(changes=changes), self.assertRaises(self.c.PredictionError):
                self.build(feed, race)

    def test_source_capture_cannot_be_relabelled_into_another_day_or_future(self):
        for stamp in ('2026-10-14T23:59:59+09:00', '2026-10-15T07:33:00.001+09:00', '2026-10-15T07:00:00'):
            feed, race = fixture()
            race['program_observed_at'] = stamp
            feed['sources'][0]['first_observed_at'] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(self.c.PredictionError):
                self.build(feed, race)

    def test_current_race_identities_and_cutoff_are_required(self):
        for mutate in (
            lambda r: r['boats'][0].update(lane=True),
            lambda r: r['boats'][0].update(racer_registration_id='bad'),
            lambda r: r['boats'][0].update(racer_registration_id=r['boats'][1]['racer_registration_id']),
            lambda r: r['boats'].pop(),
            lambda r: r.update(race_id='20261014-01-01'),
            lambda r: r.update(closed_at=CAPTURE),
        ):
            feed, race = fixture()
            mutate(race)
            with self.subTest(mutation=repr(mutate)), self.assertRaises(self.c.PredictionError):
                self.build(feed, race)
        with self.assertRaises(self.c.PredictionError):
            self.build(now=NOW.replace(tzinfo=None))

    def test_replay_validates_after_close_but_cannot_create_after_close(self):
        bundle = self.build()
        _, race = fixture()
        later = NOW + timedelta(hours=2)
        self.assertEqual(self.c.validate_research_bundle(bundle, race, later), bundle)
        with self.assertRaises(self.c.PredictionError):
            self.build(now=later)

    def test_replay_accepts_later_mutable_rating_but_rejects_new_roster_or_close(self):
        bundle = self.build()
        _, race = fixture()
        race['boats'][0]['national_win_rate'] = 9.99
        self.assertEqual(self.c.validate_research_bundle(bundle, race, NOW), bundle)
        for changes in (dict(closed_at='2026-10-15T08:36:00+09:00'), dict(race_id='20261015-01-02')):
            changed = copy.deepcopy(race)
            changed.update(changes)
            with self.subTest(changes=changes), self.assertRaises(self.c.PredictionError):
                self.c.validate_research_bundle(bundle, changed, NOW)
        changed = copy.deepcopy(race)
        changed['boats'][0]['racer_registration_id'] = '4999'
        with self.assertRaises(self.c.PredictionError):
            self.c.validate_research_bundle(bundle, changed, NOW)

    def test_rehashed_score_or_metadata_tampering_is_rejected_by_deterministic_replay(self):
        _, race = fixture()
        for mutate in (
            lambda b: b['models'][1]['triples'][0].update(probability=.9),
            lambda b: b['models'][0].update(validation_status='VALIDATED'),
            lambda b: b['models'][1]['inputs']['boats'][0].update(strength=9),
            lambda b: b.update(schema_version=True),
            lambda b: b.update(purchase_recommendations=[dict(stake_yen=100)]),
            lambda b: b.update(current_actual_st=.1),
            lambda b: b.update(generated_at='2026-10-15T00:00:00Z'),
        ):
            changed = self.build()
            mutate(changed)
            changed['snapshot_id'] = self.c._sha({k: v for k, v in changed.items() if k != 'snapshot_id'})
            with self.subTest(mutation=repr(mutate)), self.assertRaises(self.c.PredictionError):
                self.c.validate_research_bundle(changed, race, NOW)

    def test_web_root_module_runs_without_repository_or_site_packages(self):
        feed, race = fixture()
        script = """import json,sys,datetime
sys.path.insert(0,sys.argv[1]);import research_contract as c
data=json.load(sys.stdin);now=datetime.datetime.fromisoformat(data['now'])
b=c.build_research_bundle(data['feed'],data['race'],now)
assert not any(k.startswith('race_ai') for k in sys.modules)
print(json.dumps({'models':len(b['models']),'triples':len(b['models'][0]['triples'])}))"""
        execution = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(ROOT / 'web')],
            input=json.dumps(dict(feed=feed, race=race, now=NOW.isoformat())), text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        self.assertEqual(json.loads(execution.stdout), dict(models=2, triples=120))


if __name__ == '__main__':
    unittest.main()
