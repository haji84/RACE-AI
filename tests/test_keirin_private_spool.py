"""Real pinned PR71 model + real SQLite + automatic multi-tick spool E2E.

All inputs are fictional. This verifies durable orchestration, not provider
availability, legitimate source use, or independent pre-cutoff timestamp.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import tempfile
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_private_spool import KeirinPrivateSpool, InboxError
from tests.test_keirin_pr71_model_adapter import (
    RID, CUTOFF, make_sources, run_suite, verify_suite
)


@unittest.skipIf(run_suite is None, "PR71 model not installed")
class RealOwnerSpoolCycleTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.inbox=self.root/"incoming"
        for sub in ("daily","pre","results"):
            (self.inbox/sub).mkdir(parents=True)
        self.dbpath=self.root/"owner.sqlite3"
        self.now=[datetime.fromisoformat("2030-01-15T09:21:00+09:00")]
        self.clock=lambda:self.now[0]

    def save(self,kind,name,payload):
        target=self.inbox/kind/name
        target.write_text(json.dumps(payload,ensure_ascii=False,
                                     sort_keys=True),encoding="utf-8")
        return target

    def agent(self,store):
        return KeirinPrivateSpool(
            store,clock=self.clock,
            model_suite=run_suite,model_verifier=verify_suite,
            source_attestor=None,source_observation_gate=None,witness=None)

    def test_two_future_races_across_restart_with_prior_result_pdca(self):
        snapshot,_,_=make_sources()
        self.save("pre","01.json",snapshot)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["private_forecasts_saved_this_tick"],1)
            self.assertIsNone(tick["official_hit_at_8_all"])
            self.assertEqual(tick["provider_network_requests"],0)
            first=store.get_persisted_forecast(RID)
            self.assertEqual(len(first["forecast"]["top8"]),8)
            first_sha=first["sha256"]
            top=first["forecast"]["top8"][0]
        self.now[0]=datetime.fromisoformat("2030-01-15T10:40:00+09:00")
        result={"schema":"RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1",
                "observation":{
                    "race_id":RID,
                    "observed_at":"2030-01-15T10:04:00+09:00",
                    "source_sha256":"a"*64,
                    "status":"FINAL_NORMAL","refund_status":"NONE",
                    "winning_triples":[top],
                    "payouts_100yen":[{"triple":top,"yen":2680}]}}
        self.save("results","01.json",result)
        next_snap=deepcopy(snapshot)
        next_id="keirin:2030-01-15:fictional-venue:2"
        next_snap["race_id"]=next_id
        next_snap["as_of"]="2030-01-15T10:30:00+09:00"
        next_snap["official_cutoff_at"]="2030-01-15T11:50:00+09:00"
        evidence=next_snap["facts"]["pr71_evidenced_snapshot"]["race"]
        evidence["race_id"]=next_id
        evidence["as_of"]=next_snap["as_of"]
        evidence["sales_cutoff_at"]=next_snap["official_cutoff_at"]
        self.save("pre","02.json",next_snap)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["reference_hits_this_tick"],1)
            self.assertEqual(tick["private_forecasts_saved_this_tick"],1)
            self.assertEqual(tick["states"].get(
                "FORECAST_PRIVATE_DURABLY_SAVED"),1)
            self.assertEqual(tick["states"].get(
                "REFERENCE_HIT8_RESEARCH"),1)
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             first_sha)
            self.assertEqual(len(store.get_persisted_forecast(next_id)
                                 ["forecast"]["top8"]),8)
            self.assertEqual(store.research_audit(RID)["research_hit8"],True)
            self.assertIsNone(store.research_audit(RID)["formal_hit_at_8_all"])
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            again=self.agent(store).tick(self.inbox)
            self.assertEqual(again["private_forecasts_saved_this_tick"],0)
            self.assertEqual(again["reference_hits_this_tick"],0)
            self.assertEqual(again["states"]["RESULT_ALREADY_SEEN_NO_RECOUNT"],1)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM forecasts").fetchone()[0],2)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],1)

    def test_expired_source_does_not_create_forecast(self):
        snap,_,_=make_sources()
        self.save("pre","01.json",snap)
        self.now[0]=datetime.fromisoformat("2030-01-15T10:10:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["private_forecasts_saved_this_tick"],0)
            self.assertEqual(tick["states"]["MISSED_OR_UNVERIFIED_CUTOFF"],1)
            self.assertIsNone(store.get_persisted_forecast(RID))

    def test_nonexistent_real_source_authenticator_never_guesses_features(self):
        snap,_,_=make_sources()
        snap["facts"]["pr71_evidenced_snapshot"]["scope"]="OPERATOR_SUPPLIED_RESEARCH"
        self.save("pre","01.json",snap)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["states"]["REAL_SOURCE_ATTESTOR_NOT_CONFIGURED"],1)
            self.assertEqual(tick["private_forecasts_saved_this_tick"],0)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM forecasts").fetchone()[0],0)

    def test_daily_cohort_and_missing_races_retained(self):
        rows=[]
        for n in range(1,8):
            rows.append({
                "race_id":f"2030011536{n:02d}",
                "venue_code":36,"race_no":n,
                "official_cutoff_at":None,
            })
        ledger={"schema":"RACE_AI_KEIRIN_ALL_DISCOVERED_RACES_LEDGER_V1",
                "event_date_jst":"2030-01-15",
                "discovered_count":len(rows),
                "national_coverage_verified":False,
                "records":rows}
        self.save("daily","day.json",ledger)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            first=self.agent(store).tick(self.inbox)
            self.assertEqual(first["states"]["IMPORTED"],1)
            self.assertEqual(store.inspect_cohort("2030-01-15")
                             ["known_race_count"],7)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            second=self.agent(store).tick(self.inbox)
            self.assertEqual(store.inspect_cohort("2030-01-15")
                             ["known_race_count"],7)
            self.assertEqual(store.inspect_cohort("2030-01-15")
                             ["forecast_count"],0)

    def test_invalid_result_never_is_label(self):
        doc={"schema":"RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1",
             "observation":{"race_id":RID,"observed_at":
                "2030-01-15T09:15:00+09:00","source_sha256":"a"*64,
                "status":"PENDING","refund_status":"UNKNOWN",
                "winning_triples":[[1,2,3]],"payouts_100yen":[]}}
        self.save("results","bad.json",doc)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["states"]["RESULT_REJECTED_OR_NOT_ADMITTED"],1)
            self.assertIsNone(store.research_audit(RID)["research_hit8"])


if __name__=="__main__":
    unittest.main()
