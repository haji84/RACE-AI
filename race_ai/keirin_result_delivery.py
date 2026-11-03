"""Turn permission-admitted KEIRIN result deliveries into PR72 revision batches.

This is an adapter, NOT a new result scorer/forecast model, a scraper, or proof
of source use rights. The trusted owner runtime must verify both the rights
record and the source provenance before calling this code. No remote I/O.

Existing consumers: evaluation_result_revision_bridge.link_result_revisions()
                  evaluation_result_revision_bridge.research_score_existing_seal()

Public-safe output remains RESEARCH_ONLY until source authority, independent
pre-cutoff forecast receipts and full-day denominator are separately verified.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

FEED = 'RACE_AI_KEIRIN_NORMALIZED_RESULT_DELIVERY_V1'
BATCH = 'RACE_AI_OFFLINE_RESULT_OBSERVATIONS_V1'
SCOPE = 'OPERATOR_SUPPLIED_UNAUTHENTICATED_RESEARCH'
RESULT_STATUSES = frozenset({'FINAL_NORMAL','CANCELLED','NOT_OFFERED',
    'PENDING','SOURCE_UNAVAILABLE','CUTOFF_MISMATCH','UNSUPPORTED_SPECIAL'})
REFUNDS = frozenset({'NONE','PARTIAL','FULL','UNKNOWN'})
SHA_RE = re.compile(r'^[0-9a-f]{64}$')
JST = timezone(timedelta(hours=9))
MAX_FEED_BYTES = 4*1024*1024
MAX_RESULTS = 100


class KeirinDeliveryError(ValueError):
    """No raw licensed source information appears in exceptions."""


def _require(ok, code):
    if not ok:
        raise KeirinDeliveryError(code)


def _strict_pairs(pairs):
    out = {}
    for k, v in pairs:
        _require(k not in out, 'DUPLICATE_JSON_KEY')
        out[k] = v
    return out


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise KeirinDeliveryError('INVALID_CANONICAL_JSON') from None


def digest(value):
    return sha256(canonical(value)).hexdigest()


def utc(value):
    _require(type(value) is str and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)',
        value) is not None, 'TIME_WITH_OFFSET_REQUIRED')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(parsed.utcoffset() is not None, 'TIME_WITH_OFFSET_REQUIRED')
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise KeirinDeliveryError('INVALID_TIME') from None


def _day(s):
    _require(type(s) is str, 'DATE_REQUIRED')
    try:
        _require(date.fromisoformat(s).isoformat() == s, 'INVALID_DATE')
    except ValueError:
        raise KeirinDeliveryError('INVALID_DATE') from None
    return s


def _ticket(v, starters):
    _require(type(v) is list and len(v) == 3 and
             all(type(n) is int and n in starters for n in v) and len(set(v)) == 3,
             'INVALID_TRIFECTA')
    return tuple(v)


def _exact(obj, keys, code):
    _require(type(obj) is dict and set(obj) == set(keys.split()), code)


def _source_url(value):
    _require(type(value) is str and len(value) <= 2048, 'INVALID_SOURCE_URL')
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError:
        raise KeirinDeliveryError('INVALID_SOURCE_URL') from None
    _require(u.scheme == 'https' and u.hostname in ('keirin.jp','www.keirin.jp') and
             u.username is None and u.password is None and port is None and
             u.path.startswith('/') and u.fragment == '', 'NON_OFFICIAL_KEIRIN_URL')
    return value


def _race_records(bridge):
    _require(type(bridge) is dict and bridge.get('schema') ==
             'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1' and
             bridge.get('mode') == 'OFFLINE_RESEARCH_COVERAGE_LINK' and
             bridge.get('formal_hit_at_8_all') is None and
             type(bridge.get('records')) is list, 'UNVERIFIED_BRIDGE')
    day = _day(bridge.get('event_date_jst'))
    races = {}
    for item in bridge['records']:
        _require(type(item) is dict and type(item.get('race_id')) is str, 'BAD_BRIDGE_RACE')
        rid = item['race_id']
        if item.get('sport') == 'keirin':
            _require(item.get('event_date_jst') == day and
                     type(item.get('venue')) is str and item['venue'] and
                     type(item.get('race_no')) is int and 1 <= item['race_no'] <= 99 and
                     rid == f"keirin:{day}:{item['venue']}:{item['race_no']}" and
                     rid not in races, 'BAD_BRIDGE_RACE')
            races[rid] = item
    return day, races


def _verify_admission(admission, feed, raw_digest, now):
    """A receipt must come from a separately trusted owner runtime.

    The receipt itself is not a rightsholder licence or provider signature.
    An untrusted caller can fabricate it, so this adapter NEVER sets formal
    result authentication to true. Integrators must verify the rightsholder's
    actual grant and delivered bytes outside this method.
    """
    _exact(admission, 'source_id source_url source_sha256 rights_ref '
                      'verified_purposes checked_at expires_at', 'ADMISSION_FIELDS')
    _require(type(admission['source_id']) is str and 1 <= len(admission['source_id']) <= 128 and
             type(admission['rights_ref']) is str and 1 <= len(admission['rights_ref']) <= 256 and
             type(admission['source_sha256']) is str and SHA_RE.fullmatch(admission['source_sha256']) and
             admission['source_sha256'] == raw_digest and
             _source_url(admission['source_url']) == feed['source_url'], 'ADMISSION_SOURCE_MISMATCH')
    _require(type(admission['verified_purposes']) is list and
             {'result_collection', 'private_retention', 'result_analysis'} <= set(
                 admission['verified_purposes']) and
             all(type(p) is str for p in admission['verified_purposes']),
             'RESULT_PURPOSES_NOT_ADMITTED')
    _require(utc(admission['checked_at']) <= utc(feed['captured_at']) <= now <
             utc(admission['expires_at']), 'ADMISSION_TIME_INVALID')
    return admission


def _prior_chains(day, races, previous_batches):
    _require(type(previous_batches) in (list,tuple) and len(previous_batches) <= 100,
             'PREVIOUS_BATCH_LIMIT')
    history = {}
    for batch in previous_batches:
        _exact(batch, 'schema scope event_date_jst observations', 'BAD_PRIOR_BATCH')
        _require(batch['schema'] == BATCH and batch['scope'] == SCOPE and
                 batch['event_date_jst'] == day and
                 type(batch['observations']) is list, 'BAD_PRIOR_BATCH')
        for o in batch['observations']:
            rid = o.get('race_id') if type(o) is dict else None
            _require(rid in races and type(o.get('revision')) is int and
                     type(o.get('observed_at')) is str and
                     type(o.get('source_sha256')) in (str,type(None)), 'BAD_PRIOR_OBSERVATION')
            history.setdefault(rid,[]).append(o)
    for rid, seq in history.items():
        seq.sort(key=lambda x:x['revision'])
        for index, item in enumerate(seq,1):
            _require(item['revision'] == index and
                     item['previous_observation_sha256'] ==
                     (None if index == 1 else digest(seq[index-2])) and
                     (index == 1 or utc(item['observed_at']) >= utc(seq[index-2]['observed_at'])),
                     'BROKEN_PRIOR_CHAIN')
    return history


def build_research_batch(bridge, raw_feed, *, admission=None, reviewed_at=None,
                         previous_batches=()):
    """Normalize only separately admitted, supplied bytes for the existing bridge.

    No network, no public release, no formal score and no prediction update.
    Admission must be injected by a separately trusted owner boundary; merely
    typing a dict with allow-list fields is not an actual license.
    """
    _require(type(raw_feed) is bytes and 0 < len(raw_feed) <= MAX_FEED_BYTES,
             'FEED_SIZE_INVALID')
    _require(admission is not None, 'INDEPENDENT_PERMISSION_ADMISSION_REQUIRED')
    _require(reviewed_at is not None, 'TRUSTED_REVIEW_TIME_REQUIRED')
    now = utc(reviewed_at)
    try:
        feed = json.loads(raw_feed.decode('utf-8'), object_pairs_hook=_strict_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              KeirinDeliveryError('NONFINITE_NUMBER')))
    except KeirinDeliveryError:
        raise
    except (ValueError, UnicodeError):
        raise KeirinDeliveryError('MALFORMED_SOURCE_BYTES') from None
    _exact(feed, 'schema event_date_jst source_url source_published_at captured_at results',
           'BAD_FEED_FIELDS')
    _require(feed['schema'] == FEED and type(feed['results']) is list and
             0 < len(feed['results']) <= MAX_RESULTS, 'BAD_FEED_SCHEMA')
    day, races = _race_records(bridge)
    _require(feed['event_date_jst'] == day, 'DAY_MISMATCH')
    _source_url(feed['source_url'])
    observed = utc(feed['captured_at'])
    _require(observed <= now and observed.astimezone(JST).date() >= date.fromisoformat(day),
             'CAPTURE_TIME_INVALID')
    published = feed['source_published_at']
    _require(published is None or utc(published) <= observed,
             'PUBLICATION_AFTER_CAPTURE')
    _verify_admission(admission, feed, sha256(raw_feed).hexdigest(), now)
    history = _prior_chains(day,races,previous_batches)
    observed_ids = set()
    output=[]
    for result in feed['results']:
        _exact(result,'race_id starters status winning_triples payouts_100yen '
                      'refund_status provider_revision_ref official_cutoff_at',
               'RESULT_FIELDS')
        rid=result['race_id']
        _require(type(rid) is str and rid in races and rid not in observed_ids,
                 'UNKNOWN_OR_DUPLICATE_RACE')
        observed_ids.add(rid)
        starters=result['starters']
        _require(type(starters) is list and 3 <= len(starters) <= 9 and
                 all(type(n) is int and 1 <= n <= 9 for n in starters) and
                 len(set(starters)) == len(starters), 'BAD_STARTERS')
        status=result['status'];refund=result['refund_status']
        _require(type(status) is str and status in RESULT_STATUSES and
                 type(refund) is str and refund in REFUNDS, 'BAD_RESULT_STATE')
        cutoff = utc(result['official_cutoff_at'])
        _require(cutoff.astimezone(JST).date() == date.fromisoformat(day) and
                 cutoff <= observed, 'RESULT_BEFORE_CUTOFF')
        wins = result['winning_triples'];pay = result['payouts_100yen']
        _require(type(wins) is list and type(pay) is list and
                 len(wins) <= 20 and len(pay) <= 20, 'BAD_RESULT_LISTS')
        unique_winners = [_ticket(v,set(starters)) for v in wins]
        _require(len(set(unique_winners)) == len(unique_winners), 'DUPLICATE_TRIFECTA')
        payout_tickets=[]
        for item in pay:
            _exact(item,'triple yen','PAYOUT_FIELDS')
            _require(type(item['yen']) is int and 0 < item['yen'] <= 10**9,
                     'BAD_PAYOUT')
            payout_tickets.append(_ticket(item['triple'],set(starters)))
        _require(len(set(payout_tickets)) == len(payout_tickets), 'DUPLICATE_PAYOUT')
        if status == 'FINAL_NORMAL':
            _require(wins and set(unique_winners) == set(payout_tickets) and
                     refund != 'FULL', 'INCONSISTENT_FINAL_RESULT')
        else:
            _require(not wins and not pay, 'NON_FINAL_HAS_WINNERS')
        prior = history.get(rid,[])
        revision_ref = result['provider_revision_ref']
        _require(revision_ref is None or
                 (type(revision_ref) is str and 1 <= len(revision_ref) <= 256),
                 'BAD_PROVIDER_REVISION_REF')
        candidate = {
            'race_id':rid, 'revision':len(prior)+1,
            'previous_observation_sha256':None if not prior else digest(prior[-1]),
            'observed_at':feed['captured_at'],
            'source_id':admission['source_id'],
            'source_url':feed['source_url'],
            'source_sha256':admission['source_sha256'] if status != 'SOURCE_UNAVAILABLE' else None,
            'source_published_at':published,
            'provider_revision_ref':revision_ref,
            'status':status, 'winning_triples':wins,
            'payouts_100yen':pay, 'refund_status':refund,
        }
        if prior:
            prev = prior[-1]
            identity = ('status','winning_triples','payouts_100yen','refund_status',
                        'provider_revision_ref','source_sha256')
            if all(prev.get(k) == candidate.get(k) for k in identity):
                # Re-reading an unchanged source does not invent a new revision.
                continue
            _require(utc(candidate['observed_at']) >= utc(prev['observed_at']) and
                     (revision_ref is not None or
                      (candidate['source_sha256'] is not None and
                       candidate['source_sha256'] != prev.get('source_sha256'))),
                     'UNWITNESSED_RESULT_CHANGE')
        output.append(candidate)
    return {'schema':BATCH,'scope':SCOPE, 'event_date_jst':day,'observations':output}


def research_hit8(batch, frozen_by_race):
    """Optional, explicitly unofficial comparison; missing forecast is not a win.

    A caller-supplied forecast map alone is NOT proof of an externally frozen,
    deadline-valid original. This method never returns an official KPI.
    """
    _require(type(frozen_by_race) is dict, 'FORECAST_MAP_REQUIRED')
    reports=[]
    for item in batch['observations']:
        rid=item['race_id']
        record=frozen_by_race.get(rid)
        if item['status']!='FINAL_NORMAL' or item['refund_status']!='NONE':
            reports.append({'race_id':rid,'research_hit8':None,
                            'reason':'RESULT_NOT_SIMPLE_SETTLED','formal_hit8':None})
            continue
        if record is None:
            reports.append({'race_id':rid,'research_hit8':None,
                            'reason':'FORECAST_NOT_AVAILABLE','formal_hit8':None})
            continue
        _exact(record,'top8 original_generated_at original_cutoff_at model_version',
               'RESEARCH_FORECAST_FIELDS')
        picks = record['top8']
        _require(type(picks) is list and 1 <= len(picks) <= 8 and
                 len({tuple(p) for p in picks if type(p) is list}) == len(picks),
                 'BAD_RESEARCH_TOP8')
        for ticket in picks:
            _require(type(ticket) is list and len(ticket)==3 and
                     all(type(n) is int and 1 <= n <= 9 for n in ticket) and
                     len(set(ticket)) == 3, 'BAD_RESEARCH_TOP8')
        _require(utc(record['original_generated_at']) < utc(record['original_cutoff_at']) and
                 utc(record['original_cutoff_at']) <= utc(item['observed_at']),
                 'RESEARCH_FORECAST_TIMESTAMP_INVALID')
        hit=bool(set(tuple(x) for x in picks).intersection(
            tuple(x) for x in item['winning_triples']))
        reports.append({'race_id':rid,'research_hit8':hit,'reason':'REFERENCE_ONLY_UNATTESTED',
                        'model_version':record['model_version'],'formal_hit8':None})
    return {'schema':'RACE_AI_KEIRIN_RESEARCH_HIT8_V1',
            'verified_official_denominator':None,'formal_hit_at_8_all':None,
            'rows':reports}
