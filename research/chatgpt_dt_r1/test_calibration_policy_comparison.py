"""Synthetic failure cases for research policy, calibration and comparison."""
import copy
import importlib
import itertools
import math
import unittest


def module(name):
    try:
        return importlib.import_module("research.chatgpt_dt_r1." + name)
    except ModuleNotFoundError:
        return None


POLICY, CALIBRATION, COMPARISON = (module(n) for n in ("policy", "calibration", "comparison"))
MODEL_IDS = ["integrated", "codex-independent", "chatgpt-dt-r1"]


def forecast(rid="r1", day="2026-10-01", model_id="chatgpt-dt-r1", cohort="retrospective"):
    triples = list(itertools.permutations([1, 2, 3], 3))
    probabilities = [.50, .20, .10, .08, .07, .05]
    return {
        "race_id": rid, "day": day, "model_id": model_id,
        "model_sha256": ("a" if model_id == "chatgpt-dt-r1" else "b") * 64,
        "input_sha256": "c" * 64, "cohort": cohort,
        "prediction_at": f"{day}T10:00:00+00:00" if cohort == "prospective" else None,
        "cutoff_at": f"{day}T10:30:00+00:00" if cohort == "prospective" else None,
        "field_size": 3, "class": "S", "venue": "fixture", "status": "READY",
        "trifectas": [{"cars": list(t), "probability": p} for t, p in zip(triples, probabilities)],
        "exactas": [{"cars": list(t[:2]), "probability": p} for t, p in zip(triples, probabilities)],
    }


def odds(f, anchor_odds=10.0):
    return {
        "race_id": f["race_id"], "market": "trifecta", "complete": True,
        "published_at": f["day"] + "T10:02:00+00:00",
        "captured_at": f["day"] + "T10:03:00+00:00",
        "source_sha256": "d" * 64, "source": "synthetic_fixture",
        "tickets": [{"cars": t["cars"], "odds": anchor_odds if i == 0 else 2.0}
                    for i, t in enumerate(f["trifectas"])],
    }


def payout_receipt(outcome, amount=150):
    return {"verified": True, "authority": "official", "race_id": outcome["race_id"], "day": outcome["day"],
            "market": "trifecta", "cars": outcome["top3"], "payout_per_100": amount,
            "source_sha256": "d" * 64, "verification_receipt_sha256": "e" * 64}


SPLITS = {
    "fit": {"start": "2025-10-01", "end": "2026-06-30"},
    "tune": {"start": "2026-07-01", "end": "2026-07-31"},
    "calibration": {"start": "2026-08-01", "end": "2026-08-31"},
    "audit": {"start": "2026-09-01", "end": "2026-09-30"},
}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(POLICY, "policy implementation is missing")

    def test_cap_boundaries_and_no_invalid_prices(self):
        for price, want in [(1, 2), (10, 2), (10.001, 4), (20, 4), (20.001, 9), (99.999, 9), (100, 12)]:
            self.assertEqual(POLICY.ticket_cap(price), want)
        for price in [0, -1, float("nan"), float("inf"), True]:
            with self.assertRaises(ValueError):
                POLICY.ticket_cap(price)

    def test_selects_one_profitable_ticket_without_filling_cap(self):
        f = forecast(cohort="prospective")
        selected = POLICY.select_tickets(f, odds(f), decision_at=f["day"] + "T10:04:00Z")
        self.assertEqual(selected["status"], "SELECTED")
        self.assertEqual(selected["ticket_count"], 1)
        self.assertEqual(selected["cap"], 2)
        self.assertEqual(selected["anchor_ticket"], [1, 2, 3])
        self.assertAlmostEqual(selected["raw_coverage"], .5)
        self.assertAlmostEqual(selected["expected_gross"], 500)
        self.assertAlmostEqual(selected["expected_net"], 400)
        self.assertEqual(selected["confidence"], "HOLD")

    def test_odds_cannot_move_anchor_to_longshot_and_expand_cap(self):
        f = forecast(cohort="prospective")
        o = odds(f, 10)
        o["tickets"][-1]["odds"] = 1000
        selected = POLICY.select_tickets(f, o, decision_at=f["day"] + "T10:04:00Z",
                                         config={"min_marginal_probability": 0.0, "min_expected_net_per_unit": -1.0})
        self.assertEqual(selected["cap"], 2)
        self.assertEqual(selected["anchor_ticket"], [1, 2, 3])
        self.assertEqual(selected["ticket_count"], 2)

    def test_partial_or_late_odds_hold_the_entire_selection(self):
        f = forecast(cohort="prospective")
        for mutation in [lambda o: o.update(complete=False), lambda o: o["tickets"].pop(),
                         lambda o: o.update(captured_at=f["day"] + "T10:31:00Z")]:
            o = odds(f)
            mutation(o)
            selected = POLICY.select_tickets(f, o, decision_at=f["day"] + "T10:04:00Z")
            self.assertEqual(selected["status"], "HOLD")
            self.assertEqual(selected["ticket_count"], 0)
            self.assertTrue(selected["hold_reasons"])

    def test_fixed_k_retrospective_preserves_unknown_clocks_and_distinct_policy(self):
        f = forecast()
        one = POLICY.fixed_selection(f, 1)
        two = POLICY.fixed_selection(f, 2)
        self.assertIsNone(one["prediction_at"])
        self.assertIsNone(one["cutoff_at"])
        self.assertAlmostEqual(two["raw_coverage"], .7)
        self.assertNotEqual(one["policy_sha256"], two["policy_sha256"])
        self.assertIsNone(one["expected_net"])
        self.assertEqual(one["confidence"], "HOLD")

    def test_invalid_duplicate_nonfinite_or_inconsistent_joint_distribution_rejected(self):
        mutations = [lambda f: f["trifectas"].append(copy.deepcopy(f["trifectas"][0])),
                     lambda f: f["trifectas"][0].update(probability=float("nan")),
                     lambda f: f["exactas"][0].update(probability=.6),
                     lambda f: f.update(input_sha256="not-a-hash")]
        for mutation in mutations:
            f = forecast()
            mutation(f)
            with self.assertRaises(ValueError):
                POLICY.fixed_selection(f, 1)

    def test_prospective_without_authentic_clocks_is_rejected(self):
        f = forecast()
        f["cohort"] = "prospective"
        with self.assertRaises(ValueError):
            POLICY.fixed_selection(f, 1)

    def test_declared_race_day_cannot_hide_a_future_cutoff(self):
        f = forecast(cohort="prospective")
        f["prediction_at"] = "2026-11-01T10:00:00Z"
        f["cutoff_at"] = "2026-11-01T10:30:00Z"
        with self.assertRaises(ValueError):
            POLICY.fixed_selection(f, 1)

    def test_winning_ticket_need_not_recover_all_stakes(self):
        f = forecast(cohort="prospective")
        selected = POLICY.select_tickets(f, odds(f, 1.5), decision_at=f["day"] + "T10:04:00Z",
                                         config={"min_marginal_probability": 0.0, "min_expected_net_per_unit": -1.0})
        self.assertEqual(selected["ticket_count"], 2)
        self.assertEqual(selected["total_stake"], 200)
        self.assertEqual(selected["hit_returns_at_captured_odds"][0]["net_after_all_stakes"], -50)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(POLICY, "policy implementation is missing")
        self.assertIsNotNone(CALIBRATION, "calibration implementation is missing")
        self.template = POLICY.fixed_selection(forecast(), 1)
        self.lineage = {k: self.template[k] for k in ("model_id", "model_sha256", "policy_sha256")}

    def rows(self, month, *, count=80, hit_every=1, raw=.95, field=3, class_="S", prefix=""):
        rows = []
        for i in range(count):
            row = dict(self.template, race_id=f"{prefix}{month}-{i}", day=f"2026-{month}-{'10' if i % 2 else '11'}",
                       raw_coverage=raw, hit=(i % hit_every == 0), field_size=field, **{"class": class_})
            row.pop("selection_sha256", None)
            rows.append(row)
        return rows

    def fit(self, rows=None, **config):
        return CALIBRATION.fit_calibrator(self.rows("08") if rows is None else rows,
                                          split_manifest=SPLITS, lineage=self.lineage,
                                          config={"min_calibration_n": 20, "min_audit_n": 20, "min_audit_days": 2, **config})

    def target(self, raw=.95):
        row = dict(self.template, raw_coverage=raw)
        row.pop("selection_sha256", None)
        return row

    def test_raw_ninety_five_percent_cannot_receive_label_before_audit(self):
        result = CALIBRATION.assess_selection(self.target(), self.fit())
        self.assertEqual(result["label"], "HOLD")
        self.assertIn("INDEPENDENT_AUDIT_REQUIRED", result["hold_reasons"])

    def test_independent_supported_audit_can_certify_set_coverage(self):
        artifact = CALIBRATION.audit_calibrator(self.fit(), self.rows("09"))
        result = CALIBRATION.assess_selection(self.target(), artifact)
        self.assertEqual(result["label"], "HOT")
        self.assertEqual(result["calibration_n"], 80)
        self.assertEqual(result["audit_n"], 80)
        self.assertGreater(result["audit_ci"][0], .90)
        self.assertEqual(result["ticket_count"], 1)

    def test_sparse_class_fallback_is_explicit_and_never_crosses_ticket_count(self):
        artifact = CALIBRATION.audit_calibrator(self.fit(), self.rows("09"))
        target = self.target()
        target["class"] = "A3"
        result = CALIBRATION.assess_selection(target, artifact)
        self.assertEqual(result["fallback_level"], "field")
        target["ticket_count"] = 2
        result = CALIBRATION.assess_selection(target, artifact)
        self.assertEqual(result["label"], "HOLD")

    def test_bad_audit_does_not_retrain_or_grant_high_confidence(self):
        original = self.fit()
        artifact = CALIBRATION.audit_calibrator(original, self.rows("09", hit_every=2))
        self.assertNotIn("audit", original)
        self.assertEqual(artifact["cells"], original["cells"])
        result = CALIBRATION.assess_selection(self.target(), artifact)
        self.assertEqual(result["label"], "HOLD")

    def test_isotonic_prediction_is_monotonic_after_reversed_observed_rates(self):
        rows = self.rows("08", raw=.3, prefix="lo", hit_every=1) + self.rows("08", raw=.7, prefix="hi", hit_every=2)
        artifact = self.fit(rows)
        lo = CALIBRATION.assess_selection(self.target(.3), artifact)
        hi = CALIBRATION.assess_selection(self.target(.7), artifact)
        self.assertLessEqual(lo["calibrated_probability"], hi["calibrated_probability"])

    def test_temporal_overlap_duplicate_race_and_lineage_mismatch_rejected(self):
        bad_splits = copy.deepcopy(SPLITS)
        bad_splits["audit"]["start"] = "2026-08-31"
        with self.assertRaises(ValueError):
            CALIBRATION.fit_calibrator(self.rows("08"), split_manifest=bad_splits, lineage=self.lineage)
        rows = self.rows("08")
        with self.assertRaises(ValueError):
            self.fit(rows + [copy.deepcopy(rows[0])])
        rows[0]["model_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.fit(rows)

    def test_audit_overlap_and_mutated_artifact_rejected(self):
        fitted = self.fit()
        audit = self.rows("09")
        audit[0]["race_id"] = "08-0"
        with self.assertRaises(ValueError):
            CALIBRATION.audit_calibrator(fitted, audit)
        fitted["lineage"]["model_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            CALIBRATION.assess_selection(self.target(), fitted)

    def test_policy_mismatch_and_seen_audit_race_hold(self):
        fitted = CALIBRATION.audit_calibrator(self.fit(), self.rows("09"))
        target = self.target()
        target["policy_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            CALIBRATION.assess_selection(target, fitted)
        target = self.target()
        target["race_id"] = "09-0"
        result = CALIBRATION.assess_selection(target, fitted)
        self.assertEqual(result["label"], "HOLD")

    def test_training_calibration_rows_cannot_relabel_fixed_one_as_two(self):
        rows = self.rows("08")
        rows[0]["ticket_count"] = 2
        with self.assertRaises(ValueError):
            self.fit(rows)

    def test_calibration_source_clock_cannot_cross_the_declared_day(self):
        rows = self.rows("08")
        rows[0].update(prediction_at="2026-10-01T10:00:00Z", cutoff_at="2026-10-01T10:30:00Z")
        with self.assertRaises(ValueError):
            self.fit(rows)

    def test_retrospective_support_does_not_silently_certify_prospective_use(self):
        fitted = CALIBRATION.audit_calibrator(self.fit(), self.rows("09"))
        row = self.target()
        row.update(cohort="prospective", prediction_at="2026-10-01T10:00:00Z", cutoff_at="2026-10-01T10:30:00Z")
        result = CALIBRATION.assess_selection(row, fitted)
        self.assertEqual(result["label"], "HOLD")
        self.assertIn("COHORT_TRANSFER_UNVALIDATED", result["hold_reasons"])


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(COMPARISON, "comparison implementation is missing")
        self.registry = [{"race_id": "r1", "day": "2026-10-01"}, {"race_id": "r2", "day": "2026-10-02"}]
        self.outcomes = [{**r, "top3": [1, 2, 3], "status": "settled", "field_size": 3, "class": "S", "venue": "fixture"}
                         for r in self.registry]

    def compare(self, forecasts, **kwargs):
        return COMPARISON.compare_models(forecasts, self.outcomes, self.registry,
                                         expected_model_ids=MODEL_IDS, bootstrap_samples=200, seed=7, **kwargs)

    def test_missing_predictions_stay_in_all_target_denominator_and_no_fake_winner(self):
        report = self.compare([forecast()])
        own = report["all_target"]["models"]["chatgpt-dt-r1"]
        self.assertEqual(own["eligible_n"], 2)
        self.assertEqual(own["forecast_n"], 1)
        self.assertEqual(own["trifecta"]["hit_at"]["1"]["rate"], .5)
        self.assertEqual(own["hold_reasons"]["MISSING_FORECAST"], 1)
        self.assertEqual(report["common_cohort"]["eligible_n"], 0)
        self.assertIsNone(report["verdict"]["winner"])
        self.assertIn("MISSING_MODEL_ROWS", report["verdict"]["reasons"])

    def test_joint_nll_brier_and_fixed_point_calibration_are_computed_on_actual_outcome(self):
        report = self.compare([forecast()])
        market = report["all_target"]["models"]["chatgpt-dt-r1"]["trifecta"]
        self.assertAlmostEqual(market["nll"], math.log(2))
        self.assertAlmostEqual(market["brier"], .3138)
        self.assertEqual(market["score_n"], 1)
        self.assertEqual(sum(x["n"] for x in market["calibration"]["1"]), 1)

    def test_common_cohort_excludes_input_mismatch_but_not_all_target(self):
        forecasts = [forecast(model_id=m) for m in MODEL_IDS]
        forecasts[-1]["input_sha256"] = "f" * 64
        report = self.compare(forecasts)
        self.assertEqual(report["common_cohort"]["eligible_n"], 0)
        reasons = report["common_cohort"]["exclusion_reasons"]
        self.assertEqual(reasons["INPUT_MISMATCH"], 1)
        self.assertEqual(report["all_target"]["models"]["chatgpt-dt-r1"]["forecast_n"], 1)

    def test_prospective_late_forecast_is_a_miss_and_not_relabelled_retrospective(self):
        f = forecast(cohort="prospective")
        f["prediction_at"] = "2026-10-01T10:31:00Z"
        report = self.compare([f])
        own = report["all_target"]["models"]["chatgpt-dt-r1"]
        self.assertEqual(own["forecast_n"], 0)
        self.assertEqual(own["eligible_n"], 2)
        self.assertTrue(own["hold_reasons"])

    def test_duplicates_and_unregistered_model_or_race_rejected(self):
        f = forecast()
        for rows in [[f, copy.deepcopy(f)], [forecast(model_id="fabricated-rival")], [forecast(rid="unknown")]]:
            with self.assertRaises(ValueError):
                self.compare(rows)
        with self.assertRaises(ValueError):
            COMPARISON.compare_models([], [], self.registry, expected_model_ids=["only-one"])

    def test_settled_incident_stays_eligible_cancelled_does_not(self):
        self.outcomes[0]["incidents"] = ["DNF_tail"]
        self.outcomes[1]["status"] = "cancelled"
        report = self.compare([forecast()])
        self.assertEqual(report["all_target"]["eligible_n"], 1)
        self.assertEqual(report["registry"]["excluded_status_counts"]["cancelled"], 1)
        self.assertTrue(report["conditional_distribution_caveat"])

    def test_day_block_bootstrap_is_deterministic_and_paired(self):
        rows = [forecast(rid=r["race_id"], day=r["day"], model_id=m) for r in self.registry for m in MODEL_IDS]
        a = self.compare(rows)
        b = self.compare(rows)
        self.assertEqual(a["paired_bootstrap"], b["paired_bootstrap"])
        item = a["paired_bootstrap"][0]
        self.assertEqual(item["day_n"], 2)
        self.assertEqual(item["metrics"]["trifecta_hit_at_1"]["ci"], [0.0, 0.0])
        self.assertIsNone(a["verdict"]["winner"])

    def test_model_version_drift_is_not_aggregated_as_one_entrant(self):
        rows = [forecast(), forecast(rid="r2", day="2026-10-02")]
        rows[1]["model_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.compare(rows)

    def test_external_participant_pins_reject_unknown_missing_and_changed_model(self):
        rows = [forecast(model_id=m) for m in MODEL_IDS]
        policy_sha = POLICY.fixed_selection(rows[0], 1)['policy_sha256']
        pins = {r['model_id']: {'model_sha256': r['model_sha256'], 'policy_sha256': policy_sha} for r in rows}
        for invalid in [dict(list(pins.items())[:2]), dict(pins, unknown=pins[MODEL_IDS[0]]),
                        dict(pins, **{MODEL_IDS[0]: {'model_sha256': 'b' * 64}}),
                        dict(pins, **{MODEL_IDS[0]: dict(pins[MODEL_IDS[0]], private_value='not-allowed')})]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.compare(rows, expected_participant_pins=invalid)
        pins[MODEL_IDS[0]]['model_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'MODEL_MANIFEST_MISMATCH'):
            self.compare(rows, expected_participant_pins=pins)

    def test_pinned_policy_mismatch_holds_actual_selection_without_erasing_distribution(self):
        f = forecast()
        f['selection'] = POLICY.fixed_selection(f, 2)
        one_policy = POLICY.fixed_selection(f, 1)['policy_sha256']
        pins = {model: {'model_sha256': forecast(model_id=model)['model_sha256'],
                        'policy_sha256': one_policy} for model in MODEL_IDS}
        report = self.compare([f], expected_participant_pins=pins)
        own = report['all_target']['models']['chatgpt-dt-r1']
        self.assertEqual(own['forecast_n'], 1)
        self.assertEqual(own['trifecta']['hit_at']['1']['n'], 2)
        self.assertEqual(own['actual_selection']['presented_n'], 0)
        self.assertEqual(own['actual_selection']['hold_reasons'], {'POLICY_PIN_MISMATCH': 1})
        self.assertFalse(report['participant_manifest']['independently_authenticated'])
        self.assertIsNone(report['verdict']['winner'])

    def test_feature_schema_pin_rejects_changed_or_missing_schema_as_counted_hold(self):
        f = forecast()
        pins = {model: {'model_sha256': forecast(model_id=model)['model_sha256'],
                        'policy_sha256': POLICY.fixed_selection(f, 1)['policy_sha256']} for model in MODEL_IDS}
        pins['chatgpt-dt-r1']['feature_schema_sha256'] = 'd' * 64
        for schema in [None, 'e' * 64]:
            with self.subTest(schema=schema):
                row = dict(f, feature_schema_sha256=schema)
                report = self.compare([row], expected_participant_pins=pins)
                own = report['all_target']['models']['chatgpt-dt-r1']
                self.assertEqual(own['forecast_n'], 0)
                self.assertEqual(own['eligible_n'], 2)
                self.assertEqual(own['hold_reasons']['FEATURE_SCHEMA_PIN_MISMATCH'], 1)
        report = self.compare([dict(f, feature_schema_sha256='d' * 64)], expected_participant_pins=pins)
        self.assertEqual(report['all_target']['models']['chatgpt-dt-r1']['forecast_n'], 1)

    def test_conflicting_model_and_participant_manifests_are_not_silently_overridden(self):
        f = forecast()
        pins = {model: {'model_sha256': forecast(model_id=model)['model_sha256'],
                        'policy_sha256': POLICY.fixed_selection(f, 1)['policy_sha256']} for model in MODEL_IDS}
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_MODEL_MANIFESTS'):
            self.compare([f], expected_participant_pins=pins,
                         expected_model_sha256={'chatgpt-dt-r1': 'f' * 64})

    def shared_binding(self):
        self.registry[0].update(input_sha256='c' * 64, cohort='retrospective', cutoff_at=None,
            history_snapshot_sha256='1' * 64, dataset_snapshot_sha256='2' * 64,
            context_snapshot_sha256='3' * 64, context_as_of='2026-11-28T00:00:00Z')
        return dict(self.registry[0])

    def test_strict_shared_materials_allow_independent_feature_schemas(self):
        binding = self.shared_binding()
        shared = POLICY.digest({'schema': 'dt-r1-shared-evidence-v1', **binding})
        rows = [dict(forecast(model_id=model), shared_evidence_sha256=shared,
                     feature_input_sha256=str(i + 4) * 64, feature_schema_sha256=str(i + 4) * 64)
                for i, model in enumerate(MODEL_IDS)]
        report = self.compare(rows, require_shared_evidence=True)
        self.assertEqual(report['common_cohort']['eligible_n'], 1)
        self.assertEqual(report['shared_evidence']['status'], 'ENFORCED')
        self.assertEqual(report['shared_evidence']['admitted_matching_forecasts'], 3)
        self.assertFalse(report['shared_evidence']['independently_authenticated'])
        self.assertIsNone(report['verdict']['winner'])

    def test_strict_prospective_materials_must_exist_at_prediction_time(self):
        self.shared_binding()
        self.registry[0].update(cohort='prospective', cutoff_at='2026-10-01T10:30:00Z',
                                context_as_of='2026-10-01T10:20:00Z')
        shared = POLICY.shared_evidence_digest(self.registry[0])
        rows = [dict(forecast(model_id=model, cohort='prospective'), shared_evidence_sha256=shared)
                for model in MODEL_IDS]
        report = self.compare(rows, require_shared_evidence=True)
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertEqual(report['all_target']['eligible_n'], 2)
        for model in MODEL_IDS:
            self.assertEqual(report['all_target']['models'][model]['hold_reasons']['SHARED_EVIDENCE_AFTER_PREDICTION'], 1)
        self.registry[0]['context_as_of'] = rows[0]['prediction_at']
        for row in rows: row['shared_evidence_sha256'] = POLICY.shared_evidence_digest(self.registry[0])
        report = self.compare(rows, require_shared_evidence=True)
        self.assertEqual(report['common_cohort']['eligible_n'], 1)

    def test_strict_shared_materials_bind_history_sources_context_and_clock(self):
        original = self.shared_binding()
        shared = POLICY.digest({'schema': 'dt-r1-shared-evidence-v1', **original})
        rows = [dict(forecast(model_id=model), shared_evidence_sha256=shared) for model in MODEL_IDS]
        for field, value in [('history_snapshot_sha256', '4' * 64), ('dataset_snapshot_sha256', '4' * 64),
                             ('context_snapshot_sha256', '4' * 64), ('context_as_of', '2026-11-28T01:00:00Z')]:
            with self.subTest(field=field):
                self.registry[0] = dict(original, **{field: value})
                report = self.compare(rows, require_shared_evidence=True)
                self.assertEqual(report['all_target']['eligible_n'], 2)
                self.assertEqual(report['common_cohort']['eligible_n'], 0)
                for model in MODEL_IDS:
                    own = report['all_target']['models'][model]
                    self.assertEqual(own['forecast_n'], 0)
                    self.assertEqual(own['hold_reasons']['SHARED_EVIDENCE_MISMATCH'], 1)

    def test_strict_shared_materials_missing_evidence_stays_in_denominator(self):
        binding = self.shared_binding()
        shared = POLICY.digest({'schema': 'dt-r1-shared-evidence-v1', **binding})
        rows = [dict(forecast(model_id=model), shared_evidence_sha256=shared) for model in MODEL_IDS]
        del rows[0]['shared_evidence_sha256']
        report = self.compare(rows, require_shared_evidence=True)
        self.assertEqual(report['all_target']['models'][MODEL_IDS[0]]['hold_reasons']['SHARED_EVIDENCE_REQUIRED'], 1)
        self.assertEqual(report['all_target']['models'][MODEL_IDS[1]]['forecast_n'], 1)
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        del self.registry[0]['history_snapshot_sha256']
        report = self.compare(rows, require_shared_evidence=True)
        self.assertEqual(report['all_target']['eligible_n'], 2)
        for model in MODEL_IDS:
            self.assertEqual(report['all_target']['models'][model]['hold_reasons']['SHARED_EVIDENCE_BINDING_INCOMPLETE'], 1)
        legacy = self.compare(rows)
        self.assertEqual(legacy['common_cohort']['eligible_n'], 1)
        self.assertEqual(legacy['shared_evidence']['status'], 'NOT_REQUESTED')
        self.assertIsNone(legacy['shared_evidence']['admitted_matching_forecasts'])

    def test_actual_selection_set_coverage_and_verified_payout_are_separate(self):
        f = forecast()
        f["selection"] = POLICY.fixed_selection(f, 2)
        self.outcomes[0]["payout_per_100"] = 150
        self.outcomes[0]["payout_verification"] = payout_receipt(self.outcomes[0])
        report = self.compare([f])
        selected = report["all_target"]["models"]["chatgpt-dt-r1"]["actual_selection"]
        self.assertEqual(selected["presented_n"], 1)
        self.assertEqual(selected["hit_rate_all_target"], .5)
        self.assertEqual(selected["net_on_payout_scored"], -50)
        self.assertEqual(selected["hit_but_net_loss_n"], 1)

    def test_unverified_payout_never_becomes_zero_or_claimed_realised_return(self):
        f = forecast()
        f["selection"] = POLICY.fixed_selection(f, 2)
        self.outcomes[0]["payout_per_100"] = 150
        report = self.compare([f])
        selected = report["all_target"]["models"]["chatgpt-dt-r1"]["actual_selection"]
        self.assertEqual(selected["hits"], 1)
        self.assertEqual(selected["payout_scored_n"], 0)
        self.assertEqual(selected["payout_unverified_n"], 1)
        self.assertIsNone(selected["net_on_payout_scored"])

    def test_payout_verification_must_bind_market_ticket_source_and_amount(self):
        f = forecast()
        f["selection"] = POLICY.fixed_selection(f, 1)
        self.outcomes[0]["payout_per_100"] = 150
        for key, value in [("market", "exacta"), ("cars", [3, 2, 1]), ("source_sha256", "bad"),
                           ("payout_per_100", 1000), ("race_id", "wrong"), ("verified", False)]:
            receipt = payout_receipt(self.outcomes[0])
            receipt[key] = value
            self.outcomes[0]["payout_verification"] = receipt
            selected = self.compare([f])["all_target"]["models"]["chatgpt-dt-r1"]["actual_selection"]
            self.assertEqual(selected["payout_scored_n"], 0)
            self.assertEqual(selected["payout_unverified_n"], 1)
            self.assertIsNone(selected["gross_on_payout_scored"])

    def test_declared_prospective_clocks_are_labelled_unattested_shadow(self):
        rows = [forecast(model_id=m, cohort="prospective") for m in MODEL_IDS]
        report = self.compare(rows)
        self.assertEqual(report["common_cohort"]["eligible_n"], 1)
        self.assertEqual(report["prospective_evidence"]["status"], "SHADOW_UNATTESTED")
        self.assertFalse(report["prospective_evidence"]["formal_comparison_verified"])
        self.assertIsNone(report["verdict"]["winner"])

    def test_common_cohort_does_not_mix_retro_and_prospective(self):
        rows = [forecast(model_id=m) for m in MODEL_IDS]
        rows[-1] = forecast(model_id=MODEL_IDS[-1], cohort="prospective")
        report = self.compare(rows)
        self.assertEqual(report["common_cohort"]["eligible_n"], 0)
        self.assertEqual(report["common_cohort"]["exclusion_reasons"]["COHORT_MISMATCH"], 1)


if __name__ == "__main__":
    unittest.main()
