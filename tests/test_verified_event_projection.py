"""Offline contract tests. All races, issuers, keys and outcomes are fictional."""
import itertools
import json
import unittest

from race_ai.verified_event_projection import (
    AdmissionError, SCHEMA, digest, project
)


def example(sport="boat", entrants=6):
    roster = list(range(1, entrants+1))
    candidates = [{"combination": list(triple),
                   "score": 1/(entrants*(entrants-1)*(entrants-2))}
                  for triple in itertools.permutations(roster, 3)]
    forecast = {
        "ordered_top8": [c["combination"] for c in candidates[:8]],
        "candidates": candidates, "model_id": "fictional-model",
        "model_version": "0-test-only", "rationale": "No real training",
        "odds_independent": True,
        "input_sha256": "a"*64,
        "generated_at": "2030-01-01T09:00:00+09:00",
        "persisted_at": "2030-01-01T09:01:00+09:00",
        "cutoff_at": "2030-01-01T10:00:00+09:00",
        "receipt": {"issuer": "fictional-other-clock"},
    }
    forecast["prediction_sha256"] = digest({
        k: v for k,v in forecast.items()
        if k not in {"prediction_sha256", "receipt"}
    })
    race = {
        "race_id": f"{sport}:2030-01-01:fictional:1",
        "sport": sport, "event_date_jst": "2030-01-01",
        "venue": "fictional", "race_no": 1, "cutoff_at": "2030-01-01T10:00:00+09:00",
        "source": {"url": "https://example.org/fictional",
                   "usage_evidence": "TEST ONLY; not a legal rights grant"},
        "entrants": roster, "trifecta_offered": True,
        "forecast": forecast,
        "result_revisions": [{"revision_no": 1, "status": "final",
            "winning_combinations": [candidates[0]["combination"]],
            "payout_yen_per_100": 500,
            "confirmed_at": "2030-01-01T11:00:00+09:00"}],
    }
    return {"schema": SCHEMA, "classification": "REAL_REPORTED", "races": [race]}


def admitted(_source, purpose):
    return purpose in {"analysis", "derived_display"}


class ProjectionTests(unittest.TestCase):
    def test_all_four_sports_can_project_only_with_external_admissions(self):
        for sport, n in (("boat", 6),("keirin", 7),("autorace",8),("horse", 10)):
            with self.subTest(sport=sport):
                source = example(sport, n)
                output = project(source, allow_source=admitted,
                                 verify_freeze=lambda *args: True,
                                 verify_result=lambda *args: True)
                row = output["records"][0]
                self.assertEqual(row["sport"], sport)
                self.assertEqual(len(row["prediction"]["ordered_top8"]), 8)
                self.assertTrue(row["prediction"]["external_receipt_verified"])
                self.assertEqual(row["result"]["status"],"final")

    def test_default_denies_even_when_document_claims_allowed(self):
        output = project(example())
        row = output["records"][0]
        self.assertIsNone(row["prediction"])
        self.assertIsNone(row["result"])
        self.assertEqual(row["offering_status"], "UNKNOWN")
        self.assertEqual(row["no_forecast_reason"], "SOURCE_RIGHTS_NOT_VERIFIED")

    def test_recorder_cannot_self_attest_signed_external_time(self):
        output = project(example(),allow_source=admitted,
                         verify_result=lambda *_: True)
        row = output["records"][0]
        self.assertFalse(row["prediction"]["external_receipt_verified"])
        self.assertIsNotNone(row["result"])
        self.assertEqual(row["no_forecast_reason"], "EXTERNAL_FREEZE_RECEIPT_NOT_VERIFIED")

    def test_unverified_official_result_cannot_produce_hit(self):
        output = project(example(),allow_source=admitted,
                         verify_freeze=lambda *_: True)
        row = output["records"][0]
        self.assertIsNone(row["result"])
        self.assertEqual(row["no_forecast_reason"], "RESULT_SOURCE_UNVERIFIED")

    def test_after_cutoff_is_not_backfilled_as_pre_cutoff(self):
        bundle = example()
        p = bundle["races"][0]["forecast"]
        p["persisted_at"] = "2030-01-01T10:01:00+09:00"
        # The payload has not been re-hashed; failure must be cutoff guard first.
        output=project(bundle,allow_source=admitted)
        self.assertIsNone(output["records"][0]["prediction"])
        self.assertEqual(output["records"][0]["no_forecast_reason"],
                         "NOT_PERSISTED_BEFORE_OFFICIAL_CUTOFF")

    def test_market_features_never_enter_prediction(self):
        bundle=example()
        bundle["races"][0]["forecast"]["market_implied_win_probability"] = 0.9
        with self.assertRaisesRegex(AdmissionError, "market"):
            project(bundle,allow_source=admitted)

    def test_incomplete_candidate_set_is_rejected(self):
        bundle=example()
        bundle["races"][0]["forecast"]["candidates"].pop()
        with self.assertRaisesRegex(AdmissionError, "incomplete"):
            project(bundle,allow_source=admitted)

    def test_top_eight_cannot_be_changed_after_ranking(self):
        bundle=example()
        p=bundle["races"][0]["forecast"]
        p["ordered_top8"][0],p["ordered_top8"][1]=p["ordered_top8"][1],p["ordered_top8"][0]
        with self.assertRaisesRegex(AdmissionError,"top8"):
            project(bundle,allow_source=admitted)

    def test_different_forecast_hash_cannot_pass(self):
        bundle=example()
        bundle["races"][0]["forecast"]["rationale"]="changed"
        with self.assertRaisesRegex(AdmissionError,"digest"):
            project(bundle,allow_source=admitted)

    def test_official_revisions_only_if_authorized_and_monotone(self):
        bundle=example()
        old=bundle["races"][0]["result_revisions"][0]
        correction=dict(old,revision_no=2,confirmed_at="2030-01-01T11:20:00+09:00",
                        winning_combinations=[[3,2,1]])
        bundle["races"][0]["result_revisions"].append(correction)
        result=project(bundle,allow_source=admitted,
                       verify_freeze=lambda *_: True,verify_result=lambda *_: True)
        self.assertEqual(len(result["records"][0]["result_revisions"]),2)
        self.assertEqual(result["records"][0]["result"]["winning_combinations"],[[3,2,1]])

    def test_blocked_or_tokenized_source_url_not_exported(self):
        bundle = example()
        bundle['races'][0]['source']['url'] = 'https://example.org/fictional?token=SECRET'
        blocked = project(bundle)['records'][0]
        self.assertIsNone(blocked['evidence_url'])
        allowed_row = project(bundle, allow_source=admitted)['records'][0]
        self.assertIsNone(allowed_row['evidence_url'])

    def test_multiple_shadow_models_keep_primary_frozen_and_separate(self):
        from copy import deepcopy
        b=example()
        primary=b["races"][0]["forecast"]
        a=deepcopy(primary)
        a["model_id"]="boat-comprehensive-v1"
        a["model_version"]="1"
        a["prediction_sha256"]=digest({k:v for k,v in a.items() if k not in {"receipt","prediction_sha256"}})
        c=deepcopy(a)
        c["model_id"]="boat-scenario-mixture-v1"
        c["model_version"]="1"
        c["ordered_top8"]=list(reversed(c["ordered_top8"]))
        # The Top8 order must still match its complete candidate probabilities.
        # Restore order and change the model identity instead.
        c["ordered_top8"]=a["ordered_top8"]
        c["prediction_sha256"]=digest({k:v for k,v in c.items() if k not in {"receipt","prediction_sha256"}})
        b["races"][0]["comparison_forecasts"]=[a,c]
        projected=project(b,allow_source=admitted,verify_freeze=lambda *_:True,
                          verify_result=lambda *_:True)
        r=projected["records"][0]
        self.assertEqual(len(r["comparison_predictions"]),2)
        self.assertTrue(all(x["external_receipt_verified"] for x in r["comparison_predictions"]))
        self.assertEqual(r["prediction"]["model_id"],"fictional-model")
        self.assertEqual(r["result"]["winning_combinations"],[[1,2,3]])

    def test_unverified_parallel_receipt_does_not_count_as_verified(self):
        b=example()
        a=dict(b["races"][0]["forecast"],model_id="parallel")
        a["prediction_sha256"]=digest({k:v for k,v in a.items() if k not in {"receipt","prediction_sha256"}})
        b["races"][0]["comparison_forecasts"]=[a]
        result=project(b,allow_source=admitted,verify_result=lambda *_:True)
        self.assertEqual(result["records"][0]["comparison_predictions"][0]["external_receipt_verified"],False)

    def test_parallel_model_cannot_duplicate_preselected_primary(self):
        b=example()
        b["races"][0]["comparison_forecasts"]=[b["races"][0]["forecast"]]
        with self.assertRaisesRegex(AdmissionError,"duplicates production"):
            project(b,allow_source=admitted,verify_freeze=lambda *_:True)

    def test_invalid_event_cannot_start_network_fallback(self):
        b=example()
        b["races"][0]["source"]["url"]="file:///etc/passwd"
        with self.assertRaises(AdmissionError):
            project(b,allow_source=admitted)

if __name__ == "__main__":
    unittest.main()
