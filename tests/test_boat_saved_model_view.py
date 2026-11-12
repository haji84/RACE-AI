"""Append saved fictional forecasts without rerunning or rewriting any original."""
from copy import deepcopy
import importlib
from itertools import permutations
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

try:
    M = importlib.import_module("race_ai.boat_saved_model_view")
except ModuleNotFoundError:
    M = None


def prediction(**changes):
    ranked = [list(t) for t in permutations(range(1, 7), 3)]
    out = dict(model_id="fictional-model", model_version="1.0", stage="P0", variant="HISTORY_BASELINE",
               prediction_sha256="a" * 64, input_sha256="b" * 64, source_sha256="c" * 64,
               original_json_sha256="d" * 64, physical_receipt_sha256="e" * 64,
               ordered_top8=ranked[:8], ordered_candidates=ranked,
               as_of="2030-04-01T09:00:00+09:00", generated_at="2030-04-01T09:01:00+09:00",
               persisted_at="2030-04-01T09:02:00+09:00", server_saved_at="2030-04-01T09:02:00+09:00",
               cutoff_at="2030-04-01T10:00:00+09:00", odds_independent=True,
               external_receipt_verified=False, missing_reasons=[])
    out.update(changes)
    return out


def view(p=None, *, day="2030-04-01", lanes=range(1, 7)):
    p = prediction() if p is None else p
    return dict(schema="RACE_AI_PRIVATE_CYCLE_VIEW_V1", dataset_status="SYNTHETIC_ONLY", event_date_jst=day,
                records=[dict(race_id=day.replace("-", "") + "-01-01", sport="boat", venue="合成場", race_no=1,
                    event_date_jst=day, cutoff_at=p["cutoff_at"], saved_cutoff_variants=[p["cutoff_at"]],
                    source_sha256="f" * 64, observed_at="2030-04-01T09:03:00+09:00",
                    offering_status="UNKNOWN", participants=[dict(number=n, registration_no=str(4200+n), name=None) for n in lanes],
                    prediction=p, comparison_predictions=[], result=None, result_revisions=[],
                    result_observations=[], result_observation_rejections=[], missing_reasons=[])])


def candidates(row):
    return [p for p in [row["prediction"], *row["comparison_predictions"]] if p]


def add_result(doc, *, at="2030-04-01T11:00:00+09:00", status="final", rejected=False):
    row = doc["records"][0]
    row["result_observations"] = [dict(race_id=row["race_id"], captured_at=at, source_sha256="f" * 64,
        closed_at="2030-04-01T10:00:00+09:00", status="AVAILABLE" if status == "final" else "PENDING", data=None)]
    row["result"] = dict(status=status, observed_at=at, source_sha256="f" * 64, confirmed_at=None,
        official=False, winning_combinations=[[1,2,3]] if status == "final" else [])
    if status == "final":
        row["result"]["payout_yen_per_100"] = 1200
    if rejected:
        row["result_observation_rejections"] = [dict(captured_at=at, source_sha256="f" * 64, reason="RESULT_ROSTER_MISMATCH")]
    return doc


def reconciled_views():
    base = add_result(view()); extra = view(prediction(stage="P1", cutoff_at="2030-04-01T10:01:00+09:00"))
    row = base["records"][0]; observation = row["result_observations"][0]
    observation.update(body_identity_verified=True, closed_at="2030-04-01T10:01:00+09:00",
        data=dict(status="settled", confirmed=True, finish_confirmed=True,
            results=[dict(lane=n,racer_registration_id=str(4200+n),finish=n,finish_status="FINISHED") for n in range(1,7)],
            top3=[1,2,3],payouts=[dict(bet_type="trifecta",combination=[1,2,3],payout_per_100_yen=1200)]))
    row["result"]["cutoff_reconciliation"] = dict(basis="RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF", formal_eligible=False,
        original_cutoffs=["2030-04-01T10:00:00+09:00","2030-04-01T10:01:00+09:00"], source_sha256="f"*64,
        maximum_offset_seconds=60,roster_identity_verified=True,all_originals_saved_before_both=True)
    return base, extra


class SavedModelViewTests(unittest.TestCase):
    def merge(self, base, additions=(), **kwargs):
        self.assertIsNotNone(M, "pure saved forecast union helper is missing")
        return M.merge_saved_views(base, additions, **kwargs)

    def test_union_keeps_first_original_and_appends_stages_versions_variants_and_receipts(self):
        base = view()
        added = [view(prediction(**change)) for change in (
            dict(stage="P1"), dict(model_version="2.0"), dict(variant="HISTORY_ADDED"),
            dict(as_of="2030-04-01T09:00:01+09:00", prediction_sha256="1"*64),
            dict(physical_receipt_sha256="2"*64, prediction_sha256="3"*64),
        )]
        before = deepcopy((base, added))
        with patch("builtins.open", side_effect=AssertionError("union must not perform I/O")), \
             patch("socket.create_connection", side_effect=AssertionError("union must not fetch")):
            out = self.merge(base, added)
        self.assertEqual((base, added), before)
        self.assertEqual(candidates(out["records"][0]), [base["records"][0]["prediction"], *[v["records"][0]["prediction"] for v in added]])
        out["records"][0]["prediction"]["ordered_top8"][0][0] = 6
        self.assertEqual(base["records"][0]["prediction"]["ordered_top8"][0], [1,2,3])

    def test_identical_original_deduplicates_despite_different_row_source_and_observation(self):
        base = view(); extra = deepcopy(base)
        extra["records"][0].update(source_sha256="0"*64, observed_at="2030-04-01T09:05:00+09:00")
        out = self.merge(base, [extra, base])
        self.assertEqual(candidates(out["records"][0]), [base["records"][0]["prediction"]])
        self.assertEqual(self.merge(out, [extra]), out, "repeating saved intake is idempotent")

    def test_differing_original_with_same_save_identity_is_rejected_without_mutation(self):
        for change in (dict(prediction_sha256="1"*64), dict(ordered_top8=[[1,3,2]]), dict(odds_independent=False), dict(odds_independent=1)):
            base = view(); extra = view(prediction(**change)); before = deepcopy((base, extra))
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                self.merge(base, [extra])
            self.assertEqual((base, extra), before)

    def test_different_original_cutoffs_remain_on_each_prediction(self):
        base = add_result(view()); extra = view(prediction(cutoff_at="2030-04-01T10:05:00+09:00"))
        out = self.merge(base, [extra]); row = out["records"][0]
        self.assertIsNone(row["cutoff_at"])
        self.assertEqual(row["saved_cutoff_variants"], ["2030-04-01T10:00:00+09:00", "2030-04-01T10:05:00+09:00"])
        self.assertEqual(candidates(row), [base["records"][0]["prediction"], extra["records"][0]["prediction"]])
        self.assertEqual(row["result"]["status"], "unsupported")

    def test_legitimate_additions_on_another_day_keep_both_dates(self):
        extra = json.loads(json.dumps(view()).replace("2030-04-01", "2030-04-02").replace("20300401", "20300402"))
        out = self.merge(view(), extra)
        self.assertIsNone(out["event_date_jst"])
        self.assertEqual([r["event_date_jst"] for r in out["records"]], ["2030-04-01", "2030-04-02"])

    def test_latest_pending_or_rejected_result_never_falls_back_to_final(self):
        old = add_result(view())
        for status, rejected in (("pending", False), ("unsupported", True)):
            later = add_result(view(), at="2030-04-01T11:30:00+09:00", status=status, rejected=rejected)
            with self.subTest(status=status):
                row = self.merge(later, [old])["records"][0]
                self.assertEqual(row["result"]["status"], status)
                self.assertEqual(len(row["result_observations"]), 2)
                self.assertEqual(row["result"]["winning_combinations"], [])

    def test_newest_raw_observation_without_projected_result_blocks_old_final(self):
        extra = add_result(view(), at="2030-04-01T11:30:00+09:00", status="pending")
        extra["records"][0]["result"] = None
        row = self.merge(add_result(view()), [extra])["records"][0]
        self.assertEqual(row["result"]["status"], "unsupported")
        self.assertEqual(row["result"]["observed_at"], "2030-04-01T11:30:00+09:00")

    def test_conflicting_same_capture_and_foreign_race_metadata_are_rejected(self):
        old = add_result(view()); extra = deepcopy(old)
        extra["records"][0]["result_observations"][0]["status"] = "PENDING"
        with self.assertRaises(ValueError): self.merge(old, [extra])
        for change in (dict(event_date_jst="2030-04-02"), dict(sport="horse"), dict(race_no=2)):
            extra = view(); extra["records"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.merge(view(), [extra])

    def test_same_race_names_override_registry_by_registration_and_never_change_predictions(self):
        base = view()
        names = dict(races={"20300401-01-01": {"4201": {"name":"合成レース選手", "number":1}}},
            registry={"4201":dict(name="合成期別名", verified=True, source_sha256="1"*64),
                      "4202":dict(name="合成登録選手", verified=True, source_sha256="1"*64, captured_at="2030-03-01T09:00:00+09:00")})
        before = deepcopy((base, names)); row = self.merge(base, names=names)["records"][0]
        self.assertEqual((base, names), before)
        self.assertEqual(row["participants"][0]["name"], "合成レース選手")
        self.assertEqual(row["participants"][1]["name"], "合成登録選手")
        self.assertEqual(row["participants"][1]["name_source"]["source_sha256"], "1"*64)
        self.assertIsNone(row["participants"][2]["name"])
        self.assertEqual(candidates(row), candidates(base["records"][0]))

    def test_same_race_official_result_name_requires_exact_sha_clock_url_and_roster(self):
        from race_ai.racer_intraday_source import result_url
        base = view();rid = base['records'][0]['race_id']
        uri = result_url('2030-04-01', '01', 1)
        observed = dict(kind='SAME_RACE_RESULT', name='架空公式結果名', number=1,
            registration_no='4201', race_id=rid, source_url=uri,
            source_sha256='1'*64, captured_at='2030-04-01T11:00:00+09:00')
        names = dict(races={rid:{'4201':observed}}, registry={})
        after = self.merge(base, names=names)
        person = after['records'][0]['participants'][0]
        self.assertEqual(person['name'], '架空公式結果名')
        self.assertEqual(person['name_source']['kind'], 'SAME_RACE_RESULT')
        self.assertEqual(person['name_source']['source_sha256'], '1'*64)
        self.assertEqual(candidates(after['records'][0]), candidates(base['records'][0]))
        for key, value in (
            ('registration_no','9999'), ('number',2),
            ('race_id','20300401-01-02'),
            ('source_url',result_url('2030-04-01','01',2)),
            ('source_url','https://example.invalid/foreign'),
            ('source_sha256','invalid'), ('captured_at',None)):
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                self.merge(base,names=dict(races={rid:{'4201':dict(observed,**{key:value})}},registry={}))

    def test_name_metadata_rejects_lane_registration_race_or_registry_provenance_mismatch(self):
        invalid = [
            dict(races={"20300401-01-01":{"4201":dict(name="合成名", number=2)}}),
            dict(races={"20300401-01-01":{"4201":dict(name="合成名", registration_no="4202")}}),
            dict(races={"20300401-01-01":{"4201":dict(name="合成名", race_id="20300401-01-02")}}),
            dict(registry={"4201":dict(name="合成名", verified=False, source_sha256="1"*64)}),
            dict(registry={"4201":dict(name="合成名", verified=True)}),
            dict(registry={"4201":dict(name="合成名", verified=True, source_sha256="1"*64, racer_id="4202")}),
            dict(races={"20300401-01-01":{"1":"艇番を登録番号と解釈しない"}}),
        ]
        for names in invalid:
            with self.subTest(names=names), self.assertRaises(ValueError): self.merge(view(), names=names)

    def test_additional_same_race_named_roster_enriches_exact_registration(self):
        base = view(); extra = view(prediction(stage="P1"))
        extra["records"][0]["participants"][0]["name"] = "合成直前名"
        row = self.merge(base, [extra])["records"][0]
        self.assertEqual(row["participants"][0]["name"], "合成直前名")
        mismatch = deepcopy(extra); mismatch["records"][0]["participants"][0]["registration_no"] = "4999"
        with self.assertRaises(ValueError): self.merge(base, [mismatch])

    def test_equivalent_official_name_spacing_preserves_first_display_sources_and_rosters(self):
        for original, incoming in (("合成 太郎", "合成\u3000\u3000太郎"),
                                   ("合成 太郎", "合成\t 太郎"),
                                   ("合成 ｶﾞ次郎", "合成\u3000ガ次郎")):
            with self.subTest(kind="spacing_or_width"):
                base = view(); extra = view(prediction(stage="P1"))
                for doc, name, source in ((base, original, "1"*64), (extra, incoming, "2"*64)):
                    row = doc["records"][0]; person = row["participants"][0]
                    person.update(name=name, name_source=dict(kind="SAME_RACE_PROGRAM",
                        registration_no="4201", race_id=row["race_id"], source_sha256=source,
                        captured_at="2030-04-01T09:03:00+09:00"))
                    row["saved_participant_rosters"] = [dict(participants=deepcopy(row["participants"]),
                        source_sha256=source, source_provenance="INVENTED_NATIVE_ROSTER")]
                before = deepcopy((base, extra))
                merged = self.merge(base, [extra]); row = merged["records"][0]
                self.assertEqual((base, extra), before)
                self.assertEqual(row["participants"][0], base["records"][0]["participants"][0])
                self.assertEqual(row["saved_participant_rosters"],
                    [*base["records"][0]["saved_participant_rosters"],
                     *extra["records"][0]["saved_participant_rosters"]])
                self.assertEqual(candidates(row), [*candidates(base["records"][0]), *candidates(extra["records"][0])])
                self.assertEqual(self.merge(merged, [extra]), merged)
                reverse = self.merge(extra, [base])
                self.assertEqual(reverse["records"][0]["participants"][0],
                                 extra["records"][0]["participants"][0])

    def test_equivalent_name_format_never_relaxes_race_registration_or_lane_identity(self):
        for change in (dict(registration_no="4999"), dict(number=2)):
            base = view(); extra = view(prediction(stage="P1"))
            base["records"][0]["participants"][0]["name"] = "合成 太郎"
            extra["records"][0]["participants"][0].update(name="合成\u3000太郎", **change)
            before = deepcopy((base, extra))
            with self.assertRaises(ValueError): self.merge(base, [extra])
            self.assertEqual((base, extra), before)

    def test_existing_display_stays_first_when_old_snapshot_uses_equivalent_formatting(self):
        base = view(); extra = view(prediction(stage="P1"))
        person = base["records"][0]["participants"][0]
        person.update(name="合成 太郎", name_source=dict(kind="SAME_RACE_PROGRAM",
            registration_no="4201", race_id="20300401-01-01", source_sha256="1"*64))
        snapshot = dict(participants=deepcopy(base["records"][0]["participants"]))
        snapshot["participants"][0]["name"] = "合成\u3000太郎"
        snapshot["participants"][0]["name_source"]["source_sha256"] = "2"*64
        base["records"][0]["saved_participant_rosters"] = [snapshot]
        extra["records"][0]["participants"][0]["name"] = "合成  太郎"
        merged = self.merge(base, [extra])
        self.assertEqual(merged["records"][0]["participants"][0], person)
        self.assertEqual(merged["records"][0]["saved_participant_rosters"][0], snapshot)
        self.assertEqual(self.merge(merged, [extra]), merged)

    def test_different_name_letters_still_hold_in_current_or_saved_rosters(self):
        for snapshot_only in (False, True):
            base = view(); extra = view(prediction(stage="P1"))
            base["records"][0]["participants"][0]["name"] = "合成 太郎"
            person = extra["records"][0]["participants"][0]
            person["name"] = "合成\u3000次郎"
            if snapshot_only:
                extra["records"][0]["saved_participant_rosters"] = [dict(
                    participants=deepcopy(extra["records"][0]["participants"]))]
                person["name"] = "合成\u3000太郎"
            before = deepcopy((base, extra))
            with self.assertRaises(M.SavedModelViewError) as error: self.merge(base, [extra])
            self.assertEqual(error.exception.reason_code, "SAVED_MODEL_VIEW_SAME_RACE_NAME_CONFLICT")
            self.assertEqual((base, extra), before)

    def test_explicit_withdrawal_subset_keeps_original_rosters_and_physical_lanes(self):
        base = view(); extra = view(prediction(stage="P1"), lanes=(1,3,6))
        extra["records"][0].update(withdrawn_lanes=[2,4,5], roster_status="OFFICIAL_ACTIVE")
        row = self.merge(base, [extra])["records"][0]
        self.assertEqual([p["number"] for p in row["participants"]], [1,3,6])
        self.assertEqual(row["withdrawn_lanes"], [2,4,5])
        self.assertEqual([len(r["participants"]) for r in row["saved_participant_rosters"]], [6,3])
        self.assertEqual(candidates(row), [base["records"][0]["prediction"], extra["records"][0]["prediction"]])
        uncertain = view(prediction(stage="P1"), lanes=(1,3,6))
        with self.assertRaises(ValueError): self.merge(base, [uncertain])

    def test_noncontiguous_three_entrant_forecast_and_names_survive_browser_parser(self):
        ranked = [list(t) for t in permutations((1,3,6), 3)]
        out = self.merge(view(prediction(ordered_top8=ranked, ordered_candidates=ranked), lanes=(1,3,6)),
            names=dict(races={"20300401-01-01":{"4203":"合成三号"}}))
        script = "const M=require('./web/product-data.js'); const d=M.parse(require('fs').readFileSync(0,'utf8')); const r=d.records[0]; if(M.candidates(r)[0].ordered_top8.length!==6||r.participants[1].number!==3||r.participants[1].name!=='合成三号')process.exit(1);"
        result = subprocess.run(["node", "-e", script], input=json.dumps(out), text=True, capture_output=True,
            cwd=Path(__file__).resolve().parents[1], timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_saved_native_p0_archive_projection_is_added_without_reprediction(self):
        from race_ai.private_cycle_projection import project_state
        from tests.test_private_cycle_projection import saved_state
        state, _ = saved_state(); native = project_state(state, dataset_status="SYNTHETIC_ONLY")
        base = view(); base["records"][0]["participants"] = []
        old = deepcopy(base["records"][0]["prediction"])
        row = self.merge(base, [native])["records"][0]
        self.assertEqual(row["prediction"], old)
        self.assertEqual(row["comparison_predictions"], candidates(native["records"][0]))

    def test_view_scope_mismatch_and_malformed_non_json_inputs_fail_closed(self):
        extra = view(); extra["dataset_status"] = "REAL_REPORTED"
        with self.assertRaises(ValueError): self.merge(view(), [extra])
        bad = view(); bad["records"][0]["prediction"]["score"] = float("nan")
        with self.assertRaises(ValueError): self.merge(bad)

    def test_retained_roster_snapshot_cannot_hide_a_different_displayed_registration(self):
        base = view(); extra = view(prediction(stage="P1"))
        extra["records"][0]["saved_participant_rosters"] = [dict(participants=deepcopy(extra["records"][0]["participants"]))]
        extra["records"][0]["participants"][0]["registration_no"] = "4999"
        with self.assertRaises(ValueError): self.merge(base, [extra])

    def test_participant_name_source_must_bind_the_same_race_and_registration(self):
        for change in (dict(kind="SAME_RACE_PROGRAM", registration_no="4202", race_id="20300401-01-01"),
                       dict(kind="SAME_RACE_PROGRAM", registration_no="4201", race_id="20300401-01-02"),
                       dict(kind="VERIFIED_RACER_REGISTRY", registration_no="4201", verified=False, source_sha256="1"*64)):
            base = view(); base["records"][0]["participants"][0].update(name="合成名", name_source=change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.merge(base)

    def test_explicit_inactive_participant_is_displayed_as_withdrawn_without_losing_snapshot(self):
        base = view(); extra = view(prediction(stage="P1"))
        extra["records"][0]["participants"][1].update(active=False, withdrawn=True)
        row = self.merge(base, [extra])["records"][0]
        self.assertEqual([p["number"] for p in row["participants"]], [1,3,4,5,6])
        self.assertEqual(row["withdrawn_lanes"], [2])
        self.assertEqual(len(row["saved_participant_rosters"][-1]["participants"]), 6)

    def test_latest_row_source_metadata_stays_together_and_never_changes_prediction_source(self):
        base = view(); extra = view(prediction(stage="P1")); row = extra["records"][0]
        row.update(source_sha256="0"*64, observed_at="2030-04-01T09:30:00+09:00", source_provenance="SYNTHETIC_NEW_SOURCE")
        out = self.merge(base, [extra])["records"][0]
        self.assertEqual(out["source_sha256"], "0"*64)
        self.assertEqual(out["source_provenance"], "SYNTHETIC_NEW_SOURCE")
        self.assertEqual(out["prediction"]["source_sha256"], "c"*64)
        self.assertEqual(len(out["saved_row_metadata"]), 2)

    def test_later_explicit_offering_and_race_state_survive_unknown_archive_metadata(self):
        base = view(); latest = view(prediction(stage="P1"))
        latest["records"][0].update(offering_status="NOT_OFFERED", race_status="CANCELLED", observed_at="2030-04-01T09:30:00+09:00")
        row = self.merge(base, [latest, view()])["records"][0]
        self.assertEqual(row["offering_status"], "NOT_OFFERED")
        self.assertEqual(row["race_status"], "CANCELLED")
        out = self.merge(dict(schema=base["schema"],dataset_status=base["dataset_status"],event_date_jst=base["event_date_jst"],records=[row]), [view()])
        self.assertEqual(out["records"][0]["offering_status"], "NOT_OFFERED")

    def test_dispatch_coverage_retains_attempts_and_latest_status_using_saved_view_asof(self):
        old = view(); old["as_of"] = "2030-04-01T09:00:00+09:00"
        latest = view(prediction(stage="P1")); latest["as_of"] = "2030-04-01T09:20:00+09:00"
        for doc, status in ((old,"INPUT_MISSING"),(latest,"GENERATED_UNATTESTED")):
            doc["records"][0]["dispatch_slots"] = [dict(stage="P1", model_id="fictional-model", model_version="1.0", status=status,
                applicable=True, reason="SYNTHETIC_COVERAGE", prediction_sha256=None, output_sha256=None)]
        out = self.merge(latest, [old]); row = out["records"][0]
        self.assertEqual(row["dispatch_slots"][0]["status"], "GENERATED_UNATTESTED")
        self.assertEqual(len(row["saved_dispatch_slot_observations"]), 2)
        self.assertEqual(self.merge(out, [old]), out)

    def test_native_dispatch_families_and_multiple_days_keep_exact_projected_originals(self):
        from race_ai.dispatch_product_projection import project_dispatch
        from tests.test_dispatch_product_projection import all_native_reports
        additions = [project_dispatch(report, dataset_status="SYNTHETIC_ONLY") for report in all_native_reports()]
        expected = {json.dumps(p, sort_keys=True) for doc in [view(), *additions] for row in doc["records"] for p in candidates(row)}
        with patch("builtins.open", side_effect=AssertionError("union must not read files")), \
             patch("socket.create_connection", side_effect=AssertionError("union must not fetch")):
            out = self.merge(view(), additions)
        actual = {json.dumps(p, sort_keys=True) for row in out["records"] for p in candidates(row)}
        self.assertEqual(actual, expected)
        self.assertIsNone(out["event_date_jst"])
        script = "const M=require('./web/product-data.js');const d=M.parse(require('fs').readFileSync(0,'utf8'));if(M.modelGroups(d.records).length<16)process.exit(1);"
        proc = subprocess.run(["node","-e",script], input=json.dumps(out), text=True, capture_output=True,
            cwd=Path(__file__).resolve().parents[1], timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_raw_bound_one_minute_reconciliation_preserves_final_without_rewriting_originals(self):
        base, extra = reconciled_views(); before = deepcopy((base,extra))
        # The other projection may have rejected that very observation solely
        # because its merged forecast clock was ambiguous.
        extra["records"][0].update(result_observations=deepcopy(base["records"][0]["result_observations"]),
            result_observation_rejections=[dict(captured_at="2030-04-01T11:00:00+09:00",source_sha256="f"*64,reason="RESULT_AMBIGUOUS_FORECAST_CUTOFF")])
        row = self.merge(base, [extra])["records"][0]
        self.assertIsNone(row["cutoff_at"])
        self.assertEqual(row["result"]["status"], "final")
        self.assertFalse(row["result"]["cutoff_reconciliation"]["formal_eligible"])
        self.assertEqual(candidates(row),[before[0]["records"][0]["prediction"],before[1]["records"][0]["prediction"]])
        proc=subprocess.run(["node","-e","require('./web/product-data.js').parse(require('fs').readFileSync(0,'utf8'))"],
            input=json.dumps(dict(base,records=[row])), text=True,capture_output=True,cwd=Path(__file__).resolve().parents[1],timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_reconciliation_cannot_bypass_another_rejection_or_newer_pending(self):
        base, extra = reconciled_views()
        extra["records"][0].update(result_observations=deepcopy(base["records"][0]["result_observations"]),
            result_observation_rejections=[dict(captured_at="2030-04-01T11:00:00+09:00",source_sha256="f"*64,reason="RESULT_ROSTER_MISMATCH")])
        self.assertEqual(self.merge(base,[extra])["records"][0]["result"]["status"],"unsupported")
        later = add_result(view(),at="2030-04-01T11:30:00+09:00",status="pending")
        self.assertEqual(self.merge(base,[extra,later])["records"][0]["result"]["status"],"pending")

    def test_reconciliation_rejects_forged_source_roster_scope_clocks_or_large_offset(self):
        changes = [
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(source_sha256="1"*64),
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(formal_eligible=True),
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(roster_identity_verified=False),
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(all_originals_saved_before_both=False),
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(original_cutoffs=[b["records"][0]["cutoff_at"]]),
            lambda b,e:b["records"][0]["result"]["cutoff_reconciliation"].update(maximum_offset_seconds=61),
            lambda b,e:b["records"][0]["result_observations"][0].update(body_identity_verified=False),
            lambda b,e:b["records"][0]["result_observations"][0]["data"]["results"][0].update(racer_registration_id="4999"),
            lambda b,e:b["records"][0]["result"].update(payout_yen_per_100=9999),
            lambda b,e:b["records"][0]["prediction"].update(persisted_at="2030-04-01T10:00:00+09:00",server_saved_at="2030-04-01T10:00:00+09:00"),
            lambda b,e:b["records"][0].update(saved_schedule_cutoff_variants=["2030-04-01T10:00:00+09:00","2030-04-01T10:01:00+09:00"]),
        ]
        for i,change in enumerate(changes):
            base, extra = reconciled_views();change(base,extra)
            with self.subTest(change=i), self.assertRaises(ValueError):self.merge(base,[extra])

    def test_observation_only_cutoff_disagreements_cannot_erase_a_known_forecast_clock(self):
        extra = add_result(view(), at="2030-04-02T11:00:00+09:00",status="unsupported")
        r = extra["records"][0]
        r.update(prediction=None, comparison_predictions=[],cutoff_at=None,saved_cutoff_variants=[],
            saved_observation_cutoff_variants=["2030-04-01T10:00:00+09:00","2030-04-02T10:00:00+09:00"])
        r["result_observations"][0]["closed_at"]="2030-04-02T10:00:00+09:00"
        out=self.merge(view(),[extra]);row=out["records"][0]
        self.assertEqual(row["cutoff_at"],"2030-04-01T10:00:00+09:00")
        self.assertEqual(row["result"]["status"],"unsupported")
        proc=subprocess.run(["node","-e","require('./web/product-data.js').parse(require('fs').readFileSync(0,'utf8'))"],
            input=json.dumps(out),text=True,capture_output=True,cwd=Path(__file__).resolve().parents[1],timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_source_code_provenance_does_not_invent_or_replace_unknown_model_version(self):
        base=view(prediction(model_version=None,source_code_commit="1"*40,artifact_id=17))
        extra=view(prediction(model_version=None,source_code_commit="2"*40,artifact_id=18))
        out=self.merge(base,[extra])["records"][0]
        self.assertEqual(candidates(out),[base["records"][0]["prediction"],extra["records"][0]["prediction"]])
        self.assertTrue(all(p["model_version"] is None for p in candidates(out)))
        invalid=view(prediction(source_code_commit="bad"))
        with self.assertRaises(ValueError):self.merge(invalid)


if __name__ == "__main__":
    unittest.main()
