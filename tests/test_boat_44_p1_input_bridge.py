"""Source-free tests for read-only saved-history -> existing 44-factor wiring."""
from copy import deepcopy
from datetime import date, timedelta
import unittest

from race_ai.boat_44_p1_input_bridge import assemble_p1

NOW = "2026-11-09T10:00:00+09:00"
CUT = "2026-11-09T11:30:00+09:00"
PROOF = {"captured_at": "2026-11-09T09:30:00+09:00",
         "source_sha256": "c" * 64}
RACE = "20261109-04-01"


def history():
    choices = ((1, "nige"), (4, "makuri"), (5, "makurizashi"),
               (6, "makuri"), (2, "sashi"), (1, "nige"),
               (3, "makuri"), (1, "nige"), (5, "makuri"),
               (6, "makurizashi"), (1, "nige"), (4, "makurizashi"))
    records = []
    for i, (winner, method) in enumerate(choices):
        day = date(2026, 10, 20) + timedelta(days=i)
        ordered = [winner] + [c for c in range(1, 7) if c != winner]
        finish = {c: rank for rank, c in enumerate(ordered, 1)}
        records.append({
            "race_id": "%s-04-01" % day.strftime("%Y%m%d"),
            "cutoff_at": "%sT12:00:00+09:00" % day.isoformat(),
            "result_captured_at": "%sT12:25:00+09:00" % day.isoformat(),
            "winner_method": method, "source_sha256": "a" * 64,
            "entries": [{"frame": c, "course": c, "racer_id": str(4100+c),
                         "finish": finish[c]} for c in range(1, 7)]})
    return records


def payload():
    roster = [{"frame": c, "racer_id": str(4100+c)} for c in range(1, 7)]
    exhibition = [
        {"frame": c, "course": c, "racer_id": str(4100+c),
         "tilt_deg": 2. if c >= 5 else .5} for c in range(1, 7)]
    standing = [
        {"racer_id": str(4100+c), "official_rank": c,
         "total_points": float(40+c), "deductions": 0.,
         "official_rate": float(10-c), "starts": 4,
         "remaining_starts": 1, "eligibility": "ELIGIBLE"}
        for c in range(1, 7)]
    tickets = []
    for a in range(1, 7):
        for b in range(1, 7):
            for c in range(1, 7):
                if len({a, b, c}) == 3:
                    tickets.append({"ticket": "%d-%d-%d" % (a, b, c),
                                    "score": 1/120})
    return {
        "race_id": RACE, "venue_code": "04", "as_of": NOW, "cutoff_at": CUT,
        "roster": roster, "historical_records": history(),
        "exhibition": exhibition, "exhibition_receipt": deepcopy(PROOF),
        "slow_count": 3,
        "current_venue_rule": {"venue_code": "04",
            "effective_on_jst": "2026-11-09",
            "allowed_angles": [-.5, 0., .5, 1., 1.5, 2., 3.],
            "receipt": deepcopy(PROOF)},
        "event_id": "20261109-04-event",
        "event_rules": {
            "event_id": "20261109-04-event", "venue_code": "04",
            "qualifying_slots": 3, "minimum_starts": 2,
            "receipt": deepcopy(PROOF)},
        "standings": standing, "standings_receipt": deepcopy(PROOF),
        "board_complete": True,
        "baseline": {"race_id": RACE, "as_of": NOW, "full_120": tickets},
        "admit_source": lambda kind, source: True,
    }


class Boat44InputBridgeTests(unittest.TestCase):
    def test_realistic_no_entry_observations_remain_unknown(self):
        out = assemble_p1(**payload())
        self.assertEqual(out["status"], "HOLD_MISSING_ACTUAL_SOURCE_FACTS")
        self.assertIsNone(out["record"])
        self.assertEqual(out["historical_records_examined"], 12)
        self.assertIn("six_course_features.3_kado_4_makuri_won", out["missing"])
        self.assertIn("entry_tilt_cross_features.1.historical_inward_move_win_rate",
                      out["missing"])
        self.assertFalse(out["source_independently_authenticated_here"])
        self.assertFalse(out["original_model_or_weights_modified"])

    def test_refuses_future_result_in_earlier_forecast(self):
        value = payload()
        value["historical_records"][0]["result_captured_at"] = \
            "2026-11-10T12:25:00+09:00"
        with self.assertRaisesRegex(ValueError, "PAST_RESULT_AFTER_ASOF"):
            assemble_p1(**value)

    def test_refuses_official_roster_exhibition_mismatch(self):
        value = payload()
        value["exhibition"][0]["racer_id"] = "4999"
        with self.assertRaisesRegex(ValueError, "ROSTER_EXHIBITION_MISMATCH"):
            assemble_p1(**value)

    def test_source_denial_is_blocking(self):
        value = payload()
        value["admit_source"] = lambda kind, source: kind != "past_K"
        with self.assertRaisesRegex(ValueError, "PAST_RESULT_NOT_ADMITTED"):
            assemble_p1(**value)

    def test_incomplete_event_board_cannot_become_qualifying_fact(self):
        value = payload()
        value["board_complete"] = False
        out = assemble_p1(**value)
        self.assertIn("official_event_qualifying_board", out["missing"])
        self.assertEqual(out["status"], "HOLD_MISSING_ACTUAL_SOURCE_FACTS")

    def test_absent_current_tilt_rule_stays_missing(self):
        value = payload()
        value["current_venue_rule"] = None
        out = assemble_p1(**value)
        self.assertIn("current_venue_rule", out["missing"])
        self.assertIsNone(out["record"])


if __name__ == "__main__":
    unittest.main()
