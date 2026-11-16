"""Invented AES originals reproduce omitted native coverage metadata."""
from copy import deepcopy
from datetime import datetime
import hashlib
import io
import unittest
import zipfile

from race_ai import boat_saved_prediction_evidence as evidence
from race_ai import boat_saved_view_intake as intake
from race_ai.boat_ab_shadow import MODEL_IDS as AB
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.saved_view_feed import forecast_inventory
from tests.test_boat_saved_prediction_evidence import original_view


NOW = datetime.fromisoformat("2030-04-01T08:12:00+00:00")


def protected_p1():
    """Use real producer/reader shapes; the fixture key is invented and public."""
    view, document, raw, metadata = original_view("P1")
    key = bytes(range(32))
    cipher = seal_original_zip(raw, run_id=metadata["workflow_run"]["id"],
                               head_sha="a"*40, kind="P1", key=key)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("private-original.enc", cipher)
    raw = output.getvalue()
    metadata["digest"] = "sha256:"+hashlib.sha256(raw).hexdigest()
    schedule = [dict(race_id="20300401-24-12", cutoff_at="2030-04-01T17:30:00+09:00",
                     schedule_captured_at="2030-04-01T00:00:00+00:00", source_sha256="c"*64)]
    return view, document, raw, metadata, key, schedule


def predictions(row):
    return [row["prediction"], *row["comparison_predictions"]]


class NativeCoverageEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(evidence, "native_coverage_evidence", None)),
                        "authenticated native coverage evidence is unavailable")

    def hydrate(self, view, raw, metadata, key, schedule, *, now=NOW):
        return evidence.hydrate_prediction_evidence(
            view, [(raw, metadata)], key=key, official_schedule=schedule, now=now)

    def test_actual_aes_parent_generation_qualifies_without_changing_saved_predictions(self):
        view, document, raw, metadata, key, schedule = protected_p1()
        before = deepcopy(view)
        output, counts = self.hydrate(view, raw, metadata, key, schedule)
        self.assertEqual(view, before)
        self.assertEqual(forecast_inventory(output), forecast_inventory(before))
        self.assertEqual(predictions(output["records"][0]), predictions(before["records"][0]))
        qualified = []
        for prediction in predictions(output["records"][0]):
            proof = evidence.native_coverage_evidence(output["records"][0], prediction, now=NOW)
            if proof["status"] == "QUALIFIED_PRE_CUTOFF":
                qualified.append(prediction["model_id"])
                self.assertEqual(proof["generated_at"], "2030-04-01T08:10:00+00:00")
                self.assertEqual(proof["source_captured_at"], "2030-04-01T08:09:00+00:00")
                self.assertEqual(proof["server_saved_at"], "2030-04-01T08:11:00+00:00")
                self.assertEqual(proof["cutoff_at"], schedule[0]["cutoff_at"])
                self.assertEqual(proof["source_sha256"], document["paired_forecasts"][0]["source_sha256"])
            else:
                self.assertEqual(proof["reason"], "NATIVE_GENERATED_AT_MISSING")
                self.assertIsNone(proof["generated_at"])
        self.assertEqual(set(qualified), set(AB))
        self.assertEqual(counts["native_pre_cutoff_qualified"], 2)
        self.assertEqual(counts["native_pre_cutoff_held"], 5)
        self.assertTrue(all(p["generated_at"] is None for p in predictions(output["records"][0])))
        self.assertTrue(all("eligible_pre_cutoff" not in p for p in predictions(output["records"][0])))

    def test_official_schedule_conflict_and_late_capture_remain_holds(self):
        for change, reason in (({"cutoff_at":"2030-04-01T17:29:00+09:00"}, "OFFICIAL_CUTOFF_CONFLICT"),
                               ({"schedule_captured_at":"2030-04-01T08:10:01+00:00"}, "OFFICIAL_SCHEDULE_AFTER_INPUT")):
            with self.subTest(reason=reason):
                view, _, raw, metadata, key, schedule = protected_p1()
                schedule[0].update(change)
                output, counts = self.hydrate(view, raw, metadata, key, schedule)
                self.assertEqual(counts["native_pre_cutoff_qualified"], 0)
                p = next(p for p in predictions(output["records"][0]) if p["model_id"] in AB)
                self.assertEqual(evidence.native_coverage_evidence(output["records"][0], p, now=NOW)["reason"], reason)

    def test_missing_row_cutoff_never_uses_native_clock_as_official_schedule(self):
        view, _, raw, metadata, key, schedule = protected_p1()
        view["records"][0]["cutoff_at"] = None
        output, counts = self.hydrate(view, raw, metadata, key, schedule)
        self.assertEqual(counts["native_pre_cutoff_qualified"], 0)
        p = output["records"][0]["prediction"]
        self.assertEqual(evidence.native_coverage_evidence(output["records"][0], p, now=NOW)["reason"],
                         "ROW_OFFICIAL_CUTOFF_MISSING")

    def test_late_bootstrap_keeps_closed_schedule_rows_without_blocking_future_originals(self):
        view, _, raw, metadata, key, schedule = protected_p1()
        schedule[0]['schedule_captured_at']='2030-04-01T08:05:00+00:00'
        schedule.append(dict(race_id='20300401-24-11',cutoff_at='2030-04-01T17:00:00+09:00',
                             schedule_captured_at='2030-04-01T08:05:00+00:00',source_sha256='c'*64))
        output,counts=self.hydrate(view,raw,metadata,key,schedule)
        self.assertEqual(counts['native_pre_cutoff_qualified'],2)
        self.assertEqual(len(schedule),2)
        self.assertEqual(forecast_inventory(output),forecast_inventory(view))

    def test_future_receipt_and_missing_schedule_do_not_qualify(self):
        view, _, raw, metadata, key, schedule = protected_p1()
        for schedule_rows, now, reason in (([], NOW, "OFFICIAL_SCHEDULE_MISSING"),
                                           (schedule, datetime.fromisoformat("2030-04-01T08:10:30+00:00"),
                                            "NATIVE_CLOCK_IN_FUTURE")):
            with self.subTest(reason=reason):
                output, counts = self.hydrate(view, raw, metadata, key, schedule_rows, now=now)
                self.assertEqual(counts["native_pre_cutoff_qualified"], 0)
                p = output["records"][0]["prediction"]
                self.assertEqual(evidence.native_coverage_evidence(output["records"][0], p, now=now)["reason"], reason)

    def test_prediction_or_sidecar_tampering_is_rejected_by_the_coverage_consumer(self):
        view, _, raw, metadata, key, schedule = protected_p1()
        output, _ = self.hydrate(view, raw, metadata, key, schedule)
        for field in ("prediction", "evidence", "coverage", "schedule"):
            with self.subTest(field=field):
                broken = deepcopy(output); row = broken["records"][0]; p = row["prediction"]
                if field == "prediction": p["ordered_top8"].reverse()
                elif field == "evidence": next(iter(row["saved_prediction_evidence"].values()))["artifact"]["head_sha"] = "b"*40
                elif field == "coverage": next(iter(row["saved_prediction_coverage"].values()))["generated_at"] = "2030-04-01T08:10:01+00:00"
                else: row["cutoff_at"] = "2030-04-01T17:31:00+09:00"
                with self.assertRaises(ValueError):
                    evidence.native_coverage_evidence(row, p, now=NOW)

    def test_aes_authentication_and_opaque_existing_evidence_cannot_be_bypassed(self):
        view, _, raw, metadata, key, schedule = protected_p1()
        with self.assertRaises(ValueError): self.hydrate(view, raw, metadata, b"x"*32, schedule)
        self.assertIsNone(evidence.native_coverage_evidence(view["records"][0], view["records"][0]["prediction"], now=NOW))
        hydrated, _ = evidence.hydrate_prediction_evidence(view, [(raw, metadata)], key=key)
        self.assertIsNone(evidence.native_coverage_evidence(hydrated["records"][0], hydrated["records"][0]["prediction"], now=NOW))

    def test_intake_adds_coverage_beside_existing_evidence_once(self):
        import json
        view, _, raw, metadata, key, schedule = protected_p1()
        first, _ = evidence.hydrate_prediction_evidence(view, [(raw, metadata)], key=key)
        before = deepcopy(first)
        def get(path):
            return raw if path.endswith("/zip") else json.dumps(metadata).encode()
        output, counts = intake.hydrate_saved_originals(first, get, key=key, official_schedule=schedule, now=NOW)
        self.assertEqual(first, before)
        self.assertEqual(output["records"][0]["saved_prediction_evidence"], before["records"][0]["saved_prediction_evidence"])
        self.assertEqual(counts["native_pre_cutoff_qualified"], 2)
        second, again = intake.hydrate_saved_originals(output, lambda _:self.fail("already hydrated AES ZIP fetched again"),
                                                       key=key, official_schedule=schedule, now=NOW)
        self.assertEqual(second, output)
        self.assertEqual(again["native_pre_cutoff_qualified"], 2)


if __name__ == "__main__": unittest.main()
