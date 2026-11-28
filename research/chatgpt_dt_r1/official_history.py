"""Private prior-day DT-R1 inputs from a caller's pinned official SP archive."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import re

from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai.keirin_nationwide_cipher_history import GitCipherArchiveError
from race_ai.keirin_official_rider_history import NUMERIC, NON_NUMERIC, _identities

from . import official_inputs
from .admission import _lines, _riders, _source_proof
from .data import input_digest
from .policy import check_race_day, checked_sha, clock, digest


POLICY = 'DT_R1_OFFICIAL_PRIOR_7_JST_DAYS_V1'
LOOKBACK_DAYS = 7


class _HistoryHold(ValueError):
    pass


def _need(ok):
    if not ok:
        raise _HistoryHold('DT_R1_OFFICIAL_HISTORY_UNVERIFIED')


def _project(store, meta, revision, private_pem):
    original, replay, _ = records._replay_saved_result(store, meta, revision, private_pem,
                                                       strict_archive_reads=True)
    final = replay['official_result']
    snapshot = original['snapshot']
    rid = original['race_id']
    cutoff = clock(final['official_cutoff_at'])
    updated, observed, sealed = (clock(t) for t in
                               (final['source_updated_at'], final['observed_at'], revision['observed_at']))
    _need(rid == final['race_id'] == meta['race_id'] == revision['race_id'] and
          original['day_jst'] == store.day and
          final['schema'] == 'RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1' and
          final['status'] == 'FINAL_NORMAL' and final['refund_status'] == 'NONE' and
          cutoff == clock(snapshot['published_cutoff_at']) == clock(original['baseline']['published_cutoff_at']) and
          cutoff < updated <= observed <= sealed and clock(meta['observed_at']) <= sealed)
    check_race_day(store.day, final['official_cutoff_at'])
    final_sha = checked_sha(final['source_sha256'])
    proof = _source_proof(dict(original, origin_receipts=replay['origin_receipts']), meta, snapshot, rid, store.day)
    field = _identities(snapshot['riders'], 'athlete_id')
    _need(field == _identities(final['starters'], 'registration_id') ==
          _identities(final['finishes'], 'registration_id'))
    finishes = []
    for result in sorted(final['finishes'], key=lambda item: item['car']):
        place, status = result['place'], result['status']
        _need((status in NUMERIC and type(place) is int and 1 <= place <= len(field)) or
              (status in NON_NUMERIC and place is None))
        finishes.append(dict(car=result['car'], rank=place, status=status,
            incident=status != 'FINISHED', cancelled=False, absence=False,
            half_lap_seconds=None, final_lap_seconds=None, sb_mark=None))
    places = Counter(r['rank'] for r in finishes if r['rank'] is not None)
    next_place = 1
    for place, count in sorted(places.items()):
        _need(place == next_place)
        next_place += count
    starter = dict(race_id=rid, source_at=snapshot['cutoff_source']['captured_at'],
                   riders=[dict(number=car, registration=registration) for car, registration in field.items()])
    riders = _riders(snapshot, starter, rid)
    race_class = 'L1' if snapshot.get('competition') == 'GIRLS' else 'UNKNOWN'
    row = dict(race_id=rid, day=store.day, venue_code=rid[8:10], race_class=race_class,
        field_size=len(riders), field_supported=True, riders=riders, cohort='prospective',
        identity_scope=official_inputs.IDENTITY_NAMESPACE,
        cutoff_at=snapshot['published_cutoff_at'], available_at=snapshot['as_of'],
        source_available_at=snapshot['as_of'], source_available_at_verified=True,
        source_verified_at=proof['latest_server_evidence_at'], source_attestation_sha256=proof['evidence_sha256'],
        source_admission_status='ADMITTED', pre_cutoff_authenticated=True,
        source_original_evidence_sha256=meta['evidence_sha256'],
        result_admission_status='ADMITTED', official_result_authenticated=True,
        result_source_observed_at=final['observed_at'], result_at=revision['observed_at'],
        result_source_sha256=final_sha, result_revision_evidence_sha256=revision['evidence_sha256'],
        result_rows=finishes)
    row.update(_lines(snapshot, list(field), race_class))
    row['input_sha256'] = input_digest(row)
    return row, updated, observed


class OfficialHistory:
    """Select only replayed results in the exact archive already read for this job."""

    def __init__(self, store, private_pem):
        _need(isinstance(store.head, str) and re.fullmatch('[0-9a-f]{40}', store.head) is not None)
        self._repo, self._head, self._day = store.repo, store.head, date.fromisoformat(store.day)
        self._private_pem = private_pem
        self._days = {}
        self._verified = {}
        self._prefetch_attempted = False

    def _store(self, day):
        if day not in self._days:
            selected = records.RecordStore(self._repo, day, index_commit=self._head)
            _need(selected.head == self._head and selected.day == day)
            self._days[day] = selected
        return self._days[day]

    def _latest(self, store, original, versions, at):
        # A future correction is invisible at this clock, even if the pinned
        # commit contains it. Invalid eligible revisions hold the entire race.
        previous_clock, previous = None, None
        for revision in versions:
            sealed = clock(revision['observed_at'])
            if sealed > at:
                continue
            _need(previous_clock is None or previous_clock < sealed)
            previous_clock = sealed
            key = (store.day, original['evidence_sha256'], revision['evidence_sha256'])
            if key not in self._verified:
                try:
                    self._verified[key] = _project(store, original, revision, self._private_pem)
                except GitCipherArchiveError:
                    # A failed archive read must not produce a smaller forecast history.
                    raise
                except (ValueError, KeyError, TypeError, OverflowError):
                    self._verified[key] = None
            _need(self._verified[key] is not None)
            row, updated, observed = self._verified[key]
            _need(clock(row['result_at']) == sealed and clock(row['source_verified_at']) <= at)
            if previous is not None:
                prior, prior_updated, prior_observed = previous
                _need(prior_updated <= updated and prior_observed <= observed)
                if prior['result_rows'] != row['result_rows']:
                    _need(prior_updated < updated and prior['result_source_sha256'] != row['result_source_sha256'])
            previous = row, updated, observed
        return previous[0] if previous is not None else None

    def _prefetch(self, stores, at):
        self._prefetch_attempted = True
        paths, folders = set(), []
        for store in stores:
            folder = f'{records.ROOT}/{store.day}'
            folders.extend((folder, f'{archive.ROOT}/{store.day}'))
            for rid, versions in store.index['results'].items():
                available = [revision for revision in versions if clock(revision['observed_at']) <= at]
                if not available:
                    continue
                paths.update(archive._refs(rid))
                paths.update(archive._form_refs(rid))
                original = store.index['originals'][rid]
                paths.update(f"{folder}/{meta['evidence_sha256']}.sealed.json"
                             for meta in (original, *available))
        try:
            archive.prefetch_pinned_blobs(self._repo, self._head, paths, folders)
        except GitCipherArchiveError:
            # Warming the cache cannot change which authenticated records are required.
            # Verification below still fails closed on actual read errors.
            pass

    def arguments(self, payload, original, prediction_at):
        """Return kwargs for official_inputs.prepare scoped to this exact target."""
        target = official_inputs.verification_payload(
            payload, original, prediction_at=prediction_at)['normalized_input']
        _need(target['day'] == self._day.isoformat())
        at = clock(prediction_at)
        identities = {r['official_registration_id'] for r in target['riders']}
        history = []
        stores = [self._store((self._day - timedelta(days=days)).isoformat())
                  for days in range(LOOKBACK_DAYS, 0, -1)]
        if not self._prefetch_attempted:
            self._prefetch(stores, at)
        for store in stores:
            for rid, versions in sorted(store.index['results'].items()):
                try:
                    row = self._latest(store, store.index['originals'][rid], versions, at)
                except _HistoryHold:
                    continue
                if row and any(r['official_registration_id'] in identities for r in row['riders']):
                    history.append(row)
        expected = digest(dict(schema=official_inputs.HISTORY_SCHEMA, prediction_at=prediction_at,
            target_race_id=target['race_id'], target_input_sha256=target['input_sha256'],
            identity_namespace=official_inputs.IDENTITY_NAMESPACE, history_records=history))
        receipt = digest(dict(policy=POLICY, archive_commit=self._head, payload_sha256=expected))

        def verify(packet):
            _need(digest(packet) == expected)
            return dict(verified=True, independent=True, verifier='official-archive-replay',
                        payload_sha256=expected, receipt_sha256=receipt)

        return dict(history_records=deepcopy(history), history_verifier=verify)
