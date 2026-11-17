"""Synthetic-only contract: A original is unchanged; B/C require true input admission.

The historical reviews and future outcomes in this file are FICTIONAL.
"""
from pathlib import Path
import json
import tempfile
import unittest

from race_ai import keirin_real_three_arm_prospective_bridge as bridge
from tests.test_keirin_line_cohesion import empirical_fixture, IDS, config
from tests.test_keirin_round_six_phase_rank import stage_ctx, snapshot, priors, plans
from tests.test_keirin_line_three_arm_audit import fixture


def prepare(**updates):
    req = {
        "context": stage_ctx(),
        "original": snapshot(),
        "plans": plans(),
        "priors": priors(),
        "athlete_ids_by_car": IDS,
        "real_reviewed_line_history": empirical_fixture(),
        "line_config": config(),
        "computed_at": "2026-11-17T11:00:30+09:00",
        "verify_pr71_original": lambda _: True,
        "verify_rider_identity": lambda _: True,
        "verify_historical_video_label": lambda _: True,
    }
    req.update(updates)
    return bridge.prepare(**req)


class ThreeArmProspectiveBridgeContract(unittest.TestCase):

    def test_three_arms_stay_on_same_original_before_private_freeze(self):
        r = prepare()
        self.assertEqual(r["state"], "RESEARCH_READY_FOR_PRIVATE_SIDE_CAR_FREEZE")
        self.assertEqual(r["baseline_prediction_sha256"],
                         r["stage_only"]["parent_prediction_sha256"])
        self.assertEqual(r["baseline_prediction_sha256"],
                         r["stage_plus_line"]["parent_prediction_sha256"])
        self.assertEqual(r["stage_only"]["pre_race_input_sha256"],
                         r["stage_plus_line"]["pre_race_input_sha256"])
        self.assertTrue(r["can_freeze_three_arm"])
        self.assertFalse(r["formal_accuracy_proven"])

    def test_private_pair_freeze_local_only_and_keeps_original_untouched(self):
        r = prepare()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder).chmod(0o700)
            report = bridge.freeze_two_shadows_once(r, private_dir=folder)
            self.assertTrue(report["private_local_readback"])
            self.assertFalse(report["aes_gcm_persisted_across_runners"])
            self.assertFalse(report["independent_second_runner_sha_confirmed"])
            self.assertTrue(report["existing_baseline_original_not_rewritten"])
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),
                             ["stage_only.json", "stage_plus_line.json"])
            self.assertEqual((Path(folder) / "stage_only.json").stat().st_mode & 0o777,0o600)
            with self.assertRaisesRegex(ValueError,"CREATE_ONCE"):
                bridge.freeze_two_shadows_once(r, private_dir=folder)

    def test_private_output_directory_must_not_be_world_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder).chmod(0o755)
            with self.assertRaisesRegex(ValueError,"PRIVATE_0700"):
                bridge.freeze_two_shadows_once(prepare(), private_dir=folder)

    def test_historical_public_lineup_is_not_an_admitted_video_label(self):
        from race_ai import keirin_real_line_evidence as public_line
        from pathlib import Path
        doc = json.loads(
            (Path(__file__).resolve().parents[1] /
             "docs/evidence/2026-11-18/keirin_takeo_public_planned_pairs_v1.json").read_text())
        self.assertEqual(doc["records"][0]["tactical_follow_outcome"], "UNKNOWN")
        result = prepare(real_reviewed_line_history=doc["records"])
        self.assertEqual(result["state"],"HOLD")
        self.assertEqual(result["reason"],"UNVERIFIED_OR_INVALID_THREE_ARM_SOURCE_INPUT")

    def test_history_unavailable_preserves_B_but_holds_C(self):
        r = prepare(real_reviewed_line_history=[])
        self.assertEqual(r["reason"],"NO_INDEPENDENTLY_REVIEWED_PRIOR_LINE_EVENTS")
        self.assertIsNone(r["stage_plus_line"])
        self.assertEqual(r["stage_only"]["state"],
                         "STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY")

    def test_independent_label_reader_denial_holds_candidate(self):
        r = prepare(verify_historical_video_label=lambda _: False)
        self.assertEqual(r["reason"],"HISTORICAL_LABEL_NOT_EXTERNALLY_AUTHENTICATED")

    def test_future_as_of_late_input_fails_closed(self):
        r = prepare(computed_at="2026-11-17T11:14:55+09:00")
        self.assertEqual(r["reason"],"UNVERIFIED_OR_INVALID_THREE_ARM_SOURCE_INPUT")

    def test_result_scoring_requires_organizer_authentication(self):
        data = fixture()
        r = bridge.score_after_independent_archive_readback(
            frozen_original=data["original"], line_study=data["line_study"],
            original_receipt=data["original_receipt"],
            round_receipt=data["round_receipt"],
            line_receipt=data["line_receipt"], context=data["event_context"],
            result=data["result"],
            verify_original=lambda a,b: True,
            verify_round=lambda a,b: True,
            verify_line=lambda a,b: True,
            verify_video_labels=lambda a: True,
            verify_result=None,
        )
        self.assertFalse(r["paired_evaluable"])
        self.assertIn("NOT_INDEPENDENTLY_AUTHENTICATED",r["reason"])

    def test_fictional_all_three_forecasts_could_be_scored_if_every_gate_approved(self):
        data = fixture()
        r = bridge.score_after_independent_archive_readback(
            frozen_original=data["original"], line_study=data["line_study"],
            original_receipt=data["original_receipt"],
            round_receipt=data["round_receipt"],
            line_receipt=data["line_receipt"], context=data["event_context"],
            result=data["result"],
            verify_original=lambda a,b: True, verify_round=lambda a,b: True,
            verify_line=lambda a,b: True, verify_video_labels=lambda a: True,
            verify_result=lambda a: True,
        )
        self.assertEqual(r["state"],"PRIVATE_THREE_ARM_SAME_RACE_RESEARCH")
        self.assertTrue(r["paired_evaluable"])
        self.assertFalse(r["formal_uplift_proven"])


if __name__=="__main__":
    unittest.main()
