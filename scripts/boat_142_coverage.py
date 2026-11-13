"""Count-only AES-authenticated BOAT result / native-model coverage audit.

The caller must independently authenticate the saved view with the existing
encrypted Git reader and compute the existing official-result PDCA score.
This pure adapter never requests providers, modifies a forecast, or exports
race IDs, participant names, tickets, private URLs or the viewer key.
"""
from collections import Counter
from datetime import date
import re

SCHEMA = 'RACE_AI_BOAT_DAY_RESULT_COVERAGE_V1'
STATES = ('final', 'void', 'pending', 'missing', 'unsupported')



def _clock_or_none(value):
    from datetime import datetime
    if type(value) is not str or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _legacy_receipt_and_timing(row, result):
    """Only classify existing sealed source evidence; never set formal eligibility."""
    ref = result.get('cutoff_reference')
    if type(ref) is not dict:
        return ('RECEIPT_UNKNOWN', 'TIMING_UNKNOWN', 'MARKET_UNKNOWN')
    observations = row.get('result_observations')
    if type(observations) is not list or not observations:
        receipt = 'RECEIPT_MISSING'
        latest = None
    else:
        parsed = [(o, _clock_or_none(o.get('captured_at')))
                  for o in observations if type(o) is dict]
        if len(parsed) != len(observations) or any(t is None for _, t in parsed):
            receipt = 'RECEIPT_UNVERIFIED'
            latest = None
        else:
            latest = max(parsed, key=lambda item: item[1])[0]
            data = latest.get('data')
            matched = (type(result.get('source_sha256')) is str and
                       len(result['source_sha256']) == 64 and
                       latest.get('source_sha256') == result['source_sha256'] and
                       latest.get('captured_at') == result.get('observed_at') and
                       latest.get('body_identity_verified') is True and
                       latest.get('status') == 'AVAILABLE' and
                       type(data) is dict and data.get('confirmed') is True)
            receipt = ('MATCHED_OFFICIAL_SOURCE_BODY' if matched else
                       'RECEIPT_MISMATCH_OR_INCOMPLETE')
    data = latest.get('data') if latest is not None else None
    if receipt != 'MATCHED_OFFICIAL_SOURCE_BODY':
        market = 'MARKET_UNVERIFIED'
    elif result.get('status') == 'void':
        market = ('CANCELLED_OR_NO_CONTEST_SOURCE' if
                  data.get('status') in ('cancelled','no_contest') else
                  'MARKET_UNVERIFIED')
    elif data.get('status') != 'settled' or data.get('finish_confirmed') is not True:
        market = 'MARKET_UNVERIFIED'
    else:
        payouts = [p for p in data.get('payouts', []) if type(p) is dict
                   and p.get('bet_type') == 'trifecta'] \
            if type(data.get('payouts')) is list else []
        winners = result.get('winning_combinations')
        from_source = {tuple(p.get('combination',[])) for p in payouts
                       if type(p.get('combination')) is list and
                       len(p['combination']) == 3 and
                       type(p.get('payout_per_100_yen')) is int and
                       p['payout_per_100_yen'] >= 0}
        from_result = {tuple(c) for c in winners
                       if type(c) is list and len(c) == 3} \
            if type(winners) is list else set()
        market = ('SOURCE_WINNER_AND_PAYOUT_PRESENT' if
                  len(from_source) == len(payouts) and from_source and
                  from_source == from_result else 'MARKET_UNVERIFIED')
    prior = _clock_or_none(ref.get('original_cutoff_at'))
    source = _clock_or_none(ref.get('result_schedule_cutoff_at'))
    preds = ([row['prediction']] if row.get('prediction') is not None else []) + \
        list(row.get('comparison_predictions') or [])
    if prior is None or source is None or not preds:
        timing = 'TIMING_UNKNOWN'
    else:
        earliest, later = min(prior, source), max(prior, source)
        def _pred_early(pred):
            if type(pred) is not dict:
                return False
            fields = ('persisted_at','as_of','generated_at','source_captured_at',
                      'server_saved_at')
            stamps = [_clock_or_none(pred[k]) for k in fields if pred.get(k) is not None]
            return (pred.get('persisted_at') is not None and
                    all(t is not None and t < earliest for t in stamps))
        observed = _clock_or_none(result.get('observed_at'))
        timing = ('ALL_FORECASTS_BEFORE_BOTH_AND_RESULT_AFTER_BOTH' if
                  all(_pred_early(p) for p in preds) and
                  observed is not None and observed >= later
                  else 'TIMING_UNVERIFIED')
    return receipt, timing, market


def need(ok, code):
    if not ok:
        raise ValueError('BOAT_COVERAGE_' + code)


def summarize(view, statuses, score, *, day, expected_races, expected_p0):
    need(type(day) is str and date.fromisoformat(day).isoformat() == day,
         'DAY_INVALID')
    need(type(expected_races) is int and 1 <= expected_races <= 288,
         'RACE_TARGET_INVALID')
    need(type(expected_p0) is int and expected_p0 >= expected_races,
         'P0_TARGET_INVALID')
    need(type(view) is dict and type(view.get('records')) is list and
         view.get('dataset_status') == 'REAL_REPORTED', 'AUTHENTICATED_VIEW_REQUIRED')
    rows = [r for r in view['records'] if r.get('sport') == 'boat' and
            r.get('event_date_jst') == day]
    need(len(rows) == len(view['records']) and
         len({r['race_id'] for r in rows}) == len(rows),
         'RACE_INVENTORY_INVALID')
    need(type(statuses) is dict and set(statuses) == {r['race_id'] for r in rows},
         'STATUS_INVENTORY_INVALID')
    counts = Counter()
    unsupported_reasons = Counter()
    reference_only_gates = Counter()
    reference_only_basis = Counter()
    reference_only_offset = Counter()
    legacy_receipt_counts = Counter()
    legacy_timing_counts = Counter()
    legacy_market_counts = Counter()
    model_counts = Counter()
    saved_p0 = all_saved = 0
    for r in rows:
        status = statuses[r['race_id']]
        need(type(status) is str, 'STATUS_INVALID')
        counts[status if status in STATES else 'unsupported'] += 1
        if status == 'unsupported':
            # One count per race, not per rejected packet; do not publish
            # protected race identifiers or raw source/registration values.
            result = r.get('result') or {}
            observations = r.get('result_observation_rejections') or []
            need(type(observations) is list and len(observations) <= 256,
                 'REJECTION_LIST_INVALID')
            reasons = [item.get('reason') for item in observations
                       if type(item) is dict and type(item.get('reason')) is str
                       and re.fullmatch('[A-Z0-9_]{3,100}',item['reason'])]
            reason = (reasons[-1] if reasons else
                      'REFERENCE_ONLY_NOT_FORMAL' if result.get('status') in
                      ('final', 'void') else 'UNSUPPORTED_UNCLASSIFIED')
            unsupported_reasons[reason] += 1
            if reason == 'REFERENCE_ONLY_NOT_FORMAL':
                # Count the actual reconciliation gate without exposing
                # protected race IDs, saved references, source receipts or keys.
                # Categories are exclusive; overlapping flags use this order.
                reconciliation = result.get('cutoff_reconciliation')
                if result.get('cutoff_reference') is not None:
                    gate = 'LEGACY_CUTOFF_REFERENCE'
                elif result.get('formal_eligible') is False:
                    gate = 'EXPLICIT_FORMAL_ELIGIBLE_FALSE'
                elif (type(reconciliation) is dict and
                      reconciliation.get('formal_eligible') is False):
                    gate = 'CUTOFF_RECONCILIATION_FORMAL_FALSE'
                else:
                    gate = 'REFERENCE_GATE_UNCLASSIFIED'
                reference_only_gates[gate] += 1
                if gate == 'LEGACY_CUTOFF_REFERENCE':
                    evidence = result['cutoff_reference']
                    need(type(evidence) is dict, 'LEGACY_REFERENCE_METADATA_INVALID')
                    basis = evidence.get('basis')
                    reference_only_basis[basis if basis in (
                        'RAW_OFFICIAL_CANCELLATION_SELECTED_RACE',
                        'RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH',
                        'RAW_OFFICIAL_PAGE_SAME_ROSTER_SAVED_BEFORE_BOTH')
                        else 'OTHER_OR_MISSING_BASIS'] += 1
                    offset = evidence.get('offset_seconds')
                    if type(offset) not in (int, float) or not -86400 <= offset <= 86400:
                        bucket = 'OFFSET_MISSING_OR_INVALID'
                    elif offset == 0:
                        bucket = 'OFFSET_ZERO'
                    elif abs(offset) <= 60:
                        bucket = 'OFFSET_1_TO_60_SECONDS'
                    else:
                        bucket = 'OFFSET_OVER_60_SECONDS'
                    reference_only_offset[bucket] += 1
                    receipt, timing, market = _legacy_receipt_and_timing(r, result)
                    legacy_receipt_counts[receipt] += 1
                    legacy_timing_counts[timing] += 1
                    legacy_market_counts[market] += 1
        preds = ([r['prediction']] if r.get('prediction') is not None else []) + list(
            r.get('comparison_predictions') or [])
        need(len(preds) <= 128 and all(type(p) is dict for p in preds),
             'FORECAST_INVENTORY_INVALID')
        all_saved += len(preds)
        for p in preds:
            need(type(p.get('model_id')) is str and
                 0 < len(p['model_id']) <= 256, 'MODEL_ID_INVALID')
            if p.get('stage') == 'P0':
                saved_p0 += 1
                model_counts[p['model_id']] += 1
    need(type(score) is dict and
         score.get('schema') == 'RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1' and
         score.get('source') == 'AES_AUTHENTICATED_SAVED_VIEW_ONLY' and
         score.get('actual_purchases') is False and
         score.get('rewrote_predictions') is False and
         score.get('no_provider_requests') is True,
         'EXISTING_MODEL_SCORE_REQUIRED')
    group_report = []
    scored = held = pending = void = 0
    seen = set()
    for group in score['model_groups']:
        key = (group.get('model_id'), group.get('stage'),
               group.get('version') or '', group.get('variant') or '')
        need(key not in seen, 'DUPLICATE_MODEL_GROUP')
        seen.add(key)
        fields = ('forecasts', 'eligible', 'hits', 'misses', 'void', 'pending', 'held')
        need(all(type(group.get(k)) is int and group[k] >= 0 for k in fields),
             'MODEL_COUNT_INVALID')
        need(group['forecasts'] == group['eligible'] + group['void'] +
             group['pending'] + group['held'] and
             group['eligible'] == group['hits'] + group['misses'],
             'MODEL_ACCOUNTING_INVALID')
        unresolved = group.get('unresolved_reasons', {})
        need(type(unresolved) is dict and
             all(type(reason) is str and re.fullmatch('[A-Z0-9_]{3,100}',reason)
                 and type(count) is int and count >= 0
                 for reason,count in unresolved.items()),
             'MODEL_HOLD_REASON_INVALID')
        need(sum(unresolved.values()) == group['held'],
             'MODEL_HOLD_REASON_TOTAL_MISMATCH')
        scored += group['eligible']; held += group['held']
        pending += group['pending']; void += group['void']
        entry={k: group[k] for k in ('model_id', 'stage', *fields)}
        entry['unresolved_reasons']=dict(sorted(unresolved.items()))
        group_report.append(entry)
    need(sum(g['forecasts'] for g in group_report) == all_saved and
         score['total_forecasts'] == all_saved and
         score['total_scored'] == scored and
         score['unresolved'] == pending + held,
         'FORECAST_SCORE_INVENTORY_MISMATCH')
    p0_groups = [g for g in group_report if g['stage'] == 'P0']
    p0_open = sum(g['pending'] + g['held'] for g in p0_groups)
    need(sum(g['forecasts'] for g in p0_groups) == saved_p0,
         'P0_GROUP_INVENTORY_MISMATCH')
    need(sum(unsupported_reasons.values()) == counts['unsupported'],
         'UNSUPPORTED_REASON_COUNT_MISMATCH')
    need(sum(reference_only_gates.values()) ==
         unsupported_reasons['REFERENCE_ONLY_NOT_FORMAL'],
         'REFERENCE_GATE_COUNT_MISMATCH')
    need(sum(reference_only_basis.values()) ==
         reference_only_gates['LEGACY_CUTOFF_REFERENCE'] and
         sum(reference_only_offset.values()) ==
         reference_only_gates['LEGACY_CUTOFF_REFERENCE'],
         'REFERENCE_DETAILS_COUNT_MISMATCH')
    need(all(sum(c.values()) == reference_only_gates['LEGACY_CUTOFF_REFERENCE']
             for c in (legacy_receipt_counts, legacy_timing_counts, legacy_market_counts)),
         'LEGACY_PROOF_PARTITION_MISMATCH')
    complete = (len(rows) == expected_races and saved_p0 == expected_p0 and
                counts['final'] + counts['void'] == len(rows) and
                p0_open == 0)
    return dict(schema=SCHEMA,
                status='BOAT_142_COVERAGE_COMPLETE' if complete else
                       'BOAT_142_COVERAGE_HOLD',
                event_day=day, expected_races=expected_races,
                saved_races=len(rows), expected_p0_forecasts=expected_p0,
                saved_p0_forecasts=saved_p0, all_saved_forecasts=all_saved,
                confirmed_result_races=counts['final'] + counts['void'],
                result_status_counts={k:counts[k] for k in
                    (*STATES, 'unsupported')},
                unconfirmed_result_races=len(rows)-counts['final']-counts['void'],
                unsupported_reason_counts=dict(sorted(unsupported_reasons.items())),
                reference_only_gate_counts=dict(sorted(reference_only_gates.items())),
                legacy_reference_basis_counts=dict(sorted(reference_only_basis.items())),
                legacy_reference_offset_counts=dict(sorted(reference_only_offset.items())),
                legacy_reference_receipt_counts=dict(sorted(legacy_receipt_counts.items())),
                legacy_reference_timing_counts=dict(sorted(legacy_timing_counts.items())),
                legacy_reference_market_counts=dict(sorted(legacy_market_counts.items())),
                model_scored_forecasts=scored, model_pending_forecasts=pending,
                model_held_forecasts=held, model_void_forecasts=void,
                unresolved_p0_forecasts=p0_open,
                model_groups=group_report,
                official_source_requests=0, prediction_rewrites=0,
                actual_purchases=False, private_race_ids_exported=False)
