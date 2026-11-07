"""Explicit thirty-cell rank objective over unchanged authenticated labels.

BOAT legacy and official settled labels retain their original monetary evidence,
but only the existing native ordering, probability and selection metrics are
evaluated. This module does not fit, forecast, buy, or calculate cash returns.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
import io
from pathlib import Path
import re
import tempfile
import zipfile
import zlib

from .actions_contract import digest
from .all_existing_model_intake import _results, _ordinary_result
from . import all_existing_model_order_only_pdca as rank
from . import all_existing_model_official_results as official
from . import all_existing_model_result_intake as boat_results
from . import boat_all_model_store as store
from .all_existing_model_pairs import _output, _time, partition_key, verify_private_pair
from .all_existing_model_receipt import _verified_private_pairs_artifact, _entries, _payload_clock, MAX_ARCHIVE_BYTES
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import read_candidate, seal_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .existing_model_dispatch import _race_key
from .official_order_only_result import EVALUATION_SCOPE, has_order_only_markers
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root

SCHEMA = 'RACE_AI_PRIVATE_ALL_THIRTY_ORDER_PDCA_V1'
COUNTS_SCHEMA = 'RACE_AI_ALL_THIRTY_ORDER_PDCA_COUNTS_V1'
CONTEXT_SCHEMA = 'RACE_AI_ALL_THIRTY_ORDER_PDCA_SOURCE_CONTEXT_V1'
MAX_TOTAL_BYTES = 256*1024*1024
FIELDS = {'schema','training','evaluated_at','summary','source_context','source_context_sha256',
          'private_forecast','observation','order_observation','result_original_sha256',
          'result_observation_sha256','result_context_index','score','comparison'}


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_THIRTY_ORDER_PDCA_' + reason)


def _key(value):
    return value['sport'], _race_key(value['race_id'], value['sport'])


def _order_observations(contexts, forecasts, *, now):
    """Select the latest admitted order, preserving every original label byte.

    Private helper: callers first authenticate all source artifacts. These
    dictionary checks are not an independent RESULT authentication boundary.
    """
    from scripts.all_existing_model_learning import _merge_verified_result_observations
    wanted = {_key(forecast['pair']): forecast['pair'] for forecast in forecasts}
    candidates = []; originals = {}
    for index, context in enumerate(contexts):
        normalized, _ = _results(context['original_observations'], now)
        values = [entry['result'] for entry in normalized.values()]
        _need(context['observations'] == values, 'ORIGINAL_RESULT_CONVERSION_BINDING')
        for entry in normalized.values():
            observation = entry['result']
            key = digest(observation)
            candidates.append(observation)
            originals.setdefault(key, []).append((index, entry['original']))
    selected = []; outside = Counter(); unmatched = 0
    for observation in _merge_verified_result_observations(candidates):
        identity = _key(observation)
        if observation['status'] not in ('settled', 'rank_confirmed'):
            outside[observation['status']] += 1
            continue
        _need(type(observation.get('refund_numbers')) is list and not observation['refund_numbers'],
              'NORMAL_RESULT_WITH_REFUND')
        if identity not in wanted:
            unmatched += 1
            continue
        pair = wanted[identity]
        _need(observation['sport'] == pair['sport'] and observation['roster'] ==
              pair['baseline_normalized']['roster'] == pair['learned_normalized']['roster'], 'REGISTERED_ROSTER')
        cutoff = _time(pair.get('race_cutoff_at', pair['cutoff_at']))
        _need(_time(observation['closed_at']) == cutoff and
              cutoff < _time(observation['captured_at']) <= now, 'ACTUAL_RACE_RESULT_CLOCK')
        checked, reason = _ordinary_result(observation, dict(race_id=pair['race_id'],
            race_cutoff_at=observation['closed_at'], roster=pair['baseline_normalized']['roster']), now)
        _need(checked is not None and reason is None, 'NORMAL_ORDER_REQUIRED')
        # Deterministic selection is independent of winners or payout amounts.
        index, original = min(originals[digest(observation)], key=lambda item:(digest(item[1]), item[0]))
        selected.append(dict(result_context_index=index, original_observation=deepcopy(original),
            order_observation=deepcopy(observation), result_original_sha256=digest(original),
            order_observation_sha256=digest(observation)))
    return selected, dict(matched_order_result_count=len(selected), unmatched_order_result_count=unmatched,
        outside_normal_order_result_state_counts=dict(outside))


def _source_item(item):
    _need(type(item) is dict and set(item)=={'raw','metadata','expected_run_id','expected_head_sha'} and
          type(item['raw']) is bytes and type(item['metadata']) is dict, 'SOURCE_ITEM')


def admit_sources(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,*,now,
                  expected_native_run_id,expected_native_head_sha,additional_native_artifacts=()):
    """Authenticate native/origin and every whole RESULT before selecting orders.

    Metadata must be freshly fetched by the caller from GitHub. This function
    performs no network request and accepts no JSON-only teacher shortcut.
    """
    state_key('production');rank._clock(now)
    _need(type(result_artifacts) in (list,tuple) and 1<=len(result_artifacts)<=16 and
          type(additional_native_artifacts) in (list,tuple) and len(additional_native_artifacts)<=16,'SOURCE_BOUND')
    admission,records=_verified_private_pairs_artifact(native_raw,native_metadata,now=now,
        expected_run_id=expected_native_run_id,expected_head_sha=expected_native_head_sha)
    # This generic origin reader verifies the V3 MAC-bound NO_MONETARY decision;
    # the separate cash19 connector is not invoked or granted a broader scope.
    from .all_existing_model_cash_pdca_origin import verify_origin_artifact
    origin=verify_origin_artifact(origin_raw,origin_metadata,native_raw,native_metadata,admission,records,
                                  now=now,candidate_cell_count=30)
    total=len(native_raw)+len(origin_raw);ids={native_metadata['id'],origin_metadata['id']}
    _need(len(ids)==2 and total<=MAX_TOTAL_BYTES,'DISTINCT_SOURCE_BOUND')
    all_records=list(records);extras=[]
    for item in additional_native_artifacts:
        _source_item(item);total+=len(item['raw'])
        _need(total<=MAX_TOTAL_BYTES and item['metadata'].get('id') not in ids,'SOURCE_BOUND')
        extra,parts=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'])
        ids.add(item['metadata']['id']);extras.append(extra);all_records.extend(parts)
    contexts=[]
    for source in result_artifacts:
        _need(type(source) is dict and set(source)=={'kind','raw','metadata','expected_run_id','expected_head_sha'} and
              source['kind'] in ('OFFICIAL','BOAT'),'RESULT_KIND')
        item={key:value for key,value in source.items() if key!='kind'};_source_item(item)
        total+=len(item['raw']);_need(total<=MAX_TOTAL_BYTES and item['metadata'].get('id') not in ids,'SOURCE_BOUND')
        ids.add(item['metadata']['id'])
        if source['kind']=='OFFICIAL':
            admitted=official.observations_from_official_result_artifact(item['raw'],item['metadata'],now=now,
                expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'],
                frozen_native_payloads=rank._frozen(all_records),allow_order_only=True)
            journal=store.open_forecasts(official._cipher(item['raw']))['observations']
        else:
            admitted=boat_results.observations_from_result_artifact(item['raw'],item['metadata'],now=now,
                expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'])
            from .boat_private_original_archive import open_original_zip
            with open_original_zip(item['raw'],item['metadata'],expected_kind='RESULT',
                                   max_plain_zip_bytes=32*1024*1024) as archive:
                journal=boat_results._json(archive.read('official-result-observations.json'))
        normalized,_=_results(admitted['observations'],now)
        observations=[entry['result'] for entry in normalized.values()]
        contexts.append(dict(kind=source['kind'],receipt=deepcopy(admitted['receipt']),
            original_journal_observations=deepcopy(journal),
            original_observations=deepcopy(admitted['observations']),observations=observations,
            observations_sha256=digest(observations),source_summary=deepcopy(admitted['summary']),
            source_evidence=deepcopy(admitted.get('result_source_evidence',[]))))
    forecasts=[record for record in records if 'pair' in record]
    labels,counts=_order_observations(contexts,forecasts,now=now)
    context=dict(schema=CONTEXT_SCHEMA,candidate_cell_count=30,evaluation_scope=EVALUATION_SCOPE,
        monetary_evaluation_available=False,source_native_metadata=deepcopy(native_metadata),
        source_admission=deepcopy(admission),origin=origin,result_contexts=contexts,
        additional_native_admissions=extras,normal_order_results=labels,projection_counts=counts,
        original_forecast_record_sha256=sorted(digest(forecast) for forecast in forecasts))
    return context,records,total


def _result_receipts(context,now):
    ids=set()
    for result in context['result_contexts']:
        receipt=result['receipt'];metadata=receipt['artifact_metadata'];run=metadata['workflow_run']
        _need(receipt.get('authenticated_encrypted_result_artifact') is True and
              receipt['artifact_id']==metadata['id'] and metadata['id'] not in ids and
              receipt['digest']==metadata['digest'] and receipt['artifact_name']==metadata['name'] and
              receipt['workflow_run_id']==run['id'] and receipt['head_sha']==run['head_sha'] and
              all(type(run.get(k)) is int and run[k]==official.REPOSITORY_ID
                  for k in ('repository_id','head_repository_id')) and metadata.get('expired') is False and
              receipt['saved_at']==metadata['created_at'] and receipt['expires_at']==metadata['expires_at'] and
              _time(receipt['saved_at'])<=now<_time(receipt['expires_at']),'RESULT_RECEIPT')
        ids.add(metadata['id'])
        journal=result['original_journal_observations']
        _need(type(journal) is list and len(journal)<=10000 and
              receipt['original_journal_sha256']==digest(journal) and
              all(_time(o['captured_at'])<=now and _time(o['captured_at'])<
                  _time(receipt['saved_at'])+timedelta(seconds=1) for o in journal),'FULL_ORIGINAL_JOURNAL_BINDING')
        from scripts.all_existing_model_learning import _merge_verified_result_observations
        latest=_merge_verified_result_observations(journal)
        _need(sorted(digest(o) for o in latest)==sorted(digest(o) for o in result['original_observations']),
              'LATEST_ORIGINAL_REVISION_BINDING')
        normalized,_=_results(result['original_observations'],now)
        observations=[entry['result'] for entry in normalized.values()]
        _need(result['observations']==observations and result['observations_sha256']==digest(observations) and
              all(_time(o['captured_at'])<_time(receipt['saved_at'])+timedelta(seconds=1)
                  for o in observations),'ORIGINAL_RESULT_CONTEXT_BINDING')
        if result['kind']=='OFFICIAL':
            rank._typed_results(dict(receipt=receipt,observations=result['original_observations'],
                source_evidence=result['source_evidence'],
                observations_sha256=digest(result['original_observations'])),now)
        else:
            _need(result['kind']=='BOAT' and result['source_evidence']==[],'RESULT_SOURCE_KIND')
            from .repeated_cycle import matches
            _need(matches(metadata['name'],'race-existing-cycle-'+str(run['id'])),'BOAT_RESULT_NAME')
            index=receipt['journal_index']
            for original in journal:
                _need(any(row['race_id']==original['race_id'] and row['captured_at']==original['captured_at'] and
                          row['observation_sha256']==digest(original) for row in index),'BOAT_ORIGINAL_LABEL_HASH')
                day=original['race_id'][:8]
                boat_results._observation(original,day=day[:4]+'-'+day[4:6]+'-'+day[6:],
                    saved=_time(receipt['saved_at']),now=now)


def _origin_receipt(context,now):
    """Replay the retained server receipt, without refreshing its saved clocks."""
    from scripts import all_existing_model_native_future as future
    origin=context['origin'];metadata=origin['origin_metadata'];native=context['source_native_metadata']
    run=metadata.get('workflow_run');native_run=native['workflow_run'];generation=origin['generation']
    _need(type(metadata.get('id')) is int and metadata['id']>0 and metadata['id']!=native['id'] and
          metadata.get('name')==f'all-native-future-origin-{native_run["id"]}-{future.ORIGIN_ROUND}' and
          metadata.get('expired') is False and type(metadata.get('size_in_bytes')) is int and
          0<metadata['size_in_bytes']<=store.MAX_WIRE+1024*1024 and
          type(metadata.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',metadata['digest']) and
          type(origin.get('origin_cipher_sha256')) is str and re.fullmatch('[a-f0-9]{64}',origin['origin_cipher_sha256']) and
          type(run) is dict and type(run.get('id')) is int and run['id']==native_run['id']==generation['workflow_run_id'] and
          run.get('head_sha')==native_run['head_sha']==generation['expected_head_sha'] and
          all(type(run.get(k)) is int and run[k]==official.REPOSITORY_ID
              for k in ('repository_id','head_repository_id')),'ORIGIN_RECEIPT_IDENTITY')
    saved=_time(metadata['created_at']);generated=_time(generation['origin_generated_at'])
    _need(generated<=now and generated<saved+timedelta(seconds=1) and saved<=now<_time(metadata['expires_at']) and
          saved+timedelta(seconds=1)+future.MINIMUM_LEAD<_time(generation['cutoff_at']),'ORIGIN_RECEIPT_CLOCK')


def _context_binding(context,forecast,now):
    from scripts import all_existing_model_native_future as future
    _need(context['schema']==CONTEXT_SCHEMA and context['candidate_cell_count']==30 and
          context['evaluation_scope']==EVALUATION_SCOPE and context['monetary_evaluation_available'] is False,
          'NO_MONETARY_CONTEXT')
    admission=context['source_admission'];metadata=context['source_native_metadata']
    _origin_receipt(context,now)
    generation=context['origin']['generation'];audit=context['origin']['source_audit']
    training=forecast['training'];record_sha=digest(forecast)
    future._training_v3(training,audit['owner_research_record'],require_owner=True)
    _need(context['origin']['manifest']['schema']==future.MANIFEST_SCHEMA_V3 and
          generation['manifest_sha256']==digest(context['origin']['manifest']) and
          hmac.compare_digest(generation['owner_generation_mac'],future._generation_mac_v3(generation)) and
          generation['candidate_cell_count']==30 and generation['training_sha256']==training['training_sha256'] and
          generation['source_audit_sha256']==digest(audit) and
          generation['local_record_sha256']==context['original_forecast_record_sha256']==sorted(admission['record_sha256']) and
          record_sha in context['original_forecast_record_sha256'],'ORIGINAL_OWNER_GENERATION_BINDING')
    run=metadata['workflow_run'];saved=_time(metadata['created_at'])
    _need(type(metadata.get('id')) is int and metadata['id']>0 and type(metadata.get('size_in_bytes')) is int and
          0<metadata['size_in_bytes']<=MAX_ARCHIVE_BYTES and
          metadata.get('name')==f'all-existing-model-pairs-{run["id"]}-{future.ROUND}'==admission['artifact_name'] and
          all(type(run.get(k)) is int and run[k]==official.REPOSITORY_ID
              for k in ('repository_id','head_repository_id')) and
          type(metadata.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',metadata['digest']) and
          admission['independent_pre_cutoff_receipt_verified'] is True and
          admission['artifact_id']==metadata['id'] and admission['artifact_digest']==metadata['digest'] and
          admission['saved_at']==metadata['created_at'] and admission['workflow_run_id']==run['id'] and
          admission['head_sha']==run['head_sha']==generation['expected_head_sha'] and
          generation['workflow_run_id']==run['id'] and metadata.get('expired') is False and
          saved<=now<_time(metadata['expires_at']) and
          saved+timedelta(seconds=1)+future.MINIMUM_LEAD<_time(forecast['pair']['cutoff_at']),'NATIVE_RECEIPT_BINDING')
    _payload_clock(forecast,saved,now)
    _result_receipts(context,now)


def _summary(context,rows):
    admission=context['source_admission'];origin=context['origin'];generation=origin['generation']
    from scripts.all_existing_model_native_future import V3_CELLS
    expected=set().union(*V3_CELLS.values());matched=[row for row in rows if row['result_observation_sha256'] is not None]
    return dict(schema=COUNTS_SCHEMA,state='PRIVATE_THIRTY_ORDER_PDCA_SCORED' if matched else 'PRIVATE_THIRTY_ORDER_PDCA_PENDING',
        scope=admission['scope'],candidate_cell_count=30,evaluation_scope=EVALUATION_SCOPE,
        monetary_evaluation_available=False,partition_count=len(rows),baseline_forecast_count=len(rows),
        learned_forecast_count=len(rows),paired_forecasts=sum(row['score']['paired'] for row in rows),
        teacher_matched_forecasts=len(matched),result_state_counts=dict(Counter(row['score']['state'] for row in rows)),
        source_artifact_id=admission['artifact_id'],source_artifact_digest=admission['artifact_digest'],
        source_workflow_run_id=admission['workflow_run_id'],source_head_sha=admission['head_sha'],
        training_sha256=admission['training_sha256'],origin_artifact_id=origin['origin_metadata']['id'],
        origin_artifact_digest=origin['origin_metadata']['digest'],source_context_sha256=digest(context),
        all_thirty_cells_produced=generation['all_thirty_cells_produced'],
        all_thirty_cells_scored=len(matched)==30 and {row['cell_key'] for row in matched}==expected,
        independent_pre_cutoff_receipt_verified=True,independent_origin_receipt_verified=True,
        independent_result_artifact_receipt_verified=True,independent_pdca_artifact_receipt_verified=False,
        paired_cohorts_within_cells_only=True,cross_model_equal_cohort_comparison_claimed=False,
        missing_results_are_not_losses=True,provider_permission_confirmed=False,production_promoted=False,
        actual_purchases=False,accuracy_improvement_proven=False,plaintext_published=False,**context['projection_counts'])


def _matched(context,forecast,now):
    labels,_=_order_observations(context['result_contexts'],[forecast],now=now)
    label=labels[0] if labels else None
    if label is not None:
        _need(label in context['normal_order_results'],'ORIGINAL_LATEST_LABEL_BINDING')
    return label


def verify_private_thirty_order_pdca(payload):
    """Replay one owner-authenticated partition at its original evaluation time."""
    try:
        _need(type(payload) is dict and set(payload)==FIELDS and payload['schema']==SCHEMA and
              payload['training'] is None,'PAYLOAD_SCHEMA')
        now=_time(payload['evaluated_at']);forecast=payload['private_forecast'];verify_private_pair(forecast)
        context=payload['source_context'];_need(payload['source_context_sha256']==digest(context),'SOURCE_CONTEXT_HASH')
        _context_binding(context,forecast,now);label=_matched(context,forecast,now)
        expected=dict(observation=label['original_observation'] if label else None,
            order_observation=label['order_observation'] if label else None,
            result_original_sha256=label['result_original_sha256'] if label else None,
            result_observation_sha256=label['order_observation_sha256'] if label else None,
            result_context_index=label['result_context_index'] if label else None)
        _need(all(payload[key]==value for key,value in expected.items()),'ORIGINAL_RESULT_BINDING')
        row=rank._row(forecast,expected['order_observation'],now)
        _need(payload['score']==row['score'] and payload['comparison']==rank._board([row]) and
              payload['summary']==_summary(context,[row]),'RANK_SCORE_REPLAY')
        return True
    except (KeyError,TypeError,AttributeError,IndexError,StopIteration) as exc:
        raise ValueError('ALL_THIRTY_ORDER_PDCA_PAYLOAD_INVALID') from exc


def score_thirty_order_pairs_artifacts(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,output,*,now,
        expected_native_run_id,expected_native_head_sha,additional_native_artifacts=()):
    context,records,total=admit_sources(native_raw,native_metadata,origin_raw,origin_metadata,result_artifacts,now=now,
        expected_native_run_id=expected_native_run_id,expected_native_head_sha=expected_native_head_sha,
        additional_native_artifacts=additional_native_artifacts)
    root=_output(output);_need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET');rows=[];payloads=[]
    for forecast in records:
        if 'pair' not in forecast:continue
        label=_matched(context,forecast,now);order=label['order_observation'] if label else None
        row=rank._row(forecast,order,now);rows.append(row)
        payload=dict(schema=SCHEMA,training=None,evaluated_at=now.isoformat(),source_context=deepcopy(context),
            source_context_sha256=digest(context),private_forecast=deepcopy(forecast),
            observation=deepcopy(label['original_observation']) if label else None,order_observation=deepcopy(order),
            result_original_sha256=label['result_original_sha256'] if label else None,
            result_observation_sha256=label['order_observation_sha256'] if label else None,
            result_context_index=label['result_context_index'] if label else None,
            score=deepcopy(row['score']),comparison=rank._board([row]),summary=_summary(context,[row]))
        verify_private_thirty_order_pdca(payload);payloads.append(payload)
    _need(payloads,'NO_NATIVE_FORECASTS');root.mkdir(parents=True,mode=0o700,exist_ok=False);private_root(root)
    for payload in payloads:
        status=seal_candidate(payload,root/partition_key(payload['private_forecast']['pair']))
        _need(status.get('encrypted_readback_verified') is True,'LOCAL_READBACK')
    report=_summary(context,rows);report.update(encrypted_readback_verified=True,source_archive_bytes=total)
    _write(root.with_name(root.name+'.summary.json'),_bytes(report));return report


def verify_thirty_order_pdca_artifact(raw,metadata,*,now,expected_run_id,expected_head_sha,
                                     expected_source_context_sha256=None):
    """Admit actual saved encrypted score ZIP; retain original source/eval clocks."""
    state_key('production');rank._clock(now)
    _need(type(expected_run_id) is int and expected_run_id>0 and type(expected_head_sha) is str and
          re.fullmatch('[a-f0-9]{40}',expected_head_sha),'EXPECTED_RUN')
    run=metadata.get('workflow_run',{})
    _need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE_BYTES and type(metadata.get('id')) is int and
          metadata['id']>0 and metadata.get('expired') is False and
          re.fullmatch('all-existing-model-thirty-order-pdca-'+str(expected_run_id)+'-[1-9][0-9]*',metadata.get('name','')) and
          type(run.get('id')) is int and run['id']==expected_run_id and run.get('head_sha')==expected_head_sha and
          all(type(run.get(k)) is int and run[k]==official.REPOSITORY_ID for k in ('repository_id','head_repository_id')) and
          type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes']==len(raw) and
          metadata.get('digest')=='sha256:'+sha256(raw).hexdigest(),'ARTIFACT_IDENTITY_BYTES')
    saved=_time(metadata['created_at']);_need(saved<=now<_time(metadata['expires_at']),'ARTIFACT_CLOCK')
    rows=[];payloads=[]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive, tempfile.TemporaryDirectory(prefix='thirty-order-pdca-') as temporary:
            for index,(key,entries) in enumerate(sorted(_entries(archive).items())):
                folder=Path(temporary)/str(index);folder.mkdir(mode=0o700);public=None
                for name,entry in entries.items():
                    with archive.open(entry) as stream:body=stream.read(MEMBER_LIMITS[name]+1)
                    _need(len(body)==entry.file_size,'MEMBER_BOUND');_write(folder/name,body)
                    if name=='summary.json':public=read_json_bytes(body)
                payload=read_candidate(folder);verify_private_thirty_order_pdca(payload)
                _need(key==partition_key(payload['private_forecast']['pair']) and
                      public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False) and
                      _time(payload['evaluated_at'])<saved+timedelta(seconds=1) and
                      _time(payload['evaluated_at'])<=now,'PARTITION_BINDING')
                payloads.append(payload);rows.append(rank._row(payload['private_forecast'],payload['order_observation'],
                                                               _time(payload['evaluated_at'])))
    except (zipfile.BadZipFile,RuntimeError,EOFError,zlib.error) as exc:
        raise ValueError('ALL_THIRTY_ORDER_PDCA_ARCHIVE_REJECTED') from exc
    _need(payloads and len({p['source_context_sha256'] for p in payloads})==1 and
          len({p['evaluated_at'] for p in payloads})==1,'MIXED_CONTEXTS')
    context=payloads[0]['source_context'];actual=[row['forecast_record_sha256'] for row in rows]
    _need(len(set(actual))==len(actual) and sorted(actual)==context['original_forecast_record_sha256'] and
          len(rows)==context['source_admission']['forecast_partition_count'],'COMPLETE_FORECAST_SET_REQUIRED')
    labels,counts=_order_observations(context['result_contexts'],[p['private_forecast'] for p in payloads],
                                     now=_time(payloads[0]['evaluated_at']))
    _need(labels==context['normal_order_results'] and counts==context['projection_counts'],'COMPLETE_ORDER_CONTEXT_REQUIRED')
    if expected_source_context_sha256 is not None:
        _need(digest(context)==expected_source_context_sha256,'ACTUAL_SOURCE_READBACK_BINDING')
    report=_summary(context,rows)
    return dict(report,encrypted_readback_verified=True,independent_pdca_artifact_receipt_verified=True,
                pdca_artifact_id=metadata['id'],pdca_artifact_digest=metadata['digest'],pdca_saved_at=metadata['created_at'])
