"""Private numerical finish histories from a pinned day of encrypted official SP results."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import cached_property
import re

from race_ai import keirin_official_nationwide_records as records
from race_ai.keirin_official_form_history import JST, _aware

NUMERIC = {'FINISHED', 'FALL_FINISHED'}
NON_NUMERIC = {'FALL_DNF', 'DISQUALIFIED', 'OTHER_DNF'}
SHA = re.compile('[0-9a-f]{64}')


def _require(condition):
    if not condition:
        raise ValueError('OFFICIAL_RIDER_HISTORY_INPUT_INVALID')


def _identities(rows, key):
    identities = {}
    for row in rows:
        car, registration = row['car'], row[key]
        _require(type(car) is int and 1 <= car <= 9 and car not in identities)
        _require(isinstance(registration, str) and re.fullmatch('[0-9]{6}', registration)
                 and registration != '000000')
        identities[car] = registration
    _require(5 <= len(identities) <= 9 and len(set(identities.values())) == len(identities))
    return identities


def _eligible_revisions(versions, as_of):
    eligible = []
    seen = {}
    last_time = None
    for meta in versions:
        timestamp = _aware(meta['observed_at'])
        if timestamp > as_of:
            continue
        digest = meta['evidence_sha256']
        if digest in seen:
            _require(seen[digest] == meta)
            continue
        seen[digest] = meta
        # The archive appends revisions. Conflicting clocks cannot order two versions.
        _require(last_time is None or timestamp > last_time)
        last_time = timestamp
        eligible.append(meta)
    return eligible


def _verified_finishes(store, original_meta, revision, private_pem):
    original, replay, _ = records._replay_saved_result(store, original_meta, revision, private_pem)
    final = replay['official_result']
    race_id = original_meta['race_id']
    _require(original['race_id'] == final['race_id'] == revision['race_id'] == race_id and
             original['day_jst'] == store.day and final['schema'] == 'RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1'
             and final['status'] == 'FINAL_NORMAL' and final['refund_status'] == 'NONE')
    cutoff, updated, observed = (_aware(final[key]) for key in
                                ('official_cutoff_at', 'source_updated_at', 'observed_at'))
    _require(cutoff.astimezone(JST).date().isoformat() == store.day and
             cutoff == _aware(original_meta['cutoff_at']) == _aware(original['baseline']['published_cutoff_at']) and
             cutoff < updated <= observed <= _aware(revision['observed_at']))
    _require(_aware(original_meta['observed_at']) <= _aware(revision['observed_at']))
    _require(SHA.fullmatch(final['source_sha256']))
    field = _identities(original['snapshot']['riders'], 'athlete_id')
    _require(field == _identities(final['starters'], 'registration_id')
             == _identities(final['finishes'], 'registration_id'))
    finishes = []
    for row in sorted(final['finishes'], key=lambda r: r['car']):
        place, status = row['place'], row['status']
        _require((status in NUMERIC and type(place) is int and 1 <= place <= len(field)) or
                 (status in NON_NUMERIC and place is None))
        finishes.append({key:row[key] for key in ('car', 'registration_id', 'status', 'place')})
    # The payout parser checks ranks through the podium. Histories use every rank.
    places = Counter(row['place'] for row in finishes if row['place'] is not None)
    next_place = 1
    for place, count in sorted(places.items()):
        _require(place == next_place)
        next_place += count
    return finishes, dict(evidence_sha256=revision['evidence_sha256'], cipher_sha256=revision['cipher_sha256'],
                          sealed_at=revision['observed_at'], cutoff_at=cutoff.isoformat(),
                          source_sha256=final['source_sha256'],
                          source_updated_at=updated.isoformat(), source_observed_at=observed.isoformat())


def _latest(store, original_meta, versions, as_of, private_pem):
    chain = []
    finishes = None
    previous_updated = previous_observed = None
    for meta in _eligible_revisions(versions, as_of):
        current, proof = _verified_finishes(store, original_meta, meta, private_pem)
        updated, observed = _aware(proof['source_updated_at']), _aware(proof['source_observed_at'])
        if chain:
            _require(updated >= previous_updated and observed >= previous_observed)
            if current != finishes:
                _require(updated > previous_updated and proof['source_sha256'] != chain[-1]['source_sha256'])
        chain.append(proof)
        finishes = current
        previous_updated, previous_observed = updated, observed
    if not chain:
        return None
    return dict(finishes=finishes, revisions=chain,
                original_evidence_sha256=original_meta['evidence_sha256'])


@dataclass(repr=False)
class OfficialFinishHistory:
    """Only the receipt is public. The private rows retain exceptional finishes."""
    receipt: dict
    private_races: dict = field(repr=False)
    _numeric_starts: tuple = field(repr=False)
    _target: str = field(repr=False)

    @cached_property
    def _book(self):
        # An aggregate-only protected readback needs neither model code nor NumPy.
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        return HistoryBook(Ride(rid, registration, place, expected=None, role=None, grade=None)
                           for rid, registration, place in self._numeric_starts)

    def finish_history(self, registration):
        return self._book.finish_history(registration, race_id=self._target)


def project_day(store, owner_private_pem, *, target_race_id, target_cutoff_at, knowledge_as_of,
                clock=lambda: datetime.now(timezone.utc)):
    """Replay a source day's latest eligible finish revision for a later target.

    The pinned archive can be replayed after the target to study a prior knowledge
    boundary. Neither producer clocks nor a later readback witness historical availability.
    No private row is included in the public receipt.
    """
    _require(isinstance(target_race_id, str) and re.fullmatch(r'20\d{10}', target_race_id)
             and target_race_id[8:10] != '00' and 1 <= int(target_race_id[-2:]) <= 12)
    target_day = date.fromisoformat(target_race_id[:8])
    target_cutoff = _aware(target_cutoff_at)
    _require(target_day == target_cutoff.astimezone(JST).date())
    view = _project(store, owner_private_pem, target_race_id, target_day, knowledge_as_of, target_cutoff, clock)
    view.receipt['replayed_before_target_cutoff'] = _aware(view.receipt['replayed_at']) < target_cutoff
    return view


def project_day_for_dossier(store, owner_private_pem, *, target_day, knowledge_as_of,
                            clock=lambda: datetime.now(timezone.utc)):
    """Build a dated, descriptive dossier. No actual target race or deadline is supplied."""
    _require(isinstance(target_day, str))
    day = date.fromisoformat(target_day)
    _require(day.isoformat() == target_day)
    # HistoryBook needs a race ID to select the date. The 0101 suffix is only a date selector.
    selector = day.strftime('%Y%m%d') + '0101'
    next_midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=JST)
    view = _project(store, owner_private_pem, selector, day, knowledge_as_of, next_midnight, clock)
    view.receipt['target_scope'] = 'DAY_LEVEL_DOSSIER_NO_FORECAST_DEADLINE'
    return view


def _project(store, owner_private_pem, target_race_id, target_day, knowledge_as_of, knowledge_before, clock):
    _require(isinstance(store.index_commit, str) and re.fullmatch('[0-9a-f]{40}', store.index_commit)
             and store.index_commit == store.head)
    index = records.checked_index(store.index, store.day)
    _require(date.fromisoformat(store.day) < target_day)
    as_of = _aware(knowledge_as_of)
    started = _aware(clock())
    _require(as_of < knowledge_before and as_of <= started)
    private_races = {}
    held = pending = 0
    rides = []
    for rid, original_meta in index['originals'].items():
        if _aware(original_meta['observed_at']) > as_of:
            continue
        try:
            current = _latest(store, original_meta, index['results'].get(rid, ()), as_of, owner_private_pem)
        except (ValueError, TypeError, KeyError, OSError):
            held += 1
            continue
        if current is None:
            pending += 1
            continue
        private_races[rid] = current
        for row in current['finishes']:
            if row['place'] is not None:
                rides.append((rid, row['registration_id'], row['place']))
    ends = [race['finishes'] for race in private_races.values()]
    tied_races = sum(any(count > 1 for count in Counter(row['place'] for row in finish
                         if row['place'] is not None).values()) for finish in ends)
    completed = _aware(clock())
    _require(started <= completed)
    receipt = dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_REPLAY_V1', source_day=store.day,
                   target_day=target_day.isoformat(), index_commit=store.index_commit,
                   knowledge_as_of=as_of.isoformat(), replayed_at=completed.isoformat(),
                   originals_by_as_of=len(private_races) + held + pending, admitted_races=len(private_races),
                   held_races=held, no_result_by_as_of=pending, tied_races=tied_races,
                   numeric_finishes=len(rides), non_numeric_finishes=sum(map(len, ends)) - len(rides),
                   verified_revisions=sum(len(race['revisions']) for race in private_races.values()),
                   historical_as_of_authenticated=False,
                   forecast_original_authenticated=False, predictive_model_changed=False, accuracy_improvement_proven=False)
    return OfficialFinishHistory(receipt, private_races, tuple(rides), target_race_id)
