import unittest
from race_ai.core import SourceError
from race_ai.racer_win_loss_patterns import analyze_patterns

ASOF="2026-10-14T09:00:00+09:00"


def race(rid, finish, method, course=2, at="2026-10-13T18:00:00+09:00"):
    return {"race_id":rid,"racer_id":"4001","finish":finish,
            "winner_method":method,"actual_course":course,
            "observed_at":at,"published_at":at}


class RacerWinLossPatternTests(unittest.TestCase):
    def test_winner_and_loser_methods_are_distinct(self):
        rows=[race("20261013-18-01",1,"差し"),
              race("20261013-18-02",4,"まくり")]
        result=analyze_patterns(rows,racer_id="4001",asof=ASOF)
        self.assertEqual(result["wins_by_own_winning_method"],{"差し":1})
        self.assertEqual(result["losses_by_opponent_winning_method"],{"まくり":1})
        self.assertEqual(result["causal_loss_explanation"],"UNKNOWN_REQUIRES_VIDEO_OR_VERIFIED_TURN_EVIDENCE")

    def test_future_record_excluded(self):
        rows=[race("20261015-18-01",1,"逃げ",at="2026-10-15T18:00:00+09:00")]
        result=analyze_patterns(rows,racer_id="4001",asof=ASOF)
        self.assertEqual(result["valid_finishes"],0)
        self.assertEqual(result["excluded_future"],1)

    def test_duplicate_race_rejected(self):
        row=race("20261013-18-01",1,"逃げ")
        with self.assertRaises(SourceError):
            analyze_patterns([row,row],racer_id="4001",asof=ASOF)
