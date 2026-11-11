"""Inspect PRIVATE owner historical JSON sources offline and emit SHA/counts only.

No source bytes, names, rider identifiers, payouts, odds or raw entry lists in
public GitHub, stdout, or artifacts. A status HOLD is not a failed test.
"""
import argparse
import json
from pathlib import Path
from race_ai.keirin_historical_archive_inventory import (
    private_batch_inventory, HistoricalInventoryError
)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",action="append",required=True)
    args=ap.parse_args(argv)
    try:
        records=[]
        for value in args.source:
            p=Path(value).expanduser()
            if not p.is_absolute() or p.is_symlink() or not p.is_file() or (
                    p.stat().st_size > 2_000_000):
                raise HistoricalInventoryError("OWNER_PRIVATE_SOURCE_UNSAFE")
            with p.open(encoding="utf-8") as f:
                def unique(pairs):
                    out={}
                    for k,v in pairs:
                        if k in out:
                            raise HistoricalInventoryError("DUPLICATE_JSON_KEYS")
                        out[k]=v
                    return out
                records.append(json.load(f,object_pairs_hook=unique,
                                         parse_constant=lambda x: (_ for _ in ()).throw(
                                             HistoricalInventoryError("NONFINITE_JSON"))))
        report=private_batch_inventory(records)
    except (ValueError,KeyError,TypeError,OSError,
            UnicodeError,HistoricalInventoryError):
        print('{"state":"HISTORICAL_SOURCE_INVENTORY_UNVERIFIABLE"}')
        return 2
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,
                     separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
