"""Owner-private all-saved-history research replay, using existing SQLite.

Never creates a blank database, never fetches websites, never publishes raw
picks, odds or results. Not official Hit@8 or proof of automatic data rights.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_variable_integration import PrivateVariableLedger


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True)
    p.add_argument("--owner-private-research",action="store_true")
    a=p.parse_args(argv)
    file=Path(a.db).expanduser()
    if (not a.owner_private_research or not file.is_absolute()
            or file.is_symlink() or not file.is_file()
            or not 0<file.stat().st_size<=50_000_000_000):
        print('{"state":"EXISTING_PRIVATE_SQLITE_REQUIRED"}')
        return 2
    if os.environ.get("GITHUB_ACTIONS")=="true" and (
            os.environ.get("RACE_AI_PERSISTENT_PRIVATE_VOLUME")!="ACKNOWLEDGED"):
        print('{"state":"GITHUB_EPHEMERAL_PRIVATE_STATE_UNVERIFIED"}')
        return 2
    try:
        with PrivateKeirinStore(file) as store:
            report=PrivateVariableLedger(store).reconcile_saved_history()
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        print('{"state":"RECONCILIATION_FAILED_CLOSED_CHECK_PRIVATE_DB"}')
        return 2
    # Only totals, never private record URLs, odds, names or selections.
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,
                     separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
