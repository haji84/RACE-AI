"""Create fresh authored normal/rollover forecasts before cutoff.

The input and output must be private local paths outside Git. The output uses
the existing Site-data import format. This command cannot backdate, overwrite,
import a legacy confidence label, publish a feed, or place a wager.
"""
from __future__ import annotations

import argparse
import json
import os

from race_ai import keirin_authored_confidence as authored
from race_ai.keirin_note_view import _pairs


def main(argv=None, *, clock=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="0600 new-forecast request JSON")
    parser.add_argument("--output", required=True, help="empty existing 0700 directory")
    args = parser.parse_args(argv)
    source = authored.private_path(args.input, directory=False)
    authored.need(source.stat().st_size <= 8 * 1024 * 1024, "REQUEST_TOO_LARGE")
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        request = json.load(stream, object_pairs_hook=_pairs,
                            parse_constant=lambda _: authored.need(False, "NONFINITE_JSON"))
    result = authored.write_new_site(request, site_root=args.output, clock=clock)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
