import hashlib
import json
import unittest
from datetime import date, datetime, timezone

from scripts.keirin_published_hit_confidence import build, grade


class PublishedHitConfidenceTest(unittest.TestCase):
    def setUp(self):
        day = "2026-11-25"
        self.rid = "202611258401"
        row = dict(race_id=self.rid, model_variant="both_updates", default_exacta_points=2, default_trifecta_points=4)
        self.source = json.dumps(dict(date=day, generated_at=day + "T00:00:00Z", races=[row])).encode()
        self.history = date(2026, 11, 24)
        self.when = datetime(2026, 11, 25, 1, tzinfo=timezone.utc)
        days = ["20261121", "20261122", "20261123"]
        self.data = {}
        for market, points, variant in [("2t", 2, "line"), ("3t", 4, "both_updates")]:
            cohort = dict(points=points, variant=variant, lower=.4, upper=.6, hits=22, n=40, dates=days, days=3)
            self.data[market] = dict(forecast_asset_sha256=hashlib.sha256(self.source).hexdigest(), groups={"sample":cohort},
                                     races={self.rid:dict(points=points, score=.4, group="sample")})

    def assess(self):
        return build(self.source, self.data, self.history, self.when)

    def test_sufficient_evidence_and_conservative_grade(self):
        self.assertEqual(grade(29, 29, 3), "未評価")
        self.assertEqual(grade(90, 100, 2), "未評価")
        self.assertEqual(grade(91, 100, 3), "高")
        self.assertEqual(grade(99, 100, 3), "激アツ")
        result = self.assess()
        self.assertEqual(result["groups"]["3t"]["sample"], dict(points=4, grade="中", hits=22, total=40, days=3))
        self.assertEqual(result["forecast_sha256"], hashlib.sha256(self.source).hexdigest())

    def test_rejects_result_date_or_mismatched_bets(self):
        self.data["2t"]["groups"]["sample"]["dates"][0] = "20261125"
        with self.assertRaisesRegex(ValueError, "historical dates"):
            self.assess()
        self.data["2t"]["groups"]["sample"]["dates"][0] = "20261121"
        self.data["3t"]["races"][self.rid]["points"] = 8
        with self.assertRaisesRegex(ValueError, "Different number of tickets"):
            self.assess()

    def test_rejects_reassigned_forecast_or_wrong_group(self):
        self.data["3t"]["forecast_asset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Different forecast"):
            self.assess()
        self.data["3t"]["forecast_asset_sha256"] = hashlib.sha256(self.source).hexdigest()
        self.data["3t"]["races"][self.rid]["score"] = .6
        with self.assertRaisesRegex(ValueError, "Outside|outside"):
            self.assess()
