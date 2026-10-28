"""Fictional evidence only; injected authorities do not prove real source rights."""
import copy
import hashlib
import importlib
import itertools
import json
import unittest


DAY = "2030-01-15"
AS_OF = DAY + "T09:00:00+09:00"
CUTOFF = DAY + "T10:00:00+09:00"
MODELS = ("fixture-factor", "fixture-trajectory")
MODEL_VERSIONS = {name: "fixture-1" for name in MODELS}
MODEL_SOURCE_SHA40 = "d" * 40  # FICTIONAL implementation reference, never a real execution claim.
MODEL_DECLARATION = tuple((name, MODEL_VERSIONS[name], MODEL_SOURCE_SHA40) for name in MODELS)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def rehash(delivery):
    suite = delivery["research_suite"]
    for model in suite["models"].values():
        model["prediction_sha256"] = digest({k: v for k, v in model.items()
                                              if k != "prediction_sha256"})
    suite["suite_sha256"] = digest({k: v for k, v in suite.items() if k != "suite_sha256"})
    delivery["delivery_sha256"] = digest({k: v for k, v in delivery.items()
                                         if k != "delivery_sha256"})


def fixture(division="boat"):
    sport = "horse" if division.startswith("horse_") else division
    race_id = division + ":" + DAY + ":fictional-venue:1"
    model_race_id = sport + ":" + DAY + ":fictional-venue:1"
    records = [{"race_id": division + ":" + DAY + ":fictional-venue:" + str(n),
                "sport": division, "venue": "fictional-venue", "race_no": n,
                "sales_cutoff_at": CUTOFF, "cutoff_verified": False,
                "prediction": None, "result": None} for n in range(1, 4)]
    ledger = {"schema": "RACE_AI_FORECAST_AUDIT_V1", "dataset_status": "AUDIT_ONLY",
              "event_date_jst": DAY, "records": records}
    snapshot = {"scope": "OPERATOR_SUPPLIED_RESEARCH", "schema": "FICTIONAL_TEST_INPUT",
                "race": {"race_id": model_race_id, "sport": sport,
                         "venue": "fictional-venue", "event_date_jst": DAY,
                         "as_of": AS_OF, "sales_cutoff_at": CUTOFF, "race_revision": 1},
                "participants": [{"number": n, "identity": "fictional-" + str(n)}
                                 for n in range(1, 7)]}
    models = {}
    for name in MODELS:
        candidates = [{"combination": list(t),
                       "score": (2 / 140 if t[0] == 6 else 1 / 140)
                       if name == MODELS[1] else 1 / 120}
                      for t in itertools.permutations(range(1, 7), 3)]
        candidates.sort(key=lambda x: (-x["score"], x["combination"]))
        models[name] = {"model_id": name, "model_version": "fixture-1",
                        "race_id": model_race_id, "sport": sport,
                        "race_revision": 1, "as_of": AS_OF, "cutoff_at": CUTOFF,
                        "scope": "OPERATOR_SUPPLIED_RESEARCH",
                        "snapshot_sha256": digest(snapshot), "candidate_count": 120,
                        "candidates": candidates,
                        "ordered_top8": [x["combination"] for x in candidates[:8]],
                        "trained": False, "odds_independent": True,
                        "official_prediction": False, "external_pre_cutoff_receipt": None,
                        "official_result": None}
    suite = {"schema": "RACE_AI_FOUR_SPORT_RESEARCH_SUITE_V1",
             "scope": "OPERATOR_SUPPLIED_RESEARCH", "sport": sport,
             "race_id": model_race_id, "race_revision": 1, "as_of": AS_OF,
             "sales_cutoff_at": CUTOFF, "input_sha256": digest(snapshot),
             "models": models, "ranked_model_ids": list(models), "model_count": 2,
             "official_prediction": False, "external_timestamp_receipts": None,
             "official_result": None}
    delivery = {"schema": "RACE_AI_PRIVATE_DELIVERY_V1", "race_id": model_race_id,
                "sport": sport, "snapshot": snapshot, "research_suite": suite,
                "source_payload_sha256": "a" * 64, "policy_record_sha256": "b" * 64,
                "feature_snapshot_sha256": digest(snapshot),
                "ingested_at": DAY + "T09:01:00+09:00",
                "status": "PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN",
                "official_prediction": False, "external_receipt": None,
                "can_count_in_hit_at_8": False,
                "source_terms_independently_verified_by_code": False}
    rehash(delivery)
    freezes = [{"race_id": race_id, "model_id": name,
                "prediction_sha256": models[name]["prediction_sha256"],
                "generated_at": DAY + "T09:02:00+09:00",
                "persisted_at": DAY + "T09:03:00+09:00", "cutoff_at": CUTOFF,
                "receipt": {"run_id": 101 + n,
                            "path": "audit/freezes/" + DAY + "/fixture-" + str(n) + ".json"}}
               for n, name in enumerate(MODELS)]
    results = [{"race_id": row["race_id"], "status": "FINAL", "trifecta_offered": True,
                "payouts": [{"combination": [n, n + 1, n + 2], "yen_per_100": 700}],
                "refund_status": "NONE", "revision_no": 1,
                "confirmed_at": DAY + "T11:00:00+09:00",
                "source_ref": "https://example.org/fictional-result"}
               for n, row in enumerate(records, 1)]
    return ledger, results, [{"race_id": race_id, "delivery": delivery}], freezes


def authorities(data, observed=None):
    """Stand-ins for external authority; specific immutable fixture fingerprints."""
    ledger, results, deliveries, freezes = copy.deepcopy(data)
    allowed_snapshots = {digest(x["delivery"]["snapshot"]) for x in deliveries}
    expected_receipts = {digest(x["receipt"]):
                         (x["prediction_sha256"], x["persisted_at"], x["cutoff_at"],
                          next((d["delivery"]["race_id"] for d in deliveries
                                if d["race_id"] == x["race_id"]), None)) for x in freezes}
    result_hashes = {digest(x) for x in results}

    def source(ref, rights, purpose):
        return (ref, rights, purpose) == ("fixture-source", "fixture-rights", "analysis")

    def validator(snapshot, *, allow_source):
        if digest(snapshot) not in allowed_snapshots:
            raise ValueError("fixture snapshot differs from independent source evidence")
        if not allow_source("fixture-source", "fixture-rights", "analysis"):
            raise ValueError("fixture source analysis purpose denied")
        return {"snapshot_sha256": digest(snapshot)}

    def freeze(receipt, sha, persisted, cutoff, *, expected_race_id):
        if observed is not None:
            observed.append((sha, expected_race_id))
        return expected_receipts.get(digest(receipt)) == (sha, persisted, cutoff, expected_race_id)

    return {"validate_snapshot": validator, "allow_source": source,
            "expected_model_versions": dict(MODEL_VERSIONS),
            "expected_model_source_sha40": MODEL_SOURCE_SHA40,
            "admit_model_roster": lambda declaration: declaration == MODEL_DECLARATION,
            "verify_result": lambda res: digest(res) in result_hashes,
            "verify_cutoff": lambda row: row["sales_cutoff_at"] == CUTOFF,
            "verify_model_freeze": freeze,
            "verify_coverage": lambda actual: digest(actual) == digest(ledger)}


class ModelSuiteSettlementTests(unittest.TestCase):
    def setUp(self):
        # RED remains an assertion about the absent feature, rather than an import error.
        self.assertIsNotNone(importlib.util.find_spec("race_ai.model_suite_settlement"),
                             "payload-bound per-model settlement bridge is missing")
        self.module = importlib.import_module("race_ai.model_suite_settlement")

    def run_bridge(self, data, **overrides):
        gates = authorities(data)
        gates.update(overrides)
        return self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)

    def assert_blocked(self, data, **gates):
        result = self.run_bridge(data, **gates)
        for model in result["models"].values():
            self.assertIsNone(model["formal_hit_at_8_all"])
        return result

    def test_two_models_score_same_race_with_full_shared_denominator(self):
        result = self.run_bridge(fixture())
        self.assertEqual(list(result["models"]), list(MODELS))
        self.assertEqual(result["models"][MODELS[0]]["formal_hit_at_8_all"], 1 / 3)
        self.assertEqual(result["models"][MODELS[1]]["formal_hit_at_8_all"], 0)
        for model in result["models"].values():
            self.assertEqual(model["eligible_verified_subset"], 3)
            self.assertEqual(model["source_records_preserved"], 3)
        self.assertEqual(result["evidence_status"], "CALLBACK_ATTESTED_UNLESS_INDEPENDENTLY_AUDITED")
        self.assertFalse(result["official_prediction"])

    def test_each_official_fact_is_verified_once_for_identical_model_denominators(self):
        data = fixture()
        seen = []

        def drifting_result_authority(result):
            seen.append(result["race_id"])
            return len(seen) <= 3

        result = self.run_bridge(data, verify_result=drifting_result_authority)
        self.assertEqual(result["models"][MODELS[0]]["eligible_verified_subset"], 3)
        self.assertEqual(result["models"][MODELS[1]]["eligible_verified_subset"], 3)
        self.assertEqual(len(seen), 3)

    def test_missing_model_freeze_keeps_all_races_in_that_models_denominator(self):
        data = fixture()
        data[3].pop()
        result = self.run_bridge(data)
        self.assertEqual(result["models"][MODELS[1]]["eligible_verified_subset"], 3)
        self.assertEqual(result["models"][MODELS[1]]["freeze_verified_subset"], 0)
        self.assertEqual(result["models"][MODELS[1]]["formal_hit_at_8_all"], 0)

    def test_missing_model_output_cannot_remove_predeclared_model(self):
        data = fixture()
        suite = data[2][0]["delivery"]["research_suite"]
        del suite["models"][MODELS[1]]
        suite["ranked_model_ids"].pop()
        suite["model_count"] = 1
        rehash(data[2][0]["delivery"])
        data[3].pop()
        result = self.run_bridge(data)
        self.assertEqual(result["models"][MODELS[1]]["formal_capture_rate"], 0)
        self.assertEqual(result["models"][MODELS[1]]["eligible_verified_subset"], 3)

    def test_no_deliveries_still_has_every_model_and_every_eligible_race(self):
        data = fixture()
        data[2].clear()
        data[3].clear()
        result = self.run_bridge(data)
        for model in result["models"].values():
            self.assertEqual(model["formal_hit_at_8_all"], 0)
            self.assertEqual(model["eligible_verified_subset"], 3)

    def test_defaults_deny_all_formal_proof(self):
        result = self.module.audit_model_settlements(*fixture(), expected_model_ids=MODELS)
        for model in result["models"].values():
            self.assertIsNone(model["formal_hit_at_8_all"])
            self.assertEqual(model["freeze_verified_subset"], 0)

    def test_missing_version_and_source_declarations_cannot_attest_formal_scores(self):
        for versions, source in ((None, None), (None, MODEL_SOURCE_SHA40), (MODEL_VERSIONS, None)):
            with self.subTest(versions=versions, source=source):
                result = self.assert_blocked(fixture(), expected_model_versions=versions,
                                            expected_model_source_sha40=source,
                                            admit_model_roster=lambda declaration: True,
                                            verify_model_freeze=lambda *args, **kwargs: True)
                self.assertFalse(result["model_roster_admitted_by_callback"])
                for model in result["models"].values():
                    self.assertEqual(model["freeze_verified_subset"], 0)

    def test_roster_authority_receives_complete_immutable_declaration(self):
        seen = []

        def declaration_authority(declaration):
            seen.append(declaration)
            return declaration == MODEL_DECLARATION

        result = self.run_bridge(fixture(), admit_model_roster=declaration_authority)
        self.assertEqual(seen, [MODEL_DECLARATION])
        self.assertEqual(result["model_declaration_sha256"], digest(MODEL_DECLARATION))
        self.assertEqual(result["expected_model_source_sha40"], MODEL_SOURCE_SHA40)
        self.assertEqual(result["expected_model_versions"], MODEL_VERSIONS)
        self.assertFalse(result["producer_execution_authenticated_by_library"])
        self.assertEqual(result["models"][MODELS[0]]["formal_hit_at_8_all"], 1 / 3)

    def test_source_pin_outside_independent_declaration_is_denied(self):
        data = fixture()
        observed = []
        gates = authorities(data, observed)
        gates["expected_model_source_sha40"] = "e" * 40
        result = self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
        self.assertFalse(result["model_roster_admitted_by_callback"])
        self.assertEqual(observed, [])
        for model in result["models"].values():
            self.assertIsNone(model["formal_hit_at_8_all"])
            self.assertEqual(model["freeze_verified_subset"], 0)

    def test_malformed_model_declarations_fail_before_external_witness(self):
        bad_versions = ({}, {MODELS[0]: "fixture-1"},
                        {**MODEL_VERSIONS, "undeclared": "fixture-1"},
                        {**MODEL_VERSIONS, MODELS[0]: ""},
                        {**MODEL_VERSIONS, MODELS[0]: "x" * 129},
                        {**MODEL_VERSIONS, MODELS[0]: None}, ["fixture-1"])
        bad_pins = ("a" * 39, "g" * 40, "A" * 40, True, "")
        changes = [{"expected_model_versions": value} for value in bad_versions]
        changes += [{"expected_model_source_sha40": value} for value in bad_pins]
        for change in changes:
            data = fixture()
            observed = []
            gates = authorities(data, observed)
            gates.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
            self.assertEqual(observed, [])

    def test_new_receipt_cannot_bypass_predeclared_model_version(self):
        data = fixture()
        delivery = data[2][0]["delivery"]
        delivery["research_suite"]["models"][MODELS[0]]["model_version"] = "fixture-2"
        rehash(delivery)
        data[3][0]["prediction_sha256"] = delivery["research_suite"]["models"][MODELS[0]]["prediction_sha256"]
        data[3][0]["receipt"]["run_id"] = 999
        data[3][0]["receipt"]["path"] = "audit/freezes/2030-01-15/new-version.json"
        observed = []
        # This new synthetic receipt accepts the replacement's new hash. The
        # separately predeclared version must still stop it before witnessing.
        with self.assertRaises(ValueError):
            self.module.audit_model_settlements(*data, expected_model_ids=MODELS,
                                                 **authorities(data, observed))
        self.assertEqual(observed, [])

    def test_snapshot_purpose_and_roster_each_required_for_formal_scores(self):
        for name in ("validate_snapshot", "allow_source", "admit_model_roster"):
            with self.subTest(gate=name):
                self.assert_blocked(fixture(), **{name: None})
        self.assert_blocked(fixture(), admit_model_roster=lambda ids: False)
        self.assert_blocked(fixture(), allow_source=lambda *args: False)

    def test_unknown_or_duplicate_expected_models_fail(self):
        data = fixture()
        for ids in ((MODELS[0], MODELS[0]), (), (MODELS[0],)):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.module.audit_model_settlements(*data, expected_model_ids=ids,
                                                   **authorities(data))

    def test_changed_picks_with_original_hash_fails_before_external_verifier(self):
        data = fixture()
        observed = []
        gates = authorities(data, observed)
        data[2][0]["delivery"]["research_suite"]["models"][MODELS[0]]["ordered_top8"][0] = [6, 5, 4]
        with self.assertRaises(ValueError):
            self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
        self.assertEqual(observed, [])

    def test_rehashed_changed_model_cannot_use_original_receipt(self):
        data = fixture()
        gates = authorities(data)
        delivery = data[2][0]["delivery"]
        delivery["research_suite"]["models"][MODELS[0]]["research_note"] = "modified-after-freeze"
        rehash(delivery)
        data[3][0]["prediction_sha256"] = delivery["research_suite"]["models"][MODELS[0]]["prediction_sha256"]
        result = self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
        self.assertEqual(result["models"][MODELS[0]]["freeze_verified_subset"], 0)
        self.assertEqual(result["models"][MODELS[0]]["formal_hit_at_8_all"], 0)

    def test_freeze_rejects_independent_picks_and_unknown_fields(self):
        for name, value in (("ordered_top8", [[1, 2, 3]]), ("model_version", "override")):
            data = fixture()
            data[3][0][name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                self.run_bridge(data)

    def test_duplicate_freezes_and_copied_receipts_fail(self):
        data = fixture()
        data[3].append(copy.deepcopy(data[3][0]))
        with self.assertRaises(ValueError):
            self.run_bridge(data)
        data = fixture()
        data[3][1]["receipt"] = copy.deepcopy(data[3][0]["receipt"])
        with self.assertRaises(ValueError):
            self.run_bridge(data)

    def test_unlisted_race_model_wrong_hash_and_cutoff_fail(self):
        for name, value in (("race_id", "boat:2030-01-15:fictional-venue:99"),
                            ("model_id", "not-in-roster"), ("prediction_sha256", "c" * 64),
                            ("cutoff_at", DAY + "T10:01:00+09:00")):
            data = fixture()
            data[3][0][name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                self.run_bridge(data)

    def test_no_fabricated_generation_or_after_cutoff_persistence(self):
        for field, value in (("generated_at", AS_OF),
                             ("persisted_at", CUTOFF),
                             ("generated_at", DAY + "T09:04:00+09:00"),
                             ("generated_at", None)):
            data = fixture()
            data[3][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.run_bridge(data)

    def test_snapshot_mismatch_and_partial_candidate_universe_fail(self):
        for change in ("snapshot", "candidates"):
            data = fixture()
            delivery = data[2][0]["delivery"]
            model = delivery["research_suite"]["models"][MODELS[0]]
            if change == "snapshot":
                model["snapshot_sha256"] = "c" * 64
            else:
                model["candidates"].pop()
            rehash(delivery)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_bridge(data)

    def test_model_asof_revision_and_missing_version_fail(self):
        for field, value in (("as_of", DAY + "T09:30:00+09:00"),
                             ("race_revision", 2), ("race_revision", True),
                             ("model_version", None)):
            data = fixture()
            delivery = data[2][0]["delivery"]
            delivery["research_suite"]["models"][MODELS[0]][field] = value
            rehash(delivery)
            data[3][0]["prediction_sha256"] = delivery["research_suite"]["models"][MODELS[0]]["prediction_sha256"]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_bridge(data)

    def test_learned_artifact_requires_a_separate_availability_contract(self):
        data = fixture()
        delivery = data[2][0]["delivery"]
        delivery["research_suite"]["models"][MODELS[0]]["trained"] = True
        rehash(delivery)
        with self.assertRaisesRegex(ValueError, "learned"):
            self.run_bridge(data)

    def test_trusted_snapshot_validator_must_bind_the_actual_snapshot_hash(self):
        data = fixture()
        with self.assertRaises(ValueError):
            self.run_bridge(data, validate_snapshot=lambda s, **kw: {"snapshot_sha256": "c" * 64})

    def test_horse_alias_receipt_uses_original_model_race_id(self):
        for division in ("horse_jra", "horse_local"):
            data = fixture(division)
            observed = []
            gates = authorities(data, observed)
            result = self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
            self.assertEqual(observed[0][1], "horse:2030-01-15:fictional-venue:1")
            self.assertEqual(result["models"][MODELS[0]]["rows"][0]["race_id"],
                             division + ":2030-01-15:fictional-venue:1")

    def test_jra_local_alias_collision_cannot_reuse_the_same_model_race(self):
        data = fixture("horse_jra")
        other = fixture("horse_local")
        data[0]["records"].append(other[0]["records"][0])
        data[1].append(other[1][0])
        data[2].append(other[2][0])
        for freeze in other[3]:
            freeze["receipt"]["run_id"] += 100
            freeze["receipt"]["path"] = freeze["receipt"]["path"].replace("fixture-", "local-")
        data[3].extend(other[3])
        observed = []
        with self.assertRaises(ValueError):
            self.module.audit_model_settlements(*data, expected_model_ids=MODELS,
                                                 **authorities(data, observed))
        self.assertEqual(observed, [])

    def test_truthy_authority_values_do_not_attest_proof(self):
        for name in ("admit_model_roster", "allow_source", "verify_result", "verify_coverage"):
            with self.subTest(gate=name):
                self.assert_blocked(fixture(), **{name: lambda *args: 1})
        for name in ("verify_model_freeze", "verify_cutoff"):
            result = self.run_bridge(fixture(), **{name: lambda *args, **kw: 1})
            self.assertEqual(result["models"][MODELS[0]]["freeze_verified_subset"], 0)

    def test_new_result_revision_changes_only_evaluation(self):
        data = fixture()
        original = copy.deepcopy(data)
        revision = copy.deepcopy(data[1][0])
        revision.update(revision_no=2, confirmed_at=DAY + "T12:00:00+09:00",
                        payouts=[{"combination": [6, 1, 2], "yen_per_100": 900}])
        data[1].append(revision)
        result = self.run_bridge(data)
        self.assertEqual(result["models"][MODELS[0]]["formal_hit_at_8_all"], 0)
        self.assertEqual(result["models"][MODELS[1]]["formal_hit_at_8_all"], 1 / 3)
        self.assertEqual(data[2:], original[2:])
        self.assertEqual(result["models"][MODELS[0]]["rows"][0]["result_revisions_seen"], 2)

    def test_unverified_newer_result_revision_blocks_stale_scores(self):
        data = fixture()
        gates = authorities(data)
        revision = copy.deepcopy(data[1][0])
        revision.update(revision_no=2, confirmed_at=DAY + "T12:00:00+09:00")
        data[1].append(revision)
        result = self.module.audit_model_settlements(*data, expected_model_ids=MODELS, **gates)
        for model in result["models"].values():
            self.assertIsNone(model["formal_hit_at_8_all"])

    def test_duplicate_result_revision_and_pre_cutoff_final_result_fail(self):
        data = fixture()
        data[1].append(copy.deepcopy(data[1][0]))
        with self.assertRaises(ValueError):
            self.run_bridge(data)
        data = fixture()
        data[1][0]["confirmed_at"] = AS_OF
        with self.assertRaises(ValueError):
            self.run_bridge(data)

    def test_inputs_and_original_forecasts_are_not_mutated(self):
        data = fixture()
        before = copy.deepcopy(data)
        self.run_bridge(data)
        self.assertEqual(data, before)

    def test_existing_numeric_diagnostic_keys_keep_original_hash_semantics(self):
        data = fixture()
        delivery = data[2][0]["delivery"]
        delivery["research_suite"]["models"][MODELS[0]]["diagnostic_buckets"] = {
            1: "fictional-low", 2: "fictional-middle", 10: "fictional-high"}
        rehash(delivery)
        data[3][0]["prediction_sha256"] = delivery["research_suite"]["models"][MODELS[0]]["prediction_sha256"]
        before = copy.deepcopy(data)
        try:
            result = self.run_bridge(data)
        except ValueError as exc:
            self.fail("valid original numeric diagnostic keys changed during copying: " + str(exc))
        self.assertEqual(result["models"][MODELS[0]]["formal_hit_at_8_all"], 1 / 3)
        self.assertEqual(data, before)

    def test_authority_cannot_mutate_scored_original_prediction(self):
        data = fixture()
        before = copy.deepcopy(data)

        def damaging_validator(snapshot, *, allow_source):
            snapshot["race"]["race_revision"] = 99
            return {"snapshot_sha256": digest(snapshot)}

        with self.assertRaises(ValueError):
            self.run_bridge(data, validate_snapshot=damaging_validator)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
