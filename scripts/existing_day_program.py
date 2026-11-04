"""Current-day P0 orchestration of EXISTING models; never a new predictor.

Reuses pinned official B parser and PR72 program bridge. Keeps real missing
features missing, never wagers, never treats local time/hash as a freeze proof.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
import race_ai
for folder in ('pr64-reference', 'pr72-reference'):
    location = str(ROOT / folder / 'race_ai')
    if location not in race_ai.__path__: race_ai.__path__.append(location)
from race_ai.boat_observed_pairwise_models import predict_pair, MODEL_IDS as EXISTING_IDS
from race_ai.boat_observed_program_bridge import build_program_snapshot
from race_ai.official_archive_probe import official_url, StrictRedirect, MAX_ARCHIVE_BYTES, inspect_lzh
from race_ai.official_lzh_extract import extract_daily_lzh
from race_ai.official_b_snapshot_adapter import normalize_b_snapshot

JST = timezone(timedelta(hours=9))
RIGHTS = 'OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104'

def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset() is None: raise ValueError('aware clock required')
    return stamp

def forecast_program(program, *, clock=lambda: datetime.now(timezone.utc), already_frozen=frozenset()):
    day = date.fromisoformat(program['date_jst'])
    url = official_url(day, 'B')
    if program['source_url'] != url: raise ValueError('foreign program source')
    source = dict(source_id=f'official-B-{day:%Y%m%d}', source_url=url,
        source_sha256=program['source_sha256'], source_rights_ref=RIGHTS,
        published_at=None, captured_at=program['first_observed_at'],
        evidence_basis='CAPTURED_BY_CLAIM')
    # Scoped personal-analysis authorization, not a provider commercial license.
    def allowed(candidate_url, reference, purpose):
        return candidate_url == url and reference == RIGHTS and purpose == 'analysis'
    rows = sorted((r for v in program['venues'] for r in v['races']),
                  key=lambda r: (r['closed_at'], r['race_id']))
    if len({r['race_id'] for r in rows}) != len(rows): raise ValueError('duplicate program race')
    result = dict(schema='RACE_AI_EXISTING_P0_DAY_V1', day_jst=str(day), predictions=[],
        schedule=[], skipped=[], external_receipt_verified=False, actual_purchases=False,
        new_models_created=False, raw_source_published=False,
        source_url=url, source_sha256=program['source_sha256'], captured_at=source['captured_at'],
        phase_semantics='PROGRAM_ONLY; not an assertion that exhibition has not happened',
        code_sha=os.environ.get('GITHUB_SHA'), model_ids=list(EXISTING_IDS))
    for row in rows:
        now = clock()
        if instant(source['captured_at']) > now: raise ValueError('future source capture')
        result['schedule'].append(dict(race_id=row['race_id'], cutoff_at=row['closed_at']))
        reason = ('ORIGINAL_EXISTS' if row['race_id'] in already_frozen else
                  'CUTOFF_BUFFER' if now + timedelta(minutes=3) >= instant(row['closed_at']) else None)
        if reason:
            result['skipped'].append(dict(race_id=row['race_id'], reason=reason)); continue
        snap = build_program_snapshot(row, source, event_date_jst=str(day),
                                      as_of=now.isoformat(), race_revision=1)
        result['predictions'].append(predict_pair(snap, allow_source=allowed))
    result.update(state='GENERATED_PENDING_EXTERNAL_RECEIPT', race_count=len(result['predictions']),
                  model_forecast_count=sum(len(s['models']) for s in result['predictions']))
    return result

def collect(*, clock=lambda: datetime.now(timezone.utc), already_frozen=frozenset()):
    day = clock().astimezone(JST).date(); url = official_url(day, 'B')
    status = dict(schema='RACE_AI_EXISTING_P0_DAY_V1', day_jst=str(day), predictions=[],
        schedule=[], skipped=[], external_receipt_verified=False, actual_purchases=False,
        new_models_created=False, raw_source_published=False, source_url=url,
        state='SOURCE_OR_MODEL_BLOCKED', race_count=0, model_forecast_count=0)
    body = None
    try:
        req = request.Request(url, headers={'User-Agent':'RACE-AI-owner-personal-day-program/1.0',
                                          'Accept':'application/octet-stream'})
        with request.build_opener(StrictRedirect).open(req, timeout=25) as res:
            if res.status != 200 or res.geturl() != url: raise ValueError('B_SOURCE_IDENTITY')
            raw = res.read(MAX_ARCHIVE_BYTES + 1)
        capture = clock().isoformat(); meta = inspect_lzh(raw)
        status.update(source_sha256=meta['sha256'], captured_at=capture, source_requests=1)
        body = extract_daily_lzh(raw, f'B{day:%y%m%d}.TXT')
        from race_ai.program_race_isolation import normalize_races
        program = normalize_races(body, day=day, source_url=url, observed_at=capture,
                                  archive_sha256=meta['sha256'])
        status = forecast_program(program, clock=clock, already_frozen=already_frozen)
        status.update(extracted_text_sha256=program['extracted_text_sha256'], source_requests=1,
                      schedule=program['all_schedule'], blocked_races=program['blocked_races'])
        status['skipped'].extend(program['blocked_races'])
    except Exception as exc:
        status.update(failure_class=type(exc).__name__, reason=str(exc)[:200])
        if body is not None:
            from race_ai.b_layout_shape_diagnostic import summarize_b_layout
            status['layout_diagnostic'] = summarize_b_layout(body)
    status['completed_at'] = clock().isoformat()
    return status

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='boat_all_day_output/forecasts.json')
    args=parser.parse_args();out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    status=collect();payload=json.dumps(status,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    with out.open('xb') as f:f.write(payload)
    print(json.dumps({k:v for k,v in status.items() if k not in ('predictions','schedule','skipped')},ensure_ascii=False))
    print('FORECAST_FILE_SHA256',hashlib.sha256(payload).hexdigest())
    return 0 if status['race_count'] else 2

if __name__=='__main__':raise SystemExit(main())
