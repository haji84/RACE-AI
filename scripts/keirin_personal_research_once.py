"""Personal one-race KEIRIN study: source candidate vs unchanged 8 picks.

No HTTP or provider API call. A single existing, personally examined result
probe JSON is required. Output is 0600 and create-only, never Git-committed.
"""
from __future__ import annotations

import argparse
import json
from race_ai.keirin_personal_research_once import (
    MAX_REFERENCE_BYTES, MAX_PROBE_BYTES, PersonalResearchError,
    compare_personal_once, read_private_json, save_private_once
)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", required=True,
                   help="original non-calibrated pre-race forecast JSON")
    p.add_argument("--candidate", required=True,
                   help="one existing non-authoritative result probe JSON")
    p.add_argument("--race-id", required=True,
                   help="YYYYMMDD + two-digit venue code + two-digit race number")
    p.add_argument("--cutoff-at", required=True,
                   help="pre-race independently checked JST cutoff with timezone")
    p.add_argument("--output", required=True, help="new private result file")
    p.add_argument("--personal-only", action="store_true", required=True)
    args = p.parse_args(argv)
    try:
        reference = read_private_json(args.reference, limit=MAX_REFERENCE_BYTES)
        candidate = read_private_json(args.candidate, limit=MAX_PROBE_BYTES)
        result = compare_personal_once(
            result_probe=candidate, original_reference=reference,
            race_id=args.race_id, cutoff_at=args.cutoff_at,
            personal_scope=("USER_PRIVATE_NONCOMMERCIAL_RESEARCH"
                            if args.personal_only else "")
        )
        saved = save_private_once(result, args.output)
        print(json.dumps(saved, ensure_ascii=False, sort_keys=True))
        return 0
    except (PersonalResearchError, OSError) as exc:
        # Never echo source text, private forecast or credentials.
        print(json.dumps({"status": "PERSONAL_RESEARCH_NOT_SAVED",
                          "error_type": type(exc).__name__},
                          ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
