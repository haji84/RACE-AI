"""Rebuild an actual prospective BOAT A/B cohort from GitHub Actions receipts.

No Vercel, no official HTML fetch, no post-result predictions or model tuning.
All forecast artifacts are authenticated by Github API metadata + extracted
JSON SHA-256 and separately validated by the original frozen model checker.
One script processes each registered race, including pending/missing evidence.
GitHub Actions artifact expires; source immutable proof must be retained.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_ab_result_audit import score_pair
from scripts.boat_ab_cohort_report import report

REPO="haji84/RACE-AI"
HEX=re.compile(r"^[0-9a-f]{64}$")
RI=re.compile(r"^\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$")
MAX_ORIGINAL=190_000
MAX_RACES=24


def _need(condition,msg):
    if not condition:
        raise ValueError(msg)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _gh(path):
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("GitHub Actions read token missing")
    run=subprocess.run(["gh","api",path],text=True,capture_output=True,
                       encoding="utf-8",timeout=25,check=False)
    _need(run.returncode==0 and 0<len(run.stdout)<500_000,"GitHub API unavailable")
    return json.loads(run.stdout)


def _original(item,kind,cutoff):
    _need(isinstance(item,dict) and
          set(item)=={"run_id","artifact_id","name","zip_sha256","json_sha256"}
            if kind=="result" else
          isinstance(item,dict) and
          set(item)=={"run_id","artifact_id","name","zip_sha256","json_sha256","bundle_sha256"},
          "registered artifact has unsupported fields")
    _need(type(item["run_id"]) is int and type(item["artifact_id"]) is int
          and item["run_id"]>0 and item["artifact_id"]>0
          and all(isinstance(item[x],str) and HEX.fullmatch(item[x])
             for x in ("zip_sha256","json_sha256")), "artifact checksum mandatory")
    meta=_gh(f"repos/{REPO}/actions/artifacts/{item['artifact_id']}")
    _need(meta.get("name")==item["name"]
          and meta.get("expired") is False
          and meta.get("digest")=="sha256:"+item["zip_sha256"]
          and meta.get("workflow_run",{}).get("id")==item["run_id"],
          "GitHub artifact identity or SHA mismatched")
    saved_at=meta["created_at"]
    instant=datetime.fromisoformat(saved_at.replace("Z","+00:00"))
    _need(instant.tzinfo is not None,"GitHub server clock unavailable")
    if kind=="pair":
        _need(instant < cutoff, "forecast artifact was not saved before cutoff")
    else:
        _need(instant > cutoff, "result artifact cannot be preclosing")
    with tempfile.TemporaryDirectory(prefix="boat-ab-source-") as temp:
        cmd=["gh","run","download",str(item["run_id"]),
             "--repo",REPO,"--name",item["name"],"--dir",temp]
        r=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",
                         timeout=45,check=False)
        _need(r.returncode==0,"GitHub artifact content unavailable")
        target=Path(temp)/("pair.json" if kind=="pair" else "result.json")
        _need(target.is_file() and target.stat().st_size<=MAX_ORIGINAL,
              "unexpected artifact payload")
        raw=target.read_bytes()
    _need(_digest(raw)==item["json_sha256"],"downloaded original JSON hash mismatch")
    data=json.loads(raw)
    return data, saved_at, meta


def _validate_manifest(value):
    _need(isinstance(value,dict)
          and set(value)=={"schema","source_registry","races"}
          and value["schema"]=="RACE_AI_BOAT_AB_ARTIFACT_REGISTRY_V1",
          "exact prospective registry required")
    _need(isinstance(value["races"],list) and 1<=len(value["races"])<=MAX_RACES,
          "bounded explicit frozen race registry required")
    return value


def build(manifest):
    manifest=_validate_manifest(manifest)
    seen=set()
    rows=[]
    for entry in manifest["races"]:
        _need(isinstance(entry,dict)
              and set(entry)=={"race_id","cutoff_at","frozen","official_result"},
              "exact registered race metadata required")
        rid=entry["race_id"]
        _need(isinstance(rid,str) and RI.fullmatch(rid) and rid not in seen,
              "unique official race ID mandatory")
        seen.add(rid)
        cutoff=datetime.fromisoformat(entry["cutoff_at"].replace("Z","+00:00"))
        _need(cutoff.tzinfo is not None and
              cutoff.astimezone(timezone.utc).strftime("%Y-%m-%d"),
              "valid time required")
        original, saved_at, meta=_original(entry["frozen"],"pair",cutoff)
        _need(original.get("race_id")==rid
              and original.get("cutoff_at")==entry["cutoff_at"]
              and original.get("status")=="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT"
              and original.get("result_used") is False
              and original.get("paired_forecast",{}).get("bundle_sha256")==
                  entry["frozen"]["bundle_sha256"],
              "registered pair differs from verified original")
        # Cross-check the independently validated official racelist source
        # on at least the seed race, but don't claim full 12R coverage.
        if rid.endswith("-02"):
            _need(original["paired_forecast"]["program_source_sha256"]==
                  manifest["source_registry"]["source_sha256"],
                  "seed official program source does not match registry")
        row={
            "race_id":rid,"cutoff_at":entry["cutoff_at"],
            "trifecta_offered":True,
            "result_state":"PENDING","official_top3":None,
            "official_source_sha256":None,
            "official_result_captured_at":None,
            "payout_per_100_yen":None,
            "paired_audit":None,"artifact_receipt":None,
        }
        if entry["official_result"] is not None:
            settled, outcome_saved_at, _=_original(entry["official_result"],"result",cutoff)
            if settled.get("status")=="INDEPENDENT_OFFICIAL_AB_PDCA_VERIFIED":
                winner=settled.get("official_top3")
                _need(settled.get("race_id","")==rid
                      and settled.get("original_run_id")==entry["frozen"]["run_id"]
                      and settled.get("original_artifact_file_sha256")==entry["frozen"]["json_sha256"]
                      and settled.get("result_source_url")==
                          f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}",
                      "official result identity or frozen origin mismatch")
                _need(isinstance(settled.get("official_trifecta_payout_per_100_yen"),int),
                      "real 3t official payout absent")
                # Recompute the scores ONLY from the old forecast bytes and
                # official result; never re-fit or re-rank a forecast.
                verified=score_pair(original,winner,
                    settled["result_captured_at"],saved_at)
                _need(verified==settled["paired_comparison"],
                      "official A/B scoring differs from original frozen research pair")
                row.update(
                    result_state="SETTLED",
                    official_top3=winner,
                    official_source_sha256=settled["result_source_sha256"],
                    official_result_captured_at=settled["result_captured_at"],
                    payout_per_100_yen=settled["official_trifecta_payout_per_100_yen"],
                    paired_audit=verified,
                    artifact_receipt={
                      "verified_download_and_sha256":True,
                      "artifact_sha256":entry["frozen"]["zip_sha256"],
                      "original_pair_json_sha256":entry["frozen"]["json_sha256"],
                      "server_created_at":saved_at,
                      "pair_bundle_sha256":entry["frozen"]["bundle_sha256"],
                    })
            else:
                _need(settled.get("status") in
                      ("OFFICIAL_RESULT_PENDING_OR_UNSUPPORTED",
                       "OFFICIAL_RESULT_NOT_VERIFIED",
                       "OFFICIAL_RESULT_SOURCE_INVALID_OR_UNAVAILABLE"),
                      "unexpected result status; do not fabricate a settled finish")
        rows.append(row)
    return {"schema":"RACE_AI_BOAT_AB_EVIDENCE_LEDGER_V1",
            "registry":manifest["source_registry"],"rows":rows}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--output-directory",type=Path,default=Path("boat_ab_cohort_output"))
    x=p.parse_args()
    raw=x.manifest.read_bytes()
    _need(len(raw)<=300_000,"manifest too large")
    manifest=json.loads(raw)
    ledger=build(manifest)
    data=json.dumps(ledger,ensure_ascii=False,sort_keys=True,
                    separators=(",",":"),allow_nan=False).encode("utf-8")
    result=report(data)
    x.output_directory.mkdir(parents=True,exist_ok=True)
    (x.output_directory/"ledger.json").write_bytes(data)
    with (x.output_directory/"report.json").open("x",encoding="utf-8") as handle:
        json.dump(result,handle,sort_keys=True,ensure_ascii=False,
                  separators=(",",":"),allow_nan=False)
    print(json.dumps({k:result[k] for k in
        ("conclusion_scope","total_discovered","officially_settled_eligible",
         "paired_forecast_count","unforecast_or_unverified","statement",
         "model_auto_promoted")},ensure_ascii=False))


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError,TimeoutError) as exc:
        print("PROSPECTIVE_COHORT_SAFE_STOP:"+type(exc).__name__,file=sys.stderr)
        raise SystemExit(2)
