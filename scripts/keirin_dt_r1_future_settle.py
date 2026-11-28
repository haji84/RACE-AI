"""Read-only settlement of the first real DT future cohort.

Re-authenticate the retained first pin and independent GitHub artifacts, then
reproduce original inputs and forecasts at their recorded clocks BEFORE any
result is opened. Use the existing official result replayer. No provider GET,
video, training, wager, new authority, original replacement or state write.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from race_ai import keirin_form_fall_blind_pdca as pdca
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as codec
from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
from race_ai.keirin_official_paired_measurement import REPLAY_CODES
from research.chatgpt_dt_r1 import official_inputs
from research.chatgpt_dt_r1.future_retention_gate import check_first_retention
from research.chatgpt_dt_r1.pipeline import forecast_row, summarize_predictions
from research.chatgpt_dt_r1.policy import clock, digest, validate_forecast
from scripts import keirin_dt_r1_future_shadow as shadow
from scripts import keirin_dt_r1_future_readback as reader
from scripts import keirin_official_nationwide_continuation as continuation

DAY = '2026-11-28'
PRODUCER = '46082459814'
READER = '46083220254'
FIRST_INSERTION = 'a0ea5db4eec5938c2716c5d7950a43df98723f35'
ARCHIVE_COMMIT = 'ad17c6edccaa2dc05497fc99c7c653a08fd37cf2'
PIN_SHA = '093c8d02779a33b46f516d475e3d5549654eadb18c3b62f208c4a865b8cc3c4a'
PARENT = '15dd32600fbf5865df3eca340e41377e6f9caa19'
STEM = 'research/chatgpt-dt-r1/future/20261128/' + shadow.MODEL_SHA + '/'
SCHEMA = 'DT_R1_FIRST_FUTURE_SETTLEMENT_V1'
PDCA_TRIFECTA_POINTS = 4


class SettlementError(ValueError):
    def __init__(self, reason):
        super().__init__('DT_R1_SETTLEMENT_' + reason)
        self.reason = reason


def need(ok, reason):
    if not ok:
        raise SettlementError(reason)


@contextmanager
def _stage(reason):
    try:
        yield
    except SettlementError:
        raise
    except Exception:
        raise SettlementError(reason) from None


def _same(a, b):
    return digest(records.wire(a)) == digest(records.wire(b))


def _read_retention(work, tip, verified):
    records._check_archive_commit(work, ARCHIVE_COMMIT)
    records._check_archive_commit(work, PARENT)
    parents = archive._cmd(work, '--no-replace-objects', 'rev-list',
                           '--parents', '-n', '1', FIRST_INSERTION)[1].split()
    need(parents == [FIRST_INSERTION, PARENT] and
         archive._cmd(work, '--no-replace-objects', 'merge-base', '--is-ancestor',
                      FIRST_INSERTION, ARCHIVE_COMMIT, okay=True)[0] == 0, 'RETENTION_LINEAGE')
    pin_path = STEM + 'first-accepted.json'
    need(archive.read_blob_bytes(work, PARENT, pin_path, max_bytes=200001) is None,
         'FIRST_PIN_ALREADY_EXISTED')
    def read_exact(name):
        path = STEM + name
        raw = archive.read_blob_bytes(work, ARCHIVE_COMMIT, path, max_bytes=8_000_000)
        current = archive.read_blob_bytes(work, tip, path, max_bytes=8_000_000)
        need(raw is not None and current == raw, 'RETAINED_BYTES_CHANGED')
        return raw
    pin_raw = read_exact('first-accepted.json')
    need(archive.read_blob_bytes(work, FIRST_INSERTION, pin_path, max_bytes=200001) == pin_raw,
         'FIRST_INSERTION_PIN_CHANGED')
    pin = json.loads(pin_raw)
    need(pin.get('retention_parent_commit') == PARENT and
         pin.get('source_archive_commit') == PARENT, 'RETENTION_PARENT_MISMATCH')
    return check_first_retention(verified, pin_raw=pin_raw, read_retained=read_exact,
                                 expected_pin_sha256=PIN_SHA)


def _forecast_from_original(entry, verified, source, rid, private, trained, venues, client, cache):
    meta = source.index['originals'][rid]
    raw = (Path(verified['directory']) / entry['cipher']['file']).read_bytes()
    need(sha256(raw).hexdigest() == entry['cipher']['sha256'], 'FORECAST_CIPHER_CHANGED')
    with _stage('FORECAST_DECRYPT_UNVERIFIED'):
        saved = codec.decrypt_evidence(raw, private)
    clocks = entry['clocks']
    summary = verified['manifest']['summary']
    need(saved['schema'] == shadow.PRIVATE_SCHEMA and saved['day_jst'] == source.day and
         saved['race_id'] == rid and saved['observed_at'] == clocks['seal_started_at'] and
         saved['reader_run_id'] == PRODUCER == summary['reader_run_id'] and
         saved['reader_code_commit'] == summary['reader_code_commit'] and
         saved['source_archive_commit'] == source.head and
         saved['source_registry_reference'] == source.index['registry'] and
         saved['source_original_reference'] == meta and
         meta['cutoff_at'] == clocks['cutoff_at'], 'FORECAST_SOURCE_BINDING')
    with _stage('OFFICIAL_INPUT_REPLAY_UNVERIFIED'):
        payload = source.read(meta, private)
        original, _ = records.admit_original(source, payload, private, origin_client=client,
                                             packet_cache=cache)
    need(original['race_id'] == rid and original['day_jst'] == source.day and
         original['snapshot']['published_cutoff_at'] == clocks['cutoff_at'], 'SOURCE_REPLAY_CHANGED')
    # The old input clock is used ONLY to reproduce already sealed bytes.
    with _stage('FEATURE_REPLAY_UNVERIFIED'):
        row, replay_at, proof = shadow._candidate(
            store=source, payload=payload, original=original, trained=trained,
            venues=venues, private=private, client=client, cache=cache,
            clock=lambda: clock(clocks['input_at']))
    feature_row = dict(row, features=row['features'].tolist(),
                       feature_names=list(row['feature_names']))
    shared = saved['shared_material']
    need(clock(replay_at) == clock(clocks['input_at']) and
         _same(feature_row, saved['feature_row']) and
         row['input_sha256'] == entry['bindings']['input_sha256'] and
         row['feature_input_sha256'] == entry['bindings']['feature_input_sha256'] and
         row['source_attestation_sha256'] == entry['bindings']['source_receipt_sha256'] and
         digest(shared) == entry['bindings']['shared_material_sha256'] and
         shared['source_projection_schema'] == official_inputs.SCHEMA and
         shared['source_projection_sha256'] == digest(official_inputs.source_projection(payload, original)) and
         shared['source_archive_commit'] == source.head and shared['source_original_reference'] == meta and
         shared['input_sha256'] == row['input_sha256'] and _same(shared['source_verification'], proof) and
         shared['history_races'] == 0 and shared['history_status'] == 'MISSING_HISTORY',
         'FEATURE_OR_SOURCE_REPLAY_CHANGED')
    replay = forecast_row(trained, row, prediction_at=clocks['prediction_started_at'], full=True)
    replay.update(prediction_at=clocks['prediction_at'],
        scope='DT_ONLY_FUTURE_SHADOW_PENDING_INDEPENDENT_READBACK',
        forecast_original_independently_read_back=False, production_promoted=False)
    need(replay['status'] == 'READY' and replay['model_sha256'] == shadow.MODEL_SHA and
         _same(replay, saved['forecast']), 'FROZEN_FORECAST_REPLAY_CHANGED')
    checked = validate_forecast(saved['forecast'])
    need(checked['starters'] == sorted(r['car'] for r in original['snapshot']['riders']),
         'FORECAST_ROSTER_CHANGED')
    return saved['forecast']


def _result_row(result_store, rid, private, original_meta, now):
    row = dict(race_id=rid, day=result_store.day)
    current = result_store.index['originals'].get(rid)
    if current is None:
        return dict(row, result_status='NO_SAVED_OFFICIAL_ORIGINAL')
    versions = result_store.index['results'].get(rid, [])
    if not versions:
        return dict(row, result_status='MISSING_SAVED_RESULT')
    # An invalid latest revision must not cause silent fallback to an old one.
    meta = versions[-1]
    try:
        need(original_meta is None or current == original_meta, 'RESULT_ORIGINAL_CHANGED')
        with _stage('RESULT_REVISION_ORDER_UNVERIFIED'):
            clocks = [clock(revision['observed_at']) for revision in versions]
            need(all(earlier < later for earlier, later in zip(clocks, clocks[1:])),
                 'RESULT_REVISION_ORDER_UNVERIFIED')
        try:
            _, scored, _ = records._replay_saved_result(result_store, current, meta, private)
        except Exception as error:
            reason = REPLAY_CODES.get(str(error), 'OFFICIAL_RESULT_REPLAY_FAILED')
            raise SettlementError(reason) from None
        final = scored['official_result']
        need(final['race_id'] == rid and
             clock(final['official_cutoff_at']) == clock(current['cutoff_at']) and
             clock(current['cutoff_at']) < clock(final['observed_at']) <= clock(meta['observed_at']) <= now,
             'RESULT_CLOCK_OR_AUTHORITY')
        if final['status'] == 'CANCELLED' and final['refund_status'] == 'FULL':
            return dict(row, result_status='OFFICIAL_CANCELLED')
        if final['refund_status'] != 'NONE':
            return dict(row, result_status='OFFICIAL_REFUND')
        need(final['status'] == 'FINAL_NORMAL', 'RESULT_STATUS_UNSUPPORTED')
        triples = final['winning_triples']
        if len(triples) != 1:
            return dict(row, result_status='NON_UNIQUE_TOP3')
        top = triples[0]
        cars = {r['car'] for r in final['starters']}
        need(type(top) is list and len(top) == len(set(top)) == 3 and
             all(type(c) is int and c in cars for c in top), 'RESULT_TOP3_INVALID')
        return dict(row, result_status='VERIFIED_NORMAL', top3=top)
    except SettlementError as error:
        return dict(row, result_status='RESULT_REPLAY_UNVERIFIED', result_hold_reason=error.reason)
    except Exception:
        return dict(row, result_status='RESULT_REPLAY_UNVERIFIED',
                    result_hold_reason='OFFICIAL_RESULT_REPLAY_FAILED')


def _placing_pdca(rid, forecast, outcome, entry):
    """Feed the existing classifier with already authenticated in-memory originals."""
    top = sorted(forecast['trifectas'], key=lambda t: (-t['probability'], t['cars']))
    frozen = dict(race_id=rid, scope='registered', flow={},
        sealed_at=entry['clocks']['seal_started_at'], cutoff_at=entry['clocks']['cutoff_at'],
        tickets=[t['cars'] for t in top[:PDCA_TRIFECTA_POINTS]])
    official = dict(race_id=rid, winning_triples=[outcome['top3']])
    # The loaders have authenticated the frozen forecast and official result.
    # Those attestations apply only to these derived objects. This cohort did
    # not seal flow forecasts, so the classifier receives no flow observations.
    starters = sorted(rider['car'] for rider in forecast['riders'])
    return pdca.compare_race_development(race_id=rid, starters=starters,
        forecast=frozen, order=official, observations=[],
        verify_forecast=lambda value: value is frozen,
        verify_order=lambda value: value is official,
        verify_observation=lambda _: False)


def _score_registered(race_ids, day, entries, eligible, reader_holds, forecast_loader, result_loader):
    """Reverify all admitted forecast originals before opening any outcome."""
    need(len(race_ids) == len(set(race_ids)), 'DUPLICATE_REGISTRY')
    slots = {shadow.slot(day, rid): rid for rid in race_ids}
    by_slot = {e['slot_sha256']: e for e in entries}
    need(len(slots) == len(entries) == len(by_slot) and set(by_slot) == set(slots) and
         len(eligible) == len(set(eligible)) and set(eligible) <= set(slots) and
         all(by_slot[s]['state'] == shadow.READY for s in eligible), 'REGISTRY_SLOT_MISMATCH')
    eligible_slots = set(eligible)
    ready_slots = {s for s, e in by_slot.items() if e['state'] == shadow.READY}
    late_slots = {s for s, reason in reader_holds.items() if reason == 'SERVER_READBACK_AFTER_T15'}
    need(ready_slots - eligible_slots == late_slots and not eligible_slots & late_slots,
         'READER_SLOT_PARTITION')
    holds = Counter(e['reason'] for e in entries if e['state'] == 'HOLD')
    if late_slots:
        holds['SERVER_READBACK_AFTER_T15'] = len(late_slots)
    admitted = {}
    for s in eligible:
        rid = slots[s]
        try:
            f = forecast_loader(by_slot[s], rid)
            need(f['race_id'] == rid and f['day'] == day and
                 f['status'] == 'READY' and f['model_sha256'] == shadow.MODEL_SHA,
                 'FORECAST_IDENTITY')
            admitted[rid] = f
        except SettlementError as error:
            holds[error.reason] += 1
        except Exception:
            holds['FORECAST_REPLAY_UNVERIFIED'] += 1
    need(len(admitted) + sum(holds.values()) == len(race_ids), 'FORECAST_COUNT_PARTITION')
    outcomes, development = [], []
    for rid in race_ids:
        row = result_loader(rid)
        need(row['race_id'] == rid and row['day'] == day, 'RESULT_IDENTITY')
        if rid in admitted:
            row = dict(row, input_sha256=admitted[rid]['input_sha256'])
            if row['result_status'] == 'VERIFIED_NORMAL':
                development.append(_placing_pdca(rid, admitted[rid], row,
                                                  by_slot[shadow.slot(day, rid)]))
        outcomes.append(row)
    metrics = summarize_predictions(list(admitted.values()), outcomes)
    # A running series of exact probability means would disclose a private
    # outcome probability whenever a single newly verified result is added.
    del metrics['proper_scores']
    return dict(registered_races=len(race_ids), independently_timed_candidates=len(eligible),
                owner_originals_replayed=len(admitted), forecast_holds=dict(holds),
                result_states=dict(Counter(row['result_status'] for row in outcomes)),
                result_replay_holds=dict(Counter(row['result_hold_reason'] for row in outcomes
                                                 if 'result_hold_reason' in row)),
                pdca=dict(fixed_trifecta_points=PDCA_TRIFECTA_POINTS,
                          placing_checked=sum(d['placing']['formal'] for d in development),
                          flow_checked=sum(d['flow']['state'] in ('match', 'different') for d in development),
                          grade_counts=dict(Counter(d['grade'] for d in development if d['grade']))),
                metrics=metrics)


def run_settlement(*, repo, private_root, owner_public_pem, owner_private_pem, day=DAY,
                   now=continuation.now_utc):
    with _stage('PROTECTED_RUNTIME_UNVERIFIED'):
        repo, root, day, _, commit = continuation._runtime(repo=repo, private_root=private_root,
            owner_public_pem=owner_public_pem, owner_private_pem=owner_private_pem, day=day,
            clock=now, mode='study')
    need(day == DAY, 'FIRST_BATCH_ONLY')
    with _stage('FROZEN_MODEL_UNVERIFIED'):
        trained, venues = shadow.load_frozen(repo)
    client = GitHubEvidenceClient()
    with TemporaryDirectory(prefix='dt-first-settle-', dir=root) as tmp, ExitStack() as contexts:
        work = Path(tmp)
        with _stage('ARCHIVE_FETCH_UNVERIFIED'):
            archive._cmd(work, 'init', '--quiet', '--template=')
            archive._cmd(work, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
            archive._cmd(work, 'config', '--local', 'remote.origin.promisor', 'true')
            archive._cmd(work, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
            tip = records.fetch_partial_head(work, with_ancestry=True)
        with _stage('PRODUCER_AUTHENTICATION_FAILED'):
            verified = contexts.enter_context(reader.verified_producer(PRODUCER, client=client))
        with _stage('RETENTION_AUTHENTICATION_FAILED'):
            retention = _read_retention(work, tip, verified)
        with _stage('READBACK_AUTHENTICATION_FAILED'):
            origin = reader.verify_readback(verified, READER, client=client)
        manifest = verified['manifest']
        need(manifest['summary']['source_archive_commit'] == PARENT and
             manifest['summary']['day_jst'] == day and
             origin['manifest_sha256'] == retention['manifest_sha256'], 'BATCH_PIN')
        with _stage('REGISTRY_REPLAY_UNVERIFIED'):
            source = records.RecordStore(work, day, index_commit=PARENT)
            current = records.RecordStore(work, day, index_commit=tip)
            need({k: source.index['registry'][k] for k in ('cipher_sha256', 'evidence_sha256')}
                 == manifest['registry'], 'REGISTRY_PIN')
            registry = records.replay_registry(source.read(source.index['registry'], owner_private_pem))
            latest = records.replay_registry(current.read(current.index['registry'], owner_private_pem))
            races = registry['registered_race_ids']
            need(registry['event_day'] == latest['event_day'] == day and
                 set(races) <= set(latest['registered_race_ids']), 'REGISTRY_LINEAGE')
        cache = {}
        result = _score_registered(races, day, manifest['entries'], origin['eligible_slots'],
            origin['held_slots'],
            lambda e, rid: _forecast_from_original(e, verified, source, rid, owner_private_pem,
                                                    trained, venues, client, cache),
            lambda rid: _result_row(current, rid, owner_private_pem,
                                     source.index['originals'].get(rid), now()))
        return dict(schema=SCHEMA, day_jst=day, scope='FIRST_PINNED_DT_ONLY_COHORT',
            state='DT_OFFICIAL_RESULTS_SCORED' if result['metrics']['predicted_evaluable']
                  else 'HOLD_NO_VERIFIED_PREDICTED_RESULT',
            **result, retention=retention, result_archive_commit=tip,
            reader_code_commit=commit, reader_run_id=os.environ['GITHUB_RUN_ID'],
            producer_run_id=PRODUCER, independent_readback_run_id=READER,
            independent_server_evidence_at=origin['latest_server_evidence_at'],
            minimum_margin_seconds=origin['minimum_margin_seconds'],
            latest_registry_races=len(latest['registered_race_ids']),
            added_after_frozen_registry=len(set(latest['registered_race_ids']) - set(races)),
            video_required=False, provider_source_requests=0, state_writes=0,
            training_runs=0, new_forecasts=0, formal_three_way_races=0,
            confidence='HOLD', payout_evaluation='NOT_RUN', production_promoted=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--owner-public-pem', type=Path, required=True)
    parser.add_argument('--day', default=DAY)
    args = parser.parse_args(argv)
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        report = run_settlement(repo=args.repo, private_root=args.private_root,
            owner_public_pem=args.owner_public_pem, owner_private_pem=private, day=args.day)
    except Exception as error:
        reason = (error.reason if isinstance(error, SettlementError)
                  else 'RUNTIME_OR_ORIGINAL_AUTHENTICATION_FAILED')
        report = dict(schema=SCHEMA, scope='FIRST_PINNED_DT_ONLY_COHORT',
            state='HOLD_SETTLEMENT_RUNTIME_OR_ORIGIN_UNVERIFIED', registered_races=None,
            reason=reason, production_promoted=False,
            formal_three_way_races=0, provider_source_requests=0, state_writes=0)
    finally:
        private = b''
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['state'] == 'DT_OFFICIAL_RESULTS_SCORED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
