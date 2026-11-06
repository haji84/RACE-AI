"""Encrypted native paired scoring after independent artifact admission.

Every scoreboard compares baseline and learned plans within the same cell and
same scored races. Selection models retain native abstention and ticket/stake
counts. Their utilities are never presented as outcome probabilities.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import math
import re

from .actions_contract import digest
from .all_existing_model_pairs import _output, _time, partition_key, verify_private_pair
from .all_existing_model_receipt import _verified_private_pairs_artifact
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import seal_candidate
from .existing_model_dispatch import _race_key
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root

SCHEMA = 'RACE_AI_PRIVATE_ALL_EXISTING_MODEL_PDCA_V1'
RESULT_FIELDS = {'race_id', 'sport', 'status', 'ordered_top3', 'roster', 'captured_at',
                 'source_sha256', 'identity_verified', 'payout_per_100_yen', 'refund_numbers'}


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_PRIVATE_PDCA_' + reason)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _observation(observation, pair, now):
    _need(type(observation) is dict and set(observation) == RESULT_FIELDS and
          observation['sport'] == pair['sport'] and
          _race_key(observation['race_id'], pair['sport']) == _race_key(pair['race_id'], pair['sport']) and
          observation['status'] in ('settled', 'pending', 'special'), 'RESULT_IDENTITY_INVALID')
    _need(observation['identity_verified'] is True and type(observation['roster']) is dict and
          observation['roster'] == pair['baseline_normalized']['roster'] == pair['learned_normalized']['roster'],
          'RESULT_REGISTERED_ROSTER_MISMATCH')
    _need(type(observation['source_sha256']) is str and
          re.fullmatch('[a-f0-9]{64}', observation['source_sha256']), 'RESULT_SOURCE_HASH_INVALID')
    captured = _time(observation['captured_at'])
    _need(captured <= now, 'FUTURE_RESULT_SOURCE')
    if observation['status'] != 'pending':
        _need(_time(pair.get('race_cutoff_at', pair['cutoff_at'])) <= captured,
              'RESULT_BEFORE_RACE_CUTOFF')
    roster = observation['roster']; winner = observation['ordered_top3']
    _need(type(winner) is list and (len(winner) == 3 if observation['status'] == 'settled' else len(winner) in (0, 3)) and
          all(type(n) is int and str(n) in roster for n in winner) and len(winner) == len(set(winner)),
          'RESULT_ORDER_INVALID')
    refunds = observation['refund_numbers']
    _need(type(refunds) is list and all(type(n) is int and str(n) in roster for n in refunds) and
          len(refunds) == len(set(refunds)), 'RESULT_REFUNDS_INVALID')
    _need(_number(observation['payout_per_100_yen']) and observation['payout_per_100_yen'] >= 0,
          'RESULT_PAYOUT_INVALID')
    if observation['status'] == 'settled':
        _need(not set(winner).intersection(refunds), 'RESULT_WINNER_REFUNDED')


def _plan(plan, observation):
    """Score native plans; returned detail is encrypted by the caller."""
    top = plan['top']; stakes = plan['stakes']
    _need(type(top) is list and type(stakes) is list and len(top) == len(stakes) == plan['ticket_count'] and
          0 <= len(top) <= 8 and all(type(yen) is int and yen > 0 and yen % 100 == 0 for yen in stakes),
          'NATIVE_TICKET_PLAN_INVALID')
    winner = observation['ordered_top3']; refunded = set(observation['refund_numbers'])
    stake = sum(stakes); payout = 0; refund = 0; hit = False
    for ticket, yen in zip(top, stakes):
        _need(type(ticket) is list and len(ticket) == 3 and
              all(type(n) is int and str(n) in plan['roster'] for n in ticket) and len(set(ticket)) == 3,
              'NATIVE_TICKET_INVALID')
        if refunded.intersection(ticket):
            refund += yen
        elif observation['status'] == 'settled' and ticket == winner:
            hit = True; payout += observation['payout_per_100_yen']*yen/100
    loss = None
    if plan['kind'] == 'PROBABILITY' and observation['status'] == 'settled':
        ranked = plan['ranked']
        _need(type(ranked) is list and all(type(row) is dict and
              _number(row.get('score')) and 0 <= row['score'] <= 1 for row in ranked),
              'NATIVE_PROBABILITY_INVALID')
        probability = next((row['score'] for row in ranked if row['combination'] == winner), 0.0)
        loss = -math.log(max(probability, 1e-15))
    else:
        _need(plan['kind'] in ('PROBABILITY', 'SELECTION'), 'NATIVE_PLAN_KIND_INVALID')
    return dict(ticket_count=len(top), stake_yen=stake, hit=hit, payout_yen=payout,
                refund_yen=refund, net_yen=payout+refund-stake, log_loss=loss,
                selection_status=plan['selection_status'], kind=plan['kind'])


def _score_plans(baseline_plan, learned_plan, observation):
    baseline = _plan(baseline_plan, observation)
    learned = _plan(learned_plan, observation)
    # Zero-ticket selection is an abstention, never a synthetic eight-ticket miss.
    paired = baseline['ticket_count'] > 0 and learned['ticket_count'] > 0
    return dict(state=('SETTLED_PAIRED' if observation['status'] == 'settled' else 'SPECIAL_PAIRED')
                if paired else 'NATIVE_ABSTENTION_UNPAIRED', paired=paired,
                selection_plan_changed=(baseline_plan['top'] != learned_plan['top'] or
                                        baseline_plan['stakes'] != learned_plan['stakes']),
                ticket_count_changed=baseline['ticket_count'] != learned['ticket_count'],
                baseline=baseline, learned=learned)


def _score(pair, observation):
    if observation is None or observation['status'] == 'pending':
        return dict(state='PENDING_RESULT', paired=False)
    baseline = pair['baseline_normalized']; learned = pair['learned_normalized']
    result = _score_plans(baseline, learned, observation)
    if 'plans' in baseline or 'plans' in learned:
        for plan in (baseline, learned):
            _need(plan['kind'] == 'SELECTION' and type(plan.get('plans')) is dict and
                  set(plan['plans']) in (set(), {'three', 'five'}), 'NATIVE_PLAN_VARIANTS_INVALID')
            if not plan['plans']:
                # Native FILTERED/RANK_LIMIT rows carry no ticket variants.
                # Each comparison unit consequently has zero tickets/stakes.
                _need(plan['top'] == [] and plan['stakes'] == [] and plan['ticket_count'] == 0,
                      'NATIVE_ABSTENTION_PLAN_INVALID')
        variants = {}
        for name in ('three', 'five'):
            baseline_variant = dict(baseline, **baseline['plans'].get(name, {})); baseline_variant.pop('plans', None)
            learned_variant = dict(learned, **learned['plans'].get(name, {})); learned_variant.pop('plans', None)
            variants[name] = _score_plans(baseline_variant, learned_variant, observation)
        # The compatibility primary is the native five-ticket plan. Three- and
        # five-ticket economics remain separate in every returned score.
        _need(result == variants['five'], 'NATIVE_PRIMARY_PLAN_BINDING_INVALID')
        result['primary_native_plan'] = 'five'; result['native_plan_variants'] = variants
    return result


def _cohort_board(cohort):
    entry = dict(paired_forecasts=len(cohort),
        paired_cohort_sha256=digest(sorted(r['forecast_record_sha256'] for r in cohort)),
        selection_plan_changed_count=sum(r['score']['selection_plan_changed'] for r in cohort),
        native_ticket_count_changed_count=sum(r['score']['ticket_count_changed'] for r in cohort))
    for arm in ('baseline', 'learned'):
        values = [r['score'][arm] for r in cohort]; stake = sum(v['stake_yen'] for v in values)
        payout = sum(v['payout_yen'] for v in values); refund = sum(v['refund_yen'] for v in values)
        losses = [v['log_loss'] for v in values if v['log_loss'] is not None]
        entry[arm] = dict(forecasts=len(values), ticket_count=sum(v['ticket_count'] for v in values),
            hits=sum(v['hit'] for v in values), stake_yen=stake, payout_yen=payout, refund_yen=refund,
            net_yen=payout+refund-stake, roi=(payout+refund)/stake if stake else None,
            probability_scored_forecasts=len(losses), mean_log_loss=sum(losses)/len(losses) if losses else None)
    return entry


def _aggregate(rows):
    boards = {}
    for cell in sorted({r['cell_key'] for r in rows}):
        cell_rows = [r for r in rows if r['cell_key'] == cell]
        entry = _cohort_board([r for r in cell_rows if r['score']['paired']])
        variant_names = {name for row in cell_rows for name in row['score'].get('native_plan_variants', {})}
        if variant_names:
            entry['primary_native_plan'] = 'five'; variants = {}
            for name in sorted(variant_names):
                cohort = [dict(row, score=row['score']['native_plan_variants'][name]) for row in cell_rows
                          if name in row['score'].get('native_plan_variants', {}) and
                          row['score']['native_plan_variants'][name]['paired']]
                variants[name] = _cohort_board(cohort)
            entry['native_plan_variants'] = variants
        boards[cell] = entry
    return boards


def _summary(admission, rows, observation_count):
    paired = [r for r in rows if r['score']['paired']]
    return dict(schema='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_PDCA_COUNTS_V1',
        state='PRIVATE_NATIVE_PDCA_SCORED' if paired else 'PRIVATE_NATIVE_PDCA_PENDING' if rows else
              'FROZEN_NATIVE_INPUTS_NO_FORECASTS',
        scope=admission['scope'],
        partition_count=len(rows), baseline_forecast_count=len(rows), learned_forecast_count=len(rows),
        paired_forecasts=len(paired), observation_count=observation_count,
        result_state_counts=dict(Counter(r['score']['state'] for r in rows)),
        scoreboard=_aggregate(rows), source_artifact_id=admission['artifact_id'],
        source_artifact_digest=admission['artifact_digest'], source_workflow_run_id=admission['workflow_run_id'],
        source_head_sha=admission['head_sha'], training_sha256=admission['training_sha256'],
        independent_pre_cutoff_receipt_verified=True, paired_cohorts_within_cells_only=True,
        cross_model_equal_cohort_comparison_claimed=False, provider_permission_confirmed=False,
        baseline_coefficients_changed=False, production_promoted=False, actual_purchases=False,
        accuracy_improvement_proven=False, plaintext_published=False)


def verify_private_pdca(payload):
    """Replay one private scoring partition after owner-key authenticated readback."""
    try:
        fields = {'schema', 'evaluated_at', 'training', 'summary', 'source_artifact',
                  'private_forecast', 'observation', 'score'}
        _need(type(payload) is dict and set(payload) == fields and payload['schema'] == SCHEMA,
              'PAYLOAD_SCHEMA_INVALID')
        forecast = payload['private_forecast']; verify_private_pair(forecast)
        _need(payload['training'] == forecast['training'], 'TRAINING_BINDING_INVALID')
        now = _time(payload['evaluated_at']); admission = payload['source_artifact']
        _need(admission.get('independent_pre_cutoff_receipt_verified') is True and
              digest(forecast) in admission['record_sha256'] and
              admission['training_sha256'] == forecast['training']['training_sha256'],
              'SOURCE_ADMISSION_BINDING_INVALID')
        observation = payload['observation']; pair = forecast['pair']
        if observation is not None:
            _observation(observation, pair, now)
        row = dict(cell_key=pair['cell_key'], forecast_record_sha256=digest(forecast),
                   score=_score(pair, observation))
        _need(payload['score'] == row and payload['summary'] == _summary(
              admission, [row], int(observation is not None)), 'SCORE_REPLAY_MISMATCH')
        return True
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('ALL_MODEL_PRIVATE_PDCA_PAYLOAD_INVALID') from exc


def _score_verified_private_pairs(admission, records, observations, output, *, now):
    """Private boundary for records returned by the authenticated archive reader."""
    root = _output(output)
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(admission) is dict and admission.get('independent_pre_cutoff_receipt_verified') is True and
          type(records) is list and records and admission.get('record_sha256') == [digest(p) for p in records],
          'AUTHENTICATED_FORECASTS_REQUIRED')
    # Validate the complete admitted set before separating source-only inputs.
    from .all_existing_model_pairs import verify_private_record
    for record in records:verify_private_record(record)
    forecasts=[record for record in records if 'pair' in record]
    _need(type(observations) in (list, tuple), 'RESULTS_INVALID')
    by_race = {}
    for observation in observations:
        _need(type(observation) is dict and type(observation.get('sport')) is str and
              type(observation.get('race_id')) is str, 'RESULTS_INVALID')
        key = (observation['sport'], _race_key(observation['race_id'], observation['sport']))
        _need(key not in by_race, 'DUPLICATE_RESULT_REVISION')
        by_race[key] = deepcopy(observation)
    rows = []; keys = set()
    for payload in forecasts:
        verify_private_pair(payload)  # Same native payload, parameters, plans and source clocks.
        pair = payload['pair']; key = partition_key(pair)
        _need(key not in keys, 'DUPLICATE_CELL_RACE'); keys.add(key)
        observation = by_race.get((pair['sport'], _race_key(pair['race_id'], pair['sport'])))
        if observation is not None:
            _observation(observation, pair, now)
        rows.append(dict(cell_key=pair['cell_key'], forecast_record_sha256=digest(payload),
                         score=_score(pair, observation)))
    _need(set(by_race).issubset({(p['pair']['sport'], _race_key(p['pair']['race_id'], p['pair']['sport']))
                               for p in forecasts}),
          'UNRELATED_RESULT')
    summary = _summary(admission, rows, len(observations))
    root.mkdir(parents=True, mode=0o700, exist_ok=False); private_root(root)
    for forecast, row in zip(forecasts, rows):
        pair = forecast['pair']; observation = by_race.get((pair['sport'], _race_key(pair['race_id'], pair['sport'])))
        payload = dict(schema=SCHEMA, evaluated_at=now.isoformat(), training=deepcopy(forecast['training']),
            summary=_summary(admission, [row], int(observation is not None)),
            source_artifact=deepcopy(admission), private_forecast=deepcopy(forecast),
            observation=observation, score=deepcopy(row))
        verify_private_pdca(payload)
        result = seal_candidate(payload, root/partition_key(pair))
        _need(result.get('encrypted_readback_verified') is True, 'PARTITION_READBACK_FAILED')
    summary['encrypted_readback_verified'] = True
    _write(root/'summary.json', _bytes(summary))
    return summary


def score_private_pairs_artifact(raw, metadata, observations, output, *, now,
                                 expected_run_id, expected_head_sha):
    """Authenticate the complete archive, then save encrypted per-cell scores."""
    state_key('production')
    admission, forecasts = _verified_private_pairs_artifact(raw, metadata, now=now,
        expected_run_id=expected_run_id, expected_head_sha=expected_head_sha)
    # Frozen native inputs bootstrap unfitted families. They carry no forecast
    # and therefore cannot produce a miss, ROI, or paired-model observation.
    return _score_verified_private_pairs(admission, forecasts, observations, output, now=now)
