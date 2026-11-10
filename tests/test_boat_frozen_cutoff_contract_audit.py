import unittest
from race_ai.boat_frozen_cutoff_contract_audit import (
    summarize, _old_guard, OLD, NEW
)


def proof(basis=OLD, offset=60):
    return dict(basis=basis, formal_eligible=False,
                roster_identity_verified=True,
                all_originals_saved_before_both=True,
                source_sha256="a" * 64,
                maximum_offset_seconds=offset)


class FrozenCutoffContract(unittest.TestCase):
    def row(self, item):
        return dict(sport="boat", event_date_jst="2026-11-07",
                    result=dict(status="final", source_sha256="a" * 64,
                                cutoff_reconciliation=item))

    def test_registered_legacy_is_first_guard_compatible(self):
        out = summarize(dict(records=[self.row(proof())]))
        self.assertEqual(out["registered_basis"], 1)
        self.assertEqual(out["legacy_first_guard_passed"], 1)
        self.assertEqual(out["legacy_first_guard_failed"], 0)

    def test_per_model_sp_new_basis_rejected_without_new_rule_substitution(self):
        out = summarize(dict(records=[self.row(proof(NEW, 120))]))
        self.assertEqual(out["sp_per_model_basis"], 1)
        self.assertEqual(out["legacy_first_guard_failed"], 1)
        self.assertEqual(out["first_guard_basis_mismatch"], 1)
        self.assertEqual(out["first_guard_offset_out_of_range"], 1)
        self.assertFalse(out["immutable_policy_replaced"])

    def test_source_receipt_mismatch_is_separate_failure(self):
        p=proof();p["source_sha256"]="b"*64
        out=summarize(dict(records=[self.row(p)]))
        self.assertEqual(out["first_guard_other_failure"], 1)
        self.assertEqual(out["first_guard_basis_mismatch"], 0)

    def test_no_proof_not_made_up(self):
        row=self.row(proof())
        row["result"].pop("cutoff_reconciliation")
        out=summarize(dict(records=[row]))
        self.assertEqual(out["reference_results_without_cutoff_proof"], 1)
        self.assertEqual(out["final_with_proof"],0)

    def test_second_gate_does_not_become_final_acceptance(self):
        row=self.row(proof());row["saved_schedule_cutoff_variants"]=["2026-11-07T09:00:00+09:00","2026-11-07T09:01:00+09:00"]
        out=summarize(dict(records=[row]))
        self.assertEqual(out["registered_next_gate_multi_schedule"],1)
        self.assertFalse(out["represents_final_verdict"])

if __name__ == "__main__":
    unittest.main()
