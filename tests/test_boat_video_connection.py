"""Fictional end-to-end orchestration; no field or authentication claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import MODEL_IDS, predict_pair
from race_ai.boat_video_evaluation import _time
from race_ai.boat_video_model_context import prepare_video_context
from tests.test_boat_video_evaluation import reseal
from tests.test_boat_video_model_context import fixture, seal_evidence
from tests.test_boat_video_learning import controlled_inputs
from tests import test_observed_weight_learning as observed_fixtures

NOW = observed_fixtures.NOW


def controlled_connection(training):
    """Actual report/adapter/model math with an explicitly fictional reader."""
    report, evidence = fixture()
    snapshot, _ = observed_fixtures.LearningTests().future()
    snapshot['stage'] = 'P1'
    official_p1 = observed_fixtures.fixture('P1', research=True)
    instant = _time(snapshot['as_of'])
    for participant, official in zip(snapshot['participants'], official_p1['participants']):
        participant['registration_no'] = str(4200 + participant['lane'])
        for name in ('exhibition_time_seconds', 'exhibition_start_seconds'):
            participant['features'][name] = deepcopy(official['features'][name])
            participant['missing'].pop(name, None)
    report.update(race_id='20300401-24-12', cutoff_at=snapshot['sales_cutoff_at'],
        analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
        analysis_completed_at=(instant-timedelta(minutes=3)).isoformat())
    report['source']['captured_at'] = (instant-timedelta(minutes=5)).isoformat()
    report = reseal(report)
    evidence.update(race_id=report['race_id'], cutoff_at=report['cutoff_at'],
        report_sha256=report['report_sha256'], created_at=(instant-timedelta(minutes=2)).isoformat())
    evidence = seal_evidence(evidence)
    context = prepare_video_context(report, evidence, race_id=report['race_id'],
        cutoff_at=report['cutoff_at'], roster=report['roster'],
        as_of=(instant-timedelta(minutes=1)).isoformat())
    receipt = dict(id=999, created_at=(instant-timedelta(seconds=30)).isoformat(),
        digest='sha256:'+'d'*64, expired=False, workflow_run={'head_repository_id': 1416489937})
    expected = dict(context_sha256=context['context_sha256'], id=receipt['id'],
        digest=receipt['digest'], created_at=receipt['created_at'])
    def verifier(raw, context_sha256, as_of):
        if raw == receipt and context_sha256 == context['context_sha256'] and as_of == snapshot['as_of']:
            return deepcopy(expected)
        return None
    inputs = dict(snapshot=snapshot, baseline_suite=predict_pair(snapshot, allow_source=lambda *_: True),
        video_context=context, training_context=dict(training=deepcopy(training), receipt=dict(id=700,
            created_at=(NOW+timedelta(seconds=2)).isoformat(), digest='sha256:'+'a'*64,
            expired=False, workflow_run={'head_repository_id': 1416489937})), video_receipt=receipt)
    return report, evidence, inputs, verifier, instant+timedelta(seconds=30)


def queued_report(root, report):
    from race_ai.boat_video_intake import enqueue
    private = root / 'private'; private.mkdir(mode=0o700)
    media = root / 'fictional.bin'
    media.write_bytes(b'fictional decoder input; not actual exhibition footage'); media.chmod(0o600)
    job = dict(schema_version='RACE_AI_BOAT_VIDEO_JOB_V1',
        **{key: deepcopy(report[key]) for key in ('race_id', 'cutoff_at', 'roster', 'source')},
        **deepcopy(report['analysis_parameters']))
    enqueue(private, media, job)
    return private, media, job


class VideoConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.boat_video_learning import fit_with_video
        rows, observations, contexts, verifier = controlled_inputs()
        cls.training = fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)

    def module(self):
        return importlib.import_module('race_ai.boat_video_connection')

    def connect(self, **overrides):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        args = dict(identity_evidence=evidence, model_inputs=inputs,
                    receipt_verifier=verifier, clock=lambda: instant)
        args.update(overrides)
        return self.module().connect_report(report, **args)

    def test_actual_report_to_existing_model_shadows_with_later_actual_clock(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        before = deepcopy((report, evidence, inputs))
        from race_ai import observed_weight_learning as existing
        with patch.object(existing, 'make_shadows', wraps=existing.make_shadows) as actual:
            out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=inputs,
                receipt_verifier=verifier, clock=lambda: instant)
        self.assertEqual(actual.call_count, 1)
        self.assertEqual(out['status'], 'CONNECTED_EXPERIMENTAL')
        self.assertEqual(out['started_at'], instant.isoformat())
        self.assertGreater(_time(out['started_at']), _time(out['video_context']['as_of']))
        self.assertLess(_time(out['video_context']['as_of']), _time(inputs['video_receipt']['created_at']))
        self.assertLess(_time(inputs['video_receipt']['created_at']), _time(inputs['snapshot']['as_of']))
        self.assertEqual(out['video_context']['report_sha256'], report['report_sha256'])
        self.assertEqual({row['model_id'] for row in out['shadows']}, set(MODEL_IDS))
        for row in out['shadows']:
            self.assertEqual(row['model_version'], '0.3.0-VIDEO-EXPERIMENTAL')
            self.assertEqual(row['video_context'], out['video_context'])
            self.assertEqual(row['raw_report_validation_status'], 'UNVALIDATED')
            self.assertFalse(row['production_eligible'])
            self.assertFalse(row['independent_human_heldout_verified'])
            self.assertEqual(len(row['candidates']), 120)
        self.assertEqual((report, evidence, inputs), before)
        self.assertEqual(digest({k: v for k, v in out.items() if k != 'connection_sha256'}), out['connection_sha256'])

    def test_missing_evidence_and_missing_frozen_inputs_have_explicit_context(self):
        out = self.connect(identity_evidence=None, model_inputs=None)
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('INDEPENDENT_NUMBER_EVIDENCE_MISSING', out['missing_reasons'])
        self.assertFalse(out['shadows'])
        self.assertTrue(all(cell['value'] is None for row in out['video_context']['participants']
            for cell in row['feature_cells'].values()))
        out = self.connect(model_inputs=None)
        self.assertEqual(out['status'], 'WAITING_FROZEN_TRAINING_AND_INPUTS')
        self.assertFalse(out['shadows'])

    def test_json_receipt_without_trusted_callback_never_predicts(self):
        out = self.connect(receipt_verifier=None)
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('INDEPENDENT_VIDEO_RECEIPT_VERIFIER_MISSING', out['missing_reasons'])
        self.assertFalse(out['shadows'])
        out = self.connect(receipt_verifier={'authenticated': True})
        self.assertEqual(out['status'], 'BLOCKED')

    def test_fresh_context_is_returned_for_freezing_before_a_later_model_snapshot(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        inputs.pop('video_context')
        out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=inputs,
            receipt_verifier=verifier, clock=lambda: instant)
        self.assertEqual(out['status'], 'WAITING_INDEPENDENT_CONTEXT_RECEIPT')
        self.assertEqual(out['video_context']['as_of'], instant.isoformat())
        self.assertFalse(out['shadows'])

    def test_synthetic_and_actual_postcutoff_never_use_historical_context_to_predict(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        for synthetic in (False, True):
            raw, proof = deepcopy((report, evidence))
            if synthetic:
                raw['source'].update(kind='SYNTHETIC_TEST', identity_status='SYNTHETIC')
                raw['dataset_status'] = 'SYNTHETIC_ONLY'
                raw = reseal(raw); proof['report_sha256'] = raw['report_sha256']; proof = seal_evidence(proof)
            out = self.module().connect_report(raw, identity_evidence=proof, model_inputs=inputs,
                receipt_verifier=verifier, clock=lambda: instant if synthetic else _time(report['cutoff_at']))
            self.assertEqual(out['status'], 'BLOCKED')
            self.assertFalse(out['shadows'])
            self.assertIn('SYNTHETIC_ONLY' if synthetic else 'ACTUAL_INFERENCE_POST_CUTOFF', out['missing_reasons'])

    def test_completion_crossing_cutoff_discards_model_outputs(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        times = iter((instant, _time(report['cutoff_at'])))
        out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=inputs,
            receipt_verifier=verifier, clock=lambda: next(times))
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('ACTUAL_INFERENCE_POST_CUTOFF', out['missing_reasons'])
        self.assertFalse(out['shadows'])

    def test_snapshot_before_report_future_foreign_or_roster_mismatch_is_blocked(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        mutations = (
            lambda x: x['snapshot'].update(as_of=report['analysis_started_at']),
            lambda x: x['snapshot'].update(as_of=(instant+timedelta(seconds=1)).isoformat()),
            lambda x: x['snapshot'].update(race_id='boat:2030-04-01:boatrace-jcd-01:1'),
            lambda x: x['snapshot']['participants'][0].update(registration_no='9999'),
            lambda x: x['snapshot'].update(sales_cutoff_at=(instant+timedelta(minutes=30)).isoformat()),
        )
        for mutate in mutations:
            bad = deepcopy(inputs); mutate(bad)
            with self.subTest(snapshot=bad['snapshot']):
                out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=bad,
                    receipt_verifier=verifier, clock=lambda: instant)
                self.assertEqual(out['status'], 'BLOCKED')
                self.assertFalse(out['shadows'])

    def test_wrong_context_receipt_and_nonvideo_training_do_not_fake_video_use(self):
        out = self.connect(receipt_verifier=lambda *_: {'authenticated': True})
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertFalse(out['shadows'])
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        inputs['training_context'] = observed_fixtures.LearningTests().context()
        out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=inputs,
            receipt_verifier=verifier, clock=lambda: instant)
        self.assertEqual(out['status'], 'WAITING_FROZEN_TRAINING_AND_INPUTS')
        self.assertFalse(out['shadows'])

    def test_default_clock_is_actual_now_and_never_analysis_time(self):
        report, evidence, _, _, _ = controlled_connection(self.training)
        before = datetime.now(timezone.utc)
        out = self.module().connect_report(report, identity_evidence=evidence)
        self.assertLessEqual(before, _time(out['started_at']))
        self.assertLessEqual(_time(out['completed_at']), datetime.now(timezone.utc))
        self.assertEqual(out['video_context']['as_of'], out['started_at'])

    def test_intake_hook_with_trusted_readers_runs_actual_models_and_reuses_without_clock(self):
        from race_ai.boat_video_evaluation import save_evaluation
        from race_ai.boat_video_intake import process_ready, process_connections
        from race_ai import observed_weight_learning as existing
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        before = deepcopy(inputs['baseline_suite'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            save_evaluation(root, report)
            with patch.object(existing, 'make_shadows', wraps=existing.make_shadows) as actual:
                out = process_ready(root, connect_models=True,
                    identity_evidence_provider=lambda _: deepcopy(evidence),
                    model_inputs_provider=lambda _: deepcopy(inputs), receipt_verifier=verifier,
                    connection_clock=lambda: instant)
            self.assertEqual(actual.call_count, 1)
            self.assertEqual(out['model_connections']['counts'], {'CONNECTED_EXPERIMENTAL': 1})
            def no_clock():
                self.fail('a repeated input must not create a clock-only new attempt')
            repeated = process_connections(root, identity_evidence_provider=lambda _: deepcopy(evidence),
                model_inputs_provider=lambda _: deepcopy(inputs), receipt_verifier=verifier, clock=no_clock)
            self.assertEqual((repeated['processed'], repeated['reused']), (0, 1))
            bundles = list((root / 'video-connections').glob('*.json'))
            self.assertEqual(len(bundles), 1)
            self.assertEqual(len(json.loads(bundles[0].read_text())['shadows']), 2)
        self.assertEqual(inputs['baseline_suite'], before)

    def test_resealed_frozen_context_cannot_replace_report_derived_cells(self):
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        frozen = inputs['video_context']
        frozen['participants'][0]['feature_cells']['straight_mean_speed']['value'] = 999.
        frozen.pop('context_sha256'); frozen['context_sha256'] = digest(frozen)
        out = self.module().connect_report(report, identity_evidence=evidence, model_inputs=inputs,
            receipt_verifier=verifier, clock=lambda: instant)
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('FROZEN_VIDEO_CONTEXT_REPORT_BINDING_MISMATCH', out['missing_reasons'])
        self.assertFalse(out['shadows'])

    def test_urgent_new_report_reaches_actual_models_before_historical_analysis(self):
        from race_ai import boat_video_intake as intake
        from race_ai import observed_weight_learning as existing
        from race_ai.boat_video_evaluation import analyze_video
        report, evidence, inputs, verifier, instant = controlled_connection(self.training)
        events, actual_clock = [], [instant]
        original_math = existing.make_shadows
        def observed_math(*args, **kwargs):
            events.append('model:urgent')
            return original_math(*args, **kwargs)
        def analyze(path, specification, *, extractor=None):
            urgent = specification['race_id'] == report['race_id']
            events.append('analyze:urgent' if urgent else 'analyze:historical')
            if urgent:
                times = (report['analysis_started_at'], report['analysis_completed_at'])
            else:
                actual_clock[0] = _time(report['cutoff_at']) + timedelta(seconds=3)
                times = ((_time(report['cutoff_at'])+timedelta(seconds=1)).isoformat(),
                         actual_clock[0].isoformat())
            clock = iter(map(_time, times))
            return analyze_video(path, specification, clock=lambda: next(clock),
                extractor=lambda path, *, options=None: deepcopy(report['tracking']))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            private = root / 'private'; private.mkdir(mode=0o700)
            media = root / 'fictional.bin'
            media.write_bytes(b'fictional decoder input; not actual exhibition footage'); media.chmod(0o600)
            job = dict(schema_version='RACE_AI_BOAT_VIDEO_JOB_V1',
                **{key: deepcopy(report[key]) for key in ('race_id', 'cutoff_at', 'roster', 'source')},
                **deepcopy(report['analysis_parameters']))
            historical = deepcopy(job)
            historical.update(race_id='20300401-24-11', cutoff_at=(instant-timedelta(hours=1)).isoformat())
            intake.enqueue(private, media, historical)
            intake.enqueue(private, media, job)
            with patch.object(intake, 'analyze_video', side_effect=analyze), \
                 patch.object(existing, 'make_shadows', side_effect=observed_math):
                out = intake.process_ready(private, now=_time(report['cutoff_at'])-timedelta(minutes=13),
                    connect_models=True, identity_evidence_provider=lambda raw: deepcopy(evidence)
                        if raw['race_id'] == report['race_id'] else None,
                    model_inputs_provider=lambda raw: deepcopy(inputs)
                        if raw['race_id'] == report['race_id'] else None,
                    receipt_verifier=verifier, connection_clock=lambda: actual_clock[0])
            self.assertEqual(events[:3], ['analyze:urgent', 'model:urgent', 'analyze:historical'])
            self.assertEqual(out['counts']['SUCCEEDED'], 2)
            self.assertEqual(out['model_connections']['processed'], 2)
            self.assertEqual(out['model_connections']['reused'], 0)
            self.assertEqual(len(out['model_connections']['states']), 2)
            self.assertEqual(out['model_connections']['counts']['CONNECTED_EXPERIMENTAL'], 1)

    def test_saved_waiting_report_with_ready_proof_reaches_models_before_queued_history(self):
        from race_ai import boat_video_intake as intake
        from race_ai import observed_weight_learning as existing
        from race_ai.boat_video_evaluation import analyze_video
        report, evidence, inputs, verifier, _ = controlled_connection(self.training)
        current = [_time(report['cutoff_at'])-timedelta(minutes=13)]
        events, original_math = [], existing.make_shadows
        def analyze(path, specification, *, extractor=None):
            urgent = specification['race_id'] == report['race_id']
            events.append('analyze:urgent' if urgent else 'analyze:historical')
            if urgent:
                times = (report['analysis_started_at'], report['analysis_completed_at'])
            else:
                current[0] = _time(report['cutoff_at'])+timedelta(seconds=3)
                times = ((current[0]-timedelta(seconds=2)).isoformat(), current[0].isoformat())
            clock = iter(map(_time, times))
            return analyze_video(path, specification, clock=lambda: next(clock),
                extractor=lambda path, *, options=None: deepcopy(report['tracking']))
        def observe_math(*args, **kwargs):
            events.append('model:urgent')
            return original_math(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            private, media, job = queued_report(root, report)
            with patch.object(intake, 'analyze_video', side_effect=analyze), \
                 patch.object(existing, 'make_shadows', side_effect=observe_math):
                first = intake.process_ready(private, now=current[0], connect_models=True,
                    identity_evidence_provider=lambda _: deepcopy(evidence),
                    receipt_verifier=verifier, connection_clock=lambda: current[0])
                self.assertEqual(first['model_connections']['counts'], {'WAITING_FROZEN_TRAINING_AND_INPUTS': 1})
                historical = deepcopy(job)
                historical.update(race_id='20300401-24-11', cutoff_at=(current[0]-timedelta(hours=1)).isoformat())
                intake.enqueue(private, media, historical)
                events.clear()
                out = intake.process_ready(private, now=current[0], connect_models=True,
                    identity_evidence_provider=lambda raw: deepcopy(evidence)
                        if raw['race_id'] == report['race_id'] else None,
                    model_inputs_provider=lambda raw: deepcopy(inputs)
                        if raw['race_id'] == report['race_id'] else None,
                    receipt_verifier=verifier, connection_clock=lambda: current[0])
            self.assertEqual(events[:2], ['model:urgent', 'analyze:historical'])
            self.assertEqual(out['counts']['SUCCEEDED'], 2)
            self.assertEqual(out['model_connections']['counts']['CONNECTED_EXPERIMENTAL'], 1)
            self.assertEqual(out['model_connections']['processed'], 2)
            self.assertEqual(out['model_connections']['reused'], 0)

    def test_saved_waiting_proof_becoming_ready_mid_batch_scores_before_next_history(self):
        from race_ai import boat_video_intake as intake
        from race_ai import observed_weight_learning as existing
        from race_ai.boat_video_evaluation import analyze_video
        report, evidence, inputs, verifier, _ = controlled_connection(self.training)
        current = [_time(report['cutoff_at'])-timedelta(minutes=13)]
        ready, events, original_math = [False], [], existing.make_shadows
        def analyze(path, specification, *, extractor=None):
            number = specification['race_id'][-2:]
            events.append('analyze:'+number)
            if specification['race_id'] == report['race_id']:
                times = (report['analysis_started_at'], report['analysis_completed_at'])
            else:
                start = current[0]
                current[0] = (start+timedelta(seconds=2) if number == '10' else
                              _time(report['cutoff_at'])+timedelta(seconds=3))
                ready[0] = True
                times = (start.isoformat(), current[0].isoformat())
            clock = iter(map(_time, times))
            return analyze_video(path, specification, clock=lambda: next(clock),
                extractor=lambda path, *, options=None: deepcopy(report['tracking']))
        def observe_math(*args, **kwargs):
            events.append('model:urgent')
            return original_math(*args, **kwargs)
        def model_provider(raw):
            return deepcopy(inputs) if ready[0] and raw['race_id'] == report['race_id'] else None
        def evidence_provider(raw):
            return deepcopy(evidence) if raw['race_id'] == report['race_id'] else None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            private, media, job = queued_report(root, report)
            with patch.object(intake, 'analyze_video', side_effect=analyze), \
                 patch.object(existing, 'make_shadows', side_effect=observe_math):
                intake.process_ready(private, now=current[0], connect_models=True,
                    identity_evidence_provider=evidence_provider, model_inputs_provider=model_provider,
                    receipt_verifier=verifier, connection_clock=lambda: current[0])
                for number in (10, 11):
                    historical = deepcopy(job)
                    historical.update(race_id='20300401-24-%02d' % number,
                        cutoff_at=(current[0]-timedelta(hours=12-number)).isoformat())
                    intake.enqueue(private, media, historical)
                events.clear()
                out = intake.process_ready(private, now=current[0], connect_models=True,
                    identity_evidence_provider=evidence_provider, model_inputs_provider=model_provider,
                    receipt_verifier=verifier, connection_clock=lambda: current[0])
            self.assertEqual(events[:3], ['analyze:10', 'model:urgent', 'analyze:11'])
            self.assertEqual(out['counts']['SUCCEEDED'], 3)
            self.assertEqual(out['model_connections']['counts']['CONNECTED_EXPERIMENTAL'], 1)


if __name__ == '__main__':
    unittest.main()
