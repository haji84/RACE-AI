"""Local owner-cipher/readback caller fixtures; no Git or provider transport."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_all_model_cycle as engine, boat_all_model_store as store
from scripts import boat_all_model_cycle as cli, github_existing_cycle as runner
from tests import test_boat_all_model_cycle as fixtures

KEY = bytes(range(32))  # Deliberately public fixture-only key.


class CycleCapsuleCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fitted = fixtures.fitted_ranker()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.repo = self.base/'repo'; self.repo.mkdir(mode=0o700)
        self.temp = self.base/'private'; self.temp.mkdir(mode=0o700)
        self.root = self.temp/'fixtures'; self.root.mkdir(mode=0o700)
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_RUN_ID='42', GITHUB_SHA=fixtures.HEAD, RUNNER_TEMP=str(self.temp),
            RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        for context in (patch.dict(os.environ, env), patch.object(runner, 'ROOT', self.repo),
                        patch.object(cli, 'ROOT', self.repo)):
            context.start(); self.addCleanup(context.stop)
        self.clock = fixtures.NOW+timedelta(seconds=30)

    def save(self, path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = value if type(value) is bytes else (json.dumps(value, sort_keys=True, ensure_ascii=False)+'\n').encode()
        path.write_bytes(raw); path.chmod(0o600)
        return raw

    def frozen(self, *, legacy=False):
        files = fixtures.AllModelCycleTests.runtime(self, fitted=True)
        payload = engine.forecast_round([fixtures.source_context()], files, now=fixtures.NOW)
        if legacy: payload.pop('native_input_capsules')
        cipher = store.seal_forecasts(payload, run_id='42', round_no=2, key=KEY)
        env = cli._environment(); path, manifest_path = cli._paths(env, 2)
        self.save(path, cipher)
        self.manifest = dict(operation='generate', round_no=2, run_id='42', head_sha=fixtures.HEAD,
            inputs_sha256=digest(payload['current_inputs']), baseline_artifact=None,
            cipher_sha256=sha256(cipher).hexdigest(), payload_sha256=digest(payload))
        self.save(manifest_path, self.manifest)
        receipt = fixtures.receipt(payload)
        view = engine.project_round(payload, receipt)
        view_path = self.temp/'boat-all-model-views/cycle-2.json'; view_raw = self.save(view_path, view)
        pointer = dict(schema=store.SCHEMA, purpose=store.PURPOSE, repository_id=store.REPO_ID, ref=store.FORECAST_REF,
            cipher_path='forecasts/'+sha256(cipher).hexdigest()+'.enc', cipher_sha256=sha256(cipher).hexdigest(),
            header=store.forecast_header(cipher), status='READY', source_commit='b'*40,
            git_commit_at=self.clock.isoformat(), commit_clock_authority=store.CLOCK_AUTHORITY)
        self.reference = dict(schema=cli.READBACK_SCHEMA, pointer=pointer, receipt=receipt,
            private_view_path=str(view_path), view_sha256=sha256(view_raw).hexdigest(), round_no=2, run_id='42')
        self.ref_path = self.temp/'boat-all-model-readback.json'; self.save(self.ref_path, self.reference)
        return payload, path, manifest_path

    def requests(self):
        return runner._verified_round_additional_requests(2, now=self.clock)

    def test_no_readback_or_legacy_capsules_preserves_existing_path_without_transport(self):
        with patch.object(store, 'open_forecasts', side_effect=AssertionError('cipher read before independent readback')):
            self.assertEqual(self.requests(), [])
        self.frozen(legacy=True)
        with patch.object(runner, 'gh', side_effect=AssertionError('network')), \
             patch.object(cli, 'gh', side_effect=AssertionError('network')):
            self.assertEqual(self.requests(), [])

    def test_exact_verified_p1_groups_become_requests_with_no_stage_or_scope_rewrite(self):
        payload, _, _ = self.frozen()
        with patch.object(runner, 'gh', side_effect=AssertionError('network')), \
             patch.object(cli, 'gh', side_effect=AssertionError('network')):
            requests = self.requests()
        expected = {(f"boat/{mid}", digest(native)) for capsule in payload['native_input_capsules']
            for group, native in capsule['native_inputs'].items() for mid in capsule['group_model_ids'][group]}
        self.assertEqual({(r['cell_key'], digest(r['native_payload'])) for r in requests}, expected)
        self.assertGreaterEqual(len(requests), 9)
        self.assertTrue(any('multisport-' in row['cell_key'] for row in requests))
        from race_ai.all_existing_model_inputs import validate_additional_requests
        self.assertEqual(validate_additional_requests(requests), requests)
        original = deepcopy(payload)
        requests[0]['native_payload']['caller_mutation'] = True
        self.assertEqual(payload, original)

    def test_run_head_round_path_pointer_receipt_and_manifest_tamper_stop_before_generation(self):
        _, _, manifest_path = self.frozen()
        changes = (
            lambda r: r.update(round_no=1), lambda r: r.update(run_id='43'),
            lambda r: r.update(private_view_path=str(self.temp/'different.json')),
            lambda r: r['receipt'].update(independently_verified=False),
            lambda r: r['receipt'].update(head_sha='f'*40),
            lambda r: r['pointer'].update(cipher_sha256='f'*64),
        )
        for mutate in changes:
            reference = deepcopy(self.reference); mutate(reference); self.save(self.ref_path, reference)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.requests()
        self.save(self.ref_path, self.reference)
        self.save(manifest_path, dict(self.manifest, cipher_sha256='f'*64))
        with self.assertRaises(ValueError): self.requests()

    def test_wrong_owner_or_private_file_permissions_never_expose_requests(self):
        _, path, _ = self.frozen()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(range(32)))).decode()), \
                self.assertRaises(ValueError): self.requests()
        path.chmod(0o644)
        with self.assertRaises(ValueError): self.requests()
        path.chmod(0o600); self.ref_path.chmod(0o644)
        with self.assertRaises(ValueError): self.requests()

    def test_view_hash_and_future_readback_receipt_cannot_substitute_for_current_saved_inputs(self):
        self.frozen()
        self.reference['view_sha256'] = 'f'*64; self.save(self.ref_path, self.reference)
        with self.assertRaises(ValueError): self.requests()
        self.reference['view_sha256'] = sha256(Path(self.reference['private_view_path']).read_bytes()).hexdigest()
        self.reference['receipt']['created_at'] = (self.clock+timedelta(seconds=1)).isoformat()
        self.save(self.ref_path, self.reference)
        with self.assertRaises(ValueError): self.requests()

    def test_generator_receives_verified_additions_only_and_failed_readback_holds(self):
        self.frozen()
        runtime = dict(preload_folder=self.temp/'preload', output_folder=self.temp/'output')
        runtime['preload_folder'].mkdir(mode=0o700)
        response = dict(state='EXPLICIT_FIXTURE_NO_INFERENCE', pending_removed=False)
        with patch('race_ai.all_existing_model_runtime.generate_current_pairs', return_value=response) as generate, \
             patch.object(runner, 'datetime') as clock:
            clock.now.return_value = self.clock
            result = runner._all_model_research_generate(runtime, 2)
        self.assertEqual(result, response)
        self.assertTrue(generate.call_args.kwargs['additional_requests'])
        self.reference['receipt']['head_sha'] = 'f'*40; self.save(self.ref_path, self.reference)
        runtime['preload_folder'].mkdir(mode=0o700)
        with patch('race_ai.all_existing_model_runtime.generate_current_pairs') as generate, \
             patch.object(runner, 'datetime') as clock:
            clock.now.return_value = self.clock
            result = runner._all_model_research_generate(runtime, 2)
        generate.assert_not_called()
        self.assertEqual(result['state'], 'HOLD_PRIVATE_NATIVE_INPUTS')


if __name__ == '__main__':
    unittest.main()
