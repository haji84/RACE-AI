from datetime import datetime, timedelta, timezone
from itertools import permutations
import unittest

from race_ai import keirin_calibrated_selection as selection
from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_public_forecast_odds import SCHEMA


DAY = '2026-11-26'
RACE_ID = '202611267505'
AT = f'{DAY}T18:00:00+09:00'
CUTOFF = f'{DAY}T18:10:00+09:00'
CARS = (1, 3, 4, 6, 7)
ORDERS = tuple(permutations(CARS, 3))
SERIES = 'learned-v1:trifecta:research-selection-v1'


def law():
    mass = {ticket: .04 for ticket in ORDERS[:12]}
    mass[ORDERS[0]] = .12
    mass.update({ticket: .44 / (len(ORDERS) - 12) for ticket in ORDERS[12:]})
    return JointFinish(CARS, mass, tail=(0., 0.))


def archive(favorite=10, other=55):
    quotes = {'-'.join(map(str, ticket)): other for ticket in ORDERS[:12]}
    quotes['1-3-4'] = favorite
    return dict(schema=SCHEMA, day=DAY, published_at=f'{DAY}T17:59:30+09:00',
                races=[dict(race_id=RACE_ID,
                            source_url='https://keirin.kdreams.jp/matsuyama/racedetail/7520261126010005/',
                            source_at=f'{DAY}T17:58:00+09:00',
                            observed_at=f'{DAY}T17:59:00+09:00', quotes=quotes)])


def select(odds, *, cutoff_at=CUTOFF):
    return selection.select_research(law(), race_id=RACE_ID, forecast_at=AT,
                                     cutoff_at=cutoff_at, odds_archive=odds)


def calibration_rows(probability, hits, count=40):
    first = datetime(2026, 11, 21, 7, tzinfo=timezone.utc)
    for i in range(count):
        clock = first + timedelta(days=i // 10, minutes=i % 10)
        race_id = clock.strftime('%Y%m%d') + f'75{1 + i % 10:02}'
        yield selection.CalibrationObservation(race_id, clock.isoformat(),
                                               (clock + timedelta(hours=1)).isoformat(),
                                               probability, i < hits)


class CalibratedSelectionTests(unittest.TestCase):
    def test_caps_use_the_frozen_probability_favorite_at_exact_boundaries(self):
        for odds, cap in ((10, 2), (10.1, 4), (20, 4), (20.1, 9), (99.9, 9), (100, 12)):
            with self.subTest(odds=odds):
                result = select(archive(odds))
                self.assertEqual(result['favorite'], {'order': ORDERS[0], 'probability': .12})
                self.assertEqual(result['trifecta']['cap'], cap)
                self.assertEqual(len(result['trifecta']['picks']), cap)
                self.assertEqual(result['exacta']['status'], 'HOLD_EXACTA_ODDS_UNAVAILABLE')
                self.assertEqual(len(result['exacta']['probability_reference']), 2)

    def test_allows_one_and_does_not_add_low_value_or_reorder_favorite_by_odds(self):
        result = select(archive(other=1.5))
        part = result['trifecta']
        self.assertEqual(part['status'], 'RESEARCH_SELECTION')
        self.assertEqual([item['order'] for item in part['picks']], [ORDERS[0]])
        ticket = part['picks'][0]
        self.assertAlmostEqual(ticket['fair_odds'], 1 / .12)
        self.assertEqual(ticket['marginal_probability'], .12)
        self.assertAlmostEqual(part['set_probability'], .12)
        self.assertAlmostEqual(ticket['conservative_ev'], .12 * 9.3 - 1)
        self.assertEqual(select(archive(favorite=1.1, other=1.5))['trifecta']['status'],
                         'HOLD_NO_QUALIFYING_TICKET')

    def test_rejects_missing_mismatched_future_and_stale_odds(self):
        missing = archive()
        missing['races'][0]['quotes'].pop('1-3-6')
        foreign = archive()
        foreign['races'][0]['quotes']['1-2-3'] = 20
        stale = archive()
        stale['races'][0]['source_at'] = f'{DAY}T17:54:59+09:00'
        after = archive()
        after['published_at'] = f'{DAY}T18:00:01+09:00'
        bad_race = archive()
        bad_race['races'][0]['race_id'] = '202611267506'
        bad_race['races'][0]['source_url'] = bad_race['races'][0]['source_url'].replace('0005/', '0006/')
        for odds, reason in ((None, 'HOLD_ODDS_MISSING'), (missing, 'HOLD_ODDS_CANDIDATES_MISSING'),
                             (foreign, 'HOLD_ODDS_STARTERS_MISMATCH'), (stale, 'HOLD_ODDS_STALE'),
                             (after, 'HOLD_ODDS_NOT_AVAILABLE_AS_OF'), (bad_race, 'HOLD_ODDS_RACE_MISSING')):
            with self.subTest(reason=reason):
                self.assertEqual(select(odds)['trifecta']['status'], reason)
        self.assertEqual(select(archive(), cutoff_at=AT)['trifecta']['status'], 'HOLD_RACE_CUTOFF')

    def test_grading_uses_calibrated_set_probability_at_exact_thresholds(self):
        for probability, prior_probability, hits, grade in ((.90, .96, 40, 'VERY_HIGH'),
                                                            (.80, .87, 37, 'HIGH'),
                                                            (.60, .60, 24, 'MEDIUM'),
                                                            (.59, .59, 24, 'LOW')):
            with self.subTest(probability=probability):
                evidence = selection.calibration_evidence(calibration_rows(prior_probability, hits), series=SERIES,
                                                          trained_through='2026-11-20T19:00:00+09:00')
                outcome = selection.grade_confidence(probability, series=SERIES, at=AT, evidence=evidence)
                self.assertEqual(outcome['status'], 'GRADED')
                self.assertEqual(outcome['grade'], grade)
                self.assertEqual((outcome['n'], outcome['observed_hits']), (40, hits))
                self.assertAlmostEqual(outcome['mean_probability'], prior_probability)

    def test_grading_holds_below_observed_hit_kpi_or_wilson_lower_bound(self):
        for probability, hits, status in (
            (.90, 35, 'HOLD_CALIBRATION_HIT_RATE_TARGET'),
            (.90, 36, 'HOLD_CALIBRATION_WILSON_LOWER_TARGET'),
            (.80, 31, 'HOLD_CALIBRATION_HIT_RATE_TARGET'),
            (.80, 32, 'HOLD_CALIBRATION_WILSON_LOWER_TARGET'),
            (.60, 23, 'HOLD_CALIBRATION_HIT_RATE_TARGET'),
        ):
            with self.subTest(probability=probability, status=status):
                evidence = selection.calibration_evidence(calibration_rows(probability, hits), series=SERIES,
                                                          trained_through='2026-11-20T19:00:00+09:00')
                actual = selection.grade_confidence(probability, series=SERIES, at=AT, evidence=evidence)
                self.assertEqual(actual['status'], status)
                self.assertEqual(actual['observed_hits'], hits)
                self.assertEqual(actual['grade_threshold'], probability)
                self.assertIsNone(actual['grade'])

    def test_grading_holds_for_unmatched_sparse_future_and_uncalibrated_data(self):
        rows = tuple(calibration_rows(.90, 18))
        evidence = selection.calibration_evidence(rows, series=SERIES,
                                                  trained_through='2026-11-20T19:00:00+09:00')
        cases = ((evidence, 'wrong-series', AT, 'HOLD_CALIBRATION_SERIES_MISSING'),
                 (evidence, SERIES, '2026-11-21T16:00:00+09:00', 'HOLD_CALIBRATION_OUT_OF_TIME_MISSING'),
                 (evidence, SERIES, '2026-11-22T18:00:00+09:00', 'HOLD_CALIBRATION_INSUFFICIENT'),
                 (evidence, SERIES, AT, 'HOLD_CALIBRATION_HIT_RATE_TARGET'),
                 (None, SERIES, AT, 'HOLD_CALIBRATION_SERIES_MISSING'))
        for data, series, at, status in cases:
            with self.subTest(status=status):
                actual = selection.grade_confidence(.90, series=series, at=at, evidence=data)
                self.assertEqual(actual['status'], status)
                self.assertIsNone(actual['grade'])
        with self.assertRaises(ValueError):
            selection.calibration_evidence((rows[0], rows[0]), series=SERIES,
                                           trained_through='2026-11-20T19:00:00+09:00')
        low_evidence = selection.calibration_evidence(calibration_rows(.59, 18), series=SERIES,
                                                      trained_through='2026-11-20T19:00:00+09:00')
        self.assertEqual(selection.grade_confidence(.59, series=SERIES, at=AT, evidence=low_evidence)['status'],
                         'HOLD_CALIBRATION_ERROR')

    def test_conservative_set_ev_is_net_per_equal_stake_point(self):
        result = select(archive())['trifecta']
        multiplier = result['odds_multiplier']
        self.assertAlmostEqual(result['conservative_ev_per_point'], (.12 * 10 + .04 * 55) * multiplier / 2 - 1)
        self.assertAlmostEqual(result['set_probability'], .16)
