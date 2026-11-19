"""Synthetic public-JSON contracts; no real source documents or predictions."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from race_ai import keirin_official_public_source as official
from race_ai import keirin_nationwide_auto_generator as model


DAY = "2026-10-02"
RACE = "202610022601"
EVENT = "synthetic-event-token-0001"
TOKENS = ["synthetic-race-token-0001", "synthetic-race-token-0002"]
NOW = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)


def fixtures():
    """Handwritten, fictional values in the publicly observed field shapes."""
    registry = {
        "kInfo": [{"jyoName": "架空場", "KeirinCd": "26", "bKeirinCd": "26",
                   "gradeIconChar": "F1", "nitijiIconChar": "初日",
                   "encPrm": EVENT, "btnFlgResult": 1, "zenjituFlg": 0}],
        "kResultCd": 1, "resultCd": 0,
        "reqprm": {"kday": "20261002"}, "writeANA": False,
    }
    schedule = {
        "rInfo": [{
            "raceNo": n, "syumoku": "Ａ級予選", "denTime": cutoff,
            "stTime": start, "resultFlg": 1, "narabiFlg": 0,
            "sInfo": [{"syaban": car, "senNo": f"999{car:03d}",
                       "senName": f"架空選手{car}", "huken": "架空", "kyaku": "両"}
                      for car in range(1, 8)],
        } for n, cutoff, start in [(1, "10:47", "10:50"), (2, "11:47", "11:50")]],
        "syusouDispFlag": 1, "keirinCd": "26", "kaisaihi": "20261002",
        "lastUpdateTime": "2026/10/02 07:00&nbsp;更新",
        "resultCd": 0, "reqprm": {"bkcd": "26", "kday": "20261002"},
        "writeANA": True,
    }
    row = {
        "rclblRaceNo": "1R", "rclblSyumokuName": "Ａ級予選",
        "tyakui1List": [{"rclblTyakui": 1, "rclblSyaban": 1}],
        "tyakui2List": [{"rclblTyakui": 2, "rclblSyaban": 2}],
        "tyakui3List": [{"rclblTyakui": 3, "rclblSyaban": 3}],
        "harai2syaList": [{"kumi": "1-2", "kingaku": "300円", "ninki": "(1)"}],
        "harai3renList": [{"kumi": "1-2-3", "kingaku": "1,230円", "ninki": "(2)"}],
        "kessyaList": [], "kessyaDokantoList": [], "raceRVFLG": 1,
        "raceRVPrm": TOKENS[0], "raceTanpyoPrm": TOKENS[0], "cheackFLG": True,
    }
    summary = {
        "resultList": [row], "raceCount": 1, "kessyaFlg": 0,
        "kessyaDokantoFlg": 0, "ctlblResultUpdate": "2026/10/02 12:05&nbsp;更新",
        "bkcd": "26", "kday": "20261002", "resultCd": 0, "writeANA": True,
    }
    header = {
        "C0201data": {
            "encSelParaK": EVENT, "encSelParaR": TOKENS[0],
            "selKaisai": "20261002", "selKjyoCd": "26", "selRaceNo": 1,
            "flgRaceCancel": False, "flgSectionCancel": False,
            "C0201race": [{"encParaR": token, "flgRaceEnd": True,
                           "rcvKekka": "1", "rcvRefund": "1"} for token in TOKENS],
            "C0201racedtl": {"aftBetTime": "10:47", "aftStartTime": "10:50",
                              "bfrBetTime": "10:47", "bfrStartTime": "10:50"},
        }, "resultCd": 0, "writeANA": False,
    }
    detail = {
        "haraiGakuDispFlg": True, "tyakujyunDispFlg": True,
        "syabanItemDispFlg": False, "bikouDispFlg": False,
        "lastUpdateTime": "2026/10/02 12:05&nbsp;更新",
        "tyakujyunItemSubData": [{"tyaku": str(car), "syaban": str(car),
                                 "sensyuRegistNo": f"999{car:03d}",
                                 "kojinStateItemSubData": []}
                                for car in range(1, 8)],
        "haraiGakuSubData": {
            "RT3HaraiGakuDispItemSubData": [{
                "kumiBan": "1-2-3", "haraiGaku": "1,230",
                "ninki": "(2)", "ninkiDispFlg": True, "kumiDispFlg": True}],
            "APartReturnDispFlg": False,
        }, "resultCd": 0, "writeANA": True,
    }
    return {"JSJ057": registry, "JSJ017": schedule, "JSJ018": summary,
            "JSJ001": header, "JSJ012": detail}


def transport(data, calls=None):
    def get(url):
        if calls is not None:
            calls.append(url)
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.netloc == "keirin.jp"
        assert parsed.path == "/pc/json"
        params = parse_qs(parsed.query)
        kind = params["type"][0]
        if kind == "JSJ057":
            assert params == {"type": [kind], "kday": ["20261002"]}
        elif kind in ("JSJ017", "JSJ018"):
            assert params == {"type": [kind], "encp": [EVENT]}
        else:
            assert params == {"type": [kind], "encp": [TOKENS[0]]}
        return json.dumps(data[kind], ensure_ascii=False).encode("utf-8")
    return get


class OfficialPublicSourceContract(unittest.TestCase):
    def setUp(self):
        self.data = fixtures()
        self.get = transport(self.data)
        self.clock = lambda: NOW

    def schedule(self):
        return official.fetch_day_schedule(DAY, fetcher=self.get, clock=self.clock)

    def result(self, **kwargs):
        return official.fetch_race_result(
            RACE, schedule=self.schedule(), fetcher=self.get, clock=self.clock,
            **kwargs)

    def test_official_schedule_uses_published_cutoff_and_actual_race_universe(self):
        schedule = self.schedule()
        self.assertEqual(schedule["expected_venue_codes"], ["26"])
        self.assertEqual([r["race_id"] for r in schedule["races"]],
                         ["202610022601", "202610022602"])
        self.assertEqual(schedule["races"][0]["official_cutoff_at"],
                         "2026-10-02T10:47:00+09:00")
        self.assertEqual(schedule["races"][0]["start_at"],
                         "2026-10-02T10:50:00+09:00")
        self.assertEqual(schedule["venue_snapshots"][0]["race_numbers"], [1, 2])
        self.assertTrue(official.reparse_day_schedule(schedule))

    def test_schedule_requires_source_day_venue_and_unique_races(self):
        for target, field, value in [
            ("JSJ057", "reqprm", {"kday": "20261003"}),
            ("JSJ017", "keirinCd", "27"),
            ("JSJ017", "kaisaihi", "20261003"),
        ]:
            with self.subTest(field=field):
                self.data = fixtures()
                self.data[target][field] = value
                self.get = transport(self.data)
                with self.assertRaises(official.OfficialSourceError):
                    self.schedule()
        self.data = fixtures()
        self.data["JSJ017"]["rInfo"][1]["raceNo"] = 1
        self.get = transport(self.data)
        with self.assertRaises(official.OfficialSourceError):
            self.schedule()

    def test_duplicate_venues_and_same_token_for_different_venues_rejected(self):
        self.data["JSJ057"]["kInfo"].append(deepcopy(self.data["JSJ057"]["kInfo"][0]))
        with self.assertRaises(official.OfficialSourceError):
            self.schedule()
        self.data["JSJ057"]["kInfo"][1]["KeirinCd"] = "27"
        self.data["JSJ057"]["kInfo"][1]["bKeirinCd"] = "27"
        with self.assertRaises(official.OfficialSourceError):
            self.schedule()

    def test_explicit_empty_successful_calendar_preserves_the_day_receipt(self):
        # Synthetic empty list in the observed success envelope; this is not
        # evidence that a real no-meeting day or a special empty status was seen.
        self.data["JSJ057"]["kInfo"] = []
        calls=[]
        self.get=transport(self.data,calls)
        schedule=self.schedule()
        self.assertEqual(len(calls),1)
        self.assertEqual(schedule["expected_venue_codes"],[])
        self.assertEqual(schedule["venue_snapshots"],[])
        self.assertEqual(schedule["races"],[])
        self.assertEqual(len(schedule["snapshots"]),1)
        self.assertTrue(official.reparse_day_schedule(schedule))
        from scripts.keirin_official_day_pipeline import build_registry
        registry=build_registry(schedule)
        self.assertEqual(registry["captured_race_count"],0)
        self.assertTrue(registry["nationwide_coverage_independently_verified"])

    def test_missing_malformed_or_unknown_calendar_status_is_not_an_empty_day(self):
        for mutate in (
            lambda d:d.pop("kInfo"),
            lambda d:d.update(kInfo=None),
            lambda d:d.update(kInfo={}),
            lambda d:d.update(kInfo=[],kResultCd=0),
            lambda d:d.update(kInfo=[],kResultCd=2),
            lambda d:d.update(kInfo=[],kResultCd=True),
            lambda d:d.update(kInfo=[],kResultCd="1"),
            lambda d:(d.update(kInfo=[]),d.pop("kResultCd")),
            lambda d:d.update(kInfo=[],resultCd=-1),
            lambda d:d.update(kInfo=[],reqprm={"kday":"20261003"}),
        ):
            with self.subTest(mutate=mutate):
                self.data=fixtures()
                mutate(self.data["JSJ057"])
                self.get=transport(self.data)
                with self.assertRaises(official.OfficialSourceError):
                    self.schedule()

    def test_missing_cutoff_preserves_race_in_registry_without_guessing(self):
        self.data["JSJ017"]["rInfo"][0]["denTime"] = ""
        schedule = self.schedule()
        self.assertEqual(len(schedule["races"]), 2)
        self.assertIsNone(schedule["races"][0]["official_cutoff_at"])
        self.assertTrue(official.reparse_day_schedule(schedule))
        result = official.fetch_race_result(
            RACE, schedule=schedule, fetcher=self.get, clock=self.clock)
        self.assertEqual(result["state"], "HOLD_OFFICIAL_CUTOFF_UNAVAILABLE")
        self.assertIsNone(result["result"])

    def test_schedule_reparse_rejects_forged_cutoff_hash_and_source_url(self):
        for mutate in (
            lambda s: s["races"][0].update(official_cutoff_at="2026-10-02T11:47:00+09:00"),
            lambda s: s["snapshots"][0].update(source_sha256="0" * 64),
            lambda s: s["snapshots"][0].update(url="https://example.com/pc/json"),
            lambda s: s["expected_venue_codes"].append("27"),
        ):
            candidate = self.schedule()
            mutate(candidate)
            self.assertFalse(official.reparse_day_schedule(candidate))

    def test_result_joins_source_identity_cutoff_and_two_official_payout_views(self):
        record = self.result()
        self.assertEqual(record["state"], "OFFICIAL_FINAL")
        result = record["result"]
        self.assertEqual(set(result), {
            "race_id", "status", "refund_status", "official_cutoff_at",
            "source_published_at", "observed_at", "source_url", "source_sha256",
            "provider_revision_ref", "winning_triples", "payouts_100yen"})
        self.assertEqual(result["winning_triples"], [[1, 2, 3]])
        self.assertEqual(result["payouts_100yen"], [{"triple": [1, 2, 3], "yen": 1230}])
        self.assertEqual(result["source_published_at"], "2026-10-02T12:05:00+09:00")
        self.assertEqual(result["official_cutoff_at"], "2026-10-02T10:47:00+09:00")
        self.assertNotEqual(result["source_published_at"], result["observed_at"])
        self.assertFalse(record["provenance"]["cryptographic_signature_verified"])
        self.assertTrue(official.reparse_race_result(record))

    def test_no_published_result_remains_pending_not_a_miss_or_void(self):
        self.data["JSJ018"].update(resultList=[], raceCount=0)
        record = self.result()
        self.assertEqual(record["state"], "HOLD_RESULT_PENDING")
        self.assertIsNone(record["result"])
        self.assertTrue(official.reparse_race_result(record))

    def test_missing_official_update_time_is_not_replaced_by_observation_clock(self):
        del self.data["JSJ012"]["lastUpdateTime"]
        record = self.result()
        self.assertEqual(record["state"], "HOLD_PUBLICATION_TIME_UNAVAILABLE")
        self.assertIsNone(record["result"])

    def test_future_or_pre_cutoff_publication_time_is_rejected(self):
        for stamp in ["2026/10/03 12:05&nbsp;更新", "2026/10/02 08:00&nbsp;更新"]:
            with self.subTest(stamp=stamp):
                self.data["JSJ012"]["lastUpdateTime"] = stamp
                self.assertEqual(self.result()["state"], "HOLD_PUBLICATION_TIME_INCONSISTENT")

    def test_wrong_summary_or_header_identity_cannot_be_scored(self):
        for target, field, value in [
            ("JSJ018", "bkcd", "27"), ("JSJ018", "kday", "20261003"),
            ("JSJ001", "selRaceNo", 2), ("JSJ001", "selKjyoCd", "27"),
            ("JSJ001", "selKaisai", "20261003"),
        ]:
            with self.subTest(field=field):
                self.data = fixtures()
                node = self.data[target]
                if target == "JSJ001":
                    node = node["C0201data"]
                node[field] = value
                self.get = transport(self.data)
                with self.assertRaises(official.OfficialSourceError):
                    self.result()

    def test_official_payout_disagreement_is_hold(self):
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "1,240"
        record = self.result()
        self.assertEqual(record["state"], "HOLD_OFFICIAL_RESULT_DISAGREEMENT")
        self.assertIsNone(record["result"])

    def test_malformed_header_race_entry_is_a_source_error(self):
        self.data["JSJ001"]["C0201data"]["C0201race"][0] = None
        with self.assertRaises(official.OfficialSourceError):
            self.result()

    def test_non_text_receipt_url_fails_reparse_without_crashing(self):
        schedule = self.schedule()
        schedule["snapshots"][0]["url"] = []
        self.assertFalse(official.reparse_day_schedule(schedule))

    def test_dead_heat_retains_both_winning_orders_and_separate_payouts(self):
        summary = self.data["JSJ018"]["resultList"][0]
        summary["tyakui1List"].append({"rclblTyakui": 1, "rclblSyaban": 2})
        summary["tyakui2List"] = []
        summary["harai3renList"].append({"kumi": "2-1-3", "kingaku": "4,560円"})
        self.data["JSJ012"]["tyakujyunItemSubData"][1]["tyaku"] = "1"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"].append({
            "kumiBan": "2-1-3", "haraiGaku": "4,560", "kumiDispFlg": True})
        record = self.result()
        self.assertEqual(record["state"], "OFFICIAL_FINAL")
        self.assertEqual(record["result"]["winning_triples"], [[1, 2, 3], [2, 1, 3]])
        self.assertEqual(record["result"]["payouts_100yen"], [
            {"triple": [1, 2, 3], "yen": 1230}, {"triple": [2, 1, 3], "yen": 4560}])
        self.assertTrue(official.reparse_race_result(record))
        summary["harai3renList"].pop()
        self.assertEqual(self.result()["state"], "HOLD_OFFICIAL_RESULT_DISAGREEMENT")

    def test_special_payout_and_partial_refund_never_become_normal_loss(self):
        self.data["JSJ012"]["haraiGakuSubData"]["APartReturnDispFlg"] = True
        record = self.result()
        self.assertEqual(record["state"], "HOLD_REFUND_DETAILS_UNVERIFIED")
        self.assertIsNone(record["result"])
        self.data = fixtures()
        self.get = transport(self.data)
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0] = {
            "haraiGaku": "70", "kumiDispFlg": False}
        record = self.result()
        self.assertEqual(record["state"], "HOLD_SPECIAL_PAYOUT_UNVERIFIED")
        self.assertIsNone(record["result"])

    def test_cancellation_flag_and_changed_cutoff_preserve_hold(self):
        self.data["JSJ001"]["C0201data"]["flgRaceCancel"] = True
        record = self.result()
        self.assertEqual(record["state"], "HOLD_CANCELLATION_DETAILS_UNVERIFIED")
        self.assertIsNone(record["result"])
        self.data["JSJ001"]["C0201data"]["flgRaceCancel"] = False
        self.data["JSJ001"]["C0201data"]["C0201racedtl"]["aftBetTime"] = "10:48"
        self.assertEqual(self.result()["state"], "HOLD_OFFICIAL_CUTOFF_CHANGED")

    def test_changed_normal_result_with_same_update_time_remains_hold(self):
        previous = self.result()["result"]
        original = deepcopy(previous)
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "HOLD_RESULT_REVISION_REVIEW")
        self.assertEqual(record["provenance"]["revision_review_reason"],
                         "OFFICIAL_PAGE_UPDATE_NOT_NEWER")
        self.assertIsNone(record["result"])
        self.assertEqual(previous, original)
        self.assertTrue(official.reparse_race_result(record))

    def test_newer_official_correction_links_both_canonical_revisions_without_rewriting(self):
        previous_record = self.result()
        original = deepcopy(previous_record)
        previous = previous_record["result"]
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "OFFICIAL_FINAL")
        self.assertEqual(record["result"]["payouts_100yen"],
                         [{"triple": [1, 2, 3], "yen": 2340}])
        self.assertEqual(record["provenance"]["revision_relationship"], {
            "kind": "NORMAL_RESULT_CORRECTION",
            "previous_result_revision_sha256": model.digest({
                k: v for k, v in previous.items() if k != "observed_at"}),
            "previous_source_sha256": previous["source_sha256"],
            "previous_source_published_at": previous["source_published_at"],
            "current_result_revision_sha256": model.digest({
                k: v for k, v in record["result"].items() if k != "observed_at"}),
        })
        self.assertEqual(previous_record, original)
        self.assertTrue(official.reparse_race_result(previous_record))
        self.assertTrue(official.reparse_race_result(record))

    def test_corrected_result_cannot_roll_back_to_older_official_page_update(self):
        original_data = deepcopy(self.data)
        previous = self.result()["result"]
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        corrected = self.result(previous_result=previous)
        self.assertIsNotNone(corrected["result"])
        self.data = original_data
        self.get = transport(self.data)
        rollback = self.result(previous_result=corrected["result"])
        self.assertEqual(rollback["state"], "HOLD_RESULT_REVISION_REVIEW")
        self.assertEqual(rollback["provenance"]["revision_review_reason"],
                         "OFFICIAL_PAGE_UPDATE_REGRESSED")
        self.assertIsNone(rollback["result"])
        self.assertEqual(rollback["provenance"]["candidate_result"]["payouts_100yen"],
                         previous["payouts_100yen"])
        self.assertTrue(official.reparse_race_result(rollback))

    def test_newer_corrected_winning_order_requires_updated_finishes_in_both_views(self):
        previous = self.result()["result"]
        summary = self.data["JSJ018"]["resultList"][0]
        summary["harai3renList"][0]["kumi"] = "2-1-3"
        detail = self.data["JSJ012"]
        detail["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["kumiBan"] = "2-1-3"
        detail["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        self.assertEqual(self.result(previous_result=previous)["state"],
                         "HOLD_OFFICIAL_RESULT_DISAGREEMENT")
        summary["tyakui1List"][0]["rclblSyaban"] = 2
        summary["tyakui2List"][0]["rclblSyaban"] = 1
        detail["tyakujyunItemSubData"][0]["tyaku"] = "2"
        detail["tyakujyunItemSubData"][1]["tyaku"] = "1"
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "OFFICIAL_FINAL")
        self.assertEqual(record["result"]["winning_triples"], [[2, 1, 3]])
        self.assertTrue(official.reparse_race_result(record))

    def test_stale_unchanged_response_cannot_lower_the_accepted_update_time(self):
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        previous = self.result()["result"]
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:05&nbsp;更新"
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "HOLD_RESULT_REVISION_REVIEW")
        self.assertIsNone(record["result"])
        self.assertEqual(record["provenance"]["revision_review_reason"],
                         "OFFICIAL_PAGE_UPDATE_REGRESSED")

    def test_reread_observation_time_does_not_change_prior_revision_digest(self):
        previous = self.result()["result"]
        reread = deepcopy(previous)
        reread["observed_at"] = "2026-10-02T08:01:00+00:00"
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        first = self.result(previous_result=previous)
        second = self.result(previous_result=reread)
        self.assertEqual(first["provenance"]["revision_relationship"],
                         second["provenance"]["revision_relationship"])

    def test_unchanged_result_reread_does_not_claim_a_semantic_correction(self):
        previous = self.result()["result"]
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "OFFICIAL_FINAL")
        self.assertEqual(record["result"], previous)
        self.assertNotIn("revision_relationship", record["provenance"])
        self.assertTrue(official.reparse_race_result(record))

    def test_newer_timestamp_cannot_override_payout_disagreement_or_refund(self):
        previous = self.result()["result"]
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        payment = self.data["JSJ012"]["haraiGakuSubData"]
        payment["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "HOLD_OFFICIAL_RESULT_DISAGREEMENT")
        self.assertIsNone(record["result"])
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        payment["APartReturnDispFlg"] = True
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "HOLD_REFUND_DETAILS_UNVERIFIED")
        self.assertIsNone(record["result"])
        payment["APartReturnDispFlg"] = False
        self.data["JSJ001"]["C0201data"]["flgRaceCancel"] = True
        record = self.result(previous_result=previous)
        self.assertEqual(record["state"], "HOLD_CANCELLATION_DETAILS_UNVERIFIED")
        self.assertIsNone(record["result"])

    def test_previous_revision_must_be_a_complete_same_race_normal_result(self):
        previous = self.result()["result"]
        for mutate in (
            lambda r: r.update(race_id="202610022602"),
            lambda r: r.update(status="CANCELLED", refund_status="FULL"),
            lambda r: r.update(source_sha256="invalid"),
            lambda r: r.pop("source_published_at"),
            lambda r: r.update(source_url="https://example.com/result"),
            lambda r: r.update(source_published_at="2026-10-02T12:05:00"),
            lambda r: r["payouts_100yen"][0].update(yen=True),
        ):
            with self.subTest(mutate=mutate):
                invalid = deepcopy(previous)
                mutate(invalid)
                with self.assertRaises(official.OfficialSourceError):
                    self.result(previous_result=invalid)

    def test_revision_relationship_is_bound_by_receipt_reparse(self):
        previous = self.result()["result"]
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        self.data["JSJ012"]["lastUpdateTime"] = "2026/10/02 12:06&nbsp;更新"
        record = self.result(previous_result=previous)
        for key in ("previous_result_revision_sha256", "previous_source_sha256",
                    "previous_source_published_at", "current_result_revision_sha256"):
            invalid = deepcopy(record)
            invalid["provenance"]["revision_relationship"][key] = "forged"
            self.assertFalse(official.reparse_race_result(invalid))

    def test_result_reparse_binds_raw_hash_url_cutoff_and_payout(self):
        for mutate in (
            lambda r: r["result"]["payouts_100yen"][0].update(yen=9990),
            lambda r: r["result"].update(source_sha256="0" * 64),
            lambda r: r["snapshots"][-1].update(url="https://keirin.jp.evil/pc/json"),
            lambda r: r["snapshots"][-1].update(raw_bytes=b"{}"),
            lambda r: r["result"].update(official_cutoff_at="2026-10-02T12:00:00+09:00"),
        ):
            record = self.result()
            mutate(record)
            self.assertFalse(official.reparse_race_result(record))

    def test_block_or_rate_limit_stops_without_retry_or_second_source(self):
        for status in (403, 429):
            calls = []
            def blocked(url):
                calls.append(url)
                raise HTTPError(url, status, "blocked", {}, None)
            with self.subTest(status=status):
                with self.assertRaises(official.OfficialProviderStop):
                    official.fetch_day_schedule(DAY, fetcher=blocked, clock=self.clock)
                self.assertEqual(len(calls), 1)

    def test_bounded_raw_json_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b"{" + b" " * (4 * 1024 * 1024),
                    b'{"resultCd":0,"resultCd":-1}',
                    b'{"resultCd":NaN}'):
            with self.subTest(size=len(raw)):
                with self.assertRaises(official.OfficialSourceError):
                    official.fetch_day_schedule(DAY, fetcher=lambda _: raw, clock=self.clock)

    def test_raw_receipts_are_hash_bound_and_not_cryptographic_provider_signatures(self):
        schedule = self.schedule()
        for snapshot in schedule["snapshots"]:
            self.assertEqual(snapshot["source_sha256"], sha256(snapshot["raw_bytes"]).hexdigest())
            self.assertEqual(snapshot["observed_at"], "2026-10-02T08:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
