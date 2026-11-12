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
                model_scored_forecasts=scored, model_pending_forecasts=pending,
                model_held_forecasts=held, model_void_forecasts=void,
                unresolved_p0_forecasts=p0_open,
                model_groups=group_report,
                official_source_requests=0, prediction_rewrites=0,
                actual_purchases=False, private_race_ids_exported=False)
