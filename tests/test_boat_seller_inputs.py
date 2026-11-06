"""Fictional CSV originals exercise the unchanged daily seller strategy."""
from copy import deepcopy
from datetime import date
import csv
import hashlib
import importlib
import io
import unittest

from race_ai.existing_model_dispatch import dispatch

try:
    adapter = importlib.import_module("race_ai.boat_seller_inputs")
except ModuleNotFoundError:
    adapter = None

DAY = "2030-01-15"
AT = DAY+"T06:30:00+09:00"
MID = "seller-shadow-v1-20261104"


def csv_source(rows, kind):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(next(iter(rows.values()))))
    writer.writeheader(); writer.writerows(rows.values())
    raw = out.getvalue().encode("utf-8-sig")
    return dict(raw=raw, dataset_kind=kind, event_date_jst=DAY,
        metric_semantics="NATIONAL_WIN_RATING_POINTS_0_10" if kind == "race_cards" else "SAME_FRAME_WIN_RATING_POINTS_0_10",
        source_url="https://example.test/fictional-"+kind+".csv", source_sha256=hashlib.sha256(raw).hexdigest(),
        source_rights_ref="FICTIONAL_OWNER_REVIEW", captured_at=DAY+"T05:00:00+09:00", published_at=None)


def sources(count=8):
    cards = {}; waku = {}
    for n in range(1, count+1):
        rid = f"2030011518{n:02d}"
        card = {"レースコード": rid}; row = {"レースコード": rid}
        for lane in range(1, 7):
            prefix = f"艇{lane}_"
            card[prefix+"全国勝率"] = str(6.5 if lane == 1 else 5.8-.35*(lane-2))
            card[prefix+"級別"] = "A1" if lane == 1 else "B1"
            row[prefix+"枠番別勝率"] = str(8+n*.1 if lane == 1 else 6.8-.5*(lane-2))
        cards[rid] = card; waku[rid] = row
    return csv_source(cards, "race_cards"), csv_source(waku, "waku10"), list(cards)


class SellerNativeInputsTests(unittest.TestCase):
    def test_real_csv_contract_preserves_global_five_selection_and_source_clocks(self):
        self.assertIsNotNone(adapter, "daily seller source adapter is absent")
        cards, waku, ids = sources()
        before = deepcopy((cards, waku))
        batch = adapter.build_seller_native_inputs(cards, waku, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual((cards, waku), before)
        self.assertEqual(batch["readiness"]["seller"]["state"], "READY")
        payload = batch["native_inputs"]["seller"]
        self.assertEqual(payload["cards"][ids[0]]["艇1_全国勝率"], "6.5")
        self.assertEqual(payload["waku"][ids[0]]["艇1_枠番別勝率"], "8.1")
        self.assertTrue(all(e.get("published_at") is None for e in batch["source_evidence"] if "captured_at" in e))
        self.assertIn(cards["source_sha256"], {e["source_sha256"] for e in batch["source_evidence"]})
        schedule = [dict(race_id=r, sport="boat", stage="P0", cutoff_at=DAY+"T10:00:00+09:00") for r in ids]
        native = {r: {"P0": batch["native_inputs"]} for r in ids}
        admitted = {(e["source_ref"], e["source_rights_ref"]) for e in batch["source_evidence"]}
        report = dispatch(schedule, native, now=AT,
            allow_source=lambda ref, rights, purpose: (ref, rights) in admitted and purpose == "analysis")
        slots = [r for r in report["slots"] if r["model_id"] == MID]
        self.assertEqual(sum(r["status"] == "GENERATED_UNATTESTED" for r in slots), 5)
        self.assertEqual(sum(r["status"] == "RULE_FILTERED" for r in slots), 3)
        for slot in slots:
            if slot["status"] == "GENERATED_UNATTESTED":
                chosen = next(r for r in slot["prediction"]["rows"] if r["race_id"] == slot["race_id"])
                self.assertEqual([len(chosen["tickets"][k]) for k in ("three", "five")], [3, 5])

    def test_missing_rating_and_partial_daily_cards_never_become_ready(self):
        self.assertIsNotNone(adapter, "daily seller source adapter is absent")
        cards, waku, ids = sources()
        batch = adapter.build_seller_native_inputs(cards, None, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual(batch["readiness"]["seller"]["state"], "INPUT_MISSING")
        self.assertIn("SAME_FRAME_WIN_RATING_WAKU10_REQUIRED", batch["readiness"]["seller"]["reasons"])
        self.assertEqual(batch["native_inputs"], {})
        partial = adapter.build_seller_native_inputs(cards, waku, day=DAY, as_of=AT, expected_race_ids=ids+["203001151809"])
        self.assertEqual(partial["readiness"]["seller"]["state"], "INPUT_MISSING")
        self.assertIn("COMPLETE_DAILY_RACE_CARDS_REQUIRED", partial["readiness"]["seller"]["reasons"])

    def test_percentage_metrics_future_capture_wrong_day_and_tampered_bytes_fail_closed(self):
        self.assertIsNotNone(adapter, "daily seller source adapter is absent")
        for case in ("probability", "future", "day", "hash"):
            cards, waku, ids = sources()
            if case == "probability": waku["metric_semantics"] = "SAME_FRAME_WIN_FRACTION_0_1"
            if case == "future": waku["captured_at"] = DAY+"T06:31:00+09:00"
            if case == "day": waku["event_date_jst"] = "2030-01-14"
            if case == "hash": waku["raw"] += b"\n"
            batch = adapter.build_seller_native_inputs(cards, waku, day=DAY, as_of=AT, expected_race_ids=ids)
            with self.subTest(case=case):
                self.assertEqual(batch["readiness"]["seller"]["state"], "INPUT_REJECTED")
                self.assertEqual(batch["native_inputs"], {})

    def test_0700_gate_retains_missing_rows_in_the_unchanged_native_denominator(self):
        self.assertIsNotNone(adapter, "daily seller source adapter is absent")
        cards, waku, ids = sources()
        late = adapter.build_seller_native_inputs(cards, waku, day=DAY, as_of=DAY+"T07:00:00+09:00", expected_race_ids=ids)
        self.assertEqual(late["readiness"]["seller"]["state"], "DEADLINE_PASSED")
        # An absent row stays absent and is accounted for by the native strategy.
        rows = list(csv.DictReader(io.StringIO(waku["raw"].decode("utf-8-sig"))))[:-1]
        waku = csv_source({r["レースコード"]: r for r in rows}, "waku10")
        batch = adapter.build_seller_native_inputs(cards, waku, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual(batch["coverage"]["missing_same_frame_races"], [ids[-1]])
        from research.seller_shadow_v1.model import generate
        from datetime import datetime
        payload = batch["native_inputs"]["seller"]
        forecast = generate(payload["cards"], payload["waku"], date.fromisoformat(DAY), datetime.fromisoformat(AT))
        self.assertEqual(forecast["discovered"], 8)
        self.assertEqual(next(r for r in forecast["rows"] if r["race_id"] == ids[-1])["status"], "NO_WAKU10")
