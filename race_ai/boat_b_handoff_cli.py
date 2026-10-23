"""Explicit, offline B-export handoff to private, timestamped research preparation.

This command cannot fetch, notarize or publish. It requires a separately
reviewed source-purpose policy and never treats local file creation as a
trusted external pre-cutoff freeze.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .boat_b_program_bridge import stage_official_b_handoff, link_b_stage_to_features
from .permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError, read_json_bytes, MAX_SOURCE_BYTES,
    _private_write,
)


def _read(path):
    with Path(path).open("rb") as handle:
        return read_json_bytes(handle.read(MAX_SOURCE_BYTES + 1))


def main(argv=None, *, now=None):
    parser=argparse.ArgumentParser(
        description="Offline signed-rights B extract -> source/entrant verified model input"
    )
    parser.add_argument("--b-handoff", required=True, help="offline PR64 normalized B export")
    parser.add_argument("--policy", required=True, help="independently reviewed rights policy")
    parser.add_argument("--race-id", required=True, help="YYYYMMDD-venue-RR in source")
    parser.add_argument("--feature-feed", help="optional fully normalized authorized snapshot")
    parser.add_argument("--output", required=True, help="new non-Git private file")
    parser.add_argument("--key-env", default="RACE_AI_SOURCE_REVIEW_KEY")
    args=parser.parse_args(argv)
    try:
        instant=now if now is not None else datetime.now(timezone.utc)
        secret=os.environ.get(args.key_env,"").encode("utf-8")
        policy=PermissionPolicy(_read(args.policy),secret,at=instant)
        handoff=_read(args.b_handoff)
        stage=stage_official_b_handoff(handoff,policy,now=instant,race_id=args.race_id)
        record=stage
        if args.feature_feed:
            record=link_b_stage_to_features(
                stage, Path(args.feature_feed).read_bytes(), policy, at=instant
            )
        _private_write(args.output,record)
        print(json.dumps({
            "race_id":args.race_id,
            "status":record.get("status","PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN"),
            "source_program_staged":True,
            "models_ran":bool(args.feature_feed),
            "official_prediction":False,
            "external_pre_cutoff_receipt":False,
            "result_settled":False,
        },ensure_ascii=False))
        return 0
    except (SourceDeliveryError, OSError, ValueError, TypeError, KeyError) as exc:
        print("B_HANDOFF_BLOCKED: "+str(exc), file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
