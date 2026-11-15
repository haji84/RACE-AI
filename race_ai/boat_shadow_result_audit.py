"""Compare the existing frozen C-lite with A/B, without generating predictions.

The caller must authenticate the ZIP/JSON SHA, artifact server clock, earliest
receipt and official result first (the existing nationwide result workflow does
so). This offline layer also checks internal hashes, identities and chronology.
No acquisition, training, promotion, retrospective reranking or purchase occurs.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import hashlib
import itertools
import json
import math
import re

AB_IDS = ('boat-display-rating-PL-reference-v1-UNVALIDATED',
          'boat-course-motor-shadow-v0.1-UNTRAINED')
C_ID = 'boat-local-start-course-shadow-v0.1-UNTRAINED'
TICKETS = {'-'.join(map(str, t)) for t in itertools.permutations(range(1, 7), 3)}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _time(value):
    _need(isinstance(value, str), 'aware timestamp required')
    out = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(out.utcoffset() is not None, 'timestamp timezone missing')
    return out


def _sealed(value, key):
    _need(isinstance(value, dict) and value.get(key) ==
          _digest({k: v for k, v in value.items() if k != key}),
          'frozen content integrity mismatch')


def _pre_receipt(generated, saved):
    return generated <= saved or (saved.microsecond == 0 and
                                  saved <= generated < saved + timedelta(seconds=1))


def _score(model, winner, payout):
    rows, picks = model.get('full_120'), model.get('top8')
    _need(isinstance(rows, list) and len(rows) == 120 and
          isinstance(picks, list) and len(picks) == 8 and picks == rows[:8],
          'complete frozen distribution and exact top8 required')
    _need(all(isinstance(x, dict) and set(x) == {'ticket', 'score'} for x in rows),
          'unexpected distribution fields')
    _need({x['ticket'] for x in rows} == TICKETS and
          all(type(x['score']) in (int, float) and math.isfinite(x['score']) and
              0 < x['score'] < 1 for x in rows) and
          math.isclose(math.fsum(x['score'] for x in rows), 1., abs_tol=1e-9) and
          rows == sorted(rows, key=lambda x: (-x['score'], x['ticket'])),
          'invalid frozen ranked distribution')
    rank = next(i + 1 for i, x in enumerate(rows) if x['ticket'] == winner)
    probability = rows[rank - 1]['score']
    tickets = [x['ticket'] for x in picks]
    slots = [set(t.split('-')[i] for t in tickets) for i in range(3)]
    flags = []
    if rank > 8:
        flags = [label for i, label in enumerate(('FIRST_SLOT_NOT_COVERED',
                 'SECOND_SLOT_NOT_COVERED', 'THIRD_SLOT_NOT_COVERED'))
                 if winner.split('-')[i] not in slots[i]]
        if any(set(t.split('-')) == set(winner.split('-')) for t in tickets):
            flags.append('CORRECT_TRIO_DIFFERENT_ORDER')
        if not flags:
            flags.append('JOINT_COMBINATION_NOT_IN_TOP8')
    return {
        'model_id': model['model_id'], 'hit_at_1': int(rank == 1),
        'hit_at_8': int(rank <= 8), 'winning_combination_rank': rank,
        'multiclass_brier': math.fsum((x['score'] - int(x['ticket'] == winner)) ** 2 for x in rows),
        'log_loss': -math.log(probability),
        'winner_model_score_uncalibrated': probability,
        'model_top8_mass_uncalibrated': math.fsum(x['score'] for x in picks),
        'virtual_stake_yen': 800,
        'virtual_payout_yen': payout if rank <= 8 else 0,
        'actual_man_shu': payout >= 10000,
        'man_shu_missed': payout >= 10000 and rank > 8,
        'observed_miss_flags': flags,
        'miss_flags_are_causal_explanations': False,
        'calibrated': False,
    }


def _one(shadow, pair, result, saved_at):
    _sealed(pair, 'bundle_sha256')
    _sealed(shadow, 'bundle_sha256')
    _need(pair.get('schema') == 'RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1' and
          pair.get('actual_result_at_forecast_time') is None,
          'original pre-result pair required')
    _need(shadow.get('schema') == 'RACE_AI_BOAT_CURRENT_FEATURE_SHADOW_V1' and
          shadow.get('model_id') == C_ID and
          shadow.get('race_id') == pair.get('race_id') == result.get('race_id') and
          shadow.get('cutoff_at') == pair.get('cutoff_at') and
          shadow.get('source_snapshot_sha256') == pair.get('source_sha256'),
          'C-lite must match the same frozen race and official input')
    _need(shadow.get('untrained') is True and shadow.get('calibrated') is False and
          shadow.get('odds_used') is False and shadow.get('auto_promoted') is False and
          shadow.get('betting_decision') == 'NO_BET', 'unsafe shadow claims')
    _need(all(isinstance(x, str) and re.fullmatch('[0-9a-f]{64}', x)
              for x in (pair.get('source_sha256'), shadow.get('extra_source_sha256'))),
          'source hashes missing')
    cutoff, saved = _time(pair['cutoff_at']), _time(saved_at)
    generated, extra_generated = _time(pair['generated_at']), _time(shadow['as_of'])
    _need(_time(pair['source_captured_at']) <= generated <= extra_generated < cutoff and
          _pre_receipt(generated, saved) and _pre_receipt(extra_generated, saved) and
          saved < cutoff <= _time(result['result_captured_at']),
          'freeze/result chronology mismatch')
    original_audit = result.get('paired_comparison', {})
    _need(original_audit.get('pair_bundle_sha256') == pair['bundle_sha256'] and
          original_audit.get('race_id') == pair['race_id'] and
          original_audit.get('cutoff_at') == pair['cutoff_at'] and
          original_audit.get('official_top3') == result.get('official_top3') and
          _time(original_audit.get('forecast_server_saved_at')) == saved,
          'independent result audit not bound to this original')
    winner, payout = result.get('official_top3'), result.get('payout_per_100_yen')
    _need(isinstance(winner, str) and winner in TICKETS and
          type(payout) is int and payout > 0, 'settled trifecta payout required')
    models = pair.get('models')
    _need(isinstance(models, list) and [m.get('model_id') for m in models] == list(AB_IDS),
          'fixed A/B model identities required')
    scores = []
    for model in models:
        _sealed(model, 'model_sha256')
        _need(model.get('trained') is False and model.get('calibrated') is False and
              model.get('odds_independent') is True and model.get('purchase_decision') == 'NO_BET',
              'fixed A/B research claims required')
        scores.append(_score(model, winner, payout))
    scores.append(_score(shadow, winner, payout))
    c = scores[2]
    differences = {old['model_id']: {key: c[key] - old[key]
        for key in ('hit_at_1', 'hit_at_8', 'multiclass_brier', 'log_loss', 'virtual_payout_yen')}
        for old in scores[:2]}
    return {'race_id': pair['race_id'], 'state': 'ABC_SAME_FROZEN_INPUT_SCORED',
            'official_top3': winner, 'payout_per_100_yen': payout,
            'server_saved_at': saved_at, 'pair_bundle_sha256': pair['bundle_sha256'],
            'c_lite_bundle_sha256': shadow['bundle_sha256'],
            'models': scores, 'c_minus_fixed_models': differences}


def compare_frozen_current_shadows(frozen, audit, saved_at):
    """Append-only comparison; caller verifies external archives and official source."""
    _need(frozen.get('schema') == 'RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
          'nationwide frozen artifact required')
    pairs, shadows, rows = (frozen.get('paired_forecasts'),
        frozen.get('additional_official_feature_shadows', []), audit.get('official_results'))
    _need(all(isinstance(x, list) for x in (pairs, shadows, rows)), 'lists required')
    def unique(items):
        out = {}
        for item in items:
            rid = item.get('race_id') if isinstance(item, dict) else None
            _need(isinstance(rid, str) and re.fullmatch(r'\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])', rid)
                  and rid not in out, 'duplicate or invalid race identity')
            out[rid] = item
        return out
    pairs_by_id, shadow_by_id, results_by_id = unique(pairs), unique(shadows), unique(rows)
    _need(set(results_by_id) <= set(pairs_by_id) and set(shadow_by_id) <= set(pairs_by_id),
          'foreign race in original or audit')
    out = []
    for rid, pair in pairs_by_id.items():
        result = results_by_id.get(rid)
        if result is None:
            out.append({'race_id': rid, 'state': 'OFFICIAL_RESULT_NOT_AUDITED'})
        elif result.get('state') != 'INDEPENDENT_AB_RESULT_VERIFIED':
            out.append({'race_id': rid, 'state': result.get('state'), 'not_scored_as_zero': True})
        elif rid not in shadow_by_id:
            out.append({'race_id': rid, 'state': 'C_LITE_NOT_FROZEN'})
        elif shadow_by_id[rid].get('state') == 'C_LITE_SOURCE_NOT_ADMITTED':
            out.append({'race_id': rid, 'state': 'C_LITE_SOURCE_NOT_ADMITTED'})
        else:
            out.append(_one(shadow_by_id[rid], pair, result, saved_at))
    return {'schema': 'RACE_AI_BOAT_FROZEN_ABC_COMPARISON_V1',
            'scope': 'SELECTED_RACES_NOT_ALL_NATIONAL',
            'comparisons': out, 'registered_forecast_count': len(pairs_by_id),
            'scored_comparison_count': sum(r['state'] == 'ABC_SAME_FROZEN_INPUT_SCORED' for r in out),
            'all_national_hit8': None, 'auto_promoted': False,
            'past_forecasts_changed': False, 'additional_official_gets': 0}
