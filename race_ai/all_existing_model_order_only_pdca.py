"""Explicit encrypted rank-only comparison of authenticated native forecasts.

Both input and official RESULT archives are authenticated before scoring. This
module neither fits nor predicts nor calculates financial performance. Original
forecasts (including their native plans) and full result labels remain unchanged
private evidence. Structural replay is meaningful only after owner-key readback.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
import io
import math
from pathlib import Path
import re
import tempfile
import zipfile
import zlib

from .actions_contract import digest
from . import all_existing_model_official_results as official
from .all_existing_model_pairs import _output,_time,partition_key,verify_private_pair,verify_private_record
from .all_existing_model_receipt import _verified_private_pairs_artifact,_entries,_payload_clock,MAX_ARCHIVE_BYTES
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import seal_candidate,read_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .comprehensive_four_sport_models import SCHEMA as DENSE,SCHEMA_SPARSE
from .existing_model_dispatch import _race_key
from .official_order_only_result import EVALUATION_SCOPE,has_order_only_markers,validate_order_only
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root

SCHEMA='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_ORDER_ONLY_PDCA_V1'
COUNTS_SCHEMA='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_ORDER_ONLY_PDCA_COUNTS_V1'
MAX_TOTAL_INPUT_BYTES=256*1024*1024
RESULT_CONTEXT_FIELDS={'receipt','observations','source_evidence','observations_sha256'}
FIELDS={'schema','evaluated_at','training','summary','source_forecast','source_native_metadata','source_result',
        'additional_native_admissions','result_context','private_forecast','observation','result_observation_sha256',
        'result_source_evidence','score'}


def _need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_ORDER_ONLY_PDCA_'+reason)


def _clock(now):
    _need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    return now


def _key(value):return value['sport'],_race_key(value['race_id'],value['sport'])


def _source_receipt(receipt,now):
    """Check retained reader claims after owner-authenticated score readback."""
    _need(type(receipt) is dict and receipt.get('authenticated_encrypted_result_artifact') is True and
          type(receipt.get('artifact_metadata')) is dict,'RESULT_RECEIPT')
    metadata=receipt['artifact_metadata'];run=metadata.get('workflow_run');run_id=receipt.get('workflow_run_id')
    _need(type(run_id) is int and run_id>0 and type(receipt.get('head_sha')) is str and
          re.fullmatch('[a-f0-9]{40}',receipt['head_sha']) and type(metadata.get('id')) is int and
          metadata['id']==receipt.get('artifact_id') and metadata['id']>0 and metadata.get('expired') is False and
          type(metadata.get('name')) is str and re.fullmatch('all-existing-official-results-'+str(run_id)+'-[1-9][0-9]{0,5}',metadata['name']) and
          metadata['name']==receipt.get('artifact_name') and type(run) is dict and type(run.get('id')) is int and
          run['id']==run_id and run.get('head_sha')==receipt['head_sha'] and all(type(run.get(k)) is int and
          run[k]==official.REPOSITORY_ID for k in ('repository_id','head_repository_id')),'RESULT_RECEIPT_IDENTITY')
    _need(receipt.get('digest')==metadata.get('digest') and type(receipt.get('digest')) is str and
          re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and type(metadata.get('size_in_bytes')) is int and
          0<metadata['size_in_bytes']<=official.MAX_ARCHIVE_BYTES and all(type(receipt.get(k)) is str and
          re.fullmatch('[a-f0-9]{64}',receipt[k]) for k in ('cipher_sha256','original_payload_sha256',
          'original_journal_sha256','capture_index_sha256','frozen_inputs_sha256')),'RESULT_RECEIPT_BINDING')
    _need(_time(receipt['saved_at'])==_time(metadata['created_at'])<=now<_time(metadata['expires_at']) and
          receipt.get('expires_at')==metadata.get('expires_at'),'RESULT_RECEIPT_CLOCK')


def _typed_results(context,now):
    _need(type(context) is dict and set(context)==RESULT_CONTEXT_FIELDS and
          type(context['observations']) is list and len(context['observations'])<=10000 and
          context['observations_sha256']==digest(context['observations']) and
          type(context['source_evidence']) is list,'RESULT_CONTEXT')
    _source_receipt(context['receipt'],now)
    proofs={}
    for proof in context['source_evidence']:
        _need(type(proof) is dict and type(proof.get('result_binding')) is dict,'RESULT_PROOF')
        key=_key(proof['result_binding'])
        _need(key not in proofs,'DUPLICATE_RESULT_PROOF');proofs[key]=proof
    typed={};seen=set()
    for observation in context['observations']:
        _need(type(observation) is dict and type(observation.get('sport')) is str and
              type(observation.get('race_id')) is str,'RESULT_IDENTITY')
        key=_key(observation);_need(key not in seen,'DUPLICATE_RESULT');seen.add(key)
        if not has_order_only_markers(observation):
            _need(set(observation)==official.OBSERVATION_FIELDS and
                  observation.get('status') in ('settled','pending','special'),'OUTSIDE_RESULT_SCHEMA')
            continue
        checked=validate_order_only(observation)
        _need(_time(checked['captured_at'])<=now and key in proofs,'RESULT_PROOF_REQUIRED')
        proof=proofs[key]
        _need(proof.get('artifact_receipt')==context['receipt'],'RESULT_PROOF_RECEIPT_BINDING')
        _need(_time(proof['generated_at'])<=now,'RESULT_GENERATION_AFTER_EVALUATION')
        official.verify_result_source_evidence(proof,result=checked,now=now)
        typed[key]=(checked,proof)
    return typed


def _observation(observation,proof,pair,context,now):
    checked=validate_order_only(observation,sport=pair['sport'],race_id=pair['race_id'],
        roster=pair['baseline_normalized']['roster'])
    _need(checked['roster']==pair['learned_normalized']['roster'] and
          _time(checked['closed_at'])==_time(pair.get('race_cutoff_at',pair['cutoff_at'])) and
          _time(checked['captured_at'])<=now,'SAME_RACE_CUTOFF_AND_ROSTER_REQUIRED')
    _need(proof.get('artifact_receipt')==context['receipt'],'RESULT_PROOF_RECEIPT_BINDING')
    official.verify_result_source_evidence(proof,result=checked,now=now)
    return checked


def _plan(plan,observation):
    """Use native ordering/selection only; never inspect stake or money values."""
    _need(type(plan) is dict and plan.get('kind') in ('PROBABILITY','SELECTION') and
          type(plan.get('top')) is list and type(plan.get('ticket_count')) is int and
          len(plan['top'])==plan['ticket_count'] and 0<=plan['ticket_count']<=8,'NATIVE_PLAN')
    top=plan['top'];winner=observation['ordered_top3'];roster=observation['roster']
    _need(plan.get('roster')==roster and len({tuple(t) for t in top})==len(top) and all(
        type(t) is list and len(t)==3 and len(set(t))==3 and all(type(n) is int and str(n) in roster for n in t)
        for t in top),'NATIVE_TICKETS')
    selected=bool(top)
    answer=dict(kind=plan['kind'],selection_status=plan['selection_status'],ticket_count=len(top),selected=selected,
        hit=winner in top if selected else None,top1_hit=top[0]==winner if selected else None,
        winner_rank=None,winner_probability=None,log_loss=None)
    if plan['kind']=='PROBABILITY':
        ranked=plan.get('ranked');n=len(roster)
        _need(type(ranked) is list and len(ranked)==n*(n-1)*(n-2) and all(type(row) is dict and
            type(row.get('score')) in (int,float) and math.isfinite(row['score']) and 0<=row['score']<=1
            for row in ranked),'NATIVE_PROBABILITY')
        _need(len({tuple(row['combination']) for row in ranked})==len(ranked) and
            math.isclose(math.fsum(row['score'] for row in ranked),1.,abs_tol=1e-8),'NATIVE_PROBABILITY_MASS')
        position=next((i for i,row in enumerate(ranked,1) if row['combination']==winner),None)
        _need(position is not None,'NATIVE_WINNING_ORDER_ABSENT')
        probability=ranked[position-1]['score']
        answer.update(winner_rank=position,winner_probability=probability,log_loss=-math.log(max(probability,1e-15)))
    return answer


def _score_plans(baseline,learned,observation):
    arms={name:_plan(plan,observation) for name,plan in (('baseline',baseline),('learned',learned))}
    paired=arms['baseline']['selected'] and arms['learned']['selected']
    return dict(state='ORDER_CONFIRMED_PAIRED' if paired else 'NATIVE_ABSTENTION_UNPAIRED',paired=paired,
        native_selection_changed=baseline['top']!=learned['top'],ticket_count_changed=len(baseline['top'])!=len(learned['top']),**arms)


def _score(pair,observation):
    if observation is None:return dict(state='NO_ORDER_ONLY_TEACHER',paired=False)
    baseline=pair['baseline_normalized'];learned=pair['learned_normalized']
    value=_score_plans(baseline,learned,observation)
    if 'plans' in baseline or 'plans' in learned:
        for plan in (baseline,learned):
            _need(plan['kind']=='SELECTION' and type(plan.get('plans')) is dict and
                set(plan['plans']) in (set(),{'three','five'}),'NATIVE_PLAN_VARIANTS')
            if not plan['plans']:_need(plan['top']==[] and plan['ticket_count']==0,'NATIVE_ABSTENTION_PLAN')
        variants={}
        for name in ('three','five'):
            arms=[]
            for plan in (baseline,learned):
                variant=dict(plan,**plan['plans'].get(name,{}));variant.pop('plans',None);arms.append(variant)
            variants[name]=_score_plans(*arms,observation)
        _need(value==variants['five'],'NATIVE_PRIMARY_PLAN_BINDING')
        value.update(primary_native_plan='five',native_plan_variants=variants)
    return value


def _board(rows):
    matched=[r for r in rows if r['result_observation_sha256'] is not None]
    paired=[r for r in matched if r['score']['paired']]
    result=dict(teacher_matched_forecasts=len(matched),paired_forecasts=len(paired),
        paired_cohort_sha256=digest(sorted((r['forecast_record_sha256'],r['result_observation_sha256']) for r in paired)),
        native_selection_changed_count=sum(r['score']['native_selection_changed'] for r in matched))
    for arm in ('baseline','learned'):
        values=[r['score'][arm] for r in paired];losses=[v['log_loss'] for v in values if v['log_loss'] is not None]
        ranks=[v['winner_rank'] for v in values if v['winner_rank'] is not None]
        selected=sum(r['score'][arm]['selected'] for r in matched)
        result[arm]=dict(forecasts=len(values),hits=sum(v['hit'] is True for v in values),
            top1_hits=sum(v['top1_hit'] is True for v in values),selected_forecasts=selected,
            abstained_forecasts=len(matched)-selected,coverage=selected/len(matched) if matched else None,
            probability_scored_forecasts=len(losses),mean_log_loss=math.fsum(losses)/len(losses) if losses else None,
            mean_winner_rank=math.fsum(ranks)/len(ranks) if ranks else None)
    variants={name for row in matched for name in row['score'].get('native_plan_variants',{})}
    if variants:
        result.update(primary_native_plan='five',native_plan_variants={name:_board([
            dict(row,score=row['score']['native_plan_variants'][name]) for row in matched]) for name in sorted(variants)})
    return result


def _summary(admission,rows,context,now):
    typed=_typed_results(context,now)
    cases={_key(row) for row in rows}
    return dict(schema=COUNTS_SCHEMA,state='ORDER_ONLY_FROZEN_NATIVE_INPUTS_NO_FORECASTS' if not rows else
        'PRIVATE_ORDER_ONLY_PDCA_SCORED' if any(r['score']['paired'] for r in rows) else 'PRIVATE_ORDER_ONLY_PDCA_PENDING',evaluation_scope=EVALUATION_SCOPE,monetary_evaluation_available=False,
        partition_count=len(rows),baseline_forecast_count=len(rows),learned_forecast_count=len(rows),
        paired_forecasts=sum(r['score']['paired'] for r in rows),order_only_result_count=len(typed),
        unmatched_order_only_results=len(set(typed)-cases),
        outside_order_only_result_state_counts=dict(Counter(o['status'] for o in context['observations'] if not has_order_only_markers(o))),
        result_state_counts=dict(Counter(r['score']['state'] for r in rows)),
        scoreboard={cell:_board([r for r in rows if r['cell_key']==cell]) for cell in sorted({r['cell_key'] for r in rows})},
        source_artifact_id=admission['artifact_id'],source_artifact_digest=admission['artifact_digest'],
        source_workflow_run_id=admission['workflow_run_id'],source_head_sha=admission['head_sha'],
        result_artifact_id=context['receipt']['artifact_id'],result_artifact_digest=context['receipt']['digest'],
        training_sha256=admission['training_sha256'],independent_pre_cutoff_receipt_verified=True,
        independent_result_artifact_receipt_verified=True,independent_pdca_artifact_receipt_verified=False,
        paired_cohorts_within_cells_only=True,cross_model_equal_cohort_comparison_claimed=False,
        provider_permission_confirmed=False,baseline_coefficients_changed=False,production_promoted=False,
        actual_purchases=False,accuracy_improvement_proven=False,plaintext_published=False)


def _row(forecast,observation,now):
    pair=forecast['pair']
    return dict(cell_key=pair['cell_key'],sport=pair['sport'],race_id=pair['race_id'],evaluated_at=now.isoformat(),
        forecast_record_sha256=digest(forecast),native_input_sha256=pair['input_sha256'],
        result_observation_sha256=digest(observation) if observation is not None else None,score=_score(pair,observation))


def verify_private_order_only_pdca(payload):
    """Replay private evidence only after authenticated owner-codec readback."""
    try:
        _need(type(payload) is dict and set(payload)==FIELDS and payload['schema']==SCHEMA and payload['training'] is None,
            'PAYLOAD_SCHEMA')
        now=_time(payload['evaluated_at']);forecast=payload['private_forecast'];verify_private_pair(forecast)
        admission=payload['source_forecast'];metadata=payload['source_native_metadata']
        _need(admission.get('independent_pre_cutoff_receipt_verified') is True and digest(forecast) in admission['record_sha256'] and
            admission['training_sha256']==forecast['training']['training_sha256'] and
            admission['artifact_id']==metadata['id'] and admission['artifact_digest']==metadata['digest'] and
            admission['saved_at']==metadata['created_at'] and admission['workflow_run_id']==metadata['workflow_run']['id'] and
            admission['head_sha']==metadata['workflow_run']['head_sha'] and
            _time(forecast['generated_at'])<_time(admission['saved_at'])+timedelta(seconds=1)<
            _time(forecast['pair']['cutoff_at']) and _time(admission['saved_at'])<=now,'SOURCE_NATIVE_BINDING')
        native_run=metadata.get('workflow_run')
        _need(metadata.get('expired') is False and type(metadata.get('size_in_bytes')) is int and
            0<metadata['size_in_bytes']<=MAX_ARCHIVE_BYTES and type(metadata.get('name')) is str and
            re.fullmatch('all-existing-model-pairs-'+str(admission['workflow_run_id'])+'-[1-9][0-9]*',metadata['name']) and
            metadata['name']==admission.get('artifact_name') and type(native_run) is dict and
            all(type(native_run.get(k)) is int and native_run[k]==official.REPOSITORY_ID
                for k in ('repository_id','head_repository_id')) and
            _time(metadata['created_at'])<=now<_time(metadata['expires_at']),'SOURCE_NATIVE_RECEIPT')
        _payload_clock(forecast,_time(metadata['created_at']),now)
        _need(type(payload['additional_native_admissions']) is list and len(payload['additional_native_admissions'])<=30 and
            all(type(value) is dict and value.get('independent_pre_cutoff_receipt_verified') is True
                for value in payload['additional_native_admissions']),'ADDITIONAL_NATIVE_ADMISSIONS')
        context=payload['result_context']
        _need(payload['source_result']==context['receipt'],'SOURCE_RESULT_BINDING')
        typed=_typed_results(context,now);expected=typed.get(_key(forecast['pair']))
        observation=payload['observation'];proof=payload['result_source_evidence']
        if expected is None:
            _need(observation is None and proof is None and payload['result_observation_sha256'] is None,'UNMATCHED_RESULT')
        else:
            _need((observation,proof)==expected and payload['result_observation_sha256']==digest(observation),'ORIGINAL_RESULT_BINDING')
            _observation(observation,proof,forecast['pair'],context,now)
        row=_row(forecast,observation,now)
        _need(payload['score']==row['score'] and payload['summary']==_summary(admission,[row],context,now),'SCORE_REPLAY')
        return True
    except (KeyError,TypeError,AttributeError,IndexError,StopIteration) as exc:
        raise ValueError('ALL_MODEL_ORDER_ONLY_PDCA_PAYLOAD_INVALID') from exc


def _frozen(records):
    values=[];seen=set()
    for record in records:
        natives=[c['native_payload'] for c in record.get('captured_native_inputs',[])]
        if 'pair' in record:natives.append(record['native_payload'])
        for native in natives:
            snapshot=native.get('snapshot',{})
            if snapshot.get('schema') not in (DENSE,SCHEMA_SPARSE) or snapshot.get('race',{}).get('sport') not in ('autorace','keirin','horse'):continue
            fingerprint=digest(snapshot)
            if fingerprint not in seen:values.append(deepcopy(native));seen.add(fingerprint)
    return values


def score_order_only_pairs_artifacts(native_raw,native_metadata,result_raw,result_metadata,output,*,now,
    expected_native_run_id,expected_native_head_sha,expected_result_run_id,expected_result_head_sha,additional_native_artifacts=()):
    """Explicit rank-only mode; authenticate both real archives before any score.

    Actual GitHub metadata must be fetched by the caller. Additional native
    archives authenticate the other frozen cases in a full-day RESULT archive;
    they never acquire forecasts or become losses. Only archive-produced exact
    rank_confirmed labels are scored. Cash/pending/special remain outside scope.
    """
    state_key('production');now=_clock(now);root=_output(output)
    admission,records=_verified_private_pairs_artifact(native_raw,native_metadata,now=now,
        expected_run_id=expected_native_run_id,expected_head_sha=expected_native_head_sha)
    _need(type(additional_native_artifacts) in (tuple,list) and len(additional_native_artifacts)<=30,'ADDITIONAL_NATIVE_BOUND')
    total=len(native_raw)+len(result_raw);all_records=list(records);extra=[];identities={native_metadata['id'],result_metadata['id']}
    _need(len(identities)==2,'DISTINCT_SOURCE_ARTIFACTS')
    for item in additional_native_artifacts:
        _need(type(item) is dict and set(item)=={'raw','metadata','expected_run_id','expected_head_sha'} and
            type(item['raw']) is bytes and type(item['metadata']) is dict,'ADDITIONAL_NATIVE_SCHEMA')
        total+=len(item['raw']);_need(total<=MAX_TOTAL_INPUT_BYTES and item['metadata'].get('id') not in identities,'ADDITIONAL_NATIVE_BOUND')
        current,parts=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=item['expected_run_id'],expected_head_sha=item['expected_head_sha'])
        identities.add(item['metadata']['id']);all_records.extend(parts);extra.append(current)
    _need(total<=MAX_TOTAL_INPUT_BYTES,'TOTAL_SOURCE_BOUND')
    result=official.observations_from_official_result_artifact(result_raw,result_metadata,now=now,
        expected_run_id=expected_result_run_id,expected_head_sha=expected_result_head_sha,
        frozen_native_payloads=_frozen(all_records),allow_order_only=True)
    context=dict(receipt=deepcopy(result['receipt']),observations=deepcopy(result['observations']),
        source_evidence=deepcopy(result.get('result_source_evidence',[])),observations_sha256=digest(result['observations']))
    typed=_typed_results(context,now);forecasts=[record for record in records if 'pair' in record];rows=[];payloads=[]
    for forecast in forecasts:
        verify_private_pair(forecast);matched=typed.get(_key(forecast['pair']))
        observation,proof=matched if matched is not None else (None,None)
        if observation is not None:_observation(observation,proof,forecast['pair'],context,now)
        row=_row(forecast,observation,now);rows.append(row)
        payload=dict(schema=SCHEMA,evaluated_at=now.isoformat(),training=None,summary=_summary(admission,[row],context,now),
            source_forecast=deepcopy(admission),source_native_metadata=deepcopy(native_metadata),source_result=deepcopy(result['receipt']),
            additional_native_admissions=deepcopy(extra),result_context=deepcopy(context),private_forecast=deepcopy(forecast),
            observation=deepcopy(observation),result_observation_sha256=digest(observation) if observation is not None else None,
            result_source_evidence=deepcopy(proof),score=deepcopy(row['score']))
        verify_private_order_only_pdca(payload);payloads.append(payload)
    summary=_summary(admission,rows,context,now)
    root.mkdir(parents=True,mode=0o700,exist_ok=False);private_root(root)
    for payload in payloads:
        status=seal_candidate(payload,root/partition_key(payload['private_forecast']['pair']))
        _need(status.get('encrypted_readback_verified') is True,'LOCAL_READBACK')
    summary['encrypted_readback_verified']=True
    _write(root.with_name(root.name+'.summary.json'),_bytes(summary))
    return summary


def verify_order_only_pdca_artifact(raw,metadata,*,now,expected_run_id,expected_head_sha):
    """Independently admit the saved scoring ZIP and replay every opaque part."""
    state_key('production');now=_clock(now)
    _need(type(expected_run_id) is int and expected_run_id>0 and type(expected_head_sha) is str and
        re.fullmatch('[a-f0-9]{40}',expected_head_sha),'EXPECTED_RUN')
    _need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE_BYTES and type(metadata) is dict and
        type(metadata.get('id')) is int and metadata['id']>0 and metadata.get('expired') is False and
        type(metadata.get('name')) is str and re.fullmatch('all-existing-model-order-only-pdca-'+str(expected_run_id)+'-[1-9][0-9]*',metadata['name']),
        'PDCA_ARTIFACT_IDENTITY')
    run=metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id']==expected_run_id and
        run.get('head_sha')==expected_head_sha and all(type(run.get(k)) is int and run[k]==official.REPOSITORY_ID for k in ('repository_id','head_repository_id')) and
        type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes']==len(raw) and metadata.get('digest')=='sha256:'+sha256(raw).hexdigest(),'PDCA_ARTIFACT_BYTES')
    _need(type(metadata.get('created_at')) is str and type(metadata.get('expires_at')) is str,'PDCA_ARTIFACT_CLOCK')
    saved=_time(metadata['created_at']);_need(saved<=now<_time(metadata['expires_at']),'PDCA_ARTIFACT_CLOCK')
    rows=[];payloads=[]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
            groups=_entries(zipped)
            with tempfile.TemporaryDirectory(prefix='order-only-pdca-readback-') as temporary:
                for index,(key,entries) in enumerate(sorted(groups.items())):
                    root=Path(temporary)/str(index);root.mkdir(mode=0o700);public=None
                    for name,entry in entries.items():
                        with zipped.open(entry) as stream:body=stream.read(MEMBER_LIMITS[name]+1)
                        _need(len(body)==entry.file_size,'PDCA_MEMBER_SIZE');_write(root/name,body)
                        if name=='summary.json':public=read_json_bytes(body)
                    payload=read_candidate(root);verify_private_order_only_pdca(payload)
                    _need(public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False) and
                        key==partition_key(payload['private_forecast']['pair']) and
                        _time(payload['evaluated_at'])<saved+timedelta(seconds=1) and _time(payload['evaluated_at'])<=now,'PDCA_PARTITION_BINDING')
                    payloads.append(payload);rows.append(_row(payload['private_forecast'],payload['observation'],_time(payload['evaluated_at'])))
    except (zipfile.BadZipFile,RuntimeError,EOFError,zlib.error) as exc:
        raise ValueError('ALL_MODEL_ORDER_ONLY_PDCA_ARCHIVE_REJECTED') from exc
    _need(bool(payloads) and len({digest(p['source_forecast']) for p in payloads})==1 and
        len({digest(p['result_context']) for p in payloads})==1 and
        len({digest(p['additional_native_admissions']) for p in payloads})==1 and
        len({p['evaluated_at'] for p in payloads})==1,'MIXED_SCORE_CONTEXTS')
    admission=payloads[0]['source_forecast']
    _need(len(rows)==admission['forecast_partition_count'] and len({r['forecast_record_sha256'] for r in rows})==len(rows),
        'COMPLETE_FORECAST_SET_REQUIRED')
    summary=_summary(admission,rows,payloads[0]['result_context'],_time(payloads[0]['evaluated_at']))
    return dict(summary,encrypted_readback_verified=True,independent_pdca_artifact_receipt_verified=True,
        pdca_artifact_id=metadata['id'],pdca_artifact_digest=metadata['digest'],pdca_saved_at=metadata['created_at'])
