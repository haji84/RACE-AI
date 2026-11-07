"""Explicit receipt-bound cash scoring of original BOAT/HORSE future19 pairs.

The existing cash scorer owns all equations, native abstentions and stakes.
Official/legacy result readers authenticate complete original revisions before
this connector selects ordinary cash labels. No model or source is generated.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
import io
from pathlib import Path
import re
import tempfile
import zipfile

from .actions_contract import digest
from . import all_existing_model_pdca as cash
from . import all_existing_model_official_results as official
from . import all_existing_model_result_intake as boat_results
from .all_existing_model_intake import _results
from .all_existing_model_order_only_pdca import _frozen
from .all_existing_model_pairs import _output,_time,partition_key
from .all_existing_model_receipt import _verified_private_pairs_artifact,_entries,MAX_ARCHIVE_BYTES
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import read_candidate,seal_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .existing_model_dispatch import _race_key
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root

SCHEMA='RACE_AI_PRIVATE_CASH_NATIVE_PDCA_V1'
COUNTS='RACE_AI_CASH_NATIVE_PDCA_COUNTS_V1'
MAX_TOTAL_BYTES=256*1024*1024
FIELDS={'schema','training','summary','evaluated_at','cash_score','source_context','source_context_sha256'}


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_CASH_PDCA_'+reason)


def _key(row):return row['sport'],_race_key(row['race_id'],row['sport'])


def _cash_observations(contexts,forecasts,*,now):
    """Project only already-authenticated ordinary cash results, never types."""
    wanted={_key(p['pair']):p['pair'] for p in forecasts if p['pair']['sport'] in ('boat','horse')}
    labels=[];seen=set();outside=Counter();unmatched=0
    for context in contexts:
        for observation in context['observations']:
            identity=_key(observation)
            need(identity not in seen,'DUPLICATE_RESULT_REVISION');seen.add(identity)
            if observation['sport'] not in ('boat','horse') or observation['status']!='settled':
                outside[observation['status']]+=1;continue
            if identity not in wanted:unmatched+=1;continue
            pair=wanted[identity]
            need(_time(observation['closed_at'])==_time(pair.get('race_cutoff_at',pair['cutoff_at'])),'ACTUAL_RESULT_CUTOFF')
            projected={field:deepcopy(observation[field]) for field in cash.RESULT_FIELDS}
            cash._observation(projected,pair,now);labels.append(projected)
    return labels,dict(matched_cash_result_count=len(labels),unmatched_cash_result_count=unmatched,
        outside_normal_cash_result_state_counts=dict(outside))


def _item(item):
    need(type(item) is dict and set(item)=={'raw','metadata','expected_run_id','expected_head_sha'} and
         type(item['raw']) is bytes and type(item['metadata']) is dict,'SOURCE_ITEM')
    return item


def admit_sources(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,*,now,
        expected_native_run_id,expected_native_head_sha,candidate_cell_count,additional_native_artifacts=()):
    """No I/O: every byte/metadata pair must come from an actual artifact read."""
    state_key('production');need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    need(candidate_cell_count in (19,30) and type(candidate_cell_count) is int,'EXPLICIT_PROFILE')
    # The future30 ownerV2 record expressly excludes monetary evaluation.
    # A public request is not a new MAC-bound owner authorization.
    need(candidate_cell_count==19,'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION')
    need(type(result_artifacts) in (list,tuple) and 1<=len(result_artifacts)<=16 and
         type(additional_native_artifacts) in (list,tuple) and len(additional_native_artifacts)<=16,'SOURCE_BOUND')
    admission,records=_verified_private_pairs_artifact(native_raw,native_metadata,now=now,
        expected_run_id=expected_native_run_id,expected_head_sha=expected_native_head_sha)
    from .all_existing_model_cash_pdca_origin import verify_origin_artifact
    origin=verify_origin_artifact(origin_raw,origin_metadata,native_raw,native_metadata,admission,records,
        now=now,candidate_cell_count=candidate_cell_count)
    total=len(native_raw)+len(origin_raw);ids={native_metadata['id'],origin_metadata['id']}
    need(len(ids)==2,'DISTINCT_SOURCE_ARTIFACTS');all_records=list(records);extras=[]
    for item in additional_native_artifacts:
        _item(item);total+=len(item['raw']);need(total<=MAX_TOTAL_BYTES and item['metadata'].get('id') not in ids,'SOURCE_BOUND')
        extra,parts=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'])
        ids.add(item['metadata']['id']);extras.append(extra);all_records.extend(parts)
    contexts=[]
    for source in result_artifacts:
        need(type(source) is dict and set(source)=={'kind','raw','metadata','expected_run_id','expected_head_sha'} and
             source['kind'] in ('OFFICIAL','BOAT'),'RESULT_KIND')
        item={key:value for key,value in source.items() if key!='kind'};_item(item)
        total+=len(item['raw']);need(total<=MAX_TOTAL_BYTES and item['metadata'].get('id') not in ids,'SOURCE_BOUND');ids.add(item['metadata']['id'])
        if source['kind']=='OFFICIAL':
            admitted=official.observations_from_official_result_artifact(item['raw'],item['metadata'],now=now,
                expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'],
                frozen_native_payloads=_frozen(all_records),allow_order_only=True)
            observations=admitted['observations']
        else:
            admitted=boat_results.observations_from_result_artifact(item['raw'],item['metadata'],now=now,
                expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'])
            converted,_=_results(admitted['observations'],now);observations=[value['result'] for value in converted.values()]
        contexts.append(dict(kind=source['kind'],receipt=deepcopy(admitted['receipt']),
            original_observations=deepcopy(admitted['observations']),observations=deepcopy(observations),
            observations_sha256=digest(observations),source_summary=deepcopy(admitted['summary'])))
    forecasts=[record for record in records if 'pair' in record]
    labels,counts=_cash_observations(contexts,forecasts,now=now)
    context=dict(schema='RACE_AI_CASH_NATIVE_PDCA_SOURCE_CONTEXT_V1',candidate_cell_count=candidate_cell_count,
        source_native_metadata=deepcopy(native_metadata),source_admission=deepcopy(admission),origin=origin,
        result_contexts=contexts,additional_native_admissions=extras,normal_cash_observations=labels,
        projection_counts=counts,original_forecast_record_sha256=sorted(digest(p) for p in forecasts))
    return context,records,total


def _summary(context,rows,observation_count):
    admission=context['source_admission'];report=cash._summary(admission,rows,observation_count)
    # Detailed ticket/race/financial data stays in encrypted partitions only.
    report.pop('scoreboard',None)
    report.update(schema=COUNTS,candidate_cell_count=context['candidate_cell_count'],cash_cell_scope=19,
        cash_sports=['boat','horse'],source_forecast_count=admission['forecast_partition_count'],
        outside_cash_forecast_count=admission['forecast_partition_count']-sum(
            context['origin']['generation']['forecast_counts_by_sport'].get(sport,0) for sport in ('boat','horse')),
        source_context_sha256=digest(context),origin_artifact_id=context['origin']['origin_metadata']['id'],
        origin_artifact_digest=context['origin']['origin_metadata']['digest'],
        independent_origin_receipt_verified=True,independent_result_artifact_receipt_verified=True,
        independent_pdca_artifact_receipt_verified=False,all_thirty_cells_scored=False,
        missing_results_are_not_losses=True,**context['projection_counts'])
    return report


def verify_private_cash_pdca(payload):
    need(type(payload) is dict and set(payload)==FIELDS and payload['schema']==SCHEMA and payload['training'] is None,'PAYLOAD_SCHEMA')
    context=payload['source_context'];need(payload['source_context_sha256']==digest(context),'SOURCE_CONTEXT_HASH')
    need(type(context.get('candidate_cell_count')) is int and context['candidate_cell_count']==19,
        'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION')
    score=payload['cash_score'];cash.verify_private_pdca(score)
    now=_time(payload['evaluated_at']);need(score['evaluated_at']==payload['evaluated_at'],'EVALUATION_CLOCK')
    forecast=score['private_forecast'];need(forecast['pair']['sport'] in ('boat','horse'),'CASH_SPORT')
    need(score['source_artifact']==context['source_admission'] and digest(forecast) in context['original_forecast_record_sha256'],
         'ORIGINAL_FORECAST_BINDING')
    for result in context['result_contexts']:
        need(result['receipt'].get('authenticated_encrypted_result_artifact') is True and
            result['observations_sha256']==digest(result['observations']),'RESULT_CONTEXT_HASH')
    labels,_=_cash_observations(context['result_contexts'],[forecast],now=now)
    observation=next((label for label in labels if _key(label)==_key(forecast['pair'])),None)
    need(score['observation']==observation,'ORIGINAL_CASH_LABEL_BINDING')
    need(payload['summary']==_summary(context,[score['score']],int(observation is not None)),'SUMMARY_REPLAY')
    return True


def score_cash_pairs_artifacts(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,output,*,now,
        expected_native_run_id,expected_native_head_sha,candidate_cell_count,additional_native_artifacts=()):
    context,records,total=admit_sources(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,now=now,
        expected_native_run_id=expected_native_run_id,expected_native_head_sha=expected_native_head_sha,
        candidate_cell_count=candidate_cell_count,additional_native_artifacts=additional_native_artifacts)
    root=_output(output);need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET');rows=[];payloads=[]
    # Reuse the unchanged public core, including its original native receipt and
    # all plan/abstention/economic validation. Other sports remain unscored here.
    with tempfile.TemporaryDirectory(prefix='cash-native-core-') as temporary:
        scored=Path(temporary)/'core'
        cash.score_private_pairs_artifact(native_raw,native_metadata,context['normal_cash_observations'],scored,now=now,
            expected_run_id=expected_native_run_id,expected_head_sha=expected_native_head_sha)
        for folder in sorted(scored.iterdir()):
            if not folder.is_dir():continue
            original=read_candidate(folder)
            if original['private_forecast']['pair']['sport'] not in ('boat','horse'):continue
            row=original['score'];rows.append(row)
            payload=dict(schema=SCHEMA,training=None,evaluated_at=now.isoformat(),cash_score=original,
                source_context=deepcopy(context),source_context_sha256=digest(context),
                summary=_summary(context,[row],int(original['observation'] is not None)))
            verify_private_cash_pdca(payload);payloads.append(payload)
    need(payloads,'NO_CASH_FORECASTS');root.mkdir(parents=True,mode=0o700,exist_ok=False);private_root(root)
    for payload in payloads:
        status=seal_candidate(payload,root/partition_key(payload['cash_score']['private_forecast']['pair']))
        need(status.get('encrypted_readback_verified') is True,'LOCAL_READBACK')
    report=_summary(context,rows,len(context['normal_cash_observations']));report.update(encrypted_readback_verified=True,source_archive_bytes=total)
    _write(root.with_name(root.name+'.summary.json'),_bytes(report));return report


def verify_cash_pdca_artifact(raw,metadata,*,now,expected_run_id,expected_head_sha,expected_source_context_sha256=None):
    state_key('production');need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE_BYTES,'ARCHIVE_BOUND')
    run=metadata.get('workflow_run',{})
    need(type(metadata.get('id')) is int and metadata['id']>0 and metadata.get('expired') is False and
        re.fullmatch('all-existing-model-cash-pdca-'+str(expected_run_id)+'-[1-9][0-9]*',metadata.get('name','')) and
        type(run.get('id')) is int and run['id']==expected_run_id and run.get('head_sha')==expected_head_sha and
        all(type(run.get(k)) is int and run[k]==1416489937 for k in ('repository_id','head_repository_id')) and
        metadata.get('size_in_bytes')==len(raw) and metadata.get('digest')=='sha256:'+sha256(raw).hexdigest(),'ARTIFACT_IDENTITY_BYTES')
    saved=_time(metadata['created_at']);need(saved<=now<_time(metadata['expires_at']),'ARTIFACT_CLOCK')
    payloads=[];rows=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive,tempfile.TemporaryDirectory(prefix='cash-pdca-readback-') as temporary:
        for index,(key,entries) in enumerate(sorted(_entries(archive).items())):
            folder=Path(temporary)/str(index);folder.mkdir(mode=0o700);public=None
            for name,entry in entries.items():
                with archive.open(entry) as stream:body=stream.read(MEMBER_LIMITS[name]+1)
                need(len(body)==entry.file_size,'MEMBER_BOUND');_write(folder/name,body)
                if name=='summary.json':public=read_json_bytes(body)
            payload=read_candidate(folder);verify_private_cash_pdca(payload)
            need(key==partition_key(payload['cash_score']['private_forecast']['pair']) and
                public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False) and
                _time(payload['evaluated_at'])<saved+timedelta(seconds=1)<=now+timedelta(seconds=1),'PARTITION_BINDING')
            payloads.append(payload);rows.append(payload['cash_score']['score'])
    need(payloads and len({p['source_context_sha256'] for p in payloads})==1 and len({p['evaluated_at'] for p in payloads})==1,'MIXED_CONTEXTS')
    context=payloads[0]['source_context'];expected={value for value in context['original_forecast_record_sha256']}
    actual=[row['forecast_record_sha256'] for row in rows]
    need(len(set(actual))==len(actual) and set(actual)<=expected,'DUPLICATE_OR_FOREIGN_FORECAST')
    counts=context['origin']['generation']['forecast_counts_by_sport']
    need(len(rows)==sum(counts.get(sport,0) for sport in ('boat','horse')),'COMPLETE_CASH_SET_REQUIRED')
    if expected_source_context_sha256 is not None:need(digest(context)==expected_source_context_sha256,'ACTUAL_SOURCE_READBACK_BINDING')
    report=_summary(context,rows,len(context['normal_cash_observations']))
    return dict(report,encrypted_readback_verified=True,independent_pdca_artifact_receipt_verified=True,
        pdca_artifact_id=metadata['id'],pdca_artifact_digest=metadata['digest'],pdca_saved_at=metadata['created_at'])
