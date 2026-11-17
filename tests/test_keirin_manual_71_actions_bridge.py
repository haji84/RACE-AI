"""Offline-only tests: all historical-looking riders/results below are fabricated."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from race_ai import keirin_manual_71_actions_bridge as pilot
from race_ai.keirin_manual_result_sync import canonical, SOURCE_SCHEMA


def stage_fake_cohort(root):
    private=root/"private"; private.mkdir()
    stage=root/"staged";stage.mkdir()
    ids=["75-07"] + [f"{code:02d}-{n:02d}" for code in range(11,18)
                       for n in range(1,11)]
    assert len(ids)==71 and len(set(ids))==71
    old={"date":"2026-11-17","ranked_races":[]}
    rows=[]
    for rid in ids:
        code, num=(int(i) for i in rid.split("-"))
        venue="架空会場"
        old["ranked_races"].append({"id":rid,"venue":venue,
            "start":"23:30","ranked_picks":[{"cars":[1,2,3]},
                                          {"cars":[7,2,1]}]})
        rows.append({"id":rid,"venue":venue,"start":"23:30","race":num,
            "v2_count":2,"v3_count":2,"new_candidate_ranks":[],
            "ranked_picks":[{"rank":1,"cars":[1,2,3]},
                            {"rank":2,"cars":[7,2,1]}]})
    old_raw=json.dumps(old).encode()
    (private/"baseline_v2.json").write_bytes(old_raw)
    source={"date":"2026-11-17","timezone":"Asia/Tokyo",
        "baseline_v2_sha256":sha256(old_raw).hexdigest(),
        "original_pre_race_snapshot_time":"2026-11-17T07:52:51+09:00",
        "baseline_v2_publication_time":"2026-11-17T08:42:31+09:00",
        "generated_at":"2026-11-17T09:06:03+09:00",
        "pre_race_rank_1_changed":False,"races":rows}
    original=json.dumps(source).encode()
    (private/"forecast_v3.json").write_bytes(original)
    html="<html><head></head><body>"+"".join(
         f'<article id="r{rid}" data-kind="solid">予想</article>'
         for rid in ids)+"</body></html>"
    (private/"categories.html").write_text(html)
    (private/"template.html").write_text(html)
    obs={"schema":SOURCE_SCHEMA,"race_id":"202611177507",
        "source_url":"https://example.invalid/SYNTHETIC-ONLY",
        "rights_ref":"SYNTHETIC_NO_REAL_PROVIDER_RIGHTS",
        "source_published_at":"2026-11-17T11:00:00+09:00",
        "observed_at":"2026-11-17T11:01:00+09:00",
        "provider_revision_ref":"fictional-revision-1",
        "status":"FINAL_NORMAL","refund_status":"NONE",
        "winning_triples":[[7,2,1]],
        "payouts_100yen":[{"triple":[7,2,1],"yen":390}]}
    raw=canonical(obs)
    (stage/(sha256(raw).hexdigest()+".json")).write_bytes(raw)
    return private,stage,sha256(original).hexdigest()


class PilotBridgeTest(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root=Path(self.scratch.name)
        self.repo=Path(__file__).resolve().parents[1]
        self.dbfile=self.root/"sealed-before-AES.sqlite3"
        self.db=sqlite3.connect(self.dbfile)
        self.addCleanup(self.db.close)
        self.private,self.staged,self.source_sha=stage_fake_cohort(self.root)

    def test_no_private_snapshot_fails_closed_without_modifying_db(self):
        got=pilot.attempt_one_race(db=self.db,repo=self.repo,
                                  source_dir=None,result_dir=str(self.staged))
        self.assertEqual(got["new_audits"],0)
        self.assertEqual(pilot.verify_private_archive(self.db)["verified_rows"],0)

    def test_one_candidate_stored_once_then_independent_sqlite_readback(self):
        with patch.object(pilot,"PINNED_V3_SHA256",self.source_sha):
            for expected in (1,0):
                got=pilot.attempt_one_race(
                    db=self.db,repo=self.repo,source_dir=str(self.private),
                    result_dir=str(self.staged),
                    observed_at="2026-11-17T11:30:00+09:00")
                self.assertEqual(got["new_audits"],expected)
                self.assertFalse(got["official_results_authenticated"])
                self.assertFalse(got["public_html_published"])
            self.assertEqual(pilot.verify_private_archive(self.db)["verified_rows"],1)
            self.db.commit()
            with sqlite3.connect(self.dbfile) as new_process:
                self.assertEqual(
                    pilot.verify_private_archive(new_process)["verified_rows"],1)
                row=new_process.execute(
                    f"SELECT report_json,private_html FROM {pilot.TABLE}").fetchone()
                report=json.loads(row[0])
                first=next(r for r in report["rows"] if r["race_id"]=="75-07")
                self.assertFalse(report["official_results_authenticated"])
                self.assertEqual(first["reference_comparison"]["expanded"]["hit_ranks"],[2])
                self.assertIn(b'keirin-auto-result',row[1])

    def test_tampering_verified_private_receipt_is_detected(self):
        with patch.object(pilot,"PINNED_V3_SHA256",self.source_sha):
            pilot.attempt_one_race(db=self.db,repo=self.repo,
                source_dir=str(self.private),result_dir=str(self.staged),
                observed_at="2026-11-17T11:30:00+09:00")
            self.db.execute(f"UPDATE {pilot.TABLE} SET private_html=?", (b'broken',))
            self.db.commit()
            with self.assertRaisesRegex(pilot.PilotError,"TAMPERED"):
                pilot.verify_private_archive(self.db)

    def test_public_repo_input_forbidden(self):
        with patch.object(pilot,"PINNED_V3_SHA256",self.source_sha):
            with self.assertRaisesRegex(pilot.PilotError, "PUBLIC_REPOSITORY"):
                pilot._private_root(str(self.repo),self.repo)


if __name__=="__main__":
    unittest.main()
