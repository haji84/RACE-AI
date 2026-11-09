"""Synthetic WINTICKET SSR to existing A/B input-gap contract."""
from copy import deepcopy
import json
import unittest

from race_ai.keirin_real_source_gap_report import (
    inspect_source_gaps, RealSourceGapError
)
from race_ai.keirin_winticket_embedded_racecard import racecard_from_public_html
from tests.test_keirin_winticket_embedded_racecard import (
    fixture,URL,RACE,CAPTURE,CUTOFF,
)


def source():
    return racecard_from_public_html(
        fixture(),url=URL,race_id=RACE,captured_at=CAPTURE,
        expected_cutoff_at=CUTOFF
    )


class SourceOnlyPreflightTests(unittest.TestCase):
    def test_reuse_exact_347_and_model_a_b_source_slots_without_fake_inputs(self):
        counts=inspect_source_gaps(source())
        self.assertEqual(counts["race_id"],RACE)
        self.assertEqual(counts["inspection_registry_total"],347)
        self.assertEqual(counts["entrant_count"],7)
        self.assertEqual(counts["source_observed_registry_count"],75)
        self.assertEqual(counts["not_source_observed_registry_count"],272)
        self.assertGreater(counts["source_unobserved_critical_slots"],0)
        a=counts["model_A_source_coverage"]
        b=counts["model_B_source_coverage"]
        self.assertEqual(a["required_model_input_slots"],93)
        self.assertEqual(b["required_model_input_slots"],93)
        # Score and complete same-record top3 rate are actual source fields.
        # Others, including acceleration, line and venue fit, are absent.
        # H is a sourced 347 inspection field but not in the pinned
        # four-model mandatory subset. Never report it as filling the 79.
        self.assertEqual(a["source_observed_required_slots"],14)
        self.assertEqual(b["source_observed_required_slots"],14)
        self.assertEqual(a["source_unobserved_required_slots"],79)
        self.assertEqual(b["source_unobserved_required_slots"],79)
        # Source-gap prioritization must account for every missing model
        # input WITHOUT leaking athlete names or substituting fake zeros.
        for model in (a,b):
            deficit=model["missing_model_input_slots_by_source_field"]
            self.assertEqual(sum(deficit.values()),
                             model["source_unobserved_required_slots"])
            self.assertTrue(all(isinstance(key,str) and
                                "rider/" not in key for key in deficit))
            self.assertTrue(all(isinstance(count,int) and count>0
                                for count in deficit.values()))
        self.assertNotIn("fictional-rider",json.dumps(counts))
        self.assertFalse(counts["owner_private_actual_prediction_frozen"])
        self.assertFalse(counts["source_usage_rights_independently_verified"])
        self.assertFalse(counts["real_pr71_four_models_ran"])
        self.assertEqual(counts["decision"],"HOLD_MISSING_SOURCE_EVIDENCE")
        self.assertNotIn("fictional-rider",json.dumps(counts))
        self.assertNotIn("racePoint",json.dumps(counts))

    def test_absent_source_rates_do_not_turn_into_missing_score_zero(self):
        def omit(data):
            data["records"][0].pop("firstRate")
        packet=racecard_from_public_html(
            fixture(mutation=omit),url=URL,race_id=RACE,
            captured_at=CAPTURE,expected_cutoff_at=CUTOFF)
        counts=inspect_source_gaps(packet)
        self.assertEqual(
            counts["model_A_source_coverage"]["source_observed_required_slots"],13)
        self.assertEqual(
            counts["model_A_source_coverage"]["source_unobserved_required_slots"],80)
        self.assertFalse(
            counts["model_B_source_coverage"]["all_required_fields_observed"])

    def test_required_numeric_sources_cannot_claim_coverage_from_bad_values(self):
        # Keep registry keys and counts perfectly consistent, but inject
        # invalid model inputs. Membership checks alone used to count these.
        for key,invalid in (
            ("rider/1/race_score","101.4"),
            ("rider/1/race_score",True),
            ("rider/1/race_score",-1),
            ("rider/1/top_three_rate",1.2),
            ("rider/1/top_three_rate",-0.1),
            ("rider/1/top_three_rate",float("nan")),
        ):
            packet=deepcopy(source())
            packet["direct_verified_fields"][key]=invalid
            with self.subTest(key=key,invalid=str(invalid)),self.assertRaisesRegex(
                    RealSourceGapError,"SOURCE_MODEL_INPUT_VALUE_NOT_ADMISSIBLE"):
                inspect_source_gaps(packet)

    def test_new_measured_environment_count_does_not_authorize_forecast(self):
        packet=deepcopy(source())
        packet["direct_verified_fields"]["race/wind_speed"]=3.2
        packet["verified_registry_keys"].append("race/wind_speed")
        packet["verified_registry_keys"].sort()
        packet["unavailable_registry_keys"].remove("race/wind_speed")
        packet["registry_verified_count"]+=1
        packet["registry_unavailable_count"]-=1
        count=inspect_source_gaps(packet)
        for mode in ("model_A_source_coverage","model_B_source_coverage"):
            model=count[mode]
            self.assertEqual(model["source_observed_required_slots"],15)
            self.assertEqual(model["source_unobserved_required_slots"],78)
            self.assertFalse(model["all_required_fields_observed"])
        self.assertFalse(count["source_usage_rights_independently_verified"])
        self.assertFalse(count["real_pr71_four_models_ran"])
        self.assertFalse(count["owner_private_actual_prediction_frozen"])
        packet["direct_verified_fields"]["race/wind_speed"]="unmeasured"
        with self.assertRaisesRegex(
                RealSourceGapError,"SOURCE_MODEL_INPUT_VALUE_NOT_ADMISSIBLE"):
            inspect_source_gaps(packet)

    def test_tampered_347_count_or_roster_rejected(self):
        for mutation in ("count","roster","unknown","wrong_schema",
                         "missing_list","duplicate_verified","fake_complete"):
            data=deepcopy(source())
            if mutation=="count":
                data["registry_verified_count"]+=1
            if mutation=="roster":
                data["riders"][0]["car_number"]=2
            if mutation=="unknown":
                data["direct_verified_fields"]["rider/1/fake_rating"]=.99
            if mutation=="wrong_schema":
                data["schema"]="SUPER_ACCURATE_AI"
            if mutation=="missing_list":
                # Same counts, but a missing factor is silently omitted.
                data["unavailable_registry_keys"].pop()
            if mutation=="duplicate_verified":
                # A set comparison alone accepts a duplicated source key.
                data["verified_registry_keys"].append(
                    data["verified_registry_keys"][0])
            if mutation=="fake_complete":
                # Never allow an upstream source flag to claim 347/347.
                data["full_347_or_437_verified"]=True
            with self.subTest(mutation=mutation),self.assertRaises(
                    RealSourceGapError):
                inspect_source_gaps(data)


if __name__=="__main__":
    unittest.main()
