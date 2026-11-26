"""Publish dated racecard-only reference candidates for gaps in the public roster."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re

from race_ai import keirin_official_public_source as official_source
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_result_unread_racecard as racecard
from race_ai.keirin_nationwide_auto_generator import when
from scripts.keirin_capture_public_two_sources import MAX_BYTES, private_dir
from scripts.keirin_note_collect_inputs import _read
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json


def _source(root, receipt, *, generated_at):
    public.need(type(receipt) is dict and set(receipt) == {'url','bytes_sha256','bytes','status','captured_at'} and
                receipt['status'] == 200 and type(receipt['bytes_sha256']) is str and
                re.fullmatch(r'[a-f0-9]{64}', receipt['bytes_sha256']) and
                when(receipt['captured_at']) <= generated_at, 'RESEARCH_SOURCE_RECEIPT')
    digest = receipt['bytes_sha256']
    raw = _read(root/'raw'/(digest+'.html'), MAX_BYTES)
    public.need(type(receipt['bytes']) is int and len(raw) == receipt['bytes'] and sha256(raw).hexdigest() == digest,
                'RESEARCH_SOURCE_SHA')
    return raw, receipt['url']


def prepare(schedule, capture_root, *, clock=None):
    """Verify local receipts and generate results-unread candidates without fetching providers."""
    schedule = restore_private_snapshot_json(schedule)
    public.need(official_source.reparse_day_schedule(schedule), 'RESEARCH_OFFICIAL_SCHEDULE')
    day = schedule['day_jst']
    registered = {row['race_id']:row for row in schedule['races']}
    root = private_dir(capture_root)
    captured = public._json(_read(root/'cards-observed.json', public.MAX_BYTES))
    public.need(type(captured) is list and len(captured) <= len(registered), 'RESEARCH_CAPTURE_ROWS')
    ids = [row['race_id'] for row in captured]
    public.need(len(set(ids)) == len(ids) and set(ids) <= set(registered), 'RESEARCH_CAPTURE_IDS')
    net_path = root/'net-observed.json'
    secondary = public._json(_read(net_path, public.MAX_BYTES)) if net_path.exists() else []
    public.need(type(secondary) is list, 'RESEARCH_CAPTURE_ROWS')
    net_receipts = {row['race_id']:row['netkeirin_receipt'] for row in secondary}
    public.need(len(net_receipts) == len(secondary) and set(net_receipts) <= set(ids), 'RESEARCH_CAPTURE_IDS')

    clock = clock or (lambda:datetime.now(timezone.utc))
    generated = clock()
    races, held = [], []
    for row in sorted(captured, key=lambda item:item['race_id']):
        rid = row['race_id']
        try:
            kd_raw, kd_url = _source(root, row['kdreams_receipt'], generated_at=generated)
            net_raw, net_url = (_source(root, net_receipts[rid], generated_at=generated)
                                if rid in net_receipts else (None, None))
            snapshot = racecard.snapshot_from_cards(race_id=rid, kdreams_raw=kd_raw, kdreams_url=kd_url,
                                                     netkeirin_raw=net_raw, netkeirin_url=net_url)
            races.append(public.project_research_race(snapshot, registered[rid], generated_at=generated))
        except (ValueError, KeyError, TypeError, OSError) as error:
            reason = str(error)
            held.append(dict(race_id=rid, reason=reason if re.fullmatch('[A-Z_0-9]{1,100}', reason)
                             else 'INVALID_RACECARD_OR_RECEIPT'))
    body = public.checked_research(dict(schema=public.RESEARCH_SCHEMA, day=day,
                                        published_at=clock().isoformat(), races=races))
    counts = Counter(len(row['starter_cars']) for row in races)
    summary = dict(day_jst=day, captured_races=len(captured), research_races=len(races),
                   a_races=sum(bool(row['a']) for row in races), b_races=sum(bool(row['b']) for row in races),
                   after_cutoff=sum(when(row['generated_at']) >= when(row['cutoff_at']) for row in races),
                   starters_by_count=dict(sorted(counts.items())), held_races=held)
    return body, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--capture-dir', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    schedule = public._json(_read(args.schedule, MAX_BYTES))
    body, summary = prepare(schedule, args.capture_dir)
    if args.publish:
        summary['publication'] = public.publish_research(args.repo, body)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if body['races'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
