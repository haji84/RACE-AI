"""Invented operator intake; real scoped decisions, native fit and AES codec."""
import base64
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.all_existing_model_learning import records_from_observed
from race_ai.all_existing_model_registry import registry_sha256
from race_ai.all_existing_model_research import issue_decision, verify_decision
from race_ai.boat_observed_pairwise_models import WEIGHTS
from race_ai.boat_venue_learning import read_candidate, training_intake
from race_ai.boat_venue_research import issue_owner_research_decision
from scripts import all_existing_model_learning as cli
from tests.test_boat_venue_learning import NOW, POINTER
from tests.test_boat_venue_research import CONTENT, SOURCE, personal_data


# Public, invented-record-only test key; never used for private owner data.
FICTION_ONLY_KEY = base64.b64encode(bytes(range(32))).decode()


@contextmanager
def actual_calls(*functions):
    """Observe real calls without replacing the decision, fitter or codec."""
    counts = {function.__code__: 0 for function in functions}
    previous = sys.getprofile()
    def observe(frame, event, argument):
        if event == 'call' and frame.f_code in counts:
            counts[frame.f_code] += 1
    sys.setprofile(observe)
    try:
        yield counts
    finally:
        sys.setprofile(previous)


class AllExistingModelCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = personal_data(8)
        cls.records = records_from_observed(rows, observations)
        cls.intake = training_intake(rows, observations, dataset_pointer=POINTER)
        cls.binding = dict(source_pointer=deepcopy(SOURCE), state_content_sha256=CONTENT,
            dataset_pointer=deepcopy(POINTER), source_refs=deepcopy(cls.intake['source_refs']),
            intake_sha256=digest(cls.records), registry_sha256=registry_sha256())
        actual_refs = {(source['source_url'], source['source_rights_ref'])
            for row in cls.records for source in row['native_payload']['snapshot']['sources']}
        actual_refs.update((row['result']['source_ref'], row['result']['source_rights_ref'])
                           for row in cls.records)
        if actual_refs != {tuple(pair) for pair in cls.binding['source_refs']}:
            raise AssertionError('fixture decision must admit exactly the original input/result sources')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record_path = self.root/'owner-decision.json'
        self.output = self.root/'candidate'
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=FICTION_ONLY_KEY)
        environment.start(); self.addCleanup(environment.stop)

    def arguments(self, command):
        return [command, '--restored-dir', str(self.root/'restored'),
            '--state-input', str(self.root/'source-pointer.json'),
            '--dataset-input', str(self.root/'dataset-pointer.json'),
            '--owner-research-record', str(self.record_path), '--out-dir', str(self.output)]

    def invoke(self, command):
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(self.arguments(command), now=NOW)
        return result, json.loads(output.getvalue()), output.getvalue()

    def intake_value(self):
        return deepcopy((self.records, self.binding, self.intake))

    def write_decision(self, **changes):
        binding = deepcopy(self.binding); binding.update(changes)
        decision = issue_decision(**binding, now=NOW, expires_at=NOW+timedelta(days=30))
        self.record_path.write_text(json.dumps(decision), encoding='utf-8')
        return decision

    def test_missing_key_returns_hold_before_intake_private_io_or_model_calls(self):
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch(
                'scripts.all_existing_model_learning.load_intake',
                side_effect=AssertionError('missing key must not inspect private intake')) as load:
            with actual_calls(cli._read, cli._write, cli.fit, cli.issue_decision) as calls:
                for command in ('issue-decision', 'fit'):
                    with self.subTest(command=command):
                        result, summary, _ = self.invoke(command)
                        self.assertEqual(result, 0)
                        self.assertEqual(summary['state'], 'HOLD_OWNER_STATE_KEY_MISSING')
                        self.assertEqual((summary['model_family_count'], summary['applicable_model_cells'],
                                          summary['fitted_model_count']), (16, 31, 0))
            load.assert_not_called()
        self.assertEqual(set(calls.values()), {0})
        self.assertFalse(self.record_path.exists()); self.assertFalse(self.output.exists())

    def test_legacy_two_family_decision_is_rejected_before_fitting(self):
        old_binding = {key:value for key,value in self.binding.items()
                       if key not in ('intake_sha256', 'registry_sha256')}
        old = issue_owner_research_decision(**old_binding, now=NOW, expires_at=NOW+timedelta(days=1))
        self.record_path.write_text(json.dumps(old), encoding='utf-8')
        original = self.record_path.read_bytes()
        with patch('scripts.all_existing_model_learning.load_intake', return_value=self.intake_value()):
            with actual_calls(cli.fit, cli.issue_decision) as calls:
                result, summary, _ = self.invoke('fit')
        self.assertEqual(result, 2); self.assertEqual(summary['state'], 'HOLD_ALL_MODEL_RESEARCH')
        self.assertEqual(set(calls.values()), {0})
        self.assertEqual(self.record_path.read_bytes(), original)
        self.assertFalse(self.output.exists())

    def test_explicit_issuer_creates_one_exact_record_and_never_overwrites_or_fits(self):
        with patch('scripts.all_existing_model_learning.load_intake', return_value=self.intake_value()) as load:
            with actual_calls(cli.fit, cli.issue_decision) as calls:
                result, summary, public = self.invoke('issue-decision')
                original = self.record_path.read_bytes()
                repeat, rejected, _ = self.invoke('issue-decision')
        self.assertEqual(result, 0)
        self.assertEqual(summary['state'], 'OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED')
        self.assertEqual((summary['model_family_count'], summary['applicable_model_cells']), (16, 31))
        self.assertEqual(repeat, 2); self.assertEqual(rejected['state'], 'HOLD_ALL_MODEL_RESEARCH')
        self.assertEqual(self.record_path.read_bytes(), original)
        self.assertEqual(calls[cli.fit.__code__], 0)
        self.assertEqual(calls[cli.issue_decision.__code__], 1)
        decision = json.loads(original)
        self.assertEqual(verify_decision(decision, **self.binding, now=NOW), summary['decision_sha256'])
        self.assertEqual(self.record_path.stat().st_mode & 0o077, 0)
        self.assertEqual(load.call_args.kwargs['now'], NOW)
        self.assertFalse(self.output.exists()); self.assertNotIn('weights', public)

    def test_scoped_fit_preserves_missing_cells_and_encrypts_native_fits_without_auto_issue(self):
        decision = self.write_decision(); original = self.record_path.read_bytes()
        before = deepcopy((self.records, self.binding, self.intake, WEIGHTS))
        supplied = self.intake_value()
        with patch('scripts.all_existing_model_learning.load_intake', return_value=supplied) as load:
            with actual_calls(cli.fit, cli.issue_decision) as calls:
                result, summary, public = self.invoke('fit')
        self.assertEqual(result, 0)
        self.assertEqual(summary['state'], 'FITTED_SHADOW_ONLY')
        self.assertEqual((summary['model_family_count'], summary['applicable_model_cells'],
                          summary['fitted_model_count'], summary['fitted_family_count'],
                          summary['missing_or_unfitted_cells']), (16, 31, 2, 2, 29))
        self.assertEqual(summary['eligible_venue_races'], 8)
        self.assertIs(summary['encrypted_readback_verified'], True)
        self.assertIs(summary['provider_permission_confirmed'], False)
        self.assertIs(summary['production_promoted'], False)
        self.assertEqual(calls[cli.fit.__code__], 1)
        self.assertEqual(calls[cli.issue_decision.__code__], 0)
        self.assertEqual(self.record_path.read_bytes(), original)
        self.assertEqual((self.records, self.binding, self.intake, WEIGHTS), before)
        self.assertEqual(supplied, self.intake_value())
        load.assert_called_once_with(str(self.root/'restored'), str(self.root/'source-pointer.json'),
            str(self.root/'dataset-pointer.json'), now=NOW)
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {'learning.enc', 'learning.json', 'summary.json'})
        payload = read_candidate(self.output); training = payload['training']
        self.assertEqual(payload['owner_research_record'], decision)
        self.assertEqual(training['owner_research_decision_sha256'], digest(decision))
        self.assertEqual(len(training['model_states']), 31)
        self.assertEqual(sum(value['state'] == 'INPUT_MISSING'
                             for value in training['model_states'].values()), 29)
        for model in training['models'].values():
            self.assertEqual((model['unique_races'], model['train_races'], model['validation_races']), (8, 6, 2))
            self.assertEqual(model['native_training']['schema'], 'RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1')
        published = public.encode()+b''.join((self.output/name).read_bytes()
            for name in ('learning.json', 'summary.json'))
        for field in (b'"weights"', b'"parameters"', b'"base_parameters"', b'"participants"',
                      b'"ordered_top8"', b'"source_url"', FICTION_ONLY_KEY.encode()):
            self.assertNotIn(field, published)

    def test_fit_never_issues_a_missing_owner_record(self):
        with patch('scripts.all_existing_model_learning.load_intake', return_value=self.intake_value()):
            with actual_calls(cli.fit, cli.issue_decision) as calls:
                result, summary, _ = self.invoke('fit')
        self.assertEqual(result, 2); self.assertEqual(summary['state'], 'HOLD_ALL_MODEL_RESEARCH')
        self.assertEqual(set(calls.values()), {0})
        self.assertFalse(self.record_path.exists()); self.assertFalse(self.output.exists())

    def test_different_private_intake_hash_is_rejected_before_optimizer(self):
        self.write_decision(intake_sha256='f'*64)
        original = self.record_path.read_bytes()
        with patch('scripts.all_existing_model_learning.load_intake', return_value=self.intake_value()):
            with actual_calls(cli.fit, cli.issue_decision) as calls:
                result, summary, _ = self.invoke('fit')
        self.assertEqual(result, 2); self.assertEqual(summary['state'], 'HOLD_ALL_MODEL_RESEARCH')
        self.assertEqual(summary['reason'], 'ALL_MODEL_OWNER_RESEARCH_SCOPE_CHANGED')
        self.assertEqual(set(calls.values()), {0})
        self.assertEqual(self.record_path.read_bytes(), original)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
