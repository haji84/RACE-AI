"""Read genuine saved-reader fixtures without rerunning their predictors."""
from copy import deepcopy
import importlib
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.frozen_day_cycle import read_p0, read_p1
from tests.test_frozen_day_cycle import sample, observation
from tests.test_observed_p1_connection import inputs, archive, AT
from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow

try:
    M = importlib.import_module("race_ai.private_cycle_projection")
except ModuleNotFoundError:
    M = None


def seal(state):
    state["state_sha256"] = digest({k:v for k,v in state.items() if k != "state_sha256"})
    return state


def saved_state():
    document, raw, receipt = sample()
    document, rows = read_p0(raw, receipt, expected_day="2030-04-01")
    state = dict(schema="RACE_AI_RECOVERED_FIRST_RECEIPTS_V1", day_jst="2030-04-01", rows=rows,
                 observations=[], receipts=[receipt], excluded_repeats=[], complete=True,
                 learning_shadows=[], scanned_runs=[2], index_entries=[])
    return seal(state), document


def saved_learned_archive():
    """Existing synthetic fitter/shadow producer -> untouched saved P1 archive."""
    from datetime import timedelta, timezone
    from tests.test_observed_weight_learning import LearningTests, NOW
    from tests.test_observed_p1_connection import bridge
    from race_ai.observed_weight_learning import make_shadows
    base,extra,proof=inputs();rid="20300401-24-12";base["race_id"]=rid;extra["race_id"]=rid
    at=(NOW+timedelta(minutes=10)).isoformat();before=(NOW+timedelta(minutes=9)).isoformat()
    base.update(cutoff_at=(NOW+timedelta(minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat(),captured_at=before)
    extra["observed_at"]=before
    proof.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(),preview_captured_at=before)
    for field in ("program_url","preview_url"):proof[field]=proof[field].replace("jcd=01","jcd=24").replace("rno=1","rno=12")
    bundle=bridge.build_bundle(base,extra,at,**proof,owner_reviewed=True)
    shadows=make_shadows(bundle["snapshot"],bundle["suite"],LearningTests().context())
    doc=dict(schema="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",paired_forecasts=[build_pair(base,at)],
             additional_official_feature_shadows=[build_live_feature_shadow(base,extra,at)],
             observed_pairwise_p1_bundles=[bundle],learned_pairwise_shadows=shadows)
    raw,receipt=archive(doc,saved=(NOW+timedelta(minutes=11)).isoformat())
    parsed,_=read_p1(raw,receipt)
    return parsed,raw,receipt


class PrivateCycleProjectionTests(unittest.TestCase):
    def test_pure_saved_cycle_projection_exists(self):
        self.assertIsNotNone(M, "private cycle UI projection is missing")

    def test_saved_top8_ranking_hash_and_partial_metadata_are_preserved_without_invention(self):
        state,_=saved_state();before=deepcopy(state)
        view=M.project_state(state,dataset_status="REAL_REPORTED")
        self.assertEqual(state,before)
        self.assertEqual(view["schema"],"RACE_AI_PRIVATE_CYCLE_VIEW_V1")
        self.assertEqual(view["source_state_sha256"],state["state_sha256"])
        self.assertEqual(len(view["records"]),1)
        r=view["records"][0];p=r["prediction"];original=state["rows"][0]
        self.assertEqual(r["race_id"],original["race_id"])
        self.assertEqual(r["venue"],"場コード01")
        self.assertEqual(r["scope"],"research")
        self.assertEqual(p["ordered_top8"],original["top8"])
        self.assertEqual(p["ordered_candidates"],original["ranked"])
        self.assertEqual(p["prediction_sha256"],original["model_sha256"])
        self.assertEqual(p["original_json_sha256"],original["original_json_sha256"])
        self.assertEqual(p["artifact_id"],original["artifact_id"])
        self.assertEqual(p["as_of"],original["as_of"])
        self.assertEqual(p["persisted_at"],original["server_saved_at"])
        for field in ("generated_at","model_version","input_sha256","source_sha256","odds_independent"):
            self.assertIsNone(p[field],field)
        self.assertFalse(p["external_receipt_verified"])
        self.assertIn("MODEL_VERSION_NOT_SAVED",p["missing_reasons"])
        self.assertEqual(r["comparison_predictions"][0]["model_id"],state["rows"][1]["model_id"])

    def test_explicit_synthetic_scope_and_explicit_dataset_status_are_required(self):
        state,_=saved_state()
        view=M.project_state(state,dataset_status="SYNTHETIC_ONLY")
        self.assertEqual(view["dataset_status"],"SYNTHETIC_ONLY")
        self.assertTrue(all(r["scope"]=="synthetic" for r in view["records"]))
        with self.assertRaises(TypeError):M.project_state(state)
        for status in ("REAL_VERIFIED","AUDIT_ONLY",True):
            with self.assertRaises(ValueError):M.project_state(state,dataset_status=status)

    def test_matching_sealed_p0_original_enriches_only_fields_that_actually_exist(self):
        state,doc=saved_state()
        native=doc["predictions"][0]["models"][state["rows"][0]["model_id"]]
        view=M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[doc])
        p=view["records"][0]["prediction"]
        self.assertEqual(p["model_version"],native["model_version"])
        self.assertEqual(p["input_sha256"],native["snapshot_sha256"])
        self.assertEqual(p["candidates"],native["candidates"])
        self.assertEqual(p["prediction_sha256"],native["prediction_sha256"])
        self.assertIsNone(p["generated_at"],"as_of is not a saved generation timestamp")
        self.assertIsNone(p["source_sha256"])
        self.assertIsNone(p["odds_independent"],"do not invent a missing source assertion")
        self.assertFalse(p["external_receipt_verified"])

    def test_native_p1_parent_evidence_is_preserved_without_inventing_model_version(self):
        state,_=saved_state();base,extra,_=inputs()
        pair=build_pair(base,AT);shadow=build_live_feature_shadow(base,extra,AT)
        document=dict(schema="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",paired_forecasts=[pair],
                      additional_official_feature_shadows=[shadow])
        raw,receipt=archive(document);_,rows=read_p1(raw,receipt)
        state["rows"]+=rows;state["receipts"].append(receipt);seal(state)
        view=M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[document])
        r=view["records"][0];variants=[r["prediction"]]+r["comparison_predictions"]
        self.assertEqual([p["stage"] for p in variants],["P0","P0","P1","P1","P1"])
        p=next(p for p in variants if p["model_id"]==pair["models"][0]["model_id"])
        self.assertEqual(p["generated_at"],pair["generated_at"])
        self.assertEqual(p["source_sha256"],pair["source_sha256"])
        self.assertEqual(p["prediction_sha256"],pair["models"][0]["model_sha256"])
        self.assertIsNone(p["model_version"])
        self.assertIsNone(p["input_sha256"],"parent source SHA must not become an invented input SHA")
        self.assertTrue(p["odds_independent"])

    def test_partial_readback_uses_actual_wrapper_member_pins_and_records_incomplete_scope(self):
        state,doc=saved_state();r=state["rows"][0]
        state.update(schema="RACE_AI_PRIVATE_ARTIFACT_READBACK_V1",complete=False,coverage_scope="EXPLICIT_ARTIFACTS_ONLY",
                     original_documents=[dict(artifact_id=r["artifact_id"],member_name="forecasts.json",member_sha256=r["original_json_sha256"],document=doc)])
        seal(state)
        view=M.project_state(state,dataset_status="REAL_REPORTED")
        self.assertFalse(view["source_complete"])
        self.assertEqual(view["coverage_scope"],"EXPLICIT_ARTIFACTS_ONLY")
        self.assertIsNotNone(view["records"][0]["prediction"]["model_version"])
        self.assertFalse(view["independent_receipt_verified"])

    def test_observation_captures_preserve_results_and_refunds_separately_from_predictions(self):
        state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
        new["captured_at"]="2030-04-01T02:20:00Z";new["source_sha256"]="c"*64
        new["data"]["refund_boats"]=[6]
        new["data"]["payouts"][0]["payout_per_100_yen"]=2500
        state["observations"]=[old,new];seal(state)
        before=deepcopy(state)
        r=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(r["result_observations"],[old,new])
        self.assertEqual(r["result_revisions"],[])
        self.assertEqual(r["result"]["observed_at"],new["captured_at"])
        self.assertIsNone(r["result"]["confirmed_at"])
        self.assertFalse(r["result"]["official"])
        self.assertEqual(r["result"]["payout_yen_per_100"],2500)
        self.assertEqual(r["result"]["refund_boats"],[6])
        self.assertEqual(r["result"]["source_sha256"],new["source_sha256"])
        self.assertEqual(r["prediction"]["ordered_top8"],state["rows"][0]["top8"])
        self.assertEqual(state,before)

    def test_actual_schedule_rows_without_predictions_remain_visible_without_count_invention(self):
        state,_=saved_state();cutoff=state["rows"][0]["cutoff_at"]
        state["schedule_cache"]={"official_race_registry":[{"race_id":"20300401-02-02","cutoff_at":cutoff}]}
        state["scheduled_boat_races"]=288
        seal(state)
        records=M.project_state(state,dataset_status="REAL_REPORTED")["records"]
        self.assertEqual(len(records),2)
        missing=next(r for r in records if r["race_id"]=="20300401-02-02")
        self.assertIsNone(missing["prediction"])
        self.assertIn("NO_SAVED_PREDICTION",missing["missing_reasons"])

    def test_state_hash_and_canonical_json_input_guard_against_corruption(self):
        state,_=saved_state();state["rows"][0]["top8"][0].reverse()
        with self.assertRaisesRegex(ValueError,"state hash"):M.project_state(state,dataset_status="REAL_REPORTED")
        for raw in ('{"schema":1,"schema":2}','{"x":NaN}'):
            with self.assertRaises(ValueError):M.read_state_json(raw)

    def test_saved_learning_snapshot_cannot_supply_another_races_input_hash(self):
        from race_ai.observed_weight_learning import source_snapshot
        state,doc=saved_state();snapshot=source_snapshot(doc["predictions"][0])
        snapshot["race_id"]="boat:2030-04-01:boatrace-jcd-01:2"
        state["rows"][0].update(learning_snapshot=snapshot,learning_snapshot_sha256=digest(snapshot));seal(state)
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")

    def test_explicit_metadata_conflict_with_matching_native_original_is_not_hidden(self):
        state,doc=saved_state();state["rows"][0]["model_version"]="contradictory-version";seal(state)
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[doc])

    def test_native_reader_subsecond_receipt_precision_is_retained_without_rounding(self):
        base,extra,_=inputs();at="2030-04-01T10:40:00.500000+09:00"
        doc=dict(schema="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",paired_forecasts=[build_pair(base,at)],
                 additional_official_feature_shadows=[build_live_feature_shadow(base,extra,at)])
        raw,receipt=archive(doc,saved="2030-04-01T01:40:00Z");parsed,rows=read_p1(raw,receipt)
        state=seal(dict(schema="RACE_AI_PRIVATE_ARTIFACT_READBACK_V1",day_jst="2030-04-01",rows=rows,observations=[],receipts=[receipt],complete=False))
        view=M.project_state(state,dataset_status="SYNTHETIC_ONLY",original_documents=[parsed])
        self.assertEqual(view["records"][0]["prediction"]["generated_at"],at)
        self.assertEqual(view["records"][0]["prediction"]["source_captured_at"], base["captured_at"])
        without_original = M.project_state(state, dataset_status="SYNTHETIC_ONLY")
        self.assertIsNone(without_original["records"][0]["prediction"]["source_captured_at"])
        self.assertEqual(view["records"][0]["prediction"]["persisted_at"],receipt["created_at"])

    def test_ranking_identity_clock_and_hash_conflicts_fail_closed(self):
        for change in (lambda r:r.update(ranked=r["ranked"][::-1]),
                       lambda r:r.update(model_sha256="not-a-sha"),
                       lambda r:r.update(race_id="20300402-01-01"),
                       lambda r:r.update(server_saved_at=r["cutoff_at"]),
                       lambda r:r.update(roster={"1":"4001"}),
                       lambda r:r.update(top8=[[True,2,3]])):
            state,_=saved_state();change(state["rows"][0]);seal(state)
            with self.subTest(change=change),self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")

    def test_conflicting_forecasts_or_result_captures_do_not_silently_overwrite(self):
        state,_=saved_state();state["rows"].append(deepcopy(state["rows"][0]));seal(state)
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")
        state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old);new["source_sha256"]="e"*64
        state["observations"]=[old,new];seal(state)
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")

    def test_invalid_official_capture_identity_or_cutoff_never_becomes_a_displayed_final_result(self):
        for reason,edit in (("RESULT_CUTOFF_MISMATCH",lambda o:o.update(closed_at="2030-04-01T10:58:00+09:00")),
                            ("RESULT_CUTOFF_MISMATCH",lambda o:o.update(closed_at="2030-04-02T10:58:00+09:00")),
                            ("RESULT_CAPTURE_BEFORE_CUTOFF",lambda o:o.update(captured_at="2030-04-01T01:00:00Z")),
                            ("RESULT_ROSTER_MISMATCH",lambda o:o["data"]["results"][0].update(racer_registration_id="9999")),
                            ("RESULT_IDENTITY_UNVERIFIED",lambda o:o.update(body_identity_verified=False)),
                            ("RESULT_RACE_IDENTITY_MISMATCH",lambda o:o["data"]["results"][0].update(race_id="20300401-02-01"))):
            state,_=saved_state();o=observation(state["rows"][0]);edit(o);state["observations"]=[o];seal(state)
            before=deepcopy(state)
            with self.subTest(reason=reason):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertEqual(row["result_observations"],[o])
                self.assertEqual(row["cutoff_at"],state["rows"][0]["cutoff_at"])
                self.assertEqual(row["result"]["status"],"unsupported")
                self.assertEqual(row["result"]["winning_combinations"],[])
                self.assertFalse(row["result"]["official"])
                self.assertIsNone(row["result"]["confirmed_at"])
                self.assertEqual(row["result_observation_rejections"],[dict(captured_at=o["captured_at"],source_sha256=o["source_sha256"],reason=reason)])
                self.assertIn("RESULT_OBSERVATION_REJECTED",row["missing_reasons"])
                self.assertEqual(state,before)

    def test_one_bad_result_does_not_block_another_race_or_change_saved_forecasts(self):
        state,_=saved_state();first=state["rows"][0]
        other=deepcopy(first);other["race_id"]="20300401-02-02";state["rows"].append(other)
        bad=observation(first);bad["closed_at"]="2030-04-01T10:46:00+09:00"
        good=observation(other);state["observations"]=[bad,good];seal(state);before=deepcopy(state)
        rows={r["race_id"]:r for r in M.project_state(state,dataset_status="REAL_REPORTED")["records"]}
        self.assertEqual(rows[first["race_id"]]["result"]["status"],"unsupported")
        self.assertEqual(rows[other["race_id"]]["result"]["status"],"final")
        self.assertEqual(rows[other["race_id"]]["result_observation_rejections"],[])
        self.assertEqual(rows[first["race_id"]]["prediction"]["ordered_candidates"],first["ranked"])
        self.assertEqual(rows[first["race_id"]]["prediction"]["prediction_sha256"],first["model_sha256"])
        self.assertEqual(state,before)

    def test_latest_rejected_capture_does_not_fall_back_to_an_older_final(self):
        for newest_bad in (True,False):
            for reversed_input in (True,False):
                state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
                new.update(captured_at="2030-04-01T02:11:00Z",source_sha256="c"*64)
                bad=new if newest_bad else old;bad["body_identity_verified"]=False
                state["observations"]=[new,old] if reversed_input else [old,new];seal(state)
                with self.subTest(newest_bad=newest_bad,reversed_input=reversed_input):
                    row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                    self.assertEqual(row["result"]["observed_at"],new["captured_at"])
                    self.assertEqual(row["result"]["source_sha256"],new["source_sha256"])
                    self.assertEqual(row["result"]["status"],"unsupported" if newest_bad else "final")
                    self.assertEqual(row["result_observations"],state["observations"])
                    self.assertEqual(len(row["result_observation_rejections"]),1)

    def test_contradictory_finish_order_is_quarantined_without_discarding_raw_results(self):
        for edit in (lambda rows:rows[0].update(finish=rows[1]["finish"]),
                     lambda rows:rows[0].update(finish=None),
                     lambda rows:rows[0].update(finish=True)):
            state,_=saved_state();o=observation(state["rows"][0]);edit(o["data"]["results"])
            state["observations"]=[o];seal(state)
            with self.subTest(edit=edit):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertEqual(row["result"]["status"],"unsupported")
                self.assertEqual(row["result"]["winning_combinations"],[])
                self.assertEqual(row["result_observations"],[o])
                self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_FINISH_ORDER_MISMATCH")
        state,_=saved_state();o=observation(state["rows"][0]);rows=sorted(o["data"]["results"],key=lambda r:r["finish"])
        rows[0]["finish"],rows[1]["finish"]=2,1
        state["observations"]=[o];seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(row["result"]["status"],"unsupported")
        self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_FINISH_ORDER_MISMATCH")

    def test_payout_and_top3_conflicts_are_quarantined_without_exposing_payload_in_reasons(self):
        for reason,edit in (("RESULT_PAYOUT_INVALID",lambda d:d["payouts"][0].update(payout_per_100_yen=-1)),
                            ("RESULT_WINNER_MISMATCH",lambda d:d.update(top3=list(reversed(d["top3"]))))):
            state,_=saved_state();o=observation(state["rows"][0]);edit(o["data"])
            state["observations"]=[o];seal(state)
            with self.subTest(reason=reason):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertEqual(row["result"]["status"],"unsupported")
                self.assertEqual(row["result"]["winning_combinations"],[])
                self.assertEqual(row["result_observation_rejections"],[dict(captured_at=o["captured_at"],source_sha256=o["source_sha256"],reason=reason)])

    def test_observation_only_roster_identity_must_still_be_consistent(self):
        for registration in ("invalid","4002"):
            state,_=saved_state();o=observation(state["rows"][0]);state["rows"]=[]
            if registration == "4002":registration=o["data"]["results"][1]["racer_registration_id"]
            o["data"]["results"][0]["racer_registration_id"]=registration
            state["observations"]=[o];seal(state)
            with self.subTest(registration=registration):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertEqual(row["result"]["status"],"unsupported")
                self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_ROSTER_IDENTITY_MISMATCH")

    def test_coherent_dead_heat_and_abnormal_nonwinning_finish_remain_observations(self):
        state,_=saved_state();o=observation(state["rows"][0]);ordered=sorted(o["data"]["results"],key=lambda r:r["finish"])
        ordered[-1].update(finish=None,finish_status="F")
        state["observations"]=[o];seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(row["result"]["status"],"final")
        self.assertEqual(row["result_observation_rejections"],[])
        ordered[1]["finish"]=1;o["data"]["dead_heat"]=True
        second=deepcopy(o["data"]["payouts"][0]);second["combination"]=list(second["combination"])
        second["combination"][0],second["combination"][1]=second["combination"][1],second["combination"][0]
        o["data"]["payouts"].append(second);seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(row["result"]["status"],"final")
        self.assertEqual(len(row["result"]["winning_combinations"]),2)
        self.assertEqual(row["result_observation_rejections"],[])
        self.assertFalse(row["result"]["official"])
        self.assertIsNone(row["result"]["confirmed_at"])

    def test_saved_forecast_cutoff_variants_remain_exact_and_make_results_unsupported(self):
        state,_=saved_state();first,second=state["rows"]
        second.update(stage="P1",cutoff_at="2030-04-01T11:00:00+09:00")
        o=observation(first);state["observations"]=[o];seal(state);before=deepcopy(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertIsNone(row["cutoff_at"])
        self.assertEqual(row["saved_cutoff_variants"],[first["cutoff_at"],second["cutoff_at"]])
        self.assertIn("SAVED_FORECAST_CUTOFF_CONFLICT",row["missing_reasons"])
        predictions=[row["prediction"]]+row["comparison_predictions"]
        self.assertEqual([p["cutoff_at"] for p in predictions],[first["cutoff_at"],second["cutoff_at"]])
        self.assertEqual([p["prediction_sha256"] for p in predictions],[first["model_sha256"],second["model_sha256"]])
        self.assertEqual(row["result"]["status"],"unsupported")
        self.assertEqual(row["result"]["winning_combinations"],[])
        self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_AMBIGUOUS_FORECAST_CUTOFF")
        self.assertEqual(row["result_observations"],[o])
        self.assertEqual(state,before)

    def test_equivalent_saved_cutoff_spellings_do_not_invent_a_clock_conflict(self):
        state,_=saved_state();state["rows"][1]["cutoff_at"]="2030-04-01T01:59:00Z";seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(row["saved_cutoff_variants"],["2030-04-01T10:59:00+09:00","2030-04-01T01:59:00Z"])
        self.assertEqual(row["cutoff_at"],"2030-04-01T10:59:00+09:00")
        self.assertNotIn("SAVED_FORECAST_CUTOFF_CONFLICT",row["missing_reasons"])

    def test_schedule_cutoffs_match_any_saved_variant_and_never_replace_forecasts(self):
        for schedule_cutoff,conflict in (("2030-04-01T11:00:00+09:00",False),("2030-04-01T11:01:00+09:00",True)):
            state,_=saved_state();first,second=state["rows"]
            second.update(stage="P1",cutoff_at="2030-04-01T11:00:00+09:00")
            state["schedule"]=[dict(race_id=first["race_id"],cutoff_at=schedule_cutoff)];seal(state)
            with self.subTest(conflict=conflict):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertIsNone(row["cutoff_at"])
                self.assertEqual(row["saved_cutoff_variants"],[first["cutoff_at"],second["cutoff_at"]])
                self.assertEqual(row["saved_schedule_cutoff_variants"],[schedule_cutoff])
                self.assertEqual("SAVED_SCHEDULE_CUTOFF_CONFLICT" in row["missing_reasons"],conflict)

    def test_conflicting_schedule_only_clocks_do_not_choose_a_result_cutoff(self):
        state,_=saved_state();o=observation(state["rows"][0]);state["rows"]=[]
        cutoffs=[o["closed_at"],"2030-04-01T11:00:00+09:00"]
        state["schedule"]=[dict(race_id=o["race_id"],cutoff_at=c) for c in cutoffs]
        state["observations"]=[o];seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertIsNone(row["cutoff_at"])
        self.assertEqual(row["saved_cutoff_variants"],[])
        self.assertEqual(row["saved_schedule_cutoff_variants"],cutoffs)
        self.assertIn("SAVED_SCHEDULE_CUTOFF_CONFLICT",row["missing_reasons"])
        self.assertEqual(row["result"]["status"],"unsupported")
        self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_AMBIGUOUS_SCHEDULE_CUTOFF")

    def test_observation_only_cutoff_conflicts_are_quarantined_in_both_input_orders(self):
        for reverse in (False,True):
            state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
            new.update(closed_at="2030-04-01T11:00:00+09:00",captured_at="2030-04-01T02:11:00Z",source_sha256="c"*64)
            state["rows"]=[];state["observations"]=[new,old] if reverse else [old,new];seal(state);before=deepcopy(state)
            with self.subTest(reverse=reverse):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertIsNone(row["cutoff_at"])
                self.assertEqual(set(row["saved_observation_cutoff_variants"]),{old["closed_at"],new["closed_at"]})
                self.assertEqual(len(row["saved_observation_cutoff_variants"]),2)
                self.assertEqual(row["result"]["status"],"unsupported")
                self.assertEqual(row["result"]["observed_at"],new["captured_at"])
                self.assertEqual(row["result"]["winning_combinations"],[])
                self.assertFalse(row["result"]["official"])
                self.assertIsNone(row["result"]["confirmed_at"])
                self.assertEqual([r["reason"] for r in row["result_observation_rejections"]],["RESULT_AMBIGUOUS_OBSERVATION_CUTOFF"]*2)
                self.assertEqual(row["result_observations"],state["observations"])
                self.assertEqual(state,before)

    def test_observation_cutoff_variants_do_not_override_forecasts_schedules_or_equivalent_instants(self):
        for context in ("forecast","schedule","equivalent_observations"):
            state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
            new.update(closed_at="2030-04-01T11:00:00+09:00",captured_at="2030-04-01T02:11:00Z",source_sha256="c"*64)
            if context != "forecast":state["rows"]=[]
            if context == "schedule":state["schedule"]=[dict(race_id=old["race_id"],cutoff_at=old["closed_at"])]
            if context == "equivalent_observations":new["closed_at"]="2030-04-01T01:59:00Z"
            state["observations"]=[new,old];seal(state)
            with self.subTest(context=context):
                row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
                self.assertNotIn("saved_observation_cutoff_variants",row)
                self.assertIsNotNone(row["cutoff_at"])
                self.assertEqual(row["result"]["status"],"final" if context == "equivalent_observations" else "unsupported")
                if context != "equivalent_observations":
                    self.assertEqual(row["cutoff_at"],old["closed_at"])
                    self.assertEqual(row["result_observation_rejections"][0]["reason"],"RESULT_CUTOFF_MISMATCH")

    def test_ambiguous_observation_only_captures_still_enforce_integrity(self):
        for edit in (lambda o:o.update(source_sha256="invalid"),
                     lambda o:o.update(captured_at="2030-04-01T02:10:00Z"),
                     lambda o:o.update(race_id="not-a-race"),
                     lambda o:o.update(closed_at="not-a-clock")):
            state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
            new.update(closed_at="2030-04-01T11:00:00+09:00",captured_at="2030-04-01T02:11:00Z");edit(new)
            state["rows"]=[];state["observations"]=[old,new];seal(state)
            with self.subTest(edit=edit),self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")

    def test_result_capture_integrity_still_fails_closed(self):
        for edit in (lambda o:o.update(race_id="not-a-race"),
                     lambda o:o.update(race_id="20300402-01-01"),
                     lambda o:o.update(source_sha256="invalid"),
                     lambda o:o.update(captured_at="not-a-clock"),
                     lambda o:o.update(closed_at="not-a-clock"),
                     lambda o:o.update(data=[])):
            state,_=saved_state();o=observation(state["rows"][0]);edit(o);state["observations"]=[o];seal(state)
            with self.subTest(edit=edit),self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED")
        state,_=saved_state();old=observation(state["rows"][0]);new=deepcopy(old)
        new.update(captured_at="2030-04-01T11:10:00+09:00",body_identity_verified=False)
        state["observations"]=[old,new];seal(state)
        with self.assertRaisesRegex(ValueError,"duplicate result capture"):M.project_state(state,dataset_status="REAL_REPORTED")

    def test_raw_original_enrichment_rejects_tampered_or_cross_artifact_documents(self):
        state,doc=saved_state();changed=deepcopy(doc)
        changed["predictions"][0]["models"][state["rows"][0]["model_id"]]["model_version"]="made-up"
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[changed])
        wrapper=dict(artifact_id=999,member_name="forecasts.json",member_sha256=state["rows"][0]["original_json_sha256"],document=doc)
        with self.assertRaises(ValueError):M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[wrapper])

    def test_same_model_shadow_remains_distinct_without_fabricating_a_lost_version(self):
        state,_=saved_state();shadow=deepcopy(state["rows"][0])
        shadow.update(variant="LEARNED_SHADOW",training_sha256="d"*64,model_sha256="e"*64,baseline_model_sha256=state["rows"][0]["model_sha256"])
        state["learning_shadows"]=[shadow];seal(state)
        row=M.project_state(state,dataset_status="REAL_REPORTED")["records"][0]
        self.assertEqual(row["comparison_predictions"][-1]["variant"],"LEARNED_SHADOW")
        self.assertIsNone(row["comparison_predictions"][-1]["model_version"])
        self.assertEqual(row["comparison_predictions"][-1]["training_sha256"],"d"*64)

    def test_projection_runs_no_predictor_network_or_settlement_function(self):
        state,doc=saved_state()
        with patch("race_ai.boat_observed_pairwise_models.predict_pair",side_effect=AssertionError("prediction forbidden")),\
             patch("race_ai.frozen_day_cycle.settle",side_effect=AssertionError("rescoring forbidden")),\
             patch("urllib.request.urlopen",side_effect=AssertionError("network forbidden")):
            one=M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[doc])
            two=M.project_state(state,dataset_status="REAL_REPORTED",original_documents=[doc])
        self.assertEqual(one,two)

    def test_result_and_training_members_are_not_misread_as_prediction_documents(self):
        state,doc=saved_state();o=observation(state["rows"][0]);r=state["rows"][0]
        state.update(schema="RACE_AI_PRIVATE_ARTIFACT_READBACK_V1",complete=False,coverage_scope="EXPLICIT_ARTIFACTS_ONLY",observations=[o],
                     original_documents=[dict(artifact_id=r["artifact_id"],member_name="forecasts.json",member_sha256=r["original_json_sha256"],document=doc),
                         dict(artifact_id=700,member_name="official-result-observations.json",member_sha256="a"*64,document=[o]),
                         dict(artifact_id=700,member_name="status.json",member_sha256="b"*64,document={"schema":"RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1","forecast_count":2}),
                         dict(artifact_id=700,member_name="trained_observed_models.json",member_sha256="c"*64,document={"schema":"RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1","models":{"bogus":{"model_version":"NEVER_BORROW_THIS"}}})])
        seal(state)
        view=M.project_state(state,dataset_status="SYNTHETIC_ONLY")
        self.assertEqual(len(view["records"][0]["result_observations"]),1)
        self.assertEqual(view["records"][0]["prediction"]["model_version"],"0.1.0-UNTRAINED")
        self.assertEqual(len(view["original_document_references"]),4)
        self.assertNotIn("document",view["original_document_references"][0])

    def test_actual_local_restore_to_projection_with_result_and_optional_members(self):
        from tests.test_private_cycle_restore import PrivateRestoreTests
        from race_ai.private_cycle_restore import restore_manifest
        fixture=PrivateRestoreTests(methodName="runTest");fixture.setUp()
        try:
            _,raw,receipt=fixture.p0();_,rows=read_p0(raw,receipt,expected_day="2030-04-01")
            o=observation(rows[0]);out=io.BytesIO()
            with zipfile.ZipFile(out,"w") as z:
                z.writestr("official-result-observations.json",json.dumps([o]))
                z.writestr("status.json",json.dumps({"schema":"RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1","forecast_count":2}))
                z.writestr("trained_observed_models.json",json.dumps({"schema":"RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1","state":"INSUFFICIENT_VERIFIED_RACES"}))
            body=out.getvalue();meta=dict(id=700,name="race-existing-cycle-99",expired=False,created_at="2030-04-01T02:15:00Z",
                digest="sha256:"+hashlib.sha256(body).hexdigest(),workflow_run=dict(id=99,head_repository_id=1416489937))
            fixture.add("result",body,meta,"official-result-observations.json")
            from race_ai.private_cycle_capture import capture_artifacts
            replies={}
            for entry in fixture.manifest["artifacts"]:
                replies[f'actions/artifacts/{entry["artifact_id"]}']=(fixture.root/entry["metadata_file"]).read_bytes()
                replies[f'actions/artifacts/{entry["artifact_id"]}/zip']=(fixture.root/entry["zip_file"]).read_bytes()
            target=fixture.root/"captured"
            captured=capture_artifacts("2030-04-01",[e["artifact_id"] for e in fixture.manifest["artifacts"]],target,github_get=lambda path:replies[path])
            restored=restore_manifest(captured,target)
            before=deepcopy(restored)
            view=M.project_state(restored,dataset_status="SYNTHETIC_ONLY")
            self.assertEqual(restored,before)
            self.assertEqual(len(view["records"]),1)
            self.assertEqual(view["records"][0]["result_observations"],[o])
            self.assertEqual(view["records"][0]["result"]["observed_at"],o["captured_at"])
            self.assertIsNone(view["records"][0]["result"]["confirmed_at"])
            self.assertFalse(view["independent_receipt_verified"])
        finally:
            fixture.doCleanups()

    def test_saved_native_learned_versions_are_visible_without_training_replay(self):
        parsed,raw,receipt=saved_learned_archive();_,rows=read_p1(raw,receipt)
        shadows=parsed["learned_pairwise_shadows"]
        state=seal(dict(schema="RACE_AI_PRIVATE_ARTIFACT_READBACK_V1",day_jst="2030-04-01",rows=rows,observations=[],receipts=[receipt],complete=False,
            original_documents=[dict(artifact_id=receipt["id"],member_name="national.json",member_sha256=rows[0]["original_json_sha256"],document=parsed)]))
        with patch("race_ai.observed_weight_learning.make_shadows",side_effect=AssertionError("inference forbidden")),\
             patch("race_ai.observed_weight_learning.fit_from_verified",side_effect=AssertionError("training forbidden")):
            view=M.project_state(state,dataset_status="SYNTHETIC_ONLY")
        variants=[view["records"][0]["prediction"]]+view["records"][0]["comparison_predictions"]
        learned=[p for p in variants if p.get("variant")=="LEARNED_SHADOW"]
        self.assertEqual(len(variants),7);self.assertEqual(len(learned),2)
        for p,original in zip(learned,shadows):
            self.assertEqual(p["model_version"],original["model_version"])
            self.assertEqual(p["ordered_top8"],original["ordered_top8"])
            self.assertEqual(p["prediction_sha256"],original["prediction_sha256"])
            self.assertFalse(p["external_receipt_verified"])
            self.assertIn("TRAINING_RECEIPT_NOT_INDEPENDENTLY_VERIFIED",p["missing_reasons"])


if __name__ == "__main__":unittest.main()
