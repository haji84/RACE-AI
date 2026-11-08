"""Owner-private, read-only historical KEIRIN Top8 versus payout reference audit.

This does NOT execute a new post-result prediction; checks a previously saved
owner reference and a separate later results research ledger. No web requests,
no source data in logs, no claimed official Hit@8.
"""
from __future__ import annotations

import argparse
import json

from race_ai.keirin_reference_history_recheck import (
    HistoryRecheckError, recheck_original_saved_baseline_against_published
)
from scripts.keirin_reference_history_audit import read_owner_json


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner-original",required=True)
    ap.add_argument("--owner-published-results",required=True)
    args=ap.parse_args(argv)
    try:
        outcome=recheck_original_saved_baseline_against_published(
            read_owner_json(args.owner_original),
            read_owner_json(args.owner_published_results))
    except (OSError,HistoryRecheckError,ValueError,
            KeyError,TypeError,UnicodeError):
        print('{"state":"HISTORICAL_OWNER_REFERENCE_NOT_VERIFIED"}')
        return 2
    print(json.dumps(outcome,ensure_ascii=False,sort_keys=True,
                     separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
