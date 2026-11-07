"""Fictional frozen native payloads; no production keys, Git or source I/O."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_all_model_cycle as cycle
from race_ai import boat_model_runtime as runtime_codec
from race_ai.existing_model_dispatch import dispatch, GROUPS
from tests import test_boat_all_model_cycle as fixtures
from tests.test_boat_all_model_cycle import (
    ASOF, HEAD, NOW, fitted_ranker, receipt, source_context,
)


class NativeCapsuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fitted = fitted_ranker()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def runtime(self, *, fitted=False):
        return fixtures.AllModelCycleTests.runtime(self, fitted=fitted)

    def round(self, **options):
        return cycle.forecast_round([source_context()], self.runtime(fitted=options.pop('fitted', False)),
                                    now=NOW, **options)

    def rehash(self, payload):
        for capsule, report in zip(payload['native_input_capsules'], payload['dispatch_reports']):
            capsule['native_payload_sha256'] = {g: digest(p) for g, p in capsule['native_inputs'].items()}
            value = digest({capsule['race_id']: {capsule['stage']: capsule['native_inputs']}})
            capsule['dispatch_input_sha256'] = report['input_sha256'] = value
            capsule['capsule_sha256'] = digest({k: v for k, v in capsule.items() if k != 'capsule_sha256'})

    def project(self, payload):
        return cycle.project_round(payload, receipt(payload))

    def pointer(self, files):
        source = Path(files['history.sqlite'])
        racers = source.parent/'racers.sqlite'
        racers.write_bytes(source.read_bytes()); racers.chmod(0o600)
        files['racers.sqlite'] = str(racers)
        header = dict(schema=runtime_codec.SCHEMA, purpose=runtime_codec.PURPOSE,
            repository_id=runtime_codec.REPO_ID, recipient_key_id='1'*64,
            receiver_document_sha256='2'*64, receiver_run_id='42', receiver_source_head=HEAD,
            created_at=ASOF, files={name: dict(sha256=sha256(Path(path).read_bytes()).hexdigest(),
                size=Path(path).stat().st_size) for name, path in files.items() if name in runtime_codec.FILE_LIMITS})
        return dict(schema=runtime_codec.SCHEMA, purpose=runtime_codec.PURPOSE,
            repository_id=runtime_codec.REPO_ID, ref=runtime_codec.RUNTIME_REF,
            cipher_path='runtime/'+'3'*64+'.enc', cipher_sha256='3'*64, header=header,
            status='READY', source_commit='b'*40)

    def test_exact_dispatch_group_payloads_are_frozen_without_changing_summary_or_projection(self):
        calls = []
        def capture(schedule, inputs, **kwargs):
            calls.append(deepcopy(inputs))
            return dispatch(schedule, inputs, **kwargs)
        with patch.object(cycle, 'dispatch', side_effect=capture):
            payload = self.round(fitted=True)
        capsules = payload['native_input_capsules']
        self.assertEqual(len(capsules), 1)
        capsule = capsules[0]
        self.assertEqual(capsule['native_inputs'], calls[0][capsule['race_id']][capsule['stage']])
        self.assertEqual(capsule['dispatch_input_sha256'], payload['dispatch_reports'][0]['input_sha256'])
        for group, native in capsule['native_inputs'].items():
            self.assertEqual(capsule['native_payload_sha256'][group], digest(native))
            self.assertEqual(capsule['group_model_ids'][group], list(dict(GROUPS)[group]))
        self.assertIn('boat_full', capsule['native_inputs'])
        self.assertIn('shared', capsule['native_inputs'])
        self.assertTrue(capsule['analysis_source_refs'])
        self.assertEqual(cycle.verify_native_input_capsules(payload), capsules)
        legacy = deepcopy(payload); legacy.pop('native_input_capsules')
        self.assertEqual(set(payload['summary']), {'contexts', 'generated_forecasts', 'reused_baseline_forecasts'})
        def scrub(value):
            if type(value) is dict:
                return {k: scrub(v) for k, v in value.items() if k != 'original_json_sha256'}
            return [scrub(v) for v in value] if type(value) is list else value
        self.assertEqual(scrub(self.project(payload)), scrub(self.project(legacy)))
        self.assertNotIn('native_inputs', str(payload['summary']))

    def test_payload_hash_model_mapping_and_dispatch_digest_tampering_are_rejected(self):
        original = self.round()
        mutations = (
            lambda c: c['native_payload_sha256'].update(shared='f'*64),
            lambda c: c['group_model_ids'].update(shared=['made-up-family']),
            lambda c: c.update(dispatch_input_sha256='e'*64),
            lambda c: c['native_inputs']['shared']['snapshot']['participants'][0].update(identity='9999'),
        )
        for mutate in mutations:
            payload = deepcopy(original); mutate(payload['native_input_capsules'][0])
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.project(payload)

    def test_rehashed_clock_roster_and_feature_tampering_still_fail_native_replay(self):
        original = self.round()
        mutations = (
            lambda s: s['race'].update(as_of='2030-04-01T18:01:00+09:00'),
            lambda s: s['race'].update(sales_cutoff_at='2030-04-01T21:00:00+09:00'),
            lambda s: s['participants'][0].update(identity='9999'),
            lambda s: s['participants'][0]['features']['ability'].update(value=.01),
        )
        for mutate in mutations:
            payload = deepcopy(original)
            mutate(payload['native_input_capsules'][0]['native_inputs']['shared']['snapshot'])
            self.rehash(payload)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.project(payload)

    def test_unavailable_groups_have_no_fabricated_native_payload_or_forecast(self):
        payload = self.round()
        native = payload['native_input_capsules'][0]['native_inputs']
        self.assertNotIn('shared_learned', native)
        self.assertNotIn('seller', native)
        self.assertNotIn('autorace_personal', native)
        late = cycle.forecast_round([source_context()], self.runtime(),
            now=NOW.replace(hour=21))
        self.assertEqual(late['summary']['generated_forecasts'], 0)
        self.assertEqual(late['native_input_capsules'][0]['native_inputs'], {})
        cycle.project_round(late, receipt(late, saved='2030-04-01T21:00:20+09:00'))

    def test_explicit_runtime_pointer_binds_actual_restored_bytes_without_creating_receipt(self):
        files = self.runtime(); pointer = self.pointer(files)
        payload = cycle.forecast_round([source_context()], files, now=NOW, runtime_pointer=pointer)
        provenance = payload['runtime_provenance']
        self.assertEqual(provenance['runtime_pointer'], pointer)
        self.assertEqual(provenance['runtime_pointer_sha256'], digest(pointer))
        self.assertEqual(provenance['runtime_cipher_sha256'], pointer['cipher_sha256'])
        self.assertNotIn('independently_verified', provenance)
        self.assertEqual(provenance['source_code_commit'], HEAD)
        self.project(payload)
        changed = deepcopy(pointer); changed['header']['files']['history.sqlite']['sha256'] = 'f'*64
        with self.assertRaises(ValueError):
            cycle.forecast_round([source_context()], files, now=NOW, runtime_pointer=changed)
        unbound = self.round()
        self.assertNotIn('runtime_pointer', unbound['runtime_provenance'])
        self.assertNotIn('runtime_cipher_sha256', unbound['runtime_provenance'])

    def test_capsules_are_bounded_and_duplicate_or_missing_partitions_are_rejected(self):
        payload = self.round()
        with patch.object(cycle, 'MAX_NATIVE_CAPSULE_BYTES', 1), self.assertRaises(ValueError):
            self.project(payload)
        with patch.object(cycle, 'MAX_NATIVE_GROUP_BYTES', 1), self.assertRaises(ValueError):
            self.project(payload)
        payload['native_input_capsules'].append(deepcopy(payload['native_input_capsules'][0]))
        with self.assertRaises(ValueError):
            self.project(payload)

    def test_exact_capsules_survive_owner_encryption_without_plaintext_publication(self):
        from race_ai.boat_all_model_store import seal_forecasts, open_forecasts
        payload = self.round(fitted=True)
        key = bytes(range(32))  # Deliberately public fixture-only key.
        cipher = seal_forecasts(payload, run_id='42', round_no=1, key=key)
        self.assertNotIn(b'native_input_capsules', cipher)
        self.assertNotIn(b'native_inputs', cipher)
        restored = open_forecasts(cipher, key=key)
        self.assertEqual(restored, payload)
        self.assertEqual(cycle.verify_native_input_capsules(restored), payload['native_input_capsules'])

    def test_replay_uses_exact_saved_authorizer_scope_without_payload_self_authorization(self):
        payload = self.round()
        capsule = payload['native_input_capsules'][0]
        capsule['analysis_source_refs'] = []
        self.rehash(payload)
        with self.assertRaises(ValueError):
            self.project(payload)

    def test_p0_freezes_exact_new_common_inputs_without_rewriting_source_clocks(self):
        from tests.test_frozen_day_cycle import sample
        document, _, _ = sample()
        from datetime import datetime
        now = datetime.fromisoformat('2030-04-01T01:44:00+00:00')
        prior = receipt(document, artifact=99, saved='2030-04-01T01:43:00Z')
        payload = cycle.forecast_saved_p0(document, prior, self.runtime(fitted=True), now=now)
        capsule = payload['native_input_capsules'][0]
        self.assertEqual(capsule['stage'], 'P0')
        self.assertEqual(capsule['native_inputs']['shared']['snapshot']['race']['as_of'], now.isoformat())
        self.assertEqual(cycle.verify_native_input_capsules(payload), payload['native_input_capsules'])
        current = receipt(payload, saved='2030-04-01T01:44:05Z')
        self.assertTrue(cycle.project_round(payload, current)['independent_receipts_verified'])


if __name__ == '__main__':
    unittest.main()
