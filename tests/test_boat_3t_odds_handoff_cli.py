"""Offline CLI tests: synthetic HTML plus synthetic, HMAC-signed policy."""
from datetime import datetime
import contextlib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_3t_odds_handoff_cli import main
from race_ai.comprehensive_four_sport_models import digest
from tests.test_boat_official_3t_odds_adapter import (
    SOURCE,RACE,CUTOFF,html
)
from tests.test_permissioned_source_delivery import KEY, AT, policy_doc


def signed():
    doc=policy_doc()
    doc["policy"]["grants"].append({
        "source_ref":SOURCE,
        "rights_ref":"synthetic-fictional-odds-approval",
        "transport_url":SOURCE,
        "purposes":["analysis","private_storage","private_derived","odds_display"],
        "evidence_url":"https://example.org/fictional/odds-policy",
        "reviewer":"FICTIONAL_TEST_ONLY",
        "checked_at":"2030-01-10T00:00:00+09:00",
        "expires_at":"2030-02-01T00:00:00+09:00",
        "max_bytes":2000000,"max_requests":1,"max_cost_jpy":0
    })
    doc["signature"]=hmac.new(KEY,digest(doc["policy"]).encode("ascii"),
                              hashlib.sha256).hexdigest()
    return doc


class OddsOfflineCliTests(unittest.TestCase):
    def test_handoff_exclusive_private_json_and_no_automatic_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            src=folder/"fictional-odds.html"
            src.write_bytes(html())
            policy=folder/"fictional-signed-policy.json"
            policy.write_text(json.dumps(signed()))
            dest=folder/"private-odds.json"
            args=["--html-file",str(src),"--policy",str(policy),
                  "--source-url",SOURCE,"--rights-ref","synthetic-fictional-odds-approval",
                  "--race-id",RACE,"--venue","架空場","--official-cutoff",CUTOFF,
                  "--output",str(dest)]
            env={"RACE_AI_SOURCE_REVIEW_KEY":KEY.decode()}
            with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()) as output:
                result=main(args,clock=datetime.fromisoformat(AT))
            self.assertEqual(result,0)
            self.assertTrue(dest.is_file())
            data=json.loads(dest.read_text())
            self.assertEqual(len(data["odds"]),120)
            self.assertIsNone(data["source_published_at"])
            self.assertEqual(data["source_status"],"PROVIDER_REPORTED_UNVERIFIED")
            self.assertFalse("official_prediction" in data)
            self.assertFalse("prediction" in data)
            self.assertFalse("result" in data)
            self.assertIn("SOURCE_TIME_UNVERIFIED",output.getvalue())
            with patch.dict(os.environ,env),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args,clock=datetime.fromisoformat(AT)),2)

    def test_no_source_key_refuses_to_write(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            src=folder/"test.html";src.write_bytes(html())
            policy=folder/"policy.json";policy.write_text(json.dumps(signed()))
            dest=folder/"no-data.json"
            args=["--html-file",str(src),"--policy",str(policy),
                  "--source-url",SOURCE,"--rights-ref","synthetic-fictional-odds-approval",
                  "--race-id",RACE,"--venue","架空場","--official-cutoff",CUTOFF,
                  "--output",str(dest)]
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":""}):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args,clock=datetime.fromisoformat(AT)),2)
            self.assertFalse(dest.exists())


if __name__=="__main__":
    unittest.main()
