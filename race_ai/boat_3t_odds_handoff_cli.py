"""Explicit operator-supplied BOATRACE HTML-to-odds private handoff.

Offline only. The operator must separately establish real rights for copying,
analysis, private retention, derived display and publication. Policy HMAC is
only proof of a reviewed statement, NOT an upstream legal grant.

Never fetches the site, changes the forecast, schedules jobs or publishes.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .boat_official_3t_odds_adapter import normalize_html, MAX_HTML
from .permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError, _private_write, read_json_bytes
)


def main(argv=None, *, clock=None):
    ap=argparse.ArgumentParser(description="Offline 120-combination odds format intake")
    ap.add_argument("--html-file",required=True)
    ap.add_argument("--policy",required=True)
    ap.add_argument("--source-url",required=True)
    ap.add_argument("--rights-ref",required=True)
    ap.add_argument("--race-id",required=True)
    ap.add_argument("--venue",required=True)
    ap.add_argument("--official-cutoff",required=True)
    ap.add_argument("--output",required=True,
                    help="new private JSON outside Git; refuses overwrite")
    ap.add_argument("--key-env",default="RACE_AI_SOURCE_REVIEW_KEY")
    args=ap.parse_args(argv)
    try:
        now=clock or datetime.now(timezone.utc)
        if not isinstance(now,datetime) or now.utcoffset() is None:
            raise SourceDeliveryError("aware clock required")
        secret=os.environ.get(args.key_env,"").encode("utf-8")
        with Path(args.policy).open("rb") as f:
            document=read_json_bytes(f.read(4*1024*1024+1))
        policy=PermissionPolicy(document,secret,at=now.isoformat())
        with Path(args.html_file).open("rb") as f:
            original=f.read(MAX_HTML+1)
        feed=normalize_html(original,source_url=args.source_url,
                            rights_ref=args.rights_ref,policy=policy,
                            race_id=args.race_id,venue_name=args.venue,
                            cutoff_at=args.official_cutoff,
                            ingested_at=now.isoformat())
        _private_write(args.output,feed)
        print(json.dumps({
            "status":"PRIVATE_QUOTE_FORMAT_ONLY_SOURCE_TIME_UNVERIFIED",
            "race_id":feed["race_id"],
            "tickets":len(feed["odds"]),
            "provider_published_at_verified":False,
            "actual_website_ingest":False,
            "automatic_provider_refresh":False
        },ensure_ascii=False))
        return 0
    except (SourceDeliveryError,OSError,ValueError,TypeError,KeyError) as exc:
        # Never echo raw HTML or a provider key.
        print("ODDS_OFFLINE_HANDOFF_BLOCKED: "+str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
