"""Audit the EXISTING encrypted Git ref, without creating replacement state.

Supply a checkout of state/keirin-encrypted-history. This only reads its
latest.json, scope, proof and (optionally) an existing owner SQLite.
It does not decrypt, publish private information, authorize a live forecast,
retrieve odds, or claim external timestamp proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from race_ai.keirin_existing_asset_reuse import (
    ExistingStateError,report_existing_asset_reuse
)


def _json_at(root, filename):
    path=root/filename
    if not (path.is_file() and not path.is_symlink()
            and 0<path.stat().st_size<=8192):
        raise ExistingStateError("EXISTING_ARCHIVE_METADATA_REQUIRED")
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:
                raise ExistingStateError("DUPLICATE_ARCHIVE_METADATA_KEY")
            value[k]=v
        return value
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=unique,
                          parse_constant=lambda v: (_ for _ in ()).throw(
                              ExistingStateError("NONFINITE_ARCHIVE_METADATA")))
    except (ValueError,UnicodeError,TypeError):
        raise ExistingStateError("ARCHIVE_METADATA_INVALID") from None


def inspect_tree(tree, owner_db=None):
    root=Path(tree).expanduser()
    if not (root.is_absolute() and root.is_dir()
            and not root.is_symlink()):
        raise ExistingStateError("EXISTING_ARCHIVE_TREE_REQUIRED")
    head=_json_at(root,"state/keirin/v1/latest.json")
    if type(head) is not dict:
        raise ExistingStateError("ARCHIVE_HEAD_OBJECT_REQUIRED")
    scope_path=head.get("scope_file")
    proof_path=head.get("proof_file")
    if not (type(scope_path) is str and type(proof_path) is str
            and scope_path.startswith("state/keirin/v1/snapshots/")
            and proof_path.startswith("state/keirin/v1/snapshots/")
            and ".." not in Path(scope_path).parts
            and ".." not in Path(proof_path).parts):
        raise ExistingStateError("ARCHIVE_METADATA_PATH_INVALID")
    return report_existing_asset_reuse(
        head,_json_at(root,scope_path),_json_at(root,proof_path),
        owner_db=owner_db)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-tree",required=True)
    parser.add_argument("--owner-db",default=None)
    opts=parser.parse_args(argv)
    try:
        report=inspect_tree(opts.state_tree,opts.owner_db)
    except (ExistingStateError,OSError,KeyError,TypeError):
        print('{"status":"EXISTING_STATE_NOT_VERIFIED","new_empty_db_created":false}')
        return 2
    print(json.dumps(report,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
