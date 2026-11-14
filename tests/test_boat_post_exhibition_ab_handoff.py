"""Source-free P1 A/B generation and receipt contracts with invented 6-boat data."""
from copy import deepcopy
from datetime import datetime
import json
import shutil
import subprocess
import unittest

from race_ai.boat_post_exhibition_ab_handoff import (
    SCHEMA, create_candidate, readback_candidate, node_predict, digest,
    prepare_round, verify_round_readback,
)

AT = "2026-11-09T12:05:00+09:00"
CUTOFF = "2026-11-09T12:30:00+09:00"
RACE = "20261109-04-01"

STYLE = ["1_nige", "1_loss_makuri", "1_loss_sashi", "1_loss_makurizashi",
         "2_nigashi", "2_sashi", "2_makuri", "3_kado_4_makuri_won"]
STYLE += [f"{c}_{m}" for c in range(3, 7)
          for m in ("sashi", "makuri", "makurizashi")]


def sample():
    people, entrants, standing, gaps = [], {}, [], {}
    for f in range(1, 7):
        tilt = 2.0 if f == 5 else 3.0 if f == 6 else 0.0
        rid = str(4100 + f)
        people.append(dict(lane=f, registration_number=rid,
                           display_time=6.50 + f / 100, tilt=tilt,
                           exhibition_st_status="OK"))
        entrants[str(f)] = dict(
            frame=f, racer_id=rid, tilt_deg=tilt,
            outer_high_tilt_marker=f >= 5,
            historical_inward_move_win_rate=.4,
            historical_outward_move_top3_rate=.3,
            inner_pressure_kept_course_rate=.5)
        standing.append(dict(racer_id=rid, official_rank=f,
                             eligibility="ELIGIBLE", official_rate=8.0))
        gaps[rid] = .2 * (f - 3)
    exhibition = dict(
        race_id=RACE, closed_at=CUTOFF,
        captured_at="2026-11-09T12:00:00+09:00",
        source_sha256="a" * 64,
        beforeinfo=dict(
            race_id=RACE,
            captured_at="2026-11-09T12:00:00+09:00",
            source_sha256="a"*64, status="AVAILABLE",
            body_identity_verified=True, information_phase="pre_race",
            context=dict(status="PARSED", roster_binding_status="VERIFIED",
                         participants=people)),
        formation_evidence=dict(
            phase="start_exhibition", race_id=RACE,
            independently_source_verified=True,
            source_sha256="b"*64,
            beforeinfo_source_sha256="a"*64,
            captured_at="2026-11-09T12:01:00+09:00",
            course_by_frame={str(i):i for i in range(1,7)}))
    context = dict(schema="RACE_AI_BOAT_SIX_WAY_INTERACTIONS_V1",
        race_id=RACE, as_of=AT,
        formation=dict(slow_count=3, kado_course=4, kado_uke_course=3),
        six_course_features={k:.35 for k in STYLE},
        entry_tilt_cross_features=entrants,
        current_venue_rule_status="CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH",
        qualifying_rank_and_point_gaps=dict(
            border_status="CURRENT_RANK_ONLY_NOT_FINAL",
            rate_gaps=gaps, standings=standing))
    tickets = [f"{a}-{b}-{c}" for a in range(1,7) for b in range(1,7)
               for c in range(1,7) if len({a,b,c}) == 3]
    original = sorted((dict(ticket=t, score=1/120) for t in tickets),
                      key=lambda r:(-r["score"],r["ticket"]))
    baseline = dict(race_id=RACE, prediction=dict(
        model_id="boat-display-rating-PL-reference-v1-UNVALIDATED",
        race_id=RACE, as_of="2026-11-09T12:02:00+09:00",
        generated_at="2026-11-09T12:02:00+09:00",
        cutoff_at=CUTOFF, full_120=original, top8=original[:8]),
        physical_receipt=dict(server_saved_at="2026-11-09T12:03:00+09:00",
                              source_sha256="c"*64))
    return exhibition, baseline, context


def fake_predictor(record, frozen):
    rows = record["baseline"]["full_120"]
    return dict(schema="RACE_AI_BOAT_SIXWAY_OVERLAY_V1",
                research_mode="EXPERIMENTAL_OVERLAY",
                all_120=[dict(ticket=r["ticket"], probability=r["score"])
                         for r in rows],
                top8=[dict(ticket=r["ticket"], probability=r["score"])
                      for r in rows[:8]])


def test_model():
    return dict(schema="RACE_AI_BOAT_SIXWAY_OVERLAY_FROZEN_V1",
                stage="P1", frozen=True,
                trained_through="2026-11-08T22:00:00+09:00",
                training_ids=[])


class PostExhibitionABTests(unittest.TestCase):
    def candidate(self, *, predictor=fake_predictor):
        exhibition, baseline, context = sample()
        return create_candidate(exhibition,baseline,context,test_model(),
                                at=AT,predictor=predictor)

    def test_complete_source_free_handshake_no_result(self):
        exhibition, baseline, context = sample()
        old = json.dumps([exhibition,baseline,context],sort_keys=True)
        c = self.candidate()
        self.assertEqual(c["schema"],SCHEMA)
        self.assertEqual(c["stage"],"P1")
        self.assertEqual(len(c["B_full120"]),120)
        self.assertEqual(len(c["A_top8"]),8)
        self.assertEqual(len(c["B_top8"]),8)
        self.assertFalse(c["independent_physical_save_readback"])
        self.assertFalse(c["actual_result_used"])
        self.assertEqual(c["source_get_count"],0)
        self.assertEqual(json.dumps([exhibition,baseline,context],sort_keys=True),old)
        receipt=dict(server_created_at="2026-11-09T12:06:00+09:00",
                     payload_sha256=digest(c),artifact_id=123,
                     independently_authenticated=True)
        result = readback_candidate(c,receipt)
        self.assertEqual(result["state"],"B_ENCRYPTED_AND_RECEIPT_VERIFIED")
        self.assertTrue(result["external_source_authentication_separate"])

    def test_outer_baseline_race_identity_is_required_and_exact(self):
        for value in (None, "20261109-05-01"):
            with self.subTest(race_id=value):
                e,b,c = sample()
                if value is None:
                    b.pop("race_id")
                else:
                    b["race_id"] = value
                called = []
                def never_predict(record, frozen):
                    called.append(True)
                    return fake_predictor(record, frozen)
                with self.assertRaisesRegex(ValueError, "RACE_IDENTITY_MISMATCH"):
                    create_candidate(e,b,c,test_model(),at=AT,predictor=never_predict)
                self.assertEqual(called, [])

    def test_inner_baseline_prediction_cannot_belong_to_another_race(self):
        e,b,c = sample()
        b["prediction"]["race_id"] = "20261109-05-01"
        with self.assertRaisesRegex(ValueError, "A_TOP8_OR_CUTOFF_MISMATCH"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_tactical_context_cannot_belong_to_another_race(self):
        e,b,c = sample()
        c["race_id"] = "20261109-05-01"
        with self.assertRaisesRegex(ValueError, "RACE_IDENTITY_MISMATCH"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_no_visual_course_proof_blocks(self):
        e,b,c = sample()
        del e["formation_evidence"]
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_EXHIBITION_COURSE_PROOF_MISSING"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_unsupported_source_position_never_substitutes_for_course(self):
        e,b,c=sample()
        for p in e["beforeinfo"]["context"]["participants"]:
            p["exhibition_source_position_number"]=p["lane"]
            p["exhibition_course"]=None
        del e["formation_evidence"]
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_EXHIBITION_COURSE_PROOF_MISSING"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_preclose_course_formation_cannot_disagree_with_boat(self):
        e,b,c=sample()
        e["formation_evidence"]["course_by_frame"]["6"]=5
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_EXHIBITION_COURSE_PROOF_MISSING"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_tilt_and_racer_id_source_must_match(self):
        e,b,c=sample()
        c["entry_tilt_cross_features"]["6"]["tilt_deg"]=1.0
        with self.assertRaisesRegex(ValueError,"BOAT_FRAME_COURSE_OR_TILT_MISMATCH"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)
        e,b,c=sample()
        c["entry_tilt_cross_features"]["1"]["racer_id"]="4999"
        with self.assertRaisesRegex(ValueError,"BOAT_FRAME_COURSE_OR_TILT_MISMATCH"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_after_cutoff_input_or_saved_original_is_rejected(self):
        e,b,c=sample()
        with self.assertRaisesRegex(ValueError,"EXHIBITION_OR_GENERATION_AFTER_CUTOFF"):
            create_candidate(e,b,c,test_model(),at="2026-11-09T12:29:00+09:00",
                             predictor=fake_predictor)
        e,b,c=sample()
        b["physical_receipt"]["server_saved_at"]="2026-11-09T12:31:00+09:00"
        with self.assertRaisesRegex(ValueError,"A_ORIGINAL_PRE_CUTOFF_RECEIPT_REQUIRED"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_unfrozen_model_is_rejected(self):
        e,b,c=sample()
        m=test_model();m["frozen"]=False
        with self.assertRaisesRegex(ValueError,"TRAINED_B_FROZEN_MODEL_REQUIRED"):
            create_candidate(e,b,c,m,at=AT,predictor=fake_predictor)

    def test_no_event_qualifying_board_is_hold(self):
        e,b,c=sample()
        c["qualifying_rank_and_point_gaps"]["border_status"]="HOLD_NO_COMPLETE_OFFICIAL_BOARD"
        with self.assertRaisesRegex(ValueError,"EVENT_QUALIFYING_BOARD_MISSING"):
            create_candidate(e,b,c,test_model(),at=AT,predictor=fake_predictor)

    def test_readback_must_have_independent_server_receipt(self):
        c=self.candidate()
        base=dict(server_created_at="2026-11-09T12:06:00+09:00",
                  payload_sha256=digest(c),artifact_id=15,
                  independently_authenticated=False)
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_ARTIFACT_RECEIPT_MISSING"):
            readback_candidate(c,base)
        base["independently_authenticated"]=True
        base["server_created_at"]="2026-11-09T12:32:00+09:00"
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_SAVE_TOO_LATE"):
            readback_candidate(c,base)
        base["server_created_at"]="2026-11-09T12:06:00+09:00"
        base["payload_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"INDEPENDENT_ARTIFACT_RECEIPT_MISSING"):
            readback_candidate(c,base)

    def test_existing_p1_round_accepts_prepared_B_before_cutoff_only(self):
        e,b,c=sample()
        original=dict(race_id=RACE,model_id=b["prediction"]["model_id"],
                      prediction=b["prediction"],
                      dispatch_generated_at=b["prediction"]["generated_at"],
                      cutoff_at=CUTOFF)
        available={RACE:dict(program={"closed_at":CUTOFF},
                             beforeinfo=e["beforeinfo"])}
        research={RACE:dict(context=c,frozen_model=test_model(),
                           formation_evidence=e["formation_evidence"])}
        baseline_proof=dict(payload_sha256=b["physical_receipt"]["source_sha256"],
                            created_at=b["physical_receipt"]["server_saved_at"])
        made=prepare_round(available,[original],baseline_proof,research,
                           generated_at=AT,predictor=fake_predictor)
        self.assertEqual(made["candidate_pairs"],1)
        self.assertEqual(made["held_races"],0)
        receipt=dict(server_created_at="2026-11-09T12:06:00+09:00",
                     independently_authenticated=True,artifact_id=12)
        read=verify_round_readback(made,receipt)
        self.assertEqual(read["b_saved_before_cutoff"],1)
        self.assertEqual(read["b_saved_after_cutoff_held"],0)
        receipt["server_created_at"]="2026-11-09T12:31:00+09:00"
        late=verify_round_readback(made,receipt)
        self.assertEqual(late["b_saved_before_cutoff"],0)
        self.assertEqual(late["b_saved_after_cutoff_held"],1)

    def test_source_missing_round_holds_all_without_retroactive_B(self):
        e,b,c=sample()
        current={RACE:dict(program={"closed_at":CUTOFF},
                           beforeinfo=e["beforeinfo"])}
        out=prepare_round(current,[],None,{},
                          generated_at=AT,predictor=fake_predictor)
        self.assertEqual(out["candidate_pairs"],0)
        self.assertEqual(out["held_races"],1)
        self.assertEqual(out["holds"][0]["status"],
                         "HOLD_RESEARCH_FACTS_NOT_PREPARED")
        report=verify_round_readback(out,dict(
            server_created_at="2026-11-09T12:06:00+09:00",
            independently_authenticated=True,artifact_id=12))
        self.assertEqual(report["b_saved_before_cutoff"],0)
        self.assertEqual(report["held_races"],1)

    @unittest.skipUnless(shutil.which("node"), "Node runtime required")
    def test_actual_js_120_ticket_engine_with_frozen_synthetic_model(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        js=root/"race_ai/boat_six_way_probability_overlay.cjs"
        params=subprocess.run(
            ["node","-p",f"JSON.stringify(require('{js}').FACTORS)"],
            text=True,capture_output=True,check=True)
        factors=json.loads(params.stdout)
        model=test_model()
        model.update(coefficients=[0.15 if name=="winner_high_tilt" else 0
                                   for name in factors],
                     feature_names=factors)
        e,b,c=sample()
        result=create_candidate(e,b,c,model,at=AT,predictor=node_predict)
        self.assertEqual(len(result["B_full120"]),120)
        self.assertNotEqual(result["A_top8"], result["B_top8"])
        self.assertNotEqual(result["A_prediction_sha256"],result["B_context_sha256"])


if __name__=="__main__":
    unittest.main()
