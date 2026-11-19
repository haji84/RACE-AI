"""Synthetic published-page fixture; no real public network requests."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_auto_generator as predictor
from scripts import keirin_capture_public_two_sources as collector
from scripts import keirin_nationwide_auto_forecast as forecast
from tests.test_keirin_public_two_source_normalizer import pages,NET,KD,RID

REGISTRY=Path(__file__).resolve().parents[1]/"docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json"
CAPTURE_TIME="2026-11-18T09:01:00+09:00"


def manifest(*,count=1):
    data=[{
        "race_id":RID,"netkeirin_url":NET,
        "kdreams_url":KD,
        "cutoff_hint":"2026-11-18T20:45:00+09:00"
    }]
    return {"schema":collector.SCHEMA,"day_jst":"2026-11-18",
            "source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY",
            "races":data[:count]}


class TwoPublicSourcesToAutoAB(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cards=self.root/"cards";self.raw=self.root/"raw"
        self.out=self.root/"sealed"
        for p in (self.cards,self.raw,self.out):
            p.mkdir(mode=0o700)
            p.chmod(0o700)
        self.reg=json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.net,self.kd=pages()
        self.calls=[]
        self.f=self.fake_fetch
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.pem=self.key.public_key().public_bytes(
            serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        pub=self.key.public_key().public_bytes(
            serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.patch=patch.object(storage,"PINNED_OWNER_SPKI_SHA256",sha256(pub).hexdigest())
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def fake_fetch(self,url):
        self.calls.append(url)
        return {NET:self.net,KD:self.kd}[url]

    def now(self):
        return datetime.fromisoformat(CAPTURE_TIME)

    def collect(self,**overrides):
        args={
            "day_manifest":manifest(),
            "registered_ids":[x["race_id"] for x in self.reg["records"]],
            "private_cards_dir":self.cards,
            "private_raw_dir":self.raw,
            "clock":self.now,
            "fetch":self.f,
        }
        args.update(overrides)
        return collector.capture_cycle(**args)

    def test_public_pages_to_real_code_A_B_generation_and_AES(self):
        receipt=self.collect()
        self.assertEqual(receipt["normalized_private_cards"],1)
        self.assertEqual(self.calls,[NET,KD])
        card=json.loads((self.cards/(RID+".json")).read_text())
        self.assertEqual(card["line_groups"],[[1,5],[2],[4,3,6]])
        self.assertEqual(card["riders"][0]["athlete_id"],None)
        self.assertTrue((self.raw/(sha256(self.net).hexdigest()+".html")).exists())
        self.assertTrue((self.raw/(sha256(self.kd).hexdigest()+".html")).exists())
        report=forecast.run_cycle(
            registry=self.reg,private_racecards_dir=self.cards,
            raw_pages_dir=self.raw,private_cipher_dir=self.out,
            owner_public_key_pem=self.pem,clock=self.now)
        self.assertEqual(report["registered_races"],79)
        self.assertEqual(report["same_job_sealed"],1)
        self.assertEqual(report["B_generated"],1)
        self.assertEqual(report["statuses"]["NO_FORECAST_INPUT_MISSING"],78)
        self.assertEqual(report["cross_runner_RSA_decryption"],0)
        self.assertTrue((self.out/(RID+".sealed.json")).exists())

    def test_present_cards_do_not_duplicate_source_GETs(self):
        self.collect()
        again=self.collect()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(again["states"],{"CAPTURE_ALREADY_PRESENT_CREATE_ONCE":1})

    def test_blocked_provider_stops_without_retry(self):
        def denied(url):
            raise collector.SourceCaptureError("PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        out=self.collect(fetch=denied)
        self.assertEqual(out["normalized_private_cards"],0)
        self.assertEqual(out["GET_pair_attempts"],1)
        self.assertEqual(out["states"]["HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP"],1)
        self.assertFalse((self.cards/(RID+".json")).exists())

    def test_provider_denial_is_persisted_for_future_reruns(self):
        attempts=[]
        def deny(url):
            attempts.append(url)
            raise collector.SourceCaptureError(
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        first=self.collect(fetch=deny)
        self.assertEqual(first["GET_pair_attempts"],1)
        self.assertTrue((self.raw/"provider-denial-stop.json").exists())
        second=self.collect(fetch=deny)
        self.assertEqual(second["GET_pair_attempts"],0)
        self.assertEqual(len(attempts),1)
        self.assertEqual(
            second["states"]["HOLD_PROVIDER_PREVIOUS_DENIAL_NO_RETRY"],1)

    def test_early_midnight_JST_clock_not_wrong_UTC_day(self):
        x=manifest()
        x["races"][0]["cutoff_hint"]="2026-11-18T00:15:00+09:00"
        collector.manifest_check(x,registered_ids=[
            row["race_id"] for row in self.reg["records"]])

    def test_wrong_race_or_offsite_page_rejected_before_network(self):
        x=manifest()
        x["races"][0]["netkeirin_url"]="https://example.com/race?race_id="+RID
        with self.assertRaisesRegex(collector.SourceCaptureError,
                                    "UNAPPROVED_RACEPAGE"):
            self.collect(day_manifest=x)
        self.assertEqual(self.calls,[])

    def test_missing_cutoff_not_filled_from_start_or_newspaper(self):
        self.kd=self.kd.replace(b"20:45",b"")
        outcome=self.collect()
        self.assertEqual(outcome["normalized_private_cards"],0)
        self.assertIn("HOLD_KDREAMS_PUBLISHED_CUTOFF_CLOCK_MISSING",outcome["states"])
        self.assertFalse((self.cards/(RID+".json")).exists())

    def test_no_extra_races_beyond_budget(self):
        x=manifest()
        x["races"].append({
            "race_id":"202611182402",
            "netkeirin_url":"https://keirin.netkeiba.com/race/entry/?race_id=202611182402",
            "kdreams_url":"https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020002/",
            "cutoff_hint":"2026-11-18T21:05:00+09:00"})
        out=self.collect(day_manifest=x,max_races=1)
        self.assertEqual(out["GET_pair_attempts"],1)
        self.assertEqual(out["source_manifest_races"],2)
        self.assertEqual(out["states"]["HOLD_FETCH_BUDGET_NOT_YET_TRIED"],1)
        self.assertEqual(len(self.calls),2)

    def test_inconsistent_pre_captured_time_rejected(self):
        bad=manifest()
        bad["races"][0]["cutoff_hint"]="2026-11-19T21:00:00+09:00"
        with self.assertRaises(collector.SourceCaptureError):
            self.collect(day_manifest=bad)

    def test_manifest_invalid_duplicate_race_cannot_inflate(self):
        data=manifest()
        data["races"].append(dict(data["races"][0]))
        with self.assertRaisesRegex(collector.SourceCaptureError,
                                    "SOURCE_URL_RACE_NOT_IN_REGISTERED_DAY"):
            self.collect(day_manifest=data)


class OwnerApprovedPublicTransport(unittest.TestCase):
    """Only the existing four-host owner profile may reach real transport."""

    def test_excluded_or_unsafe_sources_rejected_before_request_or_opener(self):
        urls = [
            "https://keirin.kdreams.jp/kaisai/2030/01/15/",
            "https://keirin.netkeiba.com/race/entry/?race_id=203001152601",
            "https://keirin-mobile.jp/fixture",
            "https://example.invalid/fixture",
            "https://keirin.jp.attacker.invalid/fixture",
            "http://keirin.jp/fixture", "ftp://keirin.jp/fixture",
            "//keirin.jp/fixture", "https://user:password@keirin.jp/fixture",
            "https://@keirin.jp/fixture", "https://:@keirin.jp/fixture",
            "https://keirin.jp@attacker.invalid/fixture",
            "https://keirin.jp:444/fixture", "https://keirin.jp:bad/fixture",
            "https://keirin.jp:99999/fixture", "https://[invalid/fixture",
            None, b"https://keirin.jp/fixture", object(),
        ]
        for index, url in enumerate(urls):
            with self.subTest(case=index), \
                    patch.object(collector, "Request") as request, \
                    patch.object(collector, "build_opener") as opener:
                opener.return_value.open.side_effect = collector.SourceCaptureError(
                    "TRANSPORT_REACHED_BEFORE_OWNER_ADMISSION")
                with self.assertRaisesRegex(collector.SourceCaptureError,
                                            "^OWNER_APPROVED_SOURCE_HOST_REQUIRED$"):
                    collector.fetch_once(url)
                request.assert_not_called()
                opener.assert_not_called()

    def test_existing_source_session_four_host_profile_still_allows_normal_get(self):
        from scripts import keirin_cloud_owner_inputs as approved
        for host in ("winticket.jp", "www.winticket.jp", "keirin.jp", "www.keirin.jp"):
            for port in ("", ":443"):
                url = "https://" + host + port + "/fixture"
                with self.subTest(host=host, port=port), \
                        patch.object(approved, "nationwide_ab_selected", return_value=False), \
                        patch.object(collector, "build_opener") as opener:
                    session = approved.SourceSession(
                        lambda _: b"fixture", monotonic=lambda: 0, budget_seconds=60)
                    self.assertEqual(session(url), b"fixture")
                    response = opener.return_value.open.return_value
                    response.status = 200
                    response.geturl.return_value = url
                    response.headers = {"Content-Type": "text/html; charset=utf-8"}
                    response.read.return_value = b"fixture"
                    self.assertEqual(collector.fetch_once(url), b"fixture")
                    request = opener.return_value.open.call_args.args[0]
                    self.assertEqual(request.get_method(), "GET")
                    self.assertIsNone(request.get_header("Cookie"))
                    self.assertIsNone(request.get_header("Authorization"))
                    response.close.assert_called_once()

    def test_redirect_handler_never_constructs_a_request_to_an_excluded_target(self):
        with patch.object(collector, "Request") as request, \
                patch.object(collector, "build_opener") as opener:
            handler = collector.NoRedirect()
            for status in (301, 302, 303, 307, 308):
                self.assertIsNone(handler.redirect_request(
                    None, None, status, "fixture", {},
                    "https://keirin.kdreams.jp/fixture"))
            request.assert_not_called()
            opener.assert_not_called()

    def test_changed_response_url_stops_before_reading_source_body(self):
        with patch.object(collector, "build_opener") as opener:
            response = opener.return_value.open.return_value
            response.status = 200
            response.geturl.return_value = "https://keirin.kdreams.jp/fixture"
            response.headers = {"Content-Type": "text/html"}
            with self.assertRaisesRegex(collector.SourceCaptureError,
                                        "^PROVIDER_NON_HTML_OR_REDIRECT$"):
                collector.fetch_once("https://keirin.jp/fixture")
            opener.return_value.open.assert_called_once()
            response.read.assert_not_called()
            response.close.assert_called_once()

    def test_default_discovery_cannot_send_excluded_calendar_to_transport(self):
        from scripts import keirin_discover_public_race_links as discovery
        with patch.object(collector, "Request") as request, \
                patch.object(collector, "build_opener") as opener:
            opener.return_value.open.side_effect = collector.SourceCaptureError(
                "TRANSPORT_REACHED_BEFORE_OWNER_ADMISSION")
            with self.assertRaisesRegex(collector.SourceCaptureError,
                                        "^OWNER_APPROVED_SOURCE_HOST_REQUIRED$"):
                discovery.discover(day_jst="2030-01-15",
                                   registered_ids=["203001152601"])
            request.assert_not_called()
            opener.assert_not_called()

    def test_active_official_capture_success_cannot_reenter_excluded_secondary_source(self):
        from urllib.parse import parse_qs, urlsplit
        from race_ai import keirin_official_public_source as official
        from race_ai import keirin_official_run_history as history
        from scripts import keirin_github_only_ab_day as live
        from scripts import keirin_official_day_pipeline as pipeline
        from scripts import keirin_register_public_day as registration
        from tests.test_keirin_official_public_source import fixtures
        day = "2030-01-15"
        data = json.loads(json.dumps(fixtures()).replace("20261002", "20300115")
                          .replace("2026/10/02", "2030/01/15"))
        official_kinds = []

        def get_official(url):
            kind = parse_qs(urlsplit(url).query)["type"][0]
            official_kinds.append(kind)
            return json.dumps(data[kind]).encode("utf-8")

        clock = lambda: datetime.fromisoformat(day + "T08:00:00+00:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            public_path = root / "fixture-public.pem"
            public_path.write_bytes(b"fixture checked by the injected key boundary")
            private = root / "private"
            private.mkdir(mode=0o700)
            with patch.object(storage, "checked_public_key"), \
                    patch.object(live, "archived_day", return_value={}), \
                    patch.object(pipeline, "official_fetcher", return_value=get_official), \
                    patch.object(history, "read_revisions", return_value=[]), \
                    patch.object(pipeline, "persist_delta") as saved, \
                    patch.object(official, "fetch_day_schedule",
                                 wraps=official.fetch_day_schedule) as schedule, \
                    patch.object(registration, "register_day",
                                 wraps=registration.register_day) as register, \
                    patch.object(collector, "Request") as request, \
                    patch.object(collector, "build_opener") as opener:
                opener.return_value.open.side_effect = collector.SourceCaptureError(
                    "TRANSPORT_REACHED_BEFORE_OWNER_ADMISSION")
                with self.assertRaisesRegex(collector.SourceCaptureError,
                                            "^OWNER_APPROVED_SOURCE_HOST_REQUIRED$"):
                    pipeline.run_capture(day=day, repo=root, private_root=private,
                        owner_public_path=public_path, clock=clock)
                self.assertEqual(official_kinds, ["JSJ057", "JSJ017"])
                schedule.assert_called_once()
                register.assert_called_once()
                self.assertEqual(len(saved.call_args.kwargs["payload"]["schedule"]["races"]), 2)
                request.assert_not_called()
                opener.assert_not_called()


if __name__=="__main__":
    unittest.main()
