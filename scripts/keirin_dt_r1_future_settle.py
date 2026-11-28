"""Read-only settlement of the first DT-R1 cohort or a registered JST day.

Re-authenticate the retained first originals and independent GitHub artifacts, then
reproduce original inputs and forecasts at their recorded clocks BEFORE any
result is opened. Use the existing official result replayer. No provider GET,
video, training, wager, new authority, original replacement or state write.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
from functools import partial
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from race_ai import keirin_form_fall_blind_pdca as pdca
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as codec
from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
from race_ai.keirin_official_paired_measurement import REPLAY_CODES
from race_ai.keirin_paired_measurement import _difference_ci
from research.chatgpt_dt_r1 import back_official_shadow, future_batch_retention as batch_retention
from research.chatgpt_dt_r1.future_retention_gate import (
    FIRST_DAY as DAY, FIRST_PRODUCER as PRODUCER, FIRST_READER as READER,
    FIRST_SOURCE_PARENT as PARENT, read_legacy_first_retention)
from research.chatgpt_dt_r1.official_history import OfficialHistory, POLICY as HISTORY_POLICY
from research.chatgpt_dt_r1.official_feature_audit import OfficialFeatureAudit
from research.chatgpt_dt_r1.pipeline import forecast_row, summarize_predictions
from research.chatgpt_dt_r1.policy import clock, digest, validate_forecast
from scripts import keirin_dt_r1_future_shadow as shadow
from scripts import keirin_dt_r1_future_readback as reader
from scripts import keirin_official_nationwide_continuation as continuation
from scripts.keirin_dt_r1_owner_restore import BACK_RECEIPT

SCHEMA = 'DT_R1_FIRST_FUTURE_SETTLEMENT_V1'
DAY_SCHEMA = 'DT_R1_ARCHIVED_DAY_SETTLEMENT_V1'
FIRST_SCOPE = 'FIRST_PINNED_DT_ONLY_COHORT'
DAY_SCOPE = 'REGISTERED_DAY_FIRST_T15_ORIGINALS'
PDCA_TRIFECTA_POINTS = 4
BACK_ARMS = ('back_mixture', 'direct')


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


def _forecast_from_original(entry, raw, manifest, source, rid, private, trained, venues, client, cache,
                            *, history_sources=None, history_controls=None, back_trial=None, back_pairs=None,
                            back_holds=None, feature_rows=None, personal_add=None, personal_pairs=None,
                            personal_holds=None):
    meta = source.index['originals'][rid]
    need(sha256(raw).hexdigest() == entry['cipher']['sha256'], 'FORECAST_CIPHER_CHANGED')
    with _stage('FORECAST_DECRYPT_UNVERIFIED'):
        saved = codec.decrypt_evidence(raw, private)
    clocks = entry['clocks']
    summary = manifest['summary']
    need(saved['schema'] == shadow.PRIVATE_SCHEMA and saved['day_jst'] == source.day and
         saved['race_id'] == rid and saved['observed_at'] == clocks['seal_started_at'] and
         saved['reader_run_id'] == summary['reader_run_id'] and
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
    sealed = saved['shared_material']
    need(type(sealed) is dict and digest(sealed) == entry['bindings']['shared_material_sha256'],
         'FEATURE_OR_SOURCE_REPLAY_CHANGED')
    personal_material = sealed.get('schema') == shadow.PERSONAL_STUDY_MATERIAL_SCHEMA
    shared = sealed.get('frozen_material') if personal_material else sealed
    if personal_material:
        need(type(shared) is dict and shared.get('schema') in (shadow.PAIRED_HISTORY_MATERIAL_SCHEMA,
             shadow.BACK_STUDY_MATERIAL_SCHEMA) and 'no_history_control' in shared, 'FEATURE_MATERIAL_SCHEMA')
    # The old input clock is used ONLY to reproduce already sealed bytes.
    with _stage('FEATURE_REPLAY_UNVERIFIED'):
        material_schema = shared['schema']
        back_material = material_schema == shadow.BACK_STUDY_MATERIAL_SCHEMA
        has_history = material_schema in (shadow.HISTORY_MATERIAL_SCHEMA, shadow.PAIRED_HISTORY_MATERIAL_SCHEMA)
        has_control = material_schema == shadow.PAIRED_HISTORY_MATERIAL_SCHEMA
        if back_material:
            has_history = 'history_policy' in shared
            has_control = 'no_history_control' in shared
            need('back_study' in shared and (has_history or not has_control), 'BACK_STUDY_MATERIAL_CHANGED')
        need(back_material or has_history or material_schema == shadow.LEGACY_MATERIAL_SCHEMA,
             'FEATURE_MATERIAL_SCHEMA')
        prior = None
        if has_history:
            need(shared.get('history_policy') == HISTORY_POLICY, 'HISTORY_POLICY_CHANGED')
            history_sources = {} if history_sources is None else history_sources
            if source.head not in history_sources:
                history_sources[source.head] = OfficialHistory(source, private)
            prior = history_sources[source.head]
        row, replay_at, proof = shadow._candidate(
            store=source, payload=payload, original=original, trained=trained,
            venues=venues, private=private, client=client, cache=cache,
            clock=lambda: clock(clocks['input_at']), official_history=prior)
        control = None
        if has_control:
            control = shadow._no_history_forecast(store=source, payload=payload, original=original,
                trained=trained, venues=venues, private=private, client=client, cache=cache,
                input_at=clocks['input_at'], prediction_started_at=clocks['prediction_started_at'])
    feature_row = dict(row, features=row['features'].tolist(),
                       feature_names=list(row['feature_names']))
    need(clock(replay_at) == clock(clocks['input_at']) and
         _same(feature_row, saved['feature_row']) and
         row['input_sha256'] == entry['bindings']['input_sha256'] and
         row['feature_input_sha256'] == entry['bindings']['feature_input_sha256'] and
         row['source_attestation_sha256'] == entry['bindings']['source_receipt_sha256'],
         'FEATURE_OR_SOURCE_REPLAY_CHANGED')
    expected = shadow._shared_material(row, payload, original, source, proof, control=control)
    if back_material:
        base = {key: value for key, value in shared.items() if key != 'back_study'}
        base['schema'] = expected['schema']
    else:
        base = shared
    need(_same(base, expected), 'FEATURE_OR_SOURCE_REPLAY_CHANGED')
    replay = forecast_row(trained, row, prediction_at=clocks['prediction_started_at'], full=True)
    replay.update(prediction_at=clocks['prediction_at'],
        scope='DT_ONLY_FUTURE_SHADOW_PENDING_INDEPENDENT_READBACK',
        forecast_original_independently_read_back=False, production_promoted=False)
    need(replay['status'] == 'READY' and replay['model_sha256'] == shadow.MODEL_SHA and
         _same(replay, saved['forecast']), 'FROZEN_FORECAST_REPLAY_CHANGED')
    checked = validate_forecast(saved['forecast'])
    need(checked['starters'] == sorted(r['car'] for r in original['snapshot']['riders']),
         'FORECAST_ROSTER_CHANGED')
    if personal_add is not None:
        personal_add(payload=payload, original=original, baseline=row, prior=prior, prediction_at=replay_at)
    if feature_rows is not None:
        feature_rows[rid] = (row, original)
    if control is not None and history_controls is not None:
        history_controls[rid] = dict(control, prediction_at=clocks['prediction_at'])
    if back_material:
        try:
            with _stage('BACK_STUDY_RESTORE_UNVERIFIED'):
                need(callable(back_trial), 'BACK_STUDY_RESTORE_UNVERIFIED')
                restored = back_trial()
            with _stage('BACK_STUDY_REPLAY_UNVERIFIED'):
                pair = shadow._back_study_pair(restored, store=source, payload=payload, original=original,
                    private=private, client=client, cache=cache, input_at=clocks['input_at'],
                    official_history=prior)
                expected = shadow._shared_material(row, payload, original, source, proof,
                                                   control=control, back_study=pair)
                need(_same(shared, expected), 'BACK_STUDY_MATERIAL_CHANGED')
                if back_pairs is not None:
                    back_pairs[rid] = {name: dict(race_id=rid, day=source.day, status='READY',
                        input_sha256=row['input_sha256'], trifectas=pair['arms'][name]['trifectas'],
                        exactas=pair['arms'][name]['exactas']) for name in BACK_ARMS}
        except SettlementError as error:
            if back_holds is not None:
                back_holds[rid] = error.reason if error.reason in (
                    'BACK_STUDY_RESTORE_UNVERIFIED', 'BACK_STUDY_MATERIAL_CHANGED') else 'BACK_STUDY_REPLAY_UNVERIFIED'
    if personal_material:
        try:
            with _stage('PERSONAL_STUDY_REPLAY_UNVERIFIED'):
                trial, hold = shadow.personal_trial(trained=trained, venues=venues, payload=payload,
                    original=original, baseline=row, prior=prior, prediction_at=clocks['input_at'])
                need(trial is not None and hold is None, 'PERSONAL_STUDY_REPLAY_UNVERIFIED')
                expected = shadow._personal_study_material(trial, row, trained, clocks['prediction_at'])
                need(set(sealed) == {'schema', 'frozen_material', 'personal_history_trial'} and
                     _same(sealed['personal_history_trial'], expected), 'PERSONAL_STUDY_MATERIAL_CHANGED')
                if personal_pairs is not None:
                    personal_pairs[rid] = dict(trial['forecast'], used_finishes=trial['used_finishes'])
        except SettlementError as error:
            if personal_holds is not None:
                personal_holds[rid] = error.reason
    return saved['forecast']


def _prefetch_result_ciphers(store, race_ids):
    folder = f'{records.ROOT}/{store.day}'
    versions = (store.index['results'].get(rid) for rid in race_ids)
    paths = {f"{folder}/{revisions[-1]['evidence_sha256']}.sealed.json"
             for revisions in versions if revisions}
    try:
        archive.prefetch_pinned_blobs(store.repo, store.head, paths, (folder,))
    except archive.GitCipherArchiveError:
        # A cache warmup failure leaves each result to the existing verified reader.
        pass


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
        cutoff = clock(current['cutoff_at'])
        observed = clock(final['observed_at'])
        cancelled = final['status'] == 'CANCELLED' and final['refund_status'] == 'FULL'
        need(final['race_id'] == rid and
             clock(final['official_cutoff_at']) == cutoff and
             observed <= clock(meta['observed_at']) <= now and (cancelled or cutoff < observed),
             'RESULT_CLOCK_OR_AUTHORITY')
        if cancelled:
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


def _fixed_point_hits(forecasts, results, error):
    score = summarize_predictions(forecasts, results)
    need(score['predicted_evaluable'] == len(results), error)
    return {market: {k: cell['hits'] for k, cell in score[market].items()} for market in ('trifecta', 'exacta')}


def _paired_one_point(results, *, baseline, baseline_forecasts, comparison, comparison_forecasts):
    """Measure the same official outcomes after both arms pass the fixed-point scorer."""
    count = len(results)
    report = dict(baseline=baseline, comparison=comparison,
                  interval_scope='EXPLORATORY_NOMINAL_WILSON_RACES_UNCLUSTERED')
    for market, width in (('trifecta', 3), ('exacta', 2)):
        gained = lost = 0
        for row in results:
            rid = row['race_id']
            target = tuple(row['top3'][:width])
            hits = []
            for forecasts in (baseline_forecasts, comparison_forecasts):
                first = min(forecasts[rid][market + 's'], key=lambda ticket: (-ticket['probability'], ticket['cars']))
                hits.append(tuple(first['cars']) == target)
            baseline_hit, comparison_hit = hits
            gained += comparison_hit and not baseline_hit
            lost += baseline_hit and not comparison_hit
        report[market] = dict(paired_races=count, difference=(gained - lost) / count if count else None,
                              difference_ci95=_difference_ci(gained, lost, count))
    return report


def _score_back_pairs(admitted, outcomes, back_pairs, back_holds):
    paired_races = admitted.keys() & back_pairs.keys()
    held_races = admitted.keys() & back_holds.keys()
    need(not paired_races & held_races, 'BACK_STUDY_PAIR_PARTITION')
    if not paired_races and not held_races:
        return None
    paired_rows = [r for r in outcomes if r['race_id'] in paired_races and r['result_status'] == 'VERIFIED_NORMAL']
    summary = dict(registered_day=len(outcomes), retained_pairs=len(paired_races),
                   official_scorable_pairs=len(paired_rows), back_leader_observations=0,
                   replay_holds=dict(Counter(back_holds[rid] for rid in held_races)))
    arms = {name: {rid: back_pairs[rid][name] for rid in sorted(paired_races)} for name in BACK_ARMS}
    for name, forecasts in arms.items():
        summary[name] = _fixed_point_hits(list(forecasts.values()), paired_rows, 'BACK_STUDY_PAIR_DENOMINATOR')
    summary['paired_one_point'] = _paired_one_point(paired_rows, baseline='direct', baseline_forecasts=arms['direct'],
        comparison='back_mixture', comparison_forecasts=arms['back_mixture'])
    return summary


def _score_personal_pairs(admitted, outcomes, personal_pairs, personal_holds):
    paired_races = sorted(admitted.keys() & personal_pairs.keys())
    held_races = admitted.keys() & personal_holds.keys()
    need(not set(paired_races) & held_races, 'PERSONAL_STUDY_PAIR_PARTITION')
    if not paired_races and not held_races:
        return None
    paired = [r for r in outcomes if r['race_id'] in personal_pairs and r['race_id'] in admitted]
    scorable = [r for r in paired if r['result_status'] == 'VERIFIED_NORMAL']
    error = 'PERSONAL_STUDY_PAIR_DENOMINATOR'
    return dict(policy=shadow.PERSONAL_HISTORY_POLICY, prospectively_sealed=True,
        registered_day=len(outcomes), sealed_trials=len(paired_races) + len(held_races),
        retained_pairs=len(paired_races), official_scorable_pairs=len(scorable),
        pair_result_states=dict(Counter(r['result_status'] for r in paired)),
        replay_holds=dict(Counter(personal_holds[rid] for rid in held_races)),
        official_prior_personal_finish_exposures=sum(personal_pairs[rid]['used_finishes'] for rid in paired_races),
        archive_seven=_fixed_point_hits([admitted[rid] for rid in paired_races], scorable, error),
        seven_and_personal_days_8_to_30=_fixed_point_hits([personal_pairs[rid] for rid in paired_races], scorable, error),
        paired_one_point=_paired_one_point(scorable, baseline='archive_seven', baseline_forecasts=admitted,
            comparison='seven_and_personal_days_8_to_30', comparison_forecasts=personal_pairs))


def _score_codex_pair(admitted, outcomes, codex, same_source, retained, holds):
    comparable = admitted.keys() & codex.keys() & same_source
    registered = [dict(row, input_sha256=codex[row['race_id']]['input_sha256']) if row['race_id'] in codex else row
                  for row in outcomes]
    common = [row for row in outcomes if row['race_id'] in comparable]
    scorable = [row for row in common if row['result_status'] == 'VERIFIED_NORMAL']
    codex_total = summarize_predictions(list(codex.values()), registered)
    del codex_total['proper_scores']
    need(len(codex) + sum(holds.values()) == retained, 'CODEX_RETAINED_PARTITION')
    return dict(registered_day=len(outcomes), codex_independently_timed=retained, codex_replayed=len(codex),
        dt_r1_replayed=len(admitted), same_source_originals=len(comparable), official_scorable_pairs=len(scorable),
        common_result_states=dict(Counter(row['result_status'] for row in common)), replay_holds=holds,
        codex_all_targets=codex_total, formal_three_way_races=0,
        common={name: _fixed_point_hits([forecasts[rid] for rid in sorted(comparable)], scorable,
                                         'CODEX_COMMON_RESULT_DENOMINATOR')
                for name, forecasts in (('dt_r1', admitted), ('codex', codex))},
        paired_one_point=_paired_one_point(scorable, baseline='codex', baseline_forecasts=codex,
            comparison='dt_r1', comparison_forecasts=admitted))


def _score_registered(race_ids, day, entries, eligible, reader_holds, forecast_loader, result_loader,
                      *, history_controls=None, back_pairs=None, back_holds=None, personal_report=None,
                      personal_pairs=None, personal_holds=None, codex_report=None, prefetch_results=None):
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
    if prefetch_results is not None:
        prefetch_results()
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
    paired_races = set(admitted).intersection(history_controls or {})
    if paired_races:
        paired_rows = [row for row in outcomes if row['race_id'] in paired_races]
        paired = {}
        for name, forecasts in (('official_history', admitted), ('no_history', history_controls)):
            paired[name] = summarize_predictions([forecasts[rid] for rid in sorted(paired_races)], paired_rows)
            del paired[name]['proper_scores']
        scorable = [row for row in paired_rows if row['result_status'] == 'VERIFIED_NORMAL']
        need(paired['official_history']['predicted_evaluable'] == paired['no_history']['predicted_evaluable'] == len(scorable),
             'HISTORY_PAIR_DENOMINATOR')
        metrics['paired_history'] = dict(policy=shadow.HISTORY_CONTROL_POLICY,
            registered_day=len(race_ids), retained_pairs=len(paired_races), **paired,
            paired_one_point=_paired_one_point(scorable, baseline='no_history', baseline_forecasts=history_controls,
                comparison='official_history', comparison_forecasts=admitted))
    paired_back = _score_back_pairs(admitted, outcomes, back_pairs or {}, back_holds or {})
    if paired_back is not None:
        metrics['paired_back'] = paired_back
    try:
        paired_personal = _score_personal_pairs(admitted, outcomes, personal_pairs or {}, personal_holds or {})
        if paired_personal is not None:
            metrics['paired_personal_history'] = paired_personal
    except Exception:
        metrics['paired_personal_history'] = dict(state='HOLD_PERSONAL_STUDY_SCORING_UNVERIFIED')
    if personal_report is not None:
        try:
            metrics['personal_history_study'] = personal_report(admitted, outcomes)
        except Exception:
            metrics['personal_history_study'] = dict(state='HOLD_PROFILE_STUDY_SCORING_UNVERIFIED',
                                                      prospectively_sealed=False)
    if codex_report is not None:
        try:
            metrics['paired_codex'] = codex_report(admitted, outcomes)
        except Exception:
            metrics['paired_codex'] = dict(state='HOLD_CODEX_PAIR_SCORING_UNVERIFIED', formal_three_way_races=0)
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


def _load_registry(store, private, manifest=None):
    meta = store.index['registry']
    need(meta is not None, 'SAVED_REGISTRY_MISSING')
    registry = records.replay_registry(store.read(meta, private))
    need(registry['event_day'] == store.day, 'REGISTRY_DAY')
    if manifest is not None:
        need({k: meta[k] for k in ('cipher_sha256', 'evidence_sha256')} == manifest['registry'],
             'REGISTRY_PIN')
        slots = {shadow.slot(store.day, rid) for rid in registry['registered_race_ids']}
        entries = manifest['entries']
        need(len(slots) == len(entries) and slots == {entry['slot_sha256'] for entry in entries},
             'REGISTRY_SLOT_MISMATCH')
    return registry


def _same_codex_peer(codex, dt):
    manifest = dt['manifest']
    peer = codex['manifest']['summary']
    return (peer['dt_producer_run_id'] == manifest['summary']['reader_run_id'] and
            peer['dt_manifest_sha256'] == sha256(codec._canonical(manifest)).hexdigest() and
            codex['entry']['bindings']['input_sha256'] == dt['entry']['bindings']['input_sha256'] and
            clock(codex['entry']['clocks']['cutoff_at']) == clock(dt['entry']['clocks']['cutoff_at']))


def _prepare_codex_pair(*, work, current, private, repo, client, slots, dt_selected, loaded, packet_cache):
    from research.chatgpt_dt_r1 import codex_future_candidate
    from scripts.keirin_codex_future_pair_replay import CodexReplayError, replay_codex_original

    model = codex_future_candidate.model_identity()
    with _stage('CODEX_RETENTION_AUTHENTICATION_FAILED'):
        retained = batch_retention.read_retained_forecasts(work, current.head, current.day, model['model_sha256'],
            slots, authenticate_batch=partial(reader.verify_saved_batch, client=client, codex=True),
            verify_registry=True, prefetch_blobs=True)
    trained = None
    if retained:
        with _stage('CODEX_FROZEN_MODEL_UNVERIFIED'):
            trained = codex_future_candidate.load_frozen(repo, private, current.day)
    forecasts, compatible, holds, checked = {}, set(), Counter(), set()
    for slot, record in retained.items():
        rid, manifest = slots[slot], record['manifest']
        info = manifest['summary']
        try:
            commit, run = info['source_archive_commit'], info['reader_run_id']
            if commit not in loaded:
                loaded[commit] = records.RecordStore(work, current.day, index_commit=commit)
            source = loaded[commit]
            if run not in checked:
                registry = _load_registry(source, private, manifest)
                need(all(shadow.slot(source.day, item) in slots for item in registry['registered_race_ids']),
                     'CODEX_REGISTRY_LINEAGE')
                checked.add(run)
            need(source.index['originals'][rid] == current.index['originals'].get(rid), 'CODEX_SOURCE_ORIGINAL_CHANGED')
            raw = archive.read_blob_bytes(work, current.head, record['cipher_path'],
                                         max_bytes=batch_retention.MAX_ARCHIVE_BYTES + 1)
            forecast = replay_codex_original(record['entry'], raw, manifest, source, rid, private,
                                             trained, client, packet_cache)
            need(forecast['race_id'] == rid and forecast['day'] == current.day and forecast['status'] == 'READY' and
                 all(forecast[key] == model[key] for key in ('model_id', 'model_sha256')), 'CODEX_FORECAST_IDENTITY')
            if slot in dt_selected and _same_codex_peer(record, dt_selected[slot]):
                compatible.add(rid)
            forecasts[rid] = forecast
        except (SettlementError, CodexReplayError) as error:
            holds[error.reason] += 1
        except Exception:
            holds['CODEX_ORIGINAL_REPLAY_UNVERIFIED'] += 1
    return partial(_score_codex_pair, codex=forecasts, same_source=compatible, retained=len(retained), holds=dict(holds))


def _score_archived_day(work, current, private, trained, venues, client, now, legacy, *, back_trial=None,
                        feature_audit=None, personal_study=None, codex_repo=None, progress=None):
    day = current.day
    with _stage('REGISTRY_REPLAY_UNVERIFIED'):
        registry = _load_registry(current, private)
        races = registry['registered_race_ids']
        slots = {shadow.slot(day, rid): rid for rid in races}
        race_set = set(races)
    with _stage('RETENTION_AUTHENTICATION_FAILED'):
        additional = batch_retention.read_retained_forecasts(work, current.head, day, shadow.MODEL_SHA, slots,
            authenticate_batch=partial(reader.verify_saved_batch, client=client), verify_registry=True,
            prefetch_blobs=True)
    selected, legacy_late = {}, {}
    if legacy:
        verified, origin = legacy
        manifest = verified['manifest']
        eligible = set(origin['eligible_slots'])
        need(not eligible.intersection(additional), 'DUPLICATE_FIRST_SLOT')
        need(eligible <= slots.keys(), 'REGISTRY_LINEAGE')
        selected = {entry['slot_sha256']: dict(entry=entry, manifest=manifest, cipher_path=None)
                    for entry in manifest['entries'] if entry['slot_sha256'] in eligible}
        legacy_late = origin['held_slots']
    legacy_count = len(selected)
    selected.update(additional)
    sources, loaded = {}, {}
    with _stage('REGISTRY_REPLAY_UNVERIFIED'):
        for candidate in selected.values():
            manifest = candidate['manifest']
            summary = manifest['summary']
            run, commit = summary['reader_run_id'], summary['source_archive_commit']
            if run not in sources:
                if commit not in loaded:
                    loaded[commit] = records.RecordStore(work, day, index_commit=commit)
                source = loaded[commit]
                original_registry = _load_registry(source, private, manifest)
                need(set(original_registry['registered_race_ids']) <= race_set, 'REGISTRY_LINEAGE')
                sources[run] = source
    if progress is not None:
        progress('OFFICIAL_INPUT_PREFETCH_STARTED')
    prefetch = records.prefetch_original_sources(current, races)
    if progress is not None:
        progress('OFFICIAL_INPUT_PREFETCH_' + prefetch)
    entries, pinned_originals = [], {}
    cache, history_sources, history_controls, back_pairs, back_holds = {}, {}, {}, {}, {}
    personal_pairs, personal_holds = {}, {}
    codex_report = None
    if codex_repo is not None:
        try:
            codex_report = _prepare_codex_pair(work=work, current=current, private=private, repo=codex_repo,
                client=client, slots=slots, dt_selected=selected, loaded=loaded, packet_cache=cache)
        except SettlementError as error:
            state = 'HOLD_' + error.reason
            codex_report = lambda *_: dict(state=state, formal_three_way_races=0)
        except Exception:
            codex_report = lambda *_: dict(state='HOLD_CODEX_PAIR_REPLAY_UNVERIFIED', formal_three_way_races=0)
        if progress is not None:
            progress('CODEX_REPLAY_FINISHED')
    feature_rows = {} if feature_audit is not None else None
    personal_failed = False
    for slot, rid in slots.items():
        if slot in selected:
            candidate = selected[slot]
            entries.append(candidate['entry'])
            run = candidate['manifest']['summary']['reader_run_id']
            pinned_originals[rid] = sources[run].index['originals'][rid]
            continue
        reason = ('SAVED_ORIGINAL_MISSING' if rid not in current.index['originals'] else
                  legacy_late.get(slot, 'NO_RETAINED_FIRST_T15_ORIGINAL'))
        entries.append(dict(slot_sha256=slot, state='HOLD', reason=reason))

    def add_personal(**inputs):
        nonlocal personal_failed
        if not personal_failed:
            try:
                personal_study.add(**inputs)
            except Exception:
                personal_failed = True

    def report_personal(admitted, outcomes):
        need(not personal_failed, 'PERSONAL_HISTORY_RESEARCH_FAILED')
        return personal_study.report(admitted, outcomes)

    def forecast_loader(entry, rid):
        candidate = selected[entry['slot_sha256']]
        manifest = candidate['manifest']
        path = candidate['cipher_path']
        if path is None:
            raw = (Path(legacy[0]['directory']) / entry['cipher']['file']).read_bytes()
        else:
            raw = archive.read_blob_bytes(work, current.head, path,
                                         max_bytes=batch_retention.MAX_ARCHIVE_BYTES + 1)
        source = sources[manifest['summary']['reader_run_id']]
        return _forecast_from_original(entry, raw, manifest, source, rid, private, trained, venues, client, cache,
                                       history_sources=history_sources, history_controls=history_controls,
                                       back_trial=back_trial, back_pairs=back_pairs, back_holds=back_holds,
                                       feature_rows=feature_rows,
                                       personal_add=add_personal if personal_study is not None else None,
                                       personal_pairs=personal_pairs, personal_holds=personal_holds)

    def prepare_result_reads():
        if progress is not None:
            progress('DT_REPLAY_FINISHED')
        _prefetch_result_ciphers(current, races)

    result = _score_registered(races, day, entries, [slot for slot in slots if slot in selected], {},
        forecast_loader, lambda rid: _result_row(current, rid, private, pinned_originals.get(rid), now()),
        history_controls=history_controls, back_pairs=back_pairs, back_holds=back_holds,
        personal_pairs=personal_pairs, personal_holds=personal_holds,
        personal_report=report_personal if personal_study is not None else None, codex_report=codex_report,
        prefetch_results=prepare_result_reads)
    if progress is not None:
        progress('RESULT_REPLAY_FINISHED')
    if feature_audit is not None:
        for row, original in feature_rows.values():
            try:
                feature_audit.add(row, original)
            except (KeyError, TypeError, ValueError):
                # Keep an unclassified feature row out of the diagnostic only.
                continue
        audit = feature_audit.report()
        result['feature_audit'] = dict(audit,
            unaudited_replayed_races=result['owner_originals_replayed'] - audit['audited_races'])
    return dict(result, day_inventory_complete=registry['day_inventory_complete'],
                missing_venues=len(registry['missing_venues']),
                timed_originals=dict(legacy=legacy_count, additional=len(additional)),
                authenticated_batch_count=len(sources))


def _legacy_batch(work, tip, client, contexts):
    with _stage('PRODUCER_AUTHENTICATION_FAILED'):
        verified = contexts.enter_context(reader.verified_producer(PRODUCER, client=client))
    with _stage('RETENTION_AUTHENTICATION_FAILED'):
        retention = read_legacy_first_retention(work, tip, verified, model_sha256=shadow.MODEL_SHA)
    with _stage('READBACK_AUTHENTICATION_FAILED'):
        origin = reader.verify_readback(verified, READER, client=client)
    manifest = verified['manifest']
    need(manifest['summary']['source_archive_commit'] == PARENT and
         manifest['summary']['day_jst'] == DAY and
         origin['manifest_sha256'] == retention['manifest_sha256'], 'BATCH_PIN')
    return verified, origin, retention


def _lazy_back_trial(contexts, repo, root, private):
    restored = None
    attempted = False

    def restore():
        nonlocal restored, attempted
        if not attempted:
            attempted = True
            restored = contexts.enter_context(back_official_shadow.restored_candidate(
                Path(repo) / BACK_RECEIPT, root, owner_private_pem=private))
        need(callable(restored), 'BACK_STUDY_RESTORE_UNVERIFIED')
        return restored

    return restore


def run_settlement(*, repo, private_root, owner_public_pem, owner_private_pem, day=DAY,
                   archived_day=False, compare_personal_history=False, compare_codex=False,
                   now=continuation.now_utc, progress=None):
    with _stage('PROTECTED_RUNTIME_UNVERIFIED'):
        repo, root, day, _, commit = continuation._runtime(repo=repo, private_root=private_root,
            owner_public_pem=owner_public_pem, owner_private_pem=owner_private_pem, day=day,
            clock=now, mode='study')
    need(archived_day or day == DAY, 'FIRST_BATCH_ONLY')
    need(not compare_personal_history or archived_day, 'PROFILE_STUDY_REQUIRES_EXPLICIT_DAY')
    need(not compare_codex or archived_day, 'CODEX_PAIR_REQUIRES_EXPLICIT_DAY')
    with _stage('FROZEN_MODEL_UNVERIFIED'):
        trained, venues = shadow.load_frozen(repo)
    client = GitHubEvidenceClient()
    with TemporaryDirectory(prefix='dt-settle-', dir=root) as tmp, ExitStack() as contexts:
        work = Path(tmp)
        with _stage('ARCHIVE_FETCH_UNVERIFIED'):
            archive._cmd(work, 'init', '--quiet', '--template=')
            archive._cmd(work, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
            archive._cmd(work, 'config', '--local', 'remote.origin.promisor', 'true')
            archive._cmd(work, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
            tip = records.fetch_partial_head(work, with_ancestry=True)
        legacy = _legacy_batch(work, tip, client, contexts) if day == DAY else None
        with _stage('REGISTRY_REPLAY_UNVERIFIED'):
            current = records.RecordStore(work, day, index_commit=tip)
        if archived_day:
            if progress is not None:
                progress('ARCHIVE_LOADED')
            personal = None
            if compare_personal_history:
                from research.chatgpt_dt_r1.official_personal_study import OfficialPersonalStudy
                personal = OfficialPersonalStudy(trained, venues)
            result = _score_archived_day(work, current, owner_private_pem, trained, venues,
                                         client, now, legacy[:2] if legacy else None,
                                         back_trial=_lazy_back_trial(contexts, repo, root, owner_private_pem),
                                         feature_audit=OfficialFeatureAudit(trained), personal_study=personal,
                                         codex_repo=repo if compare_codex else None, progress=progress)
            scope_fields = dict(schema=DAY_SCHEMA, scope=DAY_SCOPE)
        else:
            verified, origin, retention = legacy
            manifest = verified['manifest']
            with _stage('REGISTRY_REPLAY_UNVERIFIED'):
                source = records.RecordStore(work, day, index_commit=PARENT)
                races = _load_registry(source, owner_private_pem, manifest)['registered_race_ids']
                latest = _load_registry(current, owner_private_pem)['registered_race_ids']
                need(set(races) <= set(latest), 'REGISTRY_LINEAGE')
            cache = {}
            result = _score_registered(races, day, manifest['entries'], origin['eligible_slots'],
                origin['held_slots'], lambda e, rid: _forecast_from_original(e,
                    (Path(verified['directory']) / e['cipher']['file']).read_bytes(),
                    manifest, source, rid, owner_private_pem, trained, venues, client, cache),
                lambda rid: _result_row(current, rid, owner_private_pem, source.index['originals'].get(rid), now()))
            scope_fields = dict(schema=SCHEMA, scope=FIRST_SCOPE, retention=retention, producer_run_id=PRODUCER,
                independent_readback_run_id=READER, independent_server_evidence_at=origin['latest_server_evidence_at'],
                minimum_margin_seconds=origin['minimum_margin_seconds'], latest_registry_races=len(latest),
                added_after_frozen_registry=len(set(latest) - set(races)))
        return dict(**scope_fields, day_jst=day,
            state='DT_OFFICIAL_RESULTS_SCORED' if result['metrics']['predicted_evaluable']
                  else 'HOLD_NO_VERIFIED_PREDICTED_RESULT',
            **result, result_archive_commit=tip,
            reader_code_commit=commit, reader_run_id=os.environ['GITHUB_RUN_ID'],
            video_required=False, provider_source_requests=0, state_writes=0,
            training_runs=0, new_forecasts=0, formal_three_way_races=0,
            confidence='HOLD', payout_evaluation='NOT_RUN', production_promoted=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--owner-public-pem', type=Path, required=True)
    parser.add_argument('--day', help='Explicit JST day to settle all registered slots')
    parser.add_argument('--compare-personal-history', action='store_true',
                        help='In-memory retrospective comparison on that explicit day')
    parser.add_argument('--compare-codex', action='store_true', help='Score both independently retained first originals')
    args = parser.parse_args(argv)
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()

    def report_stage(stage):
        print(f'DT_R1_SETTLEMENT_STAGE {stage}', file=sys.stderr, flush=True)

    try:
        report = run_settlement(repo=args.repo, private_root=args.private_root,
            owner_public_pem=args.owner_public_pem, owner_private_pem=private,
            day=args.day if args.day is not None else DAY, archived_day=args.day is not None,
            compare_personal_history=args.compare_personal_history, compare_codex=args.compare_codex,
            progress=report_stage)
    except Exception as error:
        reason = (error.reason if isinstance(error, SettlementError)
                  else 'RUNTIME_OR_ORIGINAL_AUTHENTICATION_FAILED')
        report = dict(schema=DAY_SCHEMA if args.day is not None else SCHEMA,
            scope=DAY_SCOPE if args.day is not None else FIRST_SCOPE,
            state='HOLD_SETTLEMENT_RUNTIME_OR_ORIGIN_UNVERIFIED', registered_races=None,
            reason=reason, production_promoted=False,
            formal_three_way_races=0, provider_source_requests=0, state_writes=0)
    finally:
        private = b''
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['state'] == 'DT_OFFICIAL_RESULTS_SCORED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
