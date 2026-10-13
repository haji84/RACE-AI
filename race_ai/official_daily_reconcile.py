"""Cross-check official B (program) vs K (results) race/boat/registration IDs."""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import json
import sys
from pathlib import Path

from .core import SourceError
from .official_daily_verify import fetch_and_parse


def reconcile_rows(program_rows:list[dict],result_rows:list[dict])->dict:
    """No names or PII in summary, fail on any racer/boat/race mismatch."""
    def keyed(rows):
        result={}
        for r in rows:
            key=(r['race_id'],r['lane'])
            if key in result:
                raise SourceError('duplicate race+lane key')
            result[key]=str(r['racer_id'])
        return result
    b=keyed(program_rows)
    k=keyed(result_rows)
    allkeys=set(b)|set(k)
    missing_in_b=len(set(k)-set(b))
    missing_in_k=len(set(b)-set(k))
    mismatches=sum(b[x]!=k[x] for x in set(b)&set(k))
    count=len({rid for rid,lane in allkeys})
    coverage=dict(races=count,program_boats=len(b),result_boats=len(k),
        absent_from_program=missing_in_b,absent_from_result=missing_in_k,
        registration_number_mismatches=mismatches)
    if missing_in_b or missing_in_k or mismatches or not count:
        raise SourceError("official B/K identifier reconciliation failed: "+json.dumps(coverage))
    return dict(status='OFFICIAL_B_K_IDENTIFIERS_RECONCILED',
                **coverage,actual_course_and_st_checked_against_website=False)


def verify(day:date)->dict:
    bmeta, brows=fetch_and_parse(day,'B',include_rows=True)
    kmeta, krows=fetch_and_parse(day,'K',include_rows=True)
    r=reconcile_rows(brows,krows)
    return dict(day_jst=day.isoformat(),retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **r,program_sha256=bmeta['download_sha256'],
                result_sha256=kmeta['download_sha256'],
                official_archives=True,
                source_published_at=None,prior_motor_user_join_completed=False,
                all_24_active_motor_inventory_verified=False,
                original_exhibition_available=False,
                note='B/K identity match is structural, not proof of complete official-result accuracy.')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--date',required=True,help='date already completed YYYY-MM-DD')
    p.add_argument('--output',type=Path,help='optional metadata-only output')
    a=p.parse_args()
    try:
        output=verify(date.fromisoformat(a.date))
    except (SourceError,ValueError,TypeError) as exc:
        print("SAFE_STOP: "+str(exc),file=sys.stderr)
        raise SystemExit(2)
    txt=json.dumps(output,ensure_ascii=False,indent=2)
    if a.output:
        a.output.write_text(txt+"\n",encoding="utf-8")
    print(txt)


if __name__=='__main__':
    main()
