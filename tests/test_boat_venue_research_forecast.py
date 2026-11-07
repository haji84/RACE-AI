"""Synthetic original P1 -> private venue-enriched paired research forecasts."""
from copy import deepcopy
from datetime import timedelta, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import MODEL_IDS, WEIGHTS, predict_pair
from race_ai.boat_venue_feature_adapter import RIGHTS
from race_ai.boat_venue_learning import fit_venue_rows, read_candidate, seal_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.boat_venue_research import issue_owner_research_decision
from race_ai.observed_weight_learning import seal
from tests import test_boat_venue_feature_adapter as grid_tests
from tests import test_boat_venue_research as research_tests
from tests import test_observed_p1_connection as p1_tests

NOW = research_tests.NOW


class PrivateVenueForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grid_fixture = grid_tests.VenueFeatureTests()
        cls.grid_fixture.setUp()
        cls.addClassCleanup(cls.grid_fixture.doCleanups)
        cls.grid, cls.pointer, _ = cls.grid_fixture.dataset(partial=True)
        rows, observations = research_tests.personal_data(8)
        for row in rows:
            snapshot = row['learning_snapshot']
            for source in snapshot['sources']:
                if source['source_id'].startswith('official-venue-grid-'):
                    source.update(source_id='official-venue-grid-'+cls.pointer['dataset_sha256'][:16],
                                  source_sha256=cls.pointer['dataset_sha256'],
                                  source_url=cls.venue_url())
            for participant in snapshot['participants']:
                for name in ('course_mean_finish', 'course_mean_st'):
                    if name in participant['features']:
                        participant['features'][name]['source_id'] = 'official-venue-grid-'+cls.pointer['dataset_sha256'][:16]
            suite = predict_pair(snapshot, allow_source=lambda *_: True)
            model = suite['models'][row['model_id']]
            row.update(learning_snapshot_sha256=digest(snapshot), model_sha256=model['prediction_sha256'],
                       top8=model['ordered_top8'], ranked=[r['combination'] for r in model['candidates']])
        record = issue_owner_research_decision(
            source_pointer=research_tests.SOURCE, state_content_sha256=research_tests.CONTENT,
            dataset_pointer=cls.pointer, source_refs=research_tests.refs(rows, observations),
            now=NOW, expires_at=NOW+timedelta(days=30))
        payload = fit_venue_rows(rows, observations, dataset_pointer=cls.pointer, now=NOW,
                                source_pointer=research_tests.SOURCE,
                                state_content_sha256=research_tests.CONTENT, owner_research_record=record)
        candidate = cls.grid_fixture.root/'fitted'; seal_candidate(payload, candidate)
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as archive:
            for name in ('learning.enc', 'learning.json', 'summary.json'):
                archive.writestr(name, (candidate/name).read_bytes())
        raw = body.getvalue()
        receipt = dict(id=700, name='boat-venue-learning-99-1', expired=False,
                       digest='sha256:'+hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw),
                       created_at=(NOW+timedelta(seconds=2)).isoformat(),
                       expires_at=(NOW+timedelta(days=7)).isoformat(),
                       workflow_run=dict(id=99, repository_id=1416489937, head_repository_id=1416489937))
        cls.context = context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                     _fetch=lambda _: deepcopy(receipt))

    @classmethod
    def venue_url(cls):
        return ('https://raw.githubusercontent.com/haji84/RACE-AI/'+cls.pointer['source_commit']+
                '/'+cls.pointer['dataset_path'])

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_research_forecast')
        except ModuleNotFoundError:
            self.fail('private venue-enriched P1 orchestration is missing')

    def bundle(self, *, with_history=False):
        base, extra, provenance = p1_tests.inputs()
        base.update(race_id='20300401-17-01', cutoff_at=(NOW+timedelta(minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat(),
                    captured_at=(NOW+timedelta(minutes=9)).isoformat())
        extra.update(race_id=base['race_id'], observed_at=base['captured_at'])
        provenance.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(),
                          preview_captured_at=base['captured_at'])
        for name in ('program_url', 'preview_url'):
            provenance[name] = provenance[name].replace('jcd=01', 'jcd=17')
        history = {}
        if with_history:
            from tests.test_observed_result_history import archived, observation
            from race_ai.observed_result_history import context_from_result_archive
            history['history_context'] = context_from_result_archive(
                *archived([observation()]), verified_at='2030-03-31T04:01:00Z')
        return p1_tests.bridge.build_bundle(base, extra, (NOW+timedelta(minutes=10)).isoformat(),
                                            **provenance, owner_reviewed=True, **history)

    def allowed(self, bundle):
        pairs = {(s['source_url'], s['source_rights_ref']) for s in bundle['snapshot']['sources']}
        pairs.add((self.venue_url(), RIGHTS))
        return lambda url, rights, purpose: (url, rights) in pairs and purpose == 'analysis'

    def run_private(self, api, bundle, output, **overrides):
        arguments = dict(now=NOW+timedelta(minutes=11),
                         dataset_verified_at=(NOW+timedelta(minutes=5)).isoformat(),
                         allow_source=self.allowed(bundle))
        arguments.update(overrides)
        return api.forecast_private_venue_p1(bundle, self.context, self.grid, self.pointer,
                                             output, **arguments)

    def test_actual_owner_fit_and_grid_produce_same_input_encrypted_pair(self):
        api = self.api(); bundle = self.bundle(); before = deepcopy((bundle, self.context, WEIGHTS))
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary:
            root = Path(temporary)/'forecast'
            status = self.run_private(api, bundle, root)
            payload = read_candidate(root); snapshot = payload['snapshot']
            self.assertTrue(api.verify_private_forecast(payload))
            self.assertEqual(snapshot['as_of'], (NOW+timedelta(minutes=11)).isoformat())
            self.assertEqual(snapshot['stage'], 'P1')
            self.assertEqual(payload['original_bundle_sha256'], bundle['bundle_sha256'])
            self.assertEqual(payload['training'], self.context['training'])
            self.assertEqual(len(payload['venue_evidence']), 6)
            self.assertTrue(all('course_mean_st' in p['features'] for p in snapshot['participants']))
            self.assertEqual(len(snapshot['sources']), 3)
            self.assertEqual(digest(payload['baseline_suite']), digest(predict_pair(snapshot, allow_source=self.allowed(bundle))))
            self.assertEqual(set(payload['baseline_suite']['models']), set(MODEL_IDS))
            self.assertEqual(len(payload['shadows']), 2)
            for shadow in payload['shadows']:
                self.assertEqual(shadow['input_sha256'], digest(snapshot))
                self.assertEqual(shadow['baseline_model_sha256'],
                                 payload['baseline_suite']['models'][shadow['model_id']]['prediction_sha256'])
                self.assertEqual(len(shadow['ordered_top8']), 8)
                self.assertEqual(len(shadow['candidates']), 120)
            self.assertEqual(status['learned_shadow_count'], 2)
            self.assertEqual(status['baseline_model_count'], 2)
            self.assertFalse(status['source_coverage_complete'])
            for name in ('provider_permission_confirmed', 'production_promoted', 'actual_purchases',
                         'independent_pre_cutoff_receipt_verified', 'baseline_coefficients_changed', 'plaintext_published'):
                self.assertIs(status[name], False)
            self.assertTrue(status['encrypted_readback_verified'])
            public = (root/'summary.json').read_bytes()
            for secret in (b'weights', b'ordered_top8', b'"participants":', b'"4001"', b'source_url'):
                self.assertNotIn(secret, public)
            self.assertEqual({p.name for p in root.iterdir()}, {'learning.enc', 'learning.json', 'summary.json'})
        self.assertEqual((bundle, self.context, WEIGHTS), before)

    def test_three_source_original_keeps_recent_history_and_original_immutable(self):
        api = self.api(); bundle = self.bundle(with_history=True); before = deepcopy(bundle)
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary:
            self.run_private(api, bundle, Path(temporary)/'forecast')
            payload = read_candidate(Path(temporary)/'forecast')
            self.assertEqual(len(payload['snapshot']['sources']), 4)
            for original, enriched in zip(bundle['snapshot']['participants'], payload['snapshot']['participants']):
                for name in ('recent_mean_finish', 'recent_mean_st'):
                    self.assertEqual(original['features'].get(name), enriched['features'].get(name))
            self.assertEqual(payload['original_bundle_sha256'], before['bundle_sha256'])
        self.assertEqual(bundle, before)

    def test_bad_original_hash_provenance_and_extra_source_never_forecast(self):
        api = self.api(); bundle = self.bundle(); variants = []
        broken = deepcopy(bundle); broken['snapshot']['participants'][0]['features']['exhibition_time_seconds']['value'] = 7.
        variants.append(broken)
        broken = deepcopy(bundle); broken['http_provenance'][0]['request_url'] = broken['http_provenance'][0]['request_url'].replace('jcd=17', 'jcd=16')
        seal(broken, 'bundle_sha256'); variants.append(broken)
        broken = deepcopy(bundle); broken['snapshot']['sources'].append(deepcopy(broken['snapshot']['sources'][0]))
        seal(broken, 'bundle_sha256'); variants.append(broken)
        broken = deepcopy(bundle); broken.pop('base_source_sha256')
        seal(broken, 'bundle_sha256'); variants.append(broken)
        broken = deepcopy(bundle); broken['http_provenance'][0]['extra'] = 'foreign'
        seal(broken, 'bundle_sha256'); variants.append(broken)
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary, \
             patch.object(api, 'make_shadows', side_effect=AssertionError('invalid original must not forecast')):
            for index, original in enumerate(variants):
                root = Path(temporary)/str(index)
                with self.subTest(case=index), self.assertRaises(ValueError):
                    self.run_private(api, original, root)
                self.assertFalse(root.exists())

    def test_wrong_dataset_or_non_owner_candidate_never_forecast(self):
        api = self.api(); bundle = self.bundle()
        variants = []
        for field, value in (('venue_dataset_sha256', 'f'*64), ('training_basis', 'PROVIDER_REVIEW'),
                             ('provider_permission_confirmed', True)):
            context = deepcopy(self.context); context['training'][field] = value
            seal(context['training'], 'training_sha256'); variants.append(context)
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary, \
             patch.object(api, 'make_shadows', side_effect=AssertionError('invalid candidate must not forecast')):
            for index, context in enumerate(variants):
                root = Path(temporary)/str(index)
                with self.subTest(case=index), self.assertRaises(ValueError):
                    api.forecast_private_venue_p1(bundle, context, self.grid, self.pointer, root,
                        now=NOW+timedelta(minutes=11), dataset_verified_at=NOW, allow_source=self.allowed(bundle))
                self.assertFalse(root.exists())

    def test_late_future_verified_time_and_missing_key_never_forecast(self):
        api = self.api(); bundle = self.bundle()
        cases = [dict(now=NOW+timedelta(minutes=30)-timedelta(seconds=210)),
                 dict(now=NOW+timedelta(minutes=9)),
                 dict(dataset_verified_at=NOW+timedelta(minutes=12)),
                 dict(now=(NOW+timedelta(minutes=11)).replace(tzinfo=None))]
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary, \
             patch.object(api, 'make_shadows', side_effect=AssertionError('invalid clock must not forecast')):
            for index, changes in enumerate(cases):
                root = Path(temporary)/str(index)
                with self.subTest(case=index), self.assertRaises(ValueError):
                    self.run_private(api, bundle, root, **changes)
                self.assertFalse(root.exists())
            root = Path(temporary)/'missing-key'
            with patch.dict(os.environ, RACE_AI_STATE_KEY=''), self.assertRaises(ValueError):
                self.run_private(api, bundle, root)
            self.assertFalse(root.exists())

    def test_denied_analysis_never_forecasts_or_publishes(self):
        api = self.api(); bundle = self.bundle()
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary, \
             patch.object(api, 'make_shadows', side_effect=AssertionError('analysis admission required')):
            root = Path(temporary)/'denied'
            with self.assertRaises(ValueError):
                self.run_private(api, bundle, root, allow_source=lambda *_: False)
            self.assertFalse(root.exists())

    def test_sealing_crossing_cutoff_retains_only_unwitnessed_ciphertext(self):
        api = self.api(); bundle = self.bundle()
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary:
            root = Path(temporary)/'late'
            with patch.object(api.time, 'monotonic', side_effect=[100., 1300.]), self.assertRaises(ValueError):
                self.run_private(api, bundle, root)
            payload = read_candidate(root)
            self.assertFalse(payload['summary']['independent_pre_cutoff_receipt_verified'])
            self.assertFalse(json.loads((root/'summary.json').read_bytes())['plaintext_published'])

    def test_pure_replay_rejects_original_input_baseline_shadow_and_metadata_changes(self):
        api = self.api(); bundle = self.bundle()
        with tempfile.TemporaryDirectory(prefix='venue-private-forecast-test-') as temporary:
            root = Path(temporary)/'forecast'; self.run_private(api, bundle, root)
            payload = read_candidate(root)
        changes = []
        for name, value in (('schema', 'foreign'), ('generated_at', NOW.isoformat()),
                            ('original_bundle_sha256', 'f'*64), ('venue_evidence', {})):
            item = deepcopy(payload); item[name] = value; changes.append(item)
        item = deepcopy(payload); item['summary']['provider_permission_confirmed'] = True; changes.append(item)
        item = deepcopy(payload); item['summary']['provider_permission_confirmed'] = 0; changes.append(item)
        item = deepcopy(payload); item['snapshot']['participants'][0]['features']['course_mean_st']['value'] = .99; changes.append(item)
        item = deepcopy(payload); item['baseline_suite']['models'][MODEL_IDS[0]]['ordered_top8'][0] = [6,5,4]; changes.append(item)
        item = deepcopy(payload); item['shadows'][0]['ordered_top8'][0] = [6,5,4]; changes.append(item)
        item = deepcopy(payload); item['original_bundle']['http_provenance'][0]['source_sha256'] = 'f'*64; changes.append(item)
        item = deepcopy(payload); item['training_receipt']['created_at'] = payload['generated_at']; changes.append(item)
        item = deepcopy(payload); item.pop('dataset_pointer'); changes.append(item)
        for index, value in enumerate(changes):
            with self.subTest(case=index), self.assertRaises(ValueError):
                api.verify_private_forecast(value)


if __name__ == '__main__':
    unittest.main()
