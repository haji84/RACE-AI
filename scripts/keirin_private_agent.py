"""Owner-side KEIRIN unattended spool processor (no external provider GET).

Example:
  python -m scripts.keirin_private_agent --db /private/race-ai/owner.db \
      --inbox /private/race-ai/inbox --personal-only --loop

Runs the *actual* PR71 model and SQLite result/forecast pipeline when a
permitted owner-controlled feeder deposits complete pre-race/result JSON.
No source-data fabrications, odds, auto-wagering or public raw JSON logs.
The owner is responsible for obtaining and retaining each source legally.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from race_ai.keirin_owner_sqlite import PrivateKeirinStore, OwnerStoreError
from race_ai.keirin_private_spool import KeirinPrivateSpool, InboxError
from race_ai.four_sport_model_suite import run_suite, verify_suite
from race_ai.keirin_result_delivery import canonical

ALLOWED_HOSTS=frozenset((
    "keirin.jp","www.keirin.jp","keirin.kdreams.jp",
    "keirin.netkeiba.com",
))
PERSONAL_MARKER="RACE_AI_PERSONAL_NONCOMMERCIAL_RESEARCH_V1"
REQUIRED_PURPOSES=("schedule","pre_race","private_retention","model_inference")


def source_ref_allowed(source_ref, rights_ref, purpose):
    """Research-only acceptance of personally supplied pre-race observations.

    This is *not* a legally verified grant for automated site extraction.
    """
    if purpose!="analysis" or rights_ref!=PERSONAL_MARKER:
        return False
    if type(source_ref) is not str:
        return False
    try:
        parsed=urlsplit(source_ref)
        return (parsed.scheme=="https" and parsed.hostname in ALLOWED_HOSTS
                and parsed.username is None and parsed.password is None
                and parsed.port is None and bool(parsed.path.startswith("/")))
    except ValueError:
        return False


def personal_certificate(snapshot, intent):
    """Explicitly self-attested PRIVATE RESEARCH ONLY, never official."""
    if type(snapshot) is not dict or type(intent) is not dict:
        return None
    if snapshot.get("permission_ref")!=PERSONAL_MARKER:
        return None
    evidence=snapshot.get("facts",{}).get("pr71_evidenced_snapshot",{})
    if evidence.get("scope")!="OPERATOR_SUPPLIED_RESEARCH":
        return None
    if evidence.get("race",{}).get("race_id")!=intent.get("race_id"):
        return None
    from race_ai.keirin_result_delivery import utc
    from hashlib import sha256
    now=datetime.now(timezone.utc)
    try:
        cutoff=utc(intent["official_cutoff_at"])
        stamp=utc(snapshot["as_of"])
    except (ValueError,KeyError,TypeError):
        return None
    if not (stamp<=now<cutoff):
        return None
    actual=sha256(canonical(snapshot)).hexdigest()
    if intent.get("pre_race_snapshot_sha256")!=actual:
        return None
    return {
        "race_id":intent["race_id"],
        "source_sha256":actual,
        "permission_ref":PERSONAL_MARKER,
        "official_cutoff_at":intent["official_cutoff_at"],
        "verified_purposes":list(REQUIRED_PURPOSES),
        "valid_until":intent["official_cutoff_at"],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,help="persistent, owner-only .db file")
    p.add_argument("--inbox",required=True,help="private daily/pre/results input folders")
    p.add_argument("--personal-only",action="store_true",
                   help="allow only owner-provided noncommercial research observations")
    p.add_argument("--loop",action="store_true",
                   help="keep processing, with 2 minute interval")
    p.add_argument("--interval-seconds",type=int,default=120)
    args=p.parse_args(argv)
    if not args.personal_only or not 60<=args.interval_seconds<=3600:
        print('{"state":"OWNER_PERSONAL_SCOPE_OR_RATE_INVALID"}')
        return 2
    db_path=Path(args.db).expanduser()
    inbox=Path(args.inbox).expanduser()
    if not db_path.is_absolute() or not inbox.is_absolute():
        print('{"state":"OWNER_PRIVATE_ABSOLUTE_PATHS_REQUIRED"}')
        return 2
    if os.environ.get("GITHUB_ACTIONS")=="true" and (
            os.environ.get("RACE_AI_PERSISTENT_PRIVATE_VOLUME")!="ACKNOWLEDGED"):
        print('{"state":"GITHUB_EPHEMERAL_DB_NOT_DURABLE"}')
        return 2
    try:
        with PrivateKeirinStore(db_path) as store:
            engine=KeirinPrivateSpool(
                store,model_suite=run_suite,model_verifier=verify_suite,
                source_observation_gate=source_ref_allowed,
                source_attestor=personal_certificate,
                witness=None)
            while True:
                result=engine.tick(inbox)
                print(json.dumps(result,ensure_ascii=False,
                                 sort_keys=True),flush=True)
                if not args.loop:
                    break
                time.sleep(args.interval_seconds)
    except (InboxError,OwnerStoreError,OSError,ValueError):
        print('{"state":"PRIVATE_OWNER_RUNTIME_FAILED_CLOSED"}')
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__=="__main__":
    raise SystemExit(main())
