"""Prepare one current future race from caller-authenticated saved P0 inputs.

No source, key, Git, storage or outcome access occurs here. The caller owns
authentication of the retained document/receipt and baseline runtime. The old
receipt proves original observations only: new paired predictions still need
their own encrypted storage and independent pre-cutoff Actions receipt.
"""
from copy import deepcopy
from datetime import datetime, timedelta

from .actions_contract import digest
from . import all_existing_model_registry as registry
from .all_existing_model_learning import _sources, verify_training
from .all_existing_model_derivation import _full_payload
from .boat_all_model_cycle import _receipt, _clock
from .boat_all_model_inputs import shared_snapshot_from_observed
from .boat_multi_feature_models import MODEL_IDS as FULL
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from .existing_model_dispatch import _native_hash
from .first_receipt_continuity import first_receipt_rows
from .four_sport_learning import LEARNED_ID
from .four_sport_model_suite import ALL_MODELS
from .frozen_day_cycle import official_id, rank_check, check_clock
from .observed_weight_learning import attach_snapshots, ts
from .boat_observed_pairwise_models import JST

MODEL_IDS=(*OBSERVED,*FULL,*ALL_MODELS,LEARNED_ID)
MINIMUM_LEAD=timedelta(minutes=10)


def _need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_FUTURE_P0_'+reason)


def _original_rows(document,receipt,now):
    _need(type(document) is dict and document.get('schema')=='RACE_AI_EXISTING_P0_DAY_V1' and
        document.get('actual_purchases') is False and type(document.get('predictions')) is list and
        document.get('race_count')==len(document['predictions'])<=288,'ORIGINAL_DOCUMENT')
    proof=_receipt(receipt,digest(document),receipt.get('head_sha'))
    _need(ts(proof['created_at'])<=now,'ORIGINAL_RECEIPT_IN_FUTURE')
    rows=[];seen=set()
    for suite in document['predictions']:
        rid=official_id(suite['race_id'])
        _need(rid not in seen and suite['stage']=='P0' and suite['event_date_jst']==document['day_jst'] and
            suite['suite_sha256']==digest({k:v for k,v in suite.items() if k!='suite_sha256'}) and
            set(suite['models'])==set(OBSERVED),'ORIGINAL_SUITE')
        seen.add(rid)
        check_clock(suite['as_of'],suite['sales_cutoff_at'],proof['created_at'])
        roster={str(p['lane']):p['registration_no'] for p in suite['observations']}
        for mid,prediction in suite['models'].items():
            _need(prediction['model_id']==mid and _native_hash(prediction) is not None and
                prediction['race_id']==suite['race_id'] and prediction['as_of']==suite['as_of'] and
                prediction['sales_cutoff_at']==suite['sales_cutoff_at'] and
                prediction['snapshot_sha256']==suite['snapshot_sha256'],'ORIGINAL_MODEL_BINDING')
            ranked=[p['combination'] for p in prediction['candidates']]
            rank_check(ranked,prediction['ordered_top8'],lanes=set(map(int,roster)))
            rows.append(dict(race_id=rid,sport='boat',stage='P0',model_id=mid,as_of=suite['as_of'],
                cutoff_at=suite['sales_cutoff_at'],server_saved_at=proof['created_at'],artifact_id=proof['artifact_id'],
                original_json_sha256=digest(document),model_sha256=prediction['prediction_sha256'],
                roster=roster,top8=prediction['ordered_top8'],ranked=ranked,calibrated=False))
    _need(len(rows)==document.get('model_forecast_count'),'ORIGINAL_MODEL_COUNT')
    first,_=first_receipt_rows(rows)
    return attach_snapshots(document,first),proof


def build_future_p0_requests(document,receipt,*,now,baseline_ranker,training=None,
                             dataset_folder=None,dataset_pointer=None,dataset_verified_at=None,
                             allow_source=None):
    """Return nine private requests for the earliest race with ten minutes left.

    Source timestamps, hashes and registered identities stay exact. Only each
    newly constructed payload's as-of is the trusted caller's current clock.
    Optional venue enrichment requires all three authenticated dataset inputs.
    No previous forecast, outcome, teacher label or saved-prediction timestamp
    is invented or replaced. All returned fields are private until encrypted.
    """
    now=_clock(now)
    rows,proof=_original_rows(document,receipt,now)
    options=(dataset_folder,dataset_pointer,dataset_verified_at)
    _need(not any(value is not None for value in options) or all(value is not None for value in options),
        'COMPLETE_DATASET_INPUTS_REQUIRED')
    if training is not None:
        verify_training(training)
        _need(training['scope']=='OPERATOR_SUPPLIED_RESEARCH' and ts(training['created_at'])<=now and
            {'boat/'+mid for mid in MODEL_IDS}<=set(training['models']),'NINE_AVAILABLE_CANDIDATE_CELLS_REQUIRED')
    eligible=[r for r in rows if r['model_id']==OBSERVED[0] and ts(r['cutoff_at'])>=now+MINIMUM_LEAD]
    if document['day_jst']!=now.astimezone(JST).date().isoformat():eligible=[]
    if not eligible:
        return dict(state='HOLD_NO_FUTURE_P0_RACE_WITH_MARGIN',requests=[],race_id=None,cutoff_at=None,
            source_refs=[],source_audit={},summary=dict(requested_cell_count=0,source_requests=0,
                independent_pre_cutoff_receipt_verified=False,plaintext_published=False))
    row=min(eligible,key=lambda r:(ts(r['cutoff_at']),r['race_id']))
    original=deepcopy(row['learning_snapshot'])
    _need(original['scope']=='OPERATOR_SUPPLIED_RESEARCH' and original['stage']=='P0','REAL_P0_SOURCE_REQUIRED')
    snapshot=deepcopy(original);snapshot['as_of']=now.isoformat()
    refs=_sources(dict(snapshot=snapshot))
    if dataset_pointer is not None:
        from .boat_venue_learning import _pin
        from .boat_venue_feature_adapter import RIGHTS,enrich_venue_snapshot
        _need(ts(dataset_verified_at)<=now,'DATASET_CLOCK')
        refs.add((_pin(dataset_pointer),RIGHTS))
        def enrichment_analysis(source,rights,purpose):
            return purpose=='analysis' and (source,rights) in refs and (
                allow_source is None or allow_source(source,rights,purpose) is True)
        snapshot=enrich_venue_snapshot(snapshot,dataset_folder,dataset_pointer,
            verified_at=dataset_verified_at,allow_source=enrichment_analysis,observed_only=True)['snapshot']
        refs|=_sources(dict(snapshot=snapshot))
    shared=shared_snapshot_from_observed(snapshot)
    full=_full_payload(dict(native_payload=dict(snapshot=snapshot)))
    _need(type(baseline_ranker) is dict,'BASELINE_RANKER_REQUIRED')
    requests=[]
    for mid in MODEL_IDS:
        if mid in OBSERVED:native=dict(snapshot=deepcopy(snapshot),scope=snapshot['scope'])
        elif mid in FULL:native=deepcopy(full)
        else:
            native=dict(snapshot=deepcopy(shared),stage='P0',scope=snapshot['scope'])
            if mid==LEARNED_ID:native['learned_model']=deepcopy(baseline_ranker)
        refs|=_sources(native)
        requests.append(dict(cell_key='boat/'+mid,native_payload=native))
    def analysis(source,rights,purpose):
        return purpose=='analysis' and (source,rights) in refs and (
            allow_source is None or allow_source(source,rights,purpose) is True)
    # The native forecast verifies the real baseline artifact's integrity,
    # schema, scope, creation clock, training cutoff and finite vector weights.
    registry.predict(LEARNED_ID,'boat',requests[-1]['native_payload'],at=now,allow_source=analysis)
    for request in requests:
        mid=request['cell_key'][5:]
        info=registry.validate_payload(mid,'boat',request['native_payload'],at=now,allow_source=analysis)
        _need(info['stage']=='P0' and ts(info['as_of'])==now and info['roster']==row['roster'] and
            ts(info['cutoff_at'])==ts(row['cutoff_at']),'NEW_NATIVE_BINDING')
    source_audit=dict(schema='RACE_AI_FUTURE_P0_SOURCE_AVAILABILITY_V1',
        race_id=row['race_id'],original_document_sha256=digest(document),original_receipt=proof,
        original_snapshot_sha256=row['learning_snapshot_sha256'],original_as_of=original['as_of'],
        original_source_evidence=deepcopy(original['sources']),new_payload_as_of=now.isoformat(),
        new_payload_saved_by_original_receipt=False,original_forecasts_changed=False,
        new_input_sha256={r['cell_key']:digest(r['native_payload']) for r in requests})
    return dict(state='READY_PRIVATE_FUTURE_P0_REQUESTS',requests=requests,race_id=row['race_id'],
        cutoff_at=row['cutoff_at'],source_refs=[list(p) for p in sorted(refs)],source_audit=source_audit,
        summary=dict(requested_cell_count=9,selected_race_count=1,minimum_lead_seconds=600,
            source_requests=0,independent_pre_cutoff_receipt_verified=False,
            original_forecasts_changed=False,provider_permission_confirmed=False,
            production_promoted=False,actual_purchases=False,plaintext_published=False))
