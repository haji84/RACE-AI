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
        self.assertIn("HOLD_SOURCE_PAGE_PARSING_OR_PROVENANCE_HOLD",outcome["states"])
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


if __name__=="__main__":
    unittest.main()
