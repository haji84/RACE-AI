"""Invented official B bytes exercise the offline seller source bridge."""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import csv
import hashlib
import io
import unittest

from race_ai.actions_contract import digest
from race_ai import boat_seller_inputs as seller
from race_ai.existing_model_dispatch import dispatch
from research.seller_shadow_v1.model import generate
from tests.test_boat_entry_observations import uncompressed_lzh


DAY = "2030-01-15"
AT = DAY + "T06:30:00+09:00"
CAPTURE = DAY + "T05:00:00+09:00"
SAVED = DAY + "T05:01:00+09:00"
HEAD = "a" * 40
URL = "https://www1.mbrace.or.jp/od2/B/203001/b300115.lzh"


def fixture():
    body = ["STARTB", "17BBGN", "2030年1月15日"]
    predictions = []; schedule = []
    for number in range(1, 9):
        rid = f"20300115-17-{number:02d}"
        cutoff = DAY + f"T10:{number:02d}:00+09:00"
        body.append(f" {number}R TEST H1800m 電話投票締切予定 10:{number:02d}")
        observations = []
        for lane in range(1, 7):
            rating = 6.5 if lane == 1 else 5.8 - .35 * (lane - 2)
            grade = "A1" if lane == 1 else "B1"
            body.append(f" {lane} {4000+lane}TEST 30東京52{grade} {rating:.2f} 45.00 5.50 30.00 "
                        f"{54+lane:02d} 35.00 {32+lane:02d} 30.00")
            observations.append(dict(lane=lane, registration_no=str(4000+lane), features={
                "national_win_rate": dict(value=float(f"{rating:.2f}"), source_id="official-B",
                                          sample_n=None, transform_id="identity-v1")}, missing={}))
        schedule.append(dict(race_id=rid, cutoff_at=cutoff))
        predictions.append(dict(race_id=rid, stage="P0", event_date_jst=DAY,
            as_of=DAY+"T05:00:10+09:00", sales_cutoff_at=cutoff, observations=observations))
    body.append("17BEND")
    text = "\n".join(body).encode("cp932")
    raw = uncompressed_lzh(text, "B300115.TXT")
    source_sha = hashlib.sha256(raw).hexdigest()
    evidence = dict(source_id="official-B", source_url=URL, source_sha256=source_sha,
        source_rights_ref="FICTIONAL_OWNER_B_ANALYSIS", captured_at=CAPTURE,
        published_at=None, evidence_basis="CAPTURED_BY_CLAIM")
    for prediction in predictions:
        prediction["source_evidence"] = [deepcopy(evidence)]
        prediction["suite_sha256"] = digest(prediction)
    document = dict(schema="RACE_AI_EXISTING_P0_DAY_V1", day_jst=DAY, actual_purchases=False,
        code_sha=HEAD, captured_at=CAPTURE, completed_at=DAY+"T05:00:20+09:00",
        source_url=URL, source_sha256=source_sha, extracted_text_sha256=hashlib.sha256(text).hexdigest(),
        race_count=8, schedule=schedule, predictions=predictions)
    receipt = dict(repository_id="1416489937", repository="haji84/RACE-AI", run_id="42", head_sha=HEAD,
        artifact_id=100, created_at=SAVED, payload_sha256=digest(document), independently_verified=True)
    return raw, document, receipt


def reseal(document, receipt):
    for prediction in document["predictions"]:
        prediction["suite_sha256"] = digest({k: v for k, v in prediction.items() if k != "suite_sha256"})
    receipt["payload_sha256"] = digest(document)


def waku_source():
    rows = []
    for number in range(1, 9):
        row = {"レースコード": f"2030011517{number:02d}"}
        for lane in range(1, 7):
            row[f"艇{lane}_枠番別勝率"] = str(8 + number / 10 if lane == 1 else 6.8 - .5 * (lane - 2))
        rows.append(row)
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    raw = out.getvalue().encode("utf-8-sig")
    return dict(raw=raw, dataset_kind="waku10", event_date_jst=DAY,
        metric_semantics="SAME_FRAME_WIN_RATING_POINTS_0_10", source_url="https://example.test/fictional-waku.csv",
        source_sha256=hashlib.sha256(raw).hexdigest(), source_rights_ref="FICTIONAL_OWNER_WAKU_ANALYSIS",
        captured_at=CAPTURE, published_at=None)


class OfficialSellerCardsTests(unittest.TestCase):
    def source(self, raw=None, document=None, receipt=None, *, as_of=AT):
        self.assertTrue(callable(getattr(seller, "official_b_cards_source", None)),
                        "offline official B seller source bridge is absent")
        original = fixture()
        return seller.official_b_cards_source(original[0] if raw is None else raw,
            original[1] if document is None else document, original[2] if receipt is None else receipt,
            day=DAY, as_of=as_of)

    def test_original_rating_grade_registration_and_receipt_survive_projection(self):
        raw, document, receipt = fixture(); before = deepcopy((raw, document, receipt))
        source = self.source(raw, document, receipt)
        self.assertEqual((raw, document, receipt), before)
        self.assertEqual(source["raw"], raw)
        self.assertEqual(source["metric_semantics"], "NATIONAL_WIN_RATING_POINTS_0_10")
        self.assertEqual(source["cards"]["203001151701"]["艇1_全国勝率"], "6.50")
        self.assertEqual(source["cards"]["203001151701"]["艇1_級別"], "A1")
        self.assertEqual(source["roster"]["203001151701"]["1"], "4001")
        original = source["source_evidence"][0]
        self.assertEqual(original["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(original["captured_at"], CAPTURE)
        self.assertIsNone(original["published_at"])
        self.assertIsNone(original["rating_window"])
        self.assertEqual(original["original_receipt"], receipt)
        self.assertEqual(source["source_requests"], 0)

    def test_missing_waku_preserves_complete_cards_and_only_the_genuine_missing_reason(self):
        raw, document, receipt = fixture(); source = self.source(raw, document, receipt)
        batch = seller.build_seller_native_inputs(source, day=DAY, as_of=AT,
            expected_race_ids=[r["race_id"] for r in document["schedule"]])
        self.assertEqual(batch["available_inputs"]["race_cards"], source["cards"])
        self.assertEqual(batch["readiness"]["race_cards"]["state"], "READY")
        self.assertEqual(batch["readiness"]["waku10"]["state"], "INPUT_MISSING")
        self.assertEqual(batch["readiness"]["waku10"]["reasons"], ["SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"])
        self.assertEqual(batch["readiness"]["seller"]["reasons"], ["SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"])
        self.assertEqual(batch["coverage"]["card_races"], 8)
        self.assertEqual(batch["coverage"]["card_entrants"], 48)
        self.assertEqual(batch["coverage"]["missing_same_frame_races"], [f"2030011517{n:02d}" for n in range(1, 9)])
        self.assertEqual(batch["native_inputs"], {})
        self.assertTrue(batch["source_evidence"])

    def test_observed_publication_clock_is_preserved_without_inference(self):
        raw, document, receipt = fixture()
        published = DAY + "T04:59:00+09:00"
        for prediction in document["predictions"]:
            prediction["source_evidence"][0]["published_at"] = published
        reseal(document, receipt)
        source = self.source(raw, document, receipt)
        self.assertEqual(source["source_evidence"][0]["published_at"], published)
        document["predictions"][0]["source_evidence"][0]["published_at"] = DAY+"T05:00:01+09:00"
        reseal(document, receipt)
        with self.assertRaises(ValueError): self.source(raw, document, receipt)

    def test_csv_cards_also_remain_visible_when_the_other_dataset_is_missing(self):
        from tests.test_boat_seller_inputs import sources
        cards, _, ids = sources()
        batch = seller.build_seller_native_inputs(cards, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual(batch["available_inputs"]["race_cards"]["203001151801"]["艇1_全国勝率"], "6.5")
        self.assertEqual(batch["readiness"]["seller"]["reasons"], ["SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"])
        self.assertEqual(batch["native_inputs"], {})
        cards["raw"] += b"changed"
        rejected = seller.build_seller_native_inputs(cards, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual(rejected["readiness"]["seller"]["state"], "INPUT_REJECTED")

    def test_genuine_waku_csv_uses_unchanged_native_daily_five_and_0700_rules(self):
        _, document, _ = fixture(); source = self.source(); waku = waku_source()
        ids = [r["race_id"] for r in document["schedule"]]
        batch = seller.build_seller_native_inputs(source, waku, day=DAY, as_of=AT, expected_race_ids=ids)
        self.assertEqual(batch["readiness"]["seller"]["state"], "READY")
        native = batch["native_inputs"]["seller"]
        forecast = generate(native["cards"], native["waku"], date.fromisoformat(DAY), datetime.fromisoformat(AT))
        selected = [r["race_id"] for r in forecast["rows"] if "tickets" in r]
        self.assertEqual(selected, [f"2030011517{n:02d}" for n in range(4, 9)])
        late = seller.build_seller_native_inputs(source, waku, day=DAY,
            as_of=DAY+"T07:00:00+09:00", expected_race_ids=ids)
        self.assertEqual(late["readiness"]["seller"]["state"], "DEADLINE_PASSED")
        self.assertEqual(late["native_inputs"], {})

    def test_official_b_evidence_authorizes_only_the_matching_native_daily_cards(self):
        _, document, _ = fixture()
        batch = seller.build_seller_native_inputs(self.source(), waku_source(), day=DAY, as_of=AT,
            expected_race_ids=[r["race_id"] for r in document["schedule"]])
        allowed = {(e["source_ref"], e["source_rights_ref"]) for e in batch["source_evidence"]}
        schedule = [dict(race_id=r["race_id"], sport="boat", stage="P0", cutoff_at=r["cutoff_at"])
                    for r in document["schedule"]]
        inputs = {r["race_id"]: {"P0": batch["native_inputs"]} for r in document["schedule"]}
        report = dispatch(schedule, inputs, now=AT,
            allow_source=lambda ref, rights, purpose: (ref, rights) in allowed and purpose == "analysis")
        states = Counter(r["status"] for r in report["slots"] if r["model_id"] == "seller-shadow-v1-20261104")
        self.assertEqual(states, {"GENERATED_UNATTESTED": 5, "RULE_FILTERED": 3})
        batch["native_inputs"]["seller"]["cards"]["203001151701"]["艇1_全国勝率"] = "9.99"
        rejected = dispatch(schedule, inputs, now=AT,
            allow_source=lambda ref, rights, purpose: (ref, rights) in allowed and purpose == "analysis")
        self.assertEqual({r["status"] for r in rejected["slots"] if r["model_id"] == "seller-shadow-v1-20261104"},
                         {"SOURCE_NOT_AUTHORIZED"})

    def test_changed_archive_document_receipt_and_source_identity_are_rejected(self):
        for case in ("bytes", "document", "receipt_hash", "foreign_repo", "unverified", "head", "url", "text_hash"):
            raw, document, receipt = fixture()
            if case == "bytes": raw += b"changed"
            elif case == "document": document["race_count"] = 7
            elif case == "receipt_hash": receipt["payload_sha256"] = "0" * 64
            elif case == "foreign_repo": receipt["repository"] = "foreign/RACE-AI"
            elif case == "unverified": receipt["independently_verified"] = False
            elif case == "head": receipt["head_sha"] = "b" * 40
            elif case == "url": document["source_url"] = "https://example.test/renamed-b.lzh"; reseal(document, receipt)
            elif case == "text_hash": document["extracted_text_sha256"] = "0" * 64; reseal(document, receipt)
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.source(raw, document, receipt)

    def test_authenticated_but_inconsistent_lane_registration_national_or_day_is_rejected(self):
        for case in ("registration", "duplicate_racer", "lane", "fraction", "source_hash", "feature_source", "day", "body_day"):
            raw, document, receipt = fixture(); prediction = document["predictions"][0]
            observation = prediction["observations"][0]
            if case == "registration": observation["registration_no"] = "4999"
            elif case == "duplicate_racer": prediction["observations"][1]["registration_no"] = "4001"
            elif case == "lane": observation["lane"] = 2
            elif case == "fraction": observation["features"]["national_win_rate"]["value"] = .65
            elif case == "source_hash": prediction["source_evidence"][0]["source_sha256"] = "0" * 64
            elif case == "feature_source": observation["features"]["national_win_rate"]["source_id"] = "other"
            elif case == "day": prediction["event_date_jst"] = "2030-01-14"
            elif case == "body_day":
                from race_ai.boat_entry_observations import extract_daily_lzh
                text = extract_daily_lzh(raw, "B300115.TXT").replace("2030年1月15日".encode("cp932"), "2030年1月14日".encode("cp932"))
                raw = uncompressed_lzh(text, "B300115.TXT")
                document["source_sha256"] = hashlib.sha256(raw).hexdigest()
                document["extracted_text_sha256"] = hashlib.sha256(text).hexdigest()
                for p in document["predictions"]: p["source_evidence"][0]["source_sha256"] = document["source_sha256"]
            reseal(document, receipt)
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.source(raw, document, receipt)

    def test_invalid_original_grade_and_rating_are_never_filled_from_the_saved_snapshot(self):
        from race_ai.boat_entry_observations import extract_daily_lzh
        for before, after in ((b"52A1", b"52ZZ"), (b"6.50 45.00", b"10.50 45.00")):
            raw, document, receipt = fixture()
            text = extract_daily_lzh(raw, "B300115.TXT").replace(before, after, 1)
            raw = uncompressed_lzh(text, "B300115.TXT")
            document.update(source_sha256=hashlib.sha256(raw).hexdigest(), extracted_text_sha256=hashlib.sha256(text).hexdigest())
            for p in document["predictions"]: p["source_evidence"][0]["source_sha256"] = document["source_sha256"]
            reseal(document, receipt)
            with self.subTest(after=after), self.assertRaises(ValueError): self.source(raw, document, receipt)

    def test_original_capture_generation_and_independent_save_clocks_cannot_be_backdated(self):
        for case in ("future_source", "future_receipt", "save_before_capture", "generation_before_capture", "generation_after_save"):
            raw, document, receipt = fixture()
            if case == "future_source":
                document["captured_at"] = DAY+"T06:31:00+09:00"
                for p in document["predictions"]: p["source_evidence"][0]["captured_at"] = document["captured_at"]
            elif case == "future_receipt": receipt["created_at"] = DAY+"T06:31:00+09:00"
            elif case == "save_before_capture": receipt["created_at"] = DAY+"T04:59:59+09:00"
            elif case == "generation_before_capture": document["predictions"][0]["as_of"] = DAY+"T04:59:59+09:00"
            elif case == "generation_after_save": document["predictions"][0]["as_of"] = DAY+"T05:02:00+09:00"
            reseal(document, receipt)
            with self.subTest(case=case), self.assertRaises(ValueError): self.source(raw, document, receipt)

    def test_partial_duplicate_or_mismatched_verified_daily_ledger_is_rejected(self):
        for case in ("missing", "extra", "duplicate", "cutoff", "prediction"):
            raw, document, receipt = fixture()
            if case == "missing": document["schedule"].pop()
            elif case == "extra": document["schedule"].append(dict(race_id="20300115-17-09", cutoff_at=DAY+"T10:09:00+09:00"))
            elif case == "duplicate": document["schedule"].append(deepcopy(document["schedule"][0]))
            elif case == "cutoff": document["schedule"][0]["cutoff_at"] = DAY+"T10:59:00+09:00"
            elif case == "prediction": document["predictions"].pop()
            reseal(document, receipt)
            with self.subTest(case=case), self.assertRaises(ValueError): self.source(raw, document, receipt)

    def test_modified_source_projection_or_source_bytes_cannot_enter_the_native_payload(self):
        _, document, _ = fixture()
        for case in ("cards", "raw", "roster", "proof"):
            source = self.source()
            if case == "cards": source["cards"]["203001151701"]["艇1_全国勝率"] = "9.99"
            elif case == "raw": source["raw"] += b"changed"
            elif case == "roster": source["roster"]["203001151701"]["1"] = "4999"
            elif case == "proof": source["source_evidence"][0]["captured_at"] = DAY+"T04:00:00+09:00"
            batch = seller.build_seller_native_inputs(source, waku_source(), day=DAY, as_of=AT,
                expected_race_ids=[r["race_id"] for r in document["schedule"]])
            with self.subTest(case=case):
                self.assertEqual(batch["readiness"]["seller"]["state"], "INPUT_REJECTED")
                self.assertEqual(batch["native_inputs"], {})


if __name__ == "__main__":
    unittest.main()
