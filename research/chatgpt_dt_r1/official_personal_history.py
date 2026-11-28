"""Private research projection of the official profile's earlier finish records.

The caller must supply the original just admitted by ``records.admit_original``
and the matching normalized prospective input. That existing authority
reconstructs the source bytes and verifies the independent GitHub readback.
This adapter checks the resulting bindings but never authenticates ciphertext
or consults additional sources. Events are individual history, not a historical
roster, and both the events and their proof are for private research only.
"""
from datetime import timedelta
import re

from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_github_origin_evidence as origin
from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_rider_form_evidence as form
from race_ai.keirin_official_rider_history import _identities

from .data import input_digest
from .official_inputs import IDENTITY_NAMESPACE, SCHEMA
from .policy import RACE_TIMEZONE, check_race_day, checked_day, checked_sha, clock, digest


POLICY = 'DT_R1_OFFICIAL_PROFILE_FINISHES_PRIOR_8_TO_30_JST_DAYS_V1'
READY = 'READY'
NO_ELIGIBLE_FINISHES = 'NO_ELIGIBLE_FINISHES'
NO_AUTHENTICATED_PROFILE = 'NO_AUTHENTICATED_PROFILE'
PROFILE_NOT_AVAILABLE_AT_PREDICTION = 'PROFILE_NOT_AVAILABLE_AT_PREDICTION'
_AUTHENTICATED = 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF'
_CONDITION_ORIGIN_SCHEMA = 'RACE_AI_KEIRIN_CONDITIONED_GITHUB_SERVER_ORIGIN_EVIDENCE_V1'
_RACE = re.compile(r'20[0-9]{10}')
_COMMIT = re.compile(r'[0-9a-f]{40}')


class ProfileHistoryError(ValueError):
    """Malformed or conflicting input; never contains private evidence values."""


def _need(valid):
    if not valid:
        raise ProfileHistoryError('DT_R1_OFFICIAL_PROFILE_HISTORY_UNVERIFIED')


def _race_id(rid, day):
    _need(type(rid) is str and _RACE.fullmatch(rid) is not None and rid[:8] == day.strftime('%Y%m%d')
          and 1 <= int(rid[8:10]) <= 99 and 1 <= int(rid[10:]) <= 12)


def _checked_digest(document, key):
    sha = checked_sha(document[key])
    _need(sha == core.digest({k: v for k, v in document.items() if k != key}))
    return sha


def _target_binding(original, target, prediction_at):
    snapshot = original['snapshot']
    day, at = checked_day(target['day']), clock(prediction_at)
    rid = target['race_id']
    _race_id(rid, day)
    check_race_day(target['day'], target['cutoff_at'])
    cutoff = clock(snapshot['published_cutoff_at'])
    source_at = clock(snapshot['as_of'])
    _need(original['schema'] == records.PRE_SCHEMA and original['race_id'] == snapshot['race_id'] == rid
          and original['day_jst'] == target['day'] and target['venue_code'] == rid[8:10]
          and target['cohort'] == 'prospective' and target['source_projection_schema'] == SCHEMA
          and target['identity_scope'] == IDENTITY_NAMESPACE
          and clock(target['context_as_of']) == at
          and clock(target['cutoff_at']) == cutoff == clock(target['published_cutoff_at'])
          and clock(target['available_at']) == source_at == clock(target['source_available_at'])
          and source_at <= at <= cutoff - timedelta(minutes=15)
          and checked_sha(target['source_sha256']) == snapshot['cutoff_source']['bytes_sha256']
          and checked_sha(target['input_sha256']) == input_digest(target))
    starters = _identities(snapshot['riders'], 'athlete_id')
    riders = target['riders']
    _need(starters == _identities(riders, 'official_registration_id') and target['field_size'] == len(starters)
          and target['field_supported'] is True)
    for row in riders:
        expected = digest(dict(namespace=IDENTITY_NAMESPACE, registration=starters[row['car']]))
        _need(row['identity_status'] == 'OFFICIAL_REGISTRATION_SOURCE_BOUND'
              and row['identity_usable'] is True and row['identity_key'] == expected)
    return day, rid, at, cutoff, source_at, {row['car']: row['identity_key'] for row in riders}


def _baseline_binding(original, rid, cutoff, source_at):
    baseline = original['baseline']
    proof = original['origin_receipts']['baseline_origin']
    _checked_digest(proof, 'evidence_sha256')
    _checked_digest(baseline, 'prediction_sha256')
    latest = clock(proof['latest_server_evidence_at'])
    generated = clock(baseline['generated_at'])
    margin = proof['minimum_margin_seconds']
    _need(proof['schema'] == origin.SCHEMA and proof['state'] == 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED'
          and proof['race_id'] == rid == baseline['race_id'] and baseline['schema'] == core.PREDICTION
          and baseline['source_facts_sha256'] == core.digest(original['snapshot'])
          and checked_sha(proof['cipher_sha256']) == original['baseline_cipher_sha256']
          and clock(proof['official_cutoff_at']) == cutoff == clock(baseline['published_cutoff_at'])
          and str(proof['producer_run_id']) == original['producer_run_id']
          and proof['producer_commit'] == original['producer_commit']
          and proof['producer_job_id'] != proof['readback_job_id']
          and proof['producer_artifact_id'] != proof['readback_artifact_id']
          and type(margin) is int and margin >= 65 and cutoff - latest >= timedelta(seconds=margin)
          and source_at <= generated <= clock(original['baseline_sealed_at']) <= latest)
    for role in ('producer', 'readback'):
        checked_sha(proof[f'{role}_archive_sha256'])
        commit = proof[f'{role}_commit']
        _need(type(commit) is str and _COMMIT.fullmatch(commit) is not None)
        for name in ('run_id', 'job_id', 'artifact_id'):
            number = proof[f'{role}_{name}']
            _need(type(number) is int and number > 0)
    return baseline, proof, generated, latest


def _conditioned_binding(original, rid, cutoff, source_at, baseline, base_origin, generated, latest, starters):
    condition = original['conditioned']
    supplement = original['supplement']
    receipt = original['origin_receipts']['condition_origin']
    _checked_digest(receipt, 'evidence_sha256')
    _checked_digest(condition, 'sha256')
    supplement_sha = checked_sha(condition['condition_supplement_sha256'])
    _need(receipt['schema'] == _CONDITION_ORIGIN_SCHEMA
          and receipt['state'] == 'GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED'
          and checked_sha(receipt['cipher_sha256']) == original['conditioned_cipher_sha256']
          and receipt['baseline_cipher_sha256'] == base_origin['cipher_sha256']
          and receipt['baseline_origin_evidence_sha256'] == base_origin['evidence_sha256']
          and checked_sha(receipt['cohort_sha256']) == original['cohort_sha256']
          and receipt['baseline_prediction_sha256'] == baseline['prediction_sha256']
          and all(receipt[key] == value for key, value in base_origin.items()
                  if key not in ('schema', 'state', 'cipher_sha256', 'evidence_sha256'))
          and receipt['producer_run_id'] == receipt['readback_run_id']
          and receipt['producer_commit'] == receipt['readback_commit']
          and condition['schema'] == shadow.SCHEMA and condition['race_id'] == rid
          and condition['baseline_source_sha256'] == baseline['source_facts_sha256']
          and condition['baseline_prediction_sha256'] == baseline['prediction_sha256']
          and clock(condition['published_cutoff_at']) == cutoff
          and clock(condition['generated_at']) == generated <= clock(original['conditioned_sealed_at']) <= latest
          and type(supplement) is dict and set(supplement) == {'schema', 'race_id', 'source_pages', 'condition_evidence'}
          and supplement['schema'] == shadow.SUPPLEMENT_SCHEMA and supplement['race_id'] == rid
          and core.digest(supplement) == supplement_sha)
    pages, evidence = supplement['source_pages'], supplement['condition_evidence']
    _need(type(pages) is list and 1 <= len(pages) <= shadow.MAX_CONDITION_SOURCE_PAGES)
    captures = []
    for page in pages:
        _need(type(page) is dict and set(page) == {'kind', 'url', 'bytes_sha256', 'captured_at'}
              and page['kind'] == 'PROGRAM')
        checked_sha(page['bytes_sha256'])
        core._url(page['url'])
        captures.append(clock(page['captured_at']))
    as_of = max(source_at, *captures)
    _need(as_of <= generated)
    form.validate(evidence, starters=starters, source_pages=pages, as_of=as_of.isoformat(), target_race_id=rid)
    return evidence, receipt['evidence_sha256'], supplement_sha


def _eligible_events(evidence, identity_by_car, day):
    fields = {}
    events = []
    for rider in evidence['riders']:
        for result in rider['results']:
            prior = checked_day(result['race_date'])
            rid = result['race_id']
            _race_id(rid, prior)
            published = clock(result['published_at'])
            _need(prior <= published.astimezone(RACE_TIMEZONE).date()
                  and fields.setdefault(rid, result['field_size']) == result['field_size'])
            if result['status'] == 'FINISHED' and 8 <= (day - prior).days <= 30:
                events.append(dict(identity_key=identity_by_car[rider['car']], race_id=rid,
                    published_at=published.isoformat(), rank=result['place'], field_size=result['field_size'],
                    source_sha256=result['source_sha256']))
    return sorted(events, key=lambda event: (event['race_id'], event['identity_key']))


def profile_finishes(original, target, *, prediction_at):
    """Return private research events, an explicit status and a derived proof digest."""
    try:
        day, rid, at, cutoff, source_at, ids = _target_binding(original, target, prediction_at)
        baseline, base_origin, generated, latest = _baseline_binding(original, rid, cutoff, source_at)
        state = original['condition_state']
        if state != _AUTHENTICATED:
            _need(state in records.CONDITION_STATES and original['origin_receipts']['condition_origin'] is None
                  and all(original[key] is None for key in ('conditioned', 'supplement',
                                                             'conditioned_cipher_sha256', 'conditioned_sealed_at')))
            return dict(policy=POLICY, status=NO_AUTHENTICATED_PROFILE, events=[], proof_sha256=None)
        evidence, condition_sha, supplement_sha = _conditioned_binding(original, rid, cutoff, source_at,
            baseline, base_origin, generated, latest, set(ids))
        # The form validator requires every publication by evidence as-of,
        # which is itself bounded by the ciphertext's verified server time.
        events = _eligible_events(evidence, ids, day)
        if latest > at:
            return dict(policy=POLICY, status=PROFILE_NOT_AVAILABLE_AT_PREDICTION, events=[], proof_sha256=None)
        proof = digest(dict(policy=POLICY, race_id=rid, prediction_at=at.isoformat(),
            target_input_sha256=target['input_sha256'], baseline_origin_sha256=base_origin['evidence_sha256'],
            conditioned_origin_sha256=condition_sha, supplement_sha256=supplement_sha, events=events))
        return dict(policy=POLICY, status=READY if events else NO_ELIGIBLE_FINISHES, events=events, proof_sha256=proof)
    except (ValueError, KeyError, TypeError, OverflowError, AttributeError):
        raise ProfileHistoryError('DT_R1_OFFICIAL_PROFILE_HISTORY_UNVERIFIED') from None
