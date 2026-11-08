"""Run owner-private KEIRIN 3-file research reference recheck, without network.

This does not authenticate official results or pre-cutoff prediction creation.
Pass the three previously saved JSON files as explicit local paths; no raw
data is uploaded or committed. Output is a summary with no rider details.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from race_ai.keirin_reference_history_recheck import (
    HistoryRecheckError, recheck_derived_references
)


def read_owner_json(filename):
    p=Path(filename).expanduser()
    if not p.is_file() or p.is_symlink() or p.stat().st_size>4_000_000:
        raise HistoryRecheckError("PRIVATE_HISTORY_FILE_MISSING_OR_UNSAFE")
    with p.open("r",encoding="utf-8") as fp:
        # Refuse repeated JSON keys; standard json.loads silently keeps last.
        def strict_pairs(pairs):
            d={}
            for k,v in pairs:
                if k in d:
                    raise HistoryRecheckError("DUPLICATE_JSON_OBJECT_KEY")
                d[k]=v
            return d
        return json.load(fp,object_pairs_hook=strict_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(
                             HistoryRecheckError("NONFINITE_JSON_NUMBER")))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner-reference-a",required=True)
    ap.add_argument("--owner-reference-b",required=True)
    ap.add_argument("--owner-reference-c",required=True)
    args=ap.parse_args(argv)
    try:
        report=recheck_derived_references(
            read_owner_json(args.owner_reference_a),
            read_owner_json(args.owner_reference_b),
            read_owner_json(args.owner_reference_c))
    except (HistoryRecheckError, OSError, ValueError, TypeError,
            UnicodeError, KeyError):
        print('{"state":"PRIVATE_REFERENCE_UNVERIFIED_OR_MISMATCH"}')
        return 2
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,
                     separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
