import unittest

from scripts import keirin_line_forward_study as study


DAY = '2026-11-24'
KEY = '202611242601'
CUTOFF = '2026-11-24T00:00:00Z'
WINNERS = [1, 2, 3]


def frame():
    ranks = {
        'current_A': {'2t': [[2, 1]], '3t': [[2, 1, 3]]},
        'current_B': {'2t': [[2, 1]], '3t': [[2, 1, 3]]},
        'published_line': {'2t': [[1, 2], [2, 1]], '3t': [WINNERS, [2, 1, 3]]},
    }
    return {'schema': study.FRAME_SCHEMA, 'date': DAY, 'sealed_at': '2026-11-23T23:30:00Z',
            'target_count': 1, 'races': [{'race_id': KEY, 'cutoff_at': CUTOFF,
                                         'starters': list(range(1, 6)), 'ranks': ranks}]}


def results(state='matched', observed_at='2026-11-24T00:30:00Z', winners=WINNERS):
    return {'schema': 'KEIRIN_PUBLISHED_RESULTS_V1', 'date': DAY, 'checked_at': '2026-11-24T01:00:00Z',
            'races': [{'race_id': KEY, 'state': state,
                       'comparison': {'race_id': KEY, 'authority': 'cross_source_reference',
                                      'comparison_scope': 'POST_CUTOFF_REFERENCE',
                                      'observed_at': observed_at,
                                      'winning_2t': winners[:2], 'winning_3t': winners}}]}


class ForwardLineStudyTests(unittest.TestCase):
    def test_each_method_scores_at_the_smallest_available_point_count(self):
        output = study.score(frame(), results(), witnessed_at='2026-11-23T23:35:00Z')
        self.assertEqual(output['matched'], 1)
        self.assertEqual(output['metrics']['3t']['8']['points_per_method'], 1)
        self.assertEqual(output['metrics']['3t']['8']['hits'],
                         {'current_A': 0, 'current_B': 0, 'published_line': 1})
        self.assertEqual(output['metrics']['2t']['2']['new_hits_vs_B'], 1)

    def test_at_cutoff_or_unsettled_is_retained_without_a_score(self):
        late = study.score(frame(), results(), witnessed_at=CUTOFF)
        self.assertEqual((late['eligible'], late['matched'], late['witness_at_or_after_cutoff']), (0, 0, 1))
        held = study.score(frame(), results('held'), witnessed_at='2026-11-23T23:35:00Z')
        self.assertEqual((held['eligible'], held['matched'], held['result_states']['held']), (1, 0, 1))

    def test_before_cutoff_result_or_unknown_winner_requires_review(self):
        before = study.score(frame(), results(observed_at='2026-11-23T23:59:00Z'),
                             witnessed_at='2026-11-23T23:35:00Z')
        self.assertEqual((before['matched'], before['result_states']['invalid_timing']), (0, 1))
        other = study.score(frame(), results(winners=[1, 2, 6]), witnessed_at='2026-11-23T23:35:00Z')
        self.assertEqual((other['matched'], other['result_states']['winner_outside_starters']), (0, 1))


if __name__ == '__main__':
    unittest.main()
