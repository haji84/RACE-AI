"""Controlled optional-hook fixtures; no real video or accuracy evidence."""
from copy import deepcopy
from datetime import timedelta, timezone
import hashlib
import io
import json
import unittest
import zipfile

from race_ai.actions_contract import digest
from race_ai import frozen_day_cycle as frozen
from race_ai import observed_weight_learning as existing
from race_ai import boat_video_learning as video
from race_ai.boat_observed_pairwise_models import MODEL_IDS
from tests.test_boat_video_learning import controlled_inputs, reseal_context
from tests import test_observed_weight_learning as observed_fixtures
from tests.test_observed_p1_connection import inputs, archive, bridge

dataset, NOW = observed_fixtures.dataset, observed_fixtures.NOW


def target_bundle():
    base, extra, provenance = inputs()
    rid = '20300401-24-12'
    base['race_id'] = extra['race_id'] = rid
    as_of = (NOW+timedelta(minutes=10)).isoformat()
    before = (NOW+timedelta(minutes=9)).isoformat()
    base.update(cutoff_at=(NOW+timedelta(minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat(),
                captured_at=before)
    extra['observed_at'] = before
    provenance.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(), preview_captured_at=before)
    for key in ('program_url', 'preview_url'):
        provenance[key] = provenance[key].replace('jcd=01', 'jcd=24').replace('rno=1', 'rno=12')
    return base, extra, bridge.build_bundle(base, extra, as_of, **provenance, owner_reviewed=True)


def target_video(template, snapshot):
    envelope = deepcopy(template)
    context = envelope['video_context']
    instant = existing.ts(snapshot['as_of'])
    context.update(race_id='20300401-24-12', as_of=(instant-timedelta(minutes=1)).isoformat(), cutoff_at=snapshot['sales_cutoff_at'],
        source_captured_at=(instant-timedelta(minutes=5)).isoformat(),
        analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
        analysis_completed_at=(instant-timedelta(minutes=3)).isoformat(),
        evidence_created_at=(instant-timedelta(minutes=2)).isoformat())
    roster = {p['lane']: p['registration_no'] for p in snapshot['participants']}
    for participant in context['participants']:
        participant['registration_number'] = roster[participant['lane']]
    reseal_context(context)
    envelope['receipt']['created_at'] = (instant-timedelta(seconds=30)).isoformat()
    proof = dict(context_sha256=context['context_sha256'], id=envelope['receipt']['id'],
        digest=envelope['receipt']['digest'], created_at=envelope['receipt']['created_at'])
    def verifier(receipt, context_sha256, as_of):
        if receipt != envelope['receipt'] or context_sha256 != proof['context_sha256'] or as_of != snapshot['as_of']:
            raise ValueError('controlled independent reader rejected binding')
        return deepcopy(proof)
    return envelope, verifier


def saved_training(training, receipt):
    report = {'automatic_learning': {'training_sha256': training['training_sha256']}}
    existing.seal(report, 'report_sha256')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        bundle.writestr('trained_observed_models.json', json.dumps(training))
        bundle.writestr('status.json', json.dumps(report))
    raw = buffer.getvalue()
    metadata = deepcopy(receipt)
    metadata['digest'] = 'sha256:'+hashlib.sha256(raw).hexdigest()
    # This helper represents a saved result artifact, including the native
    # archive identity now shared by clear and encrypted archive readers.
    metadata['name'] = 'race-existing-cycle-99'
    metadata['workflow_run']['id'] = 99
    return raw, metadata


class ExistingOptionalVideoHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.observations, cls.contexts, fit_verifier = controlled_inputs()
        cls.fit_verifier = staticmethod(fit_verifier)
        cls.training = video.fit_with_video(cls.rows, cls.observations, cls.contexts,
            now=NOW, receipt_verifier=cls.fit_verifier)
        cls.frozen = dict(training=cls.training, receipt=dict(id=700,
            created_at=(NOW+timedelta(seconds=2)).isoformat(), digest='sha256:'+'a'*64,
            expired=False, workflow_run={'head_repository_id': 1416489937}))

    def test_default_v1_bytes_and_eight_feature_equations_are_unchanged(self):
        rows, observations = dataset(12)
        training = existing.fit_from_verified(rows, observations, now=NOW)
        snapshot, suite = observed_fixtures.LearningTests().future()
        context = dict(training=training, receipt=dict(id=700, created_at='2030-04-01T08:00:02+00:00',
            name='race-existing-cycle-99', digest='sha256:'+'a'*64, expired=False,
            workflow_run={'id': 99, 'head_repository_id': 1416489937}))
        self.assertEqual(suite['suite_sha256'], 'f0d2e1f7f234b02c7b6ccee3c31ae84faeed0ff7755f38775ff1fe696e334a94')
        self.assertEqual(training['training_sha256'], '116f92b4547293d54a9ecd0b5de7ed17ab2f0cd49a14cb267040f6708b34f1bc')
        self.assertEqual(digest(existing.make_shadows(snapshot, suite, context)),
                         'dde5d8908479e97d84e4140d5450e8145b5e01e54cb8778c8d82b6d024270db0')
        self.assertEqual(digest(existing.make_shadows(snapshot, suite, context,
            video_context={'untrusted': True}, video_receipt_verifier=lambda *_: None)),
                         'dde5d8908479e97d84e4140d5450e8145b5e01e54cb8778c8d82b6d024270db0')
        self.assertTrue(all(len(vector) == 8 for vector in existing.vectors(snapshot).values()))
        self.assertEqual(existing.fit_from_verified(rows, observations, now=NOW, video_contexts=None), training)

    def test_existing_training_entrypoint_selects_video_only_when_requested(self):
        actual = existing.fit_from_verified(self.rows, self.observations, now=NOW,
            video_contexts=self.contexts, video_receipt_verifier=self.fit_verifier)
        self.assertEqual(actual, self.training)
        self.assertEqual(actual['schema'], video.SCHEMA_TRAIN)
        self.assertEqual(set(actual['models']), set(MODEL_IDS))
        self.assertIsNone(existing.verify_training(actual))
        self.assertTrue(video.replay_video_training(actual, self.rows, self.observations,
            self.contexts, now=NOW, receipt_verifier=self.fit_verifier))
        unverified = existing.fit_from_verified(self.rows, self.observations, now=NOW,
            video_contexts=self.contexts)
        self.assertEqual(unverified['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(unverified['video_admitted_races'], 0)

    def test_existing_inference_entrypoint_keeps_two_families_and_new_version(self):
        _, _, bundle = target_bundle()
        envelope, verifier = target_video(next(iter(self.contexts.values())), bundle['snapshot'])
        before = deepcopy((bundle, self.frozen, envelope))
        shadows = existing.make_shadows(bundle['snapshot'], bundle['suite'], self.frozen,
            video_context=envelope, video_receipt_verifier=verifier)
        self.assertEqual(len(shadows), 2)
        self.assertEqual({record['model_id'] for record in shadows}, set(MODEL_IDS))
        self.assertTrue(all(record['model_version'] == '0.3.0-VIDEO-EXPERIMENTAL' and
            record['variant'] == 'LEARNED_VIDEO_EXPERIMENTAL' and record['production_eligible'] is False
            for record in shadows))
        self.assertEqual((bundle, self.frozen, envelope), before)
        self.assertEqual(existing.make_shadows(bundle['snapshot'], bundle['suite'], self.frozen,
            video_context=envelope), [])

    def test_archived_video_training_recovers_only_verified_experimental_context(self):
        raw, receipt = saved_training(self.training, self.frozen['receipt'])
        context = existing.context_from_result_archive(raw, receipt)
        self.assertIsNotNone(context)
        self.assertEqual(context, dict(training=self.training, receipt=receipt))
        with self.assertRaises(ValueError):
            existing.context_from_result_archive(raw+b'changed', receipt)
        for schema, state in ((video.SCHEMA_TRAIN, 'UNKNOWN'),
                              (video.SCHEMA_TRAIN, 'FITTED_SHADOW_ONLY'),
                              ('UNRECOGNIZED_TRAINING_SCHEMA', 'FITTED_VIDEO_EXPERIMENTAL')):
            bad = deepcopy(self.training)
            bad.update(schema=schema, state=state)
            existing.seal(bad, 'training_sha256')
            bad_raw, bad_receipt = saved_training(bad, self.frozen['receipt'])
            with self.subTest(schema=schema, state=state), self.assertRaises(ValueError):
                existing.context_from_result_archive(bad_raw, bad_receipt)
        old = existing.fit_from_verified(*dataset(3), now=NOW)
        old['state'] = 'FITTED_VIDEO_EXPERIMENTAL'
        existing.seal(old, 'training_sha256')
        self.assertIsNone(existing.context_from_result_archive(*saved_training(old, self.frozen['receipt'])))

    def saved_video_archive(self):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        base, extra, bundle = target_bundle()
        envelope, verifier = target_video(next(iter(self.contexts.values())), bundle['snapshot'])
        context = existing.context_from_result_archive(*saved_training(self.training, self.frozen['receipt']))
        shadows = video.make_video_shadows(bundle['snapshot'], bundle['suite'], context,
            envelope, receipt_verifier=verifier)
        doc = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
            paired_forecasts=[build_pair(base, bundle['snapshot']['as_of'])],
            additional_official_feature_shadows=[build_live_feature_shadow(base, extra, bundle['snapshot']['as_of'])],
            observed_pairwise_p1_bundles=[bundle], learned_pairwise_shadows=shadows)
        raw, receipt = archive(doc, saved=(NOW+timedelta(minutes=11)).isoformat())
        parsed, baseline = frozen.read_p1(raw, receipt)
        return parsed, receipt, baseline, verifier, context

    def test_saved_video_versions_replay_without_changing_five_baseline_rows(self):
        doc, receipt, baseline, verifier, context = self.saved_video_archive()
        before = deepcopy((doc, receipt, baseline))
        rows = existing.read_shadow_rows(doc, receipt, baseline, video_receipt_verifier=verifier)
        self.assertEqual(len(baseline), 5)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {'race_id', 'sport', 'stage', 'model_id', 'as_of', 'cutoff_at',
            'server_saved_at', 'artifact_id', 'original_json_sha256', 'model_sha256', 'roster', 'top8',
            'ranked', 'calibrated', 'variant', 'training_sha256', 'baseline_model_sha256',
            'training_artifact_id', 'training_receipt_digest'})
        self.assertEqual({row['variant'] for row in rows}, {'LEARNED_VIDEO_EXPERIMENTAL'})
        self.assertEqual({row['model_id'] for row in rows}, set(MODEL_IDS))
        self.assertEqual({row['model_sha256'] for row in rows},
                         {record['prediction_sha256'] for record in doc['learned_pairwise_shadows']})
        self.assertEqual(rows, existing.read_shadow_rows(doc, receipt, baseline, video_receipt_verifier=verifier))
        existing.validate_shadow_training(rows, {'700': existing.training_proof(context)})
        with self.assertRaises(ValueError):
            existing.validate_shadow_training(rows, {})
        self.assertEqual((doc, receipt, baseline), before)

    def test_saved_video_json_cannot_authenticate_without_caller_reader(self):
        doc, receipt, baseline, _, _ = self.saved_video_archive()
        for record in doc['learned_pairwise_shadows']:
            record['authenticated'] = True
            existing.seal(record, 'prediction_sha256')
        with self.assertRaises(ValueError):
            existing.read_shadow_rows(doc, receipt, baseline)
        with self.assertRaises(ValueError):
            existing.read_shadow_rows(doc, receipt, baseline, video_receipt_verifier=lambda *_: None)

    def test_saved_family_cannot_contain_both_old_and_video_parameter_versions(self):
        doc, receipt, baseline, verifier, _ = self.saved_video_archive()
        bundle = doc['observed_pairwise_p1_bundles'][0]
        old_context = dict(training=existing.fit_from_verified(*dataset(12), now=NOW),
                           receipt=deepcopy(self.frozen['receipt']))
        old_shadow = existing.make_shadows(bundle['snapshot'], bundle['suite'], old_context)[0]
        doc['learned_pairwise_shadows'].append(old_shadow)
        with self.assertRaisesRegex(ValueError, 'duplicate/foreign candidate'):
            existing.read_shadow_rows(doc, receipt, baseline, video_receipt_verifier=verifier)

    def test_resealed_video_record_tampering_and_future_receipts_are_rejected(self):
        doc, receipt, baseline, verifier, _ = self.saved_video_archive()
        for change in ('baseline', 'baseline_roster', 'input', 'roster', 'future_video', 'future_training', 'training', 'cutoff', 'proof'):
            bad = deepcopy(doc)
            bound_baseline = deepcopy(baseline)
            record = bad['learned_pairwise_shadows'][0]
            if change == 'baseline': record['baseline_model_sha256'] = 'f'*64
            if change == 'baseline_roster':
                next(row for row in bound_baseline if row['model_id'] == record['model_id'])['roster']['1'] = '9999'
            if change == 'input': record['input_sha256'] = 'f'*64
            if change == 'roster':
                record['video_context']['participants'][0]['registration_number'] = '9999'
                reseal_context(record['video_context'])
            if change == 'future_video': record['video_receipt']['created_at'] = record['cutoff_at']
            if change == 'future_training': record['training_receipt']['created_at'] = record['as_of']
            if change == 'training':
                record['training']['models'][MODEL_IDS[0]]['video_weights'][0] = 5.
                existing.seal(record['training'], 'training_sha256')
            if change == 'cutoff': record['cutoff_at'] = (NOW+timedelta(minutes=40)).isoformat()
            if change == 'proof': record['video_receipt_proof']['id'] += 1
            existing.seal(record, 'prediction_sha256')
            with self.subTest(change=change), self.assertRaises(ValueError):
                existing.read_shadow_rows(bad, receipt, bound_baseline, video_receipt_verifier=verifier)


if __name__ == '__main__':
    unittest.main()
