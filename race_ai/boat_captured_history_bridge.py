"""One supplied K-day -> existing research features; no acquisition or authority.

The publication-qualified history API is unchanged. This separate bridge keeps
nullable publication as a capture claim and counts only supplied measurements.
"""
from copy import deepcopy
from datetime import date
from fractions import Fraction
import hashlib
import json
import re

from .boat_observed_program_bridge import build_program_snapshot, SOURCE_FIELDS, _reference
from .boat_observed_course_history import _sources, _rows, _time

POLICY = 'ALL_SUPPLIED_STARTS_IN_SINGLE_SOURCE_DAY'


class CapturedHistoryError(ValueError):
    """Invalid or inconsistent measured history; source content is not logged."""


def _require(value):
    if not value:
        raise CapturedHistoryError('CAPTURED_HISTORY_REJECTED') from None


def _source(source, target_day, asof):
    _require(type(source) is dict and set(source) == SOURCE_FIELDS)
    match = re.fullmatch(r'https://www1\.mbrace\.or\.jp/od2/K/(\d{6})/k(\d{6})\.lzh',
                         source['source_url']) if type(source['source_url']) is str else None
    _require(match is not None)
    day = date.fromisoformat(match[1][:4] + '-' + match[2][2:4] + '-' + match[2][4:])
    _require(match[1] == day.strftime('%Y%m') and match[2] == day.strftime('%y%m%d'))
    _require(day < date.fromisoformat(target_day))
    _reference(source['source_id'])
    _reference(source['source_rights_ref'])
    basis = source['evidence_basis']
    _require((basis == 'CAPTURED_BY_CLAIM' and source['published_at'] is None) or
             (basis == 'SOURCE_PUBLISHED_AT_CLAIM' and source['published_at'] is not None))
    record = {key: source[key] for key in ('source_url', 'source_sha256', 'published_at', 'captured_at')}
    record['event_date_jst'] = day.isoformat()
    sources, selected = _sources([record], asof)
    _require(_time(source['captured_at']) <= asof and
             selected.get(day.isoformat()) == source['source_sha256'])
    return day.isoformat(), sources


def _complete_rows(rows, sources):
    _require(type(rows) is list and len(rows) <= 1728)
    normalized = _rows(rows, sources)
    canonical_rows = {}
    for row in rows:
        _require(re.fullmatch(r'[0-9]{4}', row['racer_id']) is not None)
        key = (row['source_sha256'], row['race_id'], row['lane'])
        wire = json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)
        _require(key not in canonical_rows or canonical_rows[key] == wire)
        canonical_rows[key] = wire
    races, venues = {}, {}
    for row in normalized:
        races.setdefault(row['race_id'], []).append(row)
        venues.setdefault(row['racer_id'], set()).add(row['race_id'][9:11])
    _require(all(len(v) == 1 for v in venues.values()))
    for group in races.values():
        _require(len(group) == 6 and {r['lane'] for r in group} == set(range(1, 7)))
        finishes = [r['finish'] for r in group if r['finish'] is not None]
        _require(len(finishes) == len(set(finishes)))
    return sorted(normalized, key=lambda row: (row['race_id'], row['lane']))


def _counts(total, ok, f=0, l=0, missing=0):
    return dict(total_n=total, ok_n=ok, f_n=f, l_n=l, missing_n=missing, unresolved_n=0)


def _feature(values, source, window, counts, transform):
    return dict(value=float(sum((Fraction(str(v)) for v in values), Fraction()) / len(values)),
                sample_n=len(values), source_id=source['source_id'], transform_id=transform,
                history=dict(window_id=window, **counts))


def build_program_history_snapshot(program_race, program_source, history_rows,
                                   history_source, *, event_date_jst, as_of, race_revision):
    """Build detached P0 inputs plus private lineage; never modify an old seal.

    The caller explicitly chooses one source day/revision and owns permission,
    complete source retention and real execution time. This API authenticates
    neither the rows, their completeness nor any supplied availability claim.
    """
    try:
        snapshot = build_program_snapshot(program_race, program_source,
            event_date_jst=event_date_jst, as_of=as_of, race_revision=race_revision)
        _require(all(re.fullmatch(r'[0-9]{4}', p['registration_no']) is not None
                     for p in snapshot['participants']))
        day, sources = _source(history_source, event_date_jst, _time(as_of))
        for field in ('source_id', 'source_url', 'source_sha256'):
            _require(history_source[field] != program_source[field])
        rows = _complete_rows(history_rows, sources)
        wire = json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
        membership = hashlib.sha256(wire).hexdigest()
        snapshot['sources'].append(deepcopy(history_source))
        audits = []
        for participant in snapshot['participants']:
            registration = participant['registration_no']
            observed = [r for r in rows if r['racer_id'] == registration]
            starts = [r for r in observed if r['st_status'] != 'ABSENT']
            window = f"single-k-day:{day}:{history_source['source_sha256']}:{membership}:{registration}"
            statuses = {s: sum(r['st_status'] == s for r in starts) for s in ('OK', 'F', 'L', 'MISSING')}
            features, missing = participant['features'], participant['missing']
            finish_ok = bool(starts) and all(r['finish'] is not None and r['st_status'] not in ('F', 'L') for r in starts)
            if finish_ok:
                features['recent_mean_finish'] = _feature([r['finish'] for r in starts], history_source,
                    window, _counts(len(starts), len(starts)), 'strict_numeric_finish_mean_v1')
                del missing['recent_mean_finish']
            elif starts:
                missing['recent_mean_finish'] = 'UNRESOLVED_DISPOSITION'
            st_values = [r['st'] for r in starts if r['st_status'] == 'OK']
            if st_values:
                features['recent_mean_st'] = _feature(st_values, history_source, window,
                    _counts(len(starts), statuses['OK'], statuses['F'], statuses['L'], statuses['MISSING']),
                    'strict_ok_start_mean_seconds_v1')
                del missing['recent_mean_st']
            elif starts:
                missing['recent_mean_st'] = 'UNRESOLVED_DISPOSITION'
            audits.append(dict(registration_no=registration, lane=participant['lane'], window_id=window,
                supplied_row_n=len(observed), start_n=len(starts), absent_n=len(observed)-len(starts),
                status_counts=statuses, row_refs=deepcopy(observed),
                finish_disposition='MEASURED' if finish_ok else missing['recent_mean_finish'],
                st_disposition='MEASURED' if st_values else missing['recent_mean_st']))
        audit = dict(schema='RACE_AI_CAPTURED_SINGLE_DAY_HISTORY_V1', selection_policy=POLICY,
            source_day=day, source=deepcopy(history_source), information_as_of=as_of,
            membership_sha256=membership, input_row_count=len(history_rows),
            deduplicated_row_count=len(rows), represented_races=len(rows)//6, participants=audits,
            race_at_semantics='DATE_SENTINEL_NOT_PHYSICAL_CLOCK',
            source_bytes_authenticated=False, independent_availability_verified=False,
            publication_authenticated=False, source_rights_verified=False,
            whole_day_completeness_verified=False, provider_finality_verified=False,
            official_prediction=False)
        return dict(snapshot=snapshot, history_audit=audit)
    except Exception:
        raise CapturedHistoryError('CAPTURED_HISTORY_REJECTED') from None
