"""Pure current-day evaluation of durable research forecasts and official results.

No API, Blob SDK, SQLite, provider, money engine or storage write is imported.
Callers must read immutable objects through the storage boundary first: receipt
hashes and clocks validate supplied evidence but cannot prove a forged receipt
was actually read back from cloud storage. No model promotion is performed.
"""
from datetime import datetime, timezone
import math
import re

if __package__:
    from . import race_contract as facts
    from . import research_contract as research
else:
    import race_contract as facts
    import research_contract as research


REVIEW = 'user-confirmation-2026-10-15-official-facts'
MAX_BYTES = 256_000
KINDS = {'beforeinfo', 'odds3t', 'raceresult'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _clock(now):
    _require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None,
             'actual timezone-aware evaluation clock required')
    return now.astimezone(timezone.utc)


def _bounded(value):
    _require(0 < len(facts.canonical(value)) <= MAX_BYTES, 'evaluation input exceeds bounded JSON contract')


def _checked_prediction(value, race, now, day, closed):
    if value is None:
        return None
    fields = {'schema_version', 'request_id', 'snapshot', 'cloud_saved_at', 'cloud_eligible_pre_race', 'program_sha256'}
    _require(isinstance(value, dict) and set(value) == fields and type(value['schema_version']) is int
             and value['schema_version'] == 1 and value['cloud_eligible_pre_race'] is True,
             'durable pre-race prediction receipt required')
    _bounded(value)
    identifier = value['request_id']
    _require(isinstance(identifier, str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}', identifier) is not None,
             'invalid durable prediction request identity')
    snapshot = research.validate_research_bundle(value['snapshot'], race, now)
    saved = facts._time(value['cloud_saved_at'])
    _require(value['program_sha256'] == snapshot['program_sha256']
             and facts._time(snapshot['generated_at']) <= saved < closed and saved <= now
             and saved.astimezone(facts.JST).date() == day,
             'prediction actual cloud save must precede close and follow generation')
    return dict(receipt=value, snapshot=snapshot, proof=dict(snapshot_id=snapshot['snapshot_id'], request_id=identifier,
        as_of=snapshot['as_of'], generated_at=snapshot['generated_at'], cloud_saved_at=facts.stamp(saved),
        program_sha256=snapshot['program_sha256']))


def _checked_race_bundle(value, race, now, day, closed):
    return facts.validate_cloud_bundle(value, race, now).get('raceresult')


def _result_proof(receipt):
    if receipt is None:
        return None
    record = receipt['record']
    data = record['data'] if isinstance(record['data'], dict) else {}
    return dict(snapshot_id=record['snapshot_id'], source_url=record['source_url'], source_sha256=record['source_sha256'],
        captured_at=facts.stamp(record['captured_at']), cloud_saved_at=facts.stamp(receipt['cloud_saved_at']),
        status=data.get('status', 'PENDING'), finish_confirmed=data.get('finish_confirmed', False),
        financial_confirmed=data.get('confirmed', False),
        top3=list(data['top3']) if isinstance(data.get('top3'), list) else None)


def _scores(snapshot, truth):
    metrics = []
    for model in snapshot['models']:
        errors, winner = [], None
        for row in model['triples']:
            probability = row['probability']
            hit = row['combination'] == truth
            errors.append((probability - int(hit)) ** 2)
            if hit:
                _require(winner is None, 'duplicate realized research outcome')
                winner = probability
        _require(winner is not None and math.isfinite(winner) and 0 < winner <= 1,
                 'realized research outcome has no finite positive probability')
        brier, log_loss = math.fsum(errors), -math.log(winner)
        _require(math.isfinite(brier) and 0 <= brier <= 2 and math.isfinite(log_loss) and log_loss >= 0,
                 'research score outside finite bounds')
        metrics.append(dict(model_id=model['model_id'], model_version=model['model_version'], race_count=1,
            ticket_count=120, multiclass_brier=brier, log_loss=log_loss, winner_probability=winner))
    return metrics


def _build(prediction_receipt, race_bundle, race, now):
    clock = _clock(now)
    day, closed, _ = facts._program(race)
    _require(clock.astimezone(facts.JST).date() == day, 'current Japan-local race required for live research evaluation')
    # Independently validate every supplied proof before choosing an informative
    # empty state. Malformed result data never becomes "prediction not saved".
    prediction = _checked_prediction(prediction_receipt, race, clock, day, closed)
    result = _checked_race_bundle(race_bundle, race, clock, day, closed)
    proof = _result_proof(result)
    report = dict(schema_version=1, race_id=race['race_id'], date_jst=day.isoformat(),
        as_of=facts.stamp(clock), closed_at=facts.stamp(closed), status='PREDICTION_NOT_SAVED',
        research_only=True, validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[],
        comparison_scope='same_race_and_information_cutoff', common_race_ids=[], models=[],
        prediction_proof=prediction['proof'] if prediction is not None else None,
        result_proof=proof, exclusion_reason='PREDICTION_DURABLE_PRE_RACE_PROOF_MISSING')
    if prediction is None:
        return report
    if result is None:
        return dict(report, status='RESULT_NOT_OBTAINED', exclusion_reason='OFFICIAL_RESULT_NOT_OBTAINED')
    record = result['record']
    data = record['data'] if isinstance(record['data'], dict) else {}
    if record['status'] == 'PENDING':
        return dict(report, status='RESULT_PENDING', exclusion_reason='OFFICIAL_RESULT_PENDING')
    if data.get('status') != 'settled':
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_RESULT_STATUS_UNSUPPORTED')
    if data.get('finish_confirmed') is not True:
        return dict(report, status='RESULT_PENDING', exclusion_reason='OFFICIAL_RESULT_PENDING')
    if data.get('refund_boats') or data.get('refunds') not in ([], None):
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_REFUND_OUTCOME_UNSUPPORTED')
    truth = data.get('top3')
    if (not isinstance(truth, list) or len(truth) != 3 or any(type(x) is not int or x not in range(1, 7) for x in truth)
            or len(set(truth)) != 3):
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_TOP3_NOT_UNIQUE')
    return dict(report, status='EVALUATED', exclusion_reason=None, common_race_ids=[race['race_id']],
                models=_scores(prediction['snapshot'], truth))


def build_research_evaluation(prediction_receipt, race_bundle, race, now):
    """Evaluate the same frozen cohort using actual preclose cloud-save evidence.

    Missing evidence has an explicit empty state. Supplied malformed/tampered
    evidence raises ValueError. Financial payout completeness is independent
    of a uniquely confirmed normal finishing order and is not required to score.
    """
    try:
        return _build(prediction_receipt, race_bundle, race, now)
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid live research evaluation evidence') from exc
