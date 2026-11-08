"""Inspect one saved historical KEIRIN sparse research file without provider calls.

Prints only aggregate PR71 feature coverage, not athlete names or values.
Does not run a model, create retrospective "pre-cutoff" proofs or write
any confidential source to GitHub/Actions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from race_ai.keirin_historical_sparse_feature_probe import (
    HistoricalSparseProbeError, probe_saved_sparse_research,
    probe_saved_second_race_reference
)


def _unique(pairs):
    obj={}
    for key,val in pairs:
        if key in obj:
            raise HistoricalSparseProbeError("DUPLICATE_PRIVATE_ARCHIVE_KEY")
        obj[key]=val
    return obj


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner-archive",required=True)
    args=ap.parse_args(argv)
    file=Path(args.owner_archive).expanduser()
    try:
        if not file.is_absolute() or file.is_symlink() or not file.is_file() or (
                not 0<file.stat().st_size<=2_000_000):
            raise HistoricalSparseProbeError("PRIVATE_ARCHIVE_FILE_REQUIRED")
        data=json.loads(file.read_text(encoding="utf-8"),
                        object_pairs_hook=_unique,
                        parse_constant=lambda x: (_ for _ in ()).throw(
                            HistoricalSparseProbeError("NONFINITE_SOURCE_JSON")))
        if type(data) is not dict:
            raise HistoricalSparseProbeError("HISTORICAL_OBJECT_REQUIRED")
        if data.get("schema") == "RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1":
            result=probe_saved_sparse_research(data)
        elif data.get("schema") == "MATS2R_RESEARCH_SCENARIO_PREDICTION_V1":
            result=probe_saved_second_race_reference(data)
        else:
            raise HistoricalSparseProbeError("UNSUPPORTED_HISTORICAL_ARCHIVE")
        print(json.dumps(result["public_summary"],ensure_ascii=False,
                         separators=(",",":"),sort_keys=True,allow_nan=False))
        return 0
    except (OSError,KeyError,ValueError,TypeError,
            HistoricalSparseProbeError,UnicodeError):
        print('{"state":"HISTORICAL_SOURCE_RECONSTRUCTION_BLOCKED_OR_INVALID"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
