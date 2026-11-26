"""Publishable finish counts from a pinned day of authenticated official SP results."""
from collections import Counter
from hashlib import sha256
import re

from . import keirin_official_nationwide_records as records
from . import keirin_official_run_history as history
from .keirin_nationwide_cipher_history import COMMIT, SHA
from .keirin_official_form_history import JST, _aware

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1'
NUMERIC = frozenset(('FINISHED', 'FALL_FINISHED'))
NON_NUMERIC = frozenset(('FALL_DNF', 'DISQUALIFIED', 'OTHER_DNF'))
REGISTRATION = re.compile('[0-9]{6}')
HOLD = 'OFFICIAL_RIDER_HISTORY_DAY_HELD'


def _require(ok):
    if not ok:
        raise ValueError(HOLD)


def _checked_index(store):
    _require(type(store.index_commit) is str and COMMIT.fullmatch(store.index_commit)
             and store.head == store.index_commit)
    return records.checked_index(store.index, history._day(store.day))


def _signature(index):
    results = index['results']
    relevant_originals = {race_id: index['originals'][race_id] for race_id in results}
    document = dict(schema=SCHEMA, day=index['day_jst'], originals=relevant_originals, results=results)
    return sha256(history._canonical(document)).hexdigest()


def archive_signature(store):
    """Digest only the immutable inputs that can affect an archived day's rider counts."""
    try:
        return _signature(_checked_index(store))
    except (ValueError, KeyError, TypeError, OSError, OverflowError):
        raise ValueError(HOLD) from None


def conditioned_signature(day, result_sha256, conditions_sha256):
    _require(type(conditions_sha256) is str and SHA.fullmatch(conditions_sha256))
    return sha256(history._canonical(dict(
        day=day, result_sha256=result_sha256, conditions_sha256=conditions_sha256))).hexdigest()


def _identities(rows, registration_key):
    identities = {}
    for row in rows:
        car, registration = row['car'], row[registration_key]
        _require(type(car) is int and 1 <= car <= 9 and car not in identities)
        _require(type(registration) is str and REGISTRATION.fullmatch(registration)
                 and registration != '000000')
        identities[car] = registration
    _require(5 <= len(identities) <= 9 and len(set(identities.values())) == len(identities))
    return identities


def _verified_finishes(store, original_meta, revision, owner_private_pem, as_of):
    original, replay, _ = records._replay_saved_result(store, original_meta, revision, owner_private_pem)
    final = replay['official_result']
    cutoff, updated, observed = (_aware(final[key]) for key in
                                ('official_cutoff_at', 'source_updated_at', 'observed_at'))
    sealed = _aware(revision['observed_at'])
    _require(original['race_id'] == final['race_id'] == original_meta['race_id'] == revision['race_id']
             and original['day_jst'] == cutoff.astimezone(JST).date().isoformat() == store.day
             and final['schema'] == 'RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1'
             and final['status'] == 'FINAL_NORMAL' and final['refund_status'] == 'NONE'
             and cutoff == _aware(original_meta['cutoff_at']) == _aware(original['baseline']['published_cutoff_at'])
             and cutoff < updated <= observed <= sealed <= as_of
             and _aware(original_meta['observed_at']) <= sealed
             and SHA.fullmatch(final['source_sha256']))
    field = _identities(original['snapshot']['riders'], 'athlete_id')
    _require(field == _identities(final['starters'], 'registration_id')
             == _identities(final['finishes'], 'registration_id'))

    finishes = {}
    places = Counter()
    for row in final['finishes']:
        place, status = row['place'], row['status']
        _require((status in NUMERIC and type(place) is int and 1 <= place <= len(field))
                 or (status in NON_NUMERIC and place is None))
        finishes[row['car']] = (row['registration_id'], status, place)
        if place is not None:
            places[place] += 1

    # Full-field competition ranking leaves a gap exactly where riders tie.
    next_place = 1
    for place, count in sorted(places.items()):
        _require(place == next_place)
        next_place += count
    return finishes, updated, observed, final['source_sha256']


def _latest_finishes(store, original_meta, revisions, owner_private_pem, as_of):
    previous = None
    previous_sealed = None
    seen = {}
    for revision in revisions:
        digest = revision['evidence_sha256']
        if digest in seen:
            _require(seen[digest] == revision)
            continue
        sealed = _aware(revision['observed_at'])
        _require(sealed <= as_of and (previous_sealed is None or previous_sealed < sealed))
        current = _verified_finishes(store, original_meta, revision, owner_private_pem, as_of)
        if previous is not None:
            finishes, updated, observed, source_sha = current
            prior_finishes, prior_updated, prior_observed, prior_sha = previous
            _require(updated >= prior_updated and observed >= prior_observed)
            if finishes != prior_finishes:
                _require(updated > prior_updated and source_sha != prior_sha)
        seen[digest] = revision
        previous = current
        previous_sealed = sealed
    return previous[0]


def project_rider_day(store, owner_private_pem, *, now):
    """Verify every archived result chain or hold the day without a partial aggregate."""
    return _project_rider_day(store, owner_private_pem, now=now)[0]


def project_rider_day_with_conditions(store, owner_private_pem, *, now, race_conditions,
                                      conditions_sha256):
    """Reuse the very same exact replay for the ordinary and conditioned count projections."""
    return _project_rider_day(store, owner_private_pem, now=now, race_conditions=race_conditions,
                              conditions_sha256=conditions_sha256)


def _project_rider_day(store, owner_private_pem, *, now, race_conditions=None, conditions_sha256=None):
    try:
        index = _checked_index(store)
        as_of = _aware(now)
        _require(store.day <= as_of.astimezone(JST).date().isoformat())
        counts, observations = {}, []
        for race_id, revisions in index['results'].items():
            finishes = _latest_finishes(store, index['originals'][race_id], revisions, owner_private_pem, as_of)
            context = (race_conditions or {}).get(race_id, {})
            for registration, _, place in finishes.values():
                if place is not None:
                    counts.setdefault(registration, [0] * 9)[place - 1] += 1
                    if race_conditions is not None:
                        observations.append((registration, context.get('meeting_grade'),
                                             context.get('round_stage'), place))
        races = len(index['results'])
        ordinary = dict(schema=SCHEMA, day=store.day, source_sha256=_signature(index),
                        archive_races=races, verified_races=races,
                        riders=[dict(registration=registration, finish_counts=counts[registration])
                                for registration in sorted(counts)])
        if race_conditions is None:
            return ordinary, None
        from . import keirin_dossier_conditions as conditions

        signature = conditioned_signature(store.day, ordinary['source_sha256'], conditions_sha256)
        return ordinary, conditions.result_slice(store.day, signature, observations)
    except (ValueError, KeyError, TypeError, OSError, OverflowError):
        raise ValueError(HOLD) from None
