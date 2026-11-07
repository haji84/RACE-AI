"""Invented counts/privacy cases; no source HTTP or private key."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import importlib
import json
import os
import unittest
from unittest.mock import patch

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
        fixture = ("2030-04-01", 17, {"records": [row()]}, journal(), {"id": 23})
        with patch.dict(os.environ, context, clear=True), \
                patch.object(audit, "_load_authenticated", return_value=fixture), patch("builtins.print") as emitted:
            self.assertEqual(audit.main(["--input", "audit/state/remaining-completion-audit-input.json"]), 0)
        raw = emitted.call_args.args[0]
        result = json.loads(raw)
        self.assertEqual(result["status"], "REMAINING_COMPLETION_AUDIT_VERIFIED")
        self.assertEqual(result["source_requests"], 0)
        self.assertEqual(result["native"]["source_requests"], 8)
        self.assertEqual(result["results_admitted"], 0)
        self.assertNotIn("SECRET", raw)


if __name__ == "__main__":
    unittest.main()
