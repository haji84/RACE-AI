"""Synthetic contract tests. No provider data, wagers or real rights asserted."""
import copy
import unittest

from race_ai.keirin_preflight import (
    SCHEMA, PreRaceAuditError, audit_pre_race, expected_keys,
)

RID = "keirin:2030-01-15:fictional-venue:1"
STARTERS = [1, 2, 3, 4, 5, 6, 7]
ASOF = "2030-01-15T09:10:00+09:00"
CHECKED = "2030-01-15T09:15:00+09:00"
ISSUED = "2030-01-15T09:20:00+09:00"
CUTOFF = "2030-01-15T10:00:00+09:00"
HASH = "a" * 64


def make_audit():
    return {
        "schema": SCHEMA,
        "race_id": RID,
        "starters": STARTERS,
        "official_cutoff_at": CUTOFF,
        "evidence_sha256": HASH,
        "checked_at": CHECKED,
        "items": [{
            "key": key,
            "status": "verified",
            "reason": None,
            "source_url": "https://example.invalid/fictional-test-source",
            "published_at": "2030-01-15T08:00:00+09:00",
            "captured_at": "2030-01-15T08:05:00+09:00",
            "rights_ref": "SYNTHETIC_FIXTURE_NOT_REAL_LICENSE",
            "observation_sha256": "b" * 64,
        } for key in expected_keys(STARTERS)]
    }


def check(audit):
    return audit_pre_race(
        audit, race_id=RID, starters=STARTERS, cutoff_at=CUTOFF,
        snapshot_as_of=ASOF, issued_at=ISSUED, evidence_sha256=HASH
    )


def missing(item, *, state="unavailable"):
    item.update(status=state, reason="Not independently available at cutoff",
                source_url=None, published_at=None, captured_at=None,
                rights_ref=None, observation_sha256=None)


class KeirinPreflightTests(unittest.TestCase):
    def test_all_items_verified(self):
        audit = make_audit()
        report = check(audit)
        self.assertTrue(report["all_factors_checked"])
        self.assertTrue(report["full_forecast_gate_passed"])
        self.assertEqual(report["verified_count"], len(expected_keys(STARTERS)))
        self.assertFalse(report["probabilities_calibrated"])
        self.assertFalse(report["source_rights_independently_verified"])

    def test_optional_missing_is_recorded_not_imputed(self):
        audit = make_audit()
        missing(next(r for r in audit["items"]
                     if r["key"] == "rider/2/gear_ratio_and_changes"))
        report = check(audit)
        self.assertTrue(report["all_factors_checked"])
        self.assertTrue(report["full_forecast_gate_passed"])
        self.assertEqual(report["unknown_or_unusable_count"], 1)
        self.assertEqual(report["missing_keys"], ["rider/2/gear_ratio_and_changes"])

    def test_critical_unavailable_blocks_full_forecast(self):
        audit = make_audit()
        missing(next(r for r in audit["items"]
                     if r["key"] == "race/line_order_all_riders"))
        report = check(audit)
        self.assertFalse(report["full_forecast_gate_passed"])
        self.assertEqual(report["missing_critical_keys"],
                         ["race/line_order_all_riders"])

    def test_missing_item_rejected(self):
        audit = make_audit()
        audit["items"].pop()
        with self.assertRaisesRegex(PreRaceAuditError, "COUNT"):
            check(audit)

    def test_duplicate_rejected(self):
        audit = make_audit()
        audit["items"][0] = copy.deepcopy(audit["items"][1])
        with self.assertRaisesRegex(PreRaceAuditError, "DUPLICATE"):
            check(audit)

    def test_future_information_rejected(self):
        audit = make_audit()
        audit["items"][0]["published_at"] = "2030-01-15T10:05:00+09:00"
        with self.assertRaisesRegex(PreRaceAuditError, "NOT_PRE_RACE"):
            check(audit)

    def test_source_lacks_rights_ref(self):
        audit = make_audit()
        audit["items"][0]["rights_ref"] = None
        with self.assertRaisesRegex(PreRaceAuditError, "PROVENANCE"):
            check(audit)

    def test_rights_blocked_still_counted_but_never_used(self):
        audit = make_audit()
        missing(next(r for r in audit["items"]
                     if r["key"] == "rider/2/gear_ratio_and_changes"),
                state="rights_blocked")
        report = check(audit)
        self.assertEqual(report["unknown_or_unusable_count"], 1)

    def test_after_cutoff_rejected(self):
        audit = make_audit()
        audit["checked_at"] = "2030-01-15T10:01:00+09:00"
        with self.assertRaisesRegex(PreRaceAuditError, "CUTOFF"):
            check(audit)

    def test_unknown_field_cannot_expand_contract(self):
        audit = make_audit()
        audit["items"].append({
            **copy.deepcopy(audit["items"][0]), "key": "race/odds"
        })
        with self.assertRaisesRegex(PreRaceAuditError, "COUNT"):
            check(audit)



class RealAdapterPreflightGateTests(unittest.TestCase):
    def make_real_snapshot(self, include_audit):
        from hashlib import sha256
        from race_ai.keirin_result_delivery import canonical
        evidence = {
            "schema": "RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1",
            "scope": "OPERATOR_SUPPLIED_RESEARCH",
            "race": {"race_id": RID, "sport": "keirin",
                     "surface": "velodrome", "sales_cutoff_at": CUTOFF,
                     "as_of": ASOF},
            "participants": [{"number": n} for n in STARTERS]
        }
        facts = {"pr71_evidenced_snapshot": evidence}
        if include_audit:
            audit = make_audit()
            audit["evidence_sha256"] = sha256(canonical(evidence)).hexdigest()
            facts["keirin_pre_race_audit_v1"] = audit
        return {
            "schema": "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1",
            "race_id": RID, "starters": STARTERS,
            "as_of": ASOF, "official_cutoff_at": CUTOFF,
            "facts": facts
        }

    def call_model(self, snap, run_suite):
        from race_ai.keirin_pr71_model_adapter import run_pr71_for_next_race
        return run_pr71_for_next_race(
            snap, run_suite=run_suite, verify_suite=lambda _x: False,
            source_admission=lambda _obs: True,
            model_id="multisport-scenario-ensemble-v1",
            issued_at=ISSUED
        )

    def test_real_model_rejects_absent_audit_before_inference(self):
        from race_ai.keirin_pr71_model_adapter import Pr71AdapterError
        called = []
        with self.assertRaisesRegex(Pr71AdapterError,
                                    "COMPLETE_KEIRIN_PRE_RACE_AUDIT_REQUIRED"):
            self.call_model(self.make_real_snapshot(False),
                            lambda *_args, **_kwargs: called.append(True))
        self.assertEqual(called, [])

    def test_real_model_rejects_missing_core_before_inference(self):
        from race_ai.keirin_pr71_model_adapter import Pr71AdapterError
        snap = self.make_real_snapshot(True)
        missing(next(r for r in snap["facts"]["keirin_pre_race_audit_v1"]["items"]
                     if r["key"] == "race/official_sales_cutoff"))
        called = []
        with self.assertRaisesRegex(Pr71AdapterError,
                                    "KEIRIN_PRE_RACE_CORE_FACTORS_NOT_VERIFIED"):
            self.call_model(snap, lambda *_args, **_kwargs: called.append(True))
        self.assertEqual(called, [])

    def test_complete_real_audit_reaches_model_but_is_not_a_rights_grant(self):
        from race_ai.keirin_pr71_model_adapter import Pr71AdapterError
        called = []
        with self.assertRaisesRegex(Pr71AdapterError,
                                    "PR71_SUITE_VERIFICATION_FAILED"):
            self.call_model(self.make_real_snapshot(True),
                            lambda *_args, **_kwargs: called.append(True) or {})
        self.assertEqual(called, [True])

if __name__ == "__main__":
    unittest.main()
