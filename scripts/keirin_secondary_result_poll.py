"""One genuine public-result pair; research candidate only, never official.

Uses one known Kdreams race-detail link and the documented netkeirin public
result path, then validates both HTML day/race numbers and SHA in memory.
Never fetches or re-generates a pre-cutoff forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import json
import os

from race_ai import keirin_secondary_result_consensus as consensus
from scripts import keirin_capture_public_two_sources as source

SCHEMA = "RACE_AI_KEIRIN_TWO_SOURCE_POSTRACE_POLL_V1"


def verified_pair_urls(manifest, race_id):
    source.manifest_check(
        manifest,registered_ids=[r["race_id"] for r in manifest.get("races",[])])
    candidates = [r for r in manifest["races"] if r["race_id"] == race_id]
    consensus.require(len(candidates) == 1,
                      "RESULT_RACE_NOT_IN_CURRENT_MANIFEST")
    base = candidates[0]["kdreams_url"]
    parts = urlsplit(base)
    consensus.require(parts.query in ("", "pageType=result"),
                      "RESULT_PROVIDER_QUERY_UNEXPECTED")
    kd = base if parts.query == "pageType=result" else base + "?pageType=result"
    net = "https://keirin.netkeiba.com/race/result/?race_id=" + race_id
    consensus.check_race_url(provider="Kdreams",url=kd,race_id=race_id)
    consensus.check_race_url(provider="netkeirin",url=net,race_id=race_id)
    return kd, net


def poll(*, manifest, race_id, fetch=None, clock=None):
    fetch = fetch or source.fetch_once
    clock = clock or (lambda:datetime.now(timezone.utc))
    kd,net = verified_pair_urls(manifest,race_id)
    first=fetch(kd)
    first_at=clock().astimezone(timezone.utc).isoformat()
    # Never retry provider denials with hidden APIs or alternate hosts.
    obs1=consensus.parse_observation(
        raw=first,provider="Kdreams",source_url=kd,
        race_id=race_id,observed_at=first_at)
    second=fetch(net)
    second_at=clock().astimezone(timezone.utc).isoformat()
    obs2=consensus.parse_observation(
        raw=second,provider="netkeirin",source_url=net,
        race_id=race_id,observed_at=second_at)
    return consensus.compare_sources(obs1,obs2)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",required=True)
    p.add_argument("--race-id",required=True)
    p.add_argument("--report",required=True)
    a=p.parse_args(argv)
    try:
        manifest=json.loads(Path(a.manifest).read_text(encoding="utf-8"))
        result=poll(manifest=manifest,race_id=a.race_id)
        target=Path(a.report)
        root=os.environ.get("RUNNER_TEMP")
        consensus.require(
            root and target.is_absolute() and not target.exists() and
            not target.is_symlink() and
            Path(root).resolve() in target.resolve().parents,
            "RESULT_RECEIPT_PRIVATE_TEMP_REQUIRED")
        body=json.dumps(result,ensure_ascii=False,sort_keys=True,
                        separators=(",",":")).encode("utf-8")+b"\n"
        source._write_once(target,body)
        print(json.dumps({"race_id":a.race_id,"state":result["state"],
                          "official_primary_result_authenticated":False},
                         sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError,
            consensus.ResultConsensusError,source.SourceCaptureError) as exc:
        code=str(exc)
        if (not code.isascii() or len(code)>90 or
            not code.replace("_","").isalnum() or
            not code.replace("_","").isupper()):
            code="UNVERIFIED_RESULT_OR_PROVIDER_FAILURE"
        print(json.dumps({"state":"HOLD_RESULT_NOT_INDEPENDENTLY_CONFIRMED",
                          "reason":code,
                          "official_primary_result_authenticated":False},
                         sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
