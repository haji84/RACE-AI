"""Permissioned transport -> existing four-sport model suite contract tests.

All races, participants and rights records below are FICTIONAL. No external
provider calls, real grants, or live forecasts are represented.
"""
import contextlib
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_comprehensive_four_sport_models import sample
from race_ai.comprehensive_four_sport_models import RESEARCH, digest
from race_ai.permissioned_source_delivery import (
    POLICY_SCHEMA, FEED_SCHEMA, DELIVERY_SCHEMA, PermissionPolicy,
    SourceDeliveryError, bounded_fetch, deliver, main,
    read_json_bytes, _private_write, _https,
)

KEY=b"fictional-reviewer-secret-for-synthetic-contract-only-12345"
SRC="https://example.org/fictional/races/2030-01-15.json"
EVIDENCE="https://example.org/fictional/rights/approval-not-real"
AT="2030-01-15T09:15:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"


def policy_doc(purposes=None, *, url=SRC, expiry="2030-02-01T00:00:00+09:00"):
    grant={
        "source_ref":SRC,"rights_ref":"fictional-permission-1",
        "transport_url":url,
        "purposes":purposes or ["collection","analysis","private_storage","private_derived"],
        "evidence_url":EVIDENCE,"reviewer":"FICTIONAL_REVIEWER_FOR_TESTS",
        "checked_at":"2030-01-10T00:00:00+09:00",
        "expires_at":expiry,"max_bytes":2000000,
        "max_requests":1,"max_cost_jpy":0
    }
    policy={"authority":"SYNTHETIC_CONTRACT_TEST","grants":[grant]}
    sig=hmac.new(KEY,digest(policy).encode("ascii"),hashlib.sha256).hexdigest()
    return {"schema":POLICY_SCHEMA,"policy":policy,"signature":sig}


def snapshot(sport):
    s=sample(sport,scope=RESEARCH)
    for participant in s["participants"]:
        for observation in participant["features"].values():
            observation["source_ref"]=SRC
            observation["source_rights_ref"]="fictional-permission-1"
    for observation in s["environment"].values():
        observation["source_ref"]=SRC
        observation["source_rights_ref"]="fictional-permission-1"
    return s


def raw_feed(sport):
    return json.dumps({"schema":FEED_SCHEMA,"snapshot":snapshot(sport)},
                      sort_keys=True,separators=(",",":")).encode()


def gate(doc=None, *, at=AT):
    return PermissionPolicy(doc or policy_doc(),KEY,at=at)


class DummyResponse:
    def __init__(self,data,url=SRC,kind="application/json",status=200):
        self.data=data
        self.url=url
        self.status=status
        self.headers={"Content-Type":kind}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.data[:n]


class DummyOpener:
    def __init__(self,response):
        self.response=response
        self.calls=0
    def open(self,req,timeout=None):
        self.calls+=1
        return self.response


class DeliveryTests(unittest.TestCase):
    def test_real_like_input_reaches_all_four_sport_research_models(self):
        for sport,n in (("boat",6),("keirin",7),("autorace",8),("horse",18)):
            with self.subTest(sport=sport):
                raw=raw_feed(sport)
                output=deliver(raw,gate(),at=AT)
                self.assertEqual(output["schema"],DELIVERY_SCHEMA)
                self.assertEqual(output["source_payload_sha256"],hashlib.sha256(raw).hexdigest())
                self.assertEqual(output["feature_snapshot_sha256"],digest(snapshot(sport)))
                self.assertEqual(output["research_suite"]["model_count"],4)
                for model in output["research_suite"]["models"].values():
                    self.assertEqual(model["candidate_count"],n*(n-1)*(n-2))
                    self.assertEqual(len(model["ordered_top8"]),8)
                    self.assertFalse(model["official_prediction"])
                    self.assertTrue(model["odds_independent"])
                self.assertFalse(output["can_count_in_hit_at_8"])
                self.assertIsNone(output["external_receipt"])
                self.assertEqual(output["status"],"PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN")

    def test_reject_missing_key_invalid_signature_expired_and_paid_grants(self):
        with self.assertRaises(SourceDeliveryError):
            PermissionPolicy(policy_doc(),b"",at=AT)
        bad=policy_doc()
        bad["policy"]["grants"][0]["source_ref"]="https://different.example/forged"
        with self.assertRaisesRegex(SourceDeliveryError,"signature"):
            gate(bad)
        with self.assertRaisesRegex(SourceDeliveryError,"currently effective"):
            gate(policy_doc(expiry="2030-01-14T00:00:00+09:00"))
        paid=policy_doc()
        paid["policy"]["grants"][0]["max_cost_jpy"]=1
        paid["signature"]=hmac.new(KEY,digest(paid["policy"]).encode("ascii"),
                                  hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(SourceDeliveryError,"paid source"):
            gate(paid)

    def test_reject_unapproved_analysis_storage_and_unknown_source(self):
        for restricted in (["collection","private_storage","private_derived"],
                           ["collection","analysis","private_derived"],
                           ["collection","analysis","private_storage"]):
            with self.subTest(restricted=restricted):
                with self.assertRaises(SourceDeliveryError):
                    deliver(raw_feed("boat"),gate(policy_doc(restricted)),at=AT)
        row=json.loads(raw_feed("boat"))
        row["snapshot"]["participants"][0]["features"]["ability"]["source_ref"]="https://unknown.example/data"
        with self.assertRaisesRegex(SourceDeliveryError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            deliver(json.dumps(row).encode(),gate(),at=AT)

    def test_cutoff_and_future_time_are_enforced(self):
        with self.assertRaisesRegex(SourceDeliveryError,"MISSED_DEADLINE"):
            deliver(raw_feed("boat"),gate(at="2030-01-15T10:00:00+09:00"),
                    at="2030-01-15T10:00:00+09:00")
        with self.assertRaisesRegex(SourceDeliveryError,"MISSED_DEADLINE"):
            deliver(raw_feed("boat"),gate(at="2030-01-15T09:00:00+09:00"),
                    at="2030-01-15T09:00:00+09:00")

    def test_market_fields_duplicate_keys_and_results_are_rejected(self):
        self.assertRaises(SourceDeliveryError,read_json_bytes,b'{"a":1,"a":2}')
        for name in ("odds","payout_yen","popularity","race_result","actual_finish"):
            row=json.loads(raw_feed("boat"))
            row["snapshot"]["participants"][0][name]=9
            with self.subTest(name=name):
                with self.assertRaisesRegex(SourceDeliveryError,"market or result"):
                    deliver(json.dumps(row).encode(),gate(),at=AT)

    def test_bounded_approved_fetch_and_budget(self):
        o=DummyOpener(DummyResponse(raw_feed("boat")))
        p=gate()
        received=bounded_fetch(SRC,p,opener=o)
        self.assertEqual(received,raw_feed("boat"))
        self.assertEqual(o.calls,1)
        with self.assertRaisesRegex(SourceDeliveryError,"budget"):
            bounded_fetch(SRC,p,opener=o)
        self.assertEqual(o.calls,1)
        with self.assertRaisesRegex(SourceDeliveryError,"collection not approved"):
            bounded_fetch("https://another.example/other.json",gate(),opener=o)
        self.assertEqual(o.calls,1)

    def test_no_redirect_non_json_or_too_large(self):
        for response in (
            DummyResponse(b"{}",url="https://evil.example/redirect"),
            DummyResponse(b"{}",kind="text/html"),
            DummyResponse(b"x"*2000001),
        ):
            with self.subTest(response=response.url):
                with self.assertRaises(SourceDeliveryError):
                    bounded_fetch(SRC,gate(),opener=DummyOpener(response))

    def test_ssrf_limited_to_public_exact_https_domain(self):
        for url in ("http://example.org/a","https://127.0.0.1/a",
                    "https://localhost/a","https://10.2.3.4/a",
                    "https://example.org:8443/a",
                    "https://user:pass@example.org/a",
                    "https://admin.internal/a"):
            with self.subTest(url=url):
                with self.assertRaises(SourceDeliveryError):
                    _https(url)
        self.assertEqual(_https(SRC),SRC)

    def test_private_output_is_exclusive_and_permissions_restrictive(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"fixture-delivery.json"
            record=deliver(raw_feed("boat"),gate(),at=AT)
            _private_write(path,record)
            self.assertEqual(json.loads(path.read_text())["delivery_sha256"],record["delivery_sha256"])
            self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
            with self.assertRaisesRegex(SourceDeliveryError,"already exists"):
                _private_write(path,record)
            git=Path(t)/"checkout"
            git.mkdir()
            (git/".git").mkdir()
            with self.assertRaisesRegex(SourceDeliveryError,"Git repository"):
                _private_write(git/"secret.json",record)

    def test_command_line_blocked_without_real_secret(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            (p/"policy.json").write_text(json.dumps(policy_doc()),encoding="utf-8")
            (p/"feed.json").write_bytes(raw_feed("boat"))
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":""}):
                with contextlib.redirect_stderr(io.StringIO()) as out:
                    code=main(["--policy",str(p/"policy.json"),
                               "--file",str(p/"feed.json"),
                               "--output",str(p/"not-written.json")])
            self.assertEqual(code,2)
            self.assertIn("BLOCKED",out.getvalue())
            self.assertFalse((p/"not-written.json").exists())

    def test_document_cannot_use_self_declared_permission(self):
        feed=json.loads(raw_feed("boat"))
        feed["rights_approved"]=True
        with self.assertRaisesRegex(SourceDeliveryError,"unsupported normalized source feed"):
            deliver(json.dumps(feed).encode(),gate(),at=AT)


if __name__ == "__main__":
    unittest.main()
