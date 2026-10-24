"""Pure, frozen, untrained display-only post-exhibition research forecast."""
import hashlib
import math

if __package__:
    from . import race_contract as facts, research_contract as research, evaluation_contract as evaluation
else:
    import race_contract as facts
    import research_contract as research
    import evaluation_contract as evaluation


MODEL_ID = 'official-beforeinfo-display-pl'
PARAMETERS = dict(display_coefficient_per_second=1.0, log_strength_min=-20.0,
                  log_strength_max=20.0, rating_floor=0.01)
POSITIONS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'top3')


class ExhibitionUnavailable(ValueError):
    """A fixed missing-state reason; never an available forecast or recommendation."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def digest(value):
    return hashlib.sha256(facts.canonical(value)).hexdigest()


def _clock(now, race):
    clock = research._clock(now)
    day, closed, _ = facts._program(race)
    facts._require(clock.astimezone(facts.JST).date() == day, 'current JST exhibition day required')
    return clock, day, closed


def _pinned_preview(receipt, race, now):
    if receipt is None:
        return None
    # The standalone pinned receipt has no mutable latest pointer. Reconstruct
    # only its checked manifest envelope to reuse the full canonical validator.
    record = receipt['record']
    mini = dict(schema_version=1, race_id=race['race_id'], date_jst=facts._program(race)[0].isoformat(),
        closed_at=race['closed_at'], program_sha256=facts.program_digest(race),
        published_at=receipt['cloud_saved_at'], latest={record['kind']:record['snapshot_id']}, records=[receipt])
    return facts.validate_cloud_bundle(mini, race, now).get('beforeinfo')


def _delta(before, after):
    return dict(baseline_probability=before, post_probability=after, delta_probability=after-before)


def _assemble(baseline_receipt, beforeinfo_receipt, race, now):
    clock, day, closed = _clock(now, race)
    baseline = evaluation._checked_prediction(baseline_receipt, race, clock, day, closed)
    preview = _pinned_preview(beforeinfo_receipt, race, clock)
    if baseline is None:
        raise ExhibitionUnavailable('BASELINE_MISSING')
    if preview is None:
        raise ExhibitionUnavailable('PREVIEW_NOT_OBTAINED')
    record = preview['record']
    if record['status'] == 'PENDING' or record['data'] is None:
        raise ExhibitionUnavailable('PREVIEW_PENDING')
    facts._require(preview['cloud_eligible_pre_race'] is True and record['storage_eligible_pre_race'] is True,
                   'actual durable pre-race beforeinfo required')
    rows = sorted(record['data']['boats'], key=lambda row: row['lane'])
    if any(row['display_time'] is None for row in rows):
        raise ExhibitionUnavailable('DISPLAY_INCOMPLETE')
    snapshot = baseline['snapshot']
    models = {m['model_id']:m for m in snapshot['models']}
    base = models[research.RATING_MODEL] if research.RATING_MODEL in models else models[research.UNIFORM_MODEL]
    strengths = {r['lane']:r['strength'] for r in base['strengths']}
    mean = math.fsum(row['display_time'] for row in rows)/6
    boats = []
    for row in rows:
        strength = strengths[row['lane']]
        delta = mean-row['display_time']
        score = max(PARAMETERS['log_strength_min'], min(PARAMETERS['log_strength_max'],
                    math.log(strength)+PARAMETERS['display_coefficient_per_second']*delta))
        boats.append(dict(lane=row['lane'], racer_registration_id=row['racer_registration_id'],
            display_time_seconds=row['display_time'], base_strength=strength,
            display_delta_seconds=delta, adjusted_strength=math.exp(score)))
    distribution = research.plackett_luce({r['lane']:r['adjusted_strength'] for r in boats})
    model = dict(model_id=MODEL_ID, model_version='1', parameters=dict(PARAMETERS), **distribution)
    deltas = dict(triples=[dict(combination=list(old['combination']), **_delta(old['probability'],new['probability']))
        for old,new in zip(base['triples'],model['triples'])], marginals=[dict(lane=old['lane'],
            **{position:_delta(old[position+'_probability'],new[position+'_probability']) for position in POSITIONS})
        for old,new in zip(base['marginals'],model['marginals'])])
    present_st = sum(row['preview_st_status'] != 'PENDING' for row in rows)
    features = dict(display_time=dict(status='AVAILABLE',used=True,reason=None),
        preview_st=dict(status='OBSERVED_UNUSED' if present_st==6 else 'PARTIAL_UNUSED' if present_st else 'MISSING',
                        used=False,reason='NOT_USED_BY_DISPLAY_ONLY_MODEL'),
        weather=dict(status='SOURCE_TIME_UNVERIFIED_UNUSED',used=False,reason='SOURCE_TIME_HAS_NO_DATE'),
        original_exhibition=dict(status='MISSING',used=False,reason='ORIGINAL_SOURCE_NOT_INGESTED'),
        exhibition_video=dict(status='MISSING',used=False,reason='NO_VALIDATED_BOAT_FEATURES'))
    report = dict(schema_version=1, phase='post_exhibition', race_id=race['race_id'], date_jst=day.isoformat(),
        closed_at=facts.stamp(closed), as_of=facts.stamp(clock), generated_at=facts.stamp(clock),
        program_identity_sha256=facts.program_digest(race), b_program_sha256=snapshot['program_sha256'],
        baseline_link=dict(request_id=baseline_receipt['request_id'],snapshot_id=snapshot['snapshot_id'],
            receipt_sha256=digest(baseline_receipt),cloud_saved_at=facts.stamp(baseline_receipt['cloud_saved_at']),model_id=base['model_id']),
        beforeinfo_link=dict(snapshot_id=record['snapshot_id'],receipt_sha256=digest(preview),
            source_url=record['source_url'],source_sha256=record['source_sha256'],captured_at=facts.stamp(record['captured_at']),
            runner_saved_at=facts.stamp(record['saved_at']),cloud_saved_at=facts.stamp(preview['cloud_saved_at'])),
        boats=boats,feature_status=features,model=model,deltas=deltas,research_only=True,
        validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
    report['snapshot_id'] = digest(report)
    facts._require(len(facts.canonical(report)) <= 256_000, 'post-exhibition snapshot exceeds bounded contract')
    return report


def build_post_exhibition_bundle(baseline_receipt, race_bundle, race, now):
    """Freeze checked existing B and six actual display observations before close."""
    try:
        clock, _, closed = _clock(now, race)
        receipts = facts.validate_cloud_bundle(race_bundle, race, clock)
        # Check any supplied baseline before choosing a missing state.
        report = _assemble(baseline_receipt, receipts.get('beforeinfo'), race, clock)
        if clock >= closed:
            raise ExhibitionUnavailable('CUTOFF_PASSED')
        return report
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid post-exhibition evidence') from exc


def validate_post_exhibition_bundle(bundle, baseline_receipt, beforeinfo_receipt, race, now):
    """Replay frozen input receipts, including after close; latest is irrelevant."""
    try:
        clock, day, closed = _clock(now, race)
        facts._require(isinstance(bundle,dict) and len(facts.canonical(bundle))<=256_000, 'bounded post bundle required')
        generated, asof = facts._time(bundle['generated_at']), facts._time(bundle['as_of'])
        facts._require(asof == generated < closed and generated <= clock
            and generated.astimezone(facts.JST).date()==day, 'post forecast generation clock invalid')
        expected = _assemble(baseline_receipt, beforeinfo_receipt, race, generated)
        facts._require(facts.canonical(bundle)==facts.canonical(expected), 'post bundle differs from deterministic pinned replay')
        return expected
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid post-exhibition bundle') from exc
