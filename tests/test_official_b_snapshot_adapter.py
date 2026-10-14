import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.official_b_snapshot_adapter import normalize_b_snapshot


def fixture():
    lines = ["STARTB", "18BBGN", "2026/10/14", "１Ｒ 予選 Ｈ１８００ｍ"]
    lines += [f"{i} {4000+i} 選手" for i in range(1,7)]
    lines += ["18BEND"]
    return ("\n".join(lines) + "\n").encode("cp932")


class OfficialBSnapshotTests(unittest.TestCase):
    def test_no_motor_data_is_explicitly_unknown(self):
        result = normalize_b_snapshot(fixture(), day=date(2026,10,14),
            source_url="https://example.org/official", observed_at="2026-10-14T08:00:00+09:00")
        self.assertIsNone(result["venues"][0]["races"][0]["boats"][0]["motor_no"])

    def test_valid_motor_join_preserves_unknown_fields(self):
        motors = {(f"20261014-18-01", i): i+10 for i in range(1,7)}
        result = normalize_b_snapshot(fixture(), day=date(2026,10,14),
            source_url="https://example.org/official", observed_at="2026-10-14T08:00:00+09:00",
            motors=motors)
        self.assertEqual(result["races"], 1)
        self.assertEqual(result["complete_six_boat_races"], 1)
        self.assertIsNone(result["venues"][0]["races"][0]["boats"][0]["display_time"])

    def test_wrong_day_is_rejected(self):
        with self.assertRaises(SourceError):
            normalize_b_snapshot(fixture(), day=date(2026,10,13),
                source_url="https://example.org/official", observed_at="2026-10-13T08:00:00+09:00")
