"""One date-scoped read-only roster check, no source archive or prediction."""
import json
import sys
from race_ai.keirin_discovery import get_single_day, DiscoveryError

def main():
    day="2026-11-03"
    try:
        record=get_single_day(day)
        report={k:record[k] for k in (
            "schema","source_url","event_date_jst","source_sha256",
            "race_count","venue_count","venue_race_counts",
            "complete_national_coverage_verified","official_cutoffs_verified")}
        print(json.dumps(report,sort_keys=True,ensure_ascii=False))
        return 0
    except DiscoveryError as e:
        print(json.dumps({"state":"REAL_DAY_ROSTER_NOT_VERIFIED","reason":str(e)}))
        return 2

if __name__=="__main__":
    sys.exit(main())
