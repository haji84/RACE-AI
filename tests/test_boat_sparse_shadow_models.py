"""Synthetic only. Neither file-based nor actual source/odds data are read."""
import copy
import math
import unittest

from race_ai.boat_sparse_shadow_models import (
    CORE, EXTRA, ENVIRONMENT, LITE_ID, ENRICHED_ID, MISSING,
    RESEARCH, SYNTHETIC, SCHEMA, SparseModelError,
    predict_shadow_pair, validate_snapshot, _stable_hash
)

DAY = "2030-06-07"
PUB = DAY + "T07:00:00+09:00"
CAP = DAY + "T07:01:00+09:00"
ASOF = DAY + "T08:00:00+09:00"
CUTOFF = DAY + "T11:00:00+09:00"


def proof(value, *, kind="aggregate_stat", published_at=PUB, captured_at=CAP,
          source_ref="synthetic://fixture", rights="synthetic-test-only",
          sample_n=20, valid_for_at=None):
    return {
        "value": value, "published_at": published_at, "captured_at": captured_at,
        "valid_for_at": valid_for_at, "source_ref": source_ref,
        "source_rights_ref": rights, "transform_id": "synthetic-v1",
        "sample_n": sample_n, "observation_kind": kind,
    }


def sample():
    entrants = []
    for lane in range(1, 7):
        entrants.append({
            "number": lane, "registration_no": str(4000 + lane),
            "features": {
                "ability": proof(.1 + lane * .1),
                "course_compatibility": proof(.62 - lane * .04),
                "motor_form": proof(.26 + lane * .03),
            },
            "missing": {key: "SOURCE_UNAVAILABLE" for key in EXTRA},
        })
    return {
        "schema": SCHEMA, "scope": SYNTHETIC,
        "race": {
            "race_id": "boat:" + DAY + ":boatrace-jcd-18:1",
            "venue": "boatrace-jcd-18", "event_date_jst": DAY,
            "as_of": ASOF, "scheduled_cutoff_at": CUTOFF,
            "distance_m": 1800, "race_revision": 1,
        },
        "participants": entrants,
        "environment": {
            "features": {}, "missing": {k: "NOT_YET_PUBLISHED" for k in ENVIRONMENT}
        }
    }


class SparseBoatShadowTests(unittest.TestCase):
    def test_three_features_suffice_for_lite_without_fake_extra_data(self):
        snapshot = sample()
        paired = predict_shadow_pair(snapshot)
        lite = paired["lite"]
        self.assertEqual(lite["model_id"], LITE_ID)
        self.assertEqual(lite["model_version"], "0.1.0-UNTRAINED")
        self.assertEqual(lite["candidate_count"], 120)
        self.assertEqual(len(lite["ordered_top8"]), 8)
        self.assertEqual(len(set(tuple(x) for x in lite["ordered_top8"])), 8)
        self.assertAlmostEqual(sum(x["score"] for x in lite["candidates"]), 1, places=11)
        self.assertEqual([x["combination"] for x in lite["candidates"][:8]],
                         lite["ordered_top8"])
        self.assertEqual(paired["enriched"]["status"], "NO_FORECAST_NO_COMPLETE_ENRICHMENT")
        self.assertIsNone(paired["enriched"]["ordered_top8"])
        self.assertIsNone(lite["external_pre_cutoff_receipt"])
        self.assertFalse(lite["official_prediction"])
        self.assertFalse(lite["trained"])
        self.assertFalse(lite["calibrated"])
        self.assertTrue(lite["odds_independent"])
        self.assertEqual(lite["purchase_decision"], "NO_BET")
        self.assertFalse(paired["formal_hit_at_8_eligible"])
        self.assertEqual(lite["prediction_sha256"],
                         _stable_hash({k: v for k, v in lite.items() if k != "prediction_sha256"}))

    def test_enrichment_uses_only_identically_available_extra_keys(self):
        snapshot = sample()
        for lane, participant in enumerate(snapshot["participants"], 1):
            participant["features"]["recent_form"] = proof(.45 + lane / 20)
            del participant["missing"]["recent_form"]
        enriched = predict_shadow_pair(snapshot)["enriched"]
        self.assertEqual(enriched["model_id"], ENRICHED_ID)
        self.assertEqual(enriched["used_optional_keys"], ["recent_form"])
        self.assertEqual(enriched["candidate_count"], 120)
        self.assertEqual(len(enriched["ordered_top8"]), 8)
        self.assertFalse(enriched["official_prediction"])
        self.assertNotEqual(enriched["prediction_sha256"],
                            predict_shadow_pair(sample())["lite"]["prediction_sha256"])

    def test_partially_available_enrichment_is_never_zero_imputed(self):
        snapshot = sample()
        snapshot["participants"][0]["features"]["recent_form"] = proof(.99)
        del snapshot["participants"][0]["missing"]["recent_form"]
        bundle = predict_shadow_pair(snapshot)
        self.assertEqual(bundle["lite"], predict_shadow_pair(sample())["lite"])
        self.assertEqual(bundle["enriched"]["status"], "NO_FORECAST_NO_COMPLETE_ENRICHMENT")
        self.assertEqual(bundle["enriched"]["excluded_partially_observed_keys"], ["recent_form"])

    def test_lite_deterministic_and_enriched_does_not_retroedit_lite(self):
        base = sample()
        first = predict_shadow_pair(base)
        same = predict_shadow_pair(copy.deepcopy(base))
        self.assertEqual(first, same)
        extra = copy.deepcopy(base)
        for part in extra["participants"]:
            part["features"]["consistency"] = proof(.5 + .01 * part["number"])
            del part["missing"]["consistency"]
        second = predict_shadow_pair(extra)
        self.assertEqual(first["lite"]["ordered_top8"], second["lite"]["ordered_top8"])
        self.assertEqual(first["lite"]["input_sha256"], _stable_hash(base))
        self.assertNotEqual(first["lite"]["input_sha256"], second["lite"]["input_sha256"])
        self.assertEqual(first["lite"]["prediction_sha256"],
                         predict_shadow_pair(base)["lite"]["prediction_sha256"])

    def test_core_missing_or_not_dated_never_gives_shadow_forecast(self):
        for key in CORE:
            bad = sample()
            del bad["participants"][0]["features"][key]
            with self.subTest(core=key), self.assertRaises(SparseModelError):
                predict_shadow_pair(bad)
        bad = sample()
        bad["participants"][0]["features"]["ability"]["published_at"] = DAY + "T09:00:00+09:00"
        with self.assertRaisesRegex(SparseModelError, "as_of"):
            predict_shadow_pair(bad)
        bad = sample()
        bad["race"]["as_of"] = CUTOFF
        with self.assertRaisesRegex(SparseModelError, "cutoff"):
            predict_shadow_pair(bad)

    def test_sample_n_stat_mandatory_but_instant_weather_not_fabricated(self):
        snapshot = sample()
        snapshot["participants"][0]["features"]["ability"]["sample_n"] = None
        with self.assertRaisesRegex(SparseModelError, "sample_n"):
            validate_snapshot(snapshot)
        snapshot = sample()
        snapshot["environment"]["features"]["wind_mps"] = proof(
            8.5, kind="instantaneous", sample_n=None
        )
        del snapshot["environment"]["missing"]["wind_mps"]
        self.assertEqual(predict_shadow_pair(snapshot)["lite"]["ordered_top8"],
                         predict_shadow_pair(sample())["lite"]["ordered_top8"])
        snapshot["environment"]["features"]["wind_mps"]["sample_n"] = 1
        with self.assertRaisesRegex(SparseModelError, "must not invent"):
            predict_shadow_pair(snapshot)

    def test_forecast_time_contract(self):
        snapshot = sample()
        snapshot["environment"]["features"]["wind_mps"] = proof(
            3.2, kind="forecast", sample_n=None,
            valid_for_at=DAY + "T11:00:00+09:00"
        )
        del snapshot["environment"]["missing"]["wind_mps"]
        self.assertEqual(predict_shadow_pair(snapshot)["lite"]["candidate_count"], 120)
        snapshot["environment"]["features"]["wind_mps"]["valid_for_at"] = PUB.replace("07:00", "06:00")
        with self.assertRaisesRegex(SparseModelError, "target"):
            predict_shadow_pair(snapshot)

    def test_forbidden_odds_result_and_missing_state_mismatch_rejected(self):
        for field in ("odds", "actual_finish", "payout_yen", "popular"):
            snapshot = sample()
            snapshot["participants"][0]["features"][field] = proof(.4)
            with self.subTest(field=field), self.assertRaises(SparseModelError):
                predict_shadow_pair(snapshot)
        snapshot = sample()
        snapshot["participants"][0]["missing"].pop("recent_form")
        with self.assertRaisesRegex(SparseModelError, "missing reason"):
            predict_shadow_pair(snapshot)
        snapshot = sample()
        snapshot["participants"][0]["missing"]["tide_activity"] = "NOT_APPLICABLE"
        with self.assertRaisesRegex(SparseModelError, "missing reason"):
            predict_shadow_pair(snapshot)

    def test_rights_gate_and_research_remains_nonofficial(self):
        snapshot = sample()
        snapshot["scope"] = RESEARCH
        for p in snapshot["participants"]:
            for v in p["features"].values():
                v["source_ref"] = "https://example.org/authorized-fixture"
                v["source_rights_ref"] = "research-test-purposes"
        with self.assertRaisesRegex(SparseModelError, "rights"):
            predict_shadow_pair(snapshot)
        pair = predict_shadow_pair(
            snapshot, allow_source=lambda ref, rights, purpose:
            ref == "https://example.org/authorized-fixture" and
            rights == "research-test-purposes" and purpose == "analysis"
        )
        self.assertFalse(pair["lite"]["official_prediction"])
        self.assertFalse(pair["formal_hit_at_8_eligible"])
        self.assertIsNone(pair["lite"]["external_pre_cutoff_receipt"])
        self.assertEqual(pair["lite"]["scope"], RESEARCH)

    def test_invalid_numeric_identity_and_duplicate_lane_rejected(self):
        for value in (None, float("nan"), -0.1, 1.01, True):
            snapshot = sample()
            snapshot["participants"][0]["features"]["motor_form"]["value"] = value
            with self.subTest(value=repr(value)), self.assertRaises(SparseModelError):
                predict_shadow_pair(snapshot)
        snapshot = sample()
        snapshot["participants"][1]["number"] = 1
        with self.assertRaises(SparseModelError):
            predict_shadow_pair(snapshot)
        snapshot = sample()
        snapshot["race"]["race_id"] = "boat:" + DAY + ":boatrace-jcd-20:1"
        with self.assertRaises(SparseModelError):
            predict_shadow_pair(snapshot)


if __name__ == "__main__":
    unittest.main()
