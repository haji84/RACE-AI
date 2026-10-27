"""Train-only artifact isolation. All records and results are fictional."""
import copy
from datetime import datetime, timezone
import unittest

from test_four_sport_learning import dataset, fit_rows, future
from test_comprehensive_four_sport_models import obs
from race_ai import four_sport_learning as learning
from race_ai.comprehensive_four_sport_models import ModelInputError, RESEARCH, digest


TRAIN_END = "2030-01-07T23:59:00+09:00"
VALID_END = "2030-01-10T23:59:00+09:00"
CREATED = datetime.fromisoformat("2030-01-08T00:00:00+09:00")


class TrainOnlyTests(unittest.TestCase):
    def fit(self, rows=None, **options):
        function = getattr(learning, "fit_training_only", None)
        self.assertTrue(callable(function), "missing train-only fitting entrypoint")
        settings = dict(sport="boat", train_end_at=TRAIN_END, epochs=2,
                        now=lambda: CREATED)
        settings.update(options)
        return function(dataset()[:7] if rows is None else rows, **settings)

    def evaluate(self, rows, model, **options):
        function = getattr(learning, "evaluate_training_candidate", None)
        self.assertTrue(callable(function), "missing separate validation scorer")
        return function(rows, model, validation_end_at=VALID_END, **options)

    def test_train_artifact_has_no_validation_or_test_content(self):
        model = self.fit()
        self.assertEqual(model["model_version"], "0.2-train-only")
        self.assertEqual(model["trained_examples"], 7)
        self.assertEqual(model["trained_until"], TRAIN_END)
        self.assertEqual(model["trained_data_until"], "2030-01-07T02:05:00+00:00")
        self.assertEqual(model["created_at"], CREATED.astimezone(timezone.utc).isoformat())
        self.assertFalse(model["created_at_independently_attested"])
        self.assertFalse(any(k.startswith(("validation", "test", "holdout")) or "diagnostic" in k
                             for k in model))
        self.assertEqual(model["model_sha256"], digest({
            k: v for k, v in model.items() if k != "model_sha256"}))

    def test_new_api_does_not_accept_evaluation_window_arguments(self):
        with self.assertRaises(TypeError):
            self.fit(validation_end_at=VALID_END)
        with self.assertRaises(TypeError):
            self.fit(test_end_at=VALID_END)

    def test_refuses_future_race_instead_of_silently_dropping_it(self):
        with self.assertRaisesRegex(ModelInputError, "training boundary"):
            self.fit(dataset()[:8])

    def test_rejects_result_received_after_training_boundary(self):
        rows = dataset()[:7]
        rows[0]["result"]["captured_at"] = "2030-01-08T01:00:00+09:00"
        with self.assertRaisesRegex(ModelInputError, "result unavailable"):
            self.fit(rows)

    def test_clock_must_be_aware_and_after_training_boundary(self):
        for clock in (lambda: datetime(2030, 1, 8),
                      lambda: datetime(2030, 1, 7, tzinfo=timezone.utc),
                      lambda: "2030-01-08T00:00:00Z"):
            with self.subTest(clock=clock):
                with self.assertRaisesRegex(ModelInputError, "creation clock"):
                    self.fit(now=clock)

    def test_actual_creation_blocks_retroactive_forecast(self):
        late = datetime.fromisoformat("2030-01-16T00:00:00+09:00")
        model = self.fit(now=lambda: late)
        with self.assertRaisesRegex(ModelInputError, "artifact creation"):
            learning.forecast(future(), model)
        timely = self.fit()
        self.assertEqual(learning.forecast(future(), timely)["candidate_count"], 120)

    def test_unchanged_training_kernel_matches_legacy_and_order_is_stable(self):
        model = self.fit(epochs=12)
        self.assertEqual(model["weights"], fit_rows(dataset())["weights"])
        reversed_model = self.fit(list(reversed(dataset()[:7])), epochs=12)
        self.assertEqual(model, reversed_model)

    def test_separate_validation_does_not_mutate_artifact(self):
        model = self.fit()
        before = copy.deepcopy(model)
        report = self.evaluate(dataset()[7:10], model)
        self.assertEqual(model, before)
        self.assertEqual(report["model_sha256"], model["model_sha256"])
        self.assertEqual(report["diagnostics"]["n"], 3)
        altered = dataset()[7:10]
        for row in altered:
            row["result"]["ordered_top3"] = [6, 5, 4]
        self.evaluate(altered, model)
        self.assertEqual(model, before)

    def test_validation_rejects_training_future_and_unavailable_labels(self):
        model = self.fit()
        for rows in (dataset()[6:8], dataset()[9:11]):
            with self.assertRaisesRegex(ModelInputError, "validation window|training cutoff"):
                self.evaluate(rows, model)
        rows = dataset()[7:10]
        rows[0]["result"]["captured_at"] = "2030-01-11T00:00:00+09:00"
        with self.assertRaisesRegex(ModelInputError, "result unavailable"):
            self.evaluate(rows, model)

    def test_validation_verifies_model_hash_and_model_creation(self):
        model = self.fit()
        model["weights"][0] += 1
        with self.assertRaisesRegex(ModelInputError, "integrity"):
            self.evaluate(dataset()[7:10], model)
        model = self.fit(now=lambda: datetime.fromisoformat("2030-01-11T00:00:00+09:00"))
        with self.assertRaisesRegex(ModelInputError, "artifact creation"):
            self.evaluate(dataset()[7:10], model)

    def test_minimum_duplicates_mixed_sport_scope_and_leaks_still_rejected(self):
        cases = []
        cases.append(dataset()[:5])
        duplicate = dataset()[:7]; duplicate[1] = copy.deepcopy(duplicate[0])
        cases.append(duplicate)
        mixed = dataset()[:7]; mixed[0] = dataset("keirin")[0]
        cases.append(mixed)
        mixed_scope = dataset()[:7]; mixed_scope[0]["snapshot"]["scope"] = RESEARCH
        cases.append(mixed_scope)
        leak = dataset()[:7]; leak[0]["snapshot"]["participants"][0]["features"]["market_odds"] = obs(.5)
        cases.append(leak)
        for rows in cases:
            with self.subTest(case=cases.index(rows)):
                with self.assertRaises(ModelInputError):
                    self.fit(rows, allow_source=lambda *_: True, allow_result=lambda *_: True)

    def test_research_requires_input_and_label_admission(self):
        rows = dataset()[:7]
        for row in rows:
            row["snapshot"]["scope"] = RESEARCH
        with self.assertRaises(ModelInputError):
            self.fit(rows)
        with self.assertRaisesRegex(ModelInputError, "result label source"):
            self.fit(rows, allow_source=lambda *_: True)
        model = self.fit(rows, allow_source=lambda *_: True, allow_result=lambda *_: True)
        self.assertEqual(model["trained_on_licensed_real_data"], "REQUIRES_EXTERNAL_AUDIT")

    def test_default_clock_records_current_actual_creation(self):
        import json
        rows = json.loads(json.dumps(dataset()[:7]).replace("2030-", "2000-"))
        before = datetime.now(timezone.utc)
        model = self.fit(rows, train_end_at="2000-01-07T23:59:00+09:00", now=None)
        after = datetime.now(timezone.utc)
        self.assertLessEqual(before, datetime.fromisoformat(model["created_at"]))
        self.assertLessEqual(datetime.fromisoformat(model["created_at"]), after)

    def test_train_only_keeps_all_four_sports_supported(self):
        for sport, n in (("boat", 6), ("keirin", 7), ("autorace", 8), ("horse", 18)):
            with self.subTest(sport=sport):
                model = self.fit(dataset(sport, size=n)[:7], sport=sport)
                output = learning.forecast(future(sport, size=n), model)
                self.assertEqual(output["candidate_count"], n*(n-1)*(n-2))
                self.assertEqual(len(output["ordered_top8"]), 8)

    def test_validation_rejects_duplicate_and_empty_cohorts(self):
        model = self.fit()
        with self.assertRaisesRegex(ModelInputError, "duplicate"):
            self.evaluate([dataset()[7], dataset()[7]], model)
        with self.assertRaisesRegex(ModelInputError, "size"):
            self.evaluate([], model)


if __name__ == "__main__":
    unittest.main()
