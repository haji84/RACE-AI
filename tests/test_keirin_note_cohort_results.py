from copy import deepcopy
import unittest

from race_ai import keirin_note_cohort_results as reader
from scripts import keirin_note_collect_results as native


DAY = '2030-01-15'
RACE = '203001159801'
OTHER = '203001159802'
MISSING = '203001159803'
PRE_RACE = '2030-01-15T02:50:00Z'
ACTUAL_CUTOFF = '2030-01-15T03:00:00Z'
CAPTURE = '2030-01-15T03:09:00Z'
REVISION = '2030-01-15T03:40:00Z'
READBACK = '2030-01-15T04:00:00Z'


def observation(race=RACE, *, status=native.MATCHED, capture=CAPTURE,
                observed='2030-01-15T03:06:00Z', previous=None, winner=None):
    receipts = [
        {'provider': 'Kdreams', 'source_bytes_sha256': 'a' * 64, 'observed_at': observed,
         'source_url': f'https://keirin.kdreams.jp/fictional/racedetail/98203001150100{race[-2:]}/?pageType=result'},
        {'provider': 'netkeirin', 'source_bytes_sha256': 'b' * 64, 'observed_at': observed,
         'source_url': f'https://keirin.netkeiba.com/race/result/?race_id={race}'},
    ]
    result = native._held(race, status, receipts)
    if status == native.MATCHED:
        result.update(winning_triple=winner or [3, 1, 2], payout_per_100yen=1200)
    result.update(captured_at=capture, previous_observation_sha256=previous,
                  observation_sha256=native.fact_digest(result))
    return result


def packet(*rows):
    return {'schema': native.SCHEMA, 'day_jst': DAY, 'observations': list(rows)}


def readback(*packets):
    checks = {}
    for doc in packets:
        for row in doc['observations']:
            checks[row['race_id']] = {'checked_at': row['captured_at'],
                                     'digest': row['observation_sha256'],
                                     'status': native._status(row)}
    return {'schema': reader.SCHEMA, 'date': DAY, 'checked_at': READBACK,
            'packets': list(packets), 'result_checks': checks}


class NoteCohortResultTests(unittest.TestCase):
    def setUp(self):
        self.registered = {race: {'cutoff_at': PRE_RACE, 'starter_cars': [1, 2, 3, 4, 5, 6, 7],
                                  'result_cutoff_at': ACTUAL_CUTOFF}
                           for race in (RACE, MISSING)}

    def admit(self, envelope):
        return reader.admit(envelope, day=DAY, registered=self.registered)

    def test_scores_only_registered_two_source_trifecta_with_actual_cutoff(self):
        doc, winners, checked = self.admit(readback(packet(observation(), observation(OTHER))))
        self.assertEqual(doc, {RACE: {'state': 'matched'}})
        self.assertEqual(winners, {RACE: [3, 1, 2]})
        self.assertEqual(checked, READBACK)

    def test_missing_actual_cutoff_keeps_observation_out_of_scoring(self):
        del self.registered[RACE]['result_cutoff_at']
        doc, winners, _ = self.admit(readback(packet(observation())))
        self.assertEqual(doc[RACE], {'state': 'held', 'reason': 'independent_roster_or_cutoff_unverified'})
        self.assertEqual(winners, {})

    def test_normalizes_pending_and_special_separately_with_missing_absent(self):
        row = observation(status='HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL')
        pending = observation(MISSING, status='PENDING_RESULT_NOT_FINAL')
        doc, winners, _ = self.admit(readback(packet(row, pending)))
        self.assertEqual(doc, {RACE: {'state': 'held', 'reason': 'special_refund_or_tie_requires_official'},
                               MISSING: {'state': 'pending'}})
        self.assertEqual(winners, {})

    def test_result_revision_withdraws_previous_match(self):
        first = observation()
        second = observation(status='HOLD_SECONDARY_RESULT_DISAGREEMENT', capture=REVISION,
                             previous=first['observation_sha256'])
        envelope = readback(packet(first), packet(second))
        doc, winners, _ = self.admit(envelope)
        self.assertEqual(doc[RACE], {'state': 'held', 'reason': 'secondary_result_disagreement'})
        self.assertEqual(winners, {})
        self.assertEqual(envelope['packets'][0]['observations'][0], first)

    def test_rejects_missing_predecessor_and_duplicate_in_one_packet(self):
        first = observation()
        second = observation(status='HOLD_SECONDARY_RESULT_DISAGREEMENT', capture=REVISION,
                             previous=first['observation_sha256'])
        for bad in (readback(packet(second)), readback(packet(first, second)),
                    readback(packet(second), packet(first))):
            with self.subTest(bad=len(bad['packets'])), self.assertRaises(ValueError):
                self.admit(bad)

    def test_rejects_mismatched_or_missing_final_index_check(self):
        good = readback(packet(observation()))
        for key, value in (('digest', 'f' * 64), ('status', 'PENDING'),
                           ('checked_at', '2030-01-15T03:01:00Z'),
                           ('checked_at', '2030-01-15T04:00:01Z')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                bad = deepcopy(good)
                bad['result_checks'][RACE][key] = value
                self.admit(bad)
        bad = deepcopy(good)
        bad['packets'].clear()
        with self.assertRaises(ValueError):
            self.admit(bad)

    def test_holds_result_receipt_between_conservative_and_actual_cutoffs(self):
        row = observation()
        row['provider_receipts'][0]['observed_at'] = '2030-01-15T02:59:59Z'
        outcomes, winners, _ = self.admit(readback(packet(row)))
        self.assertEqual(outcomes[RACE], {'state':'held','reason':'source_observed_before_result_cutoff'})
        self.assertFalse(winners)

    def test_holds_changed_winner_outside_registered_field(self):
        outcomes, winners, _ = self.admit(readback(packet(observation(winner=[3, 1, 8]))))
        self.assertEqual(outcomes[RACE], {'state':'held','reason':'winner_outside_registered_starters'})
        self.assertFalse(winners)

    def test_rejects_unbound_source_or_made_up_formal_status(self):
        good = readback(packet(observation()))
        wrong_id = deepcopy(good)
        wrong_id['packets'][0]['observations'][0]['provider_receipts'][1]['source_url'] += '0'
        mislabelled = deepcopy(good)
        mislabelled['packets'][0]['observations'][0]['qualifies_for_formal_settlement'] = True
        missing_source = deepcopy(good)
        missing_source['packets'][0]['observations'][0]['provider_receipts'].pop()
        for bad in (wrong_id, mislabelled, missing_source):
            with self.subTest(bad=bad['packets'][0]['observations'][0]), self.assertRaises(ValueError):
                self.admit(bad)


if __name__ == '__main__':
    unittest.main()
