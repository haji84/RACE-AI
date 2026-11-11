"""Observed public past results for the EXISTING PR71 prior-signal equations.

This is a source adapter, not a predictor or a permissions/timestamp authority.
It retains real half-lap seconds and unknown lineup/split facts as unknown.
Only the private caller receives athlete identifiers or source measurements.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from urllib.parse import urlsplit

SITE_ID = re.compile(r'^[0-9]{12}$')
CANONICAL_ID = re.compile(r'^20[0-9]{10}$')
SLUG = re.compile(r'^[a-z][a-z0-9-]{1,30}$')
PAGE = re.compile(r'^/keirin/([a-z][a-z0-9-]{1,30})/(racecard|raceresult)/([0-9]{10})/([1-7])/([1-9][0-9]?)$')
MAX_RECORDS = 2000


class PriorSourceError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise PriorSourceError(code)


def _utc(value):
    need(type(value) is str, 'PRIOR_AWARE_CLOCK_REQUIRED')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise PriorSourceError('PRIOR_CLOCK_INVALID') from None
    need(dt.utcoffset() is not None, 'PRIOR_AWARE_CLOCK_REQUIRED')
    return dt.astimezone(timezone.utc)


def _clock(value):
    need(type(value) is int and 1_500_000_000 < value < 2_500_000_000,
         'PRIOR_SOURCE_CLOCK_MISSING')
    return datetime.fromtimestamp(value, timezone.utc)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':')).encode()


def site_id(race_id):
    need(type(race_id) is str and CANONICAL_ID.fullmatch(race_id),
         'PRIOR_RACE_ID_INVALID')
    datetime.strptime(race_id[:8], '%Y%m%d')
    need(1 <= int(race_id[-2:]) <= 12, 'PRIOR_RACE_NUMBER_INVALID')
    return race_id[-2:] + race_id[8:10] + race_id[:8]


def canonical_id(value):
    need(type(value) is str and SITE_ID.fullmatch(value),
         'PRIOR_SITE_ID_INVALID')
    rid = value[4:] + value[2:4] + value[:2]
    site_id(rid)
    return rid


def _page_identity(url, expected_id, required_kind):
    need(type(url) is str and len(url) <= 512, 'PRIOR_PAGE_URL_INVALID')
    p = urlsplit(url)
    need(p.scheme == 'https' and p.hostname in ('winticket.jp', 'www.winticket.jp')
         and p.username is None and p.password is None and p.port is None
         and not p.query and not p.fragment, 'PRIOR_PAGE_ORIGIN_INVALID')
    match = PAGE.fullmatch(p.path)
    need(match is not None, 'PRIOR_PAGE_PATH_INVALID')
    slug, kind, cup, day, number = match.groups()
    need(kind == required_kind, 'PRIOR_PAGE_KIND_INVALID')
    date = datetime.strptime(cup[:8], '%Y%m%d').date() + timedelta(days=int(day)-1)
    actual = f'{date:%Y%m%d}{cup[-2:]}{int(number):02d}'
    need(actual == expected_id, 'PRIOR_PAGE_RACE_MISMATCH')
    return slug, cup


def documents_from_state(state):
    need(type(state) is dict, 'PRIOR_PRELOADED_STATE_REQUIRED')
    cache = state.get('tanStackQuery')
    need(type(cache) is dict and type(cache.get('queries')) is list
         and len(cache['queries']) <= 250, 'PRIOR_QUERY_CACHE_INVALID')
    docs = []
    for q in cache['queries']:
        if type(q) is not dict or type(q.get('state')) is not dict:
            continue
        d = q['state'].get('data')
        if type(d) is dict:
            docs.append(d)
    return docs


def documents_from_html(html):
    # Reuse the existing strict duplicate-key/nonfinite JSON reader.
    from .keirin_winticket_embedded_odds import read_preloaded_json
    return documents_from_state(read_preloaded_json(html))


def _roster(doc, sid):
    entries = doc.get('entries')
    if type(entries) is not list or len(entries) not in (7, 9):
        return None
    if any(type(e) is not dict or e.get('raceId') != sid for e in entries):
        return None
    numbers = [e.get('number') for e in entries]
    need(all(type(n) is int for n in numbers) and
         sorted(numbers) == list(range(1, len(entries)+1)),
         'PRIOR_ENTRY_NUMBERS_INVALID')
    ids = [e.get('playerId') for e in entries]
    need(all(type(i) is str and 0 < len(i) <= 100 for i in ids)
         and len(set(ids)) == len(ids), 'PRIOR_ENTRY_IDENTITIES_INVALID')
    need(all(e.get('absent') is False for e in entries),
         'PRIOR_SCRATCHED_CARD_NOT_SUPPORTED')
    return ids


def _race_meta(docs, sid):
    found = {}
    for d in docs:
        races = d.get('races')
        if type(races) is not list:
            continue
        for r in races:
            if type(r) is dict and r.get('id') == sid:
                projection = {k:r.get(k) for k in
                    ('id','startAt','closeAt','decidedAt','class','raceType3',
                     'distance','entriesNumber')}
                found[sha256(_canonical(projection)).hexdigest()] = projection
    need(len(found) == 1, 'PRIOR_RACE_META_ABSENT_OR_CONFLICTING')
    return next(iter(found.values()))


def _class_meta(meta):
    need(type(meta['class']) is str and bool(meta['class']) and
         type(meta['raceType3']) is str and bool(meta['raceType3']) and
         type(meta['distance']) in (int,float) and
         math.isfinite(meta['distance']) and 100 <= meta['distance'] <= 10000,
         'PRIOR_CLASS_CATEGORY_DISTANCE_UNKNOWN')


def history_references(documents, *, target_race_id, target_url, captured_at,
                       venue_documents=()):
    """Join source-supplied past raceId/cupId/venue slug; no hidden endpoints."""
    need(type(documents) is list and len(documents) <= 250,
         'PRIOR_DOCUMENTS_REQUIRED')
    sid = site_id(target_race_id)
    slug, target_cup = _page_identity(target_url, target_race_id, 'racecard')
    meta = _race_meta(documents, sid)
    _class_meta(meta)
    capture = _utc(captured_at)
    cutoff = _clock(meta['closeAt'])
    need(capture < cutoff, 'TARGET_NOT_FUTURE_AT_CAPTURE')
    candidates = {}
    for d in documents:
        ids = _roster(d, sid)
        if ids is None or type(d.get('records')) is not list:
            continue
        rows = [r for r in d['records'] if type(r) is dict and r.get('playerId') in ids]
        need(len(rows) == len(ids) and {r['playerId'] for r in rows} == set(ids),
             'PRIOR_HISTORY_RIDER_JOIN_MISMATCH')
        projected = [{'playerId':r['playerId'],
                      'latestCupResults':r.get('latestCupResults',[]),
                      'latestVenueResults':r.get('latestVenueResults',[]),
                      'currentCupResults':r.get('currentCupResults',[])} for r in rows]
        key = sha256(_canonical(sorted(projected,key=lambda r:r['playerId']))).hexdigest()
        candidates[key] = (ids, projected)
    need(len(candidates) == 1, 'PRIOR_HISTORY_ABSENT_OR_CONFLICTING')
    ids, records = next(iter(candidates.values()))
    venues = {target_race_id[8:10]:slug}
    for doc in list(documents) + list(venue_documents):
        for v in doc.get('venues',[]) if type(doc.get('venues')) is list else []:
            if type(v) is dict and type(v.get('id')) is str and re.fullmatch(r'[0-9]{2}',v['id']) and type(v.get('slug')) is str and SLUG.fullmatch(v['slug']):
                need(v['id'] not in venues or venues[v['id']]==v['slug'],
                     'PRIOR_VENUE_SLUG_CONFLICT')
                venues[v['id']] = v['slug']
    refs = {}
    seen = rejected = excluded = 0
    for record in records:
        groups = []
        for name in ('latestCupResults','latestVenueResults'):
            value = record[name]
            need(type(value) is list and len(value)<=100, 'PRIOR_CUP_HISTORY_UNBOUNDED')
            groups.extend((group.get('cupId'),group.get('raceResults'))
                          for group in value if type(group) is dict)
        groups.append((target_cup,record['currentCupResults']))
        for cup, rows in groups:
            if type(rows) is not list:
                continue
            need(len(rows)<=100, 'PRIOR_RESULT_HISTORY_UNBOUNDED')
            for r in rows:
                seen += 1
                need(seen<=MAX_RECORDS,'PRIOR_RESULT_HISTORY_UNBOUNDED')
                try:
                    need(type(r) is dict and r.get('playerId') == record['playerId'],
                         'PRIOR_HISTORY_FOREIGN_RIDER')
                    rid = canonical_id(r.get('raceId'))
                    if rid[:8] >= target_race_id[:8]:
                        excluded += 1
                        continue
                    need(type(cup) is str and re.fullmatch(r'20[0-9]{8}',cup)
                         and cup[-2:] == rid[8:10], 'PRIOR_CUP_RACE_MISMATCH')
                    day=(datetime.strptime(rid[:8],'%Y%m%d')-
                         datetime.strptime(cup[:8],'%Y%m%d')).days+1
                    need(1<=day<=7 and rid[8:10] in venues, 'PRIOR_VENUE_UNMAPPED')
                    url=f'https://www.winticket.jp/keirin/{venues[rid[8:10]]}/raceresult/{cup}/{day}/{int(rid[-2:])}'
                    _page_identity(url,rid,'raceresult')
                    if rid in refs:
                        need(refs[rid]['url']==url,'PRIOR_REFERENCE_CONFLICT')
                    else:
                        refs[rid]={'race_id':rid,'url':url,'rider_ids':[]}
                    if record['playerId'] not in refs[rid]['rider_ids']:
                        refs[rid]['rider_ids'].append(record['playerId'])
                except (PriorSourceError,ValueError,TypeError):
                    rejected += 1
    return {'target':{'race_id':target_race_id,'as_of':captured_at,
                     'cutoff':cutoff.isoformat(),'venue':target_race_id[8:10],
                     'race_class':meta['class'],'distance_m':meta['distance'],
                     'race_category':meta['raceType3']},
            'rider_ids':ids,
            'references':sorted(refs.values(),key=lambda r:r['race_id'],reverse=True),
            'history_rows_seen':seen,'excluded_current_or_future_rows':excluded,
            'rejected_or_unmapped_rows':rejected,'forecast_created':False}


def _agari(raw):
    # Provider finalHalfRecord is seconds only when directly in the plausible
    # displayed range. Never silently divide undocumented integer tenths.
    if type(raw) is str and re.fullmatch(r'[0-9]{1,2}(?:\.[0-9]{1,3})?',raw):
        raw=float(raw)
    return float(raw) if type(raw) in (int,float) and math.isfinite(raw) and 8<=raw<=30 else None


def normalize_result_event(documents, *, source_url, expected_race_id,
                           source_sha256, captured_at, target_cutoff_at):
    """Full prior field only. Retrospective lineup and actual finish clock stay unknown."""
    _page_identity(source_url,expected_race_id,'raceresult')
    need(type(source_sha256) is str and re.fullmatch(r'[0-9a-f]{64}',source_sha256),
         'PRIOR_SOURCE_SHA_REQUIRED')
    sid=site_id(expected_race_id)
    now=_utc(captured_at)
    need(now<_utc(target_cutoff_at),'PAST_RESULT_CAPTURE_TOO_LATE_FOR_TARGET')
    meta=_race_meta(documents,sid)
    _class_meta(meta)
    start=_clock(meta['startAt'])
    need(start<now,'PRIOR_EVENT_HAS_NOT_STARTED')
    pub=_clock(meta['decidedAt']) if type(meta['decidedAt']) is int and meta['decidedAt']>0 else None
    if pub is not None:
        need(start<pub<=now,'PRIOR_RESULT_PUBLICATION_INVALID')
    candidates={}
    for doc in documents:
        ids=_roster(doc,sid)
        if ids is None or type(doc.get('results')) is not list:
            continue
        rows=[r for r in doc['results'] if type(r) is dict and r.get('raceId')==sid]
        need(len(rows)==len(ids) and len({r.get('playerId') for r in rows})==len(ids)
             and {r.get('playerId') for r in rows}==set(ids),
             'PRIOR_RESULT_ROSTER_MISMATCH')
        field=[]
        for row in rows:
            order=row.get('order')
            has_accident=row.get('hasAccident')
            need(type(has_accident) is bool,'PRIOR_FINISH_STATUS_UNKNOWN')
            finish=(order if not has_accident and type(order) is int and
                    1<=order<=len(ids) else None)
            field.append({'rider_id':row['playerId'],'finish_rank':finish,
                          'line_id':None,'agari_s':_agari(row.get('finalHalfRecord')) if finish is not None else None,
                          'final_two_splits':None})
        ranks=[r['finish_rank'] for r in field if r['finish_rank'] is not None]
        need(bool(ranks) and len(set(ranks))==len(ranks),
             'PRIOR_FINISH_RANK_CONFLICT')
        field=sorted(field,key=lambda r:r['rider_id'])
        candidates[sha256(_canonical(field)).hexdigest()]=field
    need(len(candidates)==1,'PRIOR_RESULT_ABSENT_OR_CONFLICTING')
    return {'race_id':expected_race_id,'started_at':start.isoformat(),
            'ended_at':None,'lineup_published_at':None,
            'result_published_at':pub.isoformat() if pub else None,
            'result_captured_at':captured_at,
            'lineup_source_url':None,'lineup_source_sha256':None,
            'result_source_url':source_url,'result_source_sha256':source_sha256,
            'venue':expected_race_id[8:10],'race_class':meta['class'],
            'distance_m':meta['distance'],'race_category':meta['raceType3'],
            'starters':next(iter(candidates.values()))}


def safe_prior_counts(reference,events):
    return {'schema':'RACE_AI_KEIRIN_REAL_PRIOR_SOURCE_COUNTS_V1',
            'target_riders':len(reference['rider_ids']),
            'past_source_references':len(reference['references']),
            'prior_result_pages_verified':len(events),
            'prior_rider_results_verified':sum(len(e['starters']) for e in events),
            'prior_half_lap_times_verified':sum(r['agari_s'] is not None for e in events for r in e['starters']),
            'current_or_future_rows_excluded':reference['excluded_current_or_future_rows'],
            'source_rows_rejected_or_unmapped':reference['rejected_or_unmapped_rows'],
            'model_input_admitted':False,'forecasts_created':0,
            'public_athlete_data_written':False}


def observed_prior_candidates(reference, events, *, as_of):
    """Use the EXISTING fixed prior equations, with observed-before-target evidence.

    No fictional pre-race lineup publication or actual end timestamp is inserted
    to pass the older complete-evidence packet contract. Unknown lineup excludes
    coordination only; it does not discard valid observed half-lap/venue data.
    These remain explicit candidates, NOT auto-admitted PR71 input fields.
    """
    from .keirin_historical_prior_signal_rules import (
        _field, LOOKBACK_DAYS, MIN_FINISH_SAMPLES, MIN_SPLIT_SAMPLES,
        MIN_LINE_SAMPLES, MIN_VENUE_SAMPLES, MIN_COMPARISON_SAMPLES,
        FORMULA_VERSION,
    )
    target = reference['target']
    now = _utc(as_of)
    need(_utc(target['as_of']) <= now < _utc(target['cutoff']),
         'HISTORY_COMPUTATION_NOT_BEFORE_TARGET')
    need(type(events) is list and len(events) <= 100,
         'PRIOR_COMPUTATION_EVENT_LIMIT')
    seen = set()
    for event in events:
        rid = event['race_id']
        need(rid not in seen and rid != target['race_id'],
             'PRIOR_COMPUTATION_DUPLICATE_OR_TARGET')
        seen.add(rid)
        start = _utc(event['started_at'])
        capture = _utc(event['result_captured_at'])
        need(start < capture <= now, 'PRIOR_RESULT_NOT_OBSERVED_ASOF')
        published = event['result_published_at']
        if published is not None:
            need(start < _utc(published) <= capture,
                 'PRIOR_RESULT_PUBLISH_AFTER_CAPTURE')
        need(event['ended_at'] is None and
             event['lineup_published_at'] is None and
             event['lineup_source_url'] is None and
             event['lineup_source_sha256'] is None and
             all(row['line_id'] is None and row['final_two_splits'] is None
                 for row in event['starters']),
             'RETROSPECTIVE_SOURCE_CANNOT_INVENT_LINE_OR_SPLITS')
    oldest = now - timedelta(days=LOOKBACK_DAYS)
    riders = {}
    for rider_id in reference['rider_ids']:
        eligible = []
        for event in events:
            if (event['race_class'] != target['race_class'] or
                event['race_category'] != target['race_category'] or
                event['distance_m'] != target['distance_m'] or
                _utc(event['started_at']) < oldest or
                rider_id not in {x['rider_id'] for x in event['starters']}):
                continue
            own=next(row for row in event['starters'] if row['rider_id']==rider_id)
            if own['finish_rank'] is None:
                continue
            eligible.append({**_field(event, rider_id), 'venue':event['venue']})
        finish = [e['closing_percentile'] for e in eligible
                  if e['closing_percentile'] is not None]
        same = [e for e in eligible if e['venue'] == target['venue']]
        other = [e for e in eligible if e['venue'] != target['venue']]
        home_p = ((sum(e['own_top3'] for e in same)+1)/(len(same)+2)
                  if same else None)
        other_p = ((sum(e['own_top3'] for e in other)+1)/(len(other)+2)
                   if other else None)
        def candidate(value, n, minimum):
            return {'candidate_value':value if n>=minimum else None,
                    'sample_count':n, 'minimum_required':minimum,
                    'approved_for_pr71_input':False,
                    'status':'OBSERVED_PRIOR_RESEARCH_CANDIDATE' if n>=minimum
                             else 'INSUFFICIENT_PAST_SAMPLES'}
        features = {
            'finishing_power':candidate(math.fsum(finish)/len(finish)
                if finish else None, len(finish), MIN_FINISH_SAMPLES),
            'bank_fit':candidate(0.5+0.5*(home_p-other_p)
                if home_p is not None and other_p is not None else None,
                min(len(same),len(other)),
                max(MIN_VENUE_SAMPLES,MIN_COMPARISON_SAMPLES)),
            'line_coordination':candidate(None,0,MIN_LINE_SAMPLES),
            'sprint_acceleration':candidate(None,0,MIN_SPLIT_SAMPLES),
        }
        features['bank_fit'].update(same_venue_count=len(same),
                                    other_venue_count=len(other))
        riders[rider_id] = {'features':features,'matched_prior_events':len(eligible)}
    fingerprint = sha256(_canonical({'target':target, 'as_of':as_of,
                                    'prior_events':events})).hexdigest()
    return {'schema':'RACE_AI_KEIRIN_OBSERVED_PRIOR_CANDIDATES_V1',
            'formula_version':FORMULA_VERSION,
            'source_packet_sha256':fingerprint,
            'as_of':as_of,'riders':riders,
            'source_time_basis':'ACTUAL_CAPTURE_BEFORE_TARGET_NOT_BACKDATED_PUBLICATION',
            'original_formula_coefficients_unchanged':True,
            'source_rights_independently_verified':False,
            'model_input_admitted':False,'forecasts_created':0}
