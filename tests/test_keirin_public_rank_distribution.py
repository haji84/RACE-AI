import base64
from copy import deepcopy
from hashlib import sha256
from itertools import permutations
import json
from math import fsum
import unittest
from unittest.mock import patch

from race_ai import keirin_public_rank_distribution as public
from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_joint_forecast import build_forecast, public_projection
from race_ai.keirin_nationwide_auto_generator import digest
from scripts import keirin_joint_original_readback as reader
from tests import test_keirin_joint_recovery_score as recovered
from tests.test_keirin_joint_original_readback import file_record


DAY = '2026-11-25'
RACE = '202611256104'
CUTOFF = DAY + 'T22:04:00+09:00'
GENERATED = DAY + 'T12:59:58+00:00'
FROZEN = DAY + 'T12:59:59+00:00'
WITNESSED = DAY + 'T13:03:07+00:00'


def fixture(cars=(1, 3, 4, 7, 9)):
    orders = list(permutations(cars, 3))
    weights = [1 + (order[0] % 4) for order in orders]
    law = JointFinish(cars, dict(zip(orders, [w / sum(weights) for w in weights])), tail=(.15, -.5))
    rider_rows = [dict(car=c, name=f'架空 選手{c}', registration=f'0151{c:02d}') for c in cars]
    forecast = build_forecast(law, race_id=RACE, generated_at=GENERATED,
        cutoff_at=CUTOFF, source_as_of=DAY + 'T12:57:00+00:00',
        source_forecast_generated_at=GENERATED, model_id=public.MODEL_ID, model_version='c' * 64,
        input_sha256='a' * 64, source_packet_sha256='b' * 64, riders=rider_rows)
    roster = dict(race_id=RACE, cutoff_at=CUTOFF, riders=[
        dict(number=rider['car'], name=rider['name'].replace(' ', ''),
             registration=rider['registration']) for rider in reversed(rider_rows)])
    return forecast, roster


def project(record, roster, **changes):
    binding = dict(roster=roster, expected_joint_sha256=digest(record), frozen_at=FROZEN,
                   witnessed_at=WITNESSED)
    binding.update(changes)
    return public.project_rank_race(record, **binding)


class PublicRankDistributionTests(unittest.TestCase):
    def test_projection_has_complete_ordered_marginals_and_only_public_identity(self):
        for cars in ((1, 3, 4, 7, 9), range(1, 10)):
            record, roster = fixture(cars)
            record['private_source'] = 'secret marker'
            record['riders'][0]['private_observations'] = ['secret marker']
            before = deepcopy(record)
            actual = project(record, roster)
            self.assertEqual(record, before)
            self.assertEqual(actual['scope'], 'PROSPECTIVE_RESEARCH')
            self.assertEqual(actual['calibration_status'], 'UNVALIDATED')
            self.assertEqual(actual['premise'], 'ALL_FINISH_NO_TIES')
            self.assertNotIn('secret marker', repr(actual))
            self.assertTrue({'trifectas', 'exactas', 'ranked_markets', 'input_sha256'}.isdisjoint(actual))
            self.assertEqual([r['number'] for r in actual['riders']], list(cars))
            for row, original in zip(actual['riders'], record['riders'], strict=True):
                self.assertEqual(row['probabilities'], original['rank_probabilities'])
                self.assertNotIn(' ', row['name'])
                self.assertAlmostEqual(fsum(row['probabilities']), 1.)
            for column in zip(*(r['probabilities'] for r in actual['riders']), strict=True):
                self.assertAlmostEqual(fsum(column), 1.)

    def test_projection_holds_a_stale_roster_or_missing_original_witness(self):
        record, roster = fixture()
        for change in (
            {'expected_joint_sha256': 'f' * 64},
            {'frozen_at': DAY + 'T12:00:00+00:00'},
            {'witnessed_at': CUTOFF},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'KEIRIN_PUBLIC_RANK_'):
                project(record, roster, **change)
        for field, value in (('number', 2), ('name', '別の選手'), ('registration', '017171')):
            mismatch = deepcopy(roster)
            mismatch['riders'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'KEIRIN_PUBLIC_RANK_'):
                project(record, mismatch)
        with self.assertRaisesRegex(ValueError, 'KEIRIN_PUBLIC_RANK_'):
            project(record, {**roster, 'cutoff_at': DAY + 'T22:03:00+09:00'})

    def test_public_payload_validator_rejects_column_error_duplicates_and_future_witness(self):
        record, roster = fixture()
        projected = project(record, roster)
        body = dict(schema=public.SCHEMA, day=DAY, published_at=DAY + 'T23:00:00+09:00', races=[projected])
        self.assertEqual(public.checked_day(body), body)
        changed = deepcopy(body)
        row = changed['races'][0]['riders'][0]['probabilities']
        row[0] += .04
        row[1] -= .04
        self.assertAlmostEqual(sum(row), 1.)
        with self.assertRaisesRegex(ValueError, 'KEIRIN_PUBLIC_RANK_'):
            public.checked_day(changed)
        for altered in ({**body, 'races': [projected, projected]},
                        {**body, 'published_at': DAY + 'T13:01:00+00:00'},
                        {**body, 'races': [{**projected, 'calibration_status': 'VERIFIED'}]}):
            with self.assertRaisesRegex(ValueError, 'KEIRIN_PUBLIC_RANK_'):
                public.checked_day(altered)

    def test_recovery_uses_real_structural_verifier_and_releases_only_bound_row(self):
        recover = recovered.JointRecoveryScoreTests()
        recover.setUp()
        prefix = 'data/' + DAY + '/'
        files = recover.note['files']
        item = json.loads(files[prefix + 'comparison_inputs.json']['text'])['races'][0]
        record, roster = fixture()
        item['roster'] = [{k: r[k] for k in ('car', 'name', 'registration')} for r in record['riders']]
        item['input']['riders'] = [dict(car=car) for car in record['cars']]
        item['input']['line_groups'] = [record['cars']]
        files[prefix + 'comparison_inputs.json'] = file_record(dict(races=[item]))
        rid = item['race_id']
        record.update(race_id=rid, cutoff_at=item['cutoff_at'], source_as_of=item['source_as_of'],
                      generated_at=item['forecast_generated_at'],
                      source_forecast_generated_at=item['forecast_generated_at'],
                      model_version=recover.note['model_sha256'],
                      input_sha256=digest(item['input']),
                      source_packet_sha256=files[prefix + 'comparison_inputs.json']['sha256'])
        before = dict(record, model_id='comparison-B-before-saved')
        files[prefix + 'comparison_baselines.json'] = file_record(dict(races=[before]))
        files[prefix + 'comparison_joint_originals.json'] = file_record(dict(races=[record]))
        files[prefix + 'joint_forecasts.json'] = file_record(dict(races=[public_projection(record)]))
        roster.update(race_id=rid, cutoff_at=record['cutoff_at'])
        files[prefix + 'races.json'] = file_record(dict(races=[dict(race_id=rid,
            cutoff=record['cutoff_at'], lines=item['input']['line_groups'],
            riders=[dict(number=r['car'], name=r['name']) for r in record['riders']])]))
        raw = recovered.canonical(recover.note)
        note_hash = sha256(raw).hexdigest()
        recover.publication.update(races=1, race_ids=[rid], cutoffs={rid: record['cutoff_at']},
                                   original_note_sha256=note_hash)
        recover.witness.update(registered_comparison_races=1, still_pre_cutoff_races=1)
        recover.receipt['original_note_sha256'] = note_hash
        recover.payload.update(original_note_sha256=note_hash, original_note_b64=base64.b64encode(raw).decode())
        recover.payload['safe_report']['original_header']['source_content_sha256'] = note_hash

        def publish(cipher=recover.cipher):
            return public.project_recovered_day(cipher, recover.private, recovered.canonical(recover.receipt),
                recovered.canonical(recover.publication), recovered.canonical(recover.witness), [roster],
                published_at=DAY + 'T23:31:00+09:00')

        with patch.object(reader.history, 'decrypt_evidence', return_value=recover.payload):
            packet = publish()
            self.assertEqual([r['race_id'] for r in packet['races']], [rid])
            self.assertEqual(packet['races'][0]['source_joint_sha256'], digest(record))
            self.assertNotIn('private-entropy', repr(packet))
            with self.assertRaisesRegex(ValueError, 'RECOVERY_OR_PROJECTION_HELD'):
                publish(recover.cipher + b' tampered')
