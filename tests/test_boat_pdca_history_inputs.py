"""Fictional retained LZH sources exercise the real PDCA history adapter."""
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from race_ai import boat_all_model_inputs as adapter
from race_ai.boat_history_store import HistoryStore
from race_ai.existing_model_dispatch import dispatch
from race_ai.official_lzh_extract import extract_daily_lzh
from tests.test_boat_all_model_inputs import official_inputs, ASOF
from tests.test_boat_entry_observations import uncompressed_lzh
from tests.test_boat_history_store import archives


def retain_days(store, count=8):
    old, _ = archives()
    for n in range(1, count+1):
        day = date(2026, 11, n)
        sources = {}; raw = {}
        for kind in ("B", "K"):
            text = extract_daily_lzh(old[kind], kind+"261104.TXT").decode("cp932")
            text = text.replace("2026年11月4日", f"2026年11月{n}日").replace("2026/11/04", f"2026/11/{n:02d}")
            raw[kind] = uncompressed_lzh(text.encode("cp932"), f"{kind}2611{n:02d}.TXT")
            sources[kind] = dict(source_url=f"https://www1.mbrace.or.jp/od2/{kind}/202611/{kind.lower()}2611{n:02d}.lzh",
                source_sha256=hashlib.sha256(raw[kind]).hexdigest(), captured_at=f"2026-11-{n+1:02d}T18:00:00+09:00")
        store.ingest_day(day, raw["B"], raw["K"], sources["B"], sources["K"])


class PdcaHistoryInputsTests(unittest.TestCase):
    def test_verified_store_builds_24_distinct_real_reports_and_active_three_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/"history.sqlite")
            self.addCleanup(store.close)
            retain_days(store)
            program, before = official_inputs()
            result = adapter.build_native_inputs(program, before, as_of=ASOF,
                history_context=dict(history_store=store, history_identity_verified=True, owner_reviewed=True))
            self.assertEqual(result["readiness"]["boat_pdca"]["state"], "READY")
            pdca = result["native_inputs"]["boat_pdca"]
            self.assertEqual(len(pdca["rows"]), 24)
            self.assertEqual([r["lane"] for r in pdca["facts"]["racers"]], [1, 3, 6])
            self.assertEqual(pdca["facts"]["program_sha256"], program["source_sha256"])
            self.assertEqual(pdca["facts"]["source_sha256"], before["source_sha256"])
            reports = [json.loads(row["report_json"]) for row in pdca["rows"]]
            self.assertEqual(len({r["race_id"] for r in reports}), 24)
            self.assertEqual(reports[0]["captured_at"], "2026-11-02T18:00:00+09:00")
            self.assertEqual(pdca["rows"][0]["db_saved_at"], "2026-11-02T09:00:00+00:00")
            self.assertEqual(reports[0]["official_top3"], [6, 1, 2])
            self.assertEqual(pdca["history_availability_semantics"], "ARCHIVE_SOURCE_CAPTURE_BOUND_NOT_DATABASE_SAVE_ATTESTATION")
            for row in pdca["rows"]:
                self.assertEqual(hashlib.sha256(row["report_json"].encode()).hexdigest(), row["report_sha256"])
            report = dispatch([dict(race_id=program["race_id"], sport="boat", cutoff_at=program["closed_at"], stage="P1")],
                {program["race_id"]: {"P1": result["native_inputs"]}}, now=ASOF,
                allow_source=lambda ref, rights, purpose: purpose == "analysis")
            slot = next(s for s in report["slots"] if s["model_id"] == "boat-pdca-lane-shadow-v1")
            self.assertEqual(slot["status"], "GENERATED_UNATTESTED")
            self.assertEqual(slot["prediction"]["training_count"], 24)
            self.assertEqual(len(slot["prediction"]["ordered_top8"]), 6)
            self.assertFalse(slot["prediction"].get("trained", False))

    def test_missing_owner_review_and_insufficient_saved_results_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/"history.sqlite")
            self.addCleanup(store.close)
            retain_days(store, count=1)
            program, before = official_inputs()
            for reviewed, reason in ((False, "PDCA_OWNER_REVIEW_REQUIRED"), (True, "PDCA_REQUIRES_24_EARLIER_SAME_VENUE_RESULTS")):
                result = adapter.build_native_inputs(program, before, as_of=ASOF,
                    history_context=dict(history_store=store, history_identity_verified=True, owner_reviewed=reviewed))
                self.assertEqual(result["readiness"]["boat_pdca"]["state"], "INPUT_MISSING")
                self.assertIn(reason, result["readiness"]["boat_pdca"]["reasons"])
                self.assertIn("shared", result["native_inputs"])

    def test_future_archive_captures_and_foreign_venues_never_fill_history_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/"history.sqlite")
            self.addCleanup(store.close)
            retain_days(store)
            program, before = official_inputs()
            context = dict(history_store=store, history_identity_verified=True, owner_reviewed=True)
            ready = adapter.build_native_inputs(program, before, as_of=ASOF, history_context=context)
            payload = ready["native_inputs"]["boat_pdca"]
            # On Nov 7 morning only the first five captured daily files exist.
            facts = json.loads(json.dumps(payload["facts"]).replace("20300115", "20261107").replace("2030-01-15", "2026-11-07"))
            evidence = json.loads(json.dumps(payload["source_evidence"]).replace("20300115", "20261107").replace("2030-01-15", "2026-11-07"))
            earlier = adapter.pdca_payload_from_history(facts, as_of="2026-11-07T09:10:00+09:00",
                history_context=context, source_evidence=evidence)
            self.assertEqual(len(earlier["rows"]), 15)
            self.assertEqual(max(json.loads(r["report_json"])["captured_at"] for r in earlier["rows"]),
                             "2026-11-06T18:00:00+09:00")
            other = dict(payload["facts"], race_id="20300115-18-01",
                         source_url=payload["facts"]["source_url"].replace("jcd=17", "jcd=18"))
            foreign = adapter.pdca_payload_from_history(other, as_of=ASOF, history_context=context,
                source_evidence=payload["source_evidence"])
            self.assertEqual(foreign["rows"], [])
