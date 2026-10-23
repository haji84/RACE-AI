"""Run pinned PR71 research delivery through existing PR72 binding.

For GitHub-hosted CI only, with FICTIONAL fixture input. No network/source
capture, real source approval, real forecast freeze, payment or deployment.
The model code is imported from a separately checked-out pinned PR71 SHA.
"""
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent.parent
# python scripts/file.py sets sys.path[0] to scripts, not the repo root.
sys.path.insert(0,str(HERE))
import race_ai
import tests

PR71=HERE/"pr71-contract-reference"
if not (PR71/"race_ai/permissioned_source_delivery.py").is_file():
    raise RuntimeError("PR71 independent pinned checkout missing")
race_ai.__path__.append(str(PR71/"race_ai"))
tests.__path__.append(str(PR71/"tests"))
sys.path.insert(0,str(PR71/"tests"))

from test_permissioned_source_delivery import raw_feed,gate,AT
from race_ai.permissioned_source_delivery import deliver
from race_ai.operator_export_intake import transform
from race_ai.pr71_delivery_binding import bind_audit_to_delivery

for sport in ("boat","keirin","autorace","horse"):
    raw=raw_feed(sport)
    data=deliver(raw,gate(),at=AT,persist=False)
    snapshot=data["snapshot"]
    race=snapshot["race"]
    model_sport=race["sport"]
    ledger_sport="horse_local" if model_sport=="horse" else model_sport
    venue=race["venue"]
    day=race["event_date_jst"]
    # PR71 test fixtures are all 1R in fictional-venue, NOT real events.
    if not race["race_id"].endswith(":1"):
        raise AssertionError("PR71 fixture changed its race ID format")
    obj={"schema":"RACE_AI_OPERATOR_EXPORT_V1","event_date_jst":day,
         "source_ref":"https://example.org/fictional",
         "source_rights_ref":"FICTIONAL_NOT_A_GRANT","captured_at":AT,
         "races":[{"sport":ledger_sport,"venue":venue,"race_no":1,
                   "sales_cutoff_at":race["sales_cutoff_at"],
                   "offering_status":"UNKNOWN"}]}
    audit=transform(obj,"a"*64)
    source_id=audit["records"][0]["race_id"]
    binding=bind_audit_to_delivery(audit,data,race_id=source_id)
    assert binding["model_race_id"]==race["race_id"]
    assert data["race_id"]==race["race_id"]  # Original model hash not edited.
    assert len(binding["models"])==data["research_suite"]["model_count"]
    assert binding["source_access_reviewed_by_this_bridge"] is False
    assert binding["official_sales_cutoff_verified"] is False
    assert binding["external_freeze_verified"] is False
    assert binding["eligible_for_scoring"] is False
    print("PINNED_PR71_PR72_SYNTHETIC_JOIN_OK",sport,len(binding["models"]))

# Use the actual pinned PR71 time verifier, rather than a fake "true"
# callback, with offline fictional GitHub HTTPS responses only.
import base64
import json
from race_ai.github_freeze_receipt import verify_github_freeze, ReceiptVerificationError, BASE, ANCHOR_SCHEMA
from race_ai.race_bound_freeze_receipt import verify_bound_receipt, BoundReceiptError

expected="boat:2030-01-15:fictional-venue:1"
sample_receipt={"run_id":31337,"path":"audit/freezes/2030-01-15/fictional-1.json"}
sample_hash="a"*64
sample_cutoff="2030-01-15T10:00:00+09:00"
sample_persisted="2030-01-15T09:40:00+09:00"
server_run={"id":31337,"event":"push","head_sha":"b"*40,
            "repository":{"full_name":"haji84/RACE-AI"},
            "created_at":"2030-01-15T00:45:00Z"}
anchor={"schema":ANCHOR_SCHEMA,"race_id":expected,
        "prediction_sha256":sample_hash,"cutoff_at":sample_cutoff}

def fictional_github(url):
    if url==f"{BASE}/actions/runs/31337":
        return server_run
    if url==f"{BASE}/contents/{sample_receipt['path']}?ref="+("b"*40):
        return {"type":"file","encoding":"base64",
                "content":base64.b64encode(json.dumps(anchor).encode("utf-8")).decode("ascii")}
    raise AssertionError("unexpected fictional GitHub URL")

assert verify_bound_receipt(sample_receipt,sample_hash,sample_persisted,sample_cutoff,
                            expected_race_id=expected,
                            trusted_legacy_verifier=verify_github_freeze,
                            github_fetch=fictional_github)
anchor["race_id"]="boat:2030-01-15:fictional-venue:2"
try:
    verify_bound_receipt(sample_receipt,sample_hash,sample_persisted,sample_cutoff,
                         expected_race_id=expected,
                         trusted_legacy_verifier=verify_github_freeze,
                         github_fetch=fictional_github)
except BoundReceiptError as exc:
    assert "RACE_ID_MISMATCH" in str(exc)
else:
    raise AssertionError("wrong race_id must not validate")
anchor["race_id"]=expected
server_run["created_at"]="2030-01-15T01:01:00Z" # after simulated cutoff
try:
    verify_bound_receipt(sample_receipt,sample_hash,sample_persisted,sample_cutoff,
                         expected_race_id=expected,
                         trusted_legacy_verifier=verify_github_freeze,
                         github_fetch=fictional_github)
except ReceiptVerificationError:
    pass
else:
    raise AssertionError("late real PR71 GitHub issuance must be rejected")
print("PINNED_PR71_RACE_BOUND_FREEZE_GUARD_OK (SYNTHETIC_API_RESPONSES_ONLY)")


# END-TO-END REPLAY OF ACTUAL PR71 MODEL CODE, BUT ALL SOURCES, HTTP
# RESPONSES, SOURCE RIGHTS AND RACE OUTCOMES HERE ARE FICTIONAL.
from race_ai.append_only_freeze_writer import prepare_anchor, submit_anchor
from race_ai.proof_aware_settlement import audit_settlement

for sport in ("boat", "keirin", "autorace", "horse"):
    supplied=deliver(raw_feed(sport),gate(),at=AT,persist=False)
    race=supplied["snapshot"]["race"]
    source_sport="horse_local" if sport=="horse" else sport
    day=race["event_date_jst"]
    venue=race["venue"]
    cutoff=race["sales_cutoff_at"]
    source_id=f"{source_sport}:{day}:{venue}:1"
    second_id=f"{source_sport}:{day}:{venue}:2"
    obj={"schema":"RACE_AI_OPERATOR_EXPORT_V1","event_date_jst":day,
         "source_ref":"https://example.org/fictional",
         "source_rights_ref":"FICTIONAL_NOT_A_GRANT",
         "captured_at":AT,
         "races":[{"sport":source_sport,"venue":venue,"race_no":n,
                   "sales_cutoff_at":cutoff,"offering_status":"UNKNOWN"}
                  for n in (1,2)]}
    audit=transform(obj,"c"*64)
    bound=bind_audit_to_delivery(audit,supplied,race_id=source_id)
    model=bound["models"][0]
    generated=race["as_of"]
    stored="2030-01-15T09:35:00+09:00"
    prepared=prepare_anchor(bound,model["model_id"],generated,stored)
    expected_raw=(json.dumps(prepared["anchor"],sort_keys=True,
                 ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
    def fake_contents_api(url, method, body):
        if method=="PUT":
            posted=json.loads(body)
            assert "sha" not in posted  # create-only; no prior overwrite
            assert base64.b64decode(posted["content"])==expected_raw
            return {"commit":{"sha":"b"*40}}
        assert method=="GET" and url.endswith("?ref="+"b"*40)
        return {"type":"file","encoding":"base64",
                "content":base64.b64encode(expected_raw).decode("ascii")}
    committed=submit_anchor(prepared,branch="audit/freeze-fictional",token="x"*40,
                            independent_release_check=lambda _:True,
                            request=fake_contents_api)
    assert committed["eligible_for_hit_at_8"] is False
    assert committed["run_id"] is None

    witnessed={"id":31337,"event":"push","head_sha":"b"*40,
               "repository":{"full_name":"haji84/RACE-AI"},
               "created_at":"2030-01-15T00:40:00Z"}
    receipt={"run_id":31337,"path":prepared["path"]}
    def fake_github_https(url):
        if url==f"{BASE}/actions/runs/31337":return witnessed
        if url==f"{BASE}/contents/{prepared['path']}?ref="+("b"*40):
            return {"type":"file","encoding":"base64",
                    "content":base64.b64encode(expected_raw).decode("ascii")}
        raise AssertionError("unexpected external endpoint")
    def verified_anchor(forecast,source_race_id):
        return (source_race_id==source_id
                and forecast["model_race_id"]==bound["model_race_id"]
                and forecast["prediction_sha256"]==model["prediction_sha256"]
                and verify_bound_receipt(
                    forecast["receipt"],forecast["prediction_sha256"],
                    forecast["persisted_at"],forecast["cutoff_at"],
                    expected_race_id=bound["model_race_id"],
                    trusted_legacy_verifier=verify_github_freeze,
                    github_fetch=fake_github_https))
    # First source race forecast is present; the second is intentionally
    # absent and MUST still count in the eligible denominator.
    f={"race_id":source_id,"model_race_id":bound["model_race_id"],
       "model_id":model["model_id"],"ordered_top8":model["ordered_top8"],
       "prediction_sha256":model["prediction_sha256"],
       "generated_at":generated,"persisted_at":stored,"cutoff_at":cutoff,
       "receipt":receipt}
    results=[
        {"race_id":identifier,"status":"FINAL","trifecta_offered":True,
         "payouts":[{"combination":model["ordered_top8"][0] if index==0 else
                     [2,3,1],"yen_per_100":1000}],
         "refund_status":"NONE","revision_no":1,
         "confirmed_at":"2030-01-15T11:00:00+09:00",
         "source_ref":"https://example.org/fictional-result"}
         for index,identifier in enumerate((source_id,second_id))]
    callbacks={"verify_result":lambda row:row["source_ref"]=="https://example.org/fictional-result",
               "verify_cutoff":lambda row:row["sales_cutoff_at"]==cutoff,
               "verify_freeze":verified_anchor,
               "verify_coverage":lambda entries:len(entries["records"])==2}
    reconciled=audit_settlement(audit,results,[f],**callbacks)
    assert reconciled["eligible_verified_subset"]==2
    assert reconciled["freeze_verified_subset"]==1
    assert reconciled["hit8_verified_subset"]==1
    assert reconciled["formal_hit_at_8_all"]==0.5
    assert reconciled["formal_capture_rate"]==0.5

    # A new, unverified revision suppresses any stale old payout score.
    from copy import deepcopy
    corrected=deepcopy(results[0])
    corrected["revision_no"]=2
    corrected["confirmed_at"]="2030-01-15T11:15:00+09:00"
    bad_callbacks=dict(callbacks)
    bad_callbacks["verify_result"]=lambda row:row["revision_no"]==1
    stale=audit_settlement(audit,results+[corrected],[f],**bad_callbacks)
    assert stale["formal_hit_at_8_all"] is None
    print("SYNTHETIC_ONE_RACE_PR71_TO_SETTLEMENT_OK",sport,
          "1_FROZEN_OF_2_ELIGIBLE; NOT_REAL_DATA")

print("NO_REAL_FORECAST_OR_OFFICIAL_FREEZE_CLAIM")
