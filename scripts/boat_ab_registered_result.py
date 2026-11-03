"""One safe postclose official result for earliest registered unscored A/B pair.

Vercel-free, no model inference, no old forecast mutation. GitHub API run/
artifact original is downloaded and verified against a predeclared manifest.
Official result is checked with the previously pinned PR64 parser. Output is
a separate immutable GitHub Actions artifact, later registered for cohort use.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import os
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PIN=ROOT/"pr64-reference"
if not (PIN/"race_ai"/"official_race_updates.py").is_file():
    raise SystemExit("PR64_PARSER_REFERENCE_NOT_FOUND")
sys.path.insert(0,str(PIN))

from race_ai.official_racelist_adapter import parse_official_racelist,endpoint,JST
from race_ai.official_race_updates import parse_update,endpoint as result_endpoint
from race_ai.core import SourceError
from scripts.boat_actual_one_shot_probe import fetch
import scripts.boat_actual_one_shot_probe as fetcher
from scripts.boat_ab_cohort_from_actions import _original
from race_ai.boat_ab_result_audit import score_pair

OUT=ROOT/"boat_ab_registered_result_output"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def emit(state, race_id=None, **extra):
    OUT.mkdir(exist_ok=True)
    packet={"schema":"RACE_AI_BOAT_AB_REAL_RESULT_PILOT_V1",
            "status":state, "race_id":race_id,
            "result_verified_at":stamp(),
            "source_gets":fetcher.calls,
            "forecast_recreated_after_result":False,
            "actual_purchase":False,
            "model_auto_promoted":False, **extra}
    with (OUT/"result.json").open("x",encoding="utf-8") as o:
        json.dump(packet,o,sort_keys=True,ensure_ascii=False,
                  separators=(",",":"),allow_nan=False)
    print(json.dumps({key:packet.get(key) for key in
          ("status","race_id","official_top3","source_gets",
           "official_trifecta_payout_per_100_yen")},ensure_ascii=False))
    return packet


def run(manifest_path):
    fetcher.calls=0
    registry=json.loads(manifest_path.read_text(encoding="utf-8"))
    if registry.get("schema")!="RACE_AI_BOAT_AB_ARTIFACT_REGISTRY_V1":
        raise ValueError("registered source manifest required")
    now=datetime.now(timezone.utc)
    choices=[]
    for r in registry.get("races",[]):
        cutoff=datetime.fromisoformat(r["cutoff_at"].replace("Z","+00:00"))
        if r.get("official_result") is None and cutoff+timedelta(seconds=120) < now:
            choices.append((cutoff,r))
    if not choices:
        return emit("NO_UNSCORED_RACE_AFTER_CLOSE")
    cutoff,entry=min(choices,key=lambda p:(p[0],p[1]["race_id"]))
    rid=entry["race_id"]
    frozen,created,meta=_original(entry["frozen"],"pair",cutoff)
    if frozen.get("race_id")!=rid or frozen.get("cutoff_at")!=entry["cutoff_at"]:
        raise ValueError("stored future A/B race mismatch")
    if not (isinstance(rid,str) and re.fullmatch(r"\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])",rid)):
        raise ValueError("invalid race identity")
    day=date(int(rid[:4]),int(rid[4:6]),int(rid[6:8]))
    venue=rid[9:11]
    number=int(rid[-2:])
    if now.astimezone(JST).date()!=day:
        return emit("OFFICIAL_RESULT_ONLY_CURRENT_JST_DAY",rid)
    try:
        program_url=endpoint(day,venue,number)
        raw,observed_program,program_hash=fetch(program_url)
        program=parse_official_racelist(raw,day=day,venue=venue,race_no=number,
                                       source_url=program_url,captured_at=observed_program.isoformat())
        if program["race_id"]!=rid or program["closed_at"]!=entry["cutoff_at"]:
            raise ValueError("result program identity or cutoff changed")
        official_url=result_endpoint(day,venue,number,"raceresult")
        html,observed,raw_sha=fetch(official_url)
        result=parse_update(html,kind="raceresult",day=day,venue=venue,race_no=number,
                            source_url=official_url,captured_at=observed.isoformat(),
                            entries=program["boats"])
        data=result.get("data")
        if (result["status"]!="AVAILABLE" or not isinstance(data,dict)
                or data.get("finish_confirmed") is not True):
            return emit("OFFICIAL_RESULT_PENDING_OR_UNSUPPORTED",rid,
                        source_sha256=raw_sha,official_status=result.get("status"),
                        original_run_id=entry["frozen"]["run_id"])
        if (data.get("status")!="settled" or data.get("refund_boats")
                or data.get("refunds") not in (None,[])):
            return emit("OFFICIAL_RESULT_SPECIAL_OR_REFUNDED",rid,
                        source_sha256=raw_sha,
                        official_status=data.get("status"))
        triple=data.get("top3")
        if (not isinstance(triple,list) or len(triple)!=3 or
                any(type(x) is not int or x not in range(1,7) for x in triple)
                or len(set(triple))!=3):
            return emit("OFFICIAL_TOP3_UNVERIFIED",rid,source_sha256=raw_sha)
        payout=[p["payout_per_100_yen"] for p in data.get("payouts",[])
                if p.get("bet_type")=="trifecta" and p.get("combination")==triple]
        if len(payout)!=1 or type(payout[0]) is not int:
            return emit("OFFICIAL_TRIFECTA_PAYOUT_UNVERIFIED",rid,source_sha256=raw_sha)
        outcome="-".join(map(str,triple))
        scored=score_pair(frozen,outcome,observed.isoformat(),created)
        return emit("INDEPENDENT_OFFICIAL_AB_PDCA_VERIFIED",rid,
                    original_run_id=entry["frozen"]["run_id"],
                    original_artifact_file_sha256=entry["frozen"]["json_sha256"],
                    forecast_artifact_server_saved_at=created,
                    official_top3=outcome,
                    official_trifecta_payout_per_100_yen=payout[0],
                    result_source_url=official_url,result_source_sha256=raw_sha,
                    result_captured_at=observed.isoformat(),
                    program_source_sha256=program_hash,
                    paired_comparison=scored,
                    next_race_action="EVALUATE_WITH_FUTURE_HOLDOUT_NO_MODEL_PROMOTION")
    except (SourceError,OSError,ValueError,TypeError,KeyError,TimeoutError) as exc:
        return emit("OFFICIAL_RESULT_NOT_VERIFIED",rid,error_class=type(exc).__name__)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",type=Path,required=True)
    args=ap.parse_args()
    run(args.manifest)


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("BOAT_AB_REGISTERED_RESULT_SAFE_STOP: "+type(exc).__name__,file=sys.stderr)
        raise SystemExit(2)
