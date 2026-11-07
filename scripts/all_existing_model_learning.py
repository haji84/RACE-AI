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


def _merge_native_records(original,additional):
    """Keep originals; an equal-time conflicting frozen input stops intake."""
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


def _intake_identity(records,*,result_admissions=()):
    """Bind all data/contracts; keep the new derivation operation clock separate.

    Every invocation records its actual derived_at in the encrypted lineage.
    The owner grants the same frozen data and deterministic transformation on
    re-execution, without claiming the derived bytes were saved in the past.
    Legacy input identity is byte-for-byte unchanged.
    """
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


def _select_native_cohort(records,*,race_ids=(),size=None):
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
            raise ValueError('ALL_MODEL_NATIVE_COHORT_FIVE_FROZEN_CELLS_REQUIRED')
    else:
        candidates=sorted(complete,key=lambda rid:(ts(complete[rid][0]['result']['captured_at']),rid))
        if len(candidates)<size:raise ValueError('ALL_MODEL_NATIVE_COHORT_INSUFFICIENT_RACES')
        chosen_ids=candidates[:size]
    chosen_ids=sorted(chosen_ids,key=lambda rid:(ts(complete[rid][0]['result']['captured_at']),rid))
    selected=[row for race in chosen_ids for row in complete[race]]
    summary=dict(cohort_race_count=len(chosen_ids),cohort_required_frozen_cells=5,
        cohort_input_record_count=len(selected),cohort_races_sha256=digest(chosen_ids),
        cohort_selection='EXPLICIT_CANONICAL_RACE_IDS' if race_ids else 'EARLIEST_AVAILABLE_COMPLETE_NATIVE_COHORT',
        cohort_selected_by_winning_order=False)
    return selected,summary


def _merge_verified_result_observations(observations):
    """Select latest canonical captures without rewriting authenticated bytes."""
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.observed_weight_learning import ts
    seen={};latest={}
    for original in observations:
        race=_race_key(original['race_id'],'boat');captured=ts(original['captured_at'])
        normalized=deepcopy(original);normalized['race_id']=race
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


def load_intake(restored_dir,state_input,dataset_input,*,now,native_archive_dirs=(),derive_observed=False,
                native_round_archive_dirs=(),result_archive_dirs=(),cohort_race_ids=(),cohort_size=None):
    rows,observations,pointer,content=load_verified_intake(restored_dir,state_input,now=now,authenticate_owner_cipher=True)
    result_admissions=[]
    if result_archive_dirs:
        from race_ai.all_existing_model_result_intake import observations_from_result_artifact
        if type(result_archive_dirs) not in (tuple,list) or len(result_archive_dirs)>32:
            raise ValueError('ALL_MODEL_RESULT_ARCHIVE_BOUNDED_LIST_REQUIRED')
        combined=list(observations);seen_results={}
        for path in result_archive_dirs:
            raw,metadata=_native_archive(path);_reverify_native_metadata(metadata)
            run=metadata['workflow_run']
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
    intake=training_intake(rows,observations,dataset_pointer=dataset)
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
            raw,metadata=_native_archive(path);_reverify_native_metadata(metadata)
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
            records=_merge_native_records(records,admitted['records'])
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
    if cohort_race_ids or cohort_size is not None:
        if not derive_observed:raise ValueError('ALL_MODEL_NATIVE_COHORT_EXPLICIT_DERIVATION_REQUIRED')
        records,cohort=_select_native_cohort(records,race_ids=cohort_race_ids,size=cohort_size)
        intake=deepcopy(intake);intake.update(cohort)
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
    return records,dict(source_pointer=pointer,state_content_sha256=content,dataset_pointer=dataset,
        source_refs=intake['source_refs'],intake_sha256=_intake_identity(records,result_admissions=result_admissions),
        registry_sha256=registry_sha256()),intake


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
        records,binding,intake=load_intake(args.restored_dir,args.state_input,args.dataset_input,**options)
        record_path=Path(args.owner_research_record)
        if args.command=='issue-decision':
            if record_path.exists() or any(p.is_symlink() for p in (record_path.absolute(),*record_path.absolute().parents)):
                raise ValueError('ALL_MODEL_OWNER_RESEARCH_RECORD_EXISTS_DO_NOT_RESET')
            expiry=datetime.fromisoformat(args.expires_at.replace('Z','+00:00')) if args.expires_at else now+timedelta(days=90)
            decision=issue_decision(**binding,now=now,expires_at=expiry)
            record_path.parent.mkdir(parents=True,exist_ok=True)
            _write(record_path,json.dumps(decision,sort_keys=True,indent=2).encode()+b'\n')
            print(json.dumps(dict(state='OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED',decision_sha256=digest(decision),
                model_family_count=16,applicable_model_cells=31,provider_permission_confirmed=False,production_promoted=False)));return 0
        if not args.out_dir:parser.error('--out-dir is required for fit')
        decision=json.loads(_read(record_path,100000));decision_sha=verify_decision(decision,**binding,now=now)
        admitted={tuple(p) for p in binding['source_refs']}
        def analysis(url,rights,purpose):return purpose=='analysis' and (url,rights) in admitted
        def training(url,rights,purpose):return purpose=='model_training' and (url,rights) in admitted
        trained=fit(records,now=now,allow_source=analysis,allow_training=training)
        trained.update(training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=decision_sha,
            venue_dataset_sha256=binding['dataset_pointer']['dataset_sha256'],
            source_content_sha256=binding['state_content_sha256'])
        if args.derive_from_observed:
            trained.update(owner_bound_intake_sha256=binding['intake_sha256'],
                intake_identity_semantics='DATA_AND_PARAMETER_CONTRACTS_WITH_SEPARATE_DERIVATION_CLOCK')
        if args.result_archive_dir:
            trained.update(owner_bound_intake_sha256=binding['intake_sha256'],
                result_archive_admissions_sha256=digest(intake['result_archive_admissions']))
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
        result=seal_candidate(dict(summary=summary,training=trained,excluded=[],owner_research_record=decision),args.out_dir)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('(ALL_MODEL_[A-Z_]{1,100}|VENUE_LEARNING_[A-Z_]{1,100})',str(exc)) else 'ALL_MODEL_OPERATION_REJECTED'
        print(json.dumps(dict(state='HOLD_ALL_MODEL_RESEARCH',reason=reason,production_promoted=False,plaintext_published=False)));return 2


if __name__=='__main__':raise SystemExit(main())
