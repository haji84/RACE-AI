"""Rank-only aggregation of separate, unchanged, same-F30 forward batches.

Every row remains an ordinary V1 private PDCA partition. The extra owner cipher
binds their explicit union; it is never represented as a combined saved origin.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import io,re,shutil,stat,tempfile,zipfile
from pathlib import Path

from .actions_contract import digest
from . import all_existing_model_thirty_order_pdca as core
from . import all_existing_model_future_batches as batches
from . import boat_all_model_store as store
from .all_existing_model_pairs import partition_key,_output,_time
from .all_existing_model_runtime import _private_directory,_private_file
from .boat_venue_learning import read_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .permissioned_source_delivery import read_json_bytes
from .boat_venue_dataset import _bytes
from scripts.boat_all_racers import _read,_write

SCHEMA='RACE_AI_PRIVATE_ALL_THIRTY_ORDER_AGGREGATE_V2'
CONTEXT='RACE_AI_ALL_THIRTY_ORDER_AGGREGATE_CONTEXT_V2'
COUNTS='RACE_AI_ALL_THIRTY_ORDER_PDCA_COUNTS_V2'
ROUND=900023
AGGREGATE_LIMIT=4*1024*1024


def need(ok,reason):
    if not ok:raise ValueError('ALL_THIRTY_ORDER_AGGREGATE_'+reason)


def _bound(receipt,pin):
    from scripts.all_existing_model_order_only_pdca import _bound_receipt
    _bound_receipt(receipt,pin)


def _check_batch_order_context(context,forecasts,now):
    labels,counts=core._order_observations(context['result_contexts'],forecasts,now=now)
    need(labels==context['normal_order_results'] and counts==context['projection_counts'],
         'COMPLETE_ORIGINAL_ORDER_CONTEXT')


def _derive(payloads,manifest,evaluated_at):
    """Called only after V1 verification of every owner-sealed private row."""
    from scripts.all_existing_model_thirty_order_pdca import validate_manifest,SCHEMA_V2
    validate_manifest(manifest);need(manifest['schema']==SCHEMA_V2,'EXPLICIT_V2')
    now=_time(evaluated_at);need(type(payloads) is list and len(payloads)==30,'EXACT_THIRTY_ROWS')
    grouped={};rows=[];row_hashes={};contexts=[]
    for payload in payloads:
        core.verify_private_thirty_order_pdca(payload)
        need(_time(payload['evaluated_at'])==now,'ORIGINAL_EVALUATION_CLOCK')
        context=payload['source_context'];key=(context['source_native_metadata']['id'],context['origin']['origin_metadata']['id'])
        grouped.setdefault(key,[]).append(payload)
        forecast=payload['private_forecast'];part=partition_key(forecast['pair'])
        need(part not in row_hashes,'DUPLICATE_PARTITION');row_hashes[part]=digest(payload)
        rows.append(core.rank._row(forecast,payload['order_observation'],now))
    bindings=[]
    for pair in manifest['forecast_batches']:
        key=(pair['future_artifact']['id'],pair['origin_artifact']['id']);parts=grouped.pop(key,[])
        need(parts and len({p['source_context_sha256'] for p in parts})==1,'EXACT_BATCH_CONTEXT')
        context=parts[0]['source_context'];forecasts=[p['private_forecast'] for p in parts]
        hashes=sorted(digest(f) for f in forecasts)
        need(hashes==context['original_forecast_record_sha256']==sorted(context['source_admission']['record_sha256']) and
            len(forecasts)==context['source_admission']['forecast_partition_count'],'COMPLETE_ORIGINAL_BATCH')
        _check_batch_order_context(context,forecasts,now)
        _bound(context['source_admission'],pair['future_artifact'])
        actual=context['origin']['origin_metadata'];pin=pair['origin_artifact']
        need((actual['id'],actual['digest'],actual['workflow_run']['id'],actual['workflow_run']['head_sha'])==
            (pin['id'],pin['digest'],pin['run_id'],pin['head_sha']),'ORIGINAL_ORIGIN_PIN')
        need(len(context['result_contexts'])==len(manifest['result_artifacts']),'RESULT_SET')
        for result,pin in zip(context['result_contexts'],manifest['result_artifacts'],strict=True):
            need(result['kind']==pin['kind'],'RESULT_KIND');_bound(result['receipt'],pin)
        expected_extras=[other['future_artifact'] for other in manifest['forecast_batches'] if other!=pair]
        expected_extras+=manifest['additional_native_artifacts']
        need(len(context['additional_native_admissions'])==len(expected_extras),'TEACHER_NATIVE_SET')
        for receipt,pin in zip(context['additional_native_admissions'],expected_extras,strict=True):_bound(receipt,pin)
        # All batches replay exactly the same original RESULT archives. They do
        # not supply independent labels that can silently disagree by model.
        if contexts:need(context['result_contexts']==contexts[0]['result_contexts'],'SAME_ORIGINAL_RESULTS')
        contexts.append(context)
        bindings.append(dict(pins=deepcopy(pair),admission=context['source_admission'],records=forecasts,origin=context['origin']))
    need(not grouped,'UNDECLARED_BATCH')
    admitted=batches._bind_admitted_batches(bindings)
    labels,projection=core._order_observations(contexts[0]['result_contexts'],admitted['records'],now=now)
    matched=[p for p in payloads if p['result_observation_sha256'] is not None]
    need(len({p['private_forecast']['cell_key'] for p in payloads})==30,'DISJOINT_CELLS')
    context=dict(schema=CONTEXT,evaluated_at=evaluated_at,manifest=deepcopy(manifest),
        candidate_context_sha256=admitted['candidate_context_sha256'],training_sha256=admitted['training_sha256'],
        owner_record_sha256=admitted['owner_record_sha256'],
        batch_contexts=[dict(pins=deepcopy(pair),source_context_sha256=digest(c))
            for pair,c in zip(manifest['forecast_batches'],contexts,strict=True)],record_sha256=row_hashes)
    summary=dict(schema=COUNTS,state='PRIVATE_THIRTY_ORDER_AGGREGATE_SCORED' if len(matched)==30 else 'HOLD_THIRTY_ORDER_AGGREGATE_MISSING_TEACHERS',
        scope=admitted['batches'][0]['admission']['scope'],candidate_cell_count=30,
        evaluation_scope=core.EVALUATION_SCOPE,monetary_evaluation_available=False,forecast_batch_count=len(bindings),
        forecast_counts_by_sport=admitted['forecast_counts_by_sport'],partition_count=30,baseline_forecast_count=30,
        learned_forecast_count=30,paired_forecasts=sum(r['score']['paired'] for r in rows),teacher_matched_forecasts=len(matched),
        result_state_counts=dict(Counter(r['score']['state'] for r in rows)),training_sha256=admitted['training_sha256'],
        source_context_sha256=digest(context),all_thirty_cells_produced=True,all_thirty_cells_scored=len(matched)==30,
        independent_pre_cutoff_receipt_verified=True,independent_origin_receipt_verified=True,
        independent_result_artifact_receipt_verified=True,independent_pdca_artifact_receipt_verified=False,
        paired_cohorts_within_cells_only=True,cross_model_equal_cohort_comparison_claimed=False,
        missing_results_are_not_losses=True,provider_permission_confirmed=False,production_promoted=False,
        actual_purchases=False,accuracy_improvement_proven=False,plaintext_published=False,
        encrypted_readback_verified=True,**projection)
    return context,summary,core.rank._board(rows)


def _local_payloads(root):
    _private_directory(root);children=list(root.iterdir())
    need({p.name for p in children if p.is_file()}=={'aggregate.enc'} and
        len(children)==31,'EXACT_AGGREGATE_LAYOUT')
    payloads=[];members={};total=0
    for folder in sorted(p for p in children if p.name!='aggregate.enc'):
        _private_directory(folder);need(re.fullmatch('[a-f0-9]{64}',folder.name) and
            {p.name for p in folder.iterdir()}==set(MEMBER_LIMITS),'PARTITION_LAYOUT')
        for name,limit in MEMBER_LIMITS.items():
            path=folder/name;_private_file(path);raw=_read(path,limit);members[folder.name+'/'+name]=raw;total+=len(raw)
        payload=read_candidate(folder);need(partition_key(payload['private_forecast']['pair'])==folder.name,'PARTITION_IDENTITY')
        public=read_json_bytes(members[folder.name+'/summary.json'])
        need(public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False),'PARTITION_PUBLIC_BINDING')
        payloads.append(payload)
    _private_file(root/'aggregate.enc');raw=_read(root/'aggregate.enc',AGGREGATE_LIMIT);members['aggregate.enc']=raw;total+=len(raw)
    need(total<=core.MAX_ARCHIVE_BYTES,'OUTPUT_BOUND');return payloads,members


def verify_local(root,manifest,*,producer=None):
    payloads,members=_local_payloads(root);raw=members['aggregate.enc'];header=store.forecast_header(raw)
    body=store.open_forecasts(raw)
    need(type(body) is dict and set(body)=={'schema','producer','source_context','summary','comparison'} and
        body['schema']==SCHEMA and body['source_context'].get('manifest')==manifest,'AGGREGATE_SCHEMA')
    need(type(body['producer']) is dict and set(body['producer'])=={'run_id','head_sha'} and
        type(body['producer']['run_id']) is int and body['producer']['run_id']>0 and
        re.fullmatch('[a-f0-9]{40}',body['producer']['head_sha']) and header['run_id']==str(body['producer']['run_id']) and
        header['round_no']==ROUND and (producer is None or producer==body['producer']),'AGGREGATE_PRODUCER')
    context,summary,comparison=_derive(payloads,manifest,body['source_context']['evaluated_at'])
    need((context,summary,comparison)==(body['source_context'],body['summary'],body['comparison']),'AGGREGATE_REPLAY')
    return summary,members


def score(manifest,archives,result_artifacts,additional_native_artifacts,output,*,now,producer):
    admitted=batches.admit_batch_origins(manifest['forecast_batches'],archives,now=now)
    root=_output(output);need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET');root.mkdir(mode=0o700)
    payloads=[];total_sources=sum(len(item['raw']) for batch in archives for item in batch.values())
    total_sources+=sum(len(i['raw']) for i in (*result_artifacts,*additional_native_artifacts))
    need(total_sources<=core.MAX_TOTAL_BYTES,'SOURCE_BOUND')
    with tempfile.TemporaryDirectory(prefix='thirty-order-batches-',dir=root.parent) as temporary:
        for index,batch in enumerate(admitted['batches']):
            pair=batch['pins'];archive=archives[index];native=archive['future'];origin=archive['origin']
            extras=[]
            for other,source in zip(manifest['forecast_batches'],archives,strict=True):
                if other==pair:continue
                pin=other['future_artifact'];extras.append(dict(source['future'],expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha']))
            extras+=additional_native_artifacts
            target=Path(temporary)/str(index)
            core.score_thirty_order_pairs_artifacts(native['raw'],native['metadata'],origin['raw'],origin['metadata'],
                result_artifacts,target,now=now,expected_native_run_id=pair['future_artifact']['run_id'],
                expected_native_head_sha=pair['future_artifact']['head_sha'],additional_native_artifacts=extras)
            for folder in target.iterdir():
                need(folder.is_dir() and not (root/folder.name).exists(),'PARTITION_COLLISION')
                payloads.append(read_candidate(folder));shutil.move(str(folder),root/folder.name)
    context,summary,comparison=_derive(payloads,manifest,now.isoformat())
    raw=store.seal_forecasts(dict(schema=SCHEMA,producer=deepcopy(producer),source_context=context,summary=summary,
        comparison=comparison),run_id=str(producer['run_id']),round_no=ROUND)
    _write(root/'aggregate.enc',raw);verify_local(root,manifest,producer=producer)
    report=dict(summary,source_archive_bytes=total_sources)
    _write(root.with_name(root.name+'.summary.json'),_bytes(report));return report


def verify_artifact(raw,metadata,*,now,expected_run_id,expected_head_sha,expected_source_context_sha256=None):
    core.state_key('production');core.rank._clock(now)
    need(type(expected_run_id) is int and expected_run_id>0 and type(expected_head_sha) is str and
        re.fullmatch('[a-f0-9]{40}',expected_head_sha),'EXPECTED_RUN')
    need(type(raw) is bytes and 0<len(raw)<=core.MAX_ARCHIVE_BYTES and type(metadata) is dict and
        type(metadata.get('id')) is int and metadata['id']>0 and
        metadata.get('expired') is False and metadata.get('size_in_bytes')==len(raw) and
        metadata.get('digest')=='sha256:'+sha256(raw).hexdigest() and
        metadata.get('name')==f'all-existing-model-thirty-order-pdca-{expected_run_id}-{ROUND}','ACTUAL_ARTIFACT_BYTES')
    run=metadata.get('workflow_run',{});need(type(run) is dict and type(run.get('id')) is int and
        run['id']==expected_run_id and run.get('head_sha')==expected_head_sha and
        all(type(run.get(k)) is int and run[k]==1416489937 for k in ('repository_id','head_repository_id')) and
        _time(metadata['created_at'])<=now<_time(metadata['expires_at']),'ACTUAL_ARTIFACT_IDENTITY_CLOCK')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive,tempfile.TemporaryDirectory(prefix='thirty-order-aggregate-') as temporary:
        entries=archive.infolist();need(len(entries)==91 and len({e.filename for e in entries})==91 and
            sum(e.file_size for e in entries)<=core.MAX_ARCHIVE_BYTES,'ACTUAL_ARCHIVE_BOUND')
        root=Path(temporary);root.chmod(0o700)
        for entry in entries:
            match=re.fullmatch(r'([a-f0-9]{64})/(learning\.enc|learning\.json|summary\.json)',entry.filename)
            need(entry.filename==entry.orig_filename and '\0' not in entry.filename and (match or entry.filename=='aggregate.enc'),
                'ACTUAL_ARCHIVE_PATH')
            limit=MEMBER_LIMITS[match[2]] if match else AGGREGATE_LIMIT
            need(0<entry.file_size<=limit and not entry.flag_bits&0x41 and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and
                entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),'ACTUAL_ARCHIVE_MEMBER')
            with archive.open(entry) as stream:body=stream.read(limit+1)
            need(len(body)==entry.file_size,'ACTUAL_ARCHIVE_MEMBER_BOUND')
            path=root/entry.filename;path.parent.mkdir(mode=0o700,exist_ok=True);_write(path,body)
        body=store.open_forecasts(_read(root/'aggregate.enc',AGGREGATE_LIMIT));manifest=body['source_context']['manifest']
        summary,_=verify_local(root,manifest,producer=dict(run_id=expected_run_id,head_sha=expected_head_sha))
        need(_time(body['source_context']['evaluated_at'])<=now and
            _time(body['source_context']['evaluated_at'])<_time(metadata['created_at'])+core.timedelta(seconds=1),'ACTUAL_EVALUATION_CLOCK')
        if expected_source_context_sha256 is not None:need(summary['source_context_sha256']==expected_source_context_sha256,'EXPECTED_CONTEXT')
    return dict(summary,independent_pdca_artifact_receipt_verified=True,pdca_artifact_id=metadata['id'],
        pdca_artifact_digest=metadata['digest'],pdca_saved_at=metadata['created_at'])
