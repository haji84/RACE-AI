"""Standalone owner personal runner CLI and pre-race source admission tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.keirin_result_delivery import canonical
from scripts.keirin_private_agent import (
    PERSONAL_MARKER, main, source_ref_allowed, personal_certificate
)


class OwnerPersonalRunnerTests(unittest.TestCase):
    def test_source_identity_allowlist_rejects_forged_hosts(self):
        self.assertTrue(source_ref_allowed(
            "https://keirin.kdreams.jp/odawara/racedetail/abc",
            PERSONAL_MARKER,"analysis"))
        self.assertTrue(source_ref_allowed(
            "https://keirin.netkeiba.com/race/entry/?race_id=202611033601",
            PERSONAL_MARKER,"analysis"))
        self.assertFalse(source_ref_allowed(
            "https://keirin.kdreams.jp.attacker.invalid/valid",
            PERSONAL_MARKER,"analysis"))
        self.assertFalse(source_ref_allowed(
            "https://keirin.kdreams.jp@evil.example/path",
            PERSONAL_MARKER,"analysis"))
        self.assertFalse(source_ref_allowed(
            "http://keirin.kdreams.jp/path",
            PERSONAL_MARKER,"analysis"))
        self.assertFalse(source_ref_allowed(
            "https://keirin.kdreams.jp/path",PERSONAL_MARKER,"wager"))
        self.assertFalse(source_ref_allowed(
            "https://keirin.kdreams.jp/path","INVENTED_LICENSE","analysis"))

    def test_certificate_remains_personal_self_attested_not_official(self):
        now=datetime.now(timezone.utc)
        day=now.isoformat()
        limit=(now+timedelta(minutes=10)).isoformat()
        snapshot={
            "race_id":"keirin:2030-01-15:fictional-venue:1",
            "as_of":day,
            "permission_ref":PERSONAL_MARKER,
            "facts":{"pr71_evidenced_snapshot":{
                "scope":"OPERATOR_SUPPLIED_RESEARCH",
                "race":{"race_id":"keirin:2030-01-15:fictional-venue:1"}
            }}
        }
        hashval=sha256(canonical(snapshot)).hexdigest()
        intent={
            "race_id":snapshot["race_id"],
            "official_cutoff_at":limit,
            "pre_race_snapshot_sha256":hashval,
        }
        value=personal_certificate(snapshot,intent)
        self.assertEqual(value["source_sha256"],hashval)
        self.assertEqual(value["permission_ref"],PERSONAL_MARKER)
        snap2={**snapshot,"permission_ref":"UNVERIFIED"}
        self.assertIsNone(personal_certificate(snap2,intent))
        self.assertIsNone(personal_certificate(
            snapshot,{**intent,"pre_race_snapshot_sha256":"0"*64}))

    def test_absolute_private_directory_no_sources_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"private.sqlite3"
            inbox=Path(d)/"inbox"
            inbox.mkdir()
            buf=StringIO()
            with redirect_stdout(buf),patch.dict(os.environ,{"GITHUB_ACTIONS":""}):
                code=main(["--db",str(db),"--inbox",str(inbox),"--personal-only"])
            self.assertEqual(code,0)
            self.assertTrue(db.exists())
            self.assertIn('"private_forecasts_saved_this_tick": 0',buf.getvalue())
            self.assertIn('"provider_network_requests": 0',buf.getvalue())

    def test_reject_ephemeral_public_github_runner(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"db.sqlite3"
            inbox=Path(d)/"inbox"
            inbox.mkdir()
            with redirect_stdout(StringIO()),patch.dict(os.environ,{
                    "GITHUB_ACTIONS":"true",
                    "RACE_AI_PERSISTENT_PRIVATE_VOLUME":""
                }):
                code=main(["--db",str(db),"--inbox",str(inbox),"--personal-only"])
            self.assertEqual(code,2)
            self.assertFalse(db.exists())

    def test_rate_guard(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--db","/tmp/private.db",
                "--inbox","/tmp/inbox","--personal-only",
                "--interval-seconds","15"]),2)


if __name__=="__main__":
    unittest.main()
