"""Credential-free synthetic E2E. This module contains no HTTP client.

A market sidecar is intentionally outside the snapshot, model and journal.
Real sources remain NOT_ADMITTED; this fixture demonstration grants no rights.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import tempfile
from .actions_contract import ContractError, FEATURES, digest, forecast, race_key
from .actions_store import SyntheticJournal

def fixture(sport,n,ordinal=1):
    s={"race_id":{"sport":sport,"organizer":"synthetic","venue":"fixture","meeting":"fixture",
                  "event_date_jst":"2030-01-01","race_no":ordinal},
       "revision":1,"scheduled_start_at":"2030-01-01T01:05:00+00:00",
       "sales_cutoff_at":"2030-01-01T01:00:00+00:00","as_of":"2030-01-01T00:20:00+00:00",
       "status":"scheduled","trifecta_offered":True,"scope":"SYNTHETIC_ONLY",
       "source":{"url":"synthetic://fixture","permission_id":"synthetic-v1",
                 "available_at":"2030-01-01T00:00:00+00:00","observed_at":"2030-01-01T00:01:00+00:00",
                 "fetched_at":"2030-01-01T00:02:00+00:00","registered_at":"2030-01-01T00:03:00+00:00",
                 "transform_version":"fixture-v1"},
       "participants":[{"participant":p,"features":{FEATURES[sport]:float(n-p+1)}} for p in range(1,n+1)]}
    s["snapshot_hash"]=digest(s)
    return s

def permission_fetch(permission,fetch):
    # No production collector in this unit. Even an arbitrary ALLOW string
    # cannot confer source permission, budget, URL or credentials.
    raise ContractError("real source NOT_ADMITTED: verified purpose-specific rights and bounded transport required")

def evaluate(store):
    races={}
    for event in store.events("race"):
        s=event["payload"]
        races[race_key(s)]=s
    results={}
    for event in store.events("result"):
        r=event["payload"]
        results[(r["race_key"],r["race_revision"])]=r
    freezes={}
    for event in store.events("freeze"):
        p=event["payload"]
        freezes[(race_key(p["snapshot"]),p["snapshot"]["revision"])]=p["prediction"]
    totals={"ledger_races":len(races),"evaluable_races":0,"hits":0,"pre_cutoff_freezes":0,
            "no_forecast":0,"not_offered":0,"void":0,"unresolved":0}
    by_sport={sport:{"ledger":0,"evaluable":0,"hits":0,"freezes":0} for sport in FEATURES}
    for key,s in races.items():
        part=by_sport[s["race_id"]["sport"]]
        part["ledger"]+=1
        f=freezes.get((key,s["revision"]))
        if f:
            totals["pre_cutoff_freezes"]+=1
            part["freezes"]+=1
        result=results.get((key,s["revision"]))
        if not s["trifecta_offered"]:
            totals["not_offered"]+=1
        elif result and result["race_revision"]==s["revision"] and result["status"]=="void":
            totals["void"]+=1
        elif not result or result["status"]!="final" or result["race_revision"]!=s["revision"]:
            totals["unresolved"]+=1
        else:
            totals["evaluable_races"]+=1
            part["evaluable"]+=1
            hit=bool(f and any(order in f["ordered_top8"] for order in result["winning_combinations"]))
            totals["hits"]+=int(hit)
            part["hits"]+=int(hit)
            if not f: totals["no_forecast"]+=1
    totals["hit8_all"]=totals["hits"]/totals["evaluable_races"] if totals["evaluable_races"] else None
    totals["by_sport"]=by_sport
    totals["result_revisions"]=len(store.events("result"))
    return totals

def run_e2e(path,*,market_sidecar=None):
    # market_sidecar is deliberately never read, hashed or passed to the model.
    now=[datetime(2030,1,1,0,30,tzinfo=timezone.utc)]
    store=SyntheticJournal(path,lambda:now[0])
    primary=[fixture("boat",6),fixture("keirin",7),fixture("autorace",8),fixture("horse",10)]
    missing=fixture("boat",6,2)
    missing["participants"][0]["features"]["historical_rating"]=None
    missing["snapshot_hash"]=digest({k:v for k,v in missing.items() if k!="snapshot_hash"})
    unsold=fixture("keirin",9,2)
    unsold["trifecta_offered"]=False
    unsold["snapshot_hash"]=digest({k:v for k,v in unsold.items() if k!="snapshot_hash"})
    void=fixture("autorace",8,2)
    pending=fixture("horse",10,2)
    try:
        for s in primary+[missing,unsold,void,pending]:
            store.discover(s)
        predictions=[forecast(s) for s in primary]
        for s,f in zip(primary,predictions):
            store.freeze(s,f,run_id="synthetic-e2e")
        store.no_forecast(missing,"MISSING_FEATURES")
        chain_before=store.verify()
        store.close()
        # Reopen without retaining the runner's in-memory journal object.
        store=SyntheticJournal(path,lambda:now[0])
        if store.verify()!=chain_before: raise ContractError("restart hash mismatch")
        for s,f in zip(primary,predictions):
            store.freeze(s,f,run_id="synthetic-e2e-retry")
        now[0]=datetime(2030,1,1,2,tzinfo=timezone.utc)
        for s,f in zip(primary,predictions):
            store.result(s,revision=1,status="final",winning_combinations=[f["ordered_top8"][0]])
        # Official correction changes the score, never the prior prediction.
        outside=next(r["combination"] for r in predictions[0]["candidates"] if r["combination"] not in predictions[0]["ordered_top8"])
        store.result(primary[0],revision=2,status="final",winning_combinations=[outside])
        store.result(missing,revision=1,status="final",winning_combinations=[[1,2,3]])
        store.result(unsold,revision=1,status="final",winning_combinations=[[1,2,3]])
        store.result(void,revision=1,status="void",winning_combinations=[])
        store.result(pending,revision=1,status="pending",winning_combinations=[])
        report=evaluate(store)
        return dict(report,scope="SYNTHETIC_ONLY",external_source_requests=0,real_races=None,
                    external_time_attested=False,production_durable_store_verified=False,
                    prediction_hashes=[f["prediction_hash"] for f in predictions],
                    journal_hash=store.verify(),accuracy_goal_status="98_PERCENT_UNVALIDATED")
    finally:
        store.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path)
    args=parser.parse_args()
    if args.db:
        print(json.dumps(run_e2e(args.db),sort_keys=True))
    else:
        with tempfile.TemporaryDirectory() as temp:
            print(json.dumps(run_e2e(Path(temp)/"synthetic.sqlite"),sort_keys=True))

if __name__=="__main__":
    main()
