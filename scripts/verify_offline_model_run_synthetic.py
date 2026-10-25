"""Executable local restart/revision check: only eight authored fictional races.

No provider fetching, external receipts, cloud writes or production operation.
Real-data manifests are intentionally outside this executable's interface.
"""
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PIN="ebe93f13062cf0461b81b924a5dc0482ada37b56"
REFERENCE=ROOT/"pr71-private-transport-reference"


def main():
    if not __debug__:
        raise RuntimeError("Verification requires enabled assertions")
    # Reuse only exact pinned authored fixtures/models; no checkout/download.
    for rel in ("race_ai/comprehensive_four_sport_models.py",
                "race_ai/four_sport_model_suite.py","race_ai/four_sport_matchup_models.py",
                "race_ai/four_sport_learning.py","race_ai/permissioned_source_delivery.py",
                "race_ai/private_delivery_codec.py",
                "tests/test_permissioned_source_delivery.py",
                "tests/test_comprehensive_four_sport_models.py"):
        original=subprocess.check_output(["git","-C",str(ROOT),"show",PIN+":"+rel])
        if (REFERENCE/rel).read_bytes().replace(b"\r\n",b"\n")!=original.replace(b"\r\n",b"\n"):
            raise RuntimeError("Pinned fictional fixture/model changed")
    sys.path.insert(0,str(ROOT))
    import race_ai
    import tests
    race_ai.__path__.append(str(REFERENCE/"race_ai"))
    tests.__path__.append(str(REFERENCE/"tests"))
    sys.path.insert(0,str(REFERENCE/"tests"))
    from test_permissioned_source_delivery import AT,gate,raw_feed
    from race_ai.comprehensive_four_sport_models import digest,validate
    from race_ai.four_sport_model_suite import ALL_MODELS
    from race_ai.permissioned_source_delivery import deliver
    from race_ai import private_delivery_codec as codec
    from race_ai.offline_model_run import SyntheticModelJournal,SCHEMA

    policy=gate();raws={};rows=[];jobs=[]
    day="2030-01-15"
    for sport in ("boat","keirin","autorace","horse"):
        raw=raw_feed(sport);snapshot=json.loads(raw)["snapshot"]
        source_sport="horse_local" if sport=="horse" else sport
        for number in (1,2):
            identity=f"{source_sport}:{day}:fictional-venue:{number}"
            rows.append({"race_id":identity,"sport":source_sport,"venue":"fictional-venue",
                         "race_no":number,"sales_cutoff_at":snapshot["race"]["sales_cutoff_at"],
                         "cutoff_verified":False,"prediction":None,"result":None})
            check=None
            if number==1:
                raws[identity]=raw
                check={"as_of":snapshot["race"]["as_of"],
                       "source_payload_sha256":hashlib.sha256(raw).hexdigest(),
                       "policy_record_sha256":policy.document_sha256,
                       "feature_snapshot_sha256":digest(snapshot)}
            jobs.append({"race_id":identity,"input_check":check})
    ledger={"schema":"RACE_AI_FORECAST_AUDIT_V1","dataset_status":"AUDIT_ONLY",
            "event_date_jst":day,"records":rows}
    manifest={"schema":SCHEMA,"scope":"SYNTHETIC_ONLY","planned_as_of":AT,
              "source_pins":{"model":PIN,
                "settlement_contract_base":"2a99473c4755932e2d395b9e785be4f4835aef99"},
              "expected_model_ids":list(ALL_MODELS),
              "expected_model_versions":{name:"0.1.0-UNTRAINED" for name in ALL_MODELS},
              "ledger":ledger,"jobs":jobs}
    now=[datetime.fromisoformat(AT)];calls=[]

    def factory(job,*,at):
        calls.append(job["race_id"])
        return deliver(raws[job["race_id"]],policy,at=at,persist=False)

    def open_journal(path):
        return SyntheticModelJournal(path,clock=lambda:now[0],codec=codec,
            validate_snapshot=validate,allow_source=policy.authorize)

    with tempfile.TemporaryDirectory(prefix="race-ai-advanced-fictional-") as directory:
        path=Path(directory)/"advanced.sqlite"
        journal=open_journal(path)
        try:initial=journal.run(manifest,delivery_factory=factory)
        finally:journal.close()
        assert len(calls)==4 and len(initial)==8
        assert sum(row["state"]=="DELIVERY" for row in initial)==4
        assert sum(row["state"]=="NO_FORECAST" for row in initial)==4
        # Exact original transport bytes survive a genuinely closed connection.
        def wires():
            with closing(sqlite3.connect(path)) as db:
                return db.execute("SELECT event_key,content FROM advanced_events WHERE kind='DELIVERY' ORDER BY seq").fetchall()
        original_wires=wires()
        assert len(original_wires)==4
        assert {key for key,wire in original_wires}=={"job:"+identity for identity in raws}
        assert all(type(wire) is bytes and wire for key,wire in original_wires)
        now[0]=datetime.fromisoformat(day+"T11:05:00+09:00")
        journal=open_journal(path)
        try:
            def forbidden_factory(*args,**kwargs):raise AssertionError("committed job recomputed")
            resumed=journal.run(manifest,delivery_factory=forbidden_factory)
            assert resumed==initial and wires()==original_wires
            results=[{"race_id":row["race_id"],"status":"FINAL","trifecta_offered":True,
                      "payouts":[{"combination":[1,2,3],"yen_per_100":1000}],
                      "refund_status":"NONE","revision_no":1,
                      "confirmed_at":day+"T11:00:00+09:00",
                      "source_ref":"https://example.org/fictional-result"} for row in rows]
            journal.add_results(results)
            denied=journal.report()
            assert tuple(denied["settlement"]["models"])==tuple(ALL_MODELS)
            assert all(row["formal_hit_at_8_all"] is None for row in denied["settlement"]["models"].values())
            assert denied["prepared_anchor_count"]==16 and len(denied["jobs"])==8
            gates={"admit_model_roster":lambda declaration:declaration==tuple(
                       (name,"0.1.0-UNTRAINED",PIN) for name in ALL_MODELS),
                   "verify_result":lambda row:True,"verify_cutoff":lambda row:True,
                   "verify_coverage":lambda observed:digest(observed)==digest(ledger)}
            first=journal.report(synthetic_gates=gates)
            assert tuple(first["settlement"]["models"])==tuple(ALL_MODELS)
            assert journal.report(synthetic_gates=gates)==first
            for comparison in first["settlement"]["models"].values():
                assert comparison["eligible_verified_subset"]==8
                assert comparison["freeze_verified_subset"]==0
                assert comparison["formal_hit_at_8_all"]==0
            corrected=deepcopy(results[0]);corrected["revision_no"]=2
            corrected["confirmed_at"]=day+"T11:04:00+09:00"
            corrected["payouts"][0]["combination"]=[3,2,1]
            journal.add_results([corrected])
            second=journal.report(synthetic_gates=gates)
            assert tuple(second["settlement"]["models"])==tuple(ALL_MODELS)
            assert second["basis_sha256"]!=first["basis_sha256"]
            assert wires()==original_wires and len(calls)==4
            assert first["official_prediction"] is False and second["external_time_attested"] is False
            with closing(sqlite3.connect(path)) as db:
                revision_count=db.execute("SELECT COUNT(*) FROM advanced_events WHERE kind='RESULT'").fetchone()[0]
            assert revision_count==9
            print(json.dumps({"scope":"SYNTHETIC_ONLY","sport_count":4,"model_count":4,
                "ledger_races":8,"deliveries":4,"missing_input_jobs":4,
                "prepared_local_anchors":16,"external_verified_freezes":0,
                "reopened_original_wire_identity":True,"models_reexecuted_on_resume":0,
                "result_revisions":revision_count,"immutable_evaluation_basis_changed":True,
                "default_formal_metrics_available":False,"source_requests":0,
                "official_prediction":False,"forward_98_percent_verified":False},sort_keys=True))
        finally:journal.close()
    return 0


if __name__=="__main__":
    with patch("socket.create_connection",side_effect=AssertionError("network forbidden in fictional run")):
        raise SystemExit(main())
