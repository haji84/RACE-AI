"""Native-objective research fitting for every existing catalog cell.

Callers authenticate frozen inputs and admit their source use before passing
real records. Synthetic cohorts remain explicitly synthetic. No model family,
default coefficient, prediction original or production selection is replaced.
"""
from collections import Counter,defaultdict
from copy import deepcopy
from datetime import datetime,timedelta
import math
import re

from .actions_contract import digest
from . import all_existing_model_registry as registry
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED,FEATURE_RANGES,WEIGHTS
from .observed_weight_learning import ts,fit_from_verified,_gradient,vectors,seal
from .existing_model_dispatch import _race_key
from .four_sport_learning import LEARNED_ID

SCHEMA='RACE_AI_ALL_EXISTING_MODEL_FIT_V1'
MIN_RACES=8

def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_LEARNING_'+reason)

def records_from_observed(rows,observations):
    """Lossless bridge from the authenticated existing journal reader only."""
    results={o['race_id']:o for o in observations};out=[]
    from .frozen_day_cycle import settle
    for row in rows:
        if row.get('model_id') not in OBSERVED or row.get('learning_snapshot') is None:continue
        result=results.get(row['race_id'])
        if result is None:continue
        verdict=settle(row,result)
        if verdict['state'] not in ('HIT','MISS'):continue
        snap=deepcopy(row['learning_snapshot']);payload=dict(snapshot=snap,scope=snap['scope'])
        label=dict(race_id=row['race_id'],sport='boat',status='settled',
            ordered_top3=verdict['winning_combination'],captured_at=result['captured_at'],
            published_at=None,source_ref=result['source_url'],
            source_rights_ref='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106',
            source_sha256=result['source_sha256'],identity_verified=result.get('body_identity_verified') is True,
            roster=deepcopy(row['roster']),payout_per_100_yen=verdict['payout_per_100_yen'],refund_numbers=[])
        out.append(dict(model_id=row['model_id'],sport='boat',race_id=row['race_id'],stage=row['stage'],
            scope=snap['scope'],as_of=row['as_of'],cutoff_at=row['cutoff_at'],native_payload=payload,
            input_sha256=digest(payload),input_saved_at=row['server_saved_at'],
            input_receipt=deepcopy(row.get('input_receipt',dict(artifact_id=row['artifact_id']))),
            result=label,observed_row=deepcopy(row),observed_result=deepcopy(result)))
    return out

def _sources(payload):
    pairs=set()
    def visit(value):
        if type(value) is dict:
            url=value.get('source_url',value.get('source_ref'));rights=value.get('source_rights_ref')
            if type(url) is str and type(rights) is str:pairs.add((url,rights))
            for child in value.values():visit(child)
        elif type(value) in (list,tuple):
            for child in value:visit(child)
    visit(payload);return pairs

GENERATION_SCHEMA='RACE_AI_AUTHENTICATED_NATIVE_GENERATION_CLOCK_V1'

def _native_generation_evidence(row,*,now):
    """Use a retained physical generation clock, never manufacture a replay time.

    Actual decryption and fresh external metadata admission belong to the
    input reader. This checks the reader's complete receipt/partition binding
    again. Legacy journal records have no partitions and keep their old clock.
    """
    if 'input_partitions' not in row:return None
    need(type(now) is datetime and now.utcoffset() is not None,'NATIVE_GENERATION_CLOCK_REQUIRED')
    parts=row['input_partitions'];receipt=row.get('input_receipt')
    need(type(parts) is list and 1<=len(parts)<=31 and type(receipt) is dict and
         receipt.get('independent_pre_cutoff_receipt_verified') is True and
         type(receipt.get('artifact_metadata')) is dict,'NATIVE_GENERATION_RECEIPT_REQUIRED')
    metadata=receipt['artifact_metadata'];run=metadata.get('workflow_run')
    need(type(receipt.get('artifact_id')) is int and 0<receipt['artifact_id']<10**20 and
         type(metadata.get('id')) is int and metadata['id']==receipt['artifact_id'] and metadata.get('expired') is False and
         type(receipt.get('workflow_run_id')) is int and 0<receipt['workflow_run_id']<10**20 and
         type(run) is dict and type(run.get('id')) is int and run['id']==receipt['workflow_run_id'] and
         all(type(run.get(k)) is int and run[k]==1416489937 for k in ('repository_id','head_repository_id')) and
         type(receipt.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}',receipt['head_sha']) and
         run.get('head_sha')==receipt['head_sha'],'NATIVE_GENERATION_ARTIFACT_IDENTITY')
    name=receipt.get('artifact_name');run_id=str(receipt['workflow_run_id'])
    private=type(name) is str and re.fullmatch('all-existing-model-pairs-'+run_id+'-[1-9][0-9]*',name)
    round_match=re.fullmatch('boat-all-model-forecasts-'+run_id+r'-r(0|[1-9][0-9]{0,5})',name) \
        if type(name) is str else None
    need(type(name) is str and len(name)<=200 and (private or round_match) and metadata.get('name')==name and
         type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and
         metadata.get('digest')==receipt['digest'] and type(metadata.get('size_in_bytes')) is int and
         0<metadata['size_in_bytes']<=64*1024*1024,'NATIVE_GENERATION_ARTIFACT_BYTES')
    need(all(type(row.get(k)) is str for k in ('as_of','cutoff_at','input_saved_at','stage')) and
         0<len(row['stage'])<=64 and
         all(type(metadata.get(k)) is str for k in ('created_at','expires_at')) and
         type(receipt.get('saved_at')) is str,'NATIVE_GENERATION_CLOCK_BINDING')
    asof=ts(row['as_of']);cutoff=ts(row['cutoff_at']);saved=ts(row['input_saved_at'])
    need(ts(receipt['saved_at'])==ts(metadata['created_at'])==saved and saved<=now<ts(metadata['expires_at']) and
         saved+timedelta(seconds=1)<cutoff,'NATIVE_GENERATION_CLOCK_BINDING')
    hex64=lambda value:type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None
    clocks=[];known={cell['cell_key'] for cell in registry.cells()}
    for part in parts:
        need(type(part) is dict and type(part.get('generated_at')) is str,'NATIVE_GENERATION_PARTITION_FIELDS')
        if private:
            fields={'carrier_cell_key','generated_at','training_sha256'}
            pair='pair_sha256' in part
            fields.add('pair_sha256' if pair else 'native_inputs_record_sha256')
            need(set(part)==fields and hex64(part.get('training_sha256')) and
                 hex64(part.get('pair_sha256' if pair else 'native_inputs_record_sha256')) and
                 (type(part.get('carrier_cell_key')) is str and part['carrier_cell_key'] in known and
                  part['carrier_cell_key'].startswith(row['sport']+'/') if pair else
                  part.get('carrier_cell_key') is None),'NATIVE_GENERATION_PARTITION_FIELDS')
        else:
            need(set(part)=={'native_group','capsule_sha256','generated_at','dispatch_input_sha256'} and
                 part.get('native_group')==receipt.get('native_group')==registry.group(row['model_id']) and
                 all(hex64(receipt.get(k)) for k in ('payload_sha256','cipher_sha256','capsule_sha256',
                     'dispatch_input_sha256','frozen_native_input_sha256','model_input_sha256')) and
                 part.get('capsule_sha256')==receipt['capsule_sha256'] and
                 part.get('dispatch_input_sha256')==receipt['dispatch_input_sha256'] and
                 receipt.get('model_input_sha256')==row['input_sha256'] and
                 receipt.get('saved_stage')==row['stage'] and row['stage'] in ('P0','P1') and
                 receipt.get('stage_binding_semantics')=='CANONICAL_INPUT_FROM_FROZEN_NATIVE_AND_SAVED_STAGE' and
                 receipt.get('authenticated_original_artifact_verified') is True and
                 type(receipt.get('round_no')) is int and receipt['round_no']==int(round_match[1]),
                 'NATIVE_GENERATION_PARTITION_FIELDS')
        generated=ts(part['generated_at'])
        need(asof<=generated<saved+timedelta(seconds=1) and generated<cutoff and generated<=now,
             'NATIVE_GENERATION_CLOCK_BINDING')
        clocks.append(generated)
    need(len(set(clocks))==1 and (not private or len({part['training_sha256'] for part in parts})==1),
         'NATIVE_GENERATION_CONFLICT')
    return dict(actual_native_generated_at=parts[0]['generated_at'],
        native_generation_receipt_sha256=digest(receipt),native_generation_partitions_sha256=digest(parts),
        native_generation_evidence=dict(schema=GENERATION_SCHEMA,stage=row['stage'],
            receipt=deepcopy(receipt),partitions=deepcopy(parts)))

def _native_replay_at(row,*,now=None):
    proof=_native_generation_evidence(row,now=now)
    return proof['actual_native_generated_at'] if proof is not None else row['as_of']

def _lineage(row,*,now=None):
    value=dict(race_id=row['race_id'],input_sha256=row['input_sha256'],as_of=row['as_of'],
        cutoff_at=row['cutoff_at'],input_saved_at=row['input_saved_at'],
        result_captured_at=row['result']['captured_at'],result_sha256=row['result']['source_sha256'])
    if 'input_derivation' in row:
        proof=row['input_derivation']
        value.update(input_derivation={k:deepcopy(v) for k,v in proof.items() if k!='original_record'},
            input_derivation_sha256=digest(proof),input_save_semantics='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND')
    generated=_native_generation_evidence(row,now=now)
    if generated is not None:value.update(generated)
    return value

def _ranker_label(row):
    snapshot=row['native_payload']['snapshot'];sport=row['sport']
    result={k:row['result'].get(k) for k in ('race_id','status','ordered_top3','published_at',
        'captured_at','source_ref','source_rights_ref')}
    # Outer admission already binds each supported alias to the same race.
    need(_race_key(result['race_id'],sport)==_race_key(snapshot['race']['race_id'],sport),'RANKER_RESULT_IDENTITY')
    result['race_id']=snapshot['race']['race_id']
    if snapshot['schema']==registry.SHARED_SPARSE:
        result['source_sha256']=row['result']['source_sha256']
    return result

def _record(row,now,allow_source,allow_training):
    need(type(row) is dict,'RECORD_REQUIRED');mid=row['model_id'];sport=row['sport']
    if 'input_derivation' in row:
        from .all_existing_model_derivation import verify_derivation
        verify_derivation(row,now=now,allow_source=allow_source,allow_training=allow_training)
    registry.specs(mid,sport);payload=row['native_payload']
    from .all_existing_model_source_derivations import validate_source_derivations
    validate_source_derivations(payload)
    need(row['input_sha256']==digest(payload),'INPUT_HASH')
    info=registry.identity(mid,sport,payload,race_id=row['race_id'])
    need(row['scope'] in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH') and row['scope']==info['scope'],'SCOPE')
    need(_race_key(row['race_id'],sport)==_race_key(info['race_id'],sport) and row['stage']==info['stage'] and
         ts(row['as_of'])==ts(info['as_of']) and ts(row['cutoff_at'])==ts(info['cutoff_at']),'INPUT_IDENTITY')
    saved=ts(row['input_saved_at']);asof=ts(row['as_of']);cutoff=ts(row['cutoff_at'])
    need(asof<cutoff and (asof<=saved or saved.microsecond==0 and asof<saved+timedelta(seconds=1)) and saved<cutoff and saved<=now,'INPUT_CLOCK')
    result=row['result'];need(type(result) is dict and result.get('sport')==sport and
        _race_key(result.get('race_id'),sport)==_race_key(row['race_id'],sport),'RESULT_IDENTITY')
    need(ts(result['captured_at'])<=now and ts(result['captured_at'])>=ts(info['race_cutoff_at']),'RESULT_CLOCK')
    need(result.get('status')=='settled' and result.get('identity_verified') is True and not result.get('refund_numbers'),'NORMAL_CONFIRMED_RESULT_REQUIRED')
    need(result.get('roster')==info['roster'],'RESULT_ROSTER')
    winner=result.get('ordered_top3');need(type(winner) is list and len(winner)==3 and len(set(winner))==3 and
        all(type(n) is int and str(n) in info['roster'] for n in winner),'RESULT_ORDER')
    sources=_sources(payload);sources.add((result.get('source_ref'),result.get('source_rights_ref')))
    need(all(type(u) is str and u and type(r) is str and r for u,r in sources),'SOURCE_REQUIRED')
    if row['scope']!='SYNTHETIC_ONLY':
        need(callable(allow_training) and all(allow_training(u,r,'model_training') is True for u,r in sources),'TRAINING_PERMISSION')
    registry.validate_payload(mid,sport,payload,at=_native_replay_at(row,now=now),allow_source=allow_source,race_id=row['race_id'])
    if mid==LEARNED_ID:
        from .four_sport_learning import _label
        # Validate every separate label before choosing a cohort. This checks
        # holdout provenance without exposing it to the coefficient optimizer.
        _label(_ranker_label(row),payload['snapshot'],scope=row['scope'],window_end=now,
            allow_result=lambda source,rights,purpose: purpose=='result_evaluation' and
                (source,rights)==(result['source_ref'],result['source_rights_ref']) and
                callable(allow_training) and allow_training(source,rights,'model_training') is True)
    return deepcopy(row)

def _metrics(rows,parameters,allow_source,*,now=None):
    losses=[];hits=0;selected=0
    for row in rows:
        replay_at=_native_replay_at(row,now=now)
        probability=registry.winning_probability(row['model_id'],row['sport'],row['native_payload'],parameters,
            row['result']['ordered_top3'],at=replay_at,allow_source=allow_source)
        losses.append(-math.log(max(probability,1e-12)))
        prediction=registry.predict(row['model_id'],row['sport'],row['native_payload'],parameters,
                                    at=replay_at,allow_source=allow_source)
        normalized=registry.normalize(row['model_id'],row['sport'],row['native_payload'],prediction,race_id=row['race_id'])
        selected+=bool(normalized['top']);hits+=row['result']['ordered_top3'] in normalized['top']
    selection=bool(rows) and registry.group(rows[0]['model_id'])=='seller'
    return dict(races=len(rows),hits=hits,selected_races=selected,
                mean_log_loss=None if selection else sum(losses)/len(losses) if losses else None,
                mean_selection_loss=(len(rows)-hits)/len(rows) if selection else None,
                loss_kind='NATIVE_FIVE_TICKET_SELECTION_MISS' if selection else 'NATIVE_DISTRIBUTION_LOG_LOSS',
                hit_rate=hits/len(rows) if rows else None,prospective=False)

def _fit_native(train,mid,sport,allow_source,*,now=None):
    spec=registry.specs(mid,sport);base={k:v[0] for k,v in spec.items()};params=dict(base);support={}
    replay_clocks={id(row):_native_replay_at(row,now=now) for row in train}
    if mid in OBSERVED:
        names=list(FEATURE_RANGES);xs=[vectors(r['native_payload']['snapshot']) for r in train]
        support={name:sum(any(abs(x[i][j])>0 for i in x) for x in xs) for j,name in enumerate(names)}
        weights=[params[name] for name in names]
        for _ in range(80):
            gradients=[_gradient(x,row['result']['ordered_top3'],weights)[0] for x,row in zip(xs,train)]
            weights=[min(4.,max(0.,w+.05*(sum(g[j] for g in gradients)/(3*len(train))-.1*(w-base[name]))))
                     if support[name]>=4 else base[name] for j,(name,w) in enumerate(zip(names,weights))]
        return dict(zip(names,weights)),support
    # Coordinate search evaluates the native family, including its mixture,
    # conditional coupling or ticket selection. No PL surrogate is substituted.
    def objective(candidate):
        loss=0.
        for row in train:
            p=registry.winning_probability(mid,sport,row['native_payload'],candidate,
                row['result']['ordered_top3'],at=replay_clocks[id(row)],allow_source=allow_source)
            loss-=math.log(max(p,1e-12))
        penalty=.01*sum(((candidate[k]-base[k])/max(1.,abs(base[k])))**2 for k in candidate)
        return loss/len(train)+penalty
    current=objective(params)
    for name,(default,low,high) in spec.items():
        step=max(abs(default)*.25,(high-low)*.025)
        minus=max(low,default-step);plus=min(high,default+step)
        supported=0
        for row in train:
            a=dict(base,**{name:minus});b=dict(base,**{name:plus})
            pa=registry.winning_probability(mid,sport,row['native_payload'],a,row['result']['ordered_top3'],at=replay_clocks[id(row)],allow_source=allow_source)
            pb=registry.winning_probability(mid,sport,row['native_payload'],b,row['result']['ordered_top3'],at=replay_clocks[id(row)],allow_source=allow_source)
            supported+=abs(pa-pb)>1e-12
        support[name]=supported
        if supported<4:continue
        for value in (minus,plus):
            candidate=dict(params,**{name:value});score=objective(candidate)
            if score<current-1e-12:params,current=candidate,score
    return params,support

def fit(records,*,now,allow_source=None,allow_training=None):
    need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    need(type(records) is list and len(records)<=10000,'BOUNDED_RECORDS')
    selected={};blocked=defaultdict(list)
    for supplied in records:
        key=registry.cell_key(supplied['sport'],supplied['model_id'])
        try:row=_record(supplied,now,allow_source,allow_training)
        except ValueError as exc:
            if str(exc)=='ALL_MODEL_LEARNING_TRAINING_PERMISSION':blocked[key].append('HOLD_MODEL_TRAINING_PERMISSION');continue
            raise
        identity=(key,_race_key(row['race_id'],row['sport']))
        old=selected.get(identity)
        if old is not None:
            if ts(row['as_of'])==ts(old['as_of']):need(digest(row)==digest(old),'CONFLICTING_DUPLICATE')
            if ts(row['as_of'])<=ts(old['as_of']):continue
        selected[identity]=row
    groups=defaultdict(list)
    for (key,_),row in selected.items():groups[key].append(row)
    out=dict(schema=SCHEMA,registry_sha256=registry.registry_sha256(),registered_model_ids=sorted({c['model_id'] for c in registry.cells()}),
        created_at=now.isoformat(),data_available_until=max((r['result']['captured_at'] for r in selected.values()),key=ts,default=now.isoformat()),
        state='NO_FITTED_MODELS',models={},model_states={},auto_promoted=False,production_promoted=False,
        accuracy_improvement_proven=False,provider_permission_confirmed=False,minimum_fit_races=MIN_RACES,
        validation_type='RETROSPECTIVE_AVAILABILITY_ORDERED_HOLDOUT',training_policy=dict(min_train=6,min_holdout=2,minimum_supported_train_races=4),
        source_intake_sha256=digest(records),scope=next(iter({r['scope'] for r in records}),'SYNTHETIC_ONLY'))
    need(len({r['scope'] for r in records})<=1,'MIXED_SCOPE')
    for cell in registry.cells():
        key=cell['cell_key'];rows=sorted(groups[key],key=lambda r:(ts(r['result']['captured_at']),r['race_id']))
        state='HOLD_MODEL_TRAINING_PERMISSION' if blocked[key] else 'INPUT_MISSING' if not rows else 'INSUFFICIENT_VERIFIED_RACES'
        out['model_states'][key]=dict(state=state,unique_races=len(rows),required_input=cell['required_input'])
        if len(rows)<MIN_RACES:continue
        nv=max(2,len(rows)//4);train,holdout=rows[:-nv],rows[-nv:]
        boundary=ts(holdout[0]['result']['captured_at'])
        while train and ts(train[-1]['result']['captured_at'])==boundary:holdout.insert(0,train.pop())
        if len(train)<6:continue
        mid=cell['model_id'];sport=cell['sport']
        schemas={r['native_payload'].get('snapshot',{}).get('schema') for r in rows}
        if mid==LEARNED_ID:need(len(schemas)==1,'MIXED_RANKER_INPUT_SCHEMAS')
        input_schema=next(iter(schemas)) if len(schemas)==1 else None
        base={k:v[0] for k,v in registry.specs(mid,sport,input_schema=input_schema).items()}
        native_training=None
        if mid==LEARNED_ID:
            from .existing_common_parameter_adapters import fit_ranker
            from .four_sport_learning import _vectors, _all_triples
            labeled=[]
            for row in train:
                snapshot=row['native_payload']['snapshot']
                labeled.append(dict(snapshot=snapshot,result=_ranker_label(row)))
            admitted_results={(row['result']['source_ref'],row['result']['source_rights_ref']) for row in train}
            def ranker_result_admission(source,rights,purpose):
                # _record independently admitted these exact result sources
                # for training. Adapt the native learner's evaluation-purpose
                # callback without widening the caller's purpose authorizer.
                return (purpose=='result_evaluation' and (source,rights) in admitted_results and
                        callable(allow_training) and allow_training(source,rights,'model_training') is True)
            native_training=fit_ranker(labeled,sport=sport,now=now,
                train_end_at=max(r['result']['captured_at'] for r in train),allow_source=allow_source,
                allow_result=ranker_result_admission)
            names=list(native_training['vector_schema'])
            native_rows=[(_vectors(row['native_payload']['snapshot'],sport),row['result']['ordered_top3'])
                         for row in sorted(train,key=lambda row:row['race_id'])]
            support={name:sum(max(vector[j] for vector in vectors.values())-
                              min(vector[j] for vector in vectors.values())>1e-12
                              for vectors,_finish in native_rows) for j,name in enumerate(names)}
            # Use the same native deterministic gradient kernel and bounds.
            # Unsupported columns remain at base throughout optimization;
            # post-fit masking would already have affected other coefficients.
            weights=[base[name] for name in names]
            for _ in range(native_training['epochs']):
                for vectors,finish in native_rows:
                    gradient,_loss=_gradient(vectors,finish,weights)
                    weights=[max(-8.,min(8.,weight+native_training['learning_rate']*(
                        gradient[j]/3-native_training['l2']*weight)))
                        if support[name]>=4 else base[name]
                        for j,(name,weight) in enumerate(zip(names,weights))]
            native_training.update(weights=weights,parameter_support_train=deepcopy(support),
                minimum_supported_train_races=4,
                support_policy='PER_RACE_DISCRIMINATING_NATIVE_VECTOR_COLUMNS')
            seal(native_training,'model_sha256')
            parameters=dict(zip(names,weights))
            def ranker_retrospective_metrics(cohort,candidate_weights):
                losses=[];hits=0
                for row in cohort:
                    # The current artifact did not exist at these old races.
                    # Native distribution scoring is retrospective and never
                    # bypasses public forecast's artifact-creation chronology.
                    ranked=_all_triples(_vectors(row['native_payload']['snapshot'],sport),candidate_weights)
                    winning=row['result']['ordered_top3']
                    probability=next(item['score'] for item in ranked if item['combination']==winning)
                    losses.append(-math.log(max(probability,1e-300)))
                    hits+=winning in [item['combination'] for item in ranked[:8]]
                n=len(cohort)
                return dict(races=n,hits=hits,selected_races=n,
                    mean_log_loss=math.fsum(losses)/n if n else None,hit_rate=hits/n if n else None,
                    prospective=False,validation_type='RETROSPECTIVE_NATIVE_DISTRIBUTION')
            metrics=ranker_retrospective_metrics(train,weights)
            validation=ranker_retrospective_metrics(holdout,weights)
            baseline_metrics=ranker_retrospective_metrics(holdout,[base[name] for name in names])
        elif mid in OBSERVED and all(r.get('observed_row') and r.get('observed_result') for r in rows):
            # Preserve the already-validated real-data fitter, equations,
            # cohort boundaries, masks, support and baseline metrics exactly.
            source_rows=[r['observed_row'] for r in rows]
            source_results={r['observed_result']['race_id']:r['observed_result'] for r in rows}
            native_training=fit_from_verified(source_rows,list(source_results.values()),now=now)
            need(native_training['state']=='FITTED_SHADOW_ONLY','LEGACY_OBSERVED_NOT_FITTED')
            native=native_training['models'][mid]
            parameters=dict(zip(FEATURE_RANGES,native['weights']))
            support=deepcopy(native_training['feature_support_train'])
            metrics=deepcopy(native['training']);validation=deepcopy(native['holdout']);baseline_metrics=deepcopy(native['holdout_baseline'])
        else:
            parameters,support=_fit_native(train,mid,sport,allow_source,now=now)
            metrics=_metrics(train,parameters,allow_source,now=now);validation=_metrics(holdout,parameters,allow_source,now=now)
            baseline_metrics=_metrics(holdout,base,allow_source,now=now)
        model=dict(model_id=mid,sport=sport,state='FITTED_SHADOW_ONLY',parameters=parameters,base_parameters=base,
            parameter_support_train=support,unique_races=len(rows),train_races=len(train),validation_races=len(holdout),
            train_race_ids=[r['race_id'] for r in train],validation_race_ids=[r['race_id'] for r in holdout],
            training=metrics,holdout=validation,holdout_baseline=baseline_metrics,
            coefficients_changed=parameters!=base,native_training=native_training,
            source_lineage=[_lineage(r,now=now) for r in rows])
        if input_schema in (registry.SHARED_SPARSE,registry.FULL_SPARSE):
            model.update(input_schema=input_schema,parameter_contract_sha256=digest(
                registry.parameter_contract(mid,sport,input_schema=input_schema)))
        seal(model,'model_sha256');out['models'][key]=model
        out['model_states'][key].update(state='FITTED_SHADOW_ONLY',train_races=len(train),validation_races=len(holdout))
    if out['models']:out['state']='FITTED_SHADOW_ONLY'
    return seal(out,'training_sha256')

def verify_training(training):
    """Validate native parameters, readiness, cohorts and source-clock closure."""
    import re
    from .frozen_day_cycle import check_clock

    def timestamp(value):
        need(type(value) is str and 0<len(value)<=64,'TIMESTAMP')
        return ts(value)

    def hash_value(value):
        return type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None

    def identities(values,sport):
        need(type(values) is list and all(type(v) is str and 0<len(v)<=250 for v in values),'COHORT_IDS')
        result=[_race_key(v,sport) for v in values]
        need(len(result)==len(set(result)),'DUPLICATE_COHORT_ID')
        return set(result)

    def metrics(value,n,*,optional=False):
        if optional and value is None:return
        need(type(value) is dict and type(value.get('races')) is int and value['races']==n and
             value.get('prospective') is False,'METRIC_COHORT')

    try:
        need(type(training) is dict and training.get('schema')==SCHEMA and
             hash_value(training.get('training_sha256')) and
             training['training_sha256']==digest({k:v for k,v in training.items() if k!='training_sha256'}),'INTEGRITY')
        cells={cell['cell_key']:cell for cell in registry.cells()}
        need(training['registry_sha256']==registry.registry_sha256() and
             training['registered_model_ids']==sorted({c['model_id'] for c in cells.values()}),'REGISTRY_BINDING')
        need(all(training[field] is False for field in ('auto_promoted','production_promoted',
             'accuracy_improvement_proven','provider_permission_confirmed')),'PROMOTION')
        need(training['scope'] in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH') and
             hash_value(training['source_intake_sha256']),'SCOPE')
        need(type(training['minimum_fit_races']) is int and training['minimum_fit_races']==MIN_RACES and
             training['validation_type']=='RETROSPECTIVE_AVAILABILITY_ORDERED_HOLDOUT' and
             training['training_policy']==dict(min_train=6,min_holdout=2,minimum_supported_train_races=4) and
             all(type(v) is int for v in training['training_policy'].values()),'TRAINING_POLICY')
        created=timestamp(training['created_at']);available=timestamp(training['data_available_until'])
        need(available<=created,'CREATION_CLOCK')
        models=training['models'];states=training['model_states']
        need(type(models) is dict and type(states) is dict and set(states)==set(cells) and
             set(models)<=set(cells),'CELL_ROSTER')
        allowed={'INPUT_MISSING','HOLD_MODEL_TRAINING_PERMISSION','INSUFFICIENT_VERIFIED_RACES','FITTED_SHADOW_ONLY'}
        for key,state in states.items():
            need(type(state) is dict and state.get('state') in allowed and
                 type(state.get('unique_races')) is int and state['unique_races']>=0 and
                 state.get('required_input')==cells[key]['required_input'],'MEMBER_STATE')
            need((state['state']=='FITTED_SHADOW_ONLY')==(key in models),'MEMBER_STATE')
            need(state['state']!='INPUT_MISSING' or state['unique_races']==0,'MEMBER_STATE')
        need(training['state'] in ('FITTED_SHADOW_ONLY','NO_FITTED_MODELS') and
             (training['state']=='FITTED_SHADOW_ONLY')==bool(models),'FITTED_STATE')
        for key,model in models.items():
            need(type(model) is dict and key==registry.cell_key(model['sport'],model['model_id']) and
                 model['state']=='FITTED_SHADOW_ONLY' and hash_value(model['model_sha256']) and
                 model['model_sha256']==digest({k:v for k,v in model.items() if k!='model_sha256'}),'MEMBER_INTEGRITY')
            mid,sport=model['model_id'],model['sport'];input_schema=model.get('input_schema')
            if 'input_schema' in model or 'parameter_contract_sha256' in model:
                contract=registry.parameter_contract(mid,sport,input_schema=input_schema)
                need(model.get('parameter_contract_sha256')==digest(contract),'PARAMETER_CONTRACT')
            spec=registry.specs(mid,sport,input_schema=input_schema)
            parameters=registry.validate_parameters(mid,sport,model['parameters'],input_schema=input_schema)
            base={name:values[0] for name,values in spec.items()}
            need(type(model['base_parameters']) is dict and model['base_parameters']==base,'BASE_PARAMETERS')
            registry.validate_parameters(mid,sport,model['base_parameters'],input_schema=input_schema)
            train_n,valid_n,n=model['train_races'],model['validation_races'],model['unique_races']
            need(all(type(count) is int for count in (train_n,valid_n,n)) and
                 train_n>=6 and valid_n>=2 and n>=MIN_RACES and train_n+valid_n==n,'COHORT')
            train_ids=identities(model['train_race_ids'],sport)
            valid_ids=identities(model['validation_race_ids'],sport)
            need(len(train_ids)==train_n and len(valid_ids)==valid_n and not train_ids&valid_ids,'COHORT')
            state=states[key]
            need(state['unique_races']==n and type(state.get('train_races')) is int and
                 type(state.get('validation_races')) is int and state['train_races']==train_n and
                 state['validation_races']==valid_n,'MEMBER_COHORT')
            support=model['parameter_support_train']
            need(type(support) is dict and set(support)==set(spec) and
                 all(type(value) is int and 0<=value<=train_n for value in support.values()),'PARAMETER_SUPPORT')
            need(all(parameters[name]==base[name] for name in spec if support[name]<4),'UNSUPPORTED_PARAMETER_CHANGED')
            need(model['coefficients_changed'] is (parameters!=base),'COEFFICIENT_CHANGE_CLAIM')
            metrics(model['training'],train_n);metrics(model['holdout'],valid_n)
            metrics(model['holdout_baseline'],valid_n,optional=mid==LEARNED_ID)
            lineage=model['source_lineage']
            need(type(lineage) is list and len(lineage)==n,'LINEAGE')
            result_times={}
            for row in lineage:
                need(type(row) is dict and type(row.get('race_id')) is str and
                     hash_value(row.get('input_sha256')) and hash_value(row.get('result_sha256')),'LINEAGE')
                rid=_race_key(row['race_id'],sport)
                need(rid not in result_times,'DUPLICATE_LINEAGE_ID')
                asof=timestamp(row['as_of']);cutoff=timestamp(row['cutoff_at'])
                saved=timestamp(row['input_saved_at']);result_at=timestamp(row['result_captured_at'])
                check_clock(row['as_of'],row['cutoff_at'],row['input_saved_at'])
                need(asof<=result_at and saved<=result_at and cutoff<=result_at<=available,'LINEAGE_CLOCK')
                generation_fields={'actual_native_generated_at','native_generation_receipt_sha256',
                    'native_generation_partitions_sha256','native_generation_evidence'}
                if generation_fields&set(row):
                    need(generation_fields<=set(row),'NATIVE_GENERATION_LINEAGE_FIELDS')
                    evidence=row['native_generation_evidence']
                    need(type(evidence) is dict and set(evidence)=={'schema','stage','receipt','partitions'} and
                         evidence['schema']==GENERATION_SCHEMA,'NATIVE_GENERATION_LINEAGE_FIELDS')
                    replay=dict(model_id=mid,sport=sport,race_id=row['race_id'],input_sha256=row['input_sha256'],
                        as_of=row['as_of'],cutoff_at=row['cutoff_at'],input_saved_at=row['input_saved_at'],
                        stage=evidence['stage'],input_receipt=evidence['receipt'],input_partitions=evidence['partitions'])
                    expected=_native_generation_evidence(replay,now=created)
                    need(expected is not None and all(row[name]==expected[name] for name in generation_fields),
                         'NATIVE_GENERATION_LINEAGE_BINDING')
                if any(name in row for name in ('input_derivation','input_derivation_sha256','input_save_semantics')):
                    from .all_existing_model_derivation import (SCHEMA as DERIVATION_SCHEMA,DERIVATION_ID,
                        AVAILABILITY_BASIS,NATIVE_SCHEMA,NATIVE_DERIVATION_ID,NATIVE_AVAILABILITY_BASIS)
                    proof=row.get('input_derivation')
                    need(type(proof) is dict,'DERIVATION_LINEAGE')
                    native_proof=proof.get('schema')==NATIVE_SCHEMA
                    fields={'schema','derivation_id','derived_at','original_record_sha256','original_model_id',
                        'original_payload_sha256','original_snapshot_sha256','original_input_receipt',
                        'original_input_saved_at','original_as_of','original_cutoff_at','native_input_sha256',
                        'data_availability_basis','derived_payload_saved_before_cutoff'}
                    if native_proof:fields|={'original_input_receipt_sha256','historical_native_payload_bytes'}
                    need(set(proof)==fields and
                        proof['schema']==(NATIVE_SCHEMA if native_proof else DERIVATION_SCHEMA) and
                        proof['derivation_id']==(NATIVE_DERIVATION_ID if native_proof else DERIVATION_ID) and
                        proof['data_availability_basis']==(NATIVE_AVAILABILITY_BASIS if native_proof else AVAILABILITY_BASIS) and
                        proof['derived_payload_saved_before_cutoff'] is False and
                        (not native_proof or proof['historical_native_payload_bytes'] is False) and
                        row.get('input_save_semantics')=='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND' and
                        hash_value(row.get('input_derivation_sha256')),'DERIVATION_LINEAGE')
                    need(sport=='boat' and registry.group(mid) in ('shared','shared_learned','boat_full') and
                        all(hash_value(proof[field]) for field in ('original_record_sha256','original_payload_sha256',
                        'original_snapshot_sha256','native_input_sha256')) and proof['original_model_id'] in OBSERVED and
                        type(proof['original_input_receipt']) is dict and bool(proof['original_input_receipt']) and
                        proof['native_input_sha256']==row['input_sha256'] and
                        proof['original_as_of']==row['as_of'] and proof['original_cutoff_at']==row['cutoff_at'] and
                        proof['original_input_saved_at']==row['input_saved_at'] and
                        saved<=timestamp(proof['derived_at'])<=created,'DERIVATION_LINEAGE_BINDING')
                    if native_proof:
                        need(hash_value(proof['original_input_receipt_sha256']) and
                             proof['original_input_receipt_sha256']==digest(proof['original_input_receipt']),
                             'DERIVATION_LINEAGE_BINDING')
                result_times[rid]=result_at
            need(set(result_times)==train_ids|valid_ids,'LINEAGE_COHORT')
            need(max(result_times[rid] for rid in train_ids)<min(result_times[rid] for rid in valid_ids),
                 'CHRONOLOGICAL_COHORT')
            native=model.get('native_training')
            if mid in OBSERVED and native is not None:
                from .observed_weight_learning import verify_training as verify_observed
                need(type(native) is dict and native.get('schema')=='RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1',
                     'NATIVE_TRAINING_SCHEMA')
                verify_observed(native)
                need(native['state']=='FITTED_SHADOW_ONLY' and native['target_scope']==training['scope'] and
                     mid in native['models'] and native['models'][mid]['weights']==[parameters[name] for name in FEATURE_RANGES] and
                     identities(native['train_race_ids'],sport)==train_ids and
                     identities(native['validation_race_ids'],sport)==valid_ids,'NATIVE_TRAINING_BINDING')
                need(timestamp(native['data_available_until'])<=available and timestamp(native['created_at'])<=created,
                     'NATIVE_TRAINING_CLOCK')
            elif mid==LEARNED_ID:
                from .four_sport_learning import vector_schema, VECTOR_VERSION, TRAIN_ONLY_VERSION, sparse_versions
                sparse=input_schema==registry.SHARED_SPARSE
                versions=sparse_versions(sport) if sparse else dict(
                    vector_version=VECTOR_VERSION,train_only_version=TRAIN_ONLY_VERSION)
                need(type(native) is dict and native.get('model_id')==mid and native.get('sport')==sport and
                     hash_value(native.get('model_sha256')) and
                     native['model_sha256']==digest({k:v for k,v in native.items() if k!='model_sha256'}),
                     'NATIVE_TRAINING_INTEGRITY')
                need(native['trained_scope']==training['scope'] and native['vector_version']==versions['vector_version'] and
                     native['model_version']==versions['train_only_version'] and
                     native.get('input_schema',registry.SHARED_SCHEMA)==(registry.SHARED_SPARSE if sparse else registry.SHARED_SCHEMA) and
                     native['vector_schema']==list(vector_schema(sport,sparse=sparse)) and
                     type(native['weights']) is list and
                     all(type(value) in (int,float) for value in native['weights']) and
                     native['weights']==[parameters[name] for name in spec] and
                     type(native['trained_examples']) is int and native['trained_examples']==train_n and
                     native.get('parameter_support_train')==support and
                     native.get('minimum_supported_train_races')==4 and
                     native.get('support_policy')=='PER_RACE_DISCRIMINATING_NATIVE_VECTOR_COLUMNS' and
                     hash_value(native['training_data_sha256']) and
                     identities(native['train_example_ids'],sport)==train_ids,'NATIVE_TRAINING_BINDING')
                need(all(native[field] is False for field in ('calibrated','official_model_approved',
                     'prediction_eligible_without_external_receipt','data_sources_independently_attested',
                     'created_at_independently_attested')),'NATIVE_PROMOTION')
                need(timestamp(native['trained_data_until'])<=timestamp(native['trained_until'])<=
                     timestamp(native['created_at'])<=created and
                     timestamp(native['trained_data_until'])==max(result_times[rid] for rid in train_ids),
                     'NATIVE_TRAINING_CLOCK')
            else:
                need(native is None,'NATIVE_TRAINING_SCHEMA')
    except (KeyError,TypeError,AttributeError,OverflowError) as exc:
        raise ValueError('ALL_MODEL_LEARNING_SCHEMA') from exc
    return True

def forecast_pair(training,cell_key,payload,*,now,allow_source=None):
    verify_training(training);need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    need(ts(training['created_at'])<=now and cell_key in training['models'],'CANDIDATE_NOT_AVAILABLE')
    model=training['models'][cell_key];mid=model['model_id'];sport=model['sport']
    if model.get('input_schema') is not None:
        need(payload.get('snapshot',{}).get('schema')==model['input_schema'],'CANDIDATE_INPUT_SCHEMA')
    info=registry.validate_payload(mid,sport,payload,at=now,allow_source=allow_source)
    need(now<ts(info['cutoff_at']),'FORECAST_CUTOFF')
    past={_race_key(rid,sport) for rid in model['train_race_ids']+model['validation_race_ids']}
    need(_race_key(info['race_id'],sport) not in past,'TRAINING_RACE_REUSED')
    baseline=registry.predict(mid,sport,payload,None,at=now,allow_source=allow_source)
    learned=registry.predict(mid,sport,payload,model['parameters'],at=now,allow_source=allow_source,native_training=model['native_training'])
    pair=dict(schema='RACE_AI_EXISTING_NATIVE_PARAMETER_PAIR_V1',model_id=mid,sport=sport,cell_key=cell_key,
        race_id=info['race_id'],stage=info['stage'],as_of=now.isoformat(),input_as_of=info['as_of'],
        cutoff_at=info['cutoff_at'],race_cutoff_at=info['race_cutoff_at'],input_sha256=digest(payload),
        baseline=baseline,learned=learned,baseline_normalized=registry.normalize(mid,sport,payload,baseline),
        learned_normalized=registry.normalize(mid,sport,payload,learned),training_sha256=training['training_sha256'],
        model_sha256=model['model_sha256'],production_promoted=False,actual_purchases=False)
    return seal(pair,'pair_sha256')
