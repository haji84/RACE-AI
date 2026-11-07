"""Prior-day official B/K history acquisition through the caller's source guard.

No network or storage is performed here. A validated daily cache avoids repeat
requests; unavailable archives remain missing observations with a real retry.
Historical results supplement descriptions and never enter forecast models.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib

from .boat_entry_observations import build_entry_history_from_archives, conditional_profile_before
from .boat_racer_tendencies import _ts
from .official_archive_probe import official_url
from .source_retry_policy import SourceWait, wait_active

SCHEMA = 'RACE_AI_BOAT_ENTRY_SOURCE_CACHE_V1'
_FIELDS = {'schema','event_day','history_day','status','checked_at','history','missing_sources','source_wait','rejected_cache_count','cache_rejection_reason'}


def _day(value):
    if type(value) is date:return value
    result = date.fromisoformat(value)
    if result.isoformat() != value:raise ValueError('ENTRY_CACHE_DAY_INVALID')
    return result


def _clock(value):
    value = value() if callable(value) else value
    return _ts(value.isoformat() if isinstance(value, datetime) else value)


def validate_entry_history_cache(cache, *, day, as_of):
    """Validate source proofs and every settled record before admitting a cache."""
    day, clock = _day(day), _clock(as_of)
    prior = day - timedelta(days=1)
    if (not isinstance(cache, dict) or set(cache) != _FIELDS or cache['schema'] != SCHEMA
            or cache['event_day'] != day.isoformat() or cache['history_day'] != prior.isoformat()
            or _ts(cache['checked_at']) > clock):
        raise ValueError('ENTRY_CACHE_IDENTITY_OR_CLOCK_INVALID')
    if (type(cache['rejected_cache_count']) is not int or cache['rejected_cache_count'] < 0
            or cache['cache_rejection_reason'] != ('ENTRY_HISTORY_CACHE_REJECTED' if cache['rejected_cache_count'] else None)):
        raise ValueError('ENTRY_CACHE_REJECTION_METADATA_INVALID')
    if cache['status'] == 'READY':
        history = cache['history']
        if (not isinstance(history,dict) or history.get('date_jst') != prior.isoformat()
                or cache['missing_sources'] != [] or cache['source_wait'] is not None):
            raise ValueError('ENTRY_CACHE_HISTORY_INVALID')
        # The existing strict validator checks all records, including racers
        # outside today's roster. No future or late-captured labels are admitted.
        conditional_profile_before(history, as_of=clock.isoformat(), racer_id='0000')
    elif cache['status'] == 'WAITING_PUBLICATION':
        wait = cache['source_wait']
        if (cache['history'] is not None or not isinstance(wait,dict)
                or wait.get('state') != 'WAITING_PUBLICATION'
                or wait.get('reason') != 'SOURCE_NOT_YET_PUBLISHED'
                or wait.get('retry_at') is None
                or _ts(wait['retry_at']) <= _ts(cache['checked_at'])
                or cache['missing_sources'] not in ([official_url(prior,'K')],[official_url(prior,'B')])):
            raise ValueError('ENTRY_CACHE_PUBLICATION_WAIT_INVALID')
        wait_active(wait,clock)
    else:
        raise ValueError('ENTRY_CACHE_STATUS_INVALID')
    return deepcopy(cache)


def cache_from_document(document, *, day, as_of):
    """Legacy authenticated national documents legitimately have no cache."""
    cache = document.get('entry_observation_history')
    return None if cache is None else validate_entry_history_cache(cache,day=day,as_of=as_of)


def optional_cache_from_document(document, *, day, as_of):
    """Isolate rejected supplemental cache data from verified forecast receipts."""
    try:
        return cache_from_document(document,day=day,as_of=as_of),None
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError):
        return None,'ENTRY_HISTORY_CACHE_REJECTED'


def collect_previous_day_history(day, *, now, fetch, cache=None):
    """Fetch at most one daily pair unless a valid cache/publication wait exists.

    ``fetch(url)`` returns raw archive bytes, the actual aware capture datetime
    or ISO timestamp, and its SHA-256. The caller must reuse its existing HTTP
    source guard and counters. Authorization/rate-limit/source waits propagate;
    only an explicit publication wait is retained as an archive missing state.
    ``now`` may be a callable so post-request validation uses the actual clock.
    """
    day, at = _day(day), _clock(now)
    rejected = 0
    if cache is not None:
        checked,reason = optional_cache_from_document({'entry_observation_history':cache},day=day,as_of=at)
        if reason is not None:rejected=1
        elif checked['status'] == 'READY' or wait_active(checked['source_wait'],at):return checked
    prior = day - timedelta(days=1)
    texts, sources = {}, {}
    # A result archive is the one normally awaiting publication. Check it first
    # so a missing result does not repeatedly download the already-published B.
    for kind in ('K','B'):
        url = official_url(prior,kind)
        try:
            raw,captured,sha = fetch(url)
        except SourceWait as exc:
            if exc.state != 'WAITING_PUBLICATION' or exc.reason != 'SOURCE_NOT_YET_PUBLISHED':raise
            wait = dict(getattr(exc,'plan',{}) or dict(
                state=exc.state,reason=exc.reason,retry_at=exc.retry_at,http_status=404,attempts=1))
            result = dict(schema=SCHEMA,event_day=day.isoformat(),history_day=prior.isoformat(),
                status='WAITING_PUBLICATION',checked_at=_clock(now).isoformat(),history=None,
                missing_sources=[url],source_wait=wait,rejected_cache_count=rejected,
                cache_rejection_reason='ENTRY_HISTORY_CACHE_REJECTED' if rejected else None)
            return validate_entry_history_cache(result,day=day,as_of=now)
        if not isinstance(raw,bytes) or sha != hashlib.sha256(raw).hexdigest():
            raise ValueError('ENTRY_ARCHIVE_SOURCE_HASH_MISMATCH')
        captured = _clock(captured).isoformat()
        texts[kind] = raw
        sources[kind] = dict(source_url=url,source_sha256=sha,captured_at=captured)
    history = build_entry_history_from_archives(texts['B'],texts['K'],day=prior,
                                               b_source=sources['B'],k_source=sources['K'])
    result = dict(schema=SCHEMA,event_day=day.isoformat(),history_day=prior.isoformat(),
        status='READY',checked_at=_clock(now).isoformat(),history=history,missing_sources=[],source_wait=None,rejected_cache_count=rejected,
        cache_rejection_reason='ENTRY_HISTORY_CACHE_REJECTED' if rejected else None)
    return validate_entry_history_cache(result,day=day,as_of=now)
