import unittest

from research.chatgpt_dt_r1.historical_replay import public_matches


def card(rid, top3, cars=(1, 2, 3, 4)):
    return dict(race_id=rid, top3=top3, result_status='COMPLETE',
                riders=[dict(car=car) for car in cars])


class HistoricalReplayTests(unittest.TestCase):
    def test_result_roster_and_unique_order_must_agree(self):
        ok = (frozenset((1, 2, 3, 4)), {(1, 2, 3)})
        archive = [
            card('scored', [1, 2, 3]), card('no_published_result', [1, 2, 3]),
            card('other_starters', [1, 2, 3], cars=(1, 2, 3, 5)),
            card('multiple_orders', [1, 2, 3]), card('incomplete', None),
            card('different_result', [1, 3, 2]),
        ]
        reference = {row['race_id']: ok for row in archive if row['race_id'] != 'no_published_result'}
        reference['multiple_orders'] = (ok[0], {(1, 2, 3), (1, 3, 2)})
        matches, held = public_matches(archive, reference)
        self.assertEqual([row['race_id'] for row in matches], ['scored'])
        self.assertEqual(held, dict(no_public_result=1, different_starters=1,
                                   multiple_public_orders=1, no_unique_archive_result=1, different_order=1))


if __name__ == '__main__':
    unittest.main()
