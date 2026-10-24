"""Pure read-only scores for one frozen name-bound forecast and official label."""
if __package__:
    from . import race_contract as facts
    from .evaluation_contract import _clock, _require, _scores, _result_proof
    from .name_bound_inputs import _context
    from .name_bound_prediction import validate_name_bound_envelope, digest, MAX_BYTES
else:
    import race_contract as facts
    from evaluation_contract import _clock, _require, _scores, _result_proof
    from name_bound_inputs import _context
    from name_bound_prediction import validate_name_bound_envelope, digest, MAX_BYTES


SCOPE = 'SAME_RACE_DIFFERENT_FEATURE_PHASES_NOT_EQUAL_INFORMATION_CUTOFF'


def _build(forecast, race_bundle, race, now):
    clock = _clock(now)
    forecast = validate_name_bound_envelope(forecast, race, now=clock)
    _, day, closed, projected, base_link, name_link = _context(
        race, forecast['baseline'], forecast['name_binding'], clock)
    result = facts.validate_cloud_bundle(race_bundle, projected, clock).get('raceresult')
    receipt, snapshot = forecast['receipt'], forecast['receipt']['snapshot']
    proof = _result_proof(result)
    if result is not None:
        record = result['record']
        captured, saved = map(facts._time, (record['captured_at'], result['cloud_saved_at']))
        _require(closed <= captured <= saved <= clock
            and all(t.astimezone(facts.JST).date() == day for t in (captured, saved))
            and record['eligible_pre_race'] is False and result['cloud_eligible_pre_race'] is False,
            'all official result receipts must be postclose on the race day')
        data = record['data'] if isinstance(record['data'], dict) else {}
        proof.update(refund_boats=sorted(data.get('refund_boats', [])),
            program_identity_sha256=facts.program_digest(projected))
    report = dict(schema_version=1, race_id=race['race_id'], date_jst=day.isoformat(),
        as_of=facts.stamp(clock), closed_at=facts.stamp(closed), status='RESULT_NOT_OBTAINED',
        research_only=True, validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[],
        comparison_scope=SCOPE, physical_exhibition_timing_verified=False, common_race_ids=[], models=[],
        forecast_proof=dict(request_id=receipt['request_id'], snapshot_id=snapshot['snapshot_id'],
            envelope_sha256=digest(forecast), baseline_request_id=base_link['request_id'],
            baseline_snapshot_id=base_link['snapshot_id'], baseline_receipt_sha256=base_link['receipt_sha256'],
            name_binding_request_id=name_link['request_id'], input_snapshot_id=forecast['inputs']['snapshot_id'],
            generated_at=snapshot['generated_at'], cloud_saved_at=receipt['cloud_saved_at'],
            receipt_confirmed_at=forecast['finalization']['receipt_confirmed_at']),
        result_proof=proof, exclusion_reason='OFFICIAL_RESULT_NOT_OBTAINED')
    if result is None:
        return report
    if record['status'] == 'PENDING' or record['data'] is None:
        return dict(report, status='RESULT_PENDING', exclusion_reason='OFFICIAL_RESULT_PENDING')
    if data.get('status') != 'settled':
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_RESULT_STATUS_UNSUPPORTED')
    if data.get('finish_confirmed') is not True:
        return dict(report, status='RESULT_PENDING', exclusion_reason='OFFICIAL_RESULT_PENDING')
    if data.get('refund_boats') or data.get('refunds') not in ([], None):
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_REFUND_OUTCOME_UNSUPPORTED')
    truth = data.get('top3')
    if (not isinstance(truth, list) or len(truth) != 3
            or any(type(x) is not int or x not in range(1,7) for x in truth) or len(set(truth)) != 3):
        return dict(report, status='RESULT_UNSUPPORTED', exclusion_reason='OFFICIAL_TOP3_NOT_UNIQUE')
    baseline = forecast['baseline']
    selected = next(m for m in baseline['snapshot']['models'] if m['model_id'] == snapshot['baseline_link']['model_id'])
    models = []
    for model, phase, source in [(selected, 'B_ONLY_BASELINE', baseline),
            (snapshot['models'][0], 'DISPLAY_V2', receipt), (snapshot['models'][1], 'ORIGINAL_V2', receipt)]:
        metrics = _scores({'models':[model]}, truth)[0]
        models.append(dict(metrics, phase=phase, forecast_generated_at=source['snapshot']['generated_at'],
            forecast_cloud_saved_at=source['cloud_saved_at']))
    return dict(report, status='EVALUATED', exclusion_reason=None,
        common_race_ids=[race['race_id']], models=models)


def build_name_bound_evaluation(forecast, race_bundle, race, now):
    """Validate pinned parents and postclose label before computing three scores.

    Missing labels have empty metrics; malformed supplied evidence raises
    ValueError even when another part would produce an informative empty state.
    Neither input arguments nor the frozen forecast models are changed.
    """
    try:
        report = _build(forecast, race_bundle, race, now)
        _require(0 < len(facts.canonical(report)) <= MAX_BYTES, 'name-bound evaluation exceeds response bound')
        return report
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError, StopIteration) as exc:
        raise ValueError('NAME_BOUND_EVALUATION_INVALID') from exc
