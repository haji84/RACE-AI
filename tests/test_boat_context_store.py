"""Supplemental observations remain separate from saved forecast originals."""
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.local_forecast_service import LocalForecastService

try:
    store = importlib.import_module("race_ai.boat_context_store")
except ModuleNotFoundError:
    store = None


DAY = "2030-04-01"
RACE = "20300401-01-01"
CUTOFF = "2030-04-01T12:00:00+09:00"


def context(captured_at="2030-04-01T11:45:00+09:00"):
    roster = [dict(lane=n, registration_number=str(4200+n)) for n in range(1, 7)]
    return dict(schema="RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1", race_id=RACE,
        cutoff_at=CUTOFF, roster=roster, forecast_inputs_used=False,
        beforeinfo=dict(schema="RACE_AI_BOAT_OBSERVATION_CONTEXT_V1", kind="beforeinfo", race_id=RACE,
            event_date_jst=DAY, venue_code="01", race_no=1, source_cutoff_at=CUTOFF, status="PARSED", forecast_ready=False,
            body_identity_verified=True, roster_binding_status="VERIFIED",
            source=dict(source_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=01&hd=20300401",
                sha256="a"*64, captured_at=captured_at, published_at=None,
                published_time_raw="11:40現在", freshness_status="UNKNOWN_SOURCE_TIME_HAS_NO_DATE"),
            participants=[dict(row, body_weight_kg=52.0) for row in roster], weather={}),
        pitreport=None, entry_history=None)


def view():
    return dict(event_date_jst=DAY, records=[dict(race_id=RACE, sport="boat", cutoff_at=CUTOFF,
        participants=[dict(number=n, registration_no=str(4200+n)) for n in range(1, 7)],
        prediction=dict(stage="P0", model_id="saved-model", ordered_top8=[[1, 2, 3]],
            prediction_sha256="b"*64, output_sha256="c"*64,
            source_captured_at="2030-04-01T11:30:00+09:00",
            generated_at="2030-04-01T11:31:00+09:00", persisted_at="2030-04-01T11:32:00+09:00"),
        comparison_predictions=[], source_sha256="d"*64, result={"refund_boats": []},
        result_observations=[dict(captured_at="2030-04-01T12:10:00+09:00")],
        saved_cutoff_variants=[CUTOFF], saved_schedule_cutoff_variants=[CUTOFF])])


def profile_context(test):
    from race_ai.boat_entry_observations import conditional_profile_before
    from tests.test_boat_entry_observations import AS_OF, history
    value = context()
    value["roster"] = [dict(lane=n, registration_number=str(4000+n)) for n in range(1, 7)]
    value["beforeinfo"]["participants"] = deepcopy(value["roster"])
    value["entry_history"] = {"profiles": [conditional_profile_before(history(test), as_of=AS_OF, racer_id="4001")]}
    return value


def with_pit(value, captured_at="2030-04-01T11:40:00+09:00"):
    value = deepcopy(value)
    value["pitreport"] = deepcopy(value["beforeinfo"])
    pit = value["pitreport"]
    pit["kind"] = "pitreport"
    pit["source"]["source_url"] = pit["source"]["source_url"].replace("beforeinfo?", "pitreport?")
    pit["source"]["captured_at"] = captured_at
    pit["participants"][0]["comment"] = "retained official comment"
    return value


class BoatContextStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(store, "save_context", None)),
                        "owner-private supplemental context store is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_private_content_addressed_versions_preserve_prior_capture_and_latest_actual_time(self):
        original = context()
        first = store.save_context(self.root, original)
        self.assertEqual(original, context(), "saving must not mutate the supplied parser result")
        saved = self.root / "boat-context" / (first + ".json")
        self.assertEqual(sha256(saved.read_bytes()).hexdigest(), first)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
        before = store.read_contexts(self.root, day=DAY)
        later = context("2030-04-01T11:50:00+09:00")
        later["beforeinfo"]["participants"][0]["body_weight_kg"] = 52.5
        second = store.save_context(self.root, later)
        after = store.read_contexts(self.root, day=DAY)
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(after["contexts"][RACE]["beforeinfo"]["participants"][0]["body_weight_kg"], 52.5)
        # An older capture arriving last cannot replace a newer observation.
        store.save_context(self.root, context("2030-04-01T11:40:00+09:00"))
        self.assertEqual(store.read_contexts(self.root, day=DAY)["contexts"][RACE], after["contexts"][RACE])
        self.assertEqual(store.save_context(self.root, later), second)
        self.assertEqual(len(list(saved.parent.glob("*.json"))), 3)
        self.assertTrue(saved.is_file())

    def test_read_only_empty_store_has_stable_revision_and_does_not_create_directories(self):
        one = store.read_contexts(self.root, day=DAY)
        two = store.read_contexts(self.root, day=DAY)
        self.assertEqual(one, two)
        self.assertEqual(one["contexts"], {})
        self.assertFalse((self.root / "boat-context").exists())

    def test_optional_comment_collection_status_survives_separate_capture(self):
        value = context()
        value["pitreport_collection_status"] = "DEFERRED_TO_PRESERVE_FORECAST_TIME"
        store.save_context(self.root, value)
        self.assertEqual(store.read_contexts(self.root, day=DAY)["contexts"][RACE]["pitreport_collection_status"],
                         "DEFERRED_TO_PRESERVE_FORECAST_TIME")

    def test_optional_comment_worker_handoff_keeps_saved_beforeinfo_readable(self):
        from scripts import boat_nationwide_ab_pilot as pilot
        value = context()
        original_beforeinfo = deepcopy(value["beforeinfo"])
        with patch.object(pilot, "_clock", return_value=datetime.fromisoformat("2030-04-01T11:45:00+09:00")), \
             patch.object(pilot, "get", side_effect=ValueError("WORKER_HANDOFF")):
            pause = pilot.collect_pitreport(value, date(2030, 4, 1))
        self.assertEqual(pause, {"state": "WORKER_HANDOFF", "reason": "WORKER_HANDOFF", "retry_at": None})
        store.save_context(self.root, value)
        saved = store.read_contexts(self.root, day=DAY)["contexts"][RACE]
        self.assertEqual(saved["pitreport_collection_status"], "WORKER_HANDOFF")
        self.assertIsNone(saved["pitreport"])
        self.assertEqual(saved["beforeinfo"]["source"], original_beforeinfo["source"])
        self.assertEqual(saved["beforeinfo"]["participants"], original_beforeinfo["participants"])
        self.assertEqual(saved["beforeinfo"]["status"], "PARSED")
        self.assertFalse(saved["forecast_inputs_used"])

    def test_late_capture_is_retained_but_cannot_claim_pre_cutoff_eligibility(self):
        late = context(CUTOFF)
        late["beforeinfo"]["cutoff_eligibility"] = dict(captured_before_cutoff=True,
            pre_cutoff_eligible=True, reason="PRE_CUTOFF_CAPTURE")
        store.save_context(self.root, late)
        readback = store.read_contexts(self.root, day=DAY)["contexts"][RACE]
        self.assertEqual(readback["beforeinfo"]["source"]["captured_at"], CUTOFF)
        self.assertFalse(readback["beforeinfo"]["cutoff_eligibility"]["captured_before_cutoff"])
        self.assertFalse(readback["beforeinfo"]["cutoff_eligibility"]["pre_cutoff_eligible"])
        self.assertFalse(readback["forecast_inputs_used"])

    def test_printed_official_deadline_cannot_be_extended_by_later_wrapper_cutoff(self):
        value = context()
        value["beforeinfo"]["source_cutoff_at"] = "2030-04-01T11:40:00+09:00"
        value["beforeinfo"].update(captured_before_cutoff=True, pre_cutoff_eligible=True,
                                   reason="CAPTURED_BEFORE_CUTOFF")
        store.save_context(self.root, value)
        parser = store.read_contexts(self.root, day=DAY)["contexts"][RACE]["beforeinfo"]
        self.assertFalse(parser["captured_before_cutoff"])
        self.assertFalse(parser["pre_cutoff_eligible"])
        self.assertEqual(parser["reason"], "CAPTURED_AT_OR_AFTER_CUTOFF")

    def test_real_parser_results_and_real_conditional_profile_remain_readable(self):
        from race_ai.boat_observation_context import parse_beforeinfo
        from tests.test_boat_observation_context import ROSTER, RACE_ID, CAPTURED, before_table, starts, frame, url
        parsed = parse_beforeinfo(frame(before_table() + starts()), source_url=url(),
            captured_at=CAPTURED, expected_race_id=RACE_ID, roster=ROSTER)
        value = context()
        value.update(race_id=RACE_ID, cutoff_at="2030-04-01T20:30:00+09:00", roster=ROSTER, beforeinfo=parsed)
        store.save_context(self.root, value)
        parser = store.read_contexts(self.root, day=DAY)["contexts"][RACE_ID]["beforeinfo"]
        self.assertTrue(parser["cutoff_eligibility"]["pre_cutoff_eligible"])
        self.assertEqual(parser["source"]["sha256"], parsed["source"]["sha256"])
        from race_ai.boat_entry_observations import conditional_profile_before
        from tests.test_boat_entry_observations import AS_OF, history
        profile = conditional_profile_before(history(self), as_of=AS_OF, racer_id="4001")
        value.update(race_id="20261105-17-01", cutoff_at=AS_OF, beforeinfo=None,
            entry_history={"profiles": [profile]})
        store.save_context(self.root, value)
        stored = store.read_contexts(self.root, day="2026-11-05")["contexts"]["20261105-17-01"]
        self.assertEqual(stored["entry_history"]["profiles"], [profile])
        value["cutoff_at"] = "2026-11-05T17:00:00+09:00"
        late_root = self.root / "late"; late_root.mkdir(mode=0o700)
        store.save_context(late_root, value)
        late = store.read_contexts(late_root, day="2026-11-05")["contexts"]["20261105-17-01"]
        self.assertFalse(late["entry_history"]["cutoff_eligibility"]["pre_cutoff_eligible"])
        self.assertFalse(late["entry_history"]["cutoff_eligibility"]["captured_before_cutoff"])

    def test_invalid_source_roster_profile_or_forecast_usage_is_rejected(self):
        cases = []
        value = context(); value["forecast_inputs_used"] = True; cases.append(value)
        value = context(); value["beforeinfo"]["source"]["sha256"] = "not-a-hash"; cases.append(value)
        value = context(); value["beforeinfo"]["source"]["source_url"] = "https://evil.test/beforeinfo"; cases.append(value)
        value = context(); value["beforeinfo"]["source"]["source_url"] += "&hd=20300402"; cases.append(value)
        value = context(); value["beforeinfo"]["venue_code"] = "02"; cases.append(value)
        value = context(); value["beforeinfo"]["race_no"] = 2; cases.append(value)
        value = context(); value["beforeinfo"]["forecast_inputs_used"] = True; cases.append(value)
        value = context(); value["race_id"] = "20300402-01-01"; cases.append(value)
        value = context(); value["roster"][1]["lane"] = 1; cases.append(value)
        value = context(); value["beforeinfo"]["participants"][0]["registration_number"] = "9999"; cases.append(value)
        value = context(); value["entry_history"] = {"profiles": [{"racer_id": "9999", "as_of": DAY}]}; cases.append(value)
        for invalid in cases:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                store.save_context(self.root, invalid)
        self.assertFalse((self.root / "boat-context").exists())

    def test_profile_rejects_fabricated_samples_and_inconsistent_rates(self):
        original = profile_context(self)
        cases = []
        def changed(label, change):
            value = deepcopy(original)
            change(value["entry_history"]["profiles"][0])
            cases.append((label, value))
        changed("positive samples without provenance", lambda p: p.update(source_proofs=[]))
        changed("sample size does not match races", lambda p: p.update(sample_races=4))
        changed("boolean sample size", lambda p: p.update(sample_races=True))
        changed("duplicate races", lambda p: p["race_ids"].__setitem__(1, p["race_ids"][0]))
        changed("invalid race date", lambda p: p["race_ids"].__setitem__(0, "20260230-17-01"))
        changed("race has no dated source", lambda p: p["race_ids"].__setitem__(0, "20261103-17-01"))
        changed("duplicate source day", lambda p: p["source_proofs"].append(deepcopy(p["source_proofs"][0])))
        changed("missing K provenance", lambda p: p["source_proofs"][0].pop("K"))
        changed("independent source verification invented", lambda p: p.update(source_authenticity_independently_verified=True))
        changed("unverified result sample", lambda p: p.update(derived_from_verified_results_only=False))
        changed("missing conditional bucket", lambda p: p["conditional_buckets"].pop("inward"))
        changed("missing actual course", lambda p: p["actual_course_when_inward_mover_present"].pop("6"))
        changed("percentage exceeds one", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(top3_rate=5.0))
        changed("percentage disagrees with counts", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(top3_rate=0.75))
        changed("negative count", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(wins=-1))
        changed("boolean count", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(wins=False))
        changed("fractional count", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(starts=2.5))
        changed("denominator disagrees with starts", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(denominator=3))
        changed("wins exceed top2", lambda p: p["conditional_buckets"]["any_inward_mover_present"].update(wins=2, win_rate=1.0))
        changed("conditional sample exceeds all races", lambda p: p["conditional_buckets"]["inward"].update(
            starts=4, denominator=4, wins=0, top2=0, top3=0, win_rate=0.0, top2_rate=0.0, top3_rate=0.0))
        changed("zero samples claim a rate", lambda p: p["conditional_buckets"]["inward"].update(top3_rate=0.0))
        changed("course partition loses a race", lambda p: p["actual_course_when_inward_mover_present"]["2"].update(
            starts=0, denominator=0, wins=0, top2=0, top3=0, win_rate=None, top2_rate=None, top3_rate=None))
        changed("outer entry is not an inward subset", lambda p: p["conditional_buckets"]["outer_to_inner3"].update(
            starts=1, denominator=1, wins=0, top2=0, top3=0, win_rate=0.0, top2_rate=0.0, top3_rate=0.0))
        for label, invalid in cases:
            with self.subTest(case=label), self.assertRaises(ValueError):
                store.save_context(self.root, invalid)
        self.assertFalse((self.root / "boat-context").exists())

    def test_zero_sample_profile_has_null_rates_and_no_invented_provenance(self):
        from race_ai.boat_entry_observations import conditional_profile_before
        value = context()
        profile = conditional_profile_before([], as_of=CUTOFF, racer_id="4201")
        value["entry_history"] = {"profiles": [profile]}
        store.save_context(self.root, value)
        readback = store.read_contexts(self.root, day=DAY)["contexts"][RACE]["entry_history"]["profiles"][0]
        self.assertEqual(readback["sample_races"], 0)
        self.assertEqual(readback["source_proofs"], [])
        self.assertFalse(readback["source_authenticity_independently_verified"])
        for bucket in readback["conditional_buckets"].values():
            self.assertEqual(bucket["denominator"], 0)
            self.assertIsNone(bucket["top3_rate"])

    def test_hash_valid_but_impossible_history_file_is_rejected_on_read(self):
        ident = store.save_context(self.root, profile_context(self))
        file = self.root / "boat-context" / (ident + ".json")
        value = json.loads(file.read_bytes())
        value["entry_history"]["profiles"][0]["conditional_buckets"]["any_inward_mover_present"]["top3_rate"] = 8.0
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        file.unlink()
        forged = file.with_name(sha256(raw).hexdigest() + ".json")
        forged.write_bytes(raw); forged.chmod(0o600)
        with self.assertRaises(ValueError):
            store.read_contexts(self.root, day=DAY)

    def test_hash_bound_read_rejects_modified_bytes_and_renamed_versions(self):
        ident = store.save_context(self.root, context())
        saved = self.root / "boat-context" / (ident + ".json")
        saved.write_bytes(saved.read_bytes().replace(b"52.0", b"53.0"))
        with self.assertRaises(ValueError):
            store.read_contexts(self.root, day=DAY)
        saved.unlink()
        ident = store.save_context(self.root, context())
        saved = self.root / "boat-context" / (ident + ".json")
        saved.rename(saved.with_name("f"*64 + ".json"))
        with self.assertRaises(ValueError):
            store.read_contexts(self.root, day=DAY)

    def test_permissions_links_and_git_ancestors_fail_closed(self):
        ident = store.save_context(self.root, context())
        folder = self.root / "boat-context"
        saved = folder / (ident + ".json")
        saved.chmod(0o644)
        with self.assertRaises(ValueError): store.read_contexts(self.root, day=DAY)
        saved.chmod(0o600)
        folder.chmod(0o755)
        with self.assertRaises(ValueError): store.read_contexts(self.root, day=DAY)
        folder.chmod(0o700)
        other = self.root / "linked.json"
        os.link(saved, other)
        with self.assertRaises(ValueError): store.read_contexts(self.root, day=DAY)
        other.unlink()
        saved.unlink(); saved.symlink_to(self.root / "missing")
        with self.assertRaises((OSError, ValueError)): store.read_contexts(self.root, day=DAY)
        saved.unlink(); folder.rmdir()
        actual = self.root / "actual"; actual.mkdir(mode=0o700)
        folder.symlink_to(actual, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)): store.save_context(self.root, context())
        with self.assertRaises((OSError, ValueError)): store.read_contexts(self.root, day=DAY)
        folder.unlink()
        (self.root / ".git").mkdir(mode=0o700)
        with self.assertRaises(ValueError): store.save_context(self.root, context())

    def test_attach_adds_only_optional_context_when_roster_and_cutoff_are_exact(self):
        store.save_context(self.root, context())
        snapshot = store.read_contexts(self.root, day=DAY)
        original = view()
        attached = deepcopy(original)
        revision = store.attach_contexts(attached, snapshot)
        self.assertTrue(revision)
        added = attached["records"][0].pop("boat_observation_context")
        self.assertFalse(added["forecast_inputs_used"])
        self.assertEqual(attached, original)
        for mutation in ("registration", "cutoff", "missing", "conflicting_cutoffs"):
            mismatch = view()
            row = mismatch["records"][0]
            if mutation == "registration": row["participants"][0]["registration_no"] = "9999"
            if mutation == "cutoff": row["cutoff_at"] = "2030-04-01T12:01:00+09:00"
            if mutation == "missing": row["participants"] = None
            if mutation == "conflicting_cutoffs": row["saved_cutoff_variants"].append("2030-04-01T12:01:00+09:00")
            with self.subTest(mutation=mutation):
                self.assertIsNone(store.attach_contexts(mismatch, snapshot))
                self.assertNotIn("boat_observation_context", row)

    def test_merge_selects_latest_capture_across_private_roots_independent_of_order(self):
        native = self.root / "native"; native.mkdir(mode=0o700)
        workflow = self.root / "workflow"; workflow.mkdir(mode=0o700)
        store.save_context(native, context())
        store.save_context(workflow, context("2030-04-01T11:50:00+09:00"))
        old = store.read_contexts(native, day=DAY)
        new = store.read_contexts(workflow, day=DAY)
        combined = store.merge_contexts(old, new)
        self.assertEqual(combined, store.merge_contexts(new, old))
        self.assertEqual(combined["contexts"][RACE], new["contexts"][RACE])

    def test_new_beforeinfo_version_keeps_independently_captured_pit_and_history(self):
        rich = with_pit(profile_context(self))
        store.save_context(self.root, rich)
        before = store.read_contexts(self.root, day=DAY)
        update = deepcopy(rich)
        update["beforeinfo"]["source"]["captured_at"] = "2030-04-01T11:50:00+09:00"
        update.update(pitreport=None, entry_history=None)
        store.save_context(self.root, update)
        after = store.read_contexts(self.root, day=DAY)
        selected = after["contexts"][RACE]
        self.assertEqual(selected["beforeinfo"]["source"]["captured_at"], "2030-04-01T11:50:00+09:00")
        self.assertIsNotNone(selected["pitreport"], "a beforeinfo refresh discarded a separate pit capture")
        self.assertEqual(selected["pitreport"]["source"]["captured_at"], "2030-04-01T11:40:00+09:00")
        self.assertEqual(selected["pitreport"]["participants"][0]["comment"], "retained official comment")
        self.assertEqual(selected["entry_history"]["profiles"], rich["entry_history"]["profiles"])
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(len(list((self.root / "boat-context").glob("*.json"))), 2)

    def test_merge_uses_each_component_clock_and_keeps_profiles_across_roots(self):
        native = self.root / "native"; native.mkdir(mode=0o700)
        workflow = self.root / "workflow"; workflow.mkdir(mode=0o700)
        rich = with_pit(profile_context(self), "2030-04-01T11:55:00+09:00")
        from race_ai.boat_entry_observations import conditional_profile_before
        from tests.test_boat_entry_observations import AS_OF, history
        rich["entry_history"]["profiles"].append(conditional_profile_before(history(self), as_of=AS_OF, racer_id="4002"))
        store.save_context(native, rich)
        update = deepcopy(rich)
        update["beforeinfo"]["source"]["captured_at"] = "2030-04-01T11:50:00+09:00"
        update["pitreport"] = None
        update["entry_history"]["profiles"] = [conditional_profile_before(history(self),
            as_of="2026-11-06T19:00:00+09:00", racer_id="4001")]
        update["entry_history"]["profiles"].append(conditional_profile_before([], as_of=CUTOFF, racer_id="4002"))
        store.save_context(workflow, update)
        left = store.read_contexts(native, day=DAY)
        right = store.read_contexts(workflow, day=DAY)
        combined = store.merge_contexts(left, right)
        self.assertEqual(combined, store.merge_contexts(right, left))
        selected = combined["contexts"][RACE]
        self.assertEqual(selected["beforeinfo"]["source"]["captured_at"], "2030-04-01T11:50:00+09:00")
        self.assertEqual(selected["pitreport"]["source"]["captured_at"], "2030-04-01T11:55:00+09:00")
        self.assertEqual([(p["racer_id"], p["as_of"]) for p in selected["entry_history"]["profiles"]],
            [("4001", "2026-11-06T19:00:00+09:00"), ("4002", AS_OF)])
        self.assertNotEqual(combined["revision"], store.merge_contexts(left)["revision"])

    def test_component_merge_never_crosses_roster_or_cutoff_identity(self):
        rich = with_pit(profile_context(self))
        store.save_context(self.root, rich)
        prior = store.read_contexts(self.root, day=DAY)
        for mismatch in ("cutoff", "roster"):
            other = self.root / mismatch; other.mkdir(mode=0o700)
            update = context("2030-04-01T11:50:00+09:00")
            if mismatch == "cutoff":
                update["roster"] = deepcopy(rich["roster"])
                update["beforeinfo"]["participants"] = deepcopy(rich["roster"])
                update["cutoff_at"] = "2030-04-01T12:01:00+09:00"
            store.save_context(other, rich)
            store.save_context(other, update)
            current = store.read_contexts(other, day=DAY)
            self.assertIsNone(current["contexts"][RACE]["pitreport"])
            self.assertIsNone(current["contexts"][RACE]["entry_history"])
            combined = store.merge_contexts(prior, current)
            selected = combined["contexts"][RACE]
            with self.subTest(mismatch=mismatch):
                self.assertIsNone(selected["pitreport"])
                self.assertIsNone(selected["entry_history"])
                self.assertEqual(selected["roster"], update["roster"])
                self.assertEqual(selected["cutoff_at"], update["cutoff_at"])
                mismatch_view = view()
                mismatch_view["records"][0]["participants"] = [dict(number=r["lane"],
                    registration_no=r["registration_number"]) for r in rich["roster"]]
                self.assertIsNone(store.attach_contexts(mismatch_view, combined))

    def test_workflow_latest_attaches_from_both_roots_and_refreshes_revision_without_changing_originals(self):
        native = self.root / "native"; native.mkdir(mode=0o700)
        workflow = self.root / "workflow"; workflow.mkdir(mode=0o700)
        service = LocalForecastService(native, workflow_projection_root=workflow,
            clock=lambda: datetime.fromisoformat("2030-04-01T11:55:00+09:00"))
        original = view()
        snapshot = {"view": original, "status": {"day_jst": DAY, "revision": "e"*64}}
        with patch("race_ai.workflow_live_projection.read_projection", return_value=snapshot), \
             patch("urllib.request.urlopen", side_effect=AssertionError("read fetched source")), \
             patch("race_ai.existing_model_dispatch.run_suite", side_effect=AssertionError("read inferred")), \
             patch("race_ai.observed_weight_learning.fit_from_verified", side_effect=AssertionError("read trained")):
            first = service.latest("boat", "P0")
            store.save_context(workflow, context())
            enriched = service.latest("boat", "P0")
            self.assertNotEqual(first["revision"], enriched["revision"])
            self.assertEqual(enriched["view"]["records"][0]["boat_observation_context"]["beforeinfo"]["source"]["captured_at"],
                "2030-04-01T11:45:00+09:00")
            store.save_context(native, context("2030-04-01T11:50:00+09:00"))
            newest = service.latest("boat", "P0")
            self.assertNotEqual(newest["revision"], enriched["revision"])
            self.assertEqual(newest["view"]["records"][0]["boat_observation_context"]["beforeinfo"]["source"]["captured_at"],
                "2030-04-01T11:50:00+09:00")
            store.save_context(workflow, with_pit(context("2030-04-01T11:40:00+09:00"),
                                                "2030-04-01T11:42:00+09:00"))
            separate_pit = service.latest("boat", "P0")
            self.assertNotEqual(separate_pit["revision"], newest["revision"])
            separate = separate_pit["view"]["records"][0].pop("boat_observation_context")
            self.assertEqual(separate["beforeinfo"]["source"]["captured_at"], "2030-04-01T11:50:00+09:00")
            self.assertEqual(separate["pitreport"]["source"]["captured_at"], "2030-04-01T11:42:00+09:00")
            self.assertEqual(separate_pit["view"], original)
            newest["view"]["records"][0].pop("boat_observation_context")
            self.assertEqual(newest["view"], original)
            self.assertEqual(snapshot["view"], original)
            for file in (workflow / "boat-context").glob("*.json"): file.write_bytes(b"corrupt")
            for file in (native / "boat-context").glob("*.json"): file.write_bytes(b"corrupt")
            still_ready = service.latest("boat", "P0")
            self.assertTrue(still_ready["available"])
            self.assertEqual(still_ready["view"], original)
            self.assertEqual(still_ready["revision"], first["revision"])


if __name__ == "__main__":
    unittest.main()
