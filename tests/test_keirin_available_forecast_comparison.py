"""Synthetic contract for A=existing generated research, B=six-phase, C=optional line.

Fixtures are deliberately invented. No production acquisition, reviewer
signatures, cutoff or official results are certified by these tests.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import unittest

from race_ai import keirin_available_forecast_sources as source
from race_ai import keirin_available_prediction_audit as audit
from race_ai import keirin_round_six_phase_rank as six
from tests.test_keirin_round_six_phase_rank import stage_ctx,snapshot,plans,priors

RID="202611175004"
T0="2026-11-17T11:00:00+09:00"
CUT="2026-11-17T11:15:00+09:00"
PHASES={p:"Unverified six-phase tactical hypothesis: "+p for p in audit.PHASES}


def saved_manual_v3(*, late=False):
    start="10:30" if late else "11:20"
    doc={
        "date":"2026-11-17","timezone":"Asia/Tokyo",
        "generated_at":"2026-11-17T11:02:00+09:00",
        "original_pre_race_snapshot_time":T0,
        "original_pre_race_snapshot_sha256":"a"*64,
        "official_results_status":"NOT_CONNECTED",
        "pre_race_rank_1_changed":False,
        "races":[{
            "id":"50-04","venue":"架空会場","race":4,"start":start,
            "v3_publication_time":"2026-11-17T11:02:00+09:00",
            "independent_cutoff_verified":False,
            "v3_count":3,
            "ranked_picks":[
                {"rank":1,"cars":[3,6,1]},
                {"rank":2,"cars":[3,1,6]},
                {"rank":3,"cars":[1,2,7]}],
            "position_hypotheses":[str(p) for p in source.PHASES],
            "expanded_after_planned_start":late,
        }]
    }
    raw=json.dumps(doc,ensure_ascii=False,separators=(",",":")).encode()
    return raw,sha256(raw).hexdigest()


def source_row(*,late=False):
    raw,hash_value=saved_manual_v3(late=late)
    return source.import_owner_71r_v3(
        raw,expected_source_sha256=hash_value)["races"][0]


def arm(kind,picks,sec,*,history=None):
    return audit.make_arm(
        race_id=RID,arm=kind,
        source_document_sha256={"EXISTING_GENERATED":"e"*64,
                                "SIX_PHASE":"f"*64,
                                "SIX_PHASE_PLUS_LINE":"b"*64}[kind],
        common_input_sha256="a"*64,
        observed_as_of=T0,
        generated_at=f"2026-11-17T11:{sec:02d}:00+09:00",
        official_cutoff_at=CUT,ranked_tickets=picks,
        phase_hypotheses=PHASES if kind!="EXISTING_GENERATED" else None,
        historical_follow_history_sha256=history)


def setup():
    cohort=audit.register_cohort(
        race_ids=[RID],registered_at="2026-11-17T10:30:00+09:00",
        race_cutoffs={RID:CUT},baseline_label="Owner saved 71R V3, no PR71")
    a=arm("EXISTING_GENERATED",[[3,6,1],[3,1,6]],1)
    b=arm("SIX_PHASE",[[6,3,1],[3,6,1]],2)
    c=arm("SIX_PHASE_PLUS_LINE",[[2,4,1],[3,6,1]],3,history="c"*64)
    receipt=lambda x:{
        "race_id":RID,"saved_at":x["generated_at"],
        "arm_digest_sha256":x["arm_digest_sha256"],
        "persisted_content_sha256":sha256(audit.canonical(x)).hexdigest()}
    result={
        "race_id":RID,"status":"FINAL_NORMAL","refund_status":"NONE",
        "winning_triples":[[2,4,1]],
        "payouts_100yen":[{"triple":[2,4,1],"yen":40000}]}
    return cohort,a,b,c,receipt(a),receipt(b),receipt(c),result


def compare(*,with_c=False,**overrides):
    cohort,a,b,c,ra,rb,rc,result=setup()
    args={
        "cohort":cohort,"original":a,"stage_forecast":b,
        "line_forecast":c if with_c else None,
        "original_receipt":ra,"stage_receipt":rb,
        "line_receipt":rc if with_c else None,
        "result":result,
        # Fictional callbacks only test the code path; real provenance is
        # never established by a True lambda in GitHub CI.
        "verify_original":lambda x,r:True,
        "verify_stage":lambda x,r:True,
        "verify_line":lambda x,r:True,
        "verify_line_history":lambda x:True,
        "verify_official_cutoff":lambda c,rid:True,
        "verify_result":lambda x:True,
    }
    args.update(overrides)
    return audit.compare(**args)


class ExistingGeneratedSource(unittest.TestCase):
    def test_real_format_is_admitted_without_four_model_requirement(self):
        raw,expected=saved_manual_v3()
        d=source.import_owner_71r_v3(raw,expected_source_sha256=expected)
        self.assertEqual(d["race_count"],1)
        self.assertEqual(d["candidate_ticket_count"],3)
        self.assertEqual(d["autonomous_4model_forecast_count"],0)
        row=d["races"][0]
        self.assertEqual(row["race_id"],RID)
        self.assertEqual(row["ranked_tickets"][0],[3,6,1])
        self.assertFalse(row["formal_prospective_eligible"])
        self.assertFalse(row["official_cutoff_independently_authenticated"])

    def test_post_start_cannot_become_a_formal_original(self):
        row=source_row(late=True)
        self.assertTrue(row["forecast_after_planned_start"])
        with self.assertRaisesRegex(source.AvailableSourceError,
                                    "SOURCE_NOT_VALIDATED"):
            source.make_stage_snapshot_from_generated(
                record=row,context=stage_ctx(),official_line_receipt={},
                starting_order=snapshot()["starting_order"],
                line_groups=snapshot()["line_groups"])

    def test_actual_generated_source_can_drive_existing_six_phases(self):
        row=source_row()
        original=snapshot()
        ctx=stage_ctx()
        lines={"race_id":RID,"source_input_sha256":"a"*64,
               "observed_at":"2026-11-17T10:59:00+09:00"}
        snap=source.make_stage_snapshot_from_generated(
            record=row,context=ctx,official_line_receipt=lines,
            starting_order=original["starting_order"],
            line_groups=original["line_groups"],
            verify_owner_original=lambda x:True,
            verify_source_roster=lambda x:True,
            verify_official_cutoff=lambda x:True)
        self.assertEqual(snap["baseline_model_id"],source.ACTIVE_SOURCE_ID)
        self.assertNotIn(snap["baseline_model_id"],six.KNOWN_PR71)
        res=six.forecast_shadow(
            context=ctx,snapshot=snap,plans=plans(),priors=priors(),
            independently_verified_parent=lambda x:True)
        self.assertEqual(res["state"],"STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY")
        self.assertEqual(len(res["six_phase_branches"][0]["six_phases"]),6)
        self.assertFalse(res["formal_model_promoted"])

    def test_owner_raw_bytes_and_bad_race_order_are_rejected(self):
        raw,hash_value=saved_manual_v3()
        with self.assertRaisesRegex(source.AvailableSourceError,"BYTES_SHA_MISMATCH"):
            source.import_owner_71r_v3(raw+b" ",expected_source_sha256=hash_value)
        d=json.loads(raw)
        d["races"][0]["ranked_picks"][1]["rank"]=12
        broken=json.dumps(d).encode()
        with self.assertRaisesRegex(source.AvailableSourceError,"RANK_OR_CAR_INVALID"):
            source.import_owner_71r_v3(
                broken,expected_source_sha256=sha256(broken).hexdigest())

    def test_missing_source_and_cutoff_witness_rejected(self):
        row=source_row()
        lines={"race_id":RID,"source_input_sha256":"a"*64,
               "observed_at":"2026-11-17T10:59:00+09:00"}
        with self.assertRaisesRegex(source.AvailableSourceError,"INDEPENDENT_GENERATED"):
            source.make_stage_snapshot_from_generated(
                record=row,context=stage_ctx(),official_line_receipt=lines,
                starting_order=snapshot()["starting_order"],
                line_groups=snapshot()["line_groups"],
                verify_owner_original=lambda x:True,
                verify_source_roster=lambda x:True,
                verify_official_cutoff=None)


class ActiveAvailableAudit(unittest.TestCase):
    def test_AB_evaluates_with_C_absent_and_no_PR71_dependency(self):
        r=compare()
        self.assertEqual(r["state"],"A_B_RESEARCH_SETTLED")
        self.assertTrue(r["ab_evaluable"])
        self.assertFalse(r["abc_evaluable"])
        self.assertEqual(r["C_state"],"HOLD_NOT_AVAILABLE")
        self.assertFalse(r["original_4model_required"])
        self.assertFalse(r["real_improvement_proven"])

    def test_three_arms_work_with_independently_admitted_line(self):
        r=compare(with_c=True)
        self.assertEqual(r["state"],"A_B_C_RESEARCH_SETTLED")
        self.assertEqual(r["bc_hit_at_1_delta"],1)
        self.assertTrue(r["C_six_phase_plus_line"]["hit_at_1"])
        self.assertFalse(r["real_improvement_proven"])

    def test_line_missing_verified_history_does_not_block_AB(self):
        r=compare(with_c=True,verify_line_history=None)
        self.assertTrue(r["ab_evaluable"])
        self.assertFalse(r["abc_evaluable"])
        self.assertEqual(r["C_state"],"HOLD_UNVERIFIED_LINE_HISTORY_OR_FREEZE")

    def test_no_independent_cutoff_ab_is_hold_not_incorrect(self):
        r=compare(verify_official_cutoff=None)
        self.assertEqual(r["reason"],"OFFICIAL_SALES_CUTOFF_NOT_ATTESTED")
        self.assertFalse(r["ab_evaluable"])

    def test_no_real_result_ab_is_hold_not_incorrect(self):
        r=compare(result=None)
        self.assertFalse(r["ab_evaluable"])
        self.assertEqual(r["reason"],"OFFICIAL_RESULT_NOT_INDEPENDENTLY_ATTESTED_OR_SETTLED")

    def test_wrong_forecast_sha_mismatch_holds(self):
        cohort,a,b,c,ra,rb,rc,result=setup()
        bad=deepcopy(b)
        bad["ranked_tickets"]=[[1,3,6]]
        r=compare(stage_forecast=bad)
        self.assertFalse(r["ab_evaluable"])
        self.assertEqual(r["reason"],"A_B_INPUT_OR_ARM_INVALID")

    def test_missing_original_independent_storage_holds(self):
        r=compare(verify_original=None)
        self.assertFalse(r["ab_evaluable"])

    def test_AB_races_kept_when_C_is_missing(self):
        cohort,a,b,c,ra,rb,rc,result=setup()
        summary=audit.summarize(cohort,[compare()])
        self.assertEqual(summary["registered_races"],1)
        self.assertEqual(summary["ab_comparable_races"],1)
        self.assertEqual(summary["abc_comparable_races"],0)
        self.assertEqual(summary["c_only_holds"],{"HOLD_NOT_AVAILABLE":1})
        self.assertEqual(summary["arms"]["B_six_phase"]["n"],1)
        self.assertEqual(summary["arms"]["C_six_phase_plus_line"]["n"],0)
        self.assertTrue(summary["four_model_dependency_removed"])

    def test_unreported_pre_registered_race_is_HOLD_not_loss(self):
        cohort=setup()[0]
        summary=audit.summarize(cohort,[])
        self.assertEqual(summary["registered_races"],1)
        self.assertEqual(summary["ab_comparable_races"],0)
        self.assertEqual(summary["ab_holds"],{"UNREPORTED":1})

    def test_bad_cutoff_and_duplicate_tickets_rejected(self):
        with self.assertRaisesRegex(audit.ActiveForecastError,"65_SECONDS_BEFORE_CUTOFF"):
            arm("SIX_PHASE",[[3,6,1]],14)
        with self.assertRaisesRegex(audit.ActiveForecastError,"REUSED"):
            arm("SIX_PHASE",[[3,6,1],[3,6,1]],2)


if __name__=="__main__":
    unittest.main()
