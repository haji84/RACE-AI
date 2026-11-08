"""Invented counts/privacy cases; no source HTTP or private key."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import importlib
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

try:
    audit = importlib.import_module("scripts.boat_remaining_completion_audit")
except ModuleNotFoundError:
    audit = None

NOW = datetime(2030, 4, 1, 6, tzinfo=timezone.utc)


def journal(index=None):
    index = index or {
        "stop_reason": "REQUEST_LIMIT",
        "actual_request_count": 8,
        "responses": [
            {"sequence": 1, "resource_type": "document", "status": 200, "url": "https://SECRET.invalid/private"},
            *[{"sequence": n, "resource_type": "xhr", "status": 200} for n in range(2, 9)],
        ],
        "cases": [{"state": "HOLD_UI_OR_SOURCE_UNAVAILABLE", "reason": "OFFICIAL_BROWSER_CAPTURE_STOPPED"}],
        "ledger": [
            {"event": "STATIC_CACHE_REPLAY", "url": "https://SECRET.invalid/private"} for _ in range(3)
        ] + [{"event": "NORMAL_SEMANTIC_UI_CLICK", "label": "SECRET-PRIVATE-LABEL"}],
    }
    raw = json.dumps(index).encode()
    return {
        "maximum_requests": 8,
        "attempts": [],
        "cases": [{"state": "HOLD_UI_OR_SOURCE_UNAVAILABLE", "sport": "autorace", "race_id": "SECRET"}],
        "browser_attempt": {"state": "COMPLETE", "actual_request_count": 8},
        "browser_quarantine": {
            "complete": True,
            "files": [{
                "kind": "ORIGINAL_INDEX", "byte_count": len(raw),
                "source_sha256": sha256(raw).hexdigest(),
                "raw_base64": base64.b64encode(raw).decode(),
            }],
        },
    }


def row(status="unsupported"):
    return {
        "race_id": "SECRET-PRIVATE-ID",
        "event_date_jst": "2030-04-01",
        "cutoff_at": "2030-04-01T03:00:00+00:00",
        "saved_cutoff_variants": ["2030-04-01T03:00:00+00:00"],
        "prediction": {"persisted_at": "2030-04-01T02:58:00+00:00", "ordered_top8": ["SECRET"]},
        "comparison_predictions": [],
        "participants": [{"name": "SECRET-NAME"} for _ in range(5)],
        "result": {"status": status, "observed_at": "2030-04-01T04:00:00+00:00"},
        "result_observation_rejections": [{
            "captured_at": "2030-04-01T04:00:00+00:00", "reason": "RESULT_CUTOFF_MISMATCH",
        }],
        "result_observations": [{
            "captured_at": "2030-04-01T04:00:00+00:00",
            "closed_at": "2030-04-01T03:02:00+00:00",
            "body_identity_verified": True, "data": {"results": [{} for _ in range(5)]},
        }],
    }


class RemainingCompletionAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(audit, "read-only actual completion audit is missing")

    def sp_fixture(self,*,invalid=False):
        from tests.test_boat_sp_settlement import document
        from tests.intraday_fixture import packet
        from tests.test_racer_daily import NOW as capture_at
        doc=document()
        if invalid:doc['maindata']['infolist3t'][0]['winno']='3-2-1'
        raw,receipt=packet(doc,captured=capture_at.isoformat());rid='20261107-01-01'
        pointer=dict(source_sha256=receipt['source_sha256'],captured_at=receipt['captured_at'])
        saved=dict(sport='boat',race_id=rid,cutoff_at='2026-11-07T10:00:00+09:00',saved_cutoff_variants=['2026-11-07T10:00:00+09:00'],
            participants=[dict(number=n,registration_no=str(4000+n)) for n in range(1,7)],
            prediction=dict(persisted_at='2026-11-07T00:00:00Z'),comparison_predictions=[],
            result=dict(status='unsupported',source_sha256=receipt['source_sha256'],observed_at=receipt['captured_at']))
        state=SimpleNamespace(control=dict(settlement_captures={rid:pointer}),capture=Mock(return_value=(raw,receipt)))
        return dict(records=[saved]),state,capture_at

    def test_retained_sp_hold_audit_reports_exact_safe_parser_reason_without_mutation(self):
        view,state,now=self.sp_fixture(invalid=True);before=deepcopy((view,state.control))
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(value['parser_reason_counts'],{'RESULT_WINNER_MISMATCH':1})
        self.assertEqual(value['authenticated_matching_captures'],1)
        self.assertEqual(value['source_requests'],0);self.assertEqual(value['results_admitted'],0)
        self.assertEqual((view,state.control),before)
        for field in ('race_id','source_url','source_sha256','participants','winno','dividend'):
            self.assertNotIn(field,json.dumps(value))

    def test_retained_sp_hold_audit_keeps_ambiguous_saved_cutoff_rejection(self):
        view,state,now=self.sp_fixture();saved=view['records'][0]
        saved['cutoff_at']=None;saved['saved_cutoff_variants'].append('2026-11-07T10:10:00+09:00')
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        # An explicit SP header still cannot invent each original's own clock.
        self.assertNotIn('cutoff_at',saved['prediction'])
        self.assertEqual(value['projection_reason_counts'],{'RESULT_CUTOFF_REFERENCE_CHRONOLOGY':1})
        self.assertEqual(value['results_admitted'],0)
        self.assertEqual(saved['result']['status'],'unsupported')

    def test_payout_shape_audit_emits_only_fixed_classes(self):
        raw=json.dumps({'maindata':{'infolist3t':[
            {'winno':'1-2-3'},{'winno':'特払'},{'winno':'1−2−3'},
            {'winno':'1=2=3'},{'winno':'<b>1-2-3</b>'},
            {'winno':'1-1-2'},{'winno':'SECRET_SOURCE_TEXT'},
        ]}}).encode()
        result=audit._payout_shapes(raw)
        self.assertEqual(result,{'ASCII_TRIFECTA':1,'SPECIAL_PAYOUT':1,'UNICODE_DASH':1,
                                 'EQUALS_SEPARATED':1,'HTML_MARKUP':1,'REPEATED_LANE':1,'OTHER':1})
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertNotIn('1-2-3',json.dumps(result))

    def test_payout_shape_audit_never_admits_missing_or_malformed_payloads(self):
        self.assertEqual(audit._payout_shapes(b'not json'),{'INVALID_DOCUMENT':1})
        self.assertEqual(audit._payout_shapes(b'{"maindata":{}}'),{'INVALID_PAYOUT_LIST':1})

    def test_per_original_cutoff_diagnostic_keeps_the_global_hold(self):
        view,state,now=self.sp_fixture();saved=view['records'][0]
        saved['cutoff_at']=None;saved['saved_cutoff_variants'].append('2026-11-07T10:10:00+09:00')
        before=deepcopy(view)
        result=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(result['per_original_cutoff_projection_reason_counts'],{'SUPPORTED':1,'SUPPORTED_REFERENCE':1})
        self.assertEqual(result['forecast_chronology_counts'],{'ALL_BEFORE_ALL_CUTOFFS':1})
        self.assertNotIn('cutoff_at',saved['prediction'])
        self.assertEqual(result['projection_reason_counts'],{'RESULT_CUTOFF_REFERENCE_CHRONOLOGY':1})
        self.assertEqual(result['results_admitted'],0);self.assertEqual(view,before)

    def test_retained_sp_chronology_checks_every_original_model_clock(self):
        view,state,now=self.sp_fixture()
        view['records'][0]['comparison_predictions']=[dict(persisted_at='2026-11-07T00:00:00Z',as_of='2026-11-07T01:01:00Z')]
        result=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(result['forecast_chronology_counts'],{'NOT_ALL_BEFORE_ALL_CUTOFFS':1})
        self.assertEqual(result['results_admitted'],0)

    def test_retained_sp_hold_audit_never_uses_a_different_or_missing_receipt(self):
        view,state,now=self.sp_fixture();view['records'][0]['result']['source_sha256']='0'*64
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(value['capture_reason_counts'],{'CURRENT_RESULT_RECEIPT_MISMATCH':1})
        state.control['settlement_captures']={}
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(value['capture_reason_counts'],{'RETAINED_CAPTURE_UNAVAILABLE':1})

    def test_retained_sp_source_failures_and_private_exceptions_never_escape(self):
        view,state,now=self.sp_fixture();state.capture.side_effect=ValueError('SECRET_RAW_SOURCE_AND_KEY')
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(value['capture_reason_counts'],{'CAPTURE_AUTHENTICATION_REJECTED':1})
        self.assertNotIn('SECRET',json.dumps(value))

    def test_retained_sp_audit_requires_exact_source_hash_before_parsing(self):
        view,state,now=self.sp_fixture();raw,receipt=state.capture.return_value
        state.capture.return_value=(raw+b'x',receipt)
        value=audit.audit_retained_sp_holds(view,state=state,now=now)
        self.assertEqual(value['capture_reason_counts'],{'CAPTURE_AUTHENTICATION_REJECTED':1})
        self.assertEqual(value['parser_reason_counts'],{})
        self.assertEqual(value['payout_shape_counts'],{})

    def test_native_counts_and_readonly_private_redaction(self):
        body = journal(); before = deepcopy(body)
        result = audit.audit_journal(body)
        self.assertEqual(result["source_requests"], 8)
        self.assertEqual(result["resource_type_counts"], {"document": 1, "xhr": 7})
        self.assertEqual(result["static_cache_replays"], 3)
        self.assertEqual(result["semantic_ui_clicks"], 1)
        self.assertEqual(result["stop_reason"], "REQUEST_LIMIT")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(body, before)

    def test_reserved_source_count_is_unknown(self):
        body = journal()
        body["browser_attempt"] = {"state": "RESERVED", "reserved_request_limit": 8}
        result = audit.audit_journal(body)
        self.assertIsNone(result["source_requests"])
        self.assertEqual(result["source_requests_upper_bound"], 8)
        self.assertTrue(result["request_count_unknown"])

    def test_unknown_native_values_do_not_escape(self):
        body = journal({
            "stop_reason": "SECRET", "responses": [{"resource_type": "SECRET", "status": "SECRET"}],
            "cases": [{"state": "SECRET", "reason": "SECRET"}],
            "ledger": [{"event": "SECRET", "label": "SECRET"}],
        })
        self.assertNotIn("SECRET", json.dumps(audit.audit_journal(body)))

    def test_retained_request_blockers_are_counted_without_private_values(self):
        body = journal({
            "stop_reason": "REQUEST_LIMIT",
            "responses": [{"method": "GET", "resource_type": "xhr", "status": 200}],
            "cases": [], "ledger": [
                {"sequence": 1, "method": "GET"},
                {"event": "BLOCKED_REQUEST", "reason": "OFFICIAL_BROWSER_NORMAL_READ_IDENTITY", "method": "POST"},
                {"event": "BLOCKED_REQUEST", "reason": "SECRET", "method": "SECRET"},
                {"event": "NORMAL_SEMANTIC_UI_CLICK", "label": "4月1日"},
            ],
        })
        value = audit.audit_journal(body)
        self.assertEqual(value["wire_method_counts"], {"GET": 1})
        self.assertEqual(value["blocked_reason_counts"],
                         {"OFFICIAL_BROWSER_NORMAL_READ_IDENTITY": 1, "OTHER": 1})
        self.assertEqual(value["blocked_method_counts"], {"POST": 1, "OTHER": 1})
        self.assertNotIn("SECRET", json.dumps(value))

    def test_dispatched_denied_request_is_counted_without_a_retained_response(self):
        body = journal({"stop_reason": "HTTP_ACCESS_DENIED", "responses": [],
                        "ledger": [{"sequence": 1, "method": "POST", "status": 403}], "cases": []})
        body["browser_attempt"]["actual_request_count"] = 1
        result = audit.audit_journal(body)
        self.assertEqual(result["source_requests"], 1)
        self.assertEqual(result["wire_method_counts"], {"POST": 1})
        self.assertEqual(result["blocked_method_counts"], {})

    def test_source_validation_failure_and_required_roles_are_fixed_counts(self):
        body = journal({"stop_reason": "FINISHED", "ledger": [], "responses": [
            {"sequence": 1, "status": 404}, {"sequence": 2, "status": 200},
            {"sequence": 3, "status": 200}], "cases": [{"state": "CAPTURED", "responses": [
                {"role": "result", "sequence": 2}, {"role": "identity", "sequence": 3}]}]})
        body["browser_failure"] = dict(stage="SOURCE_VALIDATION", error_code="ALL_MODEL_OFFICIAL_COLLECT_BROWSER_SOURCE_BYTES")
        result = audit.audit_journal(body)
        self.assertEqual(result["failure_error_code"], "ALL_MODEL_OFFICIAL_COLLECT_BROWSER_SOURCE_BYTES")
        self.assertEqual(result["required_role_status_counts"], {"result": {"200": 1}, "identity": {"200": 1}})
        self.assertEqual(result["case_state_counts"], {"CAPTURED": 1})
        self.assertEqual(result["case_reason_counts"], {})
        body["browser_failure"]["error_code"] = "SECRET"
        self.assertEqual(audit.audit_journal(body)["failure_error_code"], "OTHER")
        self.assertNotIn("SECRET", json.dumps(audit.audit_journal(body)))

    def test_same_capture_conflict_attributes_only_known_fields_and_preserves_inputs(self):
        left = row(); left["result_observations"][0]["source_sha256"] = "a"*64
        left["result_observations"][0]["data"]["results"] = [{"lane": 1, "finish": 1}]
        right = deepcopy(left)
        right["result_observations"][0]["data"]["results"][0]["race_time"] = "SECRET"
        base = {"records": [left]}; addition = {"records": [right]}
        before = deepcopy((base, addition))
        value = audit.audit_observation_conflicts(base, addition)
        self.assertEqual(value["conflicting_capture_groups"], 1)
        self.assertEqual(value["same_source_bytes_conflicts"], 1)
        self.assertEqual(value["differing_data_fields"], {"results": 1})
        self.assertEqual(value["differing_finish_fields"], {"race_time": 1})
        self.assertNotIn("SECRET", json.dumps(value))
        self.assertEqual((base, addition), before)

    def test_identical_replayed_observations_are_not_conflicts(self):
        value = {"records": [row()]}
        self.assertEqual(audit.audit_observation_conflicts(value, deepcopy(value))["conflicting_capture_groups"], 0)

    def test_unknown_conflicting_field_name_is_redacted(self):
        left = row(); right = deepcopy(left)
        right["result_observations"][0]["SECRET"] = "SECRET"
        value = audit.audit_observation_conflicts({"records": [left]}, {"records": [right]})
        self.assertEqual(value["differing_fields"], {"OTHER": 1})
        self.assertNotIn("SECRET", json.dumps(value))

    def continuity_fixture(self):
        from race_ai.boat_private_original_archive import seal_original_zip
        state = dict(schema="RACE_AI_RECOVERED_FIRST_RECEIPTS_V1", complete=True,
                     day_jst="2030-04-01", rows=[], observations=[])
        state["state_sha256"] = sha256(json.dumps(state,sort_keys=True,ensure_ascii=False,
                                                  separators=(",", ":")).encode()).hexdigest()
        def zipped(name, body):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
                target.writestr(name, body)
            return buffer.getvalue()
        key = bytes(range(32))  # Public synthetic fixture only.
        head = "a"*40
        cipher = seal_original_zip(zipped("continuity.json", json.dumps(state).encode()),
                                   run_id=42, head_sha=head, kind="CONTINUITY", key=key)
        raw = zipped("private-original.enc", cipher)
        pin = dict(id=7, digest="sha256:"+sha256(raw).hexdigest(), run_id=42, head_sha=head)
        metadata = dict(id=7, name="race-cycle-continuity-42", digest=pin["digest"],
                        size_in_bytes=len(raw), expired=False, created_at="2030-04-01T01:00:00Z",
                        expires_at="2030-04-08T01:00:00Z", workflow_run=dict(id=42,
                        head_sha=head, repository_id=1416489937, head_repository_id=1416489937))
        reader = SimpleNamespace(metadata=Mock(return_value=metadata),
                                 gh=Mock(return_value=raw))
        return pin, key, state, metadata, reader

    def test_continuity_audit_opens_real_encrypted_archive_before_projection(self):
        pin, key, state, _, future = self.continuity_fixture()
        reader = SimpleNamespace(future=future, stamp=audit._clock)
        with patch("race_ai.boat_saved_view_intake.project_native_state", return_value={"records": []}) as project:
            value = audit._continuity_projection(pin, key=key, now=NOW, day="2030-04-01", reader=reader)
        self.assertEqual(value, {"records": []})
        project.assert_called_once_with(state)
        future.gh.assert_called_once_with("actions/artifacts/7/zip")

    def test_continuity_audit_rejects_metadata_before_archive_fetch(self):
        for field, value in (("size_in_bytes", True), ("size_in_bytes", 161*1024*1024),
                             ("expired", True), ("digest", "sha256:"+"0"*64)):
            with self.subTest(field=field, value=value):
                pin, key, _, metadata, future = self.continuity_fixture()
                metadata[field] = value
                with self.assertRaisesRegex(ValueError, "AUDIT_CONTINUITY_METADATA"):
                    audit._continuity_projection(pin, key=key, now=NOW, day="2030-04-01",
                                                 reader=SimpleNamespace(future=future, stamp=audit._clock))
                future.gh.assert_not_called()

    def test_corrupt_original_index_fails(self):
        body = journal()
        body["browser_quarantine"]["files"][0]["source_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            audit.audit_journal(body)

    def test_redacted_diagnostic_cannot_claim_original_or_zero_ui_facts(self):
        body = journal()
        body.pop("browser_quarantine")
        body["browser_index"] = {
            "diagnostic_projection_only": True, "stop_reason": "REQUEST_LIMIT",
            "responses": [{"sequence": 1, "status": 200}],
            "cases": [{"state": "HOLD_UI_OR_SOURCE_UNAVAILABLE", "responses": []}],
        }
        result = audit.audit_journal(body)
        self.assertFalse(result["original_index_available"])
        for field in ("static_cache_replays", "semantic_ui_clicks",
                      "saved_rendered_dom_count", "case_reason_counts", "resource_type_counts"):
            self.assertIsNone(result[field], field)
        self.assertEqual(result["source_requests"], 8)

    def test_dom_reference_is_not_retained_dom_evidence(self):
        body = journal({
            "stop_reason": "FINISHED", "responses": [], "ledger": [],
            "cases": [{"rendered_dom": {"file": "case-01/missing.html"}}],
        })
        self.assertEqual(audit.audit_journal(body)["saved_rendered_dom_count"], 0)

    def test_retained_dom_bytes_are_verified_before_counting(self):
        body = journal()
        raw = b"<html>SECRET-DOM</html>"
        entry = {
            "kind": "RENDERED_DOM", "file": "case-01/rendered-dom.html",
            "byte_count": len(raw), "source_sha256": sha256(raw).hexdigest(),
            "raw_base64": base64.b64encode(raw).decode(),
        }
        body["browser_quarantine"]["files"].append(entry)
        self.assertEqual(audit.audit_journal(body)["saved_rendered_dom_count"], 1)
        self.assertNotIn("SECRET", json.dumps(audit.audit_journal(body)))
        entry["source_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            audit.audit_journal(body)

    def test_actual_collector_failure_stages_are_recognized(self):
        for stage in ("PROCESS", "INDEX_VALIDATION"):
            body = journal()
            body["browser_failure"] = {"stage": stage}
            self.assertEqual(audit.audit_journal(body)["failure_stage"], stage)

    def test_boat_current_hold_offsets_and_roster_counts_without_mutation(self):
        view = {"records": [row()]}; before = deepcopy(view)
        result = audit.audit_saved_view(view, now=NOW)
        self.assertEqual(result["current_rejection_reason_counts"], {"RESULT_CUTOFF_MISMATCH": 1})
        self.assertEqual(result["cutoff_offset_seconds_counts"], {"120": 1})
        self.assertEqual(result["saved_roster_sizes"], {"5": 1})
        self.assertEqual(result["all_saved_before_both_clocks"], 1)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(view, before)

    def test_final_race_ignores_historical_rejection(self):
        result = audit.audit_saved_view({"records": [row("final")]}, now=NOW)
        self.assertEqual(result["current_rejection_reason_counts"], {})
        self.assertEqual(result["held_races"], 0)
        self.assertEqual(result["result_states"]["final"], 1)

    def test_ambiguous_original_cutoffs_are_counted_without_choosing_one(self):
        past = row(); past["cutoff_at"] = None
        past["saved_cutoff_variants"] = ["2030-04-01T03:00:00Z", "2030-04-01T03:01:00Z"]
        future = deepcopy(past)
        future["saved_cutoff_variants"] = ["2030-04-01T07:00:00Z", "2030-04-01T07:01:00Z"]
        mixed = deepcopy(past)
        mixed["saved_cutoff_variants"] = ["2030-04-01T03:00:00Z", "2030-04-01T07:01:00Z"]
        view = {"records": [past, future, mixed]}; before = deepcopy(view)
        result = audit.audit_saved_view(view, now=NOW)
        self.assertEqual(result["overdue_unmatched_races"], 1)
        self.assertEqual(result["future_unmatched_races"], 1)
        self.assertEqual(result["unknown_or_mixed_cutoff_unmatched_races"], 1)
        self.assertEqual(view, before)

    def test_missing_and_future_races_remain_separate_from_misses(self):
        past = row(); past["result"] = None
        future = row(); future["result"] = None; future["cutoff_at"] = "2030-04-01T07:00:00+00:00"
        result = audit.audit_saved_view({"records": [past, future]}, now=NOW)
        self.assertEqual(result["overdue_unmatched_races"], 1)
        self.assertEqual(result["future_unmatched_races"], 1)
        self.assertNotIn("misses", result)

    def test_unknown_boat_reason_is_redacted(self):
        value = row()
        value["result_observation_rejections"][0]["reason"] = "SECRET-PRIVATE-URL"
        result = audit.audit_saved_view({"records": [value]}, now=NOW)
        self.assertEqual(result["current_rejection_reason_counts"], {"OTHER": 1})
        self.assertNotIn("SECRET", json.dumps(result))

    def test_host_context_is_rejected_before_private_reads(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(audit, "_load_authenticated") as load:
            with patch("builtins.print") as emitted:
                self.assertEqual(audit.main(["--input", "audit/state/example.json"]), 2)
        load.assert_not_called()
        output = json.loads(emitted.call_args.args[0])
        self.assertEqual(output["status"], "REMAINING_COMPLETION_AUDIT_HOLD")
        self.assertEqual(output["reason"], "OWNER_ACTIONS_CONTEXT_REQUIRED")

    def test_authenticated_actions_context_without_owner_key_stops_before_io(self):
        from pathlib import Path
        import race_ai
        reference = str(Path(__file__).resolve().parents[1]/"pr64-reference"/"race_ai")
        if reference not in race_ai.__path__:
            race_ai.__path__.append(reference)
        from scripts import all_existing_model_official_result_collect as C
        from scripts import boat_prospective_audit as A
        context = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "haji84/RACE-AI",
            "GITHUB_REPOSITORY_ID": "1416489937",
        }
        with patch.dict(os.environ, context, clear=True), \
                patch("race_ai.boat_pdca_state.state_key", side_effect=ValueError("SECRET-MISSING-KEY")) as key, \
                patch.object(C, "_repository_file") as config, \
                patch.object(C, "_journal_artifact") as artifact, \
                patch.object(A, "_owner_view") as view, patch("builtins.print") as emitted:
            self.assertEqual(audit.main(["--input", "audit/state/remaining-completion-audit-input.json"]), 2)
        key.assert_called_once_with("production")
        config.assert_not_called(); artifact.assert_not_called(); view.assert_not_called()
        self.assertNotIn("SECRET", emitted.call_args.args[0])

    def test_authenticated_cli_emits_only_counts(self):
        context = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "haji84/RACE-AI",
            "GITHUB_REPOSITORY_ID": "1416489937",
        }
        sp_holds=dict(status='RETAINED_SP_HOLD_AUDIT_UNAVAILABLE',reason='AUTHENTICATED_STATE_READ_REJECTED',source_requests=0,results_admitted=0)
        fixture = ("2030-04-01", 17, {"records": [row()]}, journal(), {"id": 23}, None, sp_holds)
        with patch.dict(os.environ, context, clear=True), \
                patch.object(audit, "_load_authenticated", return_value=fixture), patch("builtins.print") as emitted:
            self.assertEqual(audit.main(["--input", "audit/state/remaining-completion-audit-input.json"]), 0)
        raw = emitted.call_args.args[0]
        result = json.loads(raw)
        self.assertEqual(result["status"], "REMAINING_COMPLETION_AUDIT_VERIFIED")
        self.assertEqual(result["source_requests"], 0)
        self.assertEqual(result["native"]["source_requests"], 8)
        self.assertEqual(result["results_admitted"], 0)
        self.assertEqual(result['retained_sp_holds'],sp_holds)
        self.assertNotIn("SECRET", raw)


if __name__ == "__main__":
    unittest.main()
