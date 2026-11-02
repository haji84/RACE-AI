"""Offline five-provider result revision join. Development-only: no fetch or authority grant."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

BRIDGE = 'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1'
BATCH = 'RACE_AI_OFFLINE_RESULT_OBSERVATIONS_V1'
REPORT = 'RACE_AI_FOUR_SPORT_RESULT_REVISION_LINK_V1'
SCOPE = 'OPERATOR_SUPPLIED_UNAUTHENTICATED_RESEARCH'
STATUSES = {'FINAL_NORMAL', 'CANCELLED', 'NOT_OFFERED', 'PENDING',
            'SOURCE_UNAVAILABLE', 'CUTOFF_MISMATCH', 'UNSUPPORTED_SPECIAL'}
REFUNDS = {'NONE', 'PARTIAL', 'FULL', 'UNKNOWN'}
HOSTS = {
    'boat': {'www.boatrace.jp', 'boatrace.jp'},
    'keirin': {'keirin.jp', 'www.keirin.jp'},
    'autorace': {'autorace.jp', 'www.autorace.jp'},
    'horse_jra': {'jra.go.jp', 'www.jra.go.jp'},
    'horse_local': {'keiba.go.jp', 'www.keiba.go.jp'},
}
SHA = re.compile(r'[0-9a-f]{64}\Z')
JST = timezone(timedelta(hours=9))


class ResultLinkError(ValueError):
    """No private observation contents in errors."""


def _need(condition, code):
    if not condition:
        raise ResultLinkError(code)


def _exact(value, keys, code):
    _need(type(value) is dict and set(value) == set(keys.split()), code)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ResultLinkError('INVALID_CANONICAL_JSON') from None


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _moment(value):
    _need(type(value) is str and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value),
        'INVALID_TIME')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None and result.utcoffset().total_seconds() % 60 == 0,
              'INVALID_TIMEZONE')
        return result.astimezone(timezone.utc)
    except ValueError:
        raise ResultLinkError('INVALID_TIME') from None


def _day(value):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\d', value), 'INVALID_DAY')
    try:
        _need(date.fromisoformat(value).isoformat() == value, 'INVALID_DAY')
    except ValueError:
        raise ResultLinkError('INVALID_DAY') from None
    return value


def _ticket(value):
    _need(type(value) is list and len(value) == 3 and
          all(type(x) is int and 1 <= x <= 99 for x in value) and
          len(set(value)) == 3, 'INVALID_TRIFECTA')
    return tuple(value)


def _check_source(sport, url):
    _need(type(url) is str and len(url) <= 2048, 'INVALID_SOURCE_URL')
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ResultLinkError('INVALID_SOURCE_URL') from None
    _need(parsed.scheme == 'https' and parsed.hostname in HOSTS[sport] and
          parsed.username is None and parsed.password is None and port is None and
          parsed.path.startswith('/') and not parsed.fragment,
          'NON_PROVIDER_SOURCE_URL')
    # Shape is neither authentication nor an automatic use licence.


def _validate_bridge(bridge):
    _need(type(bridge) is dict and bridge.get('schema') == BRIDGE and
          bridge.get('mode') == 'OFFLINE_RESEARCH_COVERAGE_LINK' and
          bridge.get('official_completeness_verified') is False and
          bridge.get('source_rights_verified') is False and
          bridge.get('external_pre_cutoff_receipts_verified') is False and
          bridge.get('formal_hit_at_8_all') is None and
          type(bridge.get('records')) is list and len(bridge['records']) <= 100000,
          'UNTRUSTED_BRIDGE_AUTHORITY')
    day = _day(bridge.get('event_date_jst'))
    rows = {}
    for row in bridge['records']:
        _need(type(row) is dict, 'INVALID_BRIDGE_ROW')
        sport, venue, no = row.get('sport'), row.get('venue'), row.get('race_no')
        _need(type(sport) is str and sport in HOSTS and type(venue) is str and
              venue and type(no) is int and 1 <= no <= 99 and
              row.get('event_date_jst') == day, 'INVALID_BRIDGE_RACE')
        key = f'{sport}:{day}:{venue}:{no}'
        _need(row.get('race_id') == key and key not in rows,
              'DUPLICATE_OR_INVALID_RACE_ID')
        rows[key] = row
    return day, rows


def _checked_observations(day, races, batches):
    _need(type(batches) in (list, tuple) and len(batches) <= 128, 'INVALID_BATCH_LIST')
    rows = defaultdict(list)
    total = 0
    for batch in batches:
        _exact(batch, 'schema scope event_date_jst observations', 'BATCH_FIELDS')
        _need(batch['schema'] == BATCH and batch['scope'] == SCOPE and
              _day(batch['event_date_jst']) == day and
              type(batch['observations']) is list and len(batch['observations']) <= 100000,
              'BATCH_SCOPE_OR_DATE')
        total += len(batch['observations'])
        _need(total <= 100000, 'OBSERVATION_BOUND')
        for item in batch['observations']:
            _exact(item, 'race_id revision previous_observation_sha256 observed_at '
                         'source_id source_url source_sha256 source_published_at '
                         'provider_revision_ref status winning_triples payouts_100yen '
                         'refund_status', 'OBSERVATION_FIELDS')
            rid, version = item['race_id'], item['revision']
            _need(type(rid) is str and rid in races and type(version) is int and
                  1 <= version <= 10000, 'UNLISTED_RACE_OR_REVISION')
            sport = races[rid]['sport']
            _check_source(sport, item['source_url'])
            source_sha = item['source_sha256']
            _need(type(item['source_id']) is str and 1 <= len(item['source_id']) <= 128 and
                  ((type(source_sha) is str and SHA.fullmatch(source_sha) is not None) or
                   (source_sha is None and item['status'] == 'SOURCE_UNAVAILABLE')),
                  'SOURCE_ID_OR_HASH')
            seen_at = _moment(item['observed_at'])
            _need(seen_at.astimezone(JST).date() >= date.fromisoformat(day),
                  'RESULT_OBSERVED_BEFORE_RACE_DATE')
            published = item['source_published_at']
            if published is not None:
                _need(_moment(published) <= seen_at, 'SOURCE_PUBLICATION_AFTER_OBSERVATION')
            _need(item['status'] in STATUSES and item['refund_status'] in REFUNDS,
                  'INVALID_RESULT_STATUS')
            _need(type(item['winning_triples']) is list and
                  type(item['payouts_100yen']) is list, 'RESULT_SHAPE')
            wins = [_ticket(v) for v in item['winning_triples']]
            _need(len(wins) == len(set(wins)) and len(wins) <= 20, 'DUPLICATE_WINNERS')
            payouts = []
            for p in item['payouts_100yen']:
                _exact(p, 'triple yen', 'PAYOUT_FIELDS')
                _need(type(p['yen']) is int and 0 < p['yen'] <= 10**9, 'PAYOUT_YEN')
                payouts.append(_ticket(p['triple']))
            _need(len(payouts) == len(set(payouts)) and len(payouts) <= 20,
                  'DUPLICATE_PAYOUT')
            if item['status'] == 'FINAL_NORMAL':
                _need(0 < len(wins) <= 20 and set(wins) == set(payouts) and
                      item['refund_status'] != 'FULL', 'INCONSISTENT_NORMAL_RESULT')
            else:
                _need(not wins and not payouts, 'UNSCORABLE_RESULT_HAS_WINNERS')
            prev = item['previous_observation_sha256']
            _need(prev is None or (type(prev) is str and SHA.fullmatch(prev)),
                  'PREVIOUS_REVISION_HASH_INVALID')
            reference = item['provider_revision_ref']
            _need(reference is None or (type(reference) is str and 1 <= len(reference) <= 256),
                  'INVALID_PROVIDER_REVISION_REF')
            rows[rid].append((version, seen_at, item, _digest(item)))
    for rid, entries in rows.items():
        entries.sort(key=lambda x:x[0])
        previous = None
        for n, (revision, instant, original, fingerprint) in enumerate(entries, 1):
            _need(revision == n, 'MISSING_OR_DUPLICATE_REVISION')
            _need(original['previous_observation_sha256'] ==
                  (None if previous is None else previous[3]), 'REVISION_CHAIN_HASH_MISMATCH')
            if previous is not None:
                _need(instant >= previous[1] and
                      (original['provider_revision_ref'] is not None or
                       (original['source_sha256'] is not None and
                        original['source_sha256'] != previous[2]['source_sha256'])),
                      'REVISION_TIME_OR_NEW_SOURCE_EVIDENCE_MISSING')
            previous = (revision, instant, original, fingerprint)
    return rows


def link_result_revisions(bridge, batches):
    """Join supplied revisions without attesting provider authenticity or formal KPIs."""
    day, races = _validate_bridge(bridge)
    observations = _checked_observations(day, races, batches)
    totals = Counter()
    by_sport = defaultdict(Counter)
    rendered = []
    for rid, row in sorted(races.items()):
        revisions = observations.get(rid, [])
        state = 'NO_RESULT_OBSERVATION' if not revisions else revisions[-1][2]['status']
        totals[state] += 1
        by_sport[row['sport']][state] += 1
        latest = revisions[-1] if revisions else None
        rendered.append({
            'race_id': rid, 'sport': row['sport'],
            'forecast_archive_slots': len(row.get('archive_slots', [])),
            'revision_count': len(revisions),
            'latest_claimed_status': state,
            'latest_claimed_refund_status': (latest[2]['refund_status'] if latest else None),
            'latest_observation_sha256': (latest[3] if latest else None),
            'latest_provider_revision_ref': (latest[2]['provider_revision_ref'] if latest else None),
            'research_result_claim_unverified': bool(revisions),
            'official_result_authenticated': False, 'formal_score_admitted': False,
        })
    return {
        'schema': REPORT, 'event_date_jst': day, 'scope': SCOPE,
        'bridge_digest_sha256': _digest(bridge), 'listed_races': len(races),
        'result_observations': sum(len(v) for v in observations.values()),
        'latest_observation_states': dict(sorted(totals.items())),
        'latest_observation_states_by_sport': {s:dict(sorted(v.items()))
                                                for s, v in sorted(by_sport.items())},
        'records': rendered,
        'official_result_authentication': False,
        'source_automated_use_authorized': False,
        'individual_pre_cutoff_receipts_verified': False,
        'official_complete_denominator': None, 'official_hit1': None,
        'official_hit8_all': None, 'official_prediction_capture_rate': None,
        'actual_purchase_roi': None, 'brier': None, 'log_loss': None,
        'private_archive_mutated': False,
    }


def research_score_existing_seal(bridge, batches, seal):
    """Use existing evaluator on a local research seal, without model reruns."""
    from .evaluation_experiment import verify_seal, score_seal
    checked = verify_seal(seal)
    day, races = _validate_bridge(bridge)
    observations = _checked_observations(day, races, batches)
    ref_by_archive = {}
    for row in races.values():
        for slot in row.get('archive_slots', []):
            if slot.get('source') != 'VERIFIED_LOCAL_EVALUATION_SEAL' or slot.get('archive_sha256') != checked['seal_sha256']:
                continue
            original = slot.get('archive_race_id')
            if original in ref_by_archive:
                _need(ref_by_archive[original] == row['race_id'], 'ARCHIVE_RACE_COLLISION')
            ref_by_archive[original] = row['race_id']
    _need(set(ref_by_archive) == {r['race_id'] for r in checked['plan']['races']},
          'INCOMPLETE_ARCHIVE_RACE_BINDING')
    output_bindings = {(o['race_id'],o['stage'],o['model_id']):o for o in checked['outputs']}
    versions = {m['model_id']:m['version'] for m in checked['plan']['models']}
    actual_bindings = set()
    for row in races.values():
        for slot in row.get('archive_slots', []):
            if slot.get('source') != 'VERIFIED_LOCAL_EVALUATION_SEAL' or slot.get('archive_sha256') != checked['seal_sha256']:
                continue
            key = (slot['archive_race_id'],slot['stage'],slot['model_id'])
            actual_bindings.add(key)
            original = output_bindings.get(key)
            _need(original is not None and original['status'] == slot.get('forecast_state') and
                  versions.get(slot['model_id']) == slot.get('model_version'), 'ARCHIVE_SLOT_MISMATCH')
    _need(actual_bindings == set(output_bindings), 'INCOMPLETE_ARCHIVE_MODEL_BINDING')
    labels = []
    for archive_id, rid in ref_by_archive.items():
        for revision, _, item, _ in observations.get(rid, ()):
            _need(item['source_id'] in checked['plan']['result_source_ids'], 'UNDECLARED_RESULT_SOURCE')
            status = ('FINAL' if item['status'] == 'FINAL_NORMAL' and item['refund_status'] == 'NONE'
                      else 'CANCELLED' if item['status'] == 'CANCELLED'
                      else 'NOT_OFFERED' if item['status'] == 'NOT_OFFERED'
                      else 'UNSUPPORTED' if item['status'] in ('UNSUPPORTED_SPECIAL','CUTOFF_MISMATCH')
                           or item['refund_status'] in ('PARTIAL','FULL')
                      else 'UNRESOLVED')
            labels.append({
                'race_id': archive_id, 'revision': revision, 'status': status,
                'winning_triples': item['winning_triples'] if status == 'FINAL' else [],
                'source_id': item['source_id'], 'source_sha256': item['source_sha256'] or ('0'*64),
                'observed_at': item['observed_at'],
            })
    scoring = score_seal(checked, labels)
    return {
        'schema':'RACE_AI_RESULT_REVISION_RESEARCH_SCORE_V1',
        'seal_sha256':checked['seal_sha256'],
        'scorer_mode':checked['plan']['mode'],
        'result_evidence':'OPERATOR_SUPPLIED_UNAUTHENTICATED',
        'development_only':True,
        'models':scoring['models'],'by_sport':scoring['by_sport'],
        'formal_hit_at_8_all':None,'private_forecasts_mutated':False,
    }
