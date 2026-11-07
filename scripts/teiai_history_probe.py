"""Offline real-file validation; stdout contains counts/hashes, never raw rows.

Run as python -m scripts.teiai_history_probe. Download with approved collection
outside the checkout first. This does not establish historical availability,
independent receipt times, upstream authenticity, live accuracy or training.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from race_ai.teiai_history import BASE, MAX_BYTES, need, parse_history_csv, parse_racer_json, parse_race_json, race_parts
from race_ai.teiai_official_reconciliation import official_day, reconcile_rows, reconcile_payouts
from race_ai.official_lzh_extract import extract_daily_lzh


def _read(path,limit=MAX_BYTES):
    with Path(path).open('rb') as f:raw=f.read(limit+1)
    need(0<len(raw)<=limit,'PROBE_INPUT_SIZE_INVALID')
    return raw


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',required=True);parser.add_argument('--racer',required=True)
    parser.add_argument('--registration',required=True);parser.add_argument('--race',required=True)
    parser.add_argument('--race-id',required=True);parser.add_argument('--official-k',required=True)
    args=parser.parse_args(argv)
    day,_,_=race_parts(args.race_id)
    raw={k:_read(getattr(args,k),16_000_000 if k=='official_k' else MAX_BYTES) for k in ('history','racer','race','official_k')}
    parse_racer_json(raw['racer'],racer_id=args.registration)
    history=parse_history_csv(raw['history'],racer_id=args.registration,
                              source_url=f'{BASE}/api/racer/{args.registration}/results/')
    race=parse_race_json(raw['race'],race_id=args.race_id)
    official=official_day(extract_daily_lzh(raw['official_k'],f'K{day:%y%m%d}.TXT'),day=day.isoformat())
    selected=[r for r in history['rows'] if r['race_id'][:8]==day.strftime('%Y%m%d')]
    def counts(rows):return {k:v for k,v in reconcile_rows(rows,official['rows']).items() if k not in ('accepted','quarantine')}
    report=dict(schema='RACE_AI_TEIAI_OFFLINE_PROBE_V1',checked_at=datetime.now(timezone.utc).isoformat(),
        attribution='データ提供：艇愛ボートレースDB https://boatrace-db.jp/ (BOAT RACE official downloads)',
        sha256={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()},
        parsed_history_rows=len(history['rows']),duplicate_history_rows=history['duplicate_count'],
        conflicting_duplicate_races=len(history['quarantine']),history=counts(selected),race=counts(race['rows']),
        payouts=reconcile_payouts(race['payouts'],official['payouts'].get(args.race_id,[])),
        distinct_compared_races=len({r['race_id'] for r in selected+race['rows']}),
        unique_compared_entries=len({(r['race_id'],r['lane']) for r in selected+race['rows']}),
        upstream_authentication='CALLER_RESPONSIBILITY_NOT_ESTABLISHED_BY_LOCAL_HASH',
        official_corrections_history=None,publication_to_save_delay_seconds=None,
        formal_backtest_eligible=False,future_race_verified=False,production_enabled=False)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2))
    return report


if __name__=='__main__':main()
