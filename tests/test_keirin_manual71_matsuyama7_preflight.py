"""Synthetic one-race preflight contracts. No provider GET or owner secrets."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import keirin_manual71_matsuyama7_preflight as m


def fake_row():
    return {
        "schema":"RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1",
        "source_kind":"THIRD_PARTY_NOT_KEIRIN_JP",
        "source_url":m.legacy_page_url("20261117",75,7),
        "source_sha256":"a"*64,
        "captured_at_unattested":"2026-11-17T11:00:00+09:00",
        "page_date_marker":True,"page_race_marker":True,
        "result_officially_authenticated":False,
        "machine_collection_rights_verified":False,
        "raw_page_stored":False,
        "candidate_result":{
            "state":"ONE_UNVERIFIED_PROVIDER_CANDIDATE",
            "triple":[7,2,1],"payout_100yen":390,
        }
    }


def trusted():
    return {
        "GITHUB_ACTIONS":"true",
        "GITHUB_REPOSITORY":"haji84/RACE-AI",
        "GITHUB_REPOSITORY_ID":"1416489937",
        "GITHUB_REF":"refs/heads/main",
        "GITHUB_EVENT_NAME":"workflow_dispatch",
        "RACE_AI_KEIRIN_PRIVATE_RSA_PEM":"synthetic-no-real-secret",
    }


class OneRealRaceGate(unittest.TestCase):
    def test_wrong_branch_no_secret_or_schedule_never_fetches(self):
        with TemporaryDirectory() as temp:
            for env in [
                {**trusted(),"GITHUB_REF":"refs/heads/pr/12"},
                {k:v for k,v in trusted().items() if k!="RACE_AI_KEIRIN_PRIVATE_RSA_PEM"},
                {**trusted(),"GITHUB_EVENT_NAME":"schedule"},
            ]:
                requests=[]
                r=m.execute(env=env,workspace=temp,helper=temp,
                            runner_temp=temp,fetch_one=lambda *a,**k:requests.append(a))
                self.assertEqual(requests,[])
                self.assertEqual(r["source_attempts"],0)
                self.assertFalse(r["all_five_stages_passed"])
                self.assertFalse(r["71_race_rollout_allowed"])

    def test_real_owner_originals_are_sha_pinned_before_comparing(self):
        fake={"date":m.DATE,"races":[]}
        for i in range(71):
            fake["races"].append({
                "id":m.SHORT_ID if i==4 else f"{i//11+11:02d}-{i%11+1:02d}",
                "venue":"松山" if i==4 else "架空",
                "race":7 if i==4 else i%11+1,
                "ranked_picks":[{"rank":1,"cars":[7,2,1]},
                                {"rank":2,"cars":[2,7,1]}]})
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=json.dumps(fake).encode()
            (root/"forecast_v3.json").write_bytes(raw)
            with patch.object(m,"FORECAST_SHA",sha256(raw).hexdigest()):
                got=m.parse_forecast(root)
                self.assertIn((7,2,1),got)
            with self.assertRaisesRegex(m.PilotHold,"SHA_MISMATCH"):
                m.parse_forecast(root)

    def test_single_exact_source_result_is_provisional_even_if_matching(self):
        picks={(7,2,1),(2,7,1)}
        state,hit=m.classify_one_result(fake_row(),picks)
        self.assertEqual(state,"THIRD_PARTY_PROVISIONAL_RESULT_JOINED")
        self.assertTrue(hit)
        state,hit=m.classify_one_result(fake_row(),{(1,2,7)})
        self.assertEqual(state,"THIRD_PARTY_PROVISIONAL_RESULT_JOINED")
        self.assertFalse(hit)

    def test_unverified_provenance_or_wrong_race_rejected(self):
        obs=fake_row()
        for field,value in [
            ("source_url","https://other.example.invalid"),
            ("result_officially_authenticated",True),
            ("machine_collection_rights_verified",True),
            ("page_date_marker",False),
            ("page_race_marker",False),
            ("source_sha256","definitely not a SHA"),
        ]:
            temp=dict(obs,**{field:value})
            status,hit=m.classify_one_result(temp,{(7,2,1)})
            self.assertEqual(status,"SOURCE_RACE_OR_PROVENANCE_HOLD")
            self.assertFalse(hit)

    def test_source_unconfirmed_is_not_a_loss(self):
        obs=fake_row()
        obs["candidate_result"]={"state":"NO_UNAMBIGUOUS_TRIFECTA",
                                  "triple":None,"payout_100yen":None}
        state,hit=m.classify_one_result(obs,{(7,2,1)})
        self.assertEqual(state,"SOURCE_NO_UNAMBIGUOUS_RESULT")
        self.assertFalse(hit)

    def test_private_main_probe_never_claims_official_or_browser(self):
        with TemporaryDirectory() as td:
            request=[]
            def fake_fetch(*args,**kwargs):
                request.append((args,kwargs))
                return fake_row()
            with patch.object(m,"restore_existing_owner_bundle",
                              return_value={"state":"OWNER_MANUAL71_PRIVATE_SOURCE_STAGED",
                                            "source_files":4}),patch.object(
                              m,"parse_forecast",return_value={(7,2,1)}):
                out=m.execute(env=trusted(),workspace=td,helper=td,
                              runner_temp=td,fetch_one=fake_fetch)
            self.assertEqual(len(request),1)
            self.assertEqual(request[0][0],("20261117",75,7))
            self.assertEqual(request[0][1]["route"],"legacy")
            self.assertEqual(out["private_decryption"],"REAL_ORIGINAL_SHA_RESTORED")
            self.assertEqual(out["source_check"],"THIRD_PARTY_PROVISIONAL_RESULT_JOINED")
            self.assertEqual(out["third_party_source_sha256"],"a"*64)
            self.assertFalse(out["official_result_authenticated"])
            self.assertFalse(out["independent_A_E_S_readback"])
            self.assertFalse(out["owner_html_browser_verified"])
            self.assertFalse(out["all_five_stages_passed"])

    def test_provider_exception_is_one_attempt_without_retry(self):
        with TemporaryDirectory() as td:
            counter=[]
            def failed(*a,**k):
                counter.append(1)
                raise m.MobileProbeError("PROVIDER_HTTP_403")
            with patch.object(m,"restore_existing_owner_bundle",
                              return_value={"state":"OWNER_MANUAL71_PRIVATE_SOURCE_STAGED",
                                            "source_files":4}),patch.object(
                              m,"parse_forecast",return_value={(7,2,1)}):
                out=m.execute(env=trusted(),workspace=td,helper=td,
                              runner_temp=td,fetch_one=failed)
            self.assertEqual(len(counter),1)
            self.assertEqual(out["source_check"],"SOURCE_GET_FAILED_NO_RETRY")
            self.assertEqual(out["source_attempts"],1)
            self.assertFalse(out["all_five_stages_passed"])


if __name__=="__main__":
    unittest.main()
