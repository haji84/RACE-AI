"""Attach reviewed historical context to conditional paths without reweighting.

An observation describes a past opportunity. It is neither a transferable
ability score nor a calibrated probability for the current scenario.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

from . import keirin_tactical_observations as tactics
from .keirin_tactical_packets import _clock, _tactical_rows

JST = ZoneInfo('Asia/Tokyo')
_ADMITTED = object()


def _need(condition, code):
    if not condition:
        raise ValueError('KEIRIN_TACTICAL_' + code)


def _fingerprint(snapshot):
    return sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class TacticalContext:
    """A snapshot-bound private projection; public receipts contain only counts."""

    def __init__(self, snapshot, profiles, receipt, *, _admitted=None):
        _need(_admitted is _ADMITTED, 'CONTEXT_NOT_ADMITTED')
        self._snapshot_sha256 = _fingerprint(snapshot)
        self._profiles = deepcopy(profiles)
        self._receipt = deepcopy(receipt)

    @property
    def receipt(self):
        return deepcopy(self._receipt)

    def check_snapshot(self, snapshot):
        _need(self._snapshot_sha256 == _fingerprint(snapshot), 'CONTEXT_SNAPSHOT_CHANGED')

    def for_car(self, car):
        return deepcopy(self._profiles.get(car))

    def actors(self, cars):
        return [self.for_car(car) for car in sorted(set(cars)) if car in self._profiles]


def prepare_context(snapshot, *, packet_raw, expected_sha256, as_of, cutoff_at,
                    verify_starter, clock=None):
    """Reuse the dossier gate and verify current starters through the source owner.

    ``verify_starter(race_id, rider)`` must independently bind the current car,
    registration and rider identity to the saved source. SHA admission alone
    does not attest the review or establish an actual pre-cutoff original.
    The existing conservative exclusion of all target-day observations applies.
    """
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    _need(isinstance(now, datetime) and now.utcoffset() is not None and callable(verify_starter),
          'CONTEXT_CLOCK')
    at, cutoff = _clock(as_of), _clock(cutoff_at)
    rid = snapshot.get('race_id')
    _need(type(rid) is str and re.fullmatch(r'20[0-9]{10}', rid) is not None, 'CONTEXT_RACE')
    day = datetime.strptime(rid[:8], '%Y%m%d').date()
    _need(at < cutoff and at <= now and cutoff.astimezone(JST).date() == day, 'CONTEXT_CLOCK')
    riders = snapshot.get('riders')
    _need(type(riders) is list and 0 < len(riders) <= 9, 'CONTEXT_STARTERS')
    cars = Counter(row.get('car') for row in riders)
    registrations = Counter(row.get('registration') for row in riders)
    held = Counter()
    admitted = {}
    for rider in riders:
        car, registration = rider.get('car'), rider.get('registration')
        if (type(car) is not int or not 1 <= car <= 9 or cars[car] != 1 or
                type(registration) is not str or registration == '000000' or
                re.fullmatch(r'[0-9]{6}', registration) is None):
            held['STARTER_IDENTITY_UNAVAILABLE'] += 1
        elif registrations[registration] != 1:
            held['STARTER_IDENTITY_CONFLICT'] += 1
        elif verify_starter(rid, deepcopy(rider)) is not True:
            held['STARTER_UNVERIFIED'] += 1
        else:
            admitted[car] = registration
    rows, meta = _tactical_rows(packet_raw, expected_sha256, set(admitted.values()), day, at)
    profiles = {}
    for car, registration in admitted.items():
        episodes = rows.get(registration, [])
        if not episodes:
            continue
        verified = {id(row) for row in episodes}
        profile = tactics.profile_episodes(episodes, registration=registration,
            as_of=meta['review_available_before'], target_race_id=rid,
            verify=lambda row: id(row) in verified)
        profiles[car] = dict(profile, car=car, applicability='HISTORICAL_CONTEXT_ONLY',
                             source_packet_sha256=expected_sha256)
    receipt = dict(meta, schema='KEIRIN_TACTICAL_CONTEXT_RECEIPT_V1', as_of=as_of,
        verified_starters=len(admitted), riders_with_observations=len(profiles),
        identity_held_by_reason=dict(held), predictive_model_changed=False,
        scenario_probabilities_changed=False, pre_cutoff_original_verified=False,
        replayed_after_target_cutoff=now >= cutoff)
    return TacticalContext(snapshot, profiles, receipt, _admitted=_ADMITTED)


def attach_comparison(snapshot, comparison, context):
    """Add context after the existing A/B selection has finished."""
    _need(isinstance(context, TacticalContext), 'CONTEXT_TYPE')
    context.check_snapshot(snapshot)
    candidate = comparison['candidate']
    candidate['tactical_context'] = context.receipt
    for car, position in candidate['position_evidence'].items():
        if context.for_car(car) is not None:
            position['historical_tactical_context'] = context.for_car(car)
    for arm in ('A', 'B'):
        for scenario in candidate[arm]['six_phase_scenarios']:
            actors = [scenario.get(key) for key in ('attacking_car', 'challenger_car', 'faded_car')]
            actors.extend(event[key] for event in scenario.get('finish_transitions', [])
                          for key in ('overtaker', 'passed'))
            notes = context.actors(car for car in actors if type(car) is int)
            if notes:
                scenario['historical_tactical_context'] = notes
    return comparison


def attach_responses(snapshot, paths, context):
    _need(isinstance(context, TacticalContext), 'CONTEXT_TYPE')
    context.check_snapshot(snapshot)
    for path in paths:
        for move in path['moves']:
            notes = context.actors([move['actor_car'], move['countered_car'],
                                    *move['conditional_followers']])
            if notes:
                move['historical_tactical_context'] = notes
    return paths
