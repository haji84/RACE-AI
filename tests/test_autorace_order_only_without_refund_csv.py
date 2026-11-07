"""Authored eight-driver parser regression; no CSV, source access or real key.

These are structural source/frozen-roster checks using invented identities.
They do not authenticate a browser capture or supply a monetary payout basis.
"""
import base64
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from race_ai import autorace_official_result_adapter as parser
from race_ai.official_order_only_result import OBSERVATION_FIELDS, validate_order_only
from tests.test_autorace_official_result_adapter import (
    fixture, reseal_result, NOW, RIGHTS, wire,
)


ORDER = [3, 4, 6, 5, 7, 2, 8, 1]
ROSTER = {str(number):str(1000+number) for number in range(1, 9)}


def no_csv_fixture():
    """Keep the existing original JSON/OtherRaceInfo/DOM fixture, sans unit proof."""
    data = fixture()
    data['metadata'].pop('auto_result_archive_context')
    return data


def parse(data, *, allow_order_only=True):
    return parser.parse_result(wire(data['result']), data['metadata'],
        frozen_native_payload=data['frozen'], now=NOW, source_rights_ref=RIGHTS,
        allow_order_only=allow_order_only)


class AutoraceOrderOnlyWithoutRefundCSVTests(unittest.TestCase):
    def test_eight_normal_finishers_need_only_main_same_case_other_and_rendered_dom_for_order(self):
        data = no_csv_fixture(); before = deepcopy(data)
        context = data['metadata']['auto_result_context']
        self.assertEqual(set(context), {'schema', 'request_body_base64',
            'race_info_capture', 'rendered_dom_capture'})
        self.assertNotIn('/data/refund/', json.dumps(data['metadata']))
        self.assertNotIn('RaceRefund', json.dumps(data['metadata']))
        facts = parser.parse_official_result_source(wire(data['result']), data['metadata'],
            now=NOW, source_rights_ref=RIGHTS, allow_order_only=True)
        self.assertEqual(facts['roster'], ROSTER)
        self.assertEqual([row['finish'] for row in facts['finish_rows']], list(range(1, 9)))
        self.assertEqual([row['number'] for row in facts['finish_rows']], ORDER)
        self.assertEqual(len(facts['finish_rows']), 8)
        self.assertFalse(facts['future_frozen_input_paired'])
        self.assertNotIn('payout_unit_basis', facts)
        observation = parse(data)
        self.assertEqual(set(observation), OBSERVATION_FIELDS)
        self.assertEqual(observation['status'], 'rank_confirmed')
        self.assertEqual(observation['ordered_top3'], ORDER[:3])
        self.assertEqual(observation['roster'], ROSTER)
        self.assertTrue(observation['identity_verified'])
        self.assertEqual(observation['published_payout_yen'], 21710)
        self.assertIsNone(observation['payout_per_100_yen'])
        self.assertIs(observation['payout_unit_verified'], False)
        self.assertEqual(observation['evaluation_scope'], 'ORDER_ONLY_NO_MONETARY_EVALUATION')
        self.assertEqual(validate_order_only(observation, sport='autorace', roster=ROSTER), observation)
        self.assertEqual(data, before, 'CSV omission must not rewrite source or native originals')

    def test_csv_omission_never_supplies_the_missing_cash_unit_proof(self):
        data = no_csv_fixture()
        with self.assertRaisesRegex(ValueError, 'PAYOUT_UNIT_CAPTURE_REQUIRED'):
            parse(data, allow_order_only=False)
        self.assertIsNone(parse(data)['payout_per_100_yen'])
        self.assertFalse(parse(data)['payout_unit_verified'])

    def test_missing_refund_info_absent_or_trifecta_schema_still_rejects(self):
        for missing in ('refundInfo', 'absent', 'rt3', 'list'):
            data = no_csv_fixture(); body = data['result']['body']
            if missing == 'refundInfo': body.pop('refundInfo')
            elif missing == 'list': body['refundInfo']['rt3'].pop('list')
            else: body['refundInfo'].pop(missing)
            reseal_result(data)
            with self.subTest(missing=missing), self.assertRaises(ValueError): parse(data)

    def test_refund_non_normal_type_accident_and_ties_remain_unscored(self):
        for kind in ('absent', 'special_payment', 'no_vote', 'wrong_name', 'missing_type',
                     'boolean_type', 'text_type', 'accident', 'retired', 'tie'):
            data = no_csv_fixture(); body = data['result']['body']; rt3 = body['refundInfo']['rt3']
            if kind == 'absent': body['refundInfo']['absent'] = [8]
            elif kind == 'special_payment': rt3.update(typeCode=1, typeName='特払い')
            elif kind == 'no_vote': rt3.update(typeCode=5, typeName='無投票')
            elif kind == 'wrong_name': rt3['typeName'] = '不明'
            elif kind == 'missing_type': rt3.pop('typeCode')
            elif kind == 'boolean_type': rt3['typeCode'] = False
            elif kind == 'text_type': rt3['typeCode'] = '0'
            elif kind == 'accident': body['raceResult'][0].update(accidentCode=1, accidentName='落')
            elif kind == 'retired': body['raceResult'][0]['retireFlag'] = 1
            else: body['raceResult'][1]['order'] = 1
            reseal_result(data)
            with self.subTest(kind=kind):
                observation = parse(data)
                self.assertEqual(observation['status'], 'special')
                self.assertEqual(observation['ordered_top3'], [])
                self.assertIsNone(observation['payout_per_100_yen'])
                self.assertNotIn('payout_unit_verified', observation)

    def test_missing_finish_or_payment_stays_pending_and_seven_of_eight_is_not_complete(self):
        for kind in ('no_results', 'no_payment', 'unconfirmed_finish'):
            data = no_csv_fixture(); body = data['result']['body']
            if kind == 'no_results': body['raceResult'] = []
            elif kind == 'no_payment': body['refundInfo']['rt3']['list'] = []
            else: body['raceResult'][-1]['order'] = None
            reseal_result(data)
            with self.subTest(kind=kind):
                observation = parse(data)
                self.assertEqual(observation['status'], 'pending')
                self.assertEqual(observation['ordered_top3'], [])
                self.assertIsNone(observation['payout_per_100_yen'])
        data = no_csv_fixture(); data['result']['body']['raceResult'].pop(); reseal_result(data)
        with self.assertRaisesRegex(ValueError, 'COMPLETE_FROZEN_RESULT_ROSTER_REQUIRED'): parse(data)

    def test_foreign_duplicate_or_changed_frozen_driver_identity_never_pairs(self):
        for kind in ('foreign_result', 'duplicate_driver', 'frozen_roster'):
            data = no_csv_fixture(); rows = data['result']['body']['raceResult']
            if kind == 'foreign_result': rows[0]['playerCode'] = 999999
            elif kind == 'duplicate_driver': rows[1]['playerCode'] = rows[0]['playerCode']
            else: data['frozen']['snapshot']['participants'][0]['identity'] = '999999'
            reseal_result(data)
            with self.subTest(kind=kind), self.assertRaises(ValueError): parse(data)

    def test_missing_or_wrong_case_companion_dom_and_future_clock_are_not_waived(self):
        for kind in ('missing_other', 'request_race', 'dom_race', 'future_main'):
            data = no_csv_fixture(); metadata = data['metadata']; context = metadata['auto_result_context']
            if kind == 'missing_other': context.pop('race_info_capture')
            elif kind == 'request_race':
                raw = wire(dict(placeCode=3, raceDate='2030-01-15', raceNo='2'))
                context['request_body_base64'] = base64.b64encode(raw).decode()
                metadata['request_body_sha256'] = sha256(raw).hexdigest()
            elif kind == 'dom_race':
                capture = context['rendered_dom_capture']
                raw = base64.b64decode(capture['raw_base64']).replace(b'1R', b'2R')
                capture['raw_base64'] = base64.b64encode(raw).decode()
                capture['metadata'].update(byte_count=len(raw), source_sha256=sha256(raw).hexdigest())
            else: metadata['response_received_at'] = '2030-01-15T12:06:00+09:00'
            with self.subTest(kind=kind), self.assertRaises(ValueError): parse(data)


if __name__ == '__main__': unittest.main()
