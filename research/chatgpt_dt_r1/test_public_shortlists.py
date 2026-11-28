"""Checks for publishing only the requested DT-R1 candidates and clock metadata."""
from copy import deepcopy
from itertools import permutations
import unittest

from research.chatgpt_dt_r1 import public_shortlists as shortlists


RACE = '202611284606'
DAY = '2026-11-28'
CUTOFF = DAY + 'T13:24:00+09:00'
OBSERVED = DAY + 'T04:50:00+09:00'
DECISION = DAY + 'T13:17:00+09:00'
CARS = (1, 2, 3, 4, 5, 6, 7)


def sample(first_probability=None, cars=CARS):
    ordered = list(permutations(cars, 3))
    first = 1 / len(ordered) if first_probability is None else first_probability
    remainder = (1 - first) / (len(ordered) - 1)
    triples = [dict(cars=ticket, probability=first if i == 0 else remainder)
               for i, ticket in enumerate(ordered)]
    pairs = {ticket: 0. for ticket in permutations(cars, 2)}
    for triple in triples:
        pairs[triple['cars'][:2]] += triple['probability']
    return dict(model_id='chatgpt-dt-r1', model_sha256=shortlists.MODEL_SHA, input_sha256='b'*64,
                race_id=RACE, day=DAY, status='READY', cohort='retrospective',
                cutoff_at=None, prediction_at=None, field_size=len(cars),
                trifectas=[dict(row,cars=list(row['cars'])) for row in triples],
                exactas=[dict(cars=list(ticket), probability=value) for ticket,value in pairs.items()])


def choose(forecast=None, *, selected_at=DECISION, odds=None):
    return shortlists.select(sample() if forecast is None else forecast,
        cutoff_at=CUTOFF, selected_at=selected_at, source_at=OBSERVED, odds=odds)


class PublicShortlistTests(unittest.TestCase):
    def test_concentration_can_shrink_to_one_and_ties_are_deterministic(self):
        selected = choose(sample(.30))
        self.assertEqual(selected['tickets'], [[1, 2, 3]])
        self.assertEqual(selected['reason'], 'COVERAGE_REACHED')
        forecast = sample(.19)
        forecast['trifectas'].reverse()
        spread = choose(forecast)
        self.assertEqual(spread['tickets'][:2], [[1,2,3], [1,2,4]])
        self.assertGreater(len(spread['tickets']), 1)
        self.assertLess(len(spread['tickets']), 12)

    def test_dispersed_field_stops_at_twelve_and_small_roster_has_no_duplicates(self):
        result = choose()
        self.assertEqual(len(result['tickets']), 12)
        self.assertEqual(result['reason'], 'MAX_POINTS')
        small = choose(sample(cars=(1,2,3)))
        self.assertLessEqual(len(small['tickets']), 6)
        self.assertEqual(small['starter_cars'], [1,2,3])

    def test_only_pre_cutoff_observed_anchor_odds_limit_points(self):
        forecast = sample()
        odds = dict(race_id=RACE, source_at=DAY+'T12:55:00+09:00',
                    observed_at=DAY+'T12:56:00+09:00', quotes={'1-2-3':10})
        cap = choose(forecast, odds=odds)
        self.assertEqual((len(cap['tickets']), cap['reason']), (2,'ODDS_CAP'))
        self.assertEqual(len(choose(forecast, odds=dict(odds, observed_at=CUTOFF),
            selected_at=DAY+'T14:03:00+09:00')['tickets']), 12)
        self.assertEqual(len(choose(forecast, odds=dict(odds,quotes={'1-2-4':10}))['tickets']), 12)

    def test_public_schema_never_contains_distribution_or_hidden_forecast(self):
        selected = choose(selected_at=DAY+'T14:00:00+09:00')
        day = shortlists.project_day(DAY, model_sha256=shortlists.MODEL_SHA, input_commit='3'*40,
            published_at=DAY+'T14:10:00+09:00', races=[selected])
        self.assertEqual(set(day), shortlists.DAY_FIELDS)
        self.assertEqual(set(day['races'][0]), shortlists.RACE_FIELDS)
        self.assertEqual(day['races'][0]['selected_at'], DAY+'T14:00:00+09:00')
        for change in ({'probabilities': [.2]}, {'tickets':[[1,2,3],[1,2,3]]},
                       {'tickets':[[1,2,9]]}, {'source_at':CUTOFF}):
            damaged = deepcopy(day)
            damaged['races'][0].update(change)
            with self.assertRaises(ValueError):
                shortlists.checked(damaged)

    def test_other_model_sha_is_rejected_at_selection_and_publication(self):
        with self.assertRaisesRegex(ValueError, 'MODEL_PIN'):
            choose(dict(sample(), model_sha256='a'*64))
        with self.assertRaisesRegex(ValueError, 'MODEL_PIN'):
            shortlists.project_day(DAY, model_sha256='a'*64, input_commit='3'*40,
                                   published_at=DECISION, races=[choose()])

    def test_public_clocks_use_the_browser_wire_format(self):
        packet = shortlists.project_day(DAY, model_sha256=shortlists.MODEL_SHA, input_commit='3'*40,
                                       published_at=DECISION, races=[choose()])
        with self.assertRaisesRegex(ValueError, 'CLOCK_FORMAT'):
            shortlists.checked(dict(packet, published_at=DECISION.replace('T', ' ')))
        with self.assertRaisesRegex(ValueError, 'CLOCK_FORMAT'):
            shortlists.checked(dict(packet, races=[dict(choose(), selected_at=DECISION.replace('T', 'x'))]))


if __name__ == '__main__':
    unittest.main()
