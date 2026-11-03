"""One explicit KEIRIN.JP race result GET, metadata only; not an auto poller."""
from __future__ import annotations

import argparse
import json

from race_ai.keirin_official_result_page import (
    ACK, OfficialResultTransportError, probe_one_result
)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kcd", type=int, required=True)
    p.add_argument("--ymd", required=True)
    p.add_argument("--rno", type=int, required=True)
    p.add_argument("--ack-private-research-single-get",
                   action="store_true", required=True)
    args = p.parse_args(argv)
    try:
        status = probe_one_result(args.kcd, args.ymd, args.rno,
            acknowledgement=ACK if args.ack_private_research_single_get else "")
    except OfficialResultTransportError as e:
        print(json.dumps({
            "schema": "RACE_AI_KEIRIN_OFFICIAL_SINGLE_PAGE_FORMAT_PROBE_V1",
            "status": "NOT_CONNECTED_OR_UNVERIFIED",
            "reason": str(e), "no_forecast_update": True,
            "raw_html_stored": False, "persistent_monitoring_enabled": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
