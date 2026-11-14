"""Offline dispatch of real existing algorithms with explicitly fictional inputs."""
from copy import deepcopy
from datetime import datetime
import importlib
import hashlib
import json
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.existing_model_coverage import catalog, active_catalog
from race_ai.boat_ab_shadow import build_pair, MODEL_IDS as AB
from race_ai.boat_multi_feature_models import run_models, MODEL_IDS as FULL
from race_ai.four_sport_model_suite import run_suite, ALL_MODELS
from race_ai.four_sport_learning import LEARNED_ID
from tests.test_boat_ab_shadow import fixture as ab_fixture
from tests.test_boat_multi_feature_models import fixture as full_fixture
from tests.test_boat_observed_pairwise_models import fixture as observed_fixture
from tests.test_comprehensive_four_sport_models import sample as shared_fixture
from tests.test_autorace_personal_baseline import sample as auto_fixture
from tests.test_boat_live_feature_shadow import fixture as clite_fixture
from tests.test_boat_tactical_scenarios import inputs as tactical_fixture, FORECAST_AT

try:
    M = importlib.import_module("race_ai.existing_model_dispatch")
except ModuleNotFoundError:
    M = None


def schedule(race_id, cutoff, stage="P1", sport="boat"):
    return [{"race_id":race_id,"sport":sport,"cutoff_at":cutoff,"stage":stage}]


def inputs(race_id, stage, **groups):
    return {race_id:{stage:groups}}


def slot(report, mid):
    return next(s for s in report["slots"] if s["model_id"] == mid)


class ExistingDispatchTests(unittest.TestCase):
    def test_dispatch_contract_exists(self):
        self.assertIsNotNone(M, "offline existing-model dispatch is missing")

    def test_all_fifteen_active_slots_preserve_sport_applicability_without_inputs(self):
        self.assertIsNotNone(M)
        for sport in ("boat","keirin","autorace","horse"):
            rows=schedule(sport+":2030-01-15:fixture:1","2030-01-15T10:00:00+09:00",sport=sport)
            report=M.dispatch(rows,{},now="2030-01-15T09:10:00+09:00")
            self.assertEqual(len(report["slots"]),15)
            self.assertEqual({r["model_id"] for r in report["slots"]},{m["model_id"] for m in active_catalog()})
            for spec in active_catalog():
                r=slot(report,spec["model_id"])
                if sport not in spec["applicable_sports"]:
                    self.assertEqual(r["status"],"NOT_APPLICABLE")
                else:
                    self.assertIn(r["status"],("INPUT_MISSING","TRAINED_ARTIFACT_MISSING","UNCONNECTED_NATIVE_RUNTIME"))
            self.assertEqual(report["source_requests"],0)
            self.assertFalse(report["external_receipts_created"])

    def test_unexpected_native_runtime_exception_is_explicit_and_never_becomes_missing_input(self):
        source=ab_fixture();at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        with patch.object(M,"build_pair",side_effect=RuntimeError("SECRET_PRIVATE_MODEL_INPUT")):
            report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at)
        for mid in AB:
            target=slot(report,mid)
            self.assertEqual(target["status"],"EXECUTION_FAILED")
            self.assertEqual(target["reason"],"NATIVE_EXECUTION_EXCEPTION")
            self.assertIsNone(target["prediction"])
            self.assertIsNone(target["output_sha256"])
        self.assertEqual(report["status_counts"]["EXECUTION_FAILED"],len(AB))
        self.assertNotIn("SECRET_PRIVATE_MODEL_INPUT",json.dumps(report))
        self.assertEqual(report["source_requests"],0)
        self.assertFalse(report["external_receipts_created"])

    def test_boat_group_calls_original_algorithm_once_and_retains_both_exact_predictions(self):
        source=ab_fixture(); at="2030-11-03T13:18:00+09:00"; rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        before=deepcopy(raw); expected=build_pair(source,at)
        with patch.object(M,"build_pair",wraps=M.build_pair) as called:
            report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at)
        self.assertEqual(called.call_count,1)
        for original in expected["models"]:
            r=slot(report,original["model_id"])
            self.assertEqual(r["status"],"GENERATED_UNATTESTED")
            self.assertEqual(r["prediction"],original)
            self.assertEqual(r["prediction_sha256"],original["model_sha256"])
            self.assertIsNone(r["model_version"],"native model did not save a separate version")
            self.assertFalse(r["external_receipt_verified"])
        self.assertEqual(raw,before)
        self.assertEqual(report["input_sha256"],digest(before))

    def test_shared_group_returns_every_one_of_four_models_once_for_each_applicable_sport(self):
        for sport in ("boat","keirin","autorace","horse"):
            snap=shared_fixture(sport,size=3 if sport in ("autorace","horse") else None)
            race=snap["race"]; at=race["as_of"]
            raw=inputs(race["race_id"],"P0",shared={"snapshot":snap})
            expected=run_suite(snap)
            with patch.object(M,"run_suite",wraps=M.run_suite) as called:
                report=M.dispatch(schedule(race["race_id"],race["sales_cutoff_at"],"P0",sport),raw,now=at)
            self.assertEqual(called.call_count,1)
            for mid in ALL_MODELS:
                r=slot(report,mid)
                self.assertEqual(r["prediction"],expected["models"][mid])
                self.assertEqual(r["model_version"],expected["models"][mid]["model_version"])
                self.assertEqual(r["stage"],"P0")
            self.assertEqual(slot(report,LEARNED_ID)["status"],"TRAINED_ARTIFACT_MISSING")

    def test_all_complete_original_groups_are_read_before_any_native_inference_even_after_cutoff(self):
        source=ab_fixture(); at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        first=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at)
        originals=[s for s in first["slots"] if s["status"]=="GENERATED_UNATTESTED"]
        before=deepcopy(originals)
        with patch.object(M,"build_pair",side_effect=AssertionError("original must not be recomputed")):
            second=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now="2030-11-03T15:00:00+09:00",originals=originals)
        for mid in AB:
            self.assertEqual(slot(second,mid)["status"],"ORIGINAL_REUSED")
            self.assertEqual(slot(second,mid)["prediction"],slot(first,mid)["prediction"])
        self.assertEqual(originals,before)

    def test_missing_sibling_can_be_generated_without_replacing_original(self):
        source=ab_fixture(); at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        first=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at)
        original=slot(first,AB[0]); altered=deepcopy(raw)
        altered[rid]["P1"]["boat_ab"]["source"]["boats"][0]["motor_two_place_rate_percent"]=99
        second=M.dispatch(schedule(rid,source["cutoff_at"]),altered,now=at,originals=[original])
        self.assertEqual(slot(second,AB[0])["status"],"ORIGINAL_REUSED")
        self.assertEqual(slot(second,AB[0])["prediction"],original["prediction"])
        self.assertEqual(slot(second,AB[1])["status"],"GENERATED_UNATTESTED")
        self.assertNotEqual(slot(second,AB[1])["prediction_sha256"],slot(first,AB[1])["prediction_sha256"])

    def test_conflicting_or_tampered_original_hashes_fail_closed(self):
        source=ab_fixture();at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        original=slot(M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at),AB[0])
        changed=deepcopy(original);changed["prediction"]["top8"][0]["ticket"]="6-5-4"
        with self.assertRaisesRegex(ValueError,"original"):
            M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at,originals=[changed])
        with self.assertRaisesRegex(ValueError,"original"):
            M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at,originals=[original,{**original,"prediction_sha256":"f"*64}])

    def test_deadline_cannot_be_evaded_by_old_generated_timestamp(self):
        source=ab_fixture();at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        with patch.object(M,"build_pair",side_effect=AssertionError("too late")):
            report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=source["cutoff_at"])
        self.assertEqual(slot(report,AB[0])["status"],"DEADLINE_PASSED")

    def test_actual_dispatch_time_cannot_be_backdated_for_new_generation(self):
        source=ab_fixture();rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":"2030-11-03T13:18:00+09:00"})
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now="2030-11-03T13:19:00+09:00")
        self.assertEqual(slot(report,AB[0])["status"],"INPUT_REJECTED")

    def test_source_permission_defaults_deny_and_payload_boolean_is_not_a_grant(self):
        snap=shared_fixture("boat",scope="OPERATOR_SUPPLIED_RESEARCH");r=snap["race"]
        raw=inputs(r["race_id"],"P0",shared={"snapshot":snap,"source_rights_verified":True})
        for checker in (None,True,lambda *_:False):
            report=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0"),raw,now=r["as_of"],allow_source=checker)
            self.assertEqual(slot(report,ALL_MODELS[0])["status"],"SOURCE_NOT_AUTHORIZED")
        report=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0"),raw,now=r["as_of"],allow_source=lambda *_:True)
        self.assertEqual(slot(report,ALL_MODELS[0])["status"],"GENERATED_UNATTESTED")

    def test_full_boat_and_observed_pairs_keep_every_returned_output(self):
        snap=full_fixture();at=snap["as_of"];rid=snap["race_id"]
        report=M.dispatch(schedule(rid,snap["sales_cutoff_at"]),inputs(rid,"P1",boat_full={"snapshot":snap}),now=at)
        expected=run_models(snap)
        for mid in FULL:self.assertEqual(slot(report,mid)["prediction"],expected[mid])
        snap=observed_fixture("P1");rid=snap["race_id"]
        report=M.dispatch(schedule(rid,snap["sales_cutoff_at"]),inputs(rid,"P1",boat_observed={"snapshot":snap}),now=snap["as_of"])
        for mid in ("boat-observed-pairwise-factor-v1","boat-observed-pairwise-start-v1"):
            self.assertEqual(slot(report,mid)["status"],"GENERATED_UNATTESTED")
            self.assertEqual(slot(report,mid)["prediction"]["stage"],"P1")

    def test_wrong_native_race_cutoff_stage_or_sport_is_rejected(self):
        snap=shared_fixture("boat");r=snap["race"]
        for field,value in (("race_id","boat:2030-01-15:other:1"),("sales_cutoff_at","2030-01-15T10:05:00+09:00"),("sport","horse")):
            altered=deepcopy(snap);altered["race"][field]=value
            raw=inputs(r["race_id"],"P0",shared={"snapshot":altered})
            report=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0"),raw,now=r["as_of"])
            self.assertEqual(slot(report,ALL_MODELS[0])["status"],"INPUT_REJECTED")
        observed=observed_fixture("P0");rid=observed["race_id"]
        report=M.dispatch(schedule(rid,observed["sales_cutoff_at"]),inputs(rid,"P1",boat_observed={"snapshot":observed}),now=observed["as_of"])
        self.assertEqual(slot(report,"boat-observed-pairwise-factor-v1")["status"],"INPUT_REJECTED")

    def test_personal_autorace_calls_existing_formula_with_native_phase(self):
        snap=auto_fixture();r=snap["race"];at="2030-01-15T09:22:00+09:00"
        raw=inputs(r["race_id"],r["phase"],autorace_personal={"scope":"SYNTHETIC_ONLY","snapshot":snap,"generated_at":at})
        report=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],r["phase"],"autorace"),raw,now=at)
        record=slot(report,"autorace-personal-observed-baseline-v1")
        self.assertEqual(record["status"],"GENERATED_UNATTESTED")
        self.assertEqual(record["stage"],r["phase"])
        self.assertEqual(record["model_version"],"0.1.0-HEURISTIC-UNTRAINED")

    def test_determinism_and_no_io_or_original_input_mutation(self):
        snap=shared_fixture("keirin");r=snap["race"];raw=inputs(r["race_id"],"P0",shared={"snapshot":snap})
        before=deepcopy(raw)
        with patch("urllib.request.urlopen",side_effect=AssertionError("GET forbidden")),patch("socket.create_connection",side_effect=AssertionError("network forbidden")):
            one=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0","keirin"),raw,now=r["as_of"])
            two=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0","keirin"),raw,now=r["as_of"])
        self.assertEqual(one,two);self.assertEqual(raw,before)

    def test_schedule_duplicates_or_conflicting_race_identity_are_not_silently_overwritten(self):
        rows=schedule("boat:2030-01-15:fixture:1","2030-01-15T10:00:00+09:00")
        with self.assertRaisesRegex(ValueError,"schedule"):
            M.dispatch(rows+rows,{},now="2030-01-15T09:00:00+09:00")

    def test_clite_and_tactical_native_paths_keep_their_existing_saved_rankings(self):
        source,extra,at=clite_fixture();rid=source["race_id"]
        raw=inputs(rid,"P1",boat_clite={"scope":"SYNTHETIC_ONLY","base_source":source,"extra":extra,"generated_at":at})
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at)
        mid="boat-local-start-course-shadow-v0.1-UNTRAINED"
        self.assertEqual(slot(report,mid)["prediction"],M.build_live_feature_shadow(source,extra,at))
        source,profiles,venue=tactical_fixture();rid=source["race_id"]
        raw=inputs(rid,"P1",boat_tactical={"scope":"SYNTHETIC_ONLY","source":source,"histories":profiles,"venue":venue,"generated_at":FORECAST_AT})
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=FORECAST_AT)
        mid="boat-course-entry-method-scenarios-v0.1-UNTRAINED"
        self.assertEqual(slot(report,mid)["prediction"],M.predict_tactical_shadow(source,profiles,venue,FORECAST_AT))

    def test_missing_actual_profiles_remain_missing_per_model(self):
        source,_,venue=tactical_fixture();rid=source["race_id"]
        raw=inputs(rid,"P1",boat_tactical={"scope":"SYNTHETIC_ONLY","source":source,"histories":[],"venue":venue})
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=FORECAST_AT)
        self.assertEqual(slot(report,"boat-course-entry-method-scenarios-v0.1-UNTRAINED")["status"],"INPUT_MISSING")

    def test_saved_fitted_artifact_inference_does_not_discard_four_baselines(self):
        import json
        from race_ai.four_sport_learning import fit_training_only
        training=[]
        for n in range(1,7):
            day=f"2030-01-{n:02d}"
            snap=json.loads(json.dumps(shared_fixture("boat")).replace("2030-01-15",day))
            training.append({"snapshot":snap,"result":{"race_id":snap["race"]["race_id"],"status":"settled",
                "ordered_top3":[1,2,3],"published_at":day+"T11:00:00+09:00","captured_at":day+"T11:05:00+09:00",
                "source_ref":"synthetic://official-fixture","source_rights_ref":"synthetic-result-v1"}})
        model=fit_training_only(training,sport="boat",train_end_at="2030-01-07T23:59:00+09:00",epochs=1,
                                now=lambda:datetime.fromisoformat("2030-01-08T00:00:00+09:00"))
        snap=shared_fixture("boat");r=snap["race"]
        raw=inputs(r["race_id"],"P0",shared={"snapshot":snap,"learned_model":model})
        report=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0"),raw,now=r["as_of"])
        self.assertEqual(sum(s["status"]=="GENERATED_UNATTESTED" for s in report["slots"]),5)
        self.assertEqual(slot(report,LEARNED_ID)["prediction"],M.learned_forecast(snap,model))
        model["weights"][0]+=1
        changed=M.dispatch(schedule(r["race_id"],r["sales_cutoff_at"],"P0"),raw,now=r["as_of"])
        self.assertEqual(slot(changed,LEARNED_ID)["status"],"INPUT_REJECTED")
        self.assertTrue(all(slot(changed,mid)["status"]=="GENERATED_UNATTESTED" for mid in ALL_MODELS))

    @patch("race_ai.existing_model_coverage.RETIRED_MODEL_IDS", frozenset())
    def test_historical_seller_global_five_race_rule_and_0700_window_are_preserved(self):
        cards,waku={},{}
        for n in range(1,9):
            rid=f"2030011518{n:02d}";card={"レースコード":rid};w={"レースコード":rid}
            for lane in range(1,7):
                p=f"艇{lane}_";card[p+"全国勝率"]=str(6.5 if lane==1 else 5.8-.35*(lane-2))
                card[p+"級別"]="A1" if lane==1 else "B1";w[p+"枠番別勝率"]=str(8+n*.1 if lane==1 else 6.8-.5*(lane-2))
            cards[rid]=card;waku[rid]=w
        rows=[{"race_id":rid,"sport":"boat","stage":"P0","cutoff_at":"2030-01-15T10:00:00+09:00"} for rid in cards]
        raw={rid:{"P0":{"seller":{"scope":"SYNTHETIC_ONLY","cards":cards,"waku":waku,"day":"2030-01-15"}}} for rid in cards}
        report=M.dispatch(rows,raw,now="2030-01-15T06:30:00+09:00")
        seller=[s for s in report["slots"] if s["model_id"]=="seller-shadow-v1-20261104"]
        self.assertEqual(sum(s["status"]=="GENERATED_UNATTESTED" for s in seller),5)
        self.assertEqual(sum(s["status"]=="RULE_FILTERED" for s in seller),3)
        late=M.dispatch(rows,raw,now="2030-01-15T07:00:00+09:00")
        self.assertTrue(all(s["status"]=="DEADLINE_PASSED" for s in late["slots"] if s["model_id"]=="seller-shadow-v1-20261104"))
        original=next(s for s in seller if s["status"]=="GENERATED_UNATTESTED")
        replay=M.dispatch(rows,raw,now="2030-01-15T07:00:00+09:00",originals=[original])
        self.assertEqual(next(s for s in replay["slots"] if s["race_id"]==original["race_id"] and s["model_id"]==original["model_id"])["status"],"ORIGINAL_REUSED")
        requested=deepcopy(rows)
        for r in requested:r["model_versions"]={original["model_id"]:"unavailable-v2"}
        mismatch=M.dispatch(requested,raw,now="2030-01-15T06:40:00+09:00",originals=[original])
        self.assertTrue(all(s["status"]=="INPUT_REJECTED" for s in mismatch["slots"] if s["model_id"]==original["model_id"]))
        self.assertEqual(mismatch["retained_originals"],[original])
        split=deepcopy(raw)
        for rid in cards:
            split[rid]["P0"]["seller"]["cards"]={rid:cards[rid]}
            split[rid]["P0"]["seller"]["waku"]={rid:waku[rid]}
        inconsistent=M.dispatch(rows,split,now="2030-01-15T06:30:00+09:00")
        self.assertTrue(all(s["status"]=="INPUT_REJECTED" for s in inconsistent["slots"] if s["model_id"]=="seller-shadow-v1-20261104"))
        with patch.object(M,"seller_generate",side_effect=AssertionError("saved daily decision must not be re-ranked")):
            frozen=M.dispatch(rows,split,now="2030-01-15T06:40:00+09:00",originals=[original])
        frozen_seller=[s for s in frozen["slots"] if s["model_id"]==original["model_id"]]
        self.assertEqual(sum(s["status"]=="ORIGINAL_REUSED" for s in frozen_seller),5)
        self.assertEqual(sum(s["status"]=="RULE_FILTERED" for s in frozen_seller),3)

    def test_explicit_requested_version_does_not_hide_behind_a_different_original(self):
        snap=shared_fixture("boat");r=snap["race"];raw=inputs(r["race_id"],"P0",shared={"snapshot":snap})
        rows=schedule(r["race_id"],r["sales_cutoff_at"],"P0")
        original=slot(M.dispatch(rows,raw,now=r["as_of"]),ALL_MODELS[0])
        wanted=deepcopy(rows);wanted[0]["model_versions"]={ALL_MODELS[0]:"unavailable-v2"}
        report=M.dispatch(wanted,raw,now=r["as_of"],originals=[original])
        self.assertEqual(slot(report,ALL_MODELS[0])["status"],"INPUT_REJECTED")
        self.assertEqual(report["retained_originals"],[original])

    def test_original_native_race_identity_cannot_be_relabelled_by_outer_metadata(self):
        snap=shared_fixture("boat");r=snap["race"];raw=inputs(r["race_id"],"P0",shared={"snapshot":snap})
        rows=schedule(r["race_id"],r["sales_cutoff_at"],"P0")
        original=slot(M.dispatch(rows,raw,now=r["as_of"]),ALL_MODELS[0])
        p=original["prediction"];p["race_id"]="boat:2030-01-15:other:1"
        p["prediction_sha256"]=digest({k:v for k,v in p.items() if k!="prediction_sha256"})
        original["prediction_sha256"]=p["prediction_sha256"];original["output_sha256"]=digest(p)
        with self.assertRaisesRegex(ValueError,"original"):
            M.dispatch(rows,raw,now=r["as_of"],originals=[original])

    def test_outer_synthetic_flag_cannot_override_declared_research_snapshot(self):
        snap=full_fixture();snap["scope"]="OPERATOR_SUPPLIED_RESEARCH";rid=snap["race_id"]
        raw=inputs(rid,"P1",boat_full={"scope":"SYNTHETIC_ONLY","snapshot":snap})
        report=M.dispatch(schedule(rid,snap["sales_cutoff_at"]),raw,now=snap["as_of"])
        self.assertTrue(all(slot(report,mid)["status"]=="INPUT_REJECTED" for mid in FULL))
        self.assertTrue(all(slot(report,mid)["prediction"] is None for mid in FULL))

    def test_clite_extra_observations_need_their_own_bound_source_grant(self):
        source,extra,at=clite_fixture();rid=source["race_id"]
        evidence=[{"source_ref":"https://example.test/program","source_rights_ref":"owner-analysis","source_sha256":source["program_source_sha256"]},
                  {"source_ref":"https://example.test/beforeinfo","source_rights_ref":"owner-analysis","source_sha256":source["beforeinfo_source_sha256"]}]
        payload={"scope":"OPERATOR_SUPPLIED_RESEARCH","base_source":source,"extra":extra,"generated_at":at,"source_evidence":evidence}
        raw=inputs(rid,"P1",boat_clite=payload)
        authorize=lambda ref,rights,purpose:ref.startswith("https://example.test/") and rights=="owner-analysis" and purpose=="analysis"
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at,allow_source=authorize)
        mid="boat-local-start-course-shadow-v0.1-UNTRAINED"
        self.assertEqual(slot(report,mid)["status"],"SOURCE_NOT_AUTHORIZED")
        evidence.append({"source_ref":"https://example.test/local-start","source_rights_ref":"owner-analysis","source_sha256":extra["source_sha256"]})
        report=M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at,allow_source=authorize)
        self.assertEqual(slot(report,mid)["status"],"GENERATED_UNATTESTED")

    def test_ab_original_retains_and_checks_the_parent_race_binding(self):
        source=ab_fixture();at="2030-11-03T13:18:00+09:00";rid=source["race_id"]
        raw=inputs(rid,"P1",boat_ab={"scope":"SYNTHETIC_ONLY","source":source,"generated_at":at})
        original=slot(M.dispatch(schedule(rid,source["cutoff_at"]),raw,now=at),AB[0])
        original["race_id"]="20301103-17-06"
        with self.assertRaisesRegex(ValueError,"original"):
            M.dispatch(schedule(original["race_id"],source["cutoff_at"]),{},now=at,originals=[original])

    def test_reused_original_flags_do_not_claim_independent_receipt_or_official_status(self):
        snap=shared_fixture("boat");r=snap["race"];raw=inputs(r["race_id"],"P0",shared={"snapshot":snap})
        rows=schedule(r["race_id"],r["sales_cutoff_at"],"P0")
        original=slot(M.dispatch(rows,raw,now=r["as_of"]),ALL_MODELS[0])
        original.update(external_receipt_verified=True,official_prediction=True)
        report=M.dispatch(rows,{},now=r["as_of"],originals=[original])
        reused=slot(report,ALL_MODELS[0])
        self.assertFalse(reused["external_receipt_verified"]);self.assertFalse(reused["official_prediction"])
        self.assertEqual(report["retained_originals"],[original])

    @patch("race_ai.existing_model_coverage.RETIRED_MODEL_IDS", frozenset())
    def test_historical_seller_cannot_use_unrelated_source_grants_or_postexhibition_stage(self):
        rid="203001151801";card={"レースコード":rid};w={"レースコード":rid}
        for n in range(1,7):
            p=f"艇{n}_";card[p+"全国勝率"]="6.5";card[p+"級別"]="A1";w[p+"枠番別勝率"]="8.0"
        payload={"scope":"OPERATOR_SUPPLIED_RESEARCH","cards":{rid:card},"waku":{rid:w},"day":"2030-01-15",
                 "source_evidence":[{"source_ref":"unrelated-file","source_rights_ref":"unrelated-grant"}]}
        raw=inputs(rid,"P0",seller=payload)
        report=M.dispatch(schedule(rid,"2030-01-15T10:00:00+09:00","P0"),raw,now="2030-01-15T06:30:00+09:00",allow_source=lambda *_:True)
        self.assertEqual(slot(report,"seller-shadow-v1-20261104")["status"],"SOURCE_NOT_AUTHORIZED")
        payload["scope"]="SYNTHETIC_ONLY"
        report=M.dispatch(schedule(rid,"2030-01-15T10:00:00+09:00","P1"),inputs(rid,"P1",seller=payload),now="2030-01-15T06:30:00+09:00")
        self.assertEqual(slot(report,"seller-shadow-v1-20261104")["status"],"INPUT_REJECTED")

    def test_pdca_calls_existing_pure_node_model_without_storage_or_network(self):
        facts={"schema":"RACE_AI_BOAT_OBSERVATION_V1","phase":"post_exhibition","race_id":"20301103-18-05",
               "cutoff_at":"2030-11-03T10:30:00+09:00","captured_at":"2030-11-03T10:14:50+09:00",
               "source_url":"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103",
               "source_sha256":"a"*64,"program_sha256":"b"*64,"rights_verified":True,"license_purpose":"private_analysis",
               "racers":[{"lane":n,"registration_no":str(4200+n),"national_win_rate":5.2+(n-1)*.2,"exhibition_time_seconds":6.8+(n-1)*.01} for n in range(1,7)]}
        history=[]
        for n in range(24):
            day=f"{1+n//12:02d}";date="2030-11-"+day
            report={"race_id":f"203011{day}-18-{1+n%12:02d}","official_top3":[1 if n<18 else 2,3,4],
                    "captured_at":date+"T11:00:00+09:00","source_sha256":hashlib.sha256(str(n).encode()).hexdigest()}
            wire=json.dumps(report,separators=(",",":"))
            history.append({"report_json":wire,"report_sha256":hashlib.sha256(wire.encode()).hexdigest(),"db_saved_at":date+"T11:05:00+09:00"})
        rid=facts["race_id"];at="2030-11-03T10:15:00+09:00"
        raw=inputs(rid,"P1",boat_pdca={"scope":"SYNTHETIC_ONLY","facts":facts,"rows":history})
        result=M.dispatch(schedule(rid,facts["cutoff_at"]),raw,now=at)
        p=slot(result,"boat-pdca-lane-shadow-v1")
        self.assertEqual(p["status"],"GENERATED_UNATTESTED")
        self.assertEqual(p["prediction"]["training_count"],24)
        self.assertEqual(len(p["prediction"]["ordered_top8"]),8)
        self.assertIsNone(p["model_version"])
        with patch.object(M.subprocess,"run",side_effect=AssertionError("saved PDCA cannot invoke Node again")):
            reused=M.dispatch(schedule(rid,facts["cutoff_at"]),{},now=at,originals=[p])
        self.assertEqual(slot(reused,"boat-pdca-lane-shadow-v1")["status"],"ORIGINAL_REUSED")
        self.assertEqual(slot(reused,"boat-pdca-lane-shadow-v1")["prediction"],p["prediction"])
        raw[rid]["P1"]["boat_pdca"]["rows"]=history[:23]
        few=M.dispatch(schedule(rid,facts["cutoff_at"]),raw,now=at)
        self.assertEqual(slot(few,"boat-pdca-lane-shadow-v1")["status"],"INPUT_MISSING")
        raw[rid]["P1"]["boat_pdca"]["rows"]=history
        raw[rid]["P1"]["boat_pdca"]["scope"]="OPERATOR_SUPPLIED_RESEARCH"
        raw[rid]["P1"]["boat_pdca"]["source_evidence"]=[{"source_ref":"current","source_rights_ref":"r","source_sha256":"a"*64},
                                                                  {"source_ref":"program","source_rights_ref":"r","source_sha256":"b"*64}]
        denied=M.dispatch(schedule(rid,facts["cutoff_at"]),raw,now=at,allow_source=lambda *_:True)
        self.assertEqual(slot(denied,"boat-pdca-lane-shadow-v1")["status"],"SOURCE_NOT_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()
