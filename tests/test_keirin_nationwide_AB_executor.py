"""79-race orchestration contract: every source and result in this test is FAKE."""
import json
from pathlib import Path
import unittest

from race_ai import keirin_nationwide_AB_executor as executor
from race_ai import keirin_nationwide_active_AB as national
from race_ai import keirin_available_prediction_audit as arm

REGISTRY=(Path(__file__).resolve().parents[1]/
    "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json")
RACE="202611182401"
START="2026-11-18T07:25:00+09:00"
CUT="2026-11-18T20:45:00+09:00"
PHASES={p:"HYPOTHESIS_NOT_OBSERVED "+p for p in arm.PHASES}


def reg():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def live():
    return {
        "source_sha256":"a"*64,
        "source_available_at":"2026-11-18T07:10:00+09:00",
        "cutoff_at":CUT,
        "verified_field_count":21,
        "starters":[1,2,3,4,5,6],
        "competition":"CHALLENGE",
    }


def generated(rid,source):
    return {
        "A_existing":arm.make_arm(
            race_id=rid,arm="EXISTING_GENERATED",
            source_document_sha256="b"*64,
            common_input_sha256=source["source_sha256"],
            observed_as_of=START,
            generated_at="2026-11-18T07:26:00+09:00",
            official_cutoff_at=source["cutoff_at"],
            ranked_tickets=[[1,2,3],[1,3,2]]),
        "B_six_phase":arm.make_arm(
            race_id=rid,arm="SIX_PHASE",
            source_document_sha256="c"*64,
            common_input_sha256=source["source_sha256"],
            observed_as_of=START,
            generated_at="2026-11-18T07:26:00+09:00",
            official_cutoff_at=source["cutoff_at"],
            ranked_tickets=[[1,3,2],[1,2,3]],
            phase_hypotheses=PHASES),
    }


def sealing(rid,products,source):
    return {
        "race_id":rid,
        "A_arm_sha256":products["A_existing"]["arm_digest_sha256"],
        "B_arm_sha256":products["B_six_phase"]["arm_digest_sha256"],
        "A_cipher_sha256":"d"*64,
        "B_cipher_sha256":"e"*64,
        "sealed_at":"2026-11-18T07:26:10+09:00",
    }


def do(**kw):
    args={
        "registry":reg(),
        "source_by_race":{RACE:live()},
        "inspected_at":START,
        "generate_private_AB":generated,
        "seal_private_AB":sealing,
        "verify_owner_source":lambda *args:True,
        "verify_official_cutoff":lambda *args:True,
        "verify_independent_cipher":lambda *args:True,
    }
    args.update(kw)
    return executor.execute_all(**args)


class NationwidePrivateABExecutor(unittest.TestCase):
    def test_without_sources_keeps_every_race_a_HOLD(self):
        out=do(source_by_race={})
        self.assertEqual(out["states"],{"HOLD_MISSING_RACE_INPUT":79})
        self.assertEqual(out["A_generated"],0)
        self.assertEqual(out["official_results_settled"],0)
        self.assertEqual(len(out["records"]),79)

    def test_one_synthetic_six_rider_A_B_and_78_HOLD(self):
        out=do()
        self.assertEqual(out["cohort_race_count"],79)
        self.assertEqual(out["A_generated"],1)
        self.assertEqual(out["B_generated"],1)
        self.assertEqual(out["cipher_created"],1)
        self.assertEqual(out["independent_cipher_readback"],1)
        self.assertEqual(out["states"]["HOLD_MISSING_RACE_INPUT"],78)
        self.assertEqual(out["states"]["A_B_INDEPENDENT_CIPHERTEXT_READBACK"],1)
        self.assertFalse(out["old_four_models_required"])
        self.assertTrue(out["no_plaintext_tickets_or_riders_in_output"])
        self.assertNotIn("ranked_tickets",json.dumps(out))
        self.assertEqual(out["official_results_settled"],0)

    def test_missing_independent_source_cannot_generate(self):
        out=do(verify_owner_source=None)
        self.assertEqual(out["A_generated"],0)
        self.assertEqual(out["B_generated"],0)
        self.assertEqual(out["states"]["HOLD_MISSING_RACE_INPUT"],79)

    def test_missing_cutoff_does_not_guess(self):
        out=do(verify_official_cutoff=None)
        self.assertEqual(out["states"]["HOLD_NO_INDEPENDENT_CUTOFF"],1)
        self.assertEqual(out["A_generated"],0)

    def test_unavailable_model_generator_keeps_79_denominator(self):
        out=do(generate_private_AB=None)
        self.assertEqual(out["states"]["HOLD_NO_VALID_GENERATED_A_B"],1)
        self.assertEqual(out["states"]["HOLD_MISSING_RACE_INPUT"],78)

    def test_missing_sealer_cannot_claim_A_B_cipher_saved(self):
        out=do(seal_private_AB=None)
        self.assertEqual(out["states"]["A_B_COMPUTED_PRIVATE_NOT_YET_SEALED"],1)
        self.assertEqual(out["cipher_created"],0)

    def test_missing_second_runner_witness_never_claims_readback(self):
        out=do(verify_independent_cipher=None)
        self.assertEqual(out["cipher_created"],1)
        self.assertEqual(out["independent_cipher_readback"],0)
        self.assertEqual(out["states"]["A_B_ENCRYPTED_CIPHER_CREATED_READBACK_PENDING"],1)

    def test_cipher_saved_too_late_does_not_count_as_evidence(self):
        def late(rid,products,source):
            r=sealing(rid,products,source)
            r["sealed_at"]="2026-11-18T20:44:40+09:00"
            return r
        out=do(seal_private_AB=late)
        self.assertEqual(out["cipher_created"],0)
        self.assertEqual(out["states"]["HOLD_AFTER_DEADLINE"],1)

    def test_A_or_B_from_different_input_sha_rejected(self):
        def wrong(rid,source):
            x=generated(rid,source)
            x["B_six_phase"]["common_input_sha256"]="f"*64
            return x
        out=do(generate_private_AB=wrong)
        self.assertEqual(out["states"]["HOLD_NO_VALID_GENERATED_A_B"],1)

    def test_6_7_9_rider_source_coverage_and_separate_result_stage(self):
        for starters in ([1,2,3,4,5,6],
                         [1,2,3,4,5,6,7],
                         [1,2,3,4,5,6,7,8,9]):
            with self.subTest(n=len(starters)):
                x=live();x["starters"]=starters
                out=do(source_by_race={RACE:x})
                self.assertEqual(out["A_generated"],1)
                self.assertEqual(out["official_results_settled"],0)

    def test_dynamic_tomorrow_with_seven_races_without_79_hardcode(self):
        from race_ai import keirin_dynamic_nationwide_registry as daily
        source={
            "venue":"架空会場","venue_code":"01","grade":"F2",
            "source_url":"https://example.org/public-calendar",
            "source_bytes_sha256":"a"*64,
            "source_available_at":"2026-11-19T06:00:00+09:00",
            "race_numbers":[1,2,3,4,5,6,7],
            "source_race_day":"2026-11-19",
        }
        verified=daily.create_day(
            day_jst="2026-11-19",
            registered_at="2026-11-19T06:30:00+09:00",
            venue_snapshots=[source],
            expected_venue_codes=["01"],
            independently_verify_venue_snapshot=lambda x:True,
            independently_verify_whole_day=lambda *args:True)
        out=executor.execute_all(
            registry=verified,source_by_race={},
            inspected_at="2026-11-19T06:40:00+09:00")
        self.assertEqual(out["cohort_race_count"],7)
        self.assertTrue(out["national_source_universe_independently_verified"])
        self.assertEqual(out["states"],{"HOLD_MISSING_RACE_INPUT":7})
        self.assertFalse(out["old_four_models_required"])

    def test_unverified_dynamic_venue_universe_cannot_claim_complete(self):
        from race_ai import keirin_dynamic_nationwide_registry as daily
        source={
            "venue":"架空会場","venue_code":"01","grade":"F2",
            "source_url":"https://example.org/public-calendar",
            "source_bytes_sha256":"a"*64,
            "source_available_at":"2026-11-19T06:00:00+09:00",
            "race_numbers":[1,2],
            "source_race_day":"2026-11-19",
        }
        unverified=daily.create_day(
            day_jst="2026-11-19",
            registered_at="2026-11-19T06:30:00+09:00",
            venue_snapshots=[source],
            expected_venue_codes=None,
            independently_verify_venue_snapshot=lambda x:True,
            independently_verify_whole_day=None)
        out=executor.execute_all(
            registry=unverified,source_by_race={},
            inspected_at="2026-11-19T06:40:00+09:00")
        self.assertEqual(out["cohort_race_count"],2)
        self.assertTrue(out["national_universe_HOLD"])
        self.assertFalse(out["national_source_universe_independently_verified"])

    def test_unknown_source_race_rejected_not_hidden(self):
        with self.assertRaisesRegex(national.NationwideABError,"OUTSIDE_COHORT"):
            do(source_by_race={"202611189901":live()})


if __name__=="__main__":
    unittest.main()
