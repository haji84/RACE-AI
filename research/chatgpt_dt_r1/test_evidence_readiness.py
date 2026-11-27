"""Aggregate readiness diagnostics must never admit evidence or reveal originals."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.chatgpt_dt_r1.test_abilities import motion_fixture


CLOCK = '2026-07-05T00:00:00Z'


def target(race_id='private-target', day='2026-07-03', *, registration='1'):
    rider = {'car': 1, 'identity_key': '1', 'identity_usable': True}
    if registration is not None:
        rider['official_registration_id'] = registration
    return {'race_id': race_id, 'day': day, 'venue_code': 'v', 'riders': [rider],
            'cohort': 'prospective'}


def phase(**changes):
    row = {'race_id': 'private-target', 'phase': 'INITIAL', 'order': [1], 'complete': True,
           'receipt': {'private_receipt': 'never-print-this'},
           'provenance': {'kind': 'reviewed_video', 'source_url': 'urn:private:phase-source',
                          'source_sha256': 'a' * 64, 'retrieved_at': '2026-07-02T00:00:00Z',
                          'reviewed_at': '2026-07-02T01:00:00Z', 'reviewer_id': 'private-reviewer',
                          'available_at': '2026-07-02T01:00:00Z'}}
    row.update(changes)
    return row


class EvidenceReadinessTests(unittest.TestCase):
    def test_cli_partial_public_checkpoints_remain_unadmitted_and_private_values_never_print(self):
        document = {'observed_race_count': 1, 'races': [
            {'race_id': 'private-race-id', 'B_leader_registration': 'private-registration',
             'source_page': 'https://example.invalid/private-query?token=do-not-print',
             'checkpoints': [{'phase': 'back', 'first_car': 1, 'second_car': 2},
                             {'phase': 'corner', 'first_car': 2}]}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'public.json'
            path.write_text(json.dumps(document))
            process = subprocess.run([sys.executable, '-m', 'research.chatgpt_dt_r1.evidence_readiness',
                                      '--public-observations', str(path), '--as-of', CLOCK],
                                     capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['public_observations']['races'], 1)
        self.assertEqual(result['public_observations']['checkpoints'], 2)
        self.assertEqual(result['public_observations']['missing']['complete_order'], 2)
        self.assertEqual(result['public_observations']['missing']['reviewed_at'], 2)
        self.assertEqual(result['public_observations']['usable_as_complete_phase_labels'], 0)
        self.assertFalse(result['independent_source_authentication'])
        for private in ('private-race-id', 'private-registration', 'do-not-print', 'example.invalid'):
            self.assertNotIn(private, process.stdout + process.stderr)

    def test_motion_uses_existing_registration_clock_and_integrity_gates(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        valid = motion_fixture()
        changed = copy.deepcopy(valid)
        changed['metrics']['mean_speed_m_s'] = 30.
        late_provenance = dict(valid['provenance'], retrieved_at='2026-07-13T00:00:00Z',
                               reviewed_at='2026-07-13T01:00:00Z', available_at='2026-07-13T01:00:00Z')
        late = motion_fixture(race_id='another-old-race', provenance=late_provenance)
        result = inspect_evidence(targets=[target(), target('no-registration', registration=None),
                                           target('same-day', '2026-07-01')],
                                  motion_records=[valid, changed, late], as_of=CLOCK)
        self.assertEqual(result['identity']['rider_targets'], 3)
        self.assertEqual(result['identity']['missing_official_registration'], 1)
        self.assertEqual(result['motion']['schema_valid'], 2)
        self.assertEqual(result['motion']['schema_rejected'], 1)
        self.assertEqual(result['motion']['unavailable_by_as_of'], 1)
        self.assertEqual(result['motion']['target_races_with_history'], 1)
        self.assertEqual(result['motion']['rider_targets_with_history'], 1)
        self.assertEqual(result['motion']['joined_observation_uses'], 1)
        self.assertFalse(result['independent_source_authentication'])

    def test_duplicate_motion_cannot_inflate_ready_history_counts(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        record = motion_fixture()
        result = inspect_evidence(targets=[target()], motion_records=[record, record], as_of=CLOCK)
        self.assertEqual(result['motion']['duplicate_race_rider_groups'], 1)
        self.assertFalse(result['motion']['joint_schema_valid'])
        self.assertEqual(result['motion']['rider_targets_with_history'], 0)

    def test_phase_diagnostics_use_schema_without_certifying_or_converting_partial_orders(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        ai = phase(phase='BELL', provenance=dict(phase()['provenance'], kind='ai_estimate'))
        broken = phase(phase='FINAL_HOME')
        broken['provenance'].pop('reviewed_at')
        result = inspect_evidence(targets=[target()],
                                  phase_observations=[phase(), phase(), ai, broken], as_of=CLOCK)
        self.assertEqual(result['phases']['schema_valid'], 3)
        self.assertEqual(result['phases']['schema_rejected'], 1)
        self.assertEqual(result['phases']['duplicate_race_phase_groups'], 1)
        self.assertEqual(result['phases']['unreviewed_source'], 1)
        self.assertEqual(result['phases']['missing_provenance']['reviewed_at'], 1)
        self.assertEqual(result['phases']['training_admission'], 'NOT_PERFORMED')
        self.assertNotIn('private-target', json.dumps(result))
        self.assertNotIn('private-reviewer', json.dumps(result))

    def test_weather_delegates_same_day_future_and_numeric_checks(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        weather = {'kind': 'observation', 'source_sha256': 'a' * 64,
                   'issued_at': '2026-07-02T00:00:00Z', 'available_at': '2026-07-02T01:00:00Z',
                   'observed_at': '2026-07-02T00:00:00Z', 'wind_speed_m_s': 2.}
        valid = dict(target(), weather_observation=weather)
        future = dict(target('future'), weather_observation=dict(weather,
                      available_at='2026-07-13T00:00:00Z'))
        same_day = dict(target('archive', '2026-07-02'), cohort='retrospective', weather_observation=weather)
        result = inspect_evidence(targets=[valid, future, same_day, target('missing')], as_of=CLOCK)
        self.assertEqual(result['weather']['source_clock_schema_accepted'], 1)
        self.assertEqual(result['weather']['with_usable_numeric_values'], 1)
        self.assertEqual(result['weather']['rejected_by_existing_filter'], 2)
        self.assertEqual(result['weather']['missing'], 1)

    def test_cli_invalid_json_does_not_echo_private_document_or_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private-person-name.json'
            path.write_text('{"secret-raw-source":')
            process = subprocess.run([sys.executable, '-m', 'research.chatgpt_dt_r1.evidence_readiness',
                                      '--targets', str(path), '--as-of', CLOCK],
                                     capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        result = json.loads(process.stdout)
        self.assertEqual(result['status'], 'HOLD_INVALID_INPUT')
        self.assertNotIn('secret-raw-source', process.stdout + process.stderr)
        self.assertNotIn('private-person-name', process.stdout + process.stderr)

    def test_public_starters_are_counted_without_inventing_bound_model_inputs(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        starters = {'schema': 'public-projection', 'day': '2026-07-03', 'races': [
            {'race_id': 'private-public-race', 'source_at': '2026-07-02T00:00:00Z',
             'riders': [{'number': 1, 'name': 'private-name', 'registration': 'private-reg'},
                        {'number': 2, 'name': 'another-private-name', 'registration': None}]}]}
        result = inspect_evidence(as_of=CLOCK, public_starters=starters)
        self.assertEqual(result['public_starters']['races'], 1)
        self.assertEqual(result['public_starters']['rider_entries'], 2)
        self.assertEqual(result['public_starters']['registration_present'], 1)
        self.assertEqual(result['public_starters']['registration_missing'], 1)
        self.assertEqual(result['identity']['target_races'], 0)
        self.assertFalse(result['public_starters']['normalized_input_created'])
        self.assertNotIn('private-reg', json.dumps(result))

    def test_frozen_model_metadata_checks_integrity_and_counts_motion_without_claiming_observations(self):
        from research.chatgpt_dt_r1.evidence_readiness import inspect_evidence
        from research.chatgpt_dt_r1.model import RankModel
        model = RankModel.zero(('history_dt_motion_overall_mean_speed_m_s_mean',
                                'history_dt_motion_overall_mean_speed_m_s_missing', 'points'))
        model.weights[0, 2] = .5
        artifact = model.to_dict()
        result = inspect_evidence(as_of=CLOCK, frozen_model=artifact)
        self.assertEqual(result['frozen_model']['motion_feature_columns'], 2)
        self.assertEqual(result['frozen_model']['motion_columns_with_nonzero_weight'], 0)
        self.assertFalse(result['frozen_model']['timing_sidecar_declared'])
        self.assertFalse(result['frozen_model']['weather_sidecar_declared'])
        artifact['weights'][0][2] = .4
        with self.assertRaises(ValueError):
            inspect_evidence(as_of=CLOCK, frozen_model=artifact)


if __name__ == '__main__':
    unittest.main()
