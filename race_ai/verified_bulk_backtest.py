"""Offline, auditable mass historical forecast-vs-result reconciliation.

Inputs are OWNER-SUPPLIED JSONL; this tool makes no HTTP calls and does not
claim publisher permission, pre-cutoff proof, or independently verified facts.
Results with special settlements are quarantined instead of silently scored.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import csv
import json
from pathlib import Path
import re
import sys

ALLOWED_SPORTS = {'ボート', 'オート', '競輪', '競馬'}
RACE_STATUSES = {'SETTLED', 'CANCELLED', 'UNVERIFIED', 'SPECIAL'}
PROVENANCE = {'official_observed', 'third_party_observed', 'legacy_claim', 'unverified'}
SHA = re.compile(r'^[a-f0-9]{64}$')
TICKET = re.compile(r'^[1-9][0-9]*-[1-9][0-9]*-[1-9][0-9]*$')
HEADER = ['race_id', 'sport', 'venue', 'race_no', 'date', 'cohort', 'forecast_id', 'model_id', 'edition', 'ordered_picks',
          'result_status', 'winning_combinations', 'result_payout_100', 'status', 'hit_rank', 'gross_yen',
          'win_yen', 'refund_yen', 'received_yen', 'net_yen', 'refunded_positions', 'result_source_url',
          'result_source_grade', 'result_revision', 'forecast_source_url', 'forecast_source_sha256',
          'freeze_status', 'note']


class BadRecord(ValueError):
    pass


def nodups(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise BadRecord(f'duplicate JSON property: {k}')
        d[k] = v
    return d


def load_jsonl(path):
    with Path(path).open('rb') as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            if len(line) > 2_000_000:
                raise BadRecord(f'{path}:{n}: line over 2MB')
            try:
                x = json.loads(line.decode('utf-8-sig'), object_pairs_hook=nodups)
            except (ValueError, UnicodeError) as exc:
                raise BadRecord(f'{path}:{n}: {exc}') from exc
            if not isinstance(x, dict):
                raise BadRecord(f'{path}:{n}: expected JSON object')
            yield x


def safe_triple(value):
    if not isinstance(value, str) or not TICKET.fullmatch(value):
        raise BadRecord(f'invalid trifecta: {value!r}')
    parts = [int(s) for s in value.split('-')]
    if len(set(parts)) != 3 or any(n > 18 for n in parts):
        raise BadRecord(f'duplicate/out-of-range participant: {value}')
    return value


def race_parts(rid):
    if not isinstance(rid, str):
        raise BadRecord('race_id must be a string')
    parts = rid.split(':')
    if len(parts) != 4 or parts[0] not in ALLOWED_SPORTS or not 1 <= len(parts[2]) <= 40:
        raise BadRecord(f'invalid race_id: {rid}')
    try:
        datetime.strptime(parts[1], '%Y-%m-%d')
    except ValueError as exc:
        raise BadRecord(f'invalid race date in {rid}') from exc
    if not parts[3].isdigit() or not 1 <= int(parts[3]) <= 20:
        raise BadRecord(f'invalid race_no in {rid}')
    return parts


def parse_time(x):
    if not isinstance(x, str) or not x:
        return None
    try:
        d = datetime.fromisoformat(x.replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def validate_forecast(f):
    rid = f.get('race_id')
    race_parts(rid)
    picks = f.get('picks')
    if not isinstance(picks, list) or len(picks) > 12 or (not picks and not f.get('no_forecast_reason')):
        raise BadRecord(f'{rid}: pick count must be 1..12, or a documented no_forecast')
    for p in picks:
        safe_triple(p)
    if len(picks) != len(set(picks)):
        raise BadRecord(f'{rid}: duplicate picks')
    if not isinstance(f.get('forecast_id'), str) or not f['forecast_id']:
        raise BadRecord(f'{rid}: forecast_id required')
    if not isinstance(f.get('model_id'), str) or not f['model_id']:
        raise BadRecord(f'{rid}: model_id required')
    return f


def validate_result(r):
    rid = r.get('race_id')
    race_parts(rid)
    status = r.get('status')
    if status not in RACE_STATUSES:
        raise BadRecord(f'{rid}: bad status {status!r}')
    payout = r.get('payouts', {})
    if not isinstance(payout, dict):
        raise BadRecord(f'{rid}: payouts must be map')
    for k, v in payout.items():
        safe_triple(k)
        if type(v) is not int or v < 0:
            raise BadRecord(f'{rid}: invalid 100JPY payout for {k}')
    refunds = r.get('refunded_numbers', [])
    if not isinstance(refunds, list) or len(refunds) != len(set(map(str, refunds))):
        raise BadRecord(f'{rid}: invalid refund list')
    for num in refunds:
        if type(num) is not int or not 1 <= num <= 18:
            raise BadRecord(f'{rid}: invalid refunded number')
    if status == 'SETTLED' and not payout:
        raise BadRecord(f'{rid}: SETTLED without trifecta payouts; use SPECIAL')
    if status == 'UNVERIFIED' and (payout or refunds):
        raise BadRecord(f'{rid}: UNVERIFIED cannot carry settlement')
    if status == 'CANCELLED' and payout:
        raise BadRecord(f'{rid}: CANCELLED with payout')
    if not isinstance(r.get('source_url', ''), str):
        raise BadRecord(f'{rid}: bad source_url')
    if r.get('source_grade', 'unverified') not in PROVENANCE:
        raise BadRecord(f'{rid}: bad source_grade')
    if type(r.get('revision', 1)) is not int or r.get('revision', 1) < 1:
        raise BadRecord(f'{rid}: invalid revision')
    return r


def freeze_status(f):
    """A classification, not cryptographic verification of external receipts."""
    cutoff = parse_time(f.get('cutoff_at'))
    frozen = parse_time(f.get('frozen_at'))
    if not cutoff or not frozen:
        return 'EVIDENCE_MISSING'
    if frozen >= cutoff:
        return 'AT_OR_AFTER_CUTOFF'
    if f.get('freeze_evidence') != 'independently_confirmed':
        return 'TIMESTAMP_ONLY'
    if not SHA.fullmatch(str(f.get('source_sha256', ''))):
        return 'HASH_INVALID'
    if not f.get('receipt_url'):
        return 'EXTERNAL_RECEIPT_MISSING'
    return 'EXTERNAL_RECEIPT_CLAIM_UNVERIFIED'  # Offline CLI cannot independently verify an external receipt.


def choose_results(results):
    indexed = {}
    conflict = set()
    for r in results:
        r = validate_result(r)
        rid = r['race_id']
        previous = indexed.get(rid)
        if previous is None or r.get('revision', 1) > previous.get('revision', 1):
            indexed[rid] = r
            conflict.discard(rid)
        elif r.get('revision', 1) == previous.get('revision', 1) and r != previous:
            conflict.add(rid)
    for rid in conflict:
        indexed[rid] = {'race_id': rid, 'status': 'UNVERIFIED', 'source_grade': 'unverified',
                        'source_url': '', 'revision': 0, 'conflict': 'CONFLICTING_SAME_REVISION'}
    return indexed


def settle(f, r):
    """Return an auditable scoring row; 100JPY/pick hypothetical, never real bets."""
    validate_forecast(f)
    sport, day, venue, rn = race_parts(f['race_id'])
    picks = f['picks']
    result_status = r['status'] if r else 'UNVERIFIED'
    payouts = r.get('payouts', {}) if r else {}
    refunded = set(r.get('refunded_numbers', [])) if r else set()
    refunded_positions = [i + 1 for i, p in enumerate(picks)
                          if result_status == 'CANCELLED' or set(map(int, p.split('-'))) & refunded]
    gross = len(picks)*100
    known = result_status in {'SETTLED', 'CANCELLED'}
    refund_yen = 100*len(refunded_positions) if known else None
    if result_status == 'CANCELLED':
        matches = []
    else:
        matches = [i + 1 for i, p in enumerate(picks) if p in payouts and i + 1 not in refunded_positions]
    win_yen = sum(payouts[picks[i-1]] for i in matches) if known else None
    if not picks:
        judgment = 'NO_FORECAST' if known else 'NO_FORECAST_RESULT_UNVERIFIED'
        hit_rank = None
        win_yen = 0 if known else None
        refund_yen = 0 if known else None
        received = net = 0 if known else None
    elif not known:
        judgment = 'SPECIAL_REVIEW' if result_status == 'SPECIAL' else 'RESULT_UNVERIFIED'
        hit_rank = None
        received = net = None
    else:
        hit_rank = min(matches) if matches else None
        received = win_yen + refund_yen
        net = received - gross
        if result_status == 'CANCELLED' or len(refunded_positions) == len(picks):
            judgment = 'FULL_REFUND'
        elif matches and refunded_positions:
            judgment = 'HIT_PLUS_REFUND'
        elif matches:
            judgment = 'HIT'
        elif refunded_positions:
            judgment = 'MISS_PLUS_REFUND'
        else:
            judgment = 'MISS'
    payout_of_hit = max([payouts[picks[i-1]] for i in matches], default=0) if known else None
    grade = (r.get('source_grade', 'unverified') if r else 'unverified')
    note = ('Conflicting source revisions' if r and r.get('conflict') else
            ('Reference accounting only; independent receipt or source verification not established'))
    return dict(race_id=f['race_id'], sport=sport, venue=venue, race_no=int(rn), date=day,
                cohort=f.get('cohort','unspecified'), forecast_id=f['forecast_id'], model_id=f['model_id'], edition=f.get('edition',''),
                ordered_picks=' / '.join(picks), result_status=result_status,
                winning_combinations=' / '.join(payouts), result_payout_100=payout_of_hit,
                status=judgment, hit_rank=hit_rank, gross_yen=gross, win_yen=win_yen,
                refund_yen=refund_yen, received_yen=received, net_yen=net,
                refunded_positions=','.join(map(str, refunded_positions)),
                result_source_url=r.get('source_url','') if r else '', result_source_grade=grade,
                result_revision=r.get('revision',0) if r else 0,
                forecast_source_url=f.get('source_url',''),
                forecast_source_sha256=f.get('source_sha256',''),
                freeze_status=freeze_status(f) if picks else 'NO_FORECAST',
                note=f.get('no_forecast_reason',note) if not picks else note)


def summarize(rows, schedule=None):
    def stat(items):
        scored = [x for x in items if x['status'] in ('HIT','MISS','HIT_PLUS_REFUND','MISS_PLUS_REFUND')]
        settled = [x for x in items if x['status'] in ('HIT','MISS','HIT_PLUS_REFUND','MISS_PLUS_REFUND','FULL_REFUND')]
        hits = [x for x in scored if x['status'] in ('HIT','HIT_PLUS_REFUND')]
        gross = sum(x['gross_yen'] for x in settled)
        returned = sum(x['received_yen'] for x in settled)
        eligible_all=len(scored)+sum(x['status']=='NO_FORECAST' for x in items)
        hit_at_8=sum(x['hit_rank'] is not None and x['hit_rank']<=8 for x in scored)
        hit_at_12=sum(x['hit_rank'] is not None and x['hit_rank']<=12 for x in scored)
        return dict(forecasts=len(items), settled=len(settled), valid_accuracy=len(scored),
                    hit_at_8=hit_at_8,hit_at_12=hit_at_12,
                    hit_at_8_rate=(hit_at_8/len(scored) if scored else None),
                    hit_at_12_rate=(hit_at_12/len(scored) if scored else None),
                    eligible_all_count=eligible_all, hit_all_rate=len(hits)/eligible_all if eligible_all else None,
                    no_forecast=sum(x['status']=='NO_FORECAST' for x in items),
                    hits=len(hits), full_refunds=sum(x['status']=='FULL_REFUND' for x in items),
                    special_review=sum(x['status']=='SPECIAL_REVIEW' for x in items),
                    unverified=sum(x['status'] in ('RESULT_UNVERIFIED','NO_FORECAST_RESULT_UNVERIFIED') for x in items),
                    hit_rate=(len(hits)/len(scored) if scored else None),
                    stake_yen=gross, returned_yen=returned,
                    refund_yen=sum(x['refund_yen'] for x in settled),
                    roi=(returned/gross if gross else None), net_yen=returned-gross,
                    pre_cutoff_evidence_count=0,
                    reference_only_count=len(items))
    by_sport = defaultdict(list)
    by_model = defaultdict(list)
    by_cohort = defaultdict(list)
    by_month = defaultdict(list)
    for row in rows:
        by_sport[row['sport']].append(row)
        by_model[row['model_id']].append(row)
        by_cohort[row['cohort']].append(row)
        by_month[row['date'][:7]].append(row)
    used_races = set(r['race_id'] for r in rows)
    coverage = None
    if schedule is not None:
        scheduled = set()
        for x in schedule:
            rid = x.get('race_id')
            race_parts(rid)
            if rid in scheduled:
                raise BadRecord(f'duplicate schedule race: {rid}')
            scheduled.add(rid)
        coverage = {'scheduled_races':len(scheduled),'races_with_forecast':len(used_races & scheduled),
                    'races_without_forecast':len(scheduled - used_races),
                    'unscheduled_forecast_races':len(used_races - scheduled),
                    'missing_forecast_race_ids':sorted(scheduled - used_races)}
    return dict(total=stat(rows), sports={k:stat(v) for k,v in sorted(by_sport.items())},
                models={k:stat(v) for k,v in sorted(by_model.items())},
                cohorts={k:stat(v) for k,v in sorted(by_cohort.items())},
                months={k:stat(v) for k,v in sorted(by_month.items())}, coverage=coverage,
                caveat='User-supplied evidence and hypothetic 100JPY per pick; this program does not verify URLs/receipts independently.')



def diagnosis_stage(picks, outcome):
    """Post-race classification only; never a causal athlete label."""
    for ticket in picks:
        safe_triple(ticket)
    if not isinstance(outcome, str):
        return 'UNVERIFIED_OUTCOME'
    safe_triple(outcome)
    if outcome in picks:
        return 'HIT'
    first, second, _ = outcome.split('-')
    if not any(p.split('-')[0] == first for p in picks):
        return 'FIRST_NOT_COVERED'
    if not any(p.split('-')[:2] == [first, second] for p in picks):
        return 'SECOND_PAIR_NOT_COVERED'
    return 'THIRD_NOT_COVERED'


def diagnose_cohort(forecasts, results, *, cohort='morning'):
    """Offline same-day PDCA: true payout even on misses; no forecast rewrite.

    No official source authentication, learning, feature engineering, or
    independently attested prospective prediction is claimed by this routine.
    """
    result_index = choose_results(results)
    chosen = {}
    for f in forecasts:
        validate_forecast(f)
        if f.get('cohort') != cohort:
            continue
        rid = f['race_id']
        if rid in chosen:
            raise BadRecord(f'duplicate race in cohort {cohort}: {rid}')
        chosen[rid] = f
    by_sport = defaultdict(list)
    scorable = {'HIT', 'MISS', 'HIT_PLUS_REFUND', 'MISS_PLUS_REFUND'}
    for rid, f in sorted(chosen.items()):
        r = result_index.get(rid)
        score = settle(f, r)
        status = score['status']
        category = 'UNRESOLVED'
        band = 'UNKNOWN'
        if status == 'FULL_REFUND':
            category = 'FULL_REFUND'
        elif status in scorable:
            payouts = r['payouts']
            if len(payouts) != 1:
                category = 'MULTIPLE_WINNERS_NEED_SEPARATE_REVIEW'
            else:
                actual, payout = next(iter(payouts.items()))
                category = diagnosis_stage(f['picks'], actual)
                band = ('10000_PLUS' if payout >= 10000 else
                        '5000_TO_9999' if payout >= 5000 else
                        '1000_TO_4999' if payout >= 1000 else 'UNDER_1000')
        else:
            category = status
        by_sport[race_parts(rid)[0]].append({
            'status': status, 'category': category, 'band': band,
            'hit': bool(score['hit_rank']),
            'ticket_count': len(f['picks']),
            'first_1_tickets': sum(p.startswith('1-') for p in f['picks']),
            'source_grade': r.get('source_grade', 'unverified') if r else 'unverified',
            'stake': score['gross_yen'] if status in scorable | {'FULL_REFUND'} else 0,
            'received': score['received_yen'] if status in scorable | {'FULL_REFUND'} else 0,
        })
    def summary(rows):
        valid = [x for x in rows if x['status'] in scorable]
        gross = sum(x['stake'] for x in rows)
        returned = sum(x['received'] for x in rows)
        tickets = sum(x['ticket_count'] for x in rows)
        names = ('UNDER_1000','1000_TO_4999','5000_TO_9999','10000_PLUS')
        return {
            'forecasts': len(rows), 'scorable': len(valid),
            'hits': sum(x['hit'] for x in valid),
            'hit_rate': sum(x['hit'] for x in valid)/len(valid) if valid else None,
            'gross_yen': gross, 'received_yen': returned,
            'net_yen': returned-gross, 'roi': returned/gross if gross else None,
            'full_refunds': sum(x['status']=='FULL_REFUND' for x in rows),
            'failure_stage_counts': dict(Counter(x['category'] for x in valid)),
            'payout_bands': {k: {
                'races':sum(x['band']==k for x in valid),
                'hits':sum(x['band']==k and x['hit'] for x in valid),
            } for k in names},
            'first_1_ticket_share': (
                sum(x['first_1_tickets'] for x in rows)/tickets if tickets else None),
            'source_grade_counts': dict(Counter(x['source_grade'] for x in rows)),
            'all_official_results_independently_verified': False,
            'future_accuracy_gain_proved': False,
        }
    all_rows = [r for rows in by_sport.values() for r in rows]
    return {
        'scope': 'OWNER_SUPPLIED_RETROSPECTIVE_PDCA_ONLY',
        'cohort': cohort,
        'total': summary(all_rows),
        'sports': {k: summary(v) for k,v in sorted(by_sport.items())},
    }



def run(forecast_file, result_file, output_dir, schedule_file=None):
    forecast_file = Path(forecast_file)
    result_file = Path(result_file)
    out = Path(output_dir)
    if out.exists():
        raise BadRecord(f'refusing to overwrite existing output directory: {out}')
    forecasts = list(load_jsonl(forecast_file))
    ids = set()
    for f in forecasts:
        validate_forecast(f)
        if f['forecast_id'] in ids:
            raise BadRecord(f'duplicate forecast_id: {f["forecast_id"]}')
        ids.add(f['forecast_id'])
    results = choose_results(load_jsonl(result_file))
    rows = [settle(f,results.get(f['race_id'])) for f in forecasts]
    schedule = list(load_jsonl(schedule_file)) if schedule_file else None
    report = summarize(rows, schedule)
    report['input_sha256']={'forecasts':sha256(forecast_file.read_bytes()).hexdigest(),
                            'results':sha256(result_file.read_bytes()).hexdigest(),
                            'schedule':sha256(Path(schedule_file).read_bytes()).hexdigest() if schedule_file else None}
    out.mkdir(parents=True, exist_ok=False)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'all_forecasts.csv').open('w',encoding='utf-8-sig',newline='') as fh:
        writer=csv.DictWriter(fh,fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    with (out/'unresolved.jsonl').open('w',encoding='utf-8') as fh:
        for row in rows:
            if row['status'] in ('RESULT_UNVERIFIED','SPECIAL_REVIEW','NO_FORECAST_RESULT_UNVERIFIED'):
                fh.write(json.dumps(row,ensure_ascii=False)+'\n')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline immutable historical 3T reconciliation')
    p.add_argument('--forecasts',required=True)
    p.add_argument('--results',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--schedule')
    args=p.parse_args(argv)
    try:
        stats=run(args.forecasts,args.results,args.out,args.schedule)
    except (BadRecord,OSError) as err:
        print(f'AUDIT_BLOCKED: {err}',file=sys.stderr)
        return 2
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    return 0 if stats['total']['unverified']==0 and stats['total']['special_review']==0 else 1


if __name__ == '__main__':
    raise SystemExit(main())

