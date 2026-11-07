"""Invented native archives exercise evidence hydration, never live accuracy."""
from copy import deepcopy
import hashlib
import importlib
import io
import json
import unittest
import zipfile

from race_ai.actions_contract import digest
from race_ai.frozen_day_cycle import read_p0, read_p1
from race_ai.private_cycle_projection import project_state
from race_ai.saved_view_feed import forecast_inventory
from tests.test_frozen_day_cycle import sample
from tests.test_private_cycle_projection import saved_learned_archive, seal

try:
    M = importlib.import_module("race_ai.boat_saved_prediction_evidence")
except ModuleNotFoundError:
    M = None


def repack(document, receipt, member):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(member, json.dumps(document, ensure_ascii=False))
    raw = out.getvalue()
    receipt = deepcopy(receipt)
    receipt.update(digest="sha256:"+hashlib.sha256(raw).hexdigest())
    receipt["workflow_run"].update(repository_id=1416489937, head_sha="a"*40)
    return raw, receipt


def original_view(kind="P0", *, completion=True):
    if kind == "P0":
        doc, _, meta = sample()
        if completion:
            doc["completed_at"] = "2030-04-01T01:42:30Z"
        raw, meta = repack(doc, meta, "forecasts.json")
        _, rows = read_p0(raw, meta, expected_day="2030-04-01")
    else:
        doc, _, meta = saved_learned_archive()
        raw, meta = repack(doc, meta, "national.json")
        _, rows = read_p1(raw, meta)
        # Mirror the retained continuity, whose learned rows omit input/version.
        base = {(r["race_id"], r["model_id"]):r for r in rows}
        for shadow in doc["learned_pairwise_shadows"]:
            row = deepcopy(base[(shadow["race_id"], shadow["model_id"])])
            row.update(model_sha256=shadow["prediction_sha256"],
                       top8=shadow["ordered_top8"], ranked=[c["combination"] for c in shadow["candidates"]],
                       variant="LEARNED_SHADOW", baseline_model_sha256=shadow["baseline_model_sha256"],
                       training_sha256=shadow["training_sha256"])
            rows.append(row)
    state = seal(dict(schema="RACE_AI_RECOVERED_FIRST_RECEIPTS_V1", day_jst="2030-04-01",
                      rows=rows, receipts=[meta], observations=[], complete=False))
    view = project_state(state, dataset_status="SYNTHETIC_ONLY")
    for row in view["records"]:
        for p in [row["prediction"], *row["comparison_predictions"]]:
            p["source_code_commit"] = "a"*40
    return view, doc, raw, meta


class SavedPredictionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M, "native saved-evidence hydration is missing")

    def test_genuine_missing_metadata_is_separate_and_every_original_stays_exact(self):
        view, doc, raw, meta = original_view()
        before = deepcopy(view)
        output, counts = M.hydrate_prediction_evidence(view, [(raw, meta)])
        self.assertEqual(view, before)
        self.assertEqual(forecast_inventory(output), forecast_inventory(before))
        self.assertEqual(counts["evidenced_predictions"], 2)
        evidence = list(output["records"][0]["saved_prediction_evidence"].values())
        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(e["native"]["model_version"] == "0.1.0-UNTRAINED" for e in evidence))
        self.assertTrue(all(e["native"]["input_sha256"] == doc["predictions"][0]["snapshot_sha256"] for e in evidence))
        self.assertTrue(all(e["native"]["generated_at"] is None for e in evidence))
        self.assertTrue(all(e["native"]["as_of"] == doc["predictions"][0]["as_of"] for e in evidence))
        self.assertTrue(all(e["native"]["generation_completed_no_later_than"] == doc["completed_at"] for e in evidence))
        self.assertTrue(all(e["prediction_original_sha256"] in forecast_inventory(before).values() for e in evidence))
        self.assertTrue(all(p["model_version"] is None for p in [output["records"][0]["prediction"], *output["records"][0]["comparison_predictions"]]))

    def test_invocation_clock_never_becomes_exact_generation_or_completion(self):
        view, _, raw, meta = original_view(completion=False)
        output, counts = M.hydrate_prediction_evidence(view, [(raw, meta)])
        evidence = list(output["records"][0]["saved_prediction_evidence"].values())
        self.assertTrue(all(e["clock_kind"] == "NATIVE_ASOF_AND_PRE_CUTOFF_ORIGINAL" for e in evidence))
        self.assertTrue(all(e["native"]["generated_at"] is None and e["native"]["generation_completed_no_later_than"] is None for e in evidence))
        self.assertEqual(counts["exact_generation_clocks"], 0)
        self.assertEqual(counts["native_asof_clocks"], 2)

    def test_p1_parent_clock_and_native_learned_input_are_recovered_without_replay(self):
        view, doc, raw, meta = original_view("P1")
        output, counts = M.hydrate_prediction_evidence(view, [(raw, meta)])
        evidence = list(output["records"][0]["saved_prediction_evidence"].values())
        self.assertEqual(len(evidence), 7)
        self.assertEqual(counts["exact_generation_clocks"], 2)
        self.assertEqual(counts["native_asof_clocks"], 5)
        for model in doc["learned_pairwise_shadows"]:
            matched = [e for e in evidence if e["native"]["prediction_sha256"] == model["prediction_sha256"]]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["native"]["input_sha256"], model["input_sha256"])
            self.assertEqual(matched[0]["native"]["model_version"], model["model_version"])
            self.assertIsNone(matched[0]["native"]["generated_at"])

    def test_tamper_foreign_phase_head_roster_and_changed_original_stop(self):
        view, _, raw, meta = original_view()
        cases = []
        cases.append((view, raw+b"tampered", meta))
        wrong = deepcopy(meta); wrong["workflow_run"]["head_sha"] = "b"*40
        cases.append((view, raw, wrong))
        wrong = deepcopy(meta); wrong["name"] = "boat-national-cutoff-2"
        cases.append((view, raw, wrong))
        wrong_view = deepcopy(view); wrong_view["records"][0]["participants"][0]["registration_no"] = "9999"
        cases.append((wrong_view, raw, meta))
        wrong_view = deepcopy(view); wrong_view["records"][0]["prediction"]["ordered_top8"].reverse()
        cases.append((wrong_view, raw, meta))
        for v, r, m in cases:
            with self.subTest(case=len(r)), self.assertRaises(ValueError):
                M.hydrate_prediction_evidence(v, [(r, m)])

    def test_late_completion_and_conflicting_saved_metadata_are_not_repaired(self):
        view, doc, _, meta = original_view()
        doc["completed_at"] = "2030-04-01T01:43:01Z"
        raw, changed = repack(doc, meta, "forecasts.json")
        # Build a view of that actual changed member, so only clock semantics fail.
        _, rows = read_p0(raw, changed, expected_day="2030-04-01")
        state = seal(dict(schema="RACE_AI_RECOVERED_FIRST_RECEIPTS_V1",day_jst="2030-04-01",rows=rows,receipts=[changed],observations=[]))
        bad = project_state(state, dataset_status="SYNTHETIC_ONLY")
        with self.assertRaises(ValueError): M.hydrate_prediction_evidence(bad, [(raw, changed)])
        view, _, raw, meta = original_view()
        view["records"][0]["prediction"]["model_version"] = "invented-replacement"
        with self.assertRaises(ValueError): M.hydrate_prediction_evidence(view, [(raw, meta)])

    def test_repeated_archives_and_existing_evidence_are_idempotent_but_conflicts_stop(self):
        view, _, raw, meta = original_view()
        first, _ = M.hydrate_prediction_evidence(view, [(raw, meta), (raw, meta)])
        second, counts = M.hydrate_prediction_evidence(first, [(raw, meta)])
        self.assertEqual(first, second)
        self.assertEqual(counts["evidenced_predictions"], 2)
        broken = deepcopy(first)
        next(iter(broken["records"][0]["saved_prediction_evidence"].values()))["native"]["as_of"] = "2030-04-01T01:44:00Z"
        with self.assertRaises(ValueError): M.hydrate_prediction_evidence(broken, [(raw, meta)])

    def test_protected_outer_zip_uses_its_actual_receipt_and_never_exports_a_key(self):
        from race_ai.boat_private_original_archive import seal_original_zip
        view, _, raw, meta = original_view()
        key = bytes(range(32))  # Invented fixture key only.
        cipher = seal_original_zip(raw, run_id=2, head_sha="a"*40, kind="P0", key=key)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive: archive.writestr("private-original.enc", cipher)
        wrapped = out.getvalue();actual = deepcopy(meta)
        actual["digest"] = "sha256:"+hashlib.sha256(wrapped).hexdigest()
        output, counts = M.hydrate_prediction_evidence(view, [(wrapped, actual)], key=key)
        self.assertEqual(counts["evidenced_predictions"], 2)
        self.assertEqual(forecast_inventory(output), forecast_inventory(view))
        self.assertNotIn("key", json.dumps(counts))
        with self.assertRaises(ValueError): M.hydrate_prediction_evidence(view, [(wrapped, actual)], key=b"x"*32)


if __name__ == "__main__": unittest.main()
