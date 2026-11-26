"""Adapt a privately preserved joint comparison to the existing forward scorer.

No forecasts are generated, promoted, edited or sent over the network. The caller
supplies the externally anchored plaintext SHA and trusted publication/witness
receipts. Cipher-only readback does not authenticate the plaintext independently.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import fsum
from pathlib import Path
import re

from race_ai.keirin_joint_forecast import validate_forecast
from race_ai.keirin_nationwide_auto_generator import canonical, digest, when
from race_ai import keirin_paired_measurement as measured
from scripts import keirin_forward_score as forward
from scripts.keirin_generate_result_unread_analysis import check_no_result_fields

MAX_BYTES = 64 * 1024 * 1024
SEMANTICS = 'POST_CUTOFF_DERIVED_SCORING_VIEW_FOR_MATCHED_RACES_NOT_FROZEN_ORIGINAL'


def _need(condition, code):
    if not condition:
        raise ValueError('KEIRIN_JOINT_FORWARD_' + code)


def _hash(value, size=64):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value) is not None


def _pairs(items):
    out = {}
    for key, value in items:
        _need(key not in out, 'DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def _json(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'INPUT_BYTES')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: _need(False, 'NONFINITE_JSON'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('KEIRIN_JOINT_FORWARD_JSON_INVALID') from None


def _entry(note, path):
    value = note['files'].get(path)
    _need(type(value) is dict and type(value.get('text')) is str and
          type(value.get('bytes')) is int and _hash(value.get('sha256')), 'ENTRY_REQUIRED')
    raw = value['text'].encode('utf-8')
    _need(len(raw) == value['bytes'], 'ENTRY_BYTES')
    _need(sha256(raw).hexdigest() == value['sha256'], 'ENTRY_SHA256')
    return _json(raw), value['sha256']


def _cohort(document, expected):
    _need(type(document) is dict and type(document.get('races')) is list and
          0 < len(document['races']) <= 300, 'COHORT_ROWS')
    rows = {}
    for row in document['races']:
        _need(type(row) is dict and type(row.get('race_id')) is str and
              row['race_id'] not in rows, 'COHORT_DUPLICATE')
        rows[row['race_id']] = row
    _need(set(rows) == expected, 'COHORT_MISMATCH')
    return rows


def _identities(riders):
    _need(type(riders) is list, 'RIDER_IDENTITY')
    out = {}
    for rider in riders:
        _need(type(rider) is dict and type(rider.get('car')) is int and
              rider['car'] not in out and type(rider.get('name')) is str, 'RIDER_IDENTITY')
        out[rider['car']] = (rider['name'], rider.get('registration'))
    return out


def _ranked(record, market, cap):
    return [row['order'][:] for row in sorted(record[market],
            key=lambda row: (-row['probability'], row['order']))[:cap]]


def _measurement(old, new, matched, outcomes, result_states, witness):
    """Summarize frozen comparable orders and agreed observed returns."""
    market_specs = dict(trifecta_top1=('trifectas', 1), trifecta_top4=('trifectas', 4),
                        trifecta_top8=('trifectas', 8), exacta_top2=('exactas', 2),
                        top3_set_top1=('sets', 1))
    markets = {market: [] for market in market_specs}
    issue_states = defaultdict(int)
    errors = [{name: [] for name in ('rider_top1', 'rider_top2', 'rider_top3',
                                    'trifecta_order', 'exacta_order')} for _ in measured.ARMS]
    subgroup_market = {key: defaultdict(lambda: defaultdict(list)) for key in ('field_size', 'venue_code')}
    published_t15 = 0
    for rid, order in matched.items():
        winner = tuple(order)
        reference = outcomes[rid]['comparison']
        cutoff = when(old[rid]['cutoff_at'])
        published_t15 += when(witness['observed_at']) <= cutoff - timedelta(minutes=15)
        records = (old[rid], new[rid])
        distributions = {key: tuple(measured.distribution(record, key) for record in records)
                         for key in ('trifectas', 'exactas')}
        distributions['sets'] = tuple(measured.top3_sets(values) for values in distributions['trifectas'])
        for name, (key, points) in market_specs.items():
            target, payout = {
                'trifectas': (winner, reference['payouts_100yen']['3t']),
                'exactas': (winner[:2], reference['payouts_100yen']['2t']),
                'sets': (tuple(sorted(winner)), None),
            }[key]
            row = measured.observe_market(rid, cutoff, points, distributions[key], target, payout)
            if row is None:
                issue_states[name] += 1
                continue
            markets[name].append(row)
            if name in measured.PRIMARY:
                subgroup_market['field_size'][str(len(old[rid]['cars']))][name].append(row)
                subgroup_market['venue_code'][rid[8:10]][name].append(row)
        for side, record in enumerate(records):
            for name, key, target in (('trifecta_order', 'trifectas', winner), ('exacta_order', 'exactas', winner[:2])):
                errors[side][name].append(measured.distribution_score(distributions[key][side], target))
            for rank in (1, 2, 3):
                top = winner[:rank]
                errors[side][f'rider_top{rank}'].extend(
                    measured.binary_score(fsum(rider['rank_probabilities'][:rank]), rider['car'] in top)
                    for rider in record['riders'])
    return dict(schema='KEIRIN_PAIRED_MEASUREMENT_V1', result_authority='TWO_SOURCE_PUBLISHED_REFERENCE',
                coverage=dict(registered=len(old), matched_results=len(matched),
                              held_result_or_refund_review=result_states.get('held', 0),
                              pending_results=result_states.get('pending', 0),
                              missing_results=result_states.get('missing', 0),
                              matched_pairs_with_published_t15_witness=published_t15,
                              official_t15_matched_pairs=0,
                              official_t15_progress={str(target): False for target in measured.MILESTONES}),
                adoption_status='HOLD_RESEARCH_REFERENCE_ONLY',
                interval_scope='EXPLORATORY_NOMINAL_WILSON_RACES_UNCLUSTERED',
                log_probability_floor=measured.LOG_FLOOR,
                markets={k: dict(**measured.summarize_market(values, k),
                                 insufficient_distinct_orders_pairs=issue_states[k])
                         for k, values in markets.items()},
                probability_scores={side: {k: measured.average_scores(values) for k, values in errors[index].items()}
                                    for index, side in enumerate(measured.ARMS)},
                subgroups={axis: {key: {name: measured.summarize_market(markets_[name], name, detail=False)
                                        for name in measured.PRIMARY} for key, markets_ in sorted(groups.items())}
                           for axis, groups in subgroup_market.items()},
                unavailable=['COMPLETE_OBSERVED_FINISH_ORDER', 'OFFICIAL_SALES_CUTOFF', 'OFFICIAL_PAYOUT_REVISION',
                             'MARKET_BENCHMARK', 'STARTER_REFUND_AFFECTED_TICKETS',
                             'INDEPENDENT_VERIFIED_RACE_FLOW', 'MEETING_GRADE_ROUND_SUBGROUPS'])


def _publication(note, publication, witness, expected_sha, now):
    _need(type(publication) is dict and publication.get('schema') ==
          'KEIRIN_JOINT_COMPARISON_FREEZE_RECEIPT_V1', 'PUBLICATION_SCHEMA')
    if 'original_note_sha256' in publication:
        _need(publication['original_note_sha256'] == expected_sha, 'NOTE_SHA256_RECEIPT')
    _need(publication.get('pre_cutoff_git_readback') is True and
          publication.get('private_plaintext_uploaded') is False and
          publication.get('production_weights_promoted') is False, 'PUBLICATION_SCOPE')
    ids = publication.get('race_ids')
    _need(type(ids) is list and ids and len(ids) <= 300 and
          all(type(rid) is str and re.fullmatch('20[0-9]{10}', rid) for rid in ids) and
          len(set(ids)) == len(ids) and type(publication.get('races')) is int and
          publication['races'] == len(ids), 'COHORT_RECEIPT')
    _need(type(publication.get('cutoffs')) is dict and set(publication['cutoffs']) == set(ids), 'COHORT_CUTOFFS')
    archive = publication.get('publication')
    _need(type(archive) is dict and archive.get('state') == 'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED' and
          _hash(archive.get('source_commit'), 40) and _hash(publication.get('cipher_sha256')), 'ARCHIVE_RECEIPT')
    _need(type(witness) is dict and witness.get('state') == 'INDEPENDENT_RUNNER_CIPHER_SHA_READBACK_VERIFIED' and
          witness.get('archive_commit') == archive['source_commit'] and
          witness.get('cipher_sha256') == publication['cipher_sha256'], 'ARCHIVE_WITNESS')
    _need(witness.get('plaintext_decrypted') is False and witness.get('private_key_used') is False and
          witness.get('formal_pre_cutoff_original_authenticated') is False, 'WITNESS_SCOPE')
    _need(type(witness.get('registered_comparison_races')) is int and witness['registered_comparison_races'] == len(ids) and
          type(witness.get('still_pre_cutoff_races')) is int and witness['still_pre_cutoff_races'] == len(ids), 'COHORT_WITNESS')
    generated = when(publication['generated_at'])
    created_text = publication.get('original_snapshot_created_at', publication['generated_at'])
    created, readback, observed = map(when, (created_text, publication['git_readback_at'], witness['observed_at']))
    _need(when(note['imported_at']) == generated, 'IMPORT_CLOCK')
    _need(generated <= created <= readback <= observed <= now, 'ARCHIVE_CLOCK_ORDER')
    _need(all(observed < when(cutoff) for cutoff in publication['cutoffs'].values()), 'WITNESS_NOT_PRE_CUTOFF')
    return set(ids), created_text, dict(repository='haji84/RACE-AI', branch='state/keirin-note-view',
        commit=archive['source_commit'], path='views/'+publication['cipher_sha256']+'.json')


def score_joint(note_raw, publication_raw, witness_raw, roster_raw, results_raw, *, expected_note_sha256, clock=None):
    """Return safe fixed-budget aggregates; never return private forecast rows."""
    _need(_hash(expected_note_sha256) and type(note_raw) is bytes and
          sha256(note_raw).hexdigest() == expected_note_sha256, 'NOTE_SHA256_MISMATCH')
    note, publication, witness = map(_json, (note_raw, publication_raw, witness_raw))
    _need(type(note) is dict and note.get('schema') == 'RACE_AI_KEIRIN_NOTE_VIEW_V1' and
          note.get('formal_model_admission') is False and note.get('production_weight_switch') is False and
          type(note.get('files')) is dict, 'NOTE_SCOPE')
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    _need(isinstance(now, datetime) and now.utcoffset() is not None, 'NORMALIZATION_CLOCK')
    now = now.astimezone(timezone.utc)
    ids, frozen_at, archive_pointer = _publication(note, publication, witness, expected_note_sha256, now)
    dates = {rid[:4]+'-'+rid[4:6]+'-'+rid[6:8] for rid in ids}
    _need(len(dates) == 1 and type(note.get('dates')) is list and dates <= set(note['dates']), 'COHORT_DATE')
    prefix = 'data/'+next(iter(dates))+'/'
    inputs, source_sha = _entry(note, prefix+'comparison_inputs.json')
    _need(inputs.get('schema') == 'RACE_AI_KEIRIN_COMPARISON_INPUTS_V1', 'SOURCE_SCHEMA')
    baseline, _ = _entry(note, prefix+'comparison_baselines.json')
    current, _ = _entry(note, prefix+'comparison_joint_originals.json')
    sources, old, new = (_cohort(value, ids) for value in (inputs, baseline, current))
    roster, outcomes = map(_json, (roster_raw, results_raw))
    entries = forward.unique_races(roster)
    _need(ids <= entries.keys(), 'COHORT_PUBLIC_ROSTER')
    forecasts = []
    for rid in sorted(ids):
        before, after, source = old[rid], new[rid], sources[rid]
        for record in (before, after):
            validate_forecast(record)
            _need(record['scope'] == 'PROSPECTIVE_RESEARCH' and
                  when(record['generated_at']) <= when(frozen_at), 'LATE_FORECAST')
            _need(record['source_packet_sha256'] == source_sha, 'SOURCE_PACKET_SHA256')
            _need(record['input_sha256'] == digest(source['input']), 'INPUT_SHA256')
        for field in ('race_id', 'input_sha256', 'model_version'):
            _need(before[field] == after[field], 'PAIRED_IDENTITY')
        for field in ('generated_at', 'cutoff_at', 'source_as_of', 'source_forecast_generated_at'):
            _need(when(before[field]) == when(after[field]), 'PAIRED_CLOCK')
        _need(set(before['cars']) == set(after['cars']) and
              _identities(before['riders']) == _identities(after['riders']), 'PAIRED_RIDER_IDENTITY')
        _need(type(source.get('input')) is dict and source['input'].get('race_id') == rid, 'INPUT_RACE_ID')
        check_no_result_fields(source['input'])
        source_cars = [rider['car'] for rider in source['input']['riders']]
        _need(len(source_cars) == len(set(source_cars)) and set(source_cars) == set(before['cars']) and
              _identities(source['roster']) == _identities(before['riders']), 'RIDER_IDENTITY')
        _need(when(source['cutoff_at']) == when(before['cutoff_at']) == when(publication['cutoffs'][rid]) and
              when(source['source_as_of']) == when(before['source_as_of']) and
              when(source['forecast_generated_at']) == when(before['source_forecast_generated_at']), 'PAIRED_SOURCE_CLOCK')
        _need(set(before['cars']) == {rider['number'] for rider in entries[rid]['observed_riders']}, 'COHORT_STARTERS')
        forecasts.append(dict(race_id=rid, cutoff_at=before['cutoff_at'], points=4,
            published=_ranked(before, 'trifectas', 8), trial=_ranked(after, 'trifectas', 8)))
    _need(when(outcomes['checked_at']) <= now, 'RESULT_CHECK_AFTER_NORMALIZATION')
    normalized = canonical(dict(schema='KEIRIN_FORWARD_PREDICTIONS_V1', races=forecasts))
    receipt = canonical(dict(schema='KEIRIN_FORWARD_RECEIPT_V1', prediction_sha256=sha256(normalized).hexdigest(),
        frozen_at=frozen_at, normalized_at=now.isoformat(), timestamp_semantics=SEMANTICS,
        original_note_sha256=expected_note_sha256, archive_pointer=archive_pointer,
        comparators=dict(published='baseline_B', trial='joint_comparison_B')))
    report = forward.score(normalized, receipt, roster_raw, results_raw)
    nested = {str(cap): dict(matched=0, tickets_per_arm=0, published_hits=0, trial_hits=0) for cap in (1, 4, 8)}
    exacta = dict(matched=0, tickets_per_arm=0, published_hits=0, trial_hits=0)
    results = forward.unique_races(outcomes)
    checked_at = when(outcomes['checked_at'])
    matched = {}
    for rid in sorted(ids):
        outcome = results.get(rid)
        if outcome is None or outcome['state'] != 'matched':
            continue
        winner = forward.confirmed_order(outcome, old[rid]['cutoff_at'], set(old[rid]['cars']), checked_at)
        matched[rid] = winner
        for cap in (1, 4, 8):
            values = nested[str(cap)]
            values['matched'] += 1
            values['tickets_per_arm'] += min(cap, len(old[rid]['trifectas']))
            for side, record in (('published', old[rid]), ('trial', new[rid])):
                values[side+'_hits'] += winner in _ranked(record, 'trifectas', cap)
        exacta['matched'] += 1
        exacta['tickets_per_arm'] += 2
        for side, record in (('published', old[rid]), ('trial', new[rid])):
            exacta[side+'_hits'] += winner[:2] in _ranked(record, 'exactas', 2)
    report.update(trifecta_by_points=nested, exacta_top2=exacta,
        measured_comparison=_measurement(old, new, matched, results, report['result_states'], witness),
        original_note_sha256=expected_note_sha256, archive_pointer=archive_pointer,
        publication_receipt_sha256=sha256(publication_raw).hexdigest(),
        independent_witness_sha256=sha256(witness_raw).hexdigest(),
        original_plaintext_authentication='PENDING_RSA_READBACK',
        derived_predictions_pre_cutoff_authenticated=False, flow_state='NO_PRE_CUTOFF_FLOW_ORIGINAL',
        formalPR71=False, accuracy_improvement_proven=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('note', 'publication', 'witness', 'roster', 'results'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--expected-note-sha256', required=True)
    args = parser.parse_args()
    try:
        report = score_joint(*(getattr(args, name).read_bytes() for name in
            ('note', 'publication', 'witness', 'roster', 'results')), expected_note_sha256=args.expected_note_sha256)
    except (ValueError, KeyError, TypeError, OSError, OverflowError):
        parser.exit(1, 'Joint forward score failed: input or evidence validation failed.\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
