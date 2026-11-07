"""Fit the existing model registry from authenticated private input records."""
import argparse,json,os,re,stat
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path

from race_ai.actions_contract import digest
from race_ai.all_existing_model_learning import fit,records_from_observed,seal,verify_training
from race_ai.all_existing_model_registry import registry_sha256
from race_ai.all_existing_model_research import issue_decision,verify_decision
from race_ai.boat_venue_learning import training_intake,seal_candidate
from race_ai.boat_pdca_state import state_key
from race_ai.github_freeze_receipt import BASE,_github_json
from scripts.boat_venue_learning import load_verified_intake
from scripts.boat_all_racers import _read,_write,_key_ready


def _native_archive(path):
    """Read the already-fetched encrypted archive from its private container.

    Cached metadata is rechecked against the actual GitHub endpoint before
    receipt admission. Neither this path nor an optional JSON file can supply
    outcome labels: those come from the authenticated journal.
    """
    from race_ai.all_existing_model_receipt import MAX_ARCHIVE_BYTES
    from race_ai.permissioned_source_delivery import read_json_bytes
    root=Path(path).absolute()
    if ('..' in root.parts or any(p.is_symlink() for p in (root,*root.parents)) or
            not root.is_dir() or any((p/'.git').exists() for p in (root,*root.parents))):
        raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_PRIVATE_DIRECTORY_REQUIRED')
    fd=os.open(root,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
    try:
        if os.fstat(fd).st_mode&0o077 or set(os.listdir(fd))!={'archive.zip','metadata.json'}:
            raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_PRIVATE_FILES_REQUIRED')
        def read(name,limit):
            file_fd=os.open(name,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),dir_fd=fd)
            with os.fdopen(file_fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or not 0<info.st_size<=limit:
                    raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_PRIVATE_FILES_REQUIRED')
                raw=stream.read(limit+1)
            if not 0<len(raw)<=limit:
                raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_SIZE_INVALID')
            return raw
        metadata=read_json_bytes(read('metadata.json',32*1024))
        raw=read('archive.zip',MAX_ARCHIVE_BYTES)
    finally:os.close(fd)
    if type(metadata) is not dict or type(metadata.get('workflow_run')) is not dict:
        raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_METADATA_INVALID')
    return raw,metadata


def _reverify_native_metadata(metadata):
    """A private JSON file alone never proves an external save clock."""
    ident=metadata.get('id')
    if type(ident) is not int or not 0<ident<10**16:
        raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_METADATA_INVALID')
    actual=_github_json(BASE+'/actions/artifacts/'+str(ident))
    fields=('id','name','digest','size_in_bytes','created_at','expires_at','expired')
    run_fields=('id','head_sha','repository_id','head_repository_id')
    if (type(actual) is not dict or type(actual.get('workflow_run')) is not dict or
            any(metadata.get(k)!=actual.get(k) for k in fields) or
            any(metadata['workflow_run'].get(k)!=actual['workflow_run'].get(k) for k in run_fields)):
        raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_ACTUAL_METADATA_MISMATCH')


def _merge_native_records(original,additional,*,preserve_native_versions=False):
    """Keep originals; an equal-time conflicting frozen input stops intake."""
    if preserve_native_versions:
        if type(original) is not list or type(additional) is not list or len(original)+len(additional)>10000:
            raise ValueError('ALL_MODEL_COMMON_EIGHT_BOUNDED_RECORDS')
        merged=[];seen=set()
        for row in original+additional:
            key=digest(row)
            if key not in seen:merged.append(row);seen.add(key)
        return merged
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    def key(row):
        return (row['sport'],row['model_id'],_race_key(row['race_id'],row['sport']),ts(row['as_of']))
    def label(row):
        result=deepcopy(row['result'])
        result['race_id']=_race_key(result['race_id'],row['sport'])
        return digest(result)
    merged=list(original);known={key(row):row for row in original}
    for row in additional:
        old=known.get(key(row))
        if old is not None:
            if old['input_sha256']!=row['input_sha256'] or label(old)!=label(row):
                raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_CONFLICTING_RECORD')
            continue
        if len(merged)>=10000:
            raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_BOUNDED_RECORDS_REQUIRED')
        known[key(row)]=row;merged.append(row)
    return merged


def _intake_identity(records,*,result_admissions=(),common_cohort=None):
    """Bind all data/contracts; keep the new derivation operation clock separate.

    Every invocation records its actual derived_at in the encrypted lineage.
    The owner grants the same frozen data and deterministic transformation on
    re-execution, without claiming the derived bytes were saved in the past.
    Legacy input identity is byte-for-byte unchanged.
    """
    if common_cohort is not None:
        return digest(dict(schema='RACE_AI_COMMON_EIGHT_PER_SPORT_INTAKE_V1',
            record_identity_sha256=_intake_identity(records,result_admissions=result_admissions),
            common_cohort=common_cohort))
    from race_ai.all_existing_model_source_derivations import validate_source_derivations
    for row in records:validate_source_derivations(row['native_payload'])
    if result_admissions:
        return digest(dict(schema='RACE_AI_RESULT_ARCHIVE_BOUND_INTAKE_V1',
            record_identity_sha256=_intake_identity(records),result_admissions=list(result_admissions)))
    if not any('input_derivation' in row for row in records):return digest(records)
    from race_ai.all_existing_model_registry import parameter_contract
    from race_ai.all_existing_model_derivation import (SCHEMA,DERIVATION_ID,AVAILABILITY_BASIS,
        NATIVE_SCHEMA,NATIVE_DERIVATION_ID,NATIVE_AVAILABILITY_BASIS)
    normalized=deepcopy(records);contracts={};native_derivations=False
    for row in normalized:
        if 'input_derivation' not in row:continue
        proof=row['input_derivation']
        legacy=type(proof) is dict and proof.get('schema')==SCHEMA and \
            proof.get('derivation_id')==DERIVATION_ID and proof.get('data_availability_basis')==AVAILABILITY_BASIS
        native=type(proof) is dict and proof.get('schema')==NATIVE_SCHEMA and \
            proof.get('derivation_id')==NATIVE_DERIVATION_ID and \
            proof.get('data_availability_basis')==NATIVE_AVAILABILITY_BASIS and \
            proof.get('historical_native_payload_bytes') is False and \
            proof.get('original_input_receipt_sha256')==digest(proof.get('original_input_receipt'))
        if (not (legacy or native) or
                proof.get('derived_payload_saved_before_cutoff') is not False or type(proof.get('derived_at')) is not str):
            raise ValueError('ALL_MODEL_DERIVED_INTAKE_IDENTITY_SCHEMA')
        native_derivations=native_derivations or native
        proof.pop('derived_at')
        schema=row['native_payload']['snapshot']['schema']
        key=row['sport']+'/'+row['model_id']
        contract=digest(parameter_contract(row['model_id'],row['sport'],input_schema=schema))
        if key in contracts and contracts[key]!=contract:
            raise ValueError('ALL_MODEL_DERIVED_PARAMETER_CONTRACT_CONFLICT')
        contracts[key]=contract
    return digest(dict(schema='RACE_AI_DERIVED_INTAKE_CONTENT_IDENTITY_V2' if native_derivations else
                       'RACE_AI_DERIVED_INTAKE_CONTENT_IDENTITY_V1',
                       records=normalized,parameter_contracts=contracts))


def _select_native_cohort(records,*,race_ids=(),size=None,full_native_boat_cohort=False):
    """Select complete P1 cases by availability, never by the winning order.

    Each case needs the five genuinely frozen native A/B/C-lite/observed
    records. Additional sparse cells are derived only after this selection.
    Original records and any unselected G7 cases remain in their source vault;
    this explicit research cohort does not overwrite or relabel them.
    """
    from race_ai.boat_ab_shadow import MODEL_IDS as AB
    from race_ai.boat_live_feature_shadow import MODEL_ID as CLITE
    from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
    from race_ai.all_existing_model_registry import identity
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    required=(*AB,CLITE,*OBSERVED)
    if full_native_boat_cohort:
        from race_ai.all_existing_model_registry import cells,group
        required=tuple(cell['model_id'] for cell in cells() if cell['sport']=='boat' and group(cell['model_id'])!='seller')
        if len(required)!=14:raise ValueError('ALL_MODEL_FULL_NATIVE_BOAT_ROSTER_INVALID')
    if (type(race_ids) not in (tuple,list) or bool(race_ids) == (size is not None) or
            size is not None and (type(size) is not int or not 8<=size<=288)):
        raise ValueError('ALL_MODEL_NATIVE_COHORT_SELECTION_REQUIRED')
    chosen_ids=[_race_key(rid,'boat') for rid in race_ids]
    if chosen_ids and (len(chosen_ids)<8 or len(chosen_ids)>288 or len(set(chosen_ids))!=len(chosen_ids)):
        raise ValueError('ALL_MODEL_NATIVE_COHORT_UNIQUE_RACES_REQUIRED')
    indexed={}
    for row in records:
        if (row['sport']!='boat' or row['model_id'] not in required or row['stage']!='P1' or
                'input_derivation' in row or 'observed_row' in row):continue
        proof=row.get('input_receipt',{})
        if proof.get('independent_pre_cutoff_receipt_verified') is not True or \
                type(proof.get('artifact_metadata')) is not dict:continue
        race=_race_key(row['race_id'],'boat');members=indexed.setdefault(race,{})
        previous=members.get(row['model_id'])
        if previous is None or ts(row['as_of'])>ts(previous['as_of']):members[row['model_id']]=row
    complete={}
    for race,members in indexed.items():
        if set(members)!=set(required):continue
        ordered=[members[mid] for mid in required]
        infos=[identity(row['model_id'],'boat',row['native_payload'],race_id=row['race_id']) for row in ordered]
        base=infos[0];labels=[]
        for row,info in zip(ordered,infos):
            if (info['roster']!=base['roster'] or ts(info['race_cutoff_at'])!=ts(base['race_cutoff_at']) or
                    info['scope']!=base['scope']):
                raise ValueError('ALL_MODEL_NATIVE_COHORT_INPUT_CONFLICT')
            label=deepcopy(row['result']);label['race_id']=_race_key(label['race_id'],'boat')
            for field in ('captured_at','published_at'):
                if label.get(field) is not None:label[field]=ts(label[field]).astimezone(timezone.utc).isoformat()
            labels.append(digest(label))
        if len(set(labels))!=1:raise ValueError('ALL_MODEL_NATIVE_COHORT_RESULT_CONFLICT')
        complete[race]=ordered
    if chosen_ids:
        if not set(chosen_ids)<=set(complete):
            raise ValueError('ALL_MODEL_NATIVE_COHORT_FOURTEEN_FROZEN_CELLS_REQUIRED' if full_native_boat_cohort else
                'ALL_MODEL_NATIVE_COHORT_FIVE_FROZEN_CELLS_REQUIRED')
    else:
        candidates=sorted(complete,key=lambda rid:(ts(complete[rid][0]['result']['captured_at']),rid))
        if len(candidates)<size:raise ValueError('ALL_MODEL_NATIVE_COHORT_INSUFFICIENT_RACES')
        chosen_ids=candidates[:size]
    chosen_ids=sorted(chosen_ids,key=lambda rid:(ts(complete[rid][0]['result']['captured_at']),rid))
    selected=[row for race in chosen_ids for row in complete[race]]
    summary=dict(cohort_race_count=len(chosen_ids),cohort_required_frozen_cells=len(required),
        cohort_input_record_count=len(selected),cohort_races_sha256=digest(chosen_ids),
        cohort_selection='EXPLICIT_CANONICAL_RACE_IDS' if race_ids else 'EARLIEST_AVAILABLE_COMPLETE_NATIVE_COHORT',
        cohort_selected_by_winning_order=False)
    if full_native_boat_cohort:
        summary.update(full_native_boat_cohort=True,derived_record_count=0,
            cohort_input_policy='ORIGINAL_FROZEN_NATIVE_INPUTS_ONLY')
    return selected,summary



def _select_common_eight_per_sport(records,*,now):
    """Choose original complete cases by source availability, never outcomes.

    Callers independently admit archives before this pure selection. Retained
    receipt/partition evidence is checked again; no native bytes are derived.
    """
    from race_ai import all_existing_model_registry as registry
    from race_ai.all_existing_model_learning import (_native_generation_evidence,_result_available_at,
        _common_cohort_sha256)
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    def require(ok,reason):
        if not ok:raise ValueError('ALL_MODEL_COMMON_EIGHT_'+reason)
    require(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    require(type(records) is list and len(records)<=10000,'BOUNDED_RECORDS')
    all_cells={c['cell_key']:c for c in registry.cells()}
    cells={key:c for key,c in all_cells.items() if c['group']!='seller'}
    expected={sport:{key for key,cell in cells.items() if cell['sport']==sport}
              for sport in ('boat','autorace','keirin','horse')}
    require({s:len(v) for s,v in expected.items()}==dict(boat=14,autorace=6,keirin=5,horse=5),'REGISTRY')
    versions={};race_labels={}
    def normalized_label(row):
        value=deepcopy(row['result']);value['race_id']=_race_key(value['race_id'],row['sport'])
        for key in ('captured_at','published_at','closed_at'):
            if value.get(key) is not None:value[key]=ts(value[key]).astimezone(timezone.utc).isoformat()
        return digest(value)
    for row in records:
        require(type(row) is dict,'RECORD')
        if 'input_derivation' in row or 'observed_row' in row:continue
        key=registry.cell_key(row['sport'],row['model_id'])
        if key not in cells:
            require(key in all_cells and all_cells[key]['group']=='seller','FOREIGN_CELL');continue
        require(row['input_sha256']==digest(row['native_payload']),'INPUT_HASH')
        info=registry.identity(row['model_id'],row['sport'],row['native_payload'],race_id=row['race_id'])
        require(_race_key(row['race_id'],row['sport'])==_race_key(info['race_id'],row['sport']) and
            row['stage']==info['stage'] and row['scope']==info['scope'] and ts(row['as_of'])==ts(info['as_of']) and
            ts(row['cutoff_at'])==ts(info['cutoff_at']) and
            (row['sport']!='boat' or row['stage']=='P1'),'NATIVE_IDENTITY')
        proof=_native_generation_evidence(row,now=now);require(proof is not None,'ORIGINAL_NATIVE_PROOF_REQUIRED')
        from race_ai.all_existing_model_intake import _ordinary_result
        admitted,reason=_ordinary_result(row['result'],info,now)
        require(admitted is not None and reason is None,'NORMAL_RESULT')
        from race_ai.official_order_only_result import has_order_only_markers,validate_order_only
        if has_order_only_markers(row['result']) and 'result_observation' in row:
            original=validate_order_only(row['result_observation'],sport=row['sport'],roster=info['roster'],race_id=row['race_id'])
            require(normalized_label(dict(row,result=original))==normalized_label(row),'ORIGINAL_RESULT_CONFLICT')
        if 'result_source_evidence' in row:
            from race_ai.all_existing_model_official_results import verify_result_source_evidence
            verify_result_source_evidence(row['result_source_evidence'],result=row.get('result_observation',row['result']),now=now)
        result=row['result'];require(result.get('sport')==row['sport'] and
            _race_key(result['race_id'],row['sport'])==_race_key(row['race_id'],row['sport']) and
            result.get('status') in ('settled','rank_confirmed') and result.get('identity_verified') is True and
            result.get('roster')==info['roster'] and not result.get('refund_numbers'),'NORMAL_RESULT')
        require(ts(info['race_cutoff_at'])<ts(result['captured_at'])<=ts(_result_available_at(row))<=now,'RESULT_AVAILABILITY')
        race_identity=(row['sport'],_race_key(row['race_id'],row['sport']))
        label_sha=normalized_label(row)
        require(race_identity not in race_labels or race_labels[race_identity]==label_sha,'RESULT_CONFLICT')
        race_labels[race_identity]=label_sha
        identity=(row['sport'],_race_key(row['race_id'],row['sport']),key)
        rank=(ts(row['as_of']),ts(proof['actual_native_generated_at']),ts(row['input_saved_at']))
        old=versions.get(identity)
        if old is not None and rank==old[0]:
            require(row['input_sha256']==old[1]['input_sha256'] and normalized_label(row)==normalized_label(old[1]),
                    'AMBIGUOUS_NATIVE_VERSION')
            # Equal native bytes and clock claims may be independently saved
            # twice. Choose by receipt identity, never by the result values.
            receipt_order=lambda r:(r['input_receipt']['artifact_id'],digest(r['input_receipt']),digest(r['input_partitions']))
            if receipt_order(row)==receipt_order(old[1]):
                require(digest(row)==digest(old[1]),'AMBIGUOUS_ORIGINAL_RECORD')
            elif receipt_order(row)<receipt_order(old[1]):versions[identity]=(rank,row,info)
        elif old is None or rank>old[0]:versions[identity]=(rank,row,info)
    grouped={}
    for (sport,race,key),(_,row,info) in versions.items():grouped.setdefault((sport,race),{})[key]=(row,info)
    complete={sport:[] for sport in expected}
    for (sport,race),members in grouped.items():
        if set(members)!=expected[sport]:continue
        ordered=[members[key] for key in sorted(members)];first=ordered[0][1]
        require(all(info['roster']==first['roster'] and ts(info['race_cutoff_at'])==ts(first['race_cutoff_at']) and
            info['scope']==first['scope'] for _,info in ordered),'INPUT_CONFLICT')
        require(len({normalized_label(row) for row,_ in ordered})==1,'RESULT_CONFLICT')
        available={ts(_result_available_at(row)) for row,_ in ordered}
        require(len(available)==1,'SOURCE_CLOSURE_CONFLICT')
        complete[sport].append((next(iter(available)),race,[row for row,_ in ordered]))
    selected=[];cohorts={}
    for sport in ('boat','autorace','keirin','horse'):
        choices=sorted(complete[sport],key=lambda item:(item[0],item[1]))
        require(len(choices)>=8,'PER_SPORT_INSUFFICIENT_COMPLETE_RACES')
        chosen=choices[:8];require(chosen[5][0]<chosen[6][0],'TRAIN_HOLDOUT_AVAILABILITY_TIE')
        cohorts[sport]=sorted(item[1] for item in chosen)
        selected.extend(row for _,_,rows in chosen for row in rows)
    require(len({row['scope'] for row in selected})==1,'MIXED_SCOPE')
    summary=dict(common_eight_per_sport=True,required_common_cells=30,cohort_counts_by_sport={s:8 for s in expected},
        record_count=240,common_cohort_sha256=_common_cohort_sha256(digest(selected),cohorts))
    require(len(selected)==240,'RECORD_COUNT')
    return selected,summary


def _merge_verified_result_observations(observations):
    """Select latest canonical captures without rewriting authenticated bytes."""
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    seen={};latest={}
    for original in observations:
        sport=original.get('sport','boat')
        if sport not in ('boat','keirin','autorace','horse'):
            raise ValueError('ALL_MODEL_RESULT_ARCHIVE_SPORT_INVALID')
        race=(sport,_race_key(original['race_id'],sport));captured=ts(original['captured_at'])
        normalized=deepcopy(original);normalized['race_id']=race[1]
        for name in ('captured_at','available_at','published_at','upstream_published_at','closed_at'):
            if normalized.get(name) is not None:normalized[name]=ts(normalized[name]).astimezone(timezone.utc).isoformat()
        key=(race,captured);fingerprint=digest(normalized)
        if key in seen:
            old,representative=seen[key]
            if fingerprint!=old:raise ValueError('ALL_MODEL_RESULT_ARCHIVE_CONFLICTING_REVISIONS')
            if digest(original)<digest(representative):seen[key]=(fingerprint,deepcopy(original))
        else:seen[key]=(fingerprint,deepcopy(original))
    for (race,captured),(_,original) in sorted(seen.items(),key=lambda item:(item[0][1],item[0][0])):
        latest[race]=original
    return [latest[key] for key in sorted(latest)]


def _record_source_refs(record):
    from race_ai.all_existing_model_learning import _sources
    refs=_sources(record['native_payload'])
    refs.add((record['result']['source_ref'],record['result']['source_rights_ref']))
    if 'result_source_evidence' in record:refs.update(_sources(record['result_source_evidence']))
    return refs


def _attach_result_source_evidence(records,proofs,*,now):
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    from race_ai.all_existing_model_official_results import verify_result_source_evidence
    if type(proofs) is not list or len(proofs)>10000:
        raise ValueError('ALL_MODEL_RESULT_SOURCE_PROOF_BOUND')
    def key(value):
        return (value['sport'],_race_key(value['race_id'],value['sport']),value['source_sha256'],ts(value['captured_at']))
    indexed={}
    for proof in proofs:
        if type(proof) is not dict or type(proof.get('result_binding')) is not dict:
            raise ValueError('ALL_MODEL_RESULT_SOURCE_PROOF_FIELDS')
        indexed.setdefault(key(proof['result_binding']),[]).append(proof)
    out=[]
    for original in records:
        row=deepcopy(original)
        if row['sport'] not in ('autorace','keirin'):
            out.append(row);continue
        observation=row.get('result_observation',row['result'])
        candidates=indexed.get(key(observation),[])
        if candidates:
            matched=[p for p in candidates if p.get('result_observation_sha256')==digest(observation)]
            if not matched:raise ValueError('ALL_MODEL_RESULT_SOURCE_OBSERVATION_CONFLICT')
            proof=min(matched,key=lambda p:(ts(p['artifact_receipt']['saved_at']),digest(p)))
            verify_result_source_evidence(proof,result=observation,now=now)
            if 'result_source_evidence' in row and row['result_source_evidence']!=proof:
                raise ValueError('ALL_MODEL_RESULT_SOURCE_PROOF_CONFLICT')
            row['result_source_evidence']=deepcopy(proof)
        out.append(row)
    return out


def load_intake(restored_dir,state_input,dataset_input,*,now,native_archive_dirs=(),derive_observed=False,
                native_round_archive_dirs=(),result_archive_dirs=(),cohort_race_ids=(),cohort_size=None,
                keep_other_sports=False,full_native_boat_cohort=False,allow_order_only=False,common_eight_per_sport=False):
    if type(common_eight_per_sport) is not bool or common_eight_per_sport and not (
            full_native_boat_cohort is True and keep_other_sports is True and allow_order_only is True and
            type(cohort_size) is int and cohort_size==8 and not cohort_race_ids and not derive_observed):
        raise ValueError('ALL_MODEL_COMMON_EIGHT_EXPLICIT_FLAGS_REQUIRED')
    rows,observations,pointer,content=load_verified_intake(restored_dir,state_input,now=now,authenticate_owner_cipher=True)
    if type(full_native_boat_cohort) is not bool or full_native_boat_cohort and (derive_observed or
            not (cohort_size==8 and not cohort_race_ids or cohort_size is None and len(cohort_race_ids)==8)):
        raise ValueError('ALL_MODEL_FULL_NATIVE_EXPLICIT_EIGHT_WITHOUT_DERIVATION_REQUIRED')
    if type(keep_other_sports) is not bool or keep_other_sports and (not (derive_observed or full_native_boat_cohort) or
            not (cohort_size==8 and not cohort_race_ids or cohort_size is None and len(cohort_race_ids)==8)):
        raise ValueError('ALL_MODEL_OTHER_SPORTS_EXPLICIT_EIGHT_COHORT_REQUIRED')
    if type(allow_order_only) is not bool or allow_order_only and not keep_other_sports:
        raise ValueError('ALL_MODEL_ORDER_ONLY_EXPLICIT_OTHER_SPORTS_REQUIRED')
    native_bytes={};authenticated_frozen=None
    def archive_bytes(path,*,remember=False):
        identity=str(Path(path).absolute())
        if identity in native_bytes:return native_bytes[identity]
        raw,metadata=_native_archive(path);_reverify_native_metadata(metadata)
        if remember:native_bytes[identity]=(raw,metadata)
        return raw,metadata
    def frozen_inputs():
        nonlocal authenticated_frozen
        if authenticated_frozen is None:
            from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
            if type(native_archive_dirs) not in (tuple,list) or not 1<=len(native_archive_dirs)<=32:
                raise ValueError('ALL_MODEL_OFFICIAL_RESULTS_FROZEN_INPUT_ARCHIVES_REQUIRED')
            authenticated_frozen=[]
            for path in native_archive_dirs:
                raw,metadata=archive_bytes(path,remember=True);run=metadata['workflow_run']
                _,parts=_verified_private_pairs_artifact(raw,metadata,now=now,
                    expected_run_id=run.get('id'),expected_head_sha=run.get('head_sha'))
                authenticated_frozen.extend(deepcopy(capsule['native_payload'])
                    for part in parts for capsule in part.get('captured_native_inputs',[]))
        return authenticated_frozen
    result_admissions=[];result_source_proofs=[]
    if result_archive_dirs:
        from race_ai.all_existing_model_result_intake import observations_from_result_artifact
        if type(result_archive_dirs) not in (tuple,list) or len(result_archive_dirs)>32:
            raise ValueError('ALL_MODEL_RESULT_ARCHIVE_BOUNDED_LIST_REQUIRED')
        combined=list(observations);seen_results={}
        for path in result_archive_dirs:
            raw,metadata=_native_archive(path);_reverify_native_metadata(metadata)
            run=metadata['workflow_run']
            if type(metadata.get('name')) is str and metadata['name'].startswith('all-existing-official-results-'):
                from race_ai.all_existing_model_official_results import observations_from_official_result_artifact
                admitted=observations_from_official_result_artifact(raw,metadata,now=now,
                    expected_run_id=run.get('id'),expected_head_sha=run.get('head_sha'),
                    frozen_native_payloads=frozen_inputs(),**(dict(allow_order_only=True) if allow_order_only else {}))
                result_source_proofs.extend(admitted.get('result_source_evidence',[]))
            else:
                admitted=observations_from_result_artifact(raw,metadata,now=now,
                    expected_run_id=run.get('id'),expected_head_sha=run.get('head_sha'))
            identity=metadata['id'];fingerprint=digest(metadata)
            if identity in seen_results:
                if seen_results[identity]!=fingerprint:
                    raise ValueError('ALL_MODEL_RESULT_ARCHIVE_CONFLICTING_METADATA')
                continue
            seen_results[identity]=fingerprint;combined.extend(admitted['observations'])
            result_admissions.append(admitted['receipt'])
        observations=_merge_verified_result_observations(combined)
    dataset=json.loads(_read(Path(dataset_input),8192))
    boat_observations=[value for value in observations if value.get('sport','boat')=='boat']
    intake=training_intake(rows,boat_observations,dataset_pointer=dataset)
    # The legacy selector chooses one input per race. Retain both genuinely
    # frozen model rows for that same selected snapshot, never older inputs.
    selected={r['race_id']:r['learning_snapshot_sha256'] for r in intake['eligible']}
    native_rows=[r for r in rows if selected.get(r['race_id'])==r['learning_snapshot_sha256']]
    records=records_from_observed(native_rows,intake['observations'])
    if native_archive_dirs or native_round_archive_dirs:
        from race_ai.all_existing_model_intake import records_from_private_artifact
        from race_ai.all_existing_model_round_intake import records_from_round_artifact
        from race_ai.all_existing_model_learning import _sources
        if (type(native_archive_dirs) not in (tuple,list) or type(native_round_archive_dirs) not in (tuple,list) or
                len(native_archive_dirs)+len(native_round_archive_dirs)>32):
            raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_BOUNDED_LIST_REQUIRED')
        original_count=len(records);summaries=[];seen={}
        archives=[(records_from_private_artifact,path) for path in native_archive_dirs]
        archives.extend((records_from_round_artifact,path) for path in native_round_archive_dirs)
        for reader,path in archives:
            raw,metadata=archive_bytes(path)
            run=metadata['workflow_run']
            # Admission performs authenticated decryption/native replay and
            # checks the entire ZIP, repo, digest, run/head and external clock.
            admitted=reader(raw,metadata,observations,now=now,
                expected_run_id=run.get('id'),expected_head_sha=run.get('head_sha'))
            ident=admitted['summary']['artifact_id'];fingerprint=digest(metadata)
            if ident in seen:
                if seen[ident]!=fingerprint:
                    raise ValueError('ALL_MODEL_NATIVE_ARCHIVE_CONFLICTING_METADATA')
                continue
            seen[ident]=fingerprint
            records=_merge_native_records(records,admitted['records'],**(
                dict(preserve_native_versions=True) if common_eight_per_sport else {}))
            summaries.append(admitted['summary'])
        refs={tuple(pair) for pair in intake['source_refs']}
        for record in records:
            refs.update(_sources(record['native_payload']))
            refs.add((record['result']['source_ref'],record['result']['source_rights_ref']))
        intake=deepcopy(intake)
        intake.update(source_refs=[list(pair) for pair in sorted(refs)],native_archive_intakes=summaries,
            native_archive_count=len(summaries),native_admitted_records=len(records)-original_count)
    if result_admissions:
        intake=deepcopy(intake)
        intake.update(result_archive_count=len(result_admissions),result_archive_admissions=result_admissions)
    common_cohort=None
    if common_eight_per_sport:
        if result_source_proofs:
            records=_attach_result_source_evidence(records,result_source_proofs,now=now)
        records,common_cohort=_select_common_eight_per_sport(records,now=now)
        intake=deepcopy(intake);intake.update(common_cohort)
        intake.update(full_native_boat_cohort=True,derived_record_count=0,
            cohort_input_policy='ORIGINAL_FROZEN_NATIVE_INPUTS_ONLY',cohort_race_count=8,
            cohort_required_frozen_cells=14,cohort_input_record_count=112,
            cohort_selected_by_winning_order=False,
            cohort_selection='EARLIEST_AVAILABLE_COMPLETE_NATIVE_CASES_PER_SPORT',
            kept_other_sport_record_count=sum(r['sport']!='boat' for r in records),
            kept_other_sports=sorted({r['sport'] for r in records if r['sport']!='boat'}))
        refs=set()
        for record in records:refs.update(_record_source_refs(record))
        intake['source_refs']=[list(pair) for pair in sorted(refs)]
    elif cohort_race_ids or cohort_size is not None:
        if not (derive_observed or full_native_boat_cohort):
            raise ValueError('ALL_MODEL_NATIVE_COHORT_EXPLICIT_DERIVATION_REQUIRED')
        other_sports=[row for row in records if row['sport']!='boat'] if keep_other_sports else []
        records,cohort=_select_native_cohort(records,race_ids=cohort_race_ids,size=cohort_size,
            full_native_boat_cohort=full_native_boat_cohort)
        records+=other_sports
        intake=deepcopy(intake);intake.update(cohort)
        if keep_other_sports:
            intake.update(kept_other_sport_record_count=len(other_sports),
                kept_other_sports=sorted({row['sport'] for row in other_sports}))
        if full_native_boat_cohort:
            from race_ai.all_existing_model_learning import _sources
            refs=set()
            for record in records:
                refs.update(_sources(record['native_payload']))
                refs.add((record['result']['source_ref'],record['result']['source_rights_ref']))
            intake['source_refs']=[list(pair) for pair in sorted(refs)]
    if derive_observed:
        from race_ai.all_existing_model_derivation import derive_records
        from race_ai.all_existing_model_learning import _sources
        from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
        from race_ai.existing_model_dispatch import _race_key
        from race_ai.observed_weight_learning import ts
        observed=[row for row in records if row['model_id'] in OBSERVED and 'input_derivation' not in row]
        derived=derive_records(observed,now=now,include_groups=('shared','shared_learned','boat_full'))
        # A genuinely frozen native target already at this observation time
        # takes precedence over a newly calculated sparse substitute. Raw
        # native-vs-native conflicts were rejected during archive union above.
        def slot(row):
            return (row['sport'],row['model_id'],_race_key(row['race_id'],row['sport']),ts(row['as_of']))
        frozen_slots={slot(row) for row in records if 'input_derivation' not in row}
        preserved=sum(slot(row) in frozen_slots for row in derived)
        derived=[row for row in derived if slot(row) not in frozen_slots]
        records=_merge_native_records(records,derived)
        intake=deepcopy(intake)
        bases=sorted({row['input_derivation']['data_availability_basis'] for row in derived})
        intake.update(derived_record_count=len(derived),derived_model_ids=sorted({row['model_id'] for row in derived}),
            derived_native_slots_preserved=preserved,
            derived_payloads_saved_before_cutoff=False,
            derived_input_availability_basis=bases[0] if len(bases)==1 else 'MIXED_AUTHENTICATED_ORIGINAL_AVAILABILITY',
            derived_input_availability_bases=bases)
        refs=set() if cohort_race_ids or cohort_size is not None else {tuple(pair) for pair in intake['source_refs']}
        for record in records:
            refs.update(_sources(record['native_payload']))
            refs.add((record['result']['source_ref'],record['result']['source_rights_ref']))
        intake['source_refs']=[list(pair) for pair in sorted(refs)]
    if result_source_proofs and not common_eight_per_sport:
        records=_attach_result_source_evidence(records,result_source_proofs,now=now)
        refs={tuple(pair) for pair in intake['source_refs']}
        for record in records:refs.update(_record_source_refs(record))
        intake['source_refs']=[list(pair) for pair in sorted(refs)]
    scope={}
    if allow_order_only:
        from race_ai.official_order_only_result import EVALUATION_SCOPE,has_order_only_markers
        for record in records:
            if has_order_only_markers(record['result']) and 'result_source_evidence' not in record:
                raise ValueError('ALL_MODEL_ORDER_ONLY_RESULT_SOURCE_EVIDENCE_REQUIRED')
        scope['label_evaluation_scope']=EVALUATION_SCOPE
        intake.update(label_evaluation_scope=EVALUATION_SCOPE,
            order_only_record_count=sum(has_order_only_markers(r['result']) for r in records))
    return records,dict(source_pointer=pointer,state_content_sha256=content,dataset_pointer=dataset,
        source_refs=intake['source_refs'],intake_sha256=_intake_identity(records,result_admissions=result_admissions,**(
            dict(common_cohort=common_cohort) if common_eight_per_sport else {})),
        registry_sha256=registry_sha256(),**scope),intake


def main(argv=None,*,now=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('issue-decision','fit'))
    parser.add_argument('--restored-dir',required=True)
    parser.add_argument('--state-input',default='audit/state/boat-pdca-production-input.json')
    parser.add_argument('--dataset-input',default='audit/state/boat-venue-dataset-input.json')
    parser.add_argument('--owner-research-record',default='audit/state/all-existing-model-owner-research.json')
    parser.add_argument('--native-archive-dir',action='append',default=[],
        help='Existing private archive.zip/metadata.json container; outcomes come only from the authenticated restored journal')
    parser.add_argument('--native-round-archive-dir',action='append',default=[],
        help='Owner-encrypted native round ZIP and independently reverified metadata')
    parser.add_argument('--result-archive-dir',action='append',default=[],
        help='Owner-encrypted RESULT ZIP and independently reverified metadata; never a plaintext result sidecar')
    parser.add_argument('--derive-from-observed',action='store_true',
        help='Replay documented sparse native transforms from independently frozen originals; derived bytes are created now')
    cohort=parser.add_mutually_exclusive_group()
    cohort.add_argument('--cohort-race-id',action='append',default=[],
        help='Explicit common P1 race cohort (at least eight); repeat for each race, with documented aliases accepted')
    cohort.add_argument('--cohort-size',type=int,
        help='Select this many earliest available complete five-cell P1 cases before explicit derivation')
    parser.add_argument('--keep-other-sports',action='store_true',
        help='Explicitly retain authenticated other-sport native records alongside the common eight BOAT races')
    parser.add_argument('--full-native-boat-cohort',action='store_true',
        help='Select eight independently frozen complete fourteen-cell BOAT cases; forbid retrospective derivation')
    parser.add_argument('--allow-order-only',action='store_true',
        help='Explicit owner V2 research scope: confirmed ranks only, with no monetary evaluation')
    parser.add_argument('--common-eight-per-sport',action='store_true',
        help='Require unchanged complete eight-case cohorts for BOAT14/AUTO6/KEIRIN5/HORSE5 before owner issuance')
    parser.add_argument('--out-dir');parser.add_argument('--expires-at')
    args=parser.parse_args(argv);now=now or datetime.now(timezone.utc)
    try:
        if not _key_ready():
            print(json.dumps(dict(state='HOLD_OWNER_STATE_KEY_MISSING',model_family_count=16,
                applicable_model_cells=31,fitted_model_count=0,production_promoted=False,plaintext_published=False)));return 0
        state_key('production')
        options=dict(now=now)
        if args.native_archive_dir:options['native_archive_dirs']=args.native_archive_dir
        if args.native_round_archive_dir:options['native_round_archive_dirs']=args.native_round_archive_dir
        if args.result_archive_dir:options['result_archive_dirs']=args.result_archive_dir
        if args.derive_from_observed:options['derive_observed']=True
        if args.cohort_race_id:options['cohort_race_ids']=args.cohort_race_id
        if args.cohort_size is not None:options['cohort_size']=args.cohort_size
        if args.keep_other_sports:options['keep_other_sports']=True
        if args.full_native_boat_cohort:options['full_native_boat_cohort']=True
        if args.allow_order_only:options['allow_order_only']=True
        if args.common_eight_per_sport:options['common_eight_per_sport']=True
        records,binding,intake=load_intake(args.restored_dir,args.state_input,args.dataset_input,**options)
        record_path=Path(args.owner_research_record)
        if args.command=='issue-decision':
            if record_path.exists() or any(p.is_symlink() for p in (record_path.absolute(),*record_path.absolute().parents)):
                raise ValueError('ALL_MODEL_OWNER_RESEARCH_RECORD_EXISTS_DO_NOT_RESET')
            expiry=datetime.fromisoformat(args.expires_at.replace('Z','+00:00')) if args.expires_at else now+timedelta(days=90)
            decision=issue_decision(**binding,now=now,expires_at=expiry)
            record_path.parent.mkdir(parents=True,exist_ok=True)
            _write(record_path,json.dumps(decision,sort_keys=True,indent=2).encode()+b'\n')
            if args.common_eight_per_sport:
                from race_ai.all_existing_model_learning import COMMON_COHORT_FIELDS
                issued=dict(state='OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED',decision_sha256=digest(decision),
                    model_family_count=16,applicable_model_cells=31,provider_permission_confirmed=False,production_promoted=False)
                issued.update({key:intake[key] for key in COMMON_COHORT_FIELDS})
                print(json.dumps(issued));return 0
            print(json.dumps(dict(state='OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED',decision_sha256=digest(decision),
                model_family_count=16,applicable_model_cells=31,provider_permission_confirmed=False,production_promoted=False)));return 0
        if not args.out_dir:parser.error('--out-dir is required for fit')
        decision=json.loads(_read(record_path,100000));decision_sha=verify_decision(decision,**binding,now=now)
        admitted={tuple(p) for p in binding['source_refs']}
        def analysis(url,rights,purpose):return purpose=='analysis' and (url,rights) in admitted
        def training(url,rights,purpose):return purpose=='model_training' and (url,rights) in admitted
        trained=fit(records,now=now,allow_source=analysis,allow_training=training,
            **(dict(allow_order_only=True) if args.allow_order_only else {}))
        trained.update(training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=decision_sha,
            venue_dataset_sha256=binding['dataset_pointer']['dataset_sha256'],
            source_content_sha256=binding['state_content_sha256'])
        if args.derive_from_observed:
            trained.update(owner_bound_intake_sha256=binding['intake_sha256'],
                intake_identity_semantics='DATA_AND_PARAMETER_CONTRACTS_WITH_SEPARATE_DERIVATION_CLOCK')
        if args.result_archive_dir:
            trained.update(owner_bound_intake_sha256=binding['intake_sha256'],
                result_archive_admissions_sha256=digest(intake['result_archive_admissions']))
        if args.common_eight_per_sport:
            from race_ai.all_existing_model_learning import COMMON_COHORT_FIELDS
            trained.update({key:intake[key] for key in COMMON_COHORT_FIELDS})
            trained.update(owner_bound_intake_sha256=binding['intake_sha256'],
                intake_identity_semantics='ORIGINAL_COMMON_EIGHT_PER_SPORT_V1')
        seal(trained,'training_sha256');verify_training(trained)
        summary=dict(schema='RACE_AI_ALL_EXISTING_MODEL_COUNTS_V1',state=trained['state'],
            model_family_count=16,applicable_model_cells=31,fitted_model_count=len(trained['models']),
            fitted_family_count=len({v['model_id'] for v in trained['models'].values()}),
            missing_or_unfitted_cells=31-len(trained['models']),
            observed_unique_races=intake['observed_unique_races'],eligible_venue_races=len(intake['eligible']),
            model_states=trained['model_states'],training_sha256=trained['training_sha256'],
            training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=decision_sha,
            provider_permission_confirmed=False,provider_review_missing_sources=len(admitted),
            baseline_coefficients_changed=False,new_model_created=False,accuracy_improvement_proven=False,
            production_promoted=False,actual_purchases=False,plaintext_published=False)
        if args.native_archive_dir or args.native_round_archive_dir:
            summary.update(native_archive_count=intake['native_archive_count'],
                native_admitted_records=intake['native_admitted_records'])
        if args.result_archive_dir:summary['result_archive_count']=intake['result_archive_count']
        if args.derive_from_observed:
            summary.update(derived_record_count=intake['derived_record_count'],
                derived_model_ids=intake['derived_model_ids'],
                derived_payloads_saved_before_cutoff=False,
                derived_input_availability_basis=intake['derived_input_availability_basis'])
        if args.cohort_race_id or args.cohort_size is not None:
            summary.update({key:value for key,value in intake.items() if key.startswith('cohort_')})
        if args.keep_other_sports:
            summary.update(kept_other_sport_record_count=intake['kept_other_sport_record_count'],
                kept_other_sports=intake['kept_other_sports'])
        if args.full_native_boat_cohort:
            summary.update(full_native_boat_cohort=True,derived_record_count=0,
                cohort_input_policy='ORIGINAL_FROZEN_NATIVE_INPUTS_ONLY')
        if args.allow_order_only:
            summary.update(label_evaluation_scope=intake['label_evaluation_scope'],
                order_only_record_count=intake['order_only_record_count'],monetary_evaluation_available=False)
        if args.common_eight_per_sport:
            from race_ai.all_existing_model_learning import COMMON_COHORT_FIELDS
            summary.update({key:intake[key] for key in COMMON_COHORT_FIELDS})
        result=seal_candidate(dict(summary=summary,training=trained,excluded=[],owner_research_record=decision),args.out_dir)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('(ALL_MODEL_[A-Z_]{1,100}|VENUE_LEARNING_[A-Z_]{1,100})',str(exc)) else 'ALL_MODEL_OPERATION_REJECTED'
        print(json.dumps(dict(state='HOLD_ALL_MODEL_RESEARCH',reason=reason,production_promoted=False,plaintext_published=False)));return 2


if __name__=='__main__':raise SystemExit(main())
