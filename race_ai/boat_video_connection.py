"""Connect private reports to frozen research versions of existing BOAT models.

The report, comparison evidence, frozen context and model inputs remain
separate trust boundaries. This coordinator neither trains nor fetches them.
An independently authenticated context must already exist before the supplied
model snapshot; actual connection timestamps are always recorded separately.
"""
from copy import deepcopy
from datetime import datetime, timezone

from .actions_contract import digest
from .boat_observed_pairwise_models import MODEL_IDS
from .boat_video_evaluation import _report, _roster, _time
from .boat_video_model_context import prepare_video_context
from . import observed_weight_learning


SCHEMA = 'RACE_AI_BOAT_VIDEO_CONNECTION_V1'
_VIDEO_TRAINING = 'RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1'
_MODEL_VERSION = '0.3.0-VIDEO-EXPERIMENTAL'
_ERROR = 'BOAT_VIDEO_CONNECTION_REJECTED'


def input_fingerprint(report, identity_evidence=None, model_inputs=None, *, receipt_verifier=None):
    """Fingerprint supplied data, never a polling clock or Python object ID."""
    return digest(dict(report_sha256=report['report_sha256'], identity_evidence=identity_evidence,
        model_inputs=model_inputs, independent_receipt_verifier_supplied=callable(receipt_verifier)))


def _instant(clock):
    value = datetime.now(timezone.utc) if clock is None else clock()
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError(_ERROR)
    _time(value.isoformat())
    return value


def _bound_snapshot(snapshot, report):
    from .frozen_day_cycle import official_id
    return (official_id(snapshot['race_id']) == report['race_id'] and
        snapshot['sales_cutoff_at'] == report['cutoff_at'] and
        _roster([dict(lane=p['lane'], registration_number=p['registration_no'])
                 for p in snapshot['participants']]) == _roster(report['roster']))


def connect_report(report, *, identity_evidence=None, model_inputs=None, receipt_verifier=None, clock=None):
    """Prepare a sealed context and optionally call the actual existing models.

    ``model_inputs`` comes only from a trusted Python caller and contains
    ``snapshot``, ``baseline_suite``, ``training_context``, ``video_context``
    (the already frozen context) and ``video_receipt``. The non-JSON verifier
    independently authenticates that exact context hash. No absent inputs are
    inferred, no result fitting occurs, and no original forecast is written.

    A physical V2 context additionally requires ``calibration_manifest`` bound
    to this original report. Its frozen ``measurement_parameters`` are replayed;
    an explicit ``physical_parameters`` override must recreate identical bytes.

    Without a frozen context, the returned context is prepared at the actual
    clock for independent storage and a later snapshot. A saved context keeps
    its own earlier availability clock, while actual generation starts and
    completes before cutoff. Late model results are discarded.
    """
    raw = _report(deepcopy(report))
    evidence, supplied = deepcopy((identity_evidence, model_inputs))
    started = _instant(clock)
    fingerprint = input_fingerprint(raw, evidence, supplied, receipt_verifier=receipt_verifier)
    cutoff = _time(raw['cutoff_at'])
    reasons, shadows, status = [], [], 'BLOCKED'
    frozen = supplied.get('video_context') if type(supplied) is dict else None
    context_as_of = started.isoformat()
    if frozen is not None:
        try:
            _time(frozen['as_of'])
            context_as_of = frozen['as_of']
        except (KeyError, TypeError, ValueError):
            reasons.append('FROZEN_VIDEO_CONTEXT_REJECTED')
    target = dict(race_id=raw['race_id'], cutoff_at=raw['cutoff_at'], roster=raw['roster'], as_of=context_as_of)
    physical = (type(frozen) is dict and frozen.get('schema_version') == 'RACE_AI_BOAT_VIDEO_PHYSICAL_MODEL_CONTEXT_V2' or
        type(evidence) is dict and evidence.get('schema_version') == 'RACE_AI_BOAT_VIDEO_PHYSICAL_COMPARISON_EVIDENCE_V1' or
        type(supplied) is dict and 'calibration_manifest' in supplied)
    try:
        if physical:
            from .boat_video_physical_context import prepare_physical_video_context
            if type(supplied) is not dict or 'calibration_manifest' not in supplied:
                reasons.append('PHYSICAL_CALIBRATION_MANIFEST_MISSING')
                raise ValueError('PHYSICAL_CALIBRATION_MANIFEST_MISSING')
            parameters = supplied.get('physical_parameters',
                frozen.get('measurement_parameters',{}) if type(frozen) is dict else {})
            context = prepare_physical_video_context(raw,evidence,supplied['calibration_manifest'],**target,**parameters)
        else:
            context = prepare_video_context(raw, evidence, **target)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        # Invalid independent declarations cannot prevent retaining a fully
        # typed missing context for the unchanged, valid original report.
        context = prepare_video_context(raw, None, **target)
        reasons.append('PHYSICAL_CALIBRATION_OR_EVIDENCE_REJECTED' if physical else 'IDENTITY_EVIDENCE_REJECTED')
    if not context['eligible_for_research']:
        reasons.extend(context['missing_reasons'])
    if started >= cutoff:
        reasons.append('ACTUAL_INFERENCE_POST_CUTOFF')
    if _time(context['as_of']) > started:
        reasons.append('CONTEXT_NOT_AVAILABLE_AT_INFERENCE')
    if frozen is not None and frozen != context:
        reasons.append('FROZEN_VIDEO_CONTEXT_REPORT_BINDING_MISMATCH')
    if not reasons:
        if supplied is None:
            status = 'WAITING_FROZEN_TRAINING_AND_INPUTS'
            reasons.append(status)
        elif type(supplied) is not dict:
            reasons.append('MODEL_INPUTS_REJECTED')
        elif (not {'snapshot', 'baseline_suite', 'training_context', 'video_receipt'} <= supplied.keys() or
              any(supplied[key] is None for key in ('snapshot', 'baseline_suite', 'training_context', 'video_receipt'))):
            status = 'WAITING_FROZEN_TRAINING_AND_INPUTS'
            reasons.append(status)
        elif frozen is None:
            status = 'WAITING_INDEPENDENT_CONTEXT_RECEIPT'
            reasons.append(status)
        else:
            try:
                snapshot = supplied['snapshot']
                as_of = _time(snapshot['as_of'])
                if not _bound_snapshot(snapshot, raw):
                    reasons.append('MODEL_SNAPSHOT_TARGET_MISMATCH')
                if as_of > started:
                    reasons.append('MODEL_SNAPSHOT_NOT_AVAILABLE_AT_INFERENCE')
                if as_of < _time(context['as_of']):
                    reasons.append('MODEL_SNAPSHOT_PRECEDES_VIDEO_CONTEXT')
                available = max(_time(raw['analysis_completed_at']),
                    _time(context['evidence_created_at'] or raw['analysis_completed_at']))
                if as_of < available:
                    reasons.append('MODEL_SNAPSHOT_PRECEDES_REPORT_OR_EVIDENCE')
                frozen_training = supplied['training_context']
                training = frozen_training.get('training')
                if not reasons and (training is None or frozen_training.get('receipt') is None):
                    status = 'WAITING_FROZEN_TRAINING_AND_INPUTS'
                    reasons.append(status)
                if not reasons and (training.get('schema') != _VIDEO_TRAINING or
                                    training.get('state') != 'FITTED_VIDEO_EXPERIMENTAL'):
                    status = 'WAITING_FROZEN_TRAINING_AND_INPUTS'
                    reasons.append(status)
                if not reasons and not callable(receipt_verifier):
                    reasons.append('INDEPENDENT_VIDEO_RECEIPT_VERIFIER_MISSING')
                if not reasons:
                    shadows = observed_weight_learning.make_shadows(snapshot, supplied['baseline_suite'],
                        supplied['training_context'], video_context=dict(video_context=context,
                            receipt=supplied['video_receipt']), video_receipt_verifier=receipt_verifier)
                    if (len(shadows) != len(MODEL_IDS) or
                        {row['model_id'] for row in shadows} != set(MODEL_IDS) or
                        any(row.get('variant') != 'LEARNED_VIDEO_EXPERIMENTAL' or
                            row.get('model_version') != _MODEL_VERSION or
                            row.get('production_eligible') is not False or
                            row.get('raw_report_validation_status') != 'UNVALIDATED' or
                            row.get('independent_human_heldout_verified') is not False or
                            row.get('video_context') != context for row in shadows)):
                        shadows = []
                        reasons.append('EXISTING_VIDEO_MODEL_OUTPUT_UNAVAILABLE')
                    else:
                        status = 'CONNECTED_EXPERIMENTAL'
            except Exception:
                # Decoder/model/trusted-reader details can contain private
                # paths. Preserve only a stable code, never exception text.
                reasons.append('MODEL_INPUTS_OR_INDEPENDENT_RECEIPT_REJECTED')
                shadows = []
    completed = _instant(clock)
    if completed < started:
        raise ValueError(_ERROR)
    if completed >= cutoff:
        reasons.append('ACTUAL_INFERENCE_POST_CUTOFF')
        shadows = []
        status = 'BLOCKED'
    if reasons and status == 'CONNECTED_EXPERIMENTAL':
        status, shadows = 'BLOCKED', []
    bundle = dict(schema_version=SCHEMA, report_sha256=raw['report_sha256'], race_id=raw['race_id'],
        cutoff_at=raw['cutoff_at'], roster=deepcopy(raw['roster']), started_at=started.isoformat(),
        completed_at=completed.isoformat(), input_sha256=fingerprint, status=status,
        missing_reasons=sorted(set(reasons)), video_context=context, shadows=shadows,
        source_family_ids=list(MODEL_IDS), raw_report_validation_status='UNVALIDATED',
        independent_human_heldout_verified=False, production_eligible=False,
        forecast_originals_modified=False, training_performed=False)
    bundle['connection_sha256'] = digest(bundle)
    return bundle
