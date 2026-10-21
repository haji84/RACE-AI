import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import ContractError, canonical, digest, forecast, validate_snapshot
from race_ai.actions_store import SyntheticJournal
from race_ai.synthetic_e2e import fixture, run_e2e, permission_fetch, evaluate

class Clock:
    def __init__(self, value="2030-01-01T00:30:00+00:00"):
        self.value = datetime.fromisoformat(value)
    def __call__(self):
        return self.value

class FourSportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "journal.sqlite"
        self.clock = Clock()
        self.store = SyntheticJournal(self.path, self.clock)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def save(self, snapshot=None):
        s = snapshot or fixture("boat", 6)
        self.store.discover(s)
        return self.store.freeze(s, forecast(s), run_id="synthetic-run")

    def test_four_sports_full_universe_and_top8(self):
        for sport, n, count in [("boat",6,120),("keirin",7,210),("keirin",9,504),("autorace",8,336),("horse",18,4896)]:
            s = fixture(sport,n)
            f = forecast(s)
            self.assertEqual(len(f["candidates"]),count)
            self.assertEqual(len({tuple(x["combination"]) for x in f["candidates"]}),count)
            self.assertAlmostEqual(sum(x["score"] for x in f["candidates"]),1)
            self.assertEqual(len(f["ordered_top8"]),8)
            self.assertEqual(f["validation_status"],"UNVALIDATED")
            self.assertFalse(f["official_prediction"])

    def test_boat_extracted_kernel_parity(self):
        from race_ai.legacy_boat_rank import plackett_luce
        s=fixture("boat",6)
        expected=plackett_luce({r["participant"]:r["features"]["historical_rating"] for r in s["participants"]})["triples"]
        actual=forecast(s)["candidates"]
        self.assertEqual({tuple(r["combination"]):r["probability"] for r in expected},
                         {tuple(r["combination"]):r["score"] for r in actual})

    def test_market_fields_rejected_at_every_feature_boundary(self):
        for key in ["odds","popularity","payout","market_implied_win_probability","third_party_prediction","result"]:
            s=fixture("boat",6)
            s["participants"][0]["features"][key]=1
            s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
            with self.assertRaises(ContractError):
                forecast(s)

    def test_changed_market_sidecar_cannot_change_prediction_bytes(self):
        a=run_e2e(Path(self.tmp.name)/"a.sqlite",market_sidecar={"odds":[1,2],"popularity":1})
        b=run_e2e(Path(self.tmp.name)/"b.sqlite",market_sidecar={"odds":[999,0],"payout":999999})
        self.assertEqual(a["prediction_hashes"],b["prediction_hashes"])

    def test_late_freeze_and_rollback_rejected(self):
        s=fixture("boat",6)
        self.store.discover(s)
        self.clock.value=datetime.fromisoformat(s["sales_cutoff_at"])
        with self.assertRaisesRegex(ContractError,"cutoff"):
            self.store.freeze(s,forecast(s),run_id="late")
        self.clock.value=datetime.fromisoformat(s["sales_cutoff_at"])-timedelta(hours=2)
        with self.assertRaisesRegex(ContractError,"clock"):
            self.store.discover(fixture("keirin",7))

    def test_cutoff_not_start_and_commit_clock_rechecked(self):
        s=fixture("boat",6)
        self.store.discover(s)
        before=datetime.fromisoformat(s["sales_cutoff_at"])-timedelta(seconds=1)
        after=before+timedelta(seconds=2)
        self.store.clock=iter([before,after]).__next__
        with self.assertRaises(ContractError):
            self.store.freeze(s,forecast(s),run_id="crossed")
        self.assertEqual(len(self.store.events("freeze")),0)

    def test_hash_input_and_forecast_tamper(self):
        s=fixture("boat",6)
        s["participants"][0]["features"]["historical_rating"]=900
        with self.assertRaises(ContractError): forecast(s)
        s=fixture("boat",6)
        self.store.discover(s)
        f=forecast(s)
        f["ordered_top8"].reverse()
        with self.assertRaises(ContractError): self.store.freeze(s,f,run_id="tamper")

    def test_no_backdating_or_future_features(self):
        s=fixture("boat",6)
        s["source"]["available_at"]=s["scheduled_start_at"]
        s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
        with self.assertRaises(ContractError): forecast(s)

    def test_retries_reopen_backup_and_immutable_triggers(self):
        receipt=self.save()
        self.assertEqual(receipt,self.save())
        self.assertEqual(len(self.store.events("freeze")),1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE events SET body='{}'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("DELETE FROM events")
        backup=Path(self.tmp.name)/"backup.sqlite"
        self.store.backup(backup)
        restored=SyntheticJournal(backup,self.clock)
        self.assertEqual(restored.verify(),self.store.verify())
        restored.close()
        self.store.close()
        self.store=SyntheticJournal(self.path,self.clock)
        self.assertEqual(self.store.freeze(fixture("boat",6),forecast(fixture("boat",6)),run_id="retry"),receipt)

    def test_crash_before_commit_rolls_back_and_retries(self):
        s=fixture("boat",6)
        self.store.discover(s)
        with patch.object(self.store,"_before_commit",side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError): self.store.freeze(s,forecast(s),run_id="crash")
        self.assertEqual(len(self.store.events("freeze")),0)
        self.save()
        self.assertEqual(len(self.store.events("freeze")),1)

    def test_conflicting_retry_and_leases(self):
        self.store.claim("race","run-a",60)
        other=SyntheticJournal(self.path,self.clock)
        try:
            with self.assertRaises(ContractError): other.claim("race","run-b",60)
            self.clock.value+=timedelta(seconds=61)
            other.claim("race","run-b",60)
        finally: other.close()
        self.save()
        s=fixture("boat",6)
        s["participants"][0]["features"]["historical_rating"]=20
        s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
        with self.assertRaises(ContractError): self.store.discover(s)

    def test_reschedule_cancel_and_stale_revision(self):
        s=fixture("boat",6)
        self.store.discover(s)
        changed=copy.deepcopy(s)
        changed["revision"]=2
        changed["status"]="cancelled"
        changed["snapshot_hash"]=digest({k:v for k,v in changed.items() if k!="snapshot_hash"})
        self.store.discover(changed)
        with self.assertRaises(ContractError): self.store.freeze(s,forecast(s),run_id="stale")
        with self.assertRaises(ContractError): self.store.freeze(changed,forecast(changed),run_id="cancelled")

    def test_unknown_permissions_zero_calls(self):
        calls=[]
        for status in ["UNKNOWN","DENY","ALLOW"]:
            with self.assertRaises(ContractError):
                permission_fetch({"collection":status},lambda:calls.append(1))
        self.assertEqual(calls,[])

    def test_denominator_keeps_no_forecast_and_result_corrections(self):
        report=run_e2e(Path(self.tmp.name)/"all.sqlite")
        self.assertEqual(report["scope"],"SYNTHETIC_ONLY")
        self.assertEqual(report["ledger_races"],8)
        self.assertEqual(report["evaluable_races"],5)
        self.assertEqual(report["pre_cutoff_freezes"],4)
        self.assertEqual(report["no_forecast"],1)
        self.assertEqual(report["hits"],3)
        self.assertEqual(report["hit8_all"],3/5)
        self.assertEqual(report["result_revisions"],9)
        self.assertEqual(set(report["by_sport"]),{"boat","keirin","autorace","horse"})
        self.assertEqual(report["real_races"],None)
        self.assertEqual(report["external_source_requests"],0)

    def test_subprocess_reopen_integrity(self):
        self.save()
        code="from race_ai.actions_store import SyntheticJournal; import sys; j=SyntheticJournal(sys.argv[1]); print(j.verify()); j.close()"
        out=subprocess.run([sys.executable,"-c",code,str(self.path)],capture_output=True,text=True,check=True)
        self.assertIn(self.store.verify(),out.stdout)


    def test_actual_missing_feature_preserves_discovery_and_no_forecast(self):
        s=fixture("boat",6)
        s["participants"][0]["features"]["historical_rating"]=None
        s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
        self.store.discover(s)
        with self.assertRaises(ContractError): forecast(s)
        self.store.no_forecast(s,"MISSING_FEATURES")
        self.assertEqual(len(self.store.events("race")),1)

    def test_authoritative_cutoff_revision_and_postponement(self):
        s=fixture("horse",10)
        self.store.discover(s)
        changed=copy.deepcopy(s)
        changed["revision"]=2
        changed["sales_cutoff_at"]="2030-01-01T00:25:00+00:00"
        changed["snapshot_hash"]=digest({k:v for k,v in changed.items() if k!="snapshot_hash"})
        self.store.discover(changed)
        with self.assertRaises(ContractError): self.store.freeze(s,forecast(s),run_id="stale")
        with self.assertRaises(ContractError): self.store.freeze(changed,forecast(changed),run_id="late")

    def test_dead_heat_and_refund_pending_are_not_invented_winners(self):
        s=fixture("boat",6)
        self.save(s)
        self.clock.value=datetime(2030,1,1,2,tzinfo=timezone.utc)
        first=forecast(s)["ordered_top8"][0]
        self.store.result(s,revision=1,status="final",winning_combinations=[first,[6,5,4]])
        self.assertEqual(evaluate(self.store)["hits"],1)
        self.store.result(s,revision=2,status="unsupported",winning_combinations=[])
        self.assertEqual(evaluate(self.store)["evaluable_races"],0)
        self.assertEqual(evaluate(self.store)["unresolved"],1)

    def test_no_result_before_start_or_revision_gap(self):
        s=fixture("keirin",7)
        self.store.discover(s)
        with self.assertRaises(ContractError):
            self.store.result(s,revision=1,status="final",winning_combinations=[[1,2,3]])
        self.clock.value=datetime(2030,1,1,2,tzinfo=timezone.utc)
        with self.assertRaises(ContractError):
            self.store.result(s,revision=2,status="final",winning_combinations=[[1,2,3]])

    def test_jst_midnight_identity_mismatch_rejected(self):
        s=fixture("horse",10)
        s["race_id"]["event_date_jst"]="2029-12-31"
        s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
        with self.assertRaises(ContractError): self.store.discover(s)

    def test_unsafe_fields_never_admitted_or_hashed(self):
        s=fixture("keirin",7)
        s["source"]["token"]="not-a-real-token"
        s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
        with self.assertRaises(ContractError): self.store.discover(s)

    def test_cloud_builds_and_credentials_disabled(self):
        for path in ["vercel.json","web/vercel.json"]:
            self.assertIs(json.loads(Path(path).read_text())["git"]["deploymentEnabled"],False)
        workflow=Path(".github/workflows/four-sport-synthetic.yml").read_text()
        for forbidden in ["secrets.","id-token:","pull_request_target","schedule:","upload-artifact","wrangler","vercel deploy"]:
            self.assertNotIn(forbidden,workflow)
        self.assertIn("persist-credentials: false",workflow)

    def test_e2e_entirely_offline(self):
        with patch("socket.create_connection",side_effect=AssertionError("network forbidden")):
            report=run_e2e(Path(self.tmp.name)/"offline.sqlite")
        self.assertEqual(report["external_source_requests"],0)


    def test_review_clock_crosses_in_precommit_work(self):
        s=fixture("boat",6)
        self.store.discover(s)
        self.clock.value=datetime.fromisoformat(s["sales_cutoff_at"])-timedelta(seconds=1)
        def cross_cutoff():
            self.clock.value+=timedelta(seconds=2)
        with patch.object(self.store,"_before_commit",side_effect=cross_cutoff):
            with self.assertRaises(ContractError):
                self.store.freeze(s,forecast(s),run_id="crossed-in-hook")
        self.assertEqual(len(self.store.events("freeze")),0)

    def test_review_old_void_does_not_exclude_rescheduled_race(self):
        s=fixture("boat",6)
        self.store.discover(s)
        self.clock.value=datetime(2030,1,1,2,tzinfo=timezone.utc)
        self.store.result(s,revision=1,status="void",winning_combinations=[])
        changed=copy.deepcopy(s)
        changed["revision"]=2
        changed["snapshot_hash"]=digest({k:v for k,v in changed.items() if k!="snapshot_hash"})
        self.store.discover(changed)
        stats=evaluate(self.store)
        self.assertEqual(stats["void"],0)
        self.assertEqual(stats["unresolved"],1)

    def test_abrupt_process_exit_rolls_back_open_transaction(self):
        s=fixture("boat",6)
        self.store.discover(s)
        before=self.store.verify()
        code="""import os,sys
from datetime import datetime
from race_ai.actions_store import SyntheticJournal
from race_ai.actions_contract import forecast
from race_ai.synthetic_e2e import fixture
j=SyntheticJournal(sys.argv[1],lambda:datetime.fromisoformat("2030-01-01T00:30:00+00:00"))
j.db.set_trace_callback(lambda sql:os._exit(73) if sql=="COMMIT" else None)
j.freeze(fixture("boat",6),forecast(fixture("boat",6)),run_id="abrupt")
"""
        result=subprocess.run([sys.executable,"-c",code,str(self.path)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,73)
        self.assertEqual(self.store.verify(),before)
        self.save()

    def test_overlapping_processes_commit_one_identical_freeze(self):
        self.store.discover(fixture("boat",6))
        gate=Path(self.tmp.name)/"go"
        code="""import sys,time
from pathlib import Path
from datetime import datetime
from race_ai.actions_store import SyntheticJournal
from race_ai.actions_contract import forecast,canonical
from race_ai.synthetic_e2e import fixture
j=SyntheticJournal(sys.argv[1],lambda:datetime.fromisoformat("2030-01-01T00:30:00+00:00"))
while not Path(sys.argv[2]).exists(): time.sleep(.01)
j._before_commit=lambda:time.sleep(.15)
print(canonical(j.freeze(fixture("boat",6),forecast(fixture("boat",6)),run_id="overlap")))
j.close()
"""
        children=[subprocess.Popen([sys.executable,"-c",code,str(self.path),str(gate)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        gate.touch()
        outputs=[]
        try:
            for child in children:
                out,err=child.communicate(timeout=15)
                self.assertEqual(child.returncode,0,err)
                outputs.append(json.loads(out))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(len(self.store.events("freeze")),1)

    def test_corrupt_restore_rejected(self):
        self.save()
        backup=Path(self.tmp.name)/"corrupt.sqlite"
        self.store.backup(backup)
        db=sqlite3.connect(backup)
        db.execute("DROP TRIGGER events_immutable_update")
        db.execute("UPDATE events SET event_hash=?",("f"*64,))
        db.commit()
        db.close()
        with self.assertRaises(ContractError): SyntheticJournal(backup,self.clock)


    def test_review_result_requires_exact_discovered_snapshot(self):
        s=fixture("horse",10)
        self.store.discover(s)
        wrong=copy.deepcopy(s)
        wrong["scheduled_start_at"]="2030-01-01T01:00:00+00:00"
        wrong["snapshot_hash"]=digest({k:v for k,v in wrong.items() if k!="snapshot_hash"})
        self.clock.value=datetime(2030,1,1,1,tzinfo=timezone.utc)
        with self.assertRaises(ContractError):
            self.store.result(wrong,revision=1,status="final",winning_combinations=[[1,2,3]])

    def test_review_restore_missing_clock_fails_closed(self):
        self.save()
        backup=Path(self.tmp.name)/"no-clock.sqlite"
        self.store.backup(backup)
        db=sqlite3.connect(backup)
        db.execute("DELETE FROM clock_state")
        db.commit()
        db.close()
        with self.assertRaises(ContractError): SyntheticJournal(backup,self.clock)

    def test_review_old_result_correction_does_not_mask_current_revision(self):
        s=fixture("boat",6)
        self.store.discover(s)
        updated=copy.deepcopy(s)
        updated["revision"]=2
        updated["snapshot_hash"]=digest({k:v for k,v in updated.items() if k!="snapshot_hash"})
        self.store.discover(updated)
        self.clock.value=datetime(2030,1,1,2,tzinfo=timezone.utc)
        self.store.result(updated,revision=1,status="final",winning_combinations=[[1,2,3]])
        self.store.result(s,revision=2,status="void",winning_combinations=[])
        self.assertEqual(evaluate(self.store)["evaluable_races"],1)


    def test_review_boolean_or_float_prediction_tamper_rejected(self):
        s=fixture("boat",6)
        self.store.discover(s)
        for change in [True,1.0]:
            f=forecast(s)
            f["revision"]=change
            with self.assertRaises(ContractError): self.store.freeze(s,f,run_id="typed-tamper")

    def test_review_caller_mutation_during_commit_cannot_change_owned_prediction(self):
        s=fixture("boat",6)
        self.store.discover(s)
        f=forecast(s)
        expected=copy.deepcopy(f)
        with patch.object(self.store,"_before_commit",side_effect=lambda:f["ordered_top8"].reverse()):
            self.store.freeze(s,f,run_id="mutating-caller")
        self.assertEqual(self.store.events("freeze")[0]["payload"]["prediction"],expected)

    def test_review_noncanonical_date_cannot_duplicate_denominator(self):
        for alias in ["20300101","2030-W01-2"]:
            s=fixture("boat",6)
            s["race_id"]["event_date_jst"]=alias
            s["snapshot_hash"]=digest({k:v for k,v in s.items() if k!="snapshot_hash"})
            with self.assertRaises(ContractError): self.store.discover(s)


    def test_review_result_caller_list_is_owned_before_commit(self):
        s=fixture("boat",6)
        self.store.discover(s)
        self.clock.value=datetime(2030,1,1,2,tzinfo=timezone.utc)
        winners=[[1,2,3]]
        with patch.object(self.store,"_before_commit",side_effect=lambda:winners.append([99,98,97])):
            self.store.result(s,revision=1,status="final",winning_combinations=winners)
        self.assertEqual(self.store.events("result")[0]["payload"]["winning_combinations"],[[1,2,3]])
        self.store.verify()

if __name__ == "__main__":
    unittest.main()

