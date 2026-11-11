"""One read-only real WINTICKET day-index probe from GitHub Actions.

Uses only the public user-approved HTML route. Logs SHA and race counts,
never raw page bytes or private model inputs. No API discovery or bypass.
"""
from __future__ import annotations

import argparse
import json

from race_ai.keirin_owner_public_page_fetch import (
    network_page_once,PublicPageFetchError
)
from race_ai.keirin_winticket_day_index import (
    extract_owner_winticket_day,safe_day_index_summary,
    WinticketDayIndexError
)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date",required=True)
    args=p.parse_args(argv)
    source="https://www.winticket.jp/keirin/odds/"+args.date.replace("-","")
    try:
        raw=network_page_once(source)
        doc=extract_owner_winticket_day(
            raw,source_url=source,event_day=args.date)
        report=safe_day_index_summary(doc)
        report["status"]=(
            "PUBLIC_DAY_INDEX_SSR_AND_LINKS_CHECKED"
            if report["matching_public_ssr_and_href_coverage"] else
            "PUBLIC_DAY_INDEX_PARTIAL_SOURCE")
        report["live_source_html_read"]=True
    except (PublicPageFetchError,WinticketDayIndexError,OSError,ValueError):
        report={
            "schema":"RACE_AI_KEIRIN_WINTICKET_DAY_DISCOVERY_SSR_V1",
            "event_day_jst":args.date,
            "status":"SOURCE_NOT_YET_ADMITTED",
            "live_source_html_read":False,
            "future_forecast_created":False,
        }
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,
                     separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
