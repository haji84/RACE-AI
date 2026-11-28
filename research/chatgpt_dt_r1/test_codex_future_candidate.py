"""Synthetic pre-cutoff Codex inference through the frozen native engine."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from research.chatgpt_dt_r1 import codex_future_candidate as future
from research.chatgpt_dt_r1.policy import clock, digest, validate_forecast
from race_ai import keirin_learned_order as native
from race_ai import keirin_official_learned_replay as replay
from tests.test_keirin_learned_official_inputs import _original


ROOT = Path(__file__).resolve().parents[2]


class SyntheticBooster:
    def predict(self, values, *, raw_score, num_threads):
        if raw_score is not True or num_threads < 1:
            raise AssertionError('Native inference did not request joint logits')
        return np.arange(len(values), dtype=float) * .001


class CodexFutureCandidateTests(TestCase):
    def setUp(self):
        self.payload, self.original = _original()
        self.day = self.original['day_jst']
        self.cutoff = self.original['snapshot']['published_cutoff_at']
        self.proof = self.original['origin_receipts']['baseline_origin']
        self.at = '2030-01-15T02:02:00+00:00'
        self.proof.update(producer_run_id=11, readback_run_id=11, producer_job_id=12,
            readback_job_id=13, producer_artifact_id=14, readback_artifact_id=15,
            producer_commit='a' * 40, readback_commit='a' * 40,
            producer_archive_sha256='b' * 64, readback_archive_sha256='c' * 64,
            minimum_margin_seconds=65)
        self.rehash_proof()
        self.original.update(producer_run_id='11', producer_commit='a' * 40)
        self.payload.update(producer_run_id='11', producer_commit='a' * 40)
        self.meta = dict(race_id=self.original['race_id'], cutoff_at=self.cutoff,
            observed_at=self.proof['latest_server_evidence_at'], producer_run_id='11',
            producer_commit='a' * 40, baseline_cipher_sha256='a' * 64)
        self.manifest = dict(model_id=native.MODEL_ID, tree_sha256=future.model_identity()['model_sha256'],
            sealed_model_sha256=replay.FROZEN_MODEL_SHA256, temperature=1.,
            calibration_window=['20261001', '20261029'], prior_evaluation_window=['20261101', '20261122'])

    def rehash_proof(self):
        self.proof['evidence_sha256'] = digest({k: v for k, v in self.proof.items() if k != 'evidence_sha256'})

    def load(self, manifest=None):
        with patch.object(replay, 'load_candidate', return_value=(SyntheticBooster(), manifest or self.manifest)):
            return future.load_frozen(ROOT, b'synthetic fixture', self.day)

    def project(self, **overrides):
        options = dict(day=self.day, cutoff_at=self.cutoff, input_at=self.at, original_meta=self.meta)
        return future.project(self.payload, self.original, **dict(options, **overrides))

    def test_pinned_restore_and_full_market_law(self):
        candidate = self.load()
        row = self.project(input_sha256='9' * 64)
        self.assertEqual(row['input_sha256'], '9' * 64)
        self.assertEqual(row['source_attestation_sha256'], self.proof['evidence_sha256'])
        forecast = future.forecast(candidate, row, generated_or_started_at=self.at)
        self.assertEqual(forecast['model_id'], native.MODEL_ID)
        self.assertEqual(forecast['model_sha256'], self.manifest['tree_sha256'])
        self.assertEqual(forecast['feature_input_sha256'], row['feature_input_sha256'])
        self.assertNotIn('codex_features', forecast)
        checked = validate_forecast(forecast)
        self.assertEqual(len(checked['trifectas']), 210)
        self.assertEqual(len(checked['exactas']), 42)
        self.assertTrue(all(x['probability'] > 0 for x in checked['trifectas']))
        for pair in checked['exactas']:
            self.assertAlmostEqual(pair['probability'], sum(t['probability'] for t in checked['trifectas']
                                  if t['cars'][:2] == pair['cars']))

    def test_target_labels_and_conditioned_or_rival_forecasts_are_inert(self):
        before = self.project()
        for row in (self.payload, self.original):
            row.update(official_result={'winner': 7}, top3=[7, 6, 5], result_rows=[{'car': 7}],
                       conditioned={'private_rival_prediction': []}, odds={'private_odds': 99})
        self.assertEqual(self.project(), before)

    def test_unverified_origin_model_or_clock_stops(self):
        candidate = self.load()
        row = self.project()
        with self.assertRaises(ValueError):
            self.load(dict(self.manifest, tree_sha256='f' * 64))
        with self.assertRaises(ValueError):
            self.project(input_at=None)
        with self.assertRaises(ValueError):
            self.project(input_at=self.cutoff)
        with self.assertRaises(ValueError):
            self.project(input_at=(clock(self.proof['latest_server_evidence_at']) - timedelta(seconds=1)).isoformat())
        with self.assertRaises(ValueError):
            future.forecast(candidate, row, generated_or_started_at=self.cutoff)
        with self.assertRaises(ValueError):
            future.forecast(candidate, row, generated_or_started_at='2030-01-15T02:01:59+00:00')
        changed = deepcopy(row)
        changed['codex_features']['riders'][0]['points'] += 1
        with self.assertRaises(ValueError):
            future.forecast(candidate, changed, generated_or_started_at=self.at)
        self.proof['readback_job_id'] = self.proof['producer_job_id']
        self.rehash_proof()
        with self.assertRaises(ValueError):
            self.project()

    def test_candidate_confirmation_cannot_be_postdated(self):
        row = self.project()
        candidate = self.load()
        with self.assertRaisesRegex(ValueError, 'CODEX_FUTURE_MODEL_NOT_YET_CONFIRMED'):
            future.forecast(replace(candidate, confirmed_at='2030-01-15T02:02:01+00:00'), row,
                            generated_or_started_at=self.at)

    def test_exact_t15_margin_accepts_and_a_late_fraction_does_not(self):
        limit = (clock(self.cutoff) - timedelta(minutes=15)).isoformat()
        candidate = self.load()
        row = self.project(input_at=limit)
        self.assertEqual(future.forecast(candidate, row, generated_or_started_at=limit)['status'], 'READY')
        late = (clock(limit) + timedelta(microseconds=1)).isoformat()
        with self.assertRaises(ValueError):
            self.project(input_at=late)
        with self.assertRaises(ValueError):
            future.forecast(candidate, row, generated_or_started_at=late)

    def test_modified_restore_receipt_stops_before_owner_loader(self):
        with TemporaryDirectory() as work:
            repo = Path(work)
            for name in (Path(replay.FROZEN_MODEL), future.VERIFICATION_PATH, future.RESTORE_RECEIPT):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            path = repo / future.RESTORE_RECEIPT
            path.write_bytes(path.read_bytes() + b' ')
            with patch.object(replay, 'load_candidate') as loader:
                with self.assertRaisesRegex(ValueError, 'CODEX_FUTURE_MODEL_EVIDENCE_SHA'):
                    future.load_frozen(repo, b'synthetic fixture', self.day)
            loader.assert_not_called()
