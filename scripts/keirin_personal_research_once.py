"""Private KEIRIN 1-race comparison: operator-supplied JSON or one GET.

No recurring scraping, bypass, provider rights grant or public publication.
Output file is private, create-only and never overwrites the original.
"""
from __future__ import annotations

import argparse
import json
from race_ai.keirin_personal_research_once import (
    MAX_REFERENCE_BYTES, MAX_PROBE_BYTES, PersonalResearchError,
    compare_personal_once, one_private_fetch_and_compare,
    read_private_json, save_private_once
)
from race_ai.keirin_mobile_one_shot import MobileProbeError


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", required=True)
    p.add_argument("--candidate", help="existing private, unverified result JSON")
    p.add_argument("--fetch-one", action="store_true",
                   help="explicit one GET; never schedule automatically")
    p.add_argument("--ymd", help="YYYYMMDD, for --fetch-one")
    p.add_argument("--venue", type=int, help="two-digit KEIRIN venue code")
    p.add_argument("--race-no", type=int, help="race number")
    p.add_argument("--route", choices=("legacy", "new"), default="legacy")
    p.add_argument("--race-id", required=True, help="YYYYMMDDJJRR")
    p.add_argument("--cutoff-at", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--personal-only", action="store_true", required=True)
    args = p.parse_args(argv)
    try:
        if bool(args.candidate) == args.fetch_one:
            raise PersonalResearchError("EXACTLY_ONE_INPUT_MODE_REQUIRED")
        reference = read_private_json(args.reference, limit=MAX_REFERENCE_BYTES)
        scope = ("USER_PRIVATE_NONCOMMERCIAL_RESEARCH"
                 if args.personal_only else "")
        if args.fetch_one:
            result = one_private_fetch_and_compare(
                original_reference=reference, race_id=args.race_id,
                cutoff_at=args.cutoff_at, ymd=args.ymd,
                venue_code=args.venue, race_no=args.race_no,
                personal_scope=scope, route=args.route,
                one_get_acknowledgement="USER_EXPLICIT_ONE_RESULT_GET")
        else:
            probe = read_private_json(args.candidate, limit=MAX_PROBE_BYTES)
            result = compare_personal_once(
                result_probe=probe, original_reference=reference,
                race_id=args.race_id, cutoff_at=args.cutoff_at,
                personal_scope=scope)
        saved = save_private_once(result, args.output)
        print(json.dumps(saved, ensure_ascii=False, sort_keys=True))
        return 0
    except (PersonalResearchError, MobileProbeError, OSError):
        # No raw provider result, private forecast, or sensitive upstream errors.
        print(json.dumps({"status":"PERSONAL_RESEARCH_NOT_SAVED"},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
