"""Read privately retained PRE-TARGET historical events; print only safe counts.

No provider requests, no source names, credentials, original measurements,
rider identities or candidate score values to stdout/GitHub. This does not
approve PR71 inputs or claim a prospective pre-cutoff forecast.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from race_ai.keirin_historical_prior_signal_rules import (
    PriorSignalError, compute_prior_signal_candidates
)


def _unique(pairs):
    result={}
    for name,value in pairs:
        if name in result:
            raise PriorSignalError("DUPLICATE_SOURCE_JSON_KEY")
        result[name]=value
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-prior-events",required=True)
    args=parser.parse_args(argv)
    try:
        path=Path(args.owner_prior_events).expanduser()
        if not (path.is_absolute() and
                path.is_file() and not path.is_symlink() and
                0<path.stat().st_size<=2_000_000):
            raise PriorSignalError("UNSAFE_PRIVATE_ARCHIVE_PATH")
        record=json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique,
                          parse_constant=lambda val: (_ for _ in ()).throw(
                              PriorSignalError("NONFINITE_SOURCE_JSON")))
        result=compute_prior_signal_candidates(record)
        public={
            "schema":result["schema"],
            "formula_version":result["formula_version"],
            "source_packet_sha256":result["source_packet_sha256"],
            "event_count_provided":result["event_count_provided"],
            "comparison_eligible_past_events":
                result["comparison_eligible_past_events"],
            "feature_coverage":{
                name:{
                    "sample_count":entry["sample_count"],
                    "meets_fixed_minimum":entry["candidate_value"] is not None,
                    "status":entry["status"],
                    "approved_for_pr71_input":False,
                }
                for name,entry in result["features"].items()},
            "source_use_rights_verified":False,
            "original_pr71_forecast_exists":False,
            "no_hindsight_target_results":True,
        }
        print(json.dumps(public,ensure_ascii=False,sort_keys=True,
                         separators=(",",":"),allow_nan=False))
        return 0
    except (PriorSignalError,ValueError,TypeError,KeyError,OSError,
            UnicodeError):
        print('{"state":"HISTORICAL_PRIOR_SIGNAL_INPUT_HOLD"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
