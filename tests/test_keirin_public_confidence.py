from datetime import date, datetime, time, timedelta, timezone
import unittest

from race_ai import keirin_public_confidence as confidence


JST = timezone(timedelta(hours=9))
DAY = '2026-11-28'
ASSESSMENT = '2026-11-28T11:00:00+09:00'
ARCHIVE = 'a' * 40


def _row(day, index, hit, **changes):
    cutoff = datetime.combine(date.fromisoformat(day), time(18), JST)
    row = dict(lane='official', arm='A', race_id=day.replace('-', '') + f'{11 + index // 12:02}{1 + index % 12:02}',
               points=8, forecast_at=(cutoff - timedelta(hours=1)).isoformat(),
               cutoff_at=cutoff.isoformat(), result_at=(cutoff + timedelta(hours=1)).isoformat(), hit=hit)
    return confidence.ShortlistObservation(**(row | changes))


def _cohort(days, sizes, hits):
    count = 0
    for day, size in zip(days, sizes, strict=True):
        for i in range(size):
            yield _row(day, i, count < hits)
            count += 1


def _build(rows):
    return confidence.build(rows, day=DAY, assessed_at=ASSESSMENT, archive_commit=ARCHIVE)


class PublicConfidenceTests(unittest.TestCase):
    def test_prior_fit_frequency_scores_on_three_separate_validation_days(self):
        fit = list(_cohort(('2026-11-18', '2026-11-20', '2026-11-24'), (7, 7, 6), 12))
        validate = list(_cohort(('2026-11-25', '2026-11-26', '2026-11-27'), (10, 10, 10), 18))
        validate[10] = _row('2026-11-26', 0, True, forecast_at='2026-11-25T22:00:00+09:00')
        result = _build(fit + validate)
        self.assertEqual(result['schema'], 'RACE_AI_KEIRIN_PUBLIC_SHORTLIST_CONFIDENCE_V1')
        self.assertEqual(result['training_window'], ['2026-11-18', '2026-11-24'])
        self.assertEqual(result['validation_window'], ['2026-11-25', '2026-11-27'])
        self.assertEqual(result['assessed_at'], ASSESSMENT)
        self.assertEqual(result['archive_commit'], ARCHIVE)
        row, = result['rows']
        self.assertEqual(row['fit'], {'n': 20, 'hits': 12, 'days': 3})
        self.assertEqual(row['validation'], {'n': 30, 'hits': 18, 'days': 3})
        self.assertEqual((row['state'], row['probability'], row['grade']), ('GRADED', .60, 'MEDIUM'))
        self.assertLess(row['ci95'][0], .60)
        self.assertGreater(row['ci95'][1], .60)
        self.assertEqual(_build(list(reversed(fit + validate))), result)

    def test_no_pooling_and_explicit_holds_with_descriptive_validation(self):
        fit = list(_cohort(('2026-11-18', '2026-11-20', '2026-11-24'), (7, 7, 6), 17))
        validate = list(_cohort(('2026-11-25', '2026-11-26', '2026-11-27'), (10, 10, 10), 26))
        fit += [_row('2026-11-24', 0, True, lane='reference'), _row('2026-11-24', 0, True, arm='B'),
                _row('2026-11-24', 0, True, points=7)]
        validate += [_row('2026-11-26', 0, True, lane='reference')]
        rows = {(r['lane'], r['arm'], r['points']): r for r in _build(fit + validate)['rows']}
        high = rows['official', 'A', 8]
        self.assertEqual(high['state'], 'HOLD_CALIBRATION_WILSON_LOWER_TARGET')
        self.assertIsNone(high['probability'])
        self.assertIsNone(high['grade'])
        self.assertIsNotNone(high['ci95'])
        for key in (('reference', 'A', 8), ('official', 'B', 8), ('official', 'A', 7)):
            self.assertEqual(rows[key]['state'], 'HOLD_CALIBRATION_FIT_INSUFFICIENT')
            self.assertEqual(rows[key]['fit'], {'n': 1, 'hits': 1, 'days': 1})
        self.assertEqual(rows['reference', 'A', 8]['validation'], {'n': 1, 'hits': 1, 'days': 1})
        self.assertIsNotNone(rows['reference', 'A', 8]['ci95'])

    def test_jst_boundaries_ignore_late_results_and_accept_earlier_publication(self):
        observations = [
            _row('2026-11-24', 0, True, result_at='2026-11-24T15:00:00Z'),
            _row('2026-11-24', 1, True, forecast_at='2026-11-24T18:00:00+09:00'),
            _row('2026-11-26', 0, True, forecast_at='2026-11-25T15:59:00+09:00'),
            _row('2026-11-25', 0, True, forecast_at='2026-11-24T22:00:00+09:00'),
            _row('2026-11-27', 0, True, result_at='2026-11-27T15:00:00Z'),
            _row('2026-11-28', 0, True),
        ]
        row, = _build(observations)['rows']
        self.assertEqual(row['fit'], {'n': 0, 'hits': 0, 'days': 0})
        self.assertEqual(row['validation'], {'n': 1, 'hits': 1, 'days': 1})

    def test_duplicate_and_wrong_race_day_are_rejected(self):
        row = _row('2026-11-18', 0, False)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            _build([row, row])
        with self.assertRaisesRegex(ValueError, 'RACE_DAY'):
            _build([_row('2026-11-18', 0, True, cutoff_at='2026-11-19T11:00:00+09:00')])
