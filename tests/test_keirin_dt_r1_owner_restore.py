"""Synthetic orchestration checks; no real owner key or source access."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/keirin-result-live.yml'
NOW = datetime(2026, 11, 27, 22, 50, tzinfo=timezone.utc)
PRIVATE = 'SYNTHETIC_PRIVATE_SENTINEL_NOT_REAL_KEY'


class OwnerRestoreTests(unittest.TestCase):
    def setUp(self):
        self.subject = importlib.import_module('scripts.keirin_dt_r1_owner_restore')
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {
            'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'haji84/RACE-AI',
            'GITHUB_REPOSITORY_ID': '1416489937', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ID': '123',
            'GITHUB_SHA': 'a' * 40,
            'GITHUB_WORKFLOW_REF': 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main',
            'GITHUB_JOB': 'observe-results', 'RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED': 'true',
        }

    def call(self):
        return self.subject.run_restore(repo=ROOT, private_root=self.root,
            owner_public_pem=ROOT / 'owner-public-test.pem', owner_private_pem=PRIVATE.encode(),
            day='2026-11-28', clock=lambda: NOW)

    def component(self, name):
        from research.chatgpt_dt_r1.preserve_verified_bundle import MODEL_SHA, MANIFEST_SHA
        common = dict(owner_decryption_verified=True, private_extra=PRIVATE)
        if name == 'direct':
            return dict(common, model_id='chatgpt-dt-r1', model_sha256=MODEL_SHA,
                manifest_sha256=MANIFEST_SHA, archive_commit='4' * 40,
                restored_files=24, encrypted_shards=8, calibration_artifacts=7)
        if name == 'codex':
            return dict(common, model_id='keirin-conditional-order-trees-v1',
                sealed_model_sha256='b' * 64, tree_sha256='c' * 64)
        return dict(common, model_id='chatgpt-dt-r1', artifact_sha256='d' * 64,
            candidate_bytes_sha256='e' * 64, manifest_sha256='f' * 64,
            archive_commit='5' * 40, restored_files=2, receipt_file_sha256='1' * 64)

    def test_existing_runtime_rejects_nonmain_nonmanual_wrong_job_before_any_restore(self):
        for change in ({'GITHUB_REF': 'refs/heads/research'}, {'GITHUB_EVENT_NAME': 'schedule'},
                       {'GITHUB_REPOSITORY': 'fork/RACE-AI'}, {'GITHUB_JOB': 'contracts'}):
            with self.subTest(change=change), patch.dict(os.environ, {**self.env, **change}, clear=True), \
                    patch.object(self.subject, '_restore_direct') as direct, \
                    patch.object(self.subject, '_restore_codex') as codex, \
                    patch.object(self.subject, '_restore_back') as back, \
                    patch.object(self.subject.continuation.pipeline, 'check_owner_private_key') as key_check:
                with self.assertRaises(ValueError):
                    self.call()
                direct.assert_not_called(); codex.assert_not_called(); back.assert_not_called()
                key_check.assert_not_called()

    def test_success_is_aggregate_only_and_ephemeral_plaintext_is_removed(self):
        workspaces = []
        def restored(name):
            def perform(repo, private_root, private, day):
                workspaces.append(private_root)
                (private_root / (name + '.private')).write_text(PRIVATE)
                self.assertEqual(private, PRIVATE.encode())
                return self.component(name)
            return perform
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(self.subject.continuation, '_runtime',
                    return_value=(ROOT, self.root, '2026-11-28', b'public', 'a' * 40)) as guard, \
                patch.object(self.subject, '_restore_direct', side_effect=restored('direct')), \
                patch.object(self.subject, '_restore_codex', side_effect=restored('codex')), \
                patch.object(self.subject, '_restore_back', side_effect=restored('back')), \
                patch.object(self.subject.continuation, '_begin_lease') as provider:
            report = self.call()
        self.assertEqual(guard.call_args.kwargs['mode'], 'study')
        self.assertEqual(report['state'], 'OWNER_MODELS_RESTORED_AND_VERIFIED')
        self.assertTrue(report['owner_decryption_verified'])
        self.assertEqual(set(report['models']), {'dt_r1_direct', 'codex_frozen', 'dt_r1_back'})
        self.assertNotIn(PRIVATE, json.dumps(report))
        self.assertTrue(all(not p.exists() for p in workspaces))
        self.assertFalse(report['source_authenticated'])
        self.assertFalse(report['production_promoted'])
        self.assertEqual(report['provider_source_requests'], 0)
        self.assertEqual(report['new_forecasts'], 0)
        self.assertEqual(report['training_runs'], 0)
        provider.assert_not_called()

    def test_one_restore_failure_keeps_other_evidence_but_never_claims_all_verified(self):
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(self.subject.continuation, '_runtime',
                    return_value=(ROOT, self.root, '2026-11-28', b'public', 'a' * 40)), \
                patch.object(self.subject, '_restore_direct', return_value=self.component('direct')), \
                patch.object(self.subject, '_restore_codex', side_effect=RuntimeError(PRIVATE)), \
                patch.object(self.subject, '_restore_back', return_value=self.component('back')):
            report = self.call()
        self.assertEqual(report['state'], 'HOLD_OWNER_MODEL_RESTORE_INCOMPLETE')
        self.assertEqual(report['restored_models'], 2)
        self.assertFalse(report['owner_decryption_verified'])
        self.assertTrue(report['models']['dt_r1_direct']['owner_decryption_verified'])
        self.assertEqual(report['models']['codex_frozen']['reason'], 'MODEL_RESTORE_UNVERIFIED')
        self.assertNotIn(PRIVATE, json.dumps(report))

    def test_changed_direct_manifest_stops_before_decryption_or_publication(self):
        from research.chatgpt_dt_r1 import retained_readback as retained
        with patch.object(retained, 'fetch_exact', return_value=b'{}') as fetch:
            with self.assertRaisesRegex(ValueError, 'EXTERNAL_MANIFEST_MISMATCH'):
                self.subject._restore_direct(ROOT, self.root, PRIVATE.encode(), '2026-11-28')
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse((self.root / 'direct-restored').exists())

    def test_missing_external_back_receipt_is_not_replaced_by_local_weights(self):
        with self.assertRaises(ValueError):
            self.subject._restore_back(self.root, self.root, PRIVATE.encode(), '2026-11-28')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_holds_are_sanitized_and_environment_key_is_consumed(self):
        output = io.StringIO()
        with patch.dict(os.environ, {**self.env, 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM': PRIVATE}, clear=True), \
                patch.object(self.subject, 'run_restore', side_effect=RuntimeError(PRIVATE)), redirect_stdout(output):
            code = self.subject.main(['--repo', str(ROOT), '--private-root', str(self.root),
                                     '--owner-public-pem', 'fixture-public.pem'])
            self.assertNotIn('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', os.environ)
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertFalse(report['owner_decryption_verified'])
        self.assertNotIn(PRIVATE, output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())


class OwnerRestoreWorkflowTests(unittest.TestCase):
    def job(self):
        return WORKFLOW.read_text().split('  observe-results:\n', 1)[1].split('  publish-rider-dossiers:\n', 1)[0]

    def test_restore_dispatch_preserves_existing_main_and_test_gates(self):
        job = self.job()
        expression = job.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expression = ' '.join(expression.split()).replace('&&', ' and ').replace('||', ' or ')
        expression = expression.replace('!cancelled()', 'not cancelled()')
        for change, expected in [({}, True), ({'ref': 'refs/heads/feature'}, False),
                                 ({'repository': 'fork/RACE-AI'}, False), ({'tests': 'failure'}, False),
                                 ({'event': 'push'}, False), ({'prefix': 'external'}, False)]:
            v = dict(ref='refs/heads/main', repository='haji84/RACE-AI', tests='success',
                     event='workflow_dispatch', prefix=''); v.update(change)
            context = dict(github=NS(event_name=v['event'], ref=v['ref'], repository=v['repository'], repository_id='1416489937'),
                inputs=NS(mode='dt-r1-restore'), needs=NS(tests=NS(result=v['tests'])),
                vars=NS(RACE_AI_AB_SOURCE_S3_PREFIX=v['prefix']), always=lambda: True, cancelled=lambda: False)
            with self.subTest(change=change):
                self.assertEqual(bool(eval(expression, {'__builtins__': {}}, context)), expected)

    def test_restore_uses_same_secret_step_and_exits_before_other_modes(self):
        job = self.job()
        block = job.split('if [ "$RESULT_MODE" = dt-r1-restore ]; then', 1)[1].split('          fi', 1)[0]
        self.assertIn('env -u RACE_AI_KEIRIN_PRIVATE_RSA_PEM -u GITHUB_TOKEN', block)
        self.assertIn('research/chatgpt_dt_r1/requirements.txt', block)
        self.assertIn('scripts.keirin_dt_r1_owner_restore', block)
        self.assertIn('exit 0', block)
        self.assertNotIn('scripts.keirin_result_watch', block)
        self.assertNotIn('scripts.keirin_official_measured_outcomes', block)
        self.assertEqual(job.count('secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM'), 1)
        self.assertIn("inputs.mode == 'dt-r1-restore' && '3.12' || '3.11'", job)
        self.assertLess(job.index('if [ "$RESULT_MODE" = dt-r1-restore ]; then'),
                        job.index('if [ "$RESULT_MODE" = dossier-context ]; then'))


if __name__ == '__main__':
    unittest.main()
