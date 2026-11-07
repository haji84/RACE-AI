"""Invented native inputs only; no provider, receipt, order or persistent state."""
import copy
from datetime import date, datetime
import hashlib
import json
import math
import shutil
import unittest

from race_ai.autorace_ab_pdca import PHASES
from race_ai.autorace_personal_baseline import predict_personal
from research.seller_shadow_v1 import model as seller
from tests.test_autorace_personal_baseline import sample


AUTO = "autorace-personal-observed-baseline-v1"
SELLER = "seller-shadow-v1-20261104"
PDCA = "boat-pdca-lane-shadow-v1"
AUTO_AT = "2030-01-15T09:22:00+09:00"
SELLER_AT = "2030-01-15T06:30:00+09:00"


def seller_payload(count=8):
    cards, waku = {}, {}
    for race in range(1, count + 1):
        key = f"2030011518{race:02d}"
        card, course = {"レースコード": key}, {"レースコード": key}
        for lane in range(1, 7):
            prefix = f"艇{lane}_"
            card[prefix + "全国勝率"] = str(6.5 if lane == 1 else 5.8 - .35*(lane - 2))
            card[prefix + "級別"] = "A1" if lane == 1 else "B1"
            course[prefix + "枠番別勝率"] = str(8 + race*.1 if lane == 1 else 6.8 - .5*(lane - 2))
        cards[key], waku[key] = card, course
    return {"cards": cards, "waku": waku, "day": "2030-01-15"}


def pdca_payload():
    facts = {
        "schema": "RACE_AI_BOAT_OBSERVATION_V1", "phase": "post_exhibition",
        "race_id": "20301103-18-05", "cutoff_at": "2030-11-03T10:30:00+09:00",
        "captured_at": "2030-11-03T10:14:50+09:00",
        "source_url": "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103",
        "source_sha256": "a"*64, "program_sha256": "b"*64,
        "rights_verified": True, "license_purpose": "private_analysis",
        "racers": [{"lane": n, "registration_no": str(4200+n),
                    "national_win_rate": 5.2+(n-1)*.2,
                    "exhibition_time_seconds": 6.8+(n-1)*.01} for n in range(1, 7)],
    }
    rows = []
    # Twenty-four genuinely distinct earlier fixtures with a mild first-lane
    # excess; unlike a saturated prior, this makes pseudocount changes visible.
    winners = [1]*6 + [2]*4 + [3]*4 + [4]*4 + [5]*3 + [6]*3
    for n, winner in enumerate(winners):
        day = f"{1+n//12:02d}"
        others = [lane for lane in range(1, 7) if lane != winner][:2]
        report = {"race_id": f"203011{day}-18-{1+n%12:02d}",
                  "official_top3": [winner, *others], "source_sha256": "c"*64,
                  "captured_at": f"2030-11-{day}T18:00:00+09:00"}
        wire = json.dumps(report, separators=(",", ":"))
        rows.append({"report_json": wire, "report_sha256": hashlib.sha256(wire.encode()).hexdigest(),
                     "db_saved_at": f"2030-11-{day}T18:01:00+09:00"})
    return {"facts": facts, "rows": rows}


class NativeOptionalParameters(unittest.TestCase):
    def test_auto_explicit_defaults_preserve_both_original_hashes(self):
        defaults = {"recent_weight": 1.2, "handicap_weight": -.01, "trial_weight": .9}
        hashes = ["0e7b8d5bdccf1e1d4a9effdd44409c8ae8ca2b79237b2f30fa1ce2deac9636c2",
                  "33997634d29e7a5dfeb255cb8ca6d446fd4c45d4479339b418b35d2f8bd3cf70"]
        for phase, expected in zip(PHASES, hashes):
            native = predict_personal(sample(phase), generated_at=AUTO_AT)
            tuned = predict_personal(sample(phase), generated_at=AUTO_AT, parameters=defaults)
            self.assertEqual(native["prediction_sha256"], expected)
            self.assertEqual(tuned, native)

    def test_auto_trial_weight_changes_only_post_trial_and_does_not_mutate(self):
        before = sample(PHASES[1])
        frozen = copy.deepcopy(before)
        base = predict_personal(before, generated_at=AUTO_AT)
        tuned = predict_personal(before, generated_at=AUTO_AT, parameters={"trial_weight": 0})
        self.assertEqual(base["ordered_top8"][0], [8, 7, 6])
        self.assertNotEqual(tuned["ranked_relative_weights"], base["ranked_relative_weights"])
        self.assertEqual(predict_personal(before, generated_at=AUTO_AT), base)
        self.assertEqual(before, frozen)
        a = sample()
        self.assertEqual(predict_personal(a, generated_at=AUTO_AT),
                         predict_personal(a, generated_at=AUTO_AT, parameters={"trial_weight": 0}))

    def test_auto_bounded_extreme_coefficients_keep_mass_for_valid_small_roster(self):
        snapshot = sample(PHASES[1], count=3)
        for n, row in enumerate(snapshot["drivers"]):
            row.update(handicap_m=0 if n == 0 else 200,
                       recent_finishes=[1 if n == 0 else 8]*3,
                       trial_seconds=3.0 if n == 0 else 4.5)
        output = predict_personal(snapshot, generated_at=AUTO_AT,
                                  parameters={"recent_weight": 4, "trial_weight": 3, "handicap_weight": -.05})
        self.assertEqual(output["candidate_count"], 6)
        self.assertAlmostEqual(math.fsum(x["relative_weight"] for x in output["ranked_relative_weights"]), 1.)
        self.assertTrue(all(x["relative_weight"] > 0 for x in output["ranked_relative_weights"]))

    def test_seller_default_bytes_and_native_ticket_policy(self):
        payload = seller_payload()
        args = payload["cards"], payload["waku"], date(2030, 1, 15), datetime.fromisoformat(SELLER_AT)
        original = seller.generate(*args)
        defaults = {"second_national_weight": 1., "second_course_weight": 1.,
                    "score_national_weight": 2., "score_course_weight": 1., "score_gap_weight": .5}
        tuned = seller.generate(*args, parameters=defaults)
        self.assertEqual(seller.commit_digest(original), "cfe63d7c1e39c716b7b8cd8af55c6a2c42de8479274c18bb89c8e657b6ba0b02")
        self.assertEqual(tuned, original)
        selected = [r for r in tuned["rows"] if "tickets" in r]
        self.assertEqual(len(selected), 5)
        for row in selected:
            self.assertEqual([t["yen"] for t in row["tickets"]["three"]], [5000, 3000, 2000])
            self.assertEqual([t["yen"] for t in row["tickets"]["five"]], [2000]*5)
            self.assertTrue(all(t["ticket"].startswith("1-") for t in row["tickets"]["five"]))

    def test_seller_second_position_parameter_changes_native_tickets(self):
        payload = seller_payload(count=1)
        key = next(iter(payload["cards"]))
        for lane in range(2, 7):
            payload["cards"][key][f"艇{lane}_全国勝率"] = str(9-lane)
            payload["waku"][key][f"艇{lane}_枠番別勝率"] = str(lane)
        frozen = copy.deepcopy(payload)
        args = payload["cards"], payload["waku"], date(2030, 1, 15), datetime.fromisoformat(SELLER_AT)
        base = seller.generate(*args)
        tuned = seller.generate(*args, parameters={"second_national_weight": 0})
        self.assertEqual(tuned["rows"][0]["tickets"]["three"][0]["ticket"], "1-6-5")
        self.assertNotEqual(base["rows"][0]["tickets"], tuned["rows"][0]["tickets"])
        self.assertEqual(seller.generate(*args), base)
        self.assertEqual(payload, frozen)

    def test_seller_race_score_parameters_rerank_the_same_five_race_policy(self):
        payload = seller_payload(count=6)
        for race, key in enumerate(payload["cards"], 1):
            payload["cards"][key]["艇1_全国勝率"] = str(5.7 + .1*race)
            payload["waku"][key]["艇1_枠番別勝率"] = str(8.8 - .1*race)
        args = payload["cards"], payload["waku"], date(2030, 1, 15), datetime.fromisoformat(SELLER_AT)
        base = seller.generate(*args)
        tuned = seller.generate(*args, parameters={"score_national_weight": 0, "score_gap_weight": 0})
        self.assertEqual([r["race_id"][-2:] for r in base["rows"] if "tickets" in r], ["02", "03", "04", "05", "06"])
        self.assertEqual([r["race_id"][-2:] for r in tuned["rows"] if "tickets" in r], ["01", "02", "03", "04", "05"])
        self.assertEqual(tuned["forecasted"], 5)

    def test_native_entrypoints_reject_invalid_parameters_without_global_mutation(self):
        auto = sample()
        original = predict_personal(auto, generated_at=AUTO_AT)
        payload = seller_payload(count=1)
        args = payload["cards"], payload["waku"], date(2030, 1, 15), datetime.fromisoformat(SELLER_AT)
        baseline = seller.generate(*args)
        for parameters in ([1], {"trial_weight": math.nan}, {"handicap_weight": .01}, {"recent_weight": True}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                predict_personal(auto, generated_at=AUTO_AT, parameters=parameters)
        for parameters in ([], {"max_races": 9}, {"second_course_weight": math.inf}, {"score_national_weight": -1}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                seller.generate(*args, parameters=parameters)
        self.assertEqual(predict_personal(auto, generated_at=AUTO_AT), original)
        self.assertEqual(seller.generate(*args), baseline)


class SpecialAdapters(unittest.TestCase):
    def adapter(self):
        from race_ai import existing_special_parameter_adapters
        return existing_special_parameter_adapters

    def test_specs_are_bounded_family_specific_and_return_a_copy(self):
        m = self.adapter()
        self.assertEqual(m.specs(AUTO, "autorace")["handicap_weight"], (-.01, -.05, 0.))
        self.assertEqual(m.specs(PDCA, "boat"), {"lane_pseudocount": (12., 1., 48.)})
        spec = m.specs(SELLER, "boat")
        self.assertIn("second_national_weight", spec)
        self.assertNotIn("ticket_count", spec)
        spec.clear()
        self.assertTrue(m.specs(SELLER, "boat"))
        with self.assertRaises(ValueError):
            m.specs(AUTO, "boat")

    def test_auto_adapter_preserves_native_distribution_and_validates_input(self):
        m = self.adapter()
        payload = {"snapshot": sample(PHASES[1])}
        native = predict_personal(payload["snapshot"], generated_at=AUTO_AT)
        got = m.predict(AUTO, payload, None, at=AUTO_AT)
        self.assertEqual(got, native)
        self.assertAlmostEqual(math.fsum(x["relative_weight"] for x in got["ranked_relative_weights"]), 1.)
        probability = m.probability(AUTO, payload, {}, [8, 7, 6], at=AUTO_AT)
        self.assertEqual(probability, native["ranked_relative_weights"][0]["relative_weight"])
        with self.assertRaises(ValueError):
            m.predict(AUTO, {}, {}, at=AUTO_AT)
        bad = copy.deepcopy(payload)
        bad["snapshot"]["drivers"][0]["recent_finishes"] = []
        with self.assertRaises(ValueError):
            m.predict(AUTO, bad, {}, at=AUTO_AT)

    def test_seller_adapter_returns_full_native_batch_and_keeps_cutoff(self):
        m = self.adapter()
        payload = seller_payload()
        before = copy.deepcopy(payload)
        native = seller.generate(payload["cards"], payload["waku"], date(2030, 1, 15), datetime.fromisoformat(SELLER_AT))
        self.assertEqual(m.predict(SELLER, payload, None, at=SELLER_AT), native)
        self.assertEqual(payload, before)
        with self.assertRaises(ValueError):
            m.predict(SELLER, payload, {}, at="2030-01-15T07:00:00+09:00")
        with self.assertRaises(ValueError):
            m.probability(SELLER, payload, {}, [1, 2, 3], at=SELLER_AT)

    def test_parameters_reject_unknown_nonfinite_bool_and_out_of_bounds(self):
        m = self.adapter()
        for parameters in ({"unknown": 1}, {"recent_weight": math.nan},
                           {"recent_weight": True}, {"handicap_weight": .01}, []):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                m.predict(AUTO, {"snapshot": sample()}, parameters, at=AUTO_AT)
        for parameters in ({"score_gap_weight": -1}, {"second_course_weight": math.inf}, {"max_races": 6}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                m.predict(SELLER, seller_payload(), parameters, at=SELLER_AT)

    def test_missing_native_datasets_and_invalid_execution_clocks_fail_closed(self):
        m = self.adapter()
        for mid, payload, at in (
                (AUTO, {"snapshot": sample()}, "2030-01-15T09:22:00"),
                (SELLER, {**seller_payload(), "waku": {}}, SELLER_AT),
                (PDCA, {"facts": {}, "rows": []}, "2030-11-03T10:15:00+09:00")):
            with self.subTest(model_id=mid), self.assertRaises(ValueError):
                m.predict(mid, payload, None, at=at)
        for winning in ([1, 1, 2], [True, 2, 3], [8, 7, 9], "8-7-6"):
            with self.subTest(winning=winning), self.assertRaises(ValueError):
                m.probability(AUTO, {"snapshot": sample(PHASES[1])}, {}, winning, at=AUTO_AT)

    @unittest.skipUnless(shutil.which("node"), "native Node runtime required")
    def test_pdca_native_parameter_changes_normalized_prior_and_preserves_input(self):
        m = self.adapter()
        payload = pdca_payload()
        before = copy.deepcopy(payload)
        at = "2030-11-03T10:15:00+09:00"
        base = m.predict(PDCA, payload, None, at=at)
        defaults = m.predict(PDCA, payload, {"lane_pseudocount": 12}, at=at)
        tuned = m.predict(PDCA, payload, {"lane_pseudocount": 1}, at=at)
        self.assertEqual(base, defaults)
        self.assertEqual(base["training_count"], 24)
        self.assertNotEqual(base["lane_prior_factors"], tuned["lane_prior_factors"])
        self.assertAlmostEqual(math.fsum(x["score"] for x in tuned["all120"]), 1.)
        self.assertEqual(m.probability(PDCA, payload, {}, base["all120"][0]["ticket"], at=at), base["all120"][0]["score"])
        self.assertEqual(payload, before)
        payload["rows"].pop()
        with self.assertRaisesRegex(ValueError, "24"):
            m.predict(PDCA, payload, {}, at=at)


if __name__ == "__main__":
    unittest.main()
