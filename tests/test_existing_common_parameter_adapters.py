"""Invented snapshots exercise exact native research parameter inference."""
import copy
from datetime import datetime
import importlib
import math
import unittest

from test_comprehensive_four_sport_models import sample
from race_ai.comprehensive_four_sport_models import ModelInputError, digest
from race_ai.four_sport_model_suite import ALL_MODELS, run_suite


AT = "2030-01-15T09:10:00+09:00"
PINNED = {
    "boat": (6, ["1a0dd52647316f99a7e9cfbea2b6fe51676ec4bcf6f3130dbe8683720ebe0c80", "539a7911daa4c9be33f688358289546d03dbd68a9c04fea4889f2cb2dd96ed06", "ea86c6697d2027f37cfa39da3acbbefa66441005383a9ec2c887b16c07cef38d", "8567f81359e49479c40b8146d26d6f1b6008db1757093e504076f34af7c5ac71"]),
    "keirin": (7, ["21b172d7840c5b7264adca842b7a3fe637c26a1ac3fa510e9f0acc1649a479d9", "c6ccc960978a74c7e1df07deef106aac0ebc7342c0d246881330499a6ce901a8", "bff6f10dd2c92c725c3aa3d1aa0ab7d8487dd77df488e7c957613946782d2fde", "30a62a8b32ff6cebe465edaf0112959beee7e8a07b1387b69fd5d84b88e86d3d"]),
    "autorace": (3, ["fd4f078829281234ad7d52a036d222c8f5350657b09de182e6ac2020438b0780", "d07f2748321459b402850f941211c9eee6ca016a8090d4bc5731d2d8bda6476f", "bb82be291802f3a2bbfeafe013f81c22230a06ddb30a4b9c2ae7ecc81428c4e3", "3fb6c34a0d78ecd0768acb8df8c839ad72fbfa46c7fe0d6d0122f0f732d3d459"]),
    "horse": (3, ["2b630bc7cd4910eed08dc0b13a4d52f962fcba5e08d562323d8911aedb951aed", "6f61ad1d17e29fb7df0aead73bc1ada29581b83fdce7098251deca0d6639f750", "82713464dda07f2f0a16ee1704072edd5907a18f7484c1be1e64bd7f20fbcb0e", "e7828d00eaf9327216de32532c74ac8c586ffc6b5442b291385bfe32d9c0662d"]),
}


class ExistingCommonParameterAdapters(unittest.TestCase):
    def adapter(self):
        name = "race_ai.existing_common_parameter_adapters"
        self.assertIsNotNone(importlib.util.find_spec(name), "native parameter adapter is missing")
        return importlib.import_module(name)

    def test_native_defaults_keep_pre_extension_hashes_for_every_sport(self):
        adapter = self.adapter()
        for sport, (size, hashes) in PINNED.items():
            snapshot = sample(sport, size=size)
            before = copy.deepcopy(snapshot)
            suite = run_suite(snapshot)
            for mid, expected in zip(ALL_MODELS, hashes):
                with self.subTest(sport=sport, model=mid):
                    result = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
                    self.assertEqual(result, suite["models"][mid])
                    self.assertEqual(result["prediction_sha256"], expected)
                    defaults = {name: spec[0] for name, spec in adapter.specs(mid, sport).items()}
                    explicit = adapter.predict(mid, {"snapshot": snapshot}, defaults, at=AT)
                    self.assertEqual(explicit["candidates"], result["candidates"])
                    self.assertEqual(explicit["scenario_weights"], result["scenario_weights"])
                    self.assertFalse(explicit["trained"])
                    self.assertEqual(explicit["parameter_source"], "OPERATOR_SUPPLIED_RESEARCH_PARAMETERS")
            self.assertEqual(snapshot, before)

    def test_parameter_changes_use_complete_normalized_native_distribution(self):
        adapter = self.adapter()
        for sport, size in (("boat", 6), ("keirin", 9), ("autorace", 8), ("horse", 12)):
            snapshot = sample(sport, size=size)
            for mid in ALL_MODELS:
                with self.subTest(sport=sport, model=mid):
                    baseline = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
                    changed = adapter.predict(mid, {"snapshot": snapshot}, {"utility.ability": 0.}, at=AT)
                    self.assertNotEqual(changed["candidates"], baseline["candidates"])
                    zero_ability = copy.deepcopy(snapshot)
                    for participant in zero_ability["participants"]:
                        participant["features"]["ability"]["value"] = 0.
                    native_zero = adapter.predict(mid, {"snapshot": zero_ability}, None, at=AT)
                    self.assertEqual(changed["candidates"], native_zero["candidates"])
                    self.assertEqual(len(changed["candidates"]), size*(size-1)*(size-2))
                    self.assertAlmostEqual(math.fsum(r["score"] for r in changed["candidates"]), 1., places=12)
                    self.assertEqual(changed["prediction_sha256"], digest({k:v for k,v in changed.items() if k != "prediction_sha256"}))
                    self.assertEqual(changed["scenario_weights"], baseline["scenario_weights"])

    def test_native_line_pair_synergy_and_conditional_coupling_are_tunable(self):
        adapter = self.adapter()
        snapshot = sample("keirin", size=7)
        for mid, coefficient in ((ALL_MODELS[0], "pair.line_first_second"), (ALL_MODELS[1], "pair.line_first_second"), (ALL_MODELS[2], "coupling.line_leader"), (ALL_MODELS[3], "coupling.line_leader")):
            with self.subTest(model=mid):
                base = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
                changed = adapter.predict(mid, {"snapshot": snapshot}, {coefficient: 0.}, at=AT)
                self.assertNotEqual(changed["candidates"], base["candidates"])
                apart = copy.deepcopy(snapshot)
                for p in apart["participants"]:
                    p["group_id"] = None
                apart_base = adapter.predict(mid, {"snapshot": apart}, None, at=AT)
                apart_changed = adapter.predict(mid, {"snapshot": apart}, {coefficient: 0.}, at=AT)
                self.assertEqual(apart_changed["candidates"], apart_base["candidates"])

    def test_factor_pair_parameter_keeps_native_triple_reweight_and_normalization(self):
        adapter = self.adapter()
        snapshot = sample("keirin", size=7)
        mid = ALL_MODELS[0]
        baseline = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
        changed = adapter.predict(mid, {"snapshot": snapshot}, {"pair.line_first_second": .7}, at=AT)
        groups = {p["number"]: p["group_id"] for p in snapshot["participants"]}
        expected = {}
        for candidate in baseline["candidates"]:
            a, b, c = candidate["combination"]
            expected[(a, b, c)] = candidate["score"] * math.exp(.58 if groups[a] == groups[b] else 0.)
        total = math.fsum(expected.values())
        for candidate in changed["candidates"]:
            self.assertAlmostEqual(candidate["score"], expected[tuple(candidate["combination"])]/total, places=14)

    def test_native_negative_horse_competition_and_scenario_terms_remain_signed(self):
        adapter = self.adapter()
        horse = sample("horse", size=5)
        horse["participants"][1]["style"] = "front"
        for mid in ALL_MODELS[2:]:
            spec = adapter.specs(mid, "horse")["coupling.horse_front_competition"]
            self.assertLess(spec[0], 0.)
            self.assertLess(spec[1], 0.)
            base = adapter.predict(mid, {"snapshot": horse}, None, at=AT)
            changed = adapter.predict(mid, {"snapshot": horse}, {"coupling.horse_front_competition": 0.}, at=AT)
            self.assertNotEqual(base["candidates"], changed["candidates"])
        boat = sample("boat")
        mid = ALL_MODELS[1]
        self.assertLess(adapter.specs(mid, "boat")["scenario.disruption_start"][0], 0.)
        changed = adapter.predict(mid, {"snapshot": boat}, {"scenario.disruption_start": 0.}, at=AT)
        self.assertNotEqual(changed["candidates"], adapter.predict(mid, {"snapshot": boat}, None, at=AT)["candidates"])

    def test_invalid_parameters_inputs_and_source_windows_fail_closed(self):
        adapter = self.adapter()
        mid = ALL_MODELS[0]
        payload = {"snapshot": sample("boat")}
        for parameters in ({"utility.ability": True}, {"utility.ability": float("nan")}, {"utility.ability": 5.}, {"utility.ability": "1"}, {"unknown": 1.}, {1: .2}, []):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError):
                    adapter.predict(mid, payload, parameters, at=AT)
        for at in ("2030-01-15T09:00:00+09:00", "2030-01-15T10:00:00+09:00", datetime(2030, 1, 15)):
            with self.assertRaises(ValueError):
                adapter.predict(mid, payload, None, at=at)
        for invalid in ({}, {"snapshot": sample("boat"), "sport": "horse"}):
            with self.assertRaises(ValueError):
                adapter.predict(mid, invalid, None, at=AT)
        with self.assertRaises(ValueError):
            adapter.specs("unknown", "boat")
        with self.assertRaises(ValueError):
            adapter.specs(mid, "unknown")
        for model_id, sport in ((mid, []), ([], "boat"), (mid, True)):
            with self.assertRaises(ValueError):
                adapter.specs(model_id, sport)
        missing = copy.deepcopy(payload)
        del missing["snapshot"]["participants"][0]["features"]["ability"]
        with self.assertRaises(ModelInputError):
            adapter.predict(mid, missing, {"utility.ability": 0.}, at=AT)
        late = copy.deepcopy(payload)
        late["snapshot"]["environment"]["wind_mps"]["captured_at"] = "2030-01-15T09:30:00+09:00"
        with self.assertRaises(ModelInputError):
            adapter.predict(mid, late, {}, at=AT)
        real = {"snapshot": sample("boat", scope="OPERATOR_SUPPLIED_RESEARCH")}
        with self.assertRaises(ModelInputError):
            adapter.predict(mid, real, {}, at=AT)
        self.assertFalse(adapter.predict(mid, real, {}, at=AT, allow_source=lambda *_: True)["official_prediction"])

    def test_ranker_fit_helper_preserves_existing_train_only_contract(self):
        adapter = self.adapter()
        from test_four_sport_learning import dataset
        from race_ai.four_sport_learning import fit_training_only
        rows = dataset()[:7]
        now = datetime.fromisoformat("2030-01-08T00:00:00+09:00")
        args = dict(sport="boat", train_end_at="2030-01-07T23:59:00+09:00")
        model = adapter.fit_ranker(rows, now=now, **args)
        self.assertEqual(model, fit_training_only(rows, now=lambda: now, **args))


if __name__ == "__main__":
    unittest.main()
