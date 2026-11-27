"""Offline bridge from the existing official admission authority to DT-R1.

Usage (trusted owner process, never values taken from a request manifest)::

    # Existing archive objects and GitHubEvidenceClient responses are already
    # acquired by the approved workflow. This module fetches nothing.
    facade = PinnedOfficialArchive(repo=repo, owner_private_pem=existing_key,
        index_commit=archive_commit, origin_client=existing_evidence_client)
    adapter = OfficialAdmissionAdapter(facade)
    day = adapter.load_day('2030-01-15', include_results=False)
    # Pass day['records'], adapter.source_verifier and adapter.result_verifier
    # to the participant runtime. Forecast readback remains a separate gate.

The production facade calls ``load_admitted_day`` with the pinned archive
commit and an offline copy of the existing client's response cache. It invokes
``replay_saved_result`` for labels. Existing RSA-owner pin, exact source bytes,
archive lineage, and independent GitHub producer/readback checks remain intact.
GIT_NO_LAZY_FETCH=1 is required so absent partial-clone objects cannot fetch.
No key/environment-secret discovery, key creation, network transport, archive
mutation, rival forecast projection, or new admission authority is added here.

``facade`` is trusted executable integration code, not a source document. Its
load_day(day) returns {archive_commit, admission, index}; admission is the
existing load_admitted_day result with include_starters=True. replay_result
returns {archive_commit, original_meta, result_meta, revision, updates,
source_sha256, source_observed_at, result_roster}, after existing saved-result
replay. result_roster is read from the reparsed official final's complete
starters, never inferred from its winning triple. Fake
facades are only suitable for explicitly synthetic tests. Checking a receipt's
digest alone does not authenticate it: every callback re-invokes the facade.

All registered races survive. Missing originals, unknown cutoffs and rejected
proofs produce HOLD rows. An athlete_id is *not* treated as an official rider
registration without the existing card-reparsed starter projection. Missing
age, gear, top-two/top-three rates and full finishes stay unknown. Girls' listed
singletons are never declared cooperating lines. No result enters input_sha256.
An existing original-linked final may settle a participant's still-incomplete
calendar entry: input_roster_unknown and optional result_roster remain separate
result metadata. A null result roster/field size stays null; no pre-race ledger
binding is repaired by observing a finish. Without an admitted archived original
this facade still returns HOLD rather than inventing a new result authority.

Optional history/venue/timing support uses the exact runtime snapshots and
numeric feature reconstruction. Nonempty support requires an injected trusted
``support_verifier(snapshot)`` that invokes the existing independent authority.
It must return verified=True, independent=True, verifier, receipt_sha256,
payload_sha256=digest(snapshot), and nonempty source_receipt_sha256s. A boolean,
caller-supplied self-hash, or unverified sidecar is not an admission path. This
module does not implement a substitute support authority. All support must be
available by context_as_of; forecast seal/readback and future validation remain
separate. Historical replay is not evidence of prospective accuracy.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import math
import os
import re

from .data import input_digest
from .policy import check_race_day, checked_day, clock, digest


SCHEMA = 'CHAT_DT_R1_EXISTING_OFFICIAL_ADMISSION_V1'
_SHA = re.compile(r'[0-9a-f]{64}')
_COMMIT = re.compile(r'[0-9a-f]{40}')
_RACE = re.compile(r'20[0-9]{10}')
_REGISTRATION = re.compile(r'[0-9]{6}')
_FEATURE_BINDING = frozenset((
    'feature_model_id', 'feature_input_sha256', 'feature_schema_sha256',
    'history_snapshot_sha256', 'dataset_snapshot_sha256', 'context_snapshot_sha256',
    'context_as_of', 'context_evidence', 'history_evidence_sha256',
))


class AdmissionError(ValueError):
    """Fixed codes only; no private documents, identifiers or secrets in errors."""


def _need(ok, code):
    if not ok:
        raise AdmissionError('OFFICIAL_ADMISSION_' + code)


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, 'SHA256_REQUIRED')
    return value


def _commit(value):
    _need(type(value) is str and _COMMIT.fullmatch(value) is not None, 'PINNED_ARCHIVE_COMMIT_REQUIRED')
    return value


def _day(value):
    try:
        checked_day(value)
    except (ValueError, TypeError):
        raise AdmissionError('OFFICIAL_ADMISSION_DAY_INVALID') from None
    return value


def _when(value):
    try:
        return clock(value)
    except (ValueError, TypeError):
        raise AdmissionError('OFFICIAL_ADMISSION_AWARE_CLOCK_REQUIRED') from None


def _race(value, day):
    _need(type(value) is str and _RACE.fullmatch(value) is not None and
          value.startswith(day.replace('-', '')) and 1 <= int(value[-2:]) <= 12,
          'RACE_DAY_BINDING')
    return value


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, 'tolist'):
        return _json_value(value.tolist())
    return value


def _number(value, low, high, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) if low <= value <= high and (not positive or value > 0) else None


def _meta(row, kind, race_id=None):
    _need(isinstance(row, dict) and row.get('kind') == kind, 'ARCHIVE_RECEIPT_REQUIRED')
    for key in ('evidence_sha256', 'cipher_sha256'):
        _sha(row.get(key))
    _when(row.get('observed_at'))
    _commit(row.get('producer_commit'))
    _need(type(row.get('producer_run_id')) is str and re.fullmatch('[1-9][0-9]{0,17}', row['producer_run_id']),
          'ARCHIVED_PRODUCER_REQUIRED')
    if race_id is not None:
        _need(row.get('race_id') == race_id, 'ARCHIVE_RACE_BINDING')
    if kind == 'original':
        _sha(row.get('baseline_cipher_sha256'))
        _when(row.get('cutoff_at'))
    return deepcopy(row)


def _offline_required():
    _need(os.environ.get('GIT_NO_LAZY_FETCH') == '1', 'OFFLINE_GIT_GUARD_REQUIRED')


def _cache_miss(*args, **kwargs):
    raise AdmissionError('OFFICIAL_ADMISSION_EXISTING_EVIDENCE_CACHE_MISS')


class PinnedOfficialArchive:
    """Read-only production facade; callers inject existing key and client.

    Missing cached responses/objects fail closed. Caller-owned credentials and
    the live client's transport are not copied. The ordinary existing loader
    still checks the configured owner key and approved archive remote/context.
    No key is inspected or loaded until that existing loader is invoked.
    """
    def __init__(self, *, repo, owner_private_pem, index_commit, origin_client):
        from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
        _offline_required()
        _need(isinstance(origin_client, GitHubEvidenceClient), 'EXISTING_EVIDENCE_CLIENT_REQUIRED')
        _need(type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 32_768,
              'INJECTED_OWNER_KEY_REQUIRED')
        self.repo = repo
        self._owner_private_pem = owner_private_pem
        self.index_commit = _commit(index_commit)
        self.origin_client = GitHubEvidenceClient(token='', open_request=_cache_miss)
        self.origin_client._cache = deepcopy(origin_client._cache)

    def _store(self, day):
        from race_ai import keirin_official_nationwide_records as existing
        _offline_required()
        return existing.RecordStore(self.repo, _day(day), index_commit=self.index_commit)

    def load_day(self, day):
        from race_ai import keirin_official_nationwide_records as existing
        _offline_required()
        admitted = existing.load_admitted_day(self.repo, self._owner_private_pem, _day(day),
            origin_client=self.origin_client, index_commit=self.index_commit, include_starters=True)
        store = self._store(day)
        _need(store.head == self.index_commit, 'ARCHIVE_PIN_CHANGED')
        return dict(archive_commit=self.index_commit, admission=admitted, index=deepcopy(store.index))

    def replay_result(self, day, race_id, *, revision=None):
        from race_ai import keirin_official_nationwide_records as existing
        store = self._store(day)
        _race(race_id, day)
        original = store.index['originals'].get(race_id)
        versions = store.index['results'].get(race_id, [])
        _need(original is not None and versions, 'SAVED_RESULT_UNAVAILABLE')
        revision = len(versions) if revision is None else revision
        _need(type(revision) is int and 1 <= revision <= len(versions), 'RESULT_REVISION_UNAVAILABLE')
        result = versions[revision - 1]
        updates = existing.replay_saved_result(store, original, result, self._owner_private_pem)
        # These fields are read only after replay has matched the entire saved
        # scored object against reparsed source bytes. Rival arms are discarded.
        saved = store.read(result, self._owner_private_pem)
        official = saved['scored']['official_result']
        starters = official.get('starters')
        _need(isinstance(starters, list) and 3 <= len(starters) <= 9 and
              all(isinstance(r, dict) and type(r.get('car')) is int and 1 <= r['car'] <= 9
                  for r in starters), 'REPLAYED_FINAL_ROSTER_REQUIRED')
        result_roster = [r['car'] for r in starters]
        _need(len(set(result_roster)) == len(result_roster), 'REPLAYED_FINAL_ROSTER_DUPLICATE')
        return dict(archive_commit=self.index_commit, original_meta=deepcopy(original),
                    result_meta=deepcopy(result), revision=revision, updates=updates,
                    source_sha256=official['source_sha256'], source_observed_at=official['observed_at'],
                    result_roster=sorted(result_roster))


def _checked_bundle(bundle, day):
    _need(isinstance(bundle, dict), 'EXISTING_ADMISSION_REQUIRED')
    archive_commit = _commit(bundle.get('archive_commit'))
    loaded, index = bundle.get('admission'), bundle.get('index')
    _need(isinstance(loaded, dict) and loaded.get('day_jst') == day and isinstance(index, dict),
          'DAY_ADMISSION_BINDING')
    registry = loaded.get('registry')
    _need(isinstance(registry, dict) and registry.get('event_day') == day, 'DAY_REGISTRY_UNAVAILABLE')
    ids = registry.get('registered_race_ids')
    _need(isinstance(ids, list) and len(ids) <= 600 and len(ids) == len(set(ids)), 'REGISTRY_IDENTITIES')
    for rid in ids:
        _race(rid, day)
    registry_meta = _meta(index.get('registry'), 'registry')
    _sha(registry.get('calendar_source_sha256'))
    rows = loaded.get('records')
    _need(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), 'ADMITTED_ROWS_REQUIRED')
    admitted = {r.get('race_id'): r for r in rows}
    _need(len(admitted) == len(rows) and set(admitted) <= set(ids), 'ADMITTED_REGISTRY_IDENTITIES')
    states = loaded.get('states')
    _need(isinstance(states, list) and len(states) == len(ids) and
          all(isinstance(s, dict) for s in states) and {s.get('race_id') for s in states} == set(ids),
          'ALL_REGISTRY_STATES_REQUIRED')
    originals = index.get('originals')
    _need(isinstance(originals, dict) and set(originals) <= set(ids), 'ORIGINAL_REGISTRY_IDENTITIES')
    return archive_commit, loaded, registry, registry_meta, admitted, originals


def _source_proof(original, meta, snapshot, rid, day):
    _need(original.get('race_id') == snapshot.get('race_id') == rid and original.get('day_jst') == day,
          'SNAPSHOT_IDENTITY')
    cutoff = snapshot.get('published_cutoff_at')
    try:
        check_race_day(day, cutoff)
    except (ValueError, TypeError):
        raise AdmissionError('OFFICIAL_ADMISSION_CUTOFF_DAY_BINDING') from None
    _need(_when(meta['cutoff_at']) == _when(cutoff), 'CUTOFF_RECEIPT_BINDING')
    _need(original.get('baseline_cipher_sha256') == meta['baseline_cipher_sha256'] and
          original.get('producer_run_id') == meta['producer_run_id'] and
          original.get('producer_commit') == meta['producer_commit'], 'ORIGINAL_ARCHIVE_BINDING')
    origins = original.get('origin_receipts')
    proof = origins.get('baseline_origin') if isinstance(origins, dict) else None
    _need(isinstance(proof, dict) and proof.get('schema') == 'RACE_AI_KEIRIN_GITHUB_SERVER_ORIGIN_EVIDENCE_V1' and
          proof.get('state') == 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED', 'INDEPENDENT_ORIGIN_REQUIRED')
    _need(proof.get('evidence_sha256') == digest({k: v for k, v in proof.items() if k != 'evidence_sha256'}),
          'ORIGIN_RECEIPT_CHANGED')
    _need(proof.get('race_id') == rid and proof.get('cipher_sha256') == meta['baseline_cipher_sha256'] and
          _when(proof.get('official_cutoff_at')) == _when(cutoff) and
          str(proof.get('producer_run_id')) == meta['producer_run_id'] and
          proof.get('producer_commit') == meta['producer_commit'], 'ORIGIN_ARCHIVE_BINDING')
    _need(proof.get('producer_job_id') != proof.get('readback_job_id') and
          proof.get('producer_artifact_id') != proof.get('readback_artifact_id'), 'INDEPENDENT_READBACK_REQUIRED')
    for role in ('producer', 'readback'):
        _sha(proof.get(role + '_archive_sha256'))
        _commit(proof.get(role + '_commit'))
        for field in ('run_id', 'job_id', 'artifact_id'):
            _need(type(proof.get(role + '_' + field)) is int and proof[role + '_' + field] > 0,
                  'ORIGIN_SERVER_IDENTIFIERS')
    margin = proof.get('minimum_margin_seconds')
    verified_at = _when(proof.get('latest_server_evidence_at'))
    _need(type(margin) is int and margin >= 65 and (_when(cutoff) - verified_at).total_seconds() >= margin,
          'ORIGIN_PRE_CUTOFF_MARGIN')
    available = _when(snapshot.get('as_of'))
    _need(available <= verified_at < _when(cutoff), 'SOURCE_AVAILABILITY_AFTER_PROOF')
    pages = snapshot.get('source_pages')
    _need(isinstance(pages, list) and 0 < len(pages) <= 32 and all(isinstance(p, dict) for p in pages),
          'SOURCE_PAGES_REQUIRED')
    page_times = []
    for page in pages:
        _sha(page.get('bytes_sha256'))
        page_times.append(_when(page.get('captured_at')))
    _need(max(page_times) == available, 'SOURCE_AS_OF_MISMATCH')
    cut = snapshot.get('cutoff_source')
    _need(isinstance(cut, dict) and any(all(page.get(key) == cut.get(key) for key in
          ('url', 'bytes_sha256', 'captured_at')) for page in pages), 'CUTOFF_SOURCE_BINDING')
    _sha(cut.get('bytes_sha256'))
    return proof


def _riders(snapshot, starter_row, rid):
    raw = snapshot.get('riders')
    _need(isinstance(raw, list) and len(raw) <= 9 and all(isinstance(r, dict) for r in raw), 'SOURCE_ROSTER')
    cars = [r.get('car') for r in raw]
    _need(all(type(car) is int and 1 <= car <= 9 for car in cars) and len(cars) == len(set(cars)), 'SOURCE_CARS')
    registrations = {}
    if starter_row is not None:
        _need(starter_row.get('race_id') == rid, 'REGISTRATION_RACE_BINDING')
        projected = starter_row.get('riders')
        _need(isinstance(projected, list) and len(projected) == len(raw), 'REGISTRATION_ROSTER_BINDING')
        for rider in projected:
            registration, car = rider.get('registration'), rider.get('number')
            _need(type(car) is int and car in cars and car not in registrations and
                  type(registration) is str and _REGISTRATION.fullmatch(registration) and registration != '000000',
                  'REGISTRATION_SOURCE_BINDING')
            registrations[car] = registration
        _need(len(set(registrations.values())) == len(registrations) and
              all(registrations[r['car']] == r.get('athlete_id') for r in raw), 'REGISTRATION_SOURCE_BINDING')
        _need(_when(starter_row.get('source_at')) == _when(snapshot['cutoff_source']['captured_at']),
              'REGISTRATION_SOURCE_CLOCK')
    output = []
    styles = {'NIGE': 'NIGE', 'MAKURI': 'MAKURI', 'SASHI': 'SASHI', 'MARK': 'OI',
              'ALLROUND': 'RYO', 'UNKNOWN': 'UNKNOWN'}
    for raw_rider in sorted(raw, key=lambda r: r['car']):
        car = raw_rider['car']
        registration = registrations.get(car)
        key = digest({'namespace': 'KEIRIN_JP_OFFICIAL_REGISTRATION', 'registration': registration}) if registration else digest(
            {'namespace': 'OFFICIAL_SP_UNRESOLVED_RACE_CAR', 'race_id': rid, 'car': car})
        rider = dict(car=car, identity_key=key, official_registration_id=registration,
            identity_status='OFFICIAL_REGISTRATION_SOURCE_BOUND' if registration else 'UNRESOLVED_RACE_SCOPED',
            identity_usable=registration is not None, identity_collision=False,
            identity_collision_risk=registration is None, rider_class=None,
            competition_points=_number(raw_rider.get('competition_points'), 0, 150, positive=True),
            # Existing build_baseline_candidate explicitly computes this from
            # the bound official profile's win_rate_percent / 100.
            win_rate=_number(raw_rider.get('recent_form_score'), 0, 1),
            top2_rate=None, top3_rate=None, age=None, gear_ratio=None,
            style=styles.get(raw_rider.get('style'), 'UNKNOWN'),
            h_count=_number(raw_rider.get('h_count'), 0, 200), b_count=_number(raw_rider.get('b_count'), 0, 200),
            published_line_role=None)
        rider['missing_fields'] = [k for k in ('competition_points', 'win_rate', 'top2_rate', 'top3_rate',
                                              'age', 'gear_ratio') if rider[k] is None]
        output.append(rider)
    return output


def _lines(snapshot, cars, race_class):
    supplied = snapshot.get('line_groups')
    groups = deepcopy(supplied) if isinstance(supplied, list) else []
    well_formed = bool(groups) and all(isinstance(g, list) and g and all(type(c) is int and c in cars for c in g) for g in groups)
    flattened = [c for group in groups for c in group] if well_formed else []
    well_formed = well_formed and len(flattened) == len(set(flattened))
    valid = well_formed and set(flattened) == set(cars)
    contested = snapshot.get('line_status') == 'CONTESTED' or snapshot.get('lines_contested') is True
    applicable = race_class != 'L1'
    known = bool(valid and not contested and applicable)
    status = 'CONTESTED' if contested else 'KNOWN' if valid else 'MISSING' if not groups else 'PARTIAL_OR_INVALID'
    return dict(line_groups=groups if known else [], published_line_groups=groups if well_formed else [],
                lines_known=known, lines_applicable=applicable, line_status=status)


def _held_record(rid, day, state, archive_commit, registry_meta, list_row):
    cutoff = list_row.get('official_cutoff_at')
    if cutoff is not None:
        try:
            check_race_day(day, cutoff)
        except (ValueError, TypeError):
            cutoff = None
    row = dict(race_id=rid, day=day, venue_code=rid[8:10], race_class='UNKNOWN', race_type=None,
        meeting_grade=None, field_size=0, field_supported=False, riders=[],
        line_groups=[], published_line_groups=[], lines_known=False, lines_applicable=True, line_status='MISSING',
        cohort='prospective', cutoff_at=cutoff, published_cutoff_at=cutoff,
        source_sha256=None, source_sha256s=[], source_available_at=None, available_at=None,
        source_available_at_verified=False, source_verified_at=None, source_attestation_sha256=None,
        publication_time_authenticated=False,
        pre_cutoff_authenticated=False, official_result_authenticated=False,
        source_admission_status='HOLD', source_hold_reason='OFFICIAL_ADMISSION_ORIGINAL_NOT_ADMITTED',
        source_state=state, archive_commit=archive_commit,
        registry_evidence_sha256=registry_meta['evidence_sha256'],
        validation_scope='EXISTING_OFFICIAL_SOURCE_REPLAY_SHADOW_ONLY',
        finish=None, top3=None, result_rows=[], result_status='PENDING', result_at=None,
        result_admission_status='NOT_REQUESTED')
    row['input_sha256'] = input_digest(row)
    return row


class OfficialAdmissionAdapter:
    """Normalize only records returned by trusted existing admission code."""
    def __init__(self, facade, *, history_records=(), venue_store=None, timing_records=(),
                 context_as_of=None, support_verifier=None, allow_current_geometry_assumption=False):
        _need(callable(getattr(facade, 'load_day', None)) and callable(getattr(facade, 'replay_result', None)),
              'TRUSTED_ADMISSION_FACADE_REQUIRED')
        self.facade = facade
        self.history_records = deepcopy(list(history_records))
        self.venue_store = deepcopy(venue_store)
        self.timing_records = deepcopy(list(timing_records))
        self.context_as_of = context_as_of
        self.support_verifier = support_verifier
        self.allow_current_geometry_assumption = bool(allow_current_geometry_assumption)
        if context_as_of is not None:
            _when(context_as_of)

    def load_day(self, day, *, include_results=False):
        """Return all normalized records, a safe registry and aggregate coverage."""
        day = _day(day)
        try:
            bundle = self.facade.load_day(day)
            commit, loaded, registry, registry_meta, originals, metas = _checked_bundle(bundle, day)
        except AdmissionError:
            raise
        except Exception:
            raise AdmissionError('OFFICIAL_ADMISSION_EXISTING_DAY_REPLAY_FAILED') from None
        states = {r['race_id']: r.get('state', 'UNKNOWN') for r in loaded['states']}
        listed = {r['race_id']: r for r in registry.get('races', [])}
        starters = loaded.get('starter_rows', [])
        _need(isinstance(starters, list) and all(isinstance(r, dict) for r in starters), 'STARTER_PROJECTION_SHAPE')
        by_race = {r.get('race_id'): r for r in starters}
        _need(len(by_race) == len(starters) and set(by_race) <= set(originals), 'STARTER_PROJECTION_IDENTITIES')
        output = []
        for rid in sorted(registry['registered_race_ids']):
            row = _held_record(rid, day, states[rid], commit, registry_meta, listed.get(rid, {}))
            if rid in originals:
                try:
                    original = originals[rid]
                    meta = _meta(metas.get(rid), 'original', rid)
                    snapshot = original['snapshot']
                    proof = _source_proof(original, meta, snapshot, rid, day)
                    riders = _riders(snapshot, by_race.get(rid), rid)
                    race_class = {'A1_A2': 'A12', 'CHALLENGE': 'A3', 'S': 'S', 'GIRLS': 'L1'}.get(
                        snapshot.get('competition'), 'UNKNOWN')
                    row.update(race_class=race_class, race_type=snapshot.get('round_stage'),
                        riders=riders, field_size=len(riders), field_supported=3 <= len(riders) <= 9,
                        cutoff_at=snapshot['published_cutoff_at'], published_cutoff_at=snapshot['published_cutoff_at'],
                        source_sha256=snapshot['cutoff_source']['bytes_sha256'],
                        source_sha256s=sorted({page['bytes_sha256'] for page in snapshot['source_pages']}),
                        source_available_at=snapshot['as_of'], available_at=snapshot['as_of'],
                        source_available_at_verified=True, pre_cutoff_authenticated=True,
                        source_verified_at=proof['latest_server_evidence_at'],
                        source_attestation_sha256=proof['evidence_sha256'],
                        source_admission_status='ADMITTED', source_hold_reason=None,
                        source_proof=dict(archive_commit=commit, registry_evidence_sha256=registry_meta['evidence_sha256'],
                            original_evidence_sha256=meta['evidence_sha256'], original_cipher_sha256=meta['cipher_sha256'],
                            baseline_cipher_sha256=meta['baseline_cipher_sha256'],
                            origin_receipt_sha256=proof['evidence_sha256'], snapshot_sha256=digest(snapshot)))
                    row.update(_lines(snapshot, [r['car'] for r in riders], race_class))
                    row['input_sha256'] = input_digest(row)
                except Exception:
                    # Do not retain a partly projected row after any proof fails.
                    row = _held_record(rid, day, states[rid], commit, registry_meta, listed.get(rid, {}))
                    row['source_hold_reason'] = 'OFFICIAL_ADMISSION_SOURCE_BINDING_FAILED'
            if include_results:
                try:
                    row.update(self._result(row))
                except Exception:
                    row['result_admission_status'] = 'HOLD'
            output.append(row)
        safe_registry = dict(day=day, race_ids=sorted(registry['registered_race_ids']),
            archive_commit=commit, registry_evidence_sha256=registry_meta['evidence_sha256'],
            calendar_source_sha256=registry['calendar_source_sha256'],
            day_inventory_complete=registry.get('day_inventory_complete') is True,
            missing_venues=deepcopy(registry.get('missing_venues', [])),
            disappeared_race_ids=deepcopy(registry.get('disappeared_race_ids', [])))
        counts = Counter(row['source_admission_status'] for row in output)
        return dict(schema=SCHEMA, records=output, registry=safe_registry, audit=dict(
            registered_races=len(output), admitted_races=counts['ADMITTED'], held_races=counts['HOLD'],
            unknown_cutoff_races=sum(row['cutoff_at'] is None for row in output),
            result_admitted_races=sum(row['official_result_authenticated'] for row in output),
            result_hold_races=sum(row['result_admission_status'] == 'HOLD' for row in output)))

    def _row(self, day, race_id):
        _race(race_id, _day(day))
        found = next((r for r in self.load_day(day)['records'] if r['race_id'] == race_id), None)
        _need(found is not None and found['source_admission_status'] == 'ADMITTED', 'SOURCE_NOT_ADMITTED')
        return found

    def _feature_proof(self, binding, row):
        from .features import build_features, require_history_available
        from .context import augment_features
        _need(_FEATURE_BINDING <= set(binding), 'COMPLETE_FEATURE_BINDING_REQUIRED')
        _need(type(binding['feature_model_id']) is str and bool(binding['feature_model_id']), 'FEATURE_MODEL_REQUIRED')
        as_of = binding['context_as_of']
        at = _when(as_of)
        _need(max(_when(row['available_at']), _when(row['source_verified_at'])) <= at < _when(row['cutoff_at']),
              'CONTEXT_SOURCE_CLOCK')
        if self.context_as_of is not None:
            _need(_when(self.context_as_of) == at, 'CONFIGURED_CONTEXT_CLOCK_MISMATCH')
        history = deepcopy(self.history_records)
        _need(all(isinstance(r, dict) and r.get('day', '') <= row['day'] and r.get('race_id') != row['race_id']
                  for r in history), 'FUTURE_OR_TARGET_HISTORY')
        require_history_available(history, as_of)
        history_snapshot = digest(_json_value(sorted(history, key=lambda r: (r['day'], r['race_id']))))
        venue_snapshot = _json_value(list(self.venue_store.records)) if self.venue_store is not None else None
        timing_snapshot = _json_value(self.timing_records)
        support = dict(schema='CHAT_DT_R1_ADMITTED_SUPPORT_SNAPSHOT_V1', race_id=row['race_id'], day=row['day'],
            history_records=_json_value(history), venue_records=venue_snapshot, timing_records=timing_snapshot,
            weather_observation=None, as_of=as_of,
            allow_current_geometry_assumption=self.allow_current_geometry_assumption)
        receipt = None
        if history or self.venue_store is not None or self.timing_records or self.allow_current_geometry_assumption:
            _need(callable(self.support_verifier), 'INDEPENDENT_SUPPORT_VERIFIER_REQUIRED')
            receipt = self.support_verifier(deepcopy(support))
            _need(isinstance(receipt, dict) and receipt.get('verified') is True and receipt.get('independent') is True and
                  type(receipt.get('verifier')) is str and bool(receipt['verifier']) and
                  receipt.get('payload_sha256') == digest(support), 'INDEPENDENT_SUPPORT_RECEIPT_REQUIRED')
            _sha(receipt.get('receipt_sha256'))
            source_receipts = receipt.get('source_receipt_sha256s')
            _need(isinstance(source_receipts, list) and 0 < len(source_receipts) <= 100_000,
                  'SUPPORT_SOURCE_RECEIPTS_REQUIRED')
            for source in source_receipts:
                _sha(source)
        featured = next(r for r in build_features(history + [row]) if r['race_id'] == row['race_id'])
        if binding['feature_schema_sha256'] != digest(list(featured['feature_names'])):
            identities = {str(r['identity_key']) for r in row['riders'] if r['identity_usable'] is True}
            usable_timings = [r for r in self.timing_records if str(_json_value(r).get('rider_id',
                _json_value(r).get('identity_key', ''))) in identities]
            featured = augment_features([featured], venue_store=self.venue_store, timing_records=usable_timings,
                as_of=as_of, allow_current_geometry_assumption=self.allow_current_geometry_assumption)[0]
        expected = dict(feature_input_sha256=featured['feature_input_sha256'],
            feature_schema_sha256=digest(list(featured['feature_names'])),
            history_snapshot_sha256=history_snapshot,
            dataset_snapshot_sha256=digest(dict(target_input_sha256=row['input_sha256'],
                declared_dataset_sha256=row.get('dataset_sha256'), source_sha256=row.get('source_sha256'),
                history_snapshot_sha256=history_snapshot)),
            context_snapshot_sha256=digest(dict(venue_records=venue_snapshot, timing_records=timing_snapshot,
                weather_observation=None, as_of=as_of, allow_current_geometry_assumption=self.allow_current_geometry_assumption)),
            context_evidence=_json_value(featured.get('context_evidence')),
            history_evidence_sha256=digest(_json_value(featured['history_evidence'])))
        _need(all(binding[key] == value for key, value in expected.items()), 'FEATURE_OR_SUPPORT_BINDING_MISMATCH')
        return receipt

    def source_verifier(self, binding):
        """Runtime callback; re-admit source and recompute any full feature binding."""
        try:
            _need(isinstance(binding, dict), 'SOURCE_BINDING_REQUIRED')
            required = {'race_id', 'day', 'input_sha256', 'cohort', 'cutoff_at', 'starters'}
            allowed = required | {'field_size', 'class', 'venue'} | _FEATURE_BINDING
            _need(required <= set(binding) <= allowed, 'SOURCE_BINDING_FIELDS')
            row = self._row(binding['day'], binding['race_id'])
            expected = {key: row[key] for key in required - {'starters'}}
            expected['starters'] = [r['car'] for r in row['riders']]
            _need(digest({key: binding[key] for key in expected}) == digest(expected), 'SOURCE_BINDING_MISMATCH')
            extra = {'field_size': row['field_size'], 'class': row['race_class'], 'venue': row['venue_code']}
            _need(all(binding.get(k, v) == v for k, v in extra.items()), 'SOURCE_GROUP_BINDING_MISMATCH')
            support = self._feature_proof(binding, row) if _FEATURE_BINDING & set(binding) else None
            chain = dict(source=row['source_proof'], support_receipt_sha256=(support or {}).get('receipt_sha256'))
            return dict(verified=True, independent=True, verifier=SCHEMA + ':existing-source-replay',
                payload_sha256=digest(binding), receipt_sha256=digest(chain), evidence=chain,
                scope='EXISTING_SOURCE_ADMISSION_NOT_FORECAST_READBACK')
        except AdmissionError:
            raise
        except Exception:
            raise AdmissionError('OFFICIAL_ADMISSION_SOURCE_REPLAY_OR_SUPPORT_FAILED') from None

    def _result(self, row, *, revision=None):
        _need(row['source_admission_status'] == 'ADMITTED', 'RESULT_REQUIRES_ADMITTED_ORIGINAL')
        replay = self.facade.replay_result(row['day'], row['race_id'], revision=revision)
        _need(isinstance(replay, dict) and replay.get('archive_commit') == row['archive_commit'], 'RESULT_ARCHIVE_PIN')
        original = _meta(replay.get('original_meta'), 'original', row['race_id'])
        saved = _meta(replay.get('result_meta'), 'result', row['race_id'])
        _need(original['evidence_sha256'] == row['source_proof']['original_evidence_sha256'] and
              original['cipher_sha256'] == row['source_proof']['original_cipher_sha256'], 'RESULT_ORIGINAL_BINDING')
        number = replay.get('revision')
        _need(type(number) is int and 1 <= number <= 16 and (revision is None or number == revision), 'RESULT_REVISION_BINDING')
        updates = replay.get('updates')
        races = updates.get('races') if isinstance(updates, dict) else None
        _need(isinstance(races, list) and len(races) == 1 and isinstance(races[0], dict), 'RESULT_UPDATE_REQUIRED')
        result = races[0]
        _need(result.get('race_id') == row['race_id'] and result.get('authority') == 'official' and
              result.get('order_status') == 'confirmed', 'OFFICIAL_CONFIRMED_RESULT_REQUIRED')
        source_sha = _sha(replay.get('source_sha256'))
        observed = _when(replay.get('source_observed_at'))
        result_at = _when(result.get('observed_at'))
        _need(_when(row['cutoff_at']) < observed <= result_at and observed <= _when(saved['observed_at']),
              'RESULT_OBSERVATION_CLOCK')
        winners = result.get('winning_triples')
        _need(isinstance(winners, list) and 1 <= len(winners) <= 24, 'WINNING_ORDERS_REQUIRED')
        cars = {r['car'] for r in row['riders']}
        result_roster = replay.get('result_roster')
        if result_roster is not None:
            _need(isinstance(result_roster, list) and 3 <= len(result_roster) <= 9 and
                  all(type(car) is int and 1 <= car <= 9 for car in result_roster) and
                  len(set(result_roster)) == len(result_roster) and set(result_roster) == cars,
                  'REPLAYED_RESULT_ROSTER_BINDING')
            result_roster = sorted(result_roster)
        triples = []
        for text in winners:
            _need(type(text) is str and re.fullmatch('[1-9]-[1-9]-[1-9]', text), 'WINNING_ORDER_FORMAT')
            triple = tuple(map(int, text.split('-')))
            _need(len(set(triple)) == 3 and set(triple) <= cars and triple not in triples, 'WINNING_ORDER_ROSTER')
            triples.append(triple)
        top3 = list(triples[0]) if len(triples) == 1 else None
        # The update proves these top-three ranks, not every tail finish, lap
        # time or incident flag. Only the observed ranks may feed later history.
        result_rows = [dict(car=car, rank=rank, rank_raw=str(rank), absence=False,
            cancelled=False, incident=None, half_lap_seconds=None, final_lap_seconds=None,
            sb_mark=None, source_available_at=result['observed_at'])
            for rank, car in enumerate(top3 or [], 1)]
        return dict(top3=top3, top3_resolved=top3 is not None, finish=None, result_rows=result_rows,
            result_status='PARTIAL_VALID_TOP3' if top3 is not None else 'DEAD_HEAT',
            result_at=result['observed_at'], result_source_observed_at=replay['source_observed_at'],
            result_source_sha256=source_sha, result_revision=number,
            result_roster=result_roster, result_field_size=len(result_roster) if result_roster is not None else None,
            winning_triples=[list(t) for t in triples], official_result_authenticated=True,
            result_publication_time_authenticated=False, result_admission_status='ADMITTED',
            result_proof=dict(archive_commit=replay['archive_commit'],
                original_evidence_sha256=original['evidence_sha256'],
                result_evidence_sha256=saved['evidence_sha256'], result_cipher_sha256=saved['cipher_sha256'],
                result_source_sha256=source_sha, replay_update_sha256=digest(result),
                result_roster_sha256=digest(result_roster), revision=number))

    def result_verifier(self, outcome):
        """Replay final labels and optional final roster without changing inputs.

        input_roster_unknown describes the participant's calendar state, not an
        assertion that the archived final has no roster. Known final metadata
        must match replay; explicitly unknown metadata is never filled in here.
        """
        try:
            _need(isinstance(outcome, dict), 'RESULT_BINDING_REQUIRED')
            required = {'race_id', 'day', 'top3', 'status', 'result_at'}
            _need(required <= set(outcome) <= required | {'field_size', 'class', 'venue', 'revision',
                  'input_roster_unknown', 'result_roster'}, 'RESULT_BINDING_FIELDS')
            unknown_input = outcome.get('input_roster_unknown', False)
            _need(type(unknown_input) is bool, 'RESULT_INPUT_ROSTER_STATE')
            row = self._row(outcome['day'], outcome['race_id'])
            result = self._result(row, revision=outcome.get('revision'))
            expected = dict(top3=result['top3'], status='settled' if result['top3'] else 'dead_heat', result_at=result['result_at'])
            _need(digest({key: outcome[key] for key in expected}) == digest(expected), 'RESULT_BINDING_MISMATCH')
            supplied_roster = outcome.get('result_roster')
            if supplied_roster is not None:
                _need(isinstance(supplied_roster, list) and all(type(car) is int for car in supplied_roster) and
                      result['result_roster'] is not None and sorted(supplied_roster) == result['result_roster'],
                      'RESULT_FULL_ROSTER_BINDING_MISMATCH')
            if 'field_size' in outcome:
                size = outcome['field_size']
                if size is None:
                    _need(unknown_input, 'RESULT_FIELD_SIZE_UNKNOWN_FOR_ADMITTED_INPUT')
                else:
                    expected_size = result['result_field_size'] if unknown_input else row['field_size']
                    _need(type(size) is int and size == expected_size, 'RESULT_FIELD_SIZE_BINDING_MISMATCH')
            for key, value in {'class': row['race_class'], 'venue': row['venue_code']}.items():
                supplied = outcome.get(key, value)
                _need(supplied == value or (unknown_input and supplied in (None, 'UNKNOWN')),
                      'RESULT_GROUP_BINDING_MISMATCH')
            chain = dict(source=row['source_proof'], result=result['result_proof'])
            return dict(verified=True, independent=True, verifier=SCHEMA + ':existing-result-replay',
                payload_sha256=digest(outcome), receipt_sha256=digest(chain), evidence=chain,
                authority='official', source_sha256=result['result_source_sha256'],
                scope='EXISTING_SAVED_OFFICIAL_RESULT_REPLAY')
        except AdmissionError:
            raise
        except Exception:
            raise AdmissionError('OFFICIAL_ADMISSION_RESULT_REPLAY_FAILED') from None
