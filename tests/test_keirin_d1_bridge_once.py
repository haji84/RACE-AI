"""No network, synthetic OIDC handoff request test."""
from __future__ import annotations
from io import BytesIO
import json
import unittest

from scripts.keirin_d1_bridge_once import (
    BridgeError, submit_day, get_github_oidc_token
)

DAY="2026-11-03"
SHA="a"*64

class Response:
    def __init__(self,body,url,status=200):
        self.data=body
        self.url=url
        self.status=status
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.data[:n]
    def geturl(self):return self.url

class TestBridge(unittest.TestCase):
    def sample(self,day):
        return {"source_sha256":SHA,
            "races":[
                {"race_id":"202611033601","venue_code":36,"race_no":1},
                {"race_id":"202611033602","venue_code":36,"race_no":2},
            ]}
    def test_oidc_not_available_in_untrusted_branch(self):
        with self.assertRaisesRegex(BridgeError,"UNTRUSTED_ACTIONS_ORIGIN"):
            get_github_oidc_token(env={
                "GITHUB_REPOSITORY":"attacker/repo",
                "GITHUB_REF":"refs/heads/main",
                "GITHUB_EVENT_NAME":"push",
            },open_url=lambda *_a,**_k:self.fail("should not network"))
    def test_oidc_not_requested_during_pull_request(self):
        with self.assertRaises(BridgeError):
            get_github_oidc_token(env={
                "GITHUB_REPOSITORY":"haji84/RACE-AI",
                "GITHUB_REF":"refs/pull/123/merge",
                "GITHUB_EVENT_NAME":"pull_request",
            },open_url=lambda *_a,**_k:self.fail("should not network"))
    def test_submit_real_roster_shape_through_mock_private_ack(self):
        recorded=[]
        def client(req,timeout):
            body=json.loads(req.data.decode())
            recorded.append(body)
            self.assertEqual(req.get_header("Authorization"),"Bearer xxx.yyy.zzz")
            self.assertEqual(body["races"][0]["race_id"],"202611033601")
            ack={"schema":"RACE_AI_KEIRIN_PRIVATE_COHORT_ACK_V1",
                 "event_date_jst":DAY,
                 "submitted_races":2,"saved_races_for_day":2,
                 "private_forecasts_exposed":False}
            return Response(json.dumps(ack).encode(),req.full_url)
        out=submit_day(event_day=DAY,collector=self.sample,
            token_provider=lambda:"xxx.yyy.zzz",open_url=client)
        self.assertEqual(out["submitted"],2)
        self.assertEqual(out["stored_at_least"],2)
        self.assertIsNone(out["formal_hit_at_8_all"])
        self.assertFalse(out["original_forecasts_sent"])
        self.assertEqual(len(recorded),1)
    def test_source_incomplete_never_requests_token(self):
        def invalid(_):
            return {"source_sha256":SHA,"races":[]}
        with self.assertRaisesRegex(BridgeError,"INCOMPLETE_DAY_DISCOVERY"):
            submit_day(event_day=DAY,collector=invalid,
                token_provider=lambda:self.fail("must not request token"))
    def test_ack_tamper_refused(self):
        def failing(req,timeout):
            ack={"schema":"RACE_AI_KEIRIN_PRIVATE_COHORT_ACK_V1",
                 "event_date_jst":DAY,
                 "submitted_races":1,"saved_races_for_day":1,
                 "private_forecasts_exposed":False}
            return Response(json.dumps(ack).encode(),req.full_url)
        with self.assertRaisesRegex(BridgeError,"CLOUDFLARE_PRIVATE_READBACK_INVALID"):
            submit_day(event_day=DAY,collector=self.sample,
                token_provider=lambda:"xxx.yyy.zzz",open_url=failing)


if __name__=="__main__":unittest.main()
