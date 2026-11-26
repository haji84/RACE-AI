"""Prepare a checked public forecast-details artifact from matched local receipts."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from race_ai import keirin_official_public_source as official_source
from race_ai import keirin_public_forecast_details as details
from race_ai import keirin_public_forecast_updates as updates
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_result_unread_racecard as racecard
from race_ai.keirin_nationwide_auto_generator import when
from scripts.keirin_capture_public_two_sources import MAX_BYTES, private_dir
from scripts.keirin_note_collect_inputs import _read, _write_snapshot
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json
from scripts.keirin_publish_result_unread import _source


def _index(rows, field, eligible):
    public.need(type(rows) is list and all(type(row) is dict and type(row.get('race_id')) is str and
                field in row for row in rows), 'DETAIL_SOURCE_ROWS')
    by_id = {row['race_id']: row[field] for row in rows}
    public.need(len(by_id) == len(rows) and by_id.keys() <= eligible, 'DETAIL_SOURCE_IDS')
    return by_id


def _held(race_id, error):
    message = str(error)
    code = message if re.fullmatch('[A-Z_0-9]{1,100}', message) else 'DETAIL_SOURCE_OR_TICKETS_UNVERIFIED'
    return dict(race_id=race_id, reason=code)


def prepare(schedule, capture_root, research, updates_body=None, *, clock=None):
    """Reproduce the admissions and retain only exactly matched public selections."""
    schedule = restore_private_snapshot_json(schedule)
    public.need(official_source.reparse_day_schedule(schedule), 'DETAIL_OFFICIAL_SCHEDULE')
    day = schedule['day_jst']
    public.checked_research(research)
    public.need(research['day'] == day, 'DETAIL_RESEARCH_DAY')
    revisions = {}
    if updates_body is not None:
        updates.checked(updates_body)
        public.need(updates_body['day'] == day, 'DETAIL_UPDATE_DAY')
        revisions = {row['race_id']: row for row in updates_body['races']}
    registered = {row['race_id']: row for row in schedule['races']}
    root = private_dir(capture_root)
    cards = _index(public._json(_read(root/'cards-observed.json', public.MAX_BYTES)), 'kdreams_receipt', registered.keys())
    net_path = root/'net-observed.json'
    secondary = public._json(_read(net_path, public.MAX_BYTES)) if net_path.exists() else []
    supplemental = _index(secondary, 'netkeirin_receipt', cards.keys())

    at = (clock or (lambda: datetime.now(timezone.utc)))()
    public.need(isinstance(at, datetime) and at.utcoffset() is not None and when(research['published_at']) <= at and
                (updates_body is None or when(updates_body['published_at']) <= at), 'DETAIL_PUBLICATION_CLOCK')
    rows, held = [], []
    counts = Counter(a=0, b=0, conditional_races=0, conditional_cases=0, tracked_scenarios=0, coherence_grades=0)
    for row in sorted(research['races'], key=lambda item: item['race_id']):
        rid = row['race_id']
        update = revisions.get(rid)
        overlay = update['b'] if update else None
        try:
            clock_at_creation = when(row['generated_at'])
            kd_raw, kd_url = _source(root, cards[rid], generated_at=clock_at_creation)
            net_raw, net_url = (_source(root, supplemental[rid], generated_at=clock_at_creation)
                                if rid in supplemental else (None, None))
            inputs = dict(race_id=rid, kdreams_raw=kd_raw, kdreams_url=kd_url,
                          netkeirin_raw=net_raw, netkeirin_url=net_url)
            snapshot = racecard.snapshot_from_cards(**inputs)
            cases = None
            if overlay and overlay['kind'] == 'contested_lineup':
                try:
                    cases = racecard.contested_hypotheses_from_card(**inputs)
                except (ValueError, KeyError, TypeError) as error:
                    held.append(_held(rid, error))
            projected = details.project_race(snapshot, registered[rid], row, assessed_at=at, update=update,
                                             contest_cases=cases)
        except (ValueError, KeyError, TypeError, OSError) as error:
            held.append(_held(rid, error))
            continue
        if overlay and overlay['kind'] == 'contested_lineup' and 'b_conditions' not in projected:
            held.append(_held(rid, 'DETAIL_CONTEST_SELECTION_UNMATCHED'))
        if projected['a'] is None and projected['b'] is None and not projected.get('b_conditions'):
            held.append(_held(rid, 'DETAIL_NO_MATCHED_SELECTIONS'))
            continue
        rows.append(projected)
        for arm in ('a', 'b'):
            counts[arm] += projected[arm] is not None
        conditions = projected.get('b_conditions', [])
        counts['conditional_races'] += bool(conditions)
        counts['conditional_cases'] += len(conditions)
        for arm in [projected['a'], projected['b'], *conditions]:
            if arm is None:
                continue
            counts['tracked_scenarios'] += sum(any(scene['orders']) for scene in arm['scenarios'])
            counts['coherence_grades'] += 'coherence_grade' in arm
    body = details.checked(dict(schema=details.SCHEMA, day=day, published_at=at.isoformat(), races=rows))
    return body, dict(day_jst=day, research_races=len(research['races']), detailed_races=len(rows),
                      coverage=dict(counts), held_races=held)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--capture-dir', required=True, type=Path)
    parser.add_argument('--research', required=True, type=Path)
    parser.add_argument('--updates', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    research_raw = _read(args.research, public.MAX_BYTES)
    updates_raw = _read(args.updates, public.MAX_BYTES) if args.updates else None
    schedule = public._json(_read(args.schedule, MAX_BYTES))
    body, report = prepare(schedule, args.capture_dir, public._json(research_raw),
                           public._json(updates_raw) if updates_raw is not None else None)
    if body['races']:
        _write_snapshot(args.output, body)
        raw = _read(args.output, public.MAX_BYTES)
        report.update(output=str(args.output), bytes=len(raw), sha256=sha256(raw).hexdigest(),
                      research_sha256=sha256(research_raw).hexdigest(),
                      updates_sha256=sha256(updates_raw).hexdigest() if updates_raw is not None else None)
    print(json.dumps(report, sort_keys=True))
    return 0 if body['races'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
