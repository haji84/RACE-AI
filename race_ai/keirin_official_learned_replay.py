"""Compare authenticated saved A/B with the frozen learned model on one archive day."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from subprocess import TimeoutExpired

from . import keirin_form_fall_blind_pdca as tickets
from . import keirin_nationwide_auto_generator as core
from . import keirin_official_nationwide_records as records
from . import keirin_official_paired_measurement as measurement
from . import keirin_official_run_history as history
from .keirin_github_evidence_client import GitHubEvidenceClient

SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_LEARNED_MODEL_MEASUREMENT_V1'
FROZEN_MODEL = 'docs/evidence/keirin-learned-order-20261128/model.sealed.json'
FROZEN_MODEL_SHA256 = 'ba14eb787dca7d0a6b94af4e322f5a1b85ea9e5e90d4fae84d23ed7bdca87386'
MARKETS = (1, 2, 4, 8, 9, 12)
ARMS = ('official_A', 'official_B', 'learned')
EVIDENCE_ERRORS = (ValueError, KeyError, TypeError, OSError, TimeoutExpired)


def load_candidate(repo, private, day):
    from . import keirin_learned_order as learned

    raw = (Path(repo) / FROZEN_MODEL).read_bytes()
    records.need(sha256(raw).hexdigest() == FROZEN_MODEL_SHA256, 'LEARNED_REPLAY_FROZEN_CANDIDATE_SHA')
    opened = history.decrypt_evidence(raw, private)
    source_sha = sha256(Path(learned.__file__).read_bytes()).hexdigest()
    manifest = opened['model']
    records.need(opened['schema'] == 'RACE_AI_KEIRIN_LEARNED_ORDER_RESEARCH_MODEL_V1' and
                 opened['safe_report']['model'] == manifest and
                 opened['safe_report']['source_files_sha256']['race_ai/keirin_learned_order.py'] == source_sha and
                 day.replace('-', '') > manifest['evaluation_window'][1], 'LEARNED_REPLAY_MODEL_SCOPE')
    trained, temperature = learned.load_frozen(manifest, opened['tree_text'])
    return trained, dict(model_id=manifest['model_id'], tree_sha256=manifest['tree_sha256'],
                         sealed_model_sha256=FROZEN_MODEL_SHA256, temperature=temperature,
                         calibration_window=manifest['calibration_window'],
                         prior_evaluation_window=manifest['evaluation_window'])


def _prepare(store, meta, private, *, client, packet_cache, started_at):
    from . import keirin_learned_official_inputs as inputs

    payload = store.read(meta, private)
    original, _ = records.admit_original(store, payload, private, origin_client=client, packet_cache=packet_cache)
    baseline = original['baseline']
    snapshot = original['snapshot']
    cutoff = core.when(meta['cutoff_at'])
    records.need(original['race_id'] == meta['race_id'] and core.when(baseline['published_cutoff_at']) == cutoff < started_at and
                 baseline['A']['model'] == core.MODEL_A and baseline['B']['model'] == core.MODEL_B,
                 'LEARNED_REPLAY_ARCHIVED_AB_IDENTITY')
    features = inputs.project(payload, original)
    cars = {row['car'] for row in snapshot['riders']}
    records.need(features['race_id'] == meta['race_id'] and {row['car'] for row in features['riders']} == cars,
                 'LEARNED_REPLAY_STARTERS')
    return features, dict(cars=sorted(cars), cutoff_at=baseline['published_cutoff_at'],
                          original_evidence_sha256=meta['evidence_sha256'],
                          official_prediction_sha256=baseline['prediction_sha256'],
                          projected_features_sha256=core.digest(features), input_availability=inputs.availability(features),
                          official_A=tickets._tickets(baseline['A'], cars),
                          official_B=tickets._tickets(baseline['B'], cars))


def _predict(candidate, inputs):
    from . import keirin_learned_order as learned

    trained, manifest = candidate
    contexts = [learned.context(card) for card in inputs]
    for joint in learned.predict(trained, contexts, temperature=manifest['temperature']):
        yield [dict(order=order, probability=probability) for order, probability in
               sorted(joint.trifectas().items(), key=lambda value: (-value[1], value[0]))]


def _settle(store, meta, result, private, forecast):
    original, scored, _ = records._replay_saved_result(store, meta, result, private)
    extracted = measurement._result_measurements(original, scored)
    if extracted is None:
        return None
    cutoff, monetary, winners, arms, _ = extracted
    official = scored['official_result']
    records.need(cutoff == core.when(forecast['cutoff_at']) < core.when(official['observed_at']) <= core.when(result['observed_at']) and
                 original['baseline']['prediction_sha256'] == forecast['official_prediction_sha256'] and
                 arms['A'] == forecast['official_A'] and arms['B'] == forecast['official_B'] and winners,
                 'LEARNED_REPLAY_RESULT_OR_ORIGINAL_CHANGED')
    return winners, monetary


def _metrics(rows):
    report = {}
    for points in MARKETS:
        hits, payout = Counter(), Counter()
        paired = monetary_count = 0
        for scores, winners, monetary in rows:
            if any(len(ranking) < points for ranking in scores.values()):
                continue
            paired += 1
            monetary_count += monetary
            for arm, ranking in scores.items():
                hits[arm] += any(order in winners for order in ranking[:points])
                if monetary:
                    payout[arm] += sum(winners.get(order, 0) for order in ranking[:points])
        stake = 100 * points * monetary_count
        arms = {arm: dict(hits=hits[arm], rate=hits[arm] / paired if paired else None,
                          virtual_payout_yen=payout[arm], virtual_return_rate=payout[arm] / stake if stake else None)
                for arm in ARMS}
        report[f'trifecta_top{points}'] = dict(races=paired, shorter_saved_ranking=len(rows) - paired, arms=arms,
                                               payout_paired_races=monetary_count, virtual_stake_yen_per_arm=stake)
    return report


def run(store, private, candidate, *, clock, freeze, requested_race_ids=None):
    """Produce and read back new forecasts before opening any archived result envelope."""
    started = clock()
    originals = store.index['originals']
    cohort = sorted(originals) if requested_race_ids is None else sorted(requested_race_ids)
    records.need(len(cohort) == len(set(cohort)) and
                 all(core.VENUE.fullmatch(rid) and rid[:8] == store.day.replace('-', '') for rid in cohort),
                 'LEARNED_REPLAY_COHORT')
    report = dict(schema=SCHEMA, day_jst=store.day, archive_index_commit=store.head,
                  archive_index_sha256=core.digest(store.index), confirmed_race_scope='RETROSPECTIVE_RESEARCH',
                  source_requests=0, exacta_scope='NO_INDEPENDENT_EXACTA_RANKING_IN_OFFICIAL_AB_ORIGINALS',
                  requested_cohort_sha256=core.digest(cohort), learned_model=candidate[1], prepared_at=started.isoformat(),
                  official_model_ids={'official_A': core.MODEL_A, 'official_B': core.MODEL_B},
                  coverage=dict(archived_originals=len(originals), requested=len(cohort)))
    client, cache, prepared, features = GitHubEvidenceClient(), {}, {}, []
    holds, availability = Counter(), Counter()
    for race_id in cohort:
        meta = originals.get(race_id)
        if meta is None:
            holds['OFFICIAL_ORIGINAL_UNAVAILABLE'] += 1
            continue
        try:
            card, prepared[race_id] = _prepare(store, meta, private, client=client, packet_cache=cache, started_at=started)
        except EVIDENCE_ERRORS:
            holds[client.stopped_reason or 'OFFICIAL_ORIGINAL_OR_ARCHIVED_INPUT_UNVERIFIED'] += 1
            continue
        features.append(card)
        availability.update(prepared[race_id].get('input_availability', {}))
    report['coverage'].update(authenticated_input_races=len(prepared), preparation_holds=dict(holds))
    report['input_availability'] = dict(availability)
    if not prepared:
        return dict(report, state='HOLD_NO_AUTHENTICATED_INPUTS')
    for row, law in zip(prepared.values(), _predict(candidate, features), strict=True):
        row['trifectas'] = law
    report['forecast_freeze'] = freeze('forecasts', dict(
        schema=SCHEMA, day_jst=store.day, observed_at=clock().isoformat(), safe_report=report, predictions=prepared))

    rows, settled, holds = [], [], Counter()
    for race_id, forecast in prepared.items():
        revisions = store.index['results'].get(race_id, [])
        if not revisions:
            holds['OFFICIAL_RESULT_UNAVAILABLE'] += 1
            continue
        try:
            result = _settle(store, originals[race_id], revisions[-1], private, forecast)
        except EVIDENCE_ERRORS:
            holds['OFFICIAL_RESULT_REPLAY_HELD'] += 1
            continue
        if result is None:
            holds['CANCELLED_OR_REFUNDED'] += 1
            continue
        winners, monetary = result
        rankings = {arm: forecast[arm] for arm in ARMS[:2]}
        rankings['learned'] = [tuple(item['order']) for item in forecast['trifectas']]
        rows.append((rankings, winners, monetary))
        settled.append(race_id)
    report['coverage'].update(comparable_results=len(rows), result_holds=dict(holds))
    report['scored_cohort_sha256'] = core.digest(settled)
    report['metrics'] = _metrics(rows)
    report['state'] = 'OFFICIAL_LEARNED_REPLAY_MEASURED' if rows else 'HOLD_NO_COMPARABLE_RESULTS'
    return report
