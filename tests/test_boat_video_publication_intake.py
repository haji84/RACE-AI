"""Controlled intake-to-producer callbacks; no real dispatch or receipt claim."""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import numpy
except ImportError:
    numpy = None

from race_ai.boat_video_evaluation import save_evaluation
from race_ai.boat_video_model_context import prepare_video_context
from tests.test_boat_video_connection import queued_report
from tests.test_boat_video_model_context import fixture, AS_OF
from tests.test_boat_video_publication import HEAD, KEY


class PublicationIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.report, self.evidence = fixture()
        self.context = prepare_video_context(self.report, self.evidence,
            race_id=self.report['race_id'], cutoff_at=self.report['cutoff_at'],
            roster=self.report['roster'], as_of=AS_OF)
        self.inputs = {'video_context': deepcopy(self.context)}
        self.now = datetime.fromisoformat(AS_OF) + timedelta(seconds=1)
        self.private, self.media, self.job = queued_report(self.root, self.report)
        save_evaluation(self.private, self.report)
        self.mod = importlib.import_module('race_ai.boat_video_intake')
        self.calls = []

    def publisher(self, result=None, *, configuration='1'*64):
        if result is None:
            result = dict(status='DISPATCH_REQUEST_ACCEPTED_NOT_ARTIFACT_RECEIPT',
                context_count=1, cipher_sha256='a'*64, dispatch_sha256='b'*64)

        def publish(binding):
            self.calls.append(deepcopy(binding))
            return deepcopy(result)
        publish.configuration_sha256 = configuration
        return publish

    def connect(self, publisher=None, **overrides):
        options = dict(identity_evidence_provider=lambda report: deepcopy(self.evidence),
            model_inputs_provider=lambda report: deepcopy(self.inputs), clock=lambda: self.now)
        options.update(overrides)
        if publisher is not None:
            options['context_publisher'] = publisher
        return self.mod.process_connections(self.private, **options)

    def publication(self, result):
        value = result['context_publications']
        self.assertFalse(value['artifact_receipt_verified'])
        self.assertFalse(value['production_eligible'])
        return value

    def journal(self):
        return sorted((self.private / 'video-publications').glob('*.json'))

    def test_no_publisher_preserves_exact_connection_bytes_and_return_contract(self):
        baseline = self.connect()
        other = self.root / 'other-private'
        other.mkdir(mode=0o700)
        save_evaluation(other, self.report)
        repeated = self.mod.process_connections(other,
            identity_evidence_provider=lambda report: deepcopy(self.evidence),
            model_inputs_provider=lambda report: deepcopy(self.inputs), clock=lambda: self.now,
            context_publisher=None)
        self.assertEqual(baseline, repeated)
        old = next((self.private / 'video-connections').glob('*.json')).read_bytes()
        new = next((other / 'video-connections').glob('*.json')).read_bytes()
        self.assertEqual(old, new)
        self.assertNotIn('context_publications', baseline)
        self.assertFalse((self.private / 'video-publications').exists())
        self.assertFalse((other / 'video-publications').exists())

    def test_qualified_frozen_context_and_actual_private_originals_are_bound(self):
        before = deepcopy((self.report, self.evidence, self.inputs))
        result = self.connect(self.publisher(), report_sha256s=[self.report['report_sha256']])
        published = self.publication(result)
        self.assertEqual((published['processed'], published['reused']), (1, 0))
        self.assertEqual(published['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(published['states'][0]['status'], 'DISPATCH_REQUEST_ACCEPTED_NOT_ARTIFACT_RECEIPT')
        self.assertEqual(len(self.calls), 1)
        binding = self.calls[0]
        self.assertEqual(binding['report'], self.report)
        self.assertEqual(binding['identity_evidence'], self.evidence)
        self.assertEqual(binding['model_inputs'], self.inputs)
        self.assertEqual(binding['video_context'], self.context)
        self.assertEqual(binding['report_path'], self.private / 'video-evaluations' /
                         (self.report['report_sha256']+'.json'))
        self.assertEqual(binding['media_path'], self.private / 'video-intake' / 'media' /
                         (self.report['source']['media_sha256']+'.media'))
        self.assertEqual(binding['media_path'].read_bytes(), self.media.read_bytes())
        self.assertEqual((self.report, self.evidence, self.inputs), before)
        self.assertEqual(len(self.journal()), 2)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in self.journal()))
        self.assertEqual((self.private / 'video-publications').stat().st_mode & 0o777, 0o700)

    def test_selected_report_does_not_open_or_publish_other_saved_report(self):
        from race_ai.boat_video_evaluation import analyze_video
        job = deepcopy(self.job)
        job['race_id'] = '20300401-01-02'
        times = iter(map(datetime.fromisoformat,
                         (self.report['analysis_started_at'], self.report['analysis_completed_at'])))
        other = analyze_video(self.media, job, clock=lambda: next(times),
            extractor=lambda path, *, options=None: deepcopy(self.report['tracking']))
        save_evaluation(self.private, other)
        reader = self.mod._read_report

        def selected_only(directory, name):
            self.assertEqual(name, self.report['report_sha256']+'.json')
            return reader(directory, name)

        with patch.object(self.mod, '_read_report', side_effect=selected_only):
            self.connect(self.publisher(), report_sha256s=[self.report['report_sha256']])
        self.assertEqual(len(self.calls), 1)

    def test_ineligible_context_never_calls_publisher_or_creates_journal(self):
        result = self.connect(self.publisher(), identity_evidence_provider=lambda report: None)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.publication(result)['states'], [])
        self.assertFalse((self.private / 'video-publications').exists())

    def test_accepted_context_is_not_republished_after_restart_or_configuration_change(self):
        publisher = self.publisher()
        self.connect(publisher)
        publisher.configuration_sha256 = '2'*64
        result = self.connect(publisher)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.publication(result)['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(len(self.journal()), 2)

    def test_known_prepost_hold_retries_only_after_configuration_change(self):
        held = self.publisher(dict(status='HOLD_OWNER_STATE_KEY_REQUIRED', context_count=0))
        first = self.connect(held)
        self.assertEqual(self.publication(first)['states'][0]['outcome'], 'HOLD')
        self.connect(held)
        self.assertEqual(len(self.calls), 1)
        ready = self.publisher(configuration='2'*64)
        last = self.connect(ready)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.publication(last)['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(len(self.journal()), 4)

    def test_callback_exception_is_redacted_and_unknown_post_is_never_retried(self):
        publisher = self.publisher()

        def rejected(binding):
            self.calls.append(deepcopy(binding))
            raise RuntimeError('owner-secret /private/path token=sensitive')
        rejected.configuration_sha256 = '1'*64
        first = self.connect(rejected)
        self.assertEqual(first['failed'], 0)
        self.assertEqual(self.publication(first)['states'][0]['outcome'], 'UNKNOWN')
        publisher.configuration_sha256 = '2'*64
        self.connect(publisher)
        self.assertEqual(len(self.calls), 1)
        text = json.dumps(first) + ''.join(path.read_text() for path in self.journal())
        self.assertNotIn('owner-secret', text)
        self.assertNotIn('sensitive', text)

    def test_interrupted_started_marker_blocks_retry_even_with_changed_configuration(self):
        def interrupted(binding):
            raise KeyboardInterrupt()
        interrupted.configuration_sha256 = '1'*64
        with self.assertRaises(KeyboardInterrupt):
            self.connect(interrupted)
        self.assertEqual(len(self.journal()), 1)
        result = self.connect(self.publisher(configuration='2'*64))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.publication(result)['states'][0]['outcome'], 'UNKNOWN')

    def test_arbitrary_callback_values_never_enter_private_status_or_originals(self):
        self.connect()
        originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                     for folder in ('video-evaluations', 'video-connections', 'video-intake/media', 'video-intake/jobs')
                     for path in (self.private / folder).glob('*') if path.is_file()}

        def mutate(binding):
            for key in ('report', 'identity_evidence', 'model_inputs', 'connection_bundle', 'video_context'):
                binding[key].clear()
            return {'status': 'owner-secret', 'error': 'token=sensitive', 'payload': self.report}
        mutate.configuration_sha256 = '1'*64
        result = self.connect(mutate)
        self.assertEqual(self.publication(result)['states'][0]['outcome'], 'UNKNOWN')
        self.assertEqual(originals, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in originals})
        self.assertNotIn('owner-secret', ''.join(path.read_text() for path in self.journal()))
        self.assertNotIn('feature_cells', ''.join(path.read_text() for path in self.journal()))

    def test_changed_configuration_does_not_send_after_cutoff(self):
        self.connect(self.publisher(dict(status='HOLD_PLATFORM_ACTIVATION_UNVERIFIED', context_count=0)))
        self.now = datetime.fromisoformat(self.report['cutoff_at']) + timedelta(seconds=1)
        result = self.connect(self.publisher(configuration='2'*64))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.publication(result)['states'][0]['status'], 'HOLD_VIDEO_PUBLICATION_DEADLINE')

    def test_real_producer_cipher_roundtrip_uses_only_explicit_fake_sender(self):
        sent = []
        self.assertTrue(hasattr(self.mod, 'make_context_publisher'), 'trusted producer adapter is missing')
        publisher = self.mod.make_context_publisher(configuration_sha256='1'*64,
            expected_head_sha=HEAD, key_provider=lambda: KEY, clock=lambda: self.now,
            platform_ready=True, send=sent.append)
        result = self.connect(publisher)
        self.assertEqual(self.publication(result)['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(len(sent), 1)
        producer = importlib.import_module('race_ai.boat_video_publication')
        request = json.loads(sent[0])
        decoded, _ = producer.decrypt_publication(request['inputs']['video_context_cipher'].encode(),
            expected_head_sha=HEAD, key=KEY, available_at=self.now+timedelta(seconds=1))
        self.assertEqual(decoded['contexts'], [self.context])
        self.assertFalse(self.publication(result)['artifact_receipt_verified'])

    def test_no_sender_cannot_fall_back_to_real_gh(self):
        self.assertTrue(hasattr(self.mod, 'make_context_publisher'), 'trusted producer adapter is missing')
        producer = importlib.import_module('race_ai.boat_video_publication')
        with patch.object(producer.subprocess, 'run', side_effect=AssertionError('unexpected external API')):
            publisher = self.mod.make_context_publisher(configuration_sha256='1'*64,
                expected_head_sha=HEAD, key_provider=lambda: KEY, platform_ready=True, clock=lambda: self.now)
            result = self.connect(publisher)
        self.assertEqual(self.publication(result)['states'][0]['status'], 'HOLD_PUBLISHER_TRANSPORT_UNCONFIGURED')

    def test_platform_hold_can_only_activate_with_explicit_reconfigured_fake_sender(self):
        sent = []
        held = self.mod.make_context_publisher(configuration_sha256='1'*64, expected_head_sha=HEAD,
            key_provider=lambda: KEY, send=sent.append, clock=lambda: self.now)
        first = self.connect(held)
        self.assertEqual(self.publication(first)['states'][0]['status'], 'HOLD_PLATFORM_ACTIVATION_UNVERIFIED')
        self.assertEqual(sent, [])
        ready = self.mod.make_context_publisher(configuration_sha256='2'*64, expected_head_sha=HEAD,
            key_provider=lambda: KEY, platform_ready=True, send=sent.append, clock=lambda: self.now)
        last = self.connect(ready)
        self.assertEqual(self.publication(last)['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(len(sent), 1)

    def test_ambiguous_producer_transport_rejection_is_unknown_and_not_retried(self):
        sent = []

        def failed_send(raw):
            sent.append(raw)
            raise OSError('owner-secret transport credentials')

        publisher = self.mod.make_context_publisher(configuration_sha256='1'*64, expected_head_sha=HEAD,
            key_provider=lambda: KEY, platform_ready=True, send=failed_send, clock=lambda: self.now)
        first = self.connect(publisher)
        self.assertEqual(self.publication(first)['states'][0]['outcome'], 'UNKNOWN')
        replacement = self.mod.make_context_publisher(configuration_sha256='2'*64, expected_head_sha=HEAD,
            key_provider=lambda: KEY, platform_ready=True, send=sent.append, clock=lambda: self.now)
        self.connect(replacement)
        self.assertEqual(len(sent), 1)
        self.assertNotIn('owner-secret', ''.join(path.read_text() for path in self.journal()))

    def test_missing_protected_media_holds_without_falling_back_to_unqueued_original(self):
        media = self.private/'video-intake'/'media'/(self.report['source']['media_sha256']+'.media')
        moved = self.root/'unavailable-copy.media'
        media.rename(moved)
        first = self.connect(self.publisher())
        self.assertEqual(self.publication(first)['states'][0]['status'], 'HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE')
        self.assertEqual(self.calls, [])
        moved.rename(media)
        last = self.connect(self.publisher(configuration='2'*64))
        self.assertEqual(self.publication(last)['states'][0]['outcome'], 'ACCEPTED')
        self.assertEqual(len(self.calls), 1)

    def test_invalid_configuration_and_symlink_journal_cannot_trigger_callback(self):
        publisher = self.publisher(configuration='owner-secret')
        result = self.connect(publisher)
        self.assertEqual(self.publication(result)['states'][0]['status'], 'HOLD_PUBLISHER_CONFIGURATION_REQUIRED')
        self.assertNotIn('owner-secret', json.dumps(result))
        elsewhere = self.root/'other-private'
        elsewhere.mkdir(mode=0o700)
        (self.private/'video-publications').symlink_to(elsewhere, target_is_directory=True)
        result = self.connect(self.publisher(configuration='2'*64))
        self.assertEqual(self.publication(result)['states'][0]['status'], 'HOLD_PUBLICATION_STORAGE_UNAVAILABLE')
        self.assertEqual((self.publication(result)['processed'], self.publication(result)['reused']), (0, 0))
        self.assertEqual(self.calls, [])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_finished_status_storage_failure_preserves_unknown_started_attempt(self):
        atomic = self.mod._atomic

        def fail_final(directory, name, writer):
            if name.endswith('.finished.json'):
                raise OSError('owner-secret disk unavailable')
            return atomic(directory, name, writer)

        with patch.object(self.mod, '_atomic', side_effect=fail_final):
            first = self.connect(self.publisher())
        self.assertEqual(self.publication(first)['states'][0]['outcome'], 'UNKNOWN')
        self.assertEqual(self.publication(first)['processed'], 1)
        self.assertEqual(len(self.journal()), 1)
        self.connect(self.publisher(configuration='2'*64))
        self.assertEqual(len(self.calls), 1)

    @unittest.skipIf(numpy is None, 'optional NumPy is required for physical V2 replay')
    def test_calibration_v2_replays_through_real_producer_callback(self):
        from tests.test_boat_video_physical_context import physical_fixture
        from race_ai.boat_video_physical_context import prepare_physical_video_context
        report, evidence, manifest, arguments = physical_fixture()
        context = prepare_physical_video_context(report, evidence, manifest, **arguments)
        self.report, self.evidence, self.context = report, evidence, context
        self.inputs = dict(video_context=context, calibration_manifest=manifest)
        save_evaluation(self.private, report)
        sent = []
        publisher = self.mod.make_context_publisher(configuration_sha256='1'*64, expected_head_sha=HEAD,
            key_provider=lambda: KEY, platform_ready=True, send=sent.append, clock=lambda: self.now)
        result = self.connect(publisher, report_sha256s=[report['report_sha256']])
        self.assertEqual(self.publication(result)['states'][0]['outcome'], 'ACCEPTED')
        producer = importlib.import_module('race_ai.boat_video_publication')
        request = json.loads(sent[0])
        decoded, _ = producer.decrypt_publication(request['inputs']['video_context_cipher'].encode(),
            expected_head_sha=HEAD, key=KEY, available_at=self.now+timedelta(seconds=1))
        self.assertEqual(decoded['contexts'], [context])
        self.assertEqual(context['coordinate_space'], 'WATER_PLANE_METRES')

    def test_automatic_loop_publishes_new_eligible_report_once_before_final_rescan(self):
        # Analysis itself is controlled; immutable persistence, context replay
        # and automatic-loop publication use the real application code.
        publisher = self.publisher()
        with patch.object(self.mod, 'analyze_video', return_value=deepcopy(self.report)):
            result = self.mod.process_ready(self.private,
                now=datetime.fromisoformat(self.report['cutoff_at'])-timedelta(minutes=13),
                connect_models=True, identity_evidence_provider=lambda report: deepcopy(self.evidence),
                model_inputs_provider=lambda report: deepcopy(self.inputs),
                connection_clock=lambda: self.now, context_publisher=publisher)
        self.assertEqual(result['counts']['SUCCEEDED'], 1)
        self.assertEqual(len(self.calls), 1)
        published = self.publication(result['model_connections'])
        self.assertEqual((published['processed'], published['reused']), (1, 0))

    def test_callback_failure_does_not_stop_other_ready_jobs(self):
        from race_ai.boat_video_evaluation import analyze_video
        historical = deepcopy(self.job)
        historical.update(race_id='20300401-01-02',
                          cutoff_at=(datetime.fromisoformat(self.job['cutoff_at'])-timedelta(hours=1)).isoformat())
        self.mod.enqueue(self.private, self.media, historical)

        def analyze(path, specification, *, extractor=None):
            if specification['race_id'] == self.report['race_id']:
                return deepcopy(self.report)
            times = iter(map(datetime.fromisoformat,
                (self.report['analysis_started_at'], self.report['analysis_completed_at'])))
            return analyze_video(path, specification, clock=lambda: next(times),
                extractor=lambda path, *, options=None: deepcopy(self.report['tracking']))

        def rejected(binding):
            raise RuntimeError('owner-secret publisher failure')
        rejected.configuration_sha256 = '1'*64
        with patch.object(self.mod, 'analyze_video', side_effect=analyze):
            result = self.mod.process_ready(self.private,
                now=datetime.fromisoformat(self.report['cutoff_at'])-timedelta(minutes=13), connect_models=True,
                identity_evidence_provider=lambda report: deepcopy(self.evidence)
                    if report['race_id'] == self.report['race_id'] else None,
                model_inputs_provider=lambda report: deepcopy(self.inputs)
                    if report['race_id'] == self.report['race_id'] else None,
                connection_clock=lambda: self.now, context_publisher=rejected)
        self.assertEqual((result['counts']['SUCCEEDED'], result['failed']), (2, 0))
        self.assertEqual(self.publication(result['model_connections'])['states'][0]['outcome'], 'UNKNOWN')

    def test_existing_follow_entrypoint_accepts_only_trusted_python_publication_callbacks(self):
        output, error = io.StringIO(), io.StringIO()
        actual_process = self.mod.process_ready

        def scheduled(*args, **kwargs):
            # Keep the future-dated fictional job's scheduling clock explicit.
            return actual_process(*args,
                now=datetime.fromisoformat(self.report['cutoff_at'])-timedelta(minutes=13), **kwargs)

        with patch.object(self.mod, 'analyze_video', return_value=deepcopy(self.report)), \
                patch.object(self.mod, 'process_ready', side_effect=scheduled), \
                patch.object(self.mod.time, 'sleep', side_effect=KeyboardInterrupt()), \
                redirect_stdout(output), redirect_stderr(error):
            code = self.mod.main(['--private-root', str(self.private), '--follow', '--connect-models'],
                identity_evidence_provider=lambda report: deepcopy(self.evidence),
                model_inputs_provider=lambda report: deepcopy(self.inputs),
                connection_clock=lambda: self.now, context_publisher=self.publisher())
        self.assertEqual((code, error.getvalue()), (0, ''))
        self.assertEqual(len(self.calls), 1)
        poll = json.loads(output.getvalue())
        self.assertEqual(poll['counts']['SUCCEEDED'], 1)
        self.assertEqual(self.publication(poll['model_connections'])['counts'], {'ACCEPTED': 1})

    def test_entrypoint_callbacks_require_explicit_connection_mode(self):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), self.assertRaises(SystemExit) as rejected:
            self.mod.main(['--private-root', str(self.private), '--once'], context_publisher=self.publisher())
        self.assertEqual(rejected.exception.code, 2)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(error.getvalue(), 'BOAT_VIDEO_INTAKE_REJECTED: invalid command arguments\n')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
