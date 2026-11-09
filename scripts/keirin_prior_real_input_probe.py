"""Actual prior results -> existing PR71 candidate inputs; public counts only.

Uses owner-approved ordinary WINTICKET public pages, never an internal API.
Stops that host on access denial/rate limit. No real input, ticket, name, odds,
license, secret or raw HTML is sent to public logs/artifacts. No predictions.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json

from race_ai.keirin_owner_public_page_fetch import network_page_once, PublicPageFetchError
from race_ai.keirin_winticket_embedded_racecard import racecard_from_public_html
from race_ai.keirin_winticket_prior_events import (
    documents_from_html, history_references, normalize_result_event,
    observed_prior_candidates, safe_prior_counts, PriorSourceError,
)


def probe(*, race_id, racecard_url, max_pages=32, fetch=None, clock=None):
    if type(max_pages) is not int or not 1<=max_pages<=100:
        raise ValueError('PRIOR_PAGE_BUDGET_INVALID')
    if fetch is None: fetch=network_page_once
    if clock is None: clock=lambda:datetime.now(timezone.utc)
    requests=0
    requests+=1; body=fetch(racecard_url)
    captured=clock().isoformat()
    validated=racecard_from_public_html(body,url=racecard_url,
                                       race_id=race_id,captured_at=captured)
    requests+=1; index=fetch('https://www.winticket.jp/keirin/odds/'+race_id[:8])
    reference=history_references(documents_from_html(body),
        target_race_id=race_id,target_url=racecard_url,captured_at=captured,
        venue_documents=documents_from_html(index))
    if set(reference['rider_ids']) != {
        str(r['source_player_id']) for r in validated['riders']}:
        raise ValueError('PRIOR_TARGET_ROSTER_MISMATCH')
    # A finite one-shot verification visits each athlete before a second pass.
    # Shared prior races are fetched once; this is not a nationwide quota.
    by_rider={r:[v for v in reference['references'] if r in v['rider_ids']]
              for r in reference['rider_ids']}
    chosen=[]; seen=set()
    for round_index in range(max((len(v) for v in by_rider.values()),default=0)):
        for rider in reference['rider_ids']:
            rows=by_rider[rider]
            if round_index>=len(rows): continue
            row=rows[round_index]
            if row['race_id'] in seen: continue
            seen.add(row['race_id']); chosen.append(row)
    events=[]; failures=Counter(); stopped=False; attempted=0
    for ref in chosen[:max_pages]:
        attempted+=1
        try:
            requests+=1; raw=fetch(ref['url'])
            event=normalize_result_event(documents_from_html(raw),
                source_url=ref['url'],expected_race_id=ref['race_id'],
                source_sha256=sha256(raw).hexdigest(),captured_at=clock().isoformat(),
                target_cutoff_at=reference['target']['cutoff'])
            events.append(event)
        except PublicPageFetchError as exc:
            reason=str(exc)
            failures[reason if reason.startswith('PUBLIC_PAGE_') else 'SOURCE_UNAVAILABLE']+=1
            if 'BLOCKED' in reason or 'RATE_LIMITED' in reason:
                stopped=True
                break
        except PriorSourceError as exc:
            failures[str(exc)]+=1
        except (ValueError,TypeError,KeyError,OSError):
            failures['PRIOR_RESULT_SCHEMA_OR_TIME_NOT_VERIFIED']+=1
    as_of=clock().isoformat()
    derived=observed_prior_candidates(reference,events,as_of=as_of)
    counts=safe_prior_counts(reference,events)
    features=('finishing_power','bank_fit','line_coordination','sprint_acceleration')
    return {**counts,'race_id':race_id,'observed_at':as_of,
        'racecard_sha256':sha256(body).hexdigest(),
        'source_packet_sha256':derived['source_packet_sha256'],
        'candidate_riders_by_existing_feature':{
            name:sum(r['features'][name]['candidate_value'] is not None
                     for r in derived['riders'].values()) for name in features},
        'matched_prior_event_counts':sorted(r['matched_prior_events']
                                            for r in derived['riders'].values()),
        'unfetched_prior_references':max(0,len(chosen)-attempted),
        'request_count':requests,'host_denial_stopped':stopped,
        'source_failures':dict(failures),'formula_version':derived['formula_version'],
        'model_coefficients_changed':False,'actual_four_model_forecast_saved':False,
        'status':'REAL_PRIOR_SOURCE_CHECKED_NOT_FULL_MODEL_ADMISSION'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--race-id',required=True)
    parser.add_argument('--racecard-url',required=True)
    parser.add_argument('--max-pages',type=int,default=32)
    args=parser.parse_args()
    try:
        report=probe(race_id=args.race_id,racecard_url=args.racecard_url,
                     max_pages=args.max_pages)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        report={'status':'REAL_PRIOR_INPUT_UNAVAILABLE_NO_INVENTED_VALUES',
                'model_input_admitted':False,'actual_four_model_forecast_saved':False,
                'reason':str(exc) if isinstance(exc,PriorSourceError) else type(exc).__name__}
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
