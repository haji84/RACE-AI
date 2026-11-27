from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import unittest

from race_ai import keirin_github_origin_evidence as origin
from race_ai import keirin_learned_official_inputs as inputs
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_official_nationwide_extension as extension
from race_ai import keirin_official_nationwide_records as records
from tests import test_keirin_official_nationwide_extension as fixture


def _original(extra=b''):
    args = fixture.NationwideExtensionTests().baseline_arguments()
    now = args.pop('now')
    source = args['profile_sources'][0]
    if extra:
        source['raw_bytes'] = source['raw_bytes'].replace(b'</body>', extra + b'</body>')
        source['expected_sha256'] = sha256(source['raw_bytes']).hexdigest()
    snapshot = extension.build_baseline_candidate(**args, now=now)['snapshot']
    baseline = model.generate_A_B(snapshot, generated_at=now.isoformat())
    race_id = snapshot['race_id']
    cutoff = snapshot['published_cutoff_at']
    day = args['card_arguments']['expected_day']
    proof = dict(schema=origin.SCHEMA, state='GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED', race_id=race_id,
                 official_cutoff_at=cutoff, cipher_sha256='a' * 64,
                 latest_server_evidence_at=(now + timedelta(seconds=1)).isoformat())
    proof['evidence_sha256'] = model.digest(proof)
    original = dict(schema=records.PRE_SCHEMA, day_jst=day, race_id=race_id, baseline=baseline,
                    snapshot=snapshot, baseline_cipher_sha256='a' * 64, baseline_sealed_at=now.isoformat(),
                    origin_receipts={'baseline_origin': proof})
    payload = deepcopy(original)
    payload.pop('origin_receipts')
    payload['baseline_arguments'] = args
    return payload, original


class LearnedOfficialInputsTests(unittest.TestCase):
    def test_projects_exact_base_facts_and_counts_only_supported_inputs(self):
        payload, admitted = _original()
        projected = inputs.project(payload, admitted)
        snapshot = admitted['snapshot']
        self.assertEqual(set(projected), {'race_id', 'riders', 'line_groups', 'competition', 'meeting_grade', 'round_stage'})
        self.assertEqual(projected['line_groups'], snapshot['line_groups'])
        self.assertEqual(projected['round_stage'], 'SELECTION')
        self.assertEqual(projected['race_id'], snapshot['race_id'])
        self.assertEqual(projected['competition'], 'GIRLS')
        for actual, saved in zip(projected['riders'], snapshot['riders'], strict=True):
            self.assertEqual(actual['car'], saved['car'])
            self.assertEqual(actual['mark_rank'], 8 if saved['mark_rank'] == 'UNMARKED' else saved['mark_rank'])
            self.assertEqual(actual['points'], saved['competition_points'])
            self.assertAlmostEqual(actual['win_rate'], saved['recent_form_score'] * 100)
            self.assertEqual(actual['style'], None if saved['style'] == 'UNKNOWN' else saved['style'])
            self.assertEqual(actual['rider_class'], 'L1')
            self.assertTrue(all(actual[field] is None for field in ('age', 'top2_rate', 'top3_rate', 'gear')))
        self.assertEqual(inputs.availability(projected)['top2_rate'], 0)
        self.assertEqual(inputs.availability(projected)['rider_class'], 7)
        self.assertEqual(inputs.availability(projected)['riders'], 7)
        self.assertEqual(inputs.availability(projected)['round_stage'], 1)

    def test_only_explicit_profile_labels_supply_optional_rates_and_age(self):
        source = ('<table><tr><th>年齢</th><td>30歳</td></tr>'
                  '<tr><th>2連対率</th><td>40.5%</td></tr>'
                  '<tr><th>3連対率</th><td>61.0%</td></tr></table>').encode()
        payload, admitted = _original(extra=source)
        result = inputs.project(payload, admitted)
        self.assertEqual(inputs.availability(result)['age'], 1)
        self.assertEqual(inputs.availability(result)['top2_rate'], 1)
        self.assertEqual(inputs.availability(result)['top3_rate'], 1)
        self.assertEqual(inputs.availability(result)['gear'], 0)
        enriched, = [row for row in result['riders'] if row['age'] is not None]
        self.assertEqual((enriched['age'], enriched['top2_rate'], enriched['top3_rate']), (30, 40.5, 61.))

    def test_wrong_rider_and_tampered_sources_are_rejected(self):
        payload, admitted = _original()
        bad_rider = deepcopy(payload)
        bad_rider['baseline_arguments']['profile_sources'][0]['registration_id'] = '999998'
        bad_raw = deepcopy(payload)
        bad_raw['baseline_arguments']['profile_sources'][0]['raw_bytes'] += b' '
        bad_card = deepcopy(payload)
        bad_card['baseline_arguments']['card_arguments']['detail_raw'] += b' '
        bad_marks = deepcopy(payload)
        bad_marks['baseline_arguments']['prediction_source']['raw_bytes'] += b' '
        for changed in (bad_rider, bad_raw, bad_card, bad_marks):
            with self.subTest(changed='source'), self.assertRaises(ValueError):
                inputs.project(changed, admitted)

    def test_future_observations_and_unrelated_proof_are_rejected(self):
        payload, admitted = _original()
        change = deepcopy(payload)
        change['baseline_arguments']['profile_sources'][0]['observed_at'] = admitted['baseline']['published_cutoff_at']
        with self.assertRaises(ValueError):
            inputs.project(change, admitted)
        proof = admitted['origin_receipts']['baseline_origin']
        proof['latest_server_evidence_at'] = admitted['baseline']['published_cutoff_at']
        proof.pop('evidence_sha256')
        proof['evidence_sha256'] = model.digest(proof)
        with self.assertRaises(ValueError):
            inputs.project(payload, admitted)
