"""Descriptive exact-eight audit over a caller-authenticated declared schedule.

No I/O, replay, fitting, ticket unions, source authentication, or promotion.
Normal official outcomes establish the shared denominator even without a saved
forecast. Unknown outcomes remain explicit and never become synthetic losses.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from .boat_ab_cohort import RACE_ID, wilson
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from .frozen_day_cycle import check_clock, rank_check, settle, ts
from .private_saved_comparison import _result


SPECIAL = frozenset({'CANCELLED', 'NO_CONTEST', 'NO_TRIFECTA',
    'REFUND_REVIEW_REQUIRED', 'ABNORMAL_FINISH_REVIEW_REQUIRED',
    'SPECIAL_SETTLEMENT_REVIEW_REQUIRED'})


def _official_result(race, observations, now):
    """Adapt actual observations to the existing strict result classifier.

    Its capture wrapper describes caller-supplied authenticated observations;
    it is not a fabricated forecast or an independent receipt authentication.
    Passing no selected rows allows the six official rows to establish outcome
    eligibility without pretending a forecast roster existed.
    """
    if RACE_ID.fullmatch(race['race_id']) is None:
        return 'RESULT_REJECTED', None, None
    try:
        visible = [o for o in observations if ts(o['captured_at']) <= now]
        latest = max((ts(o['captured_at']) for o in visible), default=None)
        last = [o for o in visible if ts(o['captured_at']) == latest]
        # Identical copies do not create a new result version. Different bodies
        # at the latest visible clock cannot be resolved by input ordering.
        if last and any(o != last[0] for o in last[1:]):
            return 'RESULT_CAPTURE_CONFLICT', None, None
        admitted = last[0] if last else None
        captures = [] if admitted is None else [dict(original=admitted,
            references=[dict(source_sha256=admitted.get('source_sha256'),
                scope='CALLER_AUTHENTICATED_OBSERVATION')],
            available_at_boundary=True)]
        state, selected = _result(race, captures, [], now)
        return state, selected, admitted
    except (ValueError, TypeError, KeyError, AttributeError):
        return 'RESULT_REJECTED', None, None


def _first_original(rows, race, now):
    """Select once by receipt time, never by outcome or replacement tickets."""
    valid = []; rejected = []
    for row in rows:
        try:
            if ts(row['cutoff_at']) != ts(race['cutoff_at']):
                raise ValueError('forecast/schedule cutoff mismatch')
            check_clock(row['as_of'], row['cutoff_at'], row['server_saved_at'])
            if ts(row['server_saved_at']) > now:
                raise ValueError('future forecast receipt')
            valid.append(row)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            rejected.append(str(exc)[:160])
    if not valid:
        return None, rejected[0] if rejected else 'NO_SAVED_ORIGINAL', 0
    earliest = min(ts(r['server_saved_at']) for r in valid)
    first = [r for r in valid if ts(r['server_saved_at']) == earliest]
    if any(r != first[0] for r in first[1:]):
        return None, 'CONFLICTING_FIRST_RECEIPT', len(valid)-1
    row = first[0]
    try:
        # rank_check binds all 120 permutations to the exact original first 8.
        if (len(row['top8']) != 8 or
                any(len(t) != 3 or any(type(n) is not int for n in t)
                    for tickets in (row['ranked'], row['top8']) for t in tickets)):
            raise ValueError('exact eight ordered distinct integer triples required')
        rank_check(row['ranked'], row['top8'])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return None, 'INCOMPATIBLE_ORIGINAL: '+str(exc)[:140], len(valid)-1
    return row, None, len(valid)-1


def all_race_top8_target(rows, schedule, observations, *, now, expected_models,
                         learned_rows=None):
    """Each phase/model/variant scores separately on the same normal outcomes.

    All supplied originals/results must already have been authenticated by the
    caller. The declared schedule bounds coverage; this cannot prove discovery
    of every nationwide race or a future 98% probability.
    """
    if now.utcoffset() is None:
        raise ValueError('aware target audit time required')
    groups = {('P1', mid, 'BASELINE') for mid in expected_models}
    forecast_rows = defaultdict(list)
    for variant, originals in [('BASELINE', rows), ('LEARNED_SHADOW', learned_rows or [])]:
        for row in originals:
            stage, mid = row['stage'], row['model_id']
            allowed = expected_models if variant == 'BASELINE' else set(OBSERVED)
            if stage not in ('P0', 'P1') or mid not in allowed:
                continue
            key = (stage, mid, variant); groups.add(key)
            forecast_rows[(row['race_id'], key)].append(row)
    if learned_rows is not None:
        groups.update(('P1', mid, 'LEARNED_SHADOW') for mid in OBSERVED)
    by_result = defaultdict(list)
    for observation in observations:
        by_result[observation['race_id']].append(observation)
    race_rows = []; forecasts = []; eligible_ids = []
    for race in schedule:
        rid = race['race_id']; future = ts(race['cutoff_at']) > now
        state, selected, admitted = ('FUTURE', None, None) if future else _official_result(race, by_result[rid], now)
        eligible = state == 'FINAL_NORMAL'
        if eligible:
            eligible_ids.append(rid)
        race_rows.append(dict(race_id=rid, cutoff_at=race['cutoff_at'],
            result_state=state, eligible=eligible,
            result_captured_at=selected.get('captured_at') if selected else None))
        for key in sorted(groups):
            phase, mid, variant = key
            item = dict(race_id=rid, stage=phase, model_id=mid, variant=variant,
                eligible=eligible, state=state, hit=None, issued=False)
            if eligible:
                original, reason, later = _first_original(forecast_rows[(rid,key)], race, now)
                item['later_or_duplicate_receipts'] = later
                if original is not None:
                    try:
                        verdict = settle(original, admitted)
                        if verdict['state'] not in ('HIT', 'MISS'):
                            raise ValueError('frozen settlement '+verdict['state'])
                        item.update(state=verdict['state'], issued=True,
                            hit=verdict['state']=='HIT', artifact_id=original['artifact_id'],
                            model_sha256=original['model_sha256'],
                            server_saved_at=original['server_saved_at'],
                            top8=deepcopy(original['top8']))
                        if original.get('training_sha256') is not None:
                            item['training_sha256'] = original['training_sha256']
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        reason = 'INCOMPATIBLE_ORIGINAL: '+str(exc)[:140]
                if not item['issued']:
                    item.update(state='NO_PRE_CUTOFF_FORECAST', reason=reason, hit=False)
            forecasts.append(item)
    eligible = len(eligible_ids)
    board = []
    for phase, mid, variant in sorted(groups):
        entries = [f for f in forecasts if (f['stage'],f['model_id'],f['variant']) == (phase,mid,variant) and f['eligible']]
        issued = sum(f['issued'] for f in entries); hits = sum(f['hit'] for f in entries)
        rate = hits/eligible if eligible else None
        interval = wilson(hits, eligible)
        board.append(dict(stage=phase, model_id=mid, variant=variant, eligible=eligible,
            hits=hits, issued=issued, missing=eligible-issued,
            hit_at_8_all=rate, hit_at_8_saved_only=hits/issued if issued else None,
            wilson95=dict(lower=interval[0], upper=interval[1]) if interval else None, distinct_days=len({rid[:8] for rid in eligible_ids}),
            distinct_venue_days=len({rid[:11] for rid in eligible_ids}),
            training_sha256s=sorted({f['training_sha256'] for f in entries if 'training_sha256' in f}),
            target_status='INSUFFICIENT_OUTCOMES' if rate is None else
                          'MET_OBSERVED_ONLY' if rate >= .98 else 'NOT_MET',
            target_established=False, promotion_allowed=False))
    counts = Counter(r['result_state'] for r in race_rows)
    pending = counts['RESULT_PENDING']; special = sum(counts[s] for s in SPECIAL)
    unknown = len(schedule)-counts['FUTURE']-eligible-pending-special
    return dict(target_hit_rate=.98, exact_ticket_count=8,
        denominator_scope='ENDED_SCHEDULED_OFFICIAL_FINAL_NORMAL_RACES',
        selection_policy='FIRST_PRE_CUTOFF_ORIGINAL_PER_RACE_PHASE_MODEL_VARIANT',
        scheduled_races=len(schedule), ended_races=len(schedule)-counts['FUTURE'],
        future_races=counts['FUTURE'], eligible_normal_final_races=eligible,
        pending_races=pending, unknown_races=unknown, special_races=special,
        all_schedule_completion_status='COMPLETE' if not (pending or unknown or counts['FUTURE']) else 'INCOMPLETE',
        all_schedule_completion_scope='OUTCOMES_ONLY',
        result_state_counts=dict(sorted(counts.items())), scoreboard=board,
        per_race=race_rows, per_forecast=forecasts, target_established=False,
        auto_promoted=False, statistical_scope='DESCRIPTIVE_MARGINAL_WILSON95_NOT_INDEPENDENCE_PROOF',
        limitations=['Unknown and pending outcomes are visible but cannot enter the normal-final denominator.',
            'Missing or incompatible originals contribute zero hits without being fabricated MISS forecasts.',
            'Models and variants are measured separately; their tickets are never combined.',
            'The declared schedule and caller authentication bound this audit.',
            'Schedule completion describes classified outcomes; missing forecast coverage is reported separately.',
            'An observed 98% point estimate is not proof of future accuracy; races may be correlated.'])
