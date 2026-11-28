"""Synthetic official projection, encrypted candidate and paired shadow."""
from copy import deepcopy
from hashlib import sha256
import json
from unittest import TestCase
from unittest.mock import patch

from research.chatgpt_dt_r1 import back_candidate, back_official_shadow, retained_back_readback
from research.chatgpt_dt_r1.data import input_digest
from research.chatgpt_dt_r1.model import digest
from research.chatgpt_dt_r1.pipeline import write_private_json
from research.chatgpt_dt_r1 import test_back_candidate as back_fixture
from research.chatgpt_dt_r1 import test_official_inputs as official_fixture


class BackOfficialShadowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        back_fixture.BackCandidateTests.setUpClass()

    def setUp(self):
        candidate = back_fixture.BackCandidateTests()
        candidate.setUp()
        self.addCleanup(candidate.doCleanups)
        self.candidate = candidate
        artifact = candidate.candidate
        leader = artifact['leader']
        leader['weights'][leader['feature_names'].index('points_relative')] = 1.3
        conditional = artifact['conditional']
        conditional['weights'][0][conditional['feature_names'].index('scenario_B_self')] = 1.7
        conditional['model_sha256'] = digest({k: v for k, v in conditional.items() if k != 'model_sha256'})
        candidate.pin = candidate.rewrite(artifact)
        candidate.report['artifact_sha256'] = artifact['artifact_sha256']
        (candidate.study / 'aggregate.json').unlink()
        write_private_json(candidate.study / 'aggregate.json', candidate.report)
        directory, _ = candidate.export()
        self.root = candidate.root / 'owner'
        self.root.mkdir(mode=0o700)
        self.receipt_path = candidate.root / 'retained.json'
        files = {name: (directory / filename).read_bytes()
                 for name, filename in retained_back_readback.NAMES.items()}
        members = {name: dict(file=retained_back_readback.NAMES[name], bytes=len(raw),
                             sha256=sha256(raw).hexdigest()) for name, raw in files.items()}
        self.receipt = dict(schema=retained_back_readback.RECEIPT_SCHEMA,
            repository=retained_back_readback.REPOSITORY, archive_commit='a' * 40,
            source_code_commit='b' * 40, source_code_sha256=back_candidate._source_pins(),
            path='research/chatgpt-dt-r1/synthetic/' + members['manifest']['sha256'],
            candidate_bytes_sha256=candidate.pin, artifact_sha256=candidate.candidate['artifact_sha256'],
            dataset_sha256=candidate.candidate['source_dataset_sha256'], **members)
        self.receipt_path.write_text(json.dumps(self.receipt))
        fetch = patch.object(retained_back_readback, 'fetch_exact',
                             side_effect=lambda receipt, name: files[name])
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)
        self.official = official_fixture.OfficialInputTests()
        self.official.setUp()
        self.target = self.official.project()
        self.history = self.official.history(self.target)
        self.arguments = dict(payload=self.official.payload, original=self.official.original,
            prediction_at=self.official.at, source_verifier=self.official.verifier,
            history_records=[self.history], history_verifier=self.official.verifier)

    def restored(self):
        return back_official_shadow.restored_candidate(
            self.receipt_path, self.root, owner_private_pem=self.candidate.secret)

    def test_restored_pair_has_common_bindings_and_json_stable_rank_laws(self):
        with self.restored() as forecast:
            result = forecast(**self.arguments)
            cold = forecast(**dict(self.arguments, history_records=[]))
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['input_sha256'], self.target['input_sha256'])
        self.assertEqual(result['prediction_at'], self.official.at)
        self.assertEqual(result['cutoff_at'], self.target['cutoff_at'])
        self.assertEqual(result['source_attestation_sha256'], self.target['source_attestation_sha256'])
        self.assertEqual(result['history']['history_races'], 1)
        self.assertTrue(result['history']['verification_receipt_sha256'])
        self.assertEqual(result['candidate']['candidate_bytes_sha256'], self.candidate.pin)
        self.assertEqual(result['candidate']['receipt_file_sha256'],
                         sha256(self.receipt_path.read_bytes()).hexdigest())
        self.assertNotEqual(result['feature_input_sha256'], cold['feature_input_sha256'])
        self.assertEqual(result['input_sha256'], cold['input_sha256'])
        self.assertFalse(result['independent_forecast_readback'])
        self.assertEqual(set(result['arms']), {'back_mixture', 'direct'})
        mixture = result['arms']['back_mixture']
        direct = result['arms']['direct']
        self.assertEqual(mixture['model_sha256'], self.candidate.candidate['artifact_sha256'])
        self.assertEqual(direct['model_sha256'], self.candidate.candidate['direct']['model_sha256'])
        self.assertNotEqual(mixture['trifectas'], direct['trifectas'])
        for arm in result['arms'].values():
            self.assertEqual(arm['trifecta_top12'], [t['cars'] for t in arm['trifectas'][:12]])
            self.assertEqual(arm['exacta_top2'], [t['cars'] for t in arm['exactas'][:2]])
            self.assertAlmostEqual(sum(t['probability'] for t in arm['trifectas']), 1.)
            for rider in arm['riders']:
                self.assertAlmostEqual(sum(rider['rank_probabilities']), 1.)
                for rank in range(3):
                    probability = sum(t['probability'] for t in arm['trifectas']
                                      if t['cars'][rank] == rider['car'])
                    self.assertAlmostEqual(probability, rider['rank_probabilities'][rank])
        back = result['back_leader_estimate']
        self.assertFalse(back['observed'])
        self.assertEqual([x['car'] for x in back['probabilities']], sorted(r['car'] for r in self.target['riders']))
        self.assertAlmostEqual(sum(x['probability'] for x in back['probabilities']), 1.)

    def test_target_labels_are_inert_and_unverified_evidence_fails_closed(self):
        changed = deepcopy(self.official.original)
        changed.update(result_rows=[dict(car=7, rank=1, sb_mark='B')], top3=[7, 6, 5],
                       official_result={'winner': 7})
        future = deepcopy(self.history)
        future['result_at'] = '2030-01-15T02:02:00+00:00'
        future['input_sha256'] = input_digest(future)
        with self.restored() as forecast:
            self.assertEqual(forecast(**self.arguments),
                             forecast(**dict(self.arguments, original=changed)))
            with self.assertRaisesRegex(ValueError, 'HISTORY_AVAILABILITY_CLOCK'):
                forecast(**dict(self.arguments, history_records=[future]))
            with self.assertRaises(ValueError):
                forecast(**dict(self.arguments, history_verifier=lambda payload: True))
            with self.assertRaises(ValueError):
                forecast(**dict(self.arguments, source_verifier=lambda payload: True))
            with self.assertRaises(ValueError):
                forecast(**dict(self.arguments, prediction_at=self.target['cutoff_at']))

    def test_invalid_candidate_pin_blocks_inference_and_leaves_no_plaintext(self):
        self.receipt['candidate_bytes_sha256'] = '0' * 64
        self.receipt_path.write_text(json.dumps(self.receipt))
        with self.assertRaisesRegex(ValueError, 'RETAINED_B_RECEIPT_BINDING'):
            with self.restored():
                self.fail('Mismatched retained candidate must not reach inference')
        self.assertEqual(list(self.root.iterdir()), [])
