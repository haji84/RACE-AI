"""Bounded in-run result observation with immediate private publication.

The controller owns no network client, authority decision, scorer or storage.
``tick`` must preserve provider-denial latches itself and return only an already
admitted display snapshot. ``publish`` must encrypt, retain and verify that
snapshot before returning. Their exception text and payloads never enter the
controller's public summary. A successful offline callback is not a live proof.
"""
from hashlib import sha256
import json
import math
import re


SCHEMA = 'RACE_AI_KEIRIN_RESULT_OBSERVER_V1'
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


class ObserverError(ValueError):
    pass


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _tick_payload(value):
    if (type(value) is not dict or
            type(value.get('provider_denied')) is not bool or
            type(value.get('done')) is not bool):
        raise ObserverError('OBSERVER_TICK_INVALID')
    snapshot = value.get('snapshot')
    if snapshot is not None and type(snapshot) is not dict:
        raise ObserverError('OBSERVER_TICK_INVALID')
    fingerprint = value.get('fingerprint')
    if (fingerprint is not None and
            (type(fingerprint) is not str or
             re.fullmatch('[a-f0-9]{64}', fingerprint) is None)):
        raise ObserverError('OBSERVER_TICK_INVALID')
    if snapshot:
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ObserverError('OBSERVER_TICK_INVALID')
        # A supplied digest is the trusted producer's stable content identity,
        # not an authority proof. It may exclude acquisition-time metadata.
        fingerprint = fingerprint or sha256(raw).hexdigest()
        snapshot = json.loads(raw)
    return snapshot, fingerprint, value['provider_denied'], value['done']


def run_observer(*, tick, publish, stop_check, monotonic, sleep,
                 interval_seconds=60, duration_seconds=540, max_ticks=10):
    """Observe within one bounded runner lease, publishing each change at once.

    ``stop_check()`` returns an actual bool, where True prohibits another tick.
    ``tick()`` returns ``{snapshot: dict | None, provider_denied: bool,
    done: bool, fingerprint?: lowercase_sha256}``. A pending tick supplies no
    snapshot; this module never manufactures an outcome, score, or authority.
    Identical adjacent content is skipped, while subsequent corrections and
    reversions retain their order. Cross-run idempotency belongs to the durable
    publisher, so the first fresh snapshot in each run reaches that publisher.

    A tick that captured a valid result before an optional-source denial may
    supply both a snapshot and ``provider_denied=True``. The snapshot is sent
    to the publisher before this controller stops. No callback is retried.

    The minimum provider-tick interval is 60 seconds. Sleep is split into at
    most 60-second chunks for process cancellation. Callbacks must bound their
    own network I/O; a controller cannot interrupt a blocking Python callback.
    """
    if (not _number(interval_seconds) or not 60 <= interval_seconds <= 600 or
            not _number(duration_seconds) or not 0 < duration_seconds <= 21600 or
            type(max_ticks) is not int or not 1 <= max_ticks <= 360):
        raise ObserverError('OBSERVER_INVALID_BOUNDS')
    if not all(callable(fn) for fn in (tick, publish, stop_check, monotonic, sleep)):
        raise ObserverError('OBSERVER_INVALID_CALLBACKS')

    report = dict(schema=SCHEMA, state='RESULT_OBSERVER_WINDOW_ENDED', ticks=0,
                  published_snapshots=0, provider_denied=False, done=False,
                  no_provider_tick=True)
    last_clock = None
    last_published = None

    def now():
        nonlocal last_clock
        value = monotonic()
        if (not _number(value) or value < 0 or
                (last_clock is not None and value < last_clock)):
            raise ObserverError('OBSERVER_CLOCK_INVALID')
        last_clock = value
        return value

    def finish(state):
        report['state'] = state
        return report

    try:
        deadline = now() + duration_seconds
    except Exception:
        return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')

    while report['ticks'] < max_ticks:
        try:
            if now() >= deadline:
                return finish('RESULT_OBSERVER_WINDOW_ENDED')
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')
        try:
            stopped = stop_check()
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_STOP_CHECK_FAILED')
        if type(stopped) is not bool:
            return finish('HOLD_RESULT_OBSERVER_STOP_CHECK_INVALID')
        if stopped:
            report['provider_denied'] = True
            return finish('HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        try:
            # Reading Git state for a stop check can itself take time.
            if now() >= deadline:
                return finish('RESULT_OBSERVER_WINDOW_ENDED')
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')

        report['ticks'] += 1
        report['no_provider_tick'] = False
        try:
            value = tick()
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_TICK_FAILED')
        try:
            snapshot, fingerprint, denied, done = _tick_payload(value)
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_TICK_INVALID')
        report['provider_denied'] = denied
        report['done'] = done
        if snapshot and fingerprint != last_published:
            try:
                publish(snapshot)
            except Exception:
                return finish('HOLD_RESULT_OBSERVER_PUBLICATION_FAILED')
            report['published_snapshots'] += 1
            last_published = fingerprint
        if denied:
            return finish('HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        if done:
            return finish('RESULT_OBSERVER_COMPLETE')
        if report['ticks'] >= max_ticks:
            return finish('RESULT_OBSERVER_TICK_LIMIT')

        try:
            current = now()
            wake_at = min(deadline, current + interval_seconds)
        except Exception:
            return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')
        while current < wake_at:
            try:
                sleep(min(60, wake_at - current))
            except Exception:
                return finish('HOLD_RESULT_OBSERVER_SLEEP_FAILED')
            try:
                updated = now()
                # An injected or broken clock must not cause an infinite wait.
                if updated <= current:
                    return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')
                current = updated
            except Exception:
                return finish('HOLD_RESULT_OBSERVER_CLOCK_INVALID')
    return finish('RESULT_OBSERVER_TICK_LIMIT')
