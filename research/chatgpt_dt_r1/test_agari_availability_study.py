from copy import deepcopy
import unittest

from research.chatgpt_dt_r1 import agari_availability_study as study
from research.chatgpt_dt_r1.history_window_study import history_projection


class AgariAvailabilityTests(unittest.TestCase):
    def row(self):
        return dict(day='2026-06-30', race_id='202606309801', venue_code='98',
            race_class='L1', field_supported=True, riders=[{'car': car} for car in range(1, 6)],
            result_rows=[dict(car=car, rank=car, incident=(car == 2), cancelled=False, absence=False,
                half_lap_seconds=value, final_lap_seconds=25., sb_mark='SB')
                for car, value in enumerate((11.4, 11.2, None, float('inf'), 0.), 1)])

    def test_only_normal_numeric_prior_half_lap_is_added(self):
        raw = self.row()
        before = deepcopy(raw)
        base = history_projection(raw)
        alternate = study.with_half_lap(base, raw)
        expected = deepcopy(base)
        expected['result_rows'][0]['half_lap_seconds'] = 11.4
        self.assertEqual(alternate, expected)
        self.assertEqual(base, history_projection(raw))
        self.assertEqual(raw, before)

    def test_projection_must_already_have_an_admitted_roster(self):
        raw = self.row()
        raw['result_rows'][0]['absence'] = True
        self.assertIsNone(history_projection(raw))
        self.assertIsNone(study.with_half_lap(None, raw))
