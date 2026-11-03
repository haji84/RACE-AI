import json
from pathlib import Path
import tempfile
import unittest

from race_ai.historical_pairwise import compare, append_revisions
from race_ai.verified_bulk_backtest import BadRecord


def fc(picks, day="2026-11-03"):
    return {"race_id": f"オート:{day}:浜松:1",
            "forecast_id": "before-race", "model_id": "M",
            "cohort": "morning", "picks": picks}


def result(payouts, refunds=None):
    return {"race_id": "オート:2026-11-03:浜松:1",
            "revision": 1, "status": "SETTLED",
            "payouts": payouts, "refunded_numbers": refunds or [],
            "source_grade": "legacy_claim"}


PICKS = ["1-2-3", "1-3-2", "2-1-3", "2-3-1", "3-1-2", "3-2-1",
         "1-2-4", "1-4-2", "1-3-4", "2-1-4", "2-4-1", "3-1-4"]


class PairedHistoricalTest(unittest.TestCase):
    def test_extra_hit_changes_stake_and_net(self):
        s, rows = compare([fc(PICKS)], [result({PICKS[10]: 3600})])
        self.assertEqual((s["pick_8"]["hits"], s["pick_12"]["hits"]), (0, 1))
        self.assertEqual((s["pick_8"]["stake_yen"], s["pick_12"]["stake_yen"]), (800, 1200))
        self.assertEqual((s["pick_8"]["net_yen"], s["pick_12"]["net_yen"]), (-800, 2400))
        self.assertEqual(s["normal_accuracy_denominator"], 1)

    def test_full_refund_is_not_scored_as_miss(self):
        s, _ = compare([fc(PICKS)], [result({"4-5-6": 1000}, [1, 2, 3, 4])])
        self.assertEqual(s["normal_accuracy_denominator"], 0)
        self.assertEqual(s["settled_parity_races"], 1)
        self.assertEqual(s["pick_8"]["refund_yen"], 800)

    def test_partial_refund_is_ticket_specific(self):
        s, _ = compare([fc(PICKS)], [result({"4-5-6": 1000}, [4])])
        self.assertEqual(s["pick_8"]["refund_yen"], 200)
        self.assertEqual(s["pick_12"]["refund_yen"], 600)

    def test_eight_picks_are_not_extended_after_result(self):
        s, _ = compare([fc(PICKS[:8])], [result({PICKS[5]: 1000})])
        self.assertEqual(s["paired_12_pick_races"], 0)
        self.assertEqual(s["excluded_fewer_than_12"], 1)

    def test_unknown_result_not_scored(self):
        s, _ = compare([fc(PICKS)], [])
        self.assertEqual(s["normal_accuracy_denominator"], 0)
        self.assertEqual(len(s["pending_or_special_race_ids"]), 1)

    def test_duplicate_forecast_rejected(self):
        with self.assertRaises(BadRecord):
            compare([fc(PICKS), fc(PICKS)], [])

    def test_old_result_revision_immutable(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            base, incoming, output = [tmp / x for x in ("base.jsonl", "new.jsonl", "all.jsonl")]
            old = result({"1-2-3": 450})
            base.write_text(json.dumps(old) + "\n", encoding="utf-8")
            changed = {**old, "payouts": {"1-2-3": 600}}
            incoming.write_text(json.dumps(changed) + "\n", encoding="utf-8")
            with self.assertRaises(BadRecord):
                append_revisions(base, incoming, output)
            self.assertFalse(output.exists())
            changed["revision"] = 2
            incoming.write_text(json.dumps(changed) + "\n", encoding="utf-8")
            evidence = append_revisions(base, incoming, output)
            self.assertEqual(evidence["new_unique_observations"], 1)
            self.assertEqual(len(output.read_text().splitlines()), 2)
            with self.assertRaises(BadRecord):
                append_revisions(base, incoming, output)


if __name__ == "__main__":
    unittest.main()
