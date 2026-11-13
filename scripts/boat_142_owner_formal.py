"""Owner-authorized, evidence-gated BOAT formal scoring of raw SP cutoff references.

Read-only reconciliation for the 2026-11-12 original 142 P0 races. Keeps the
authenticated saved ciphertext, original forecast clocks and source receipts
untouched. An in-memory scored view may omit ONLY a legacy display-only
cutoff_reference when its source and both clocks are proven. Result settlement
and refunds still use the unchanged original audited model PDCA engine.
"""
from copy import deepcopy
from datetime import datetime, date
from collections import Counter
import re

POLICY = 'BOAT_OWNER_APPROVED_SP_CUTOFF_FORMAL_V1'
DAY = '2026-11-12'
SOURCE = 'RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH'
SHA256 = re.compile(r'[a-f0-9]{64}\Z')


def need(ok, reason):
    if not ok:
        raise ValueError('BOAT_OWNER_FORMAL_' + reason)


def clock(value):
    need(type(value) is str and len(value) <= 64, 'CLOCK_REQUIRED')
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('BOAT_OWNER_FORMAL_CLOCK_INVALID') from None
    need(d.utcoffset() is not None, 'CLOCK_AWARE_REQUIRED')
    return d


def _validate_legacy(row, P):
    """Fail closed: a historical display reference is NOT itself formal evidence."""
    result = row.get('result')
    need(type(result) is dict and result.get('status') == 'final',
         'FINAL_RESULT_REQUIRED')
    need(not result.get('cutoff_reconciliation') and
         result.get('formal_eligible') is not False,
         'OTHER_NONFORMAL_GATE_PRESENT')
    ref = result.get('cutoff_reference')
    need(type(ref) is dict and ref.get('basis') == SOURCE and
         ref.get('formal_eligible') is False, 'SP_REFERENCE_SCOPE_REQUIRED')
    saved_cutoff = clock(ref.get('original_cutoff_at'))
    official_cutoff = clock(ref.get('result_schedule_cutoff_at'))
    need(row.get('cutoff_at') == ref.get('original_cutoff_at'),
         'ORIGINAL_CUTOFF_CHANGED')
    need(saved_cutoff.date() == official_cutoff.date() or
         saved_cutoff.astimezone(official_cutoff.tzinfo).date() ==
         official_cutoff.date(), 'CUTOFF_DAY_CONFLICT')
    offset = ref.get('offset_seconds')
    need(type(offset) in (int, float) and
         abs((official_cutoff - saved_cutoff).total_seconds() - offset) < 0.001,
         'CUTOFF_OFFSET_CONFLICT')
    need(abs(offset) <= 86400, 'CUTOFF_OFFSET_UNSUPPORTED')
    need(not row.get('saved_observation_cutoff_variants'),
         'UNRESOLVED_OBSERVATION_CUTOFF_CONFLICT')
    need(not row.get('result_observation_rejections'),
         'UNRESOLVED_RESULT_REJECTION')
    observations = row.get('result_observations')
    need(type(observations) is list and observations,
         'SOURCE_OBSERVATION_REQUIRED')
    need(all(type(o) is dict and o.get('race_id') == row.get('race_id')
             for o in observations), 'SOURCE_RACE_IDENTITY_MISMATCH')
    latest = max(observations, key=lambda o: clock(o.get('captured_at')))
    source_sha = result.get('source_sha256')
    need(type(source_sha) is str and SHA256.fullmatch(source_sha) is not None
         and latest.get('source_sha256') == source_sha and
         latest.get('captured_at') == result.get('observed_at') and
         latest.get('closed_at') == ref.get('result_schedule_cutoff_at') and
         latest.get('status') == 'AVAILABLE' and
         latest.get('body_identity_verified') is True,
         'LATEST_SOURCE_RECEIPT_UNVERIFIED')
    source_url = latest.get('source_url')
    need(type(source_url) is str and
         source_url.startswith('https://www.boatrace.jp/owsp/sp/spdata?') and
         latest.get('schedule_binding') == 'SP_EXPLICIT_RACE_HEADER',
         'OFFICIAL_SP_SOURCE_REQUIRED')
    body = latest.get('data')
    need(type(body) is dict and body.get('confirmed') is True and
         body.get('status') == 'settled' and
         body.get('finish_confirmed') is True,
         'OFFICIAL_SETTLEMENT_BODY_REQUIRED')
    early = min(saved_cutoff, official_cutoff)
    late = max(saved_cutoff, official_cutoff)
    need(clock(result.get('observed_at')) >= late,
         'RESULT_OBSERVED_BEFORE_BOTH_CUTOFFS')
    predictions = ([row.get('prediction')] if row.get('prediction') is not None
                   else []) + list(row.get('comparison_predictions') or [])
    need(len(predictions) == 2 and
         all(type(p) is dict and p.get('stage') == 'P0'
             for p in predictions), 'ORIGINAL_TWO_P0_MODELS_REQUIRED')
    for prediction in predictions:
        require = clock(prediction.get('persisted_at'))
        need(require < early, 'FORECAST_NOT_FROZEN_BEFORE_BOTH')
        for field in ('generated_at', 'as_of', 'source_captured_at',
                      'server_saved_at'):
            if prediction.get(field) is not None:
                need(clock(prediction[field]) < early,
                     'FORECAST_SOURCE_AFTER_CUTOFF')
        if prediction.get('cutoff_at') is not None:
            clock(prediction['cutoff_at'])
        # Original scorer retains its own per-model cutoff and pre-cutoff proof.
        P._saved_clock(prediction, row)
    return True


def score_owner_approved(view, *, F, D, P, day=DAY,
                         expected_races=142, expected_p0=284):
    """Return a strictly derived scoring view and count-only authorization proof.

    NO mutation of saved source, original forecasts, P0, Git state or public
    pages. Does not claim independent post-save verification for the derived
    artifact. The normal native scorer still handles F, L, refunds and payouts.
    """
    need(day == DAY and date.fromisoformat(day).isoformat() == day,
         'ONLY_APPROVED_DAY')
    need(type(view) is dict and view.get('dataset_status') == 'REAL_REPORTED'
         and type(view.get('records')) is list, 'AES_AUTHENTICATED_VIEW_REQUIRED')
    rows = view['records']
    need(len(rows) == expected_races and expected_races == 142 and
         expected_p0 == 284 and
         all(r.get('sport') == 'boat' and r.get('event_date_jst') == DAY
             for r in rows), 'ORIGINAL_RACE_INVENTORY_REQUIRED')
    before_forecast = F.originals_sha(view)
    before_inventory = F.inventory_sha(view)
    before_anchor = F.forecast_anchor(view)
    before = Counter(D.reconciled_status(r) for r in rows)
    need(before['final'] == 132 and before['unsupported'] == 10 and
         sum(before.values()) == expected_races,
         'EXPECTED_ORIGINAL_132_AND_TEN_REFERENCE_REQUIRED')
    working = deepcopy(view)
    approved = 0
    for row in working['records']:
        if D.reconciled_status(row) != 'unsupported':
            continue
        need(_validate_legacy(row, P), 'REFERENCE_NOT_PROVEN')
        # The ONLY data adjustment is in the scored in-memory result. Retain
        # source authenticated row in the original encrypted view unchanged.
        original_result = row['result']
        row['result'] = dict(original_result)
        row['result'].pop('cutoff_reference')
        need(D.reconciled_status(row) == 'final', 'FORMAL_GATES_NOT_RESOLVED')
        state, winnings, refunds = P._result_context(row)
        need(state == 'FINAL' and type(winnings) is dict and winnings and
             type(refunds) is set, 'ORIGINAL_SCORER_NOT_READY')
        approved += 1
    need(approved == 10, 'EXACT_TEN_APPROVAL_REQUIRED')
    need(F.originals_sha(working) == before_forecast and
         F.inventory_sha(working) == before_inventory and
         F.forecast_anchor(working) == before_anchor,
         'IMMUTABLE_P0_CHANGED')
    after = Counter(D.reconciled_status(r) for r in working['records'])
    need(after == Counter({'final':142}), 'NOT_FULLY_FORMAL')
    score = P.score_view(working, authenticated=True)
    need(score['total_forecasts'] == expected_p0 and
         score['total_scored'] == expected_p0 and
         score['unresolved'] == 0 and
         len(score['model_groups']) == 2 and
         all(g.get('forecasts') == 142 and
             g.get('eligible') + g.get('void') == 142 and
             g.get('held') == g.get('pending') == 0
             for g in score['model_groups']), 'FULL_MODEL_SCORING_NOT_VERIFIED')
    proof = dict(schema=POLICY, day=day,
                 original_confirmed=before['final'],
                 original_reference_hold=before['unsupported'],
                 owner_approved_formal_reference_races=approved,
                 accepted_result_races=after['final'],
                 model_forecasts_scored=score['total_scored'],
                 model_unresolved=score['unresolved'],
                 source_gets=0, original_prediction_rewrites=0,
                 saved_source_state_unchanged=True,
                 scoring_copy_only=True,
                 reference_evidence_preserved_in_original=True,
                 actual_purchases=False)
    return working, score, proof
