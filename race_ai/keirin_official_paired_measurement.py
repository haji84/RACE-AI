"""Safe day metrics from exact replay of the existing official SP archive."""
from collections import defaultdict
from datetime import timedelta
from subprocess import TimeoutExpired

from . import keirin_form_fall_blind_pdca as ticket_score
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_condition_scoring as condition_scoring
from . import keirin_official_nationwide_records as records
from . import keirin_paired_measurement as paired

SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_PAIRED_MEASUREMENT_V1'
MARKETS = {f'trifecta_top{points}':points for points in (1, 4, 8)}
COMPARISONS = {
    'baseline_A_vs_baseline_B': ('A', 'B'),
    'baseline_A_vs_conditioned_A': ('A', 'conditioned_A'),
    'baseline_B_vs_conditioned_B': ('B', 'conditioned_B'),
}
SCOPES = ('all_pre_cutoff', 'official_t15')
REPLAY_CODES = {
    'GIT_COMMAND_OR_REMOTE_UNAVAILABLE': 'ENCRYPTED_ARCHIVE_READ_HELD',
    'OFFICIAL_SP_RECORD_EVIDENCE_CIPHER_SHA': 'ENCRYPTED_ARCHIVE_READ_HELD',
    'OFFICIAL_SP_RECORD_BASELINE_ARCHIVE_LINEAGE': 'ORIGINAL_ARCHIVE_LINEAGE_HELD',
    'OFFICIAL_SP_RECORD_ORIGINAL_SOURCE_OR_MODEL_CHANGED': 'ORIGINAL_INPUT_REPLAY_HELD',
    'OFFICIAL_SP_RECORD_CONFIDENCE_PRESENCE_MISMATCH': 'ORIGINAL_INPUT_REPLAY_HELD',
    'OFFICIAL_SP_RECORD_CONFIDENCE_SOURCE_CIPHER_MISMATCH': 'ORIGINAL_INPUT_REPLAY_HELD',
    'OFFICIAL_SP_RECORD_SAVED_RESULT_NOT_REPRODUCIBLE': 'SAVED_SCORE_REPLAY_HELD',
    'GITHUB_SERVER_PRE_CUTOFF_MARGIN_NOT_PROVEN': 'PRE_CUTOFF_PROOF_HELD',
    'INDEPENDENT_REPORTS_DO_NOT_BIND_EXACT_CIPHER_SHA': 'INDEPENDENT_SHA_HELD',
    'OFFICIAL_SP_RECORD_CONDITIONED_SERVER_BINDING': 'INDEPENDENT_SHA_HELD',
}


def _observation(race_id, cutoff, points, left, right, winners, monetary):
    if min(len(left), len(right)) < points:
        return None
    first = ticket_score._score(left[:points], winners)
    second = ticket_score._score(right[:points], winners)
    return paired.MarketObservation(cutoff.isoformat(), race_id, points, (first['all_hit'], second['all_hit']),
                                    virtual_payouts_yen=(first['payout_yen'], second['payout_yen']) if monetary else None)


def _frozen_with_margin(original, scored, cutoff, use_conditioned):
    origin = scored['origin_receipts']
    pairs = [(original['baseline_sealed_at'], origin['baseline_origin']['latest_server_evidence_at'])]
    if use_conditioned:
        pairs.append((original['conditioned_sealed_at'], origin['condition_origin']['latest_server_evidence_at']))
    return all(model.when(sealed) <= cutoff - timedelta(minutes=15) and
               model.when(server) <= cutoff - timedelta(minutes=15) for sealed, server in pairs)


def _result_measurements(original, scored):
    final = scored['official_result']
    rid = original['race_id']
    records.need(final['race_id'] == rid, 'MEASUREMENT_WRONG_RESULT')
    if final['status'] != 'FINAL_NORMAL' or final['refund_status'] != 'NONE':
        return None
    cutoff = model.when(final['official_cutoff_at'])
    snapshot = original['snapshot']
    cars = {rider['car'] for rider in snapshot['riders']}
    monetary = scored['monetary_comparison_eligible'] is True
    winners = ticket_score._result(final, cars, rid) if monetary else {
        ticket_score._ticket(order, cars): 0 for order in final['winning_triples']}
    arms = {side: ticket_score._tickets(original['baseline'][side], cars) for side in ('A', 'B')}
    if original['conditioned'] is not None:
        arms.update({f'conditioned_{side}': ticket_score._tickets(
            original['conditioned'][f'{side}_research'], cars) for side in ('A', 'B')})
    groups = dict(field_size=str(len(cars)), venue_code=rid[8:10], competition=snapshot['competition'],
                  round_stage=snapshot['round_stage'], largest_line_size=str(max(map(len, snapshot['line_groups']))))
    return cutoff, monetary, winners, arms, groups


def measure_day(store, owner_private_pem, *, admit_condition_pair=None):
    """Replay only the latest revision of each official result on one pinned day."""
    index = store.index
    if index['registry'] is None:
        return dict(schema=SCHEMA, day_jst=store.day, archive_commit=store.head,
                    state='HOLD_OFFICIAL_CALENDAR_UNAVAILABLE', coverage={'official_registered_races': None})
    latest = records.replay_registry(store.read(index['registry'], owner_private_pem))
    race_ids = set(latest['registered_race_ids'])
    original_ids = set(index['originals'])
    result_ids = set(index['results'])
    records.need(latest['event_day'] == store.day and result_ids <= original_ids <= race_ids,
                 'MEASUREMENT_REGISTERED_COHORT')
    coverage = dict(official_registered_races=len(race_ids), archived_baseline_races=len(original_ids),
                    archived_result_races=len(result_ids), official_order_replay_verified_races=0,
                    official_payout_verified_races=0, official_result_replay_held_races=0,
                    archived_baseline_without_result=len(original_ids - result_ids),
                    registered_without_original=len(race_ids - original_ids), cancelled_or_refunded_result_replays=0)
    observations = {key: {scope: {market: [] for market in MARKETS} for scope in SCOPES}
                    for key in COMPARISONS}
    group_rows = {key: defaultdict(lambda: defaultdict(list)) for key in COMPARISONS}
    holds = {key: {scope: defaultdict(int) for scope in SCOPES} for key in COMPARISONS}
    condition_rows = []
    result_replay_holds = defaultdict(int)
    condition_coverage = dict(replayed_official_results=0, no_admitted_condition_pair=0,
                              attested_condition_pairs=0, pair_or_witness_held=0, official_premise_held=0)
    for rid in sorted(result_ids):
        original_meta = index['originals'][rid]
        result_meta = index['results'][rid][-1]
        try:
            original, scored, _ = records._replay_saved_result(store, original_meta, result_meta, owner_private_pem)
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired) as error:
            code = REPLAY_CODES.get(str(error), 'ARCHIVE_REPLAY_VALIDATION_HELD')
            result_replay_holds[code] += 1
            coverage['official_result_replay_held_races'] += 1
            continue
        try:
            extracted = _result_measurements(original, scored)
            if extracted is None:
                coverage['cancelled_or_refunded_result_replays'] += 1
                continue
            cutoff, monetary, winners, arms, groups = extracted
            late = {key: not _frozen_with_margin(original, scored, cutoff, use_conditioned=right.startswith('conditioned_'))
                    for key, (left, right) in COMPARISONS.items() if left in arms and right in arms}
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            result_replay_holds['FIXED_BUDGET_COMPARISON_VALIDATION_HELD'] += 1
            coverage['official_result_replay_held_races'] += 1
            continue
        coverage['official_order_replay_verified_races'] += 1
        coverage['official_payout_verified_races'] += monetary
        if admit_condition_pair is not None:
            condition_coverage['replayed_official_results'] += 1
            try:
                admitted = admit_condition_pair(store, original_meta, result_meta, owner_private_pem)
                if admitted is None:
                    condition_coverage['no_admitted_condition_pair'] += 1
                else:
                    condition_pair, witnessed_at, sealed_at = admitted
                    condition_coverage['attested_condition_pairs'] += 1
                    condition_rows.append(condition_scoring.observe(condition_pair, scored['official_result'],
                        latest_server_evidence_at=witnessed_at, sealed_at=sealed_at,
                        competition=groups['competition'], largest_line_size=int(groups['largest_line_size'])))
            except (ValueError, KeyError, TypeError, OSError, TimeoutExpired) as error:
                reason = ('official_premise_held' if str(error) ==
                          'OFFICIAL_CONDITION_SCORING_UNSUPPORTED_ALL_FINISH_NO_TIES_PREMISE'
                          else 'pair_or_witness_held')
                condition_coverage[reason] += 1
        for key, (left, right) in COMPARISONS.items():
            if key not in late:
                holds[key]['all_pre_cutoff']['no_admitted_pair'] += 1
                holds[key]['official_t15']['no_admitted_pair'] += 1
                continue
            for scope in SCOPES:
                if scope == 'official_t15' and late[key]:
                    holds[key][scope]['archive_or_readback_after_t15'] += 1
                    continue
                for market, points in MARKETS.items():
                    row = _observation(rid, cutoff, points, arms[left], arms[right], winners, monetary)
                    if row is None:
                        holds[key][scope][f'{market}_not_enough_distinct_orders'] += 1
                        continue
                    observations[key][scope][market].append(row)
                    if scope == 'official_t15' and market == 'trifecta_top4':
                        for axis, group in groups.items():
                            group_rows[key][axis][group].append(row)

    comparisons = {}
    for key, scopes in observations.items():
        comparisons[key] = {
            scope: {market: paired.summarize_market(rows, market) for market, rows in markets.items()}
            for scope, markets in scopes.items()}
        count = len(scopes['official_t15']['trifecta_top4'])
        comparisons[key].update(holds=holds[key],
            official_t15_top4_progress={str(m): count >= m for m in paired.MILESTONES},
            subgroups_t15={axis: {group: paired.summarize_market(rows, 'trifecta_top4', detail=False)
                                  for group, rows in sorted(groups.items())}
                          for axis, groups in group_rows[key].items()})
    report = dict(schema=SCHEMA, state='OFFICIAL_SP_RESULT_ARCHIVE_MEASURED',
                day_jst=store.day, archive_commit=store.head, result_authority='KEIRIN_JP_OFFICIAL_SP_REPLAY',
                coverage=coverage, comparisons=comparisons, result_replay_holds=dict(result_replay_holds),
                interval_scope='EXPLORATORY_NOMINAL_WILSON_RACES_UNCLUSTERED',
                adoption_status='HOLD_OFFICIAL_PROSPECTIVE_PRODUCT_EVALUATION_INCOMPLETE',
                unavailable=['PRE_REGISTERED_INDEPENDENT_TRIAL_ADOPTION', 'EXACTA_ORIGINALS',
                             'CALIBRATABLE_PROBABILITY_ORIGINALS', 'INDEPENDENT_VERIFIED_RACE_FLOW',
                             'MEETING_GRADE_SUBGROUPS', 'PAID_REFUND_REVISION_REPLAY'])
    if admit_condition_pair is not None:
        report['meeting_condition_trial'] = condition_scoring.summarize_day(
            store.day, condition_rows, coverage=condition_coverage)
    return report
