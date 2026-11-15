"""Authenticate saved future provenance after results, without a runtime tree.

The caller supplies records already returned by the native artifact reader.
This reader authenticates their sealed generation and retained source claims;
it does not fetch or reparse the original source documents, refit a model, or
create a current training permission or a new GitHub receipt.
"""
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
import hmac
import io
import re
import stat
import zipfile
import zlib

from .actions_contract import digest,stamp
from . import all_existing_model_registry as registry
from . import all_existing_model_research as research
from . import all_existing_model_future_baseline as baseline
from . import boat_all_model_store as store
from .all_existing_model_learning import _sources
from .all_existing_model_pairs import CAPSULE_FIELDS,record_partition_key,_seal_cutoff,_training_receipt
from .all_existing_model_receipt import _metadata as native_metadata_check,_entries
from .boat_pdca_state import state_key
from .existing_model_dispatch import _race_key
from .four_sport_learning import LEARNED_ID
from scripts import all_existing_model_native_future as future

SCHEMA='RACE_AI_CASH_NATIVE_PDCA_ORIGIN_CONTEXT_V1'


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_CASH_ORIGIN_'+reason)


def _hash(value):return type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None


def _origin_cipher(raw,metadata,native_metadata,now):
    run=native_metadata['workflow_run'];actual=metadata.get('workflow_run')
    need(type(metadata.get('id')) is int and metadata['id']>0 and metadata.get('expired') is False and
         metadata.get('name')==f'all-native-future-origin-{run["id"]}-{future.ORIGIN_ROUND}' and
         type(actual) is dict and type(actual.get('id')) is int and actual['id']==run['id'] and
         actual.get('head_sha')==run['head_sha'] and all(type(actual.get(k)) is int and actual[k]==1416489937
             for k in ('repository_id','head_repository_id')),'ARTIFACT_IDENTITY')
    need(type(raw) is bytes and 0<len(raw)<=store.MAX_WIRE+1024*1024 and
         type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes']==len(raw) and
         metadata.get('digest')=='sha256:'+sha256(raw).hexdigest(),'ARTIFACT_BYTES')
    need(stamp(metadata['created_at'])<=now<stamp(metadata['expires_at']),'ARTIFACT_CLOCK')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();need(len(entries)==1,'ONE_ORIGIN_MEMBER_REQUIRED')
            entry=entries[0]
            need(entry.filename==entry.orig_filename=='origin.enc' and not entry.flag_bits&0x41 and
                 stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and
                 entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                 0<entry.file_size<=store.MAX_WIRE,'ORIGIN_MEMBER_INVALID')
            with archive.open(entry) as source:cipher=source.read(store.MAX_WIRE+1)
            need(len(cipher)==entry.file_size,'ORIGIN_MEMBER_SIZE')
    except (zipfile.BadZipFile,RuntimeError,EOFError,zlib.error):
        raise ValueError('ALL_MODEL_CASH_ORIGIN_ARCHIVE_INVALID') from None
    header=store.forecast_header(cipher)
    need(header['run_id']==str(run['id']) and header['round_no']==future.ORIGIN_ROUND,'ORIGIN_HEADER')
    return cipher,store.open_forecasts(cipher)


def _historical_owner(owner,created,expected_hash):
    need(type(owner) is dict and set(owner)=={'schema','decision','mac'} and
         owner['schema'] in (research.SCHEMA,research.ORDER_SCHEMA) and digest(owner)==expected_hash,'BASELINE_OWNER_RECORD')
    order=owner['schema']==research.ORDER_SCHEMA;decision=owner['decision']
    need(type(decision) is dict and set(decision)==research.FIELDS|({'label_evaluation_scope'} if order else set()) and
         _hash(owner['mac']) and hmac.compare_digest(owner['mac'],research._mac(decision,schema=owner['schema'])),
         'BASELINE_OWNER_MAC')
    scope=research._scope(registry.registry_sha256())
    need(decision['repository_id']=='1416489937' and decision['basis']=='OWNER_PERSONAL_RESEARCH' and
         decision['purpose']==(research.ORDER_PURPOSE if order else research.PURPOSE) and
         decision['instruction_ref']==research.INSTRUCTION and all(decision[k] is False for k in research.FALSE_FIELDS) and
         all(decision[k]==value for k,value in scope.items()) and
         stamp(decision['issued_at'])<=created<stamp(decision['expires_at']),'BASELINE_OWNER_SCOPE')
    if order:
        from .official_order_only_result import EVALUATION_SCOPE
        need(decision['label_evaluation_scope']==EVALUATION_SCOPE,'BASELINE_OWNER_LABEL_SCOPE')


def _historical_baseline(capsule,manifest,training,candidate_receipt,original_generation):
    """Replay the available retained proof at its original clocks, not today."""
    payload=capsule['native_payload'];proof=payload.get('baseline_attachment');native=payload.get('learned_model')
    need(type(proof) is dict and set(proof)==baseline.PROOF_FIELDS and proof.get('schema')==baseline.SCHEMA and
         type(native) is dict,'BASELINE_ATTACHMENT_REQUIRED')
    original=deepcopy(payload);del original['baseline_attachment'];del original['learned_model']
    need(proof['original_payload_sha256']==digest(original) and _hash(proof['model_sha256']) and
         _hash(proof['training_sha256']) and native.get('model_sha256')==proof['native_model_sha256']==
         digest({k:v for k,v in native.items() if k!='model_sha256'}),'BASELINE_MODEL_BINDING')
    pin=baseline.validate_pin(proof['pin']);receipt=proof['artifact_receipt'];run=receipt.get('workflow_run')
    need(pin==manifest['horse_baseline_artifact'] and pin['id']!=candidate_receipt['id'] and
         receipt.get('id')==pin['id'] and receipt.get('digest')==pin['digest'] and receipt.get('expired') is False and
         type(receipt.get('size_in_bytes')) is int and receipt['size_in_bytes']>0 and type(run) is dict and
         run.get('id')==pin['run_id'] and run.get('head_sha')==pin['head_sha'] and
         all(type(run.get(k)) is int and run[k]==1416489937 for k in ('repository_id','head_repository_id')) and
         type(receipt.get('name')) is str and re.fullmatch(
             '(?:boat-venue-learning|all-existing-model-learning)-'+str(pin['run_id'])+'-[1-9][0-9]*',receipt['name']),
         'BASELINE_RECEIPT_BINDING')
    selected=payload['snapshot'];created=stamp(native['created_at']);asof=stamp(selected['race']['as_of'])
    attached=stamp(proof['attached_at']);source=proof['source_metadata']
    fetched=stamp(source['fetched_at']);completed=stamp(source['response_received_at'])
    need(native.get('model_id')==LEARNED_ID and native.get('sport')=='horse' and
         native.get('trained_scope')==selected['scope']==training['scope'] and
         native.get('input_schema',registry.SHARED_SCHEMA)==selected['schema'] and stamp(native['trained_until'])<asof and
         created<fetched and stamp(receipt['created_at'])+timedelta(seconds=1)<=fetched<=completed<=asof<=attached<=
         original_generation<stamp(receipt['expires_at']) and
         stamp(receipt['created_at'])+timedelta(seconds=1)<=stamp(training['created_at']),
         'BASELINE_HISTORICAL_CLOCK')
    need(type(source.get('status')) is int and source['status']==200 and _hash(source.get('source_sha256')) and
         any(e.get('source_ref',e.get('source_url'))==source.get('source_url') and
             e.get('source_sha256')==source['source_sha256'] and stamp(e['captured_at'])==completed
             for e in original.get('source_evidence',[]) if type(e) is dict),'BASELINE_SOURCE_BINDING')
    _historical_owner(proof['owner_research_record'],created,proof['owner_research_record_sha256'])
    need(type(proof['source_lineage']) is list and bool(proof['source_lineage']) and
         proof['historical_source_refs']==[list(pair) for pair in sorted(_sources(proof['source_lineage']))],
         'BASELINE_SOURCE_LINEAGE')
    for row in proof['source_lineage']:
        need(stamp(row['as_of'])<=stamp(row['input_saved_at'])<stamp(row['cutoff_at'])<=
             stamp(row['result_captured_at'])<=created,'BASELINE_LINEAGE_CLOCK')


def _source_audit(audit,manifest,capsules,selected_at,forecast_generated,training,candidate_receipt):
    need(audit.get('source_clocks_rewritten') is False and audit.get('native_input_clocks_rewritten') is False and
         audit.get('provider_refetched') is False and sorted(digest(c) for c in audit['capsules'])==
         sorted(digest(c) for c in capsules),'SOURCE_CAPSULE_BINDING')
    requests=[dict(cell_key=c['cell_key'],native_payload=c['native_payload']) for c in capsules]
    clocks,unknown=future._retained_source_clocks(requests,selected_at)
    need(audit.get('retained_source_clocks')==clocks and type(audit.get('source_capture_clock_missing_count')) is int and
         audit['source_capture_clock_missing_count']==unknown,'SOURCE_CAPTURE_CLOCKS')
    admissions=audit['source_admissions'];pins=manifest['source_input_artifacts']
    need(type(admissions) is list and len(admissions)==len(pins) and
         len({a['artifact_id'] for a in admissions})==len(pins),'SOURCE_ADMISSIONS')
    sources={}
    for pin in pins:
        matches=[a for a in admissions if a['artifact_id']==pin['id']];need(len(matches)==1,'SOURCE_ADMISSION_PIN')
        current=matches[0]
        need(current.get('artifact_digest')==pin['digest'] and current.get('workflow_run_id')==pin['run_id'] and
             current.get('head_sha')==pin['head_sha'] and current.get('independent_pre_cutoff_receipt_verified') is True and
             stamp(current['saved_at'])<=selected_at and type(current.get('record_sha256')) is list and
             all(_hash(value) for value in current['record_sha256']),'SOURCE_ADMISSION_BINDING')
        for value in current['record_sha256']:sources.setdefault(value,[]).append(stamp(current['saved_at']))
    originals=audit['original_source_partitions'];need(type(originals) is list and bool(originals),'SOURCE_ORIGINALS')
    baseline_count=0
    for capsule in capsules:
        need(type(capsule) is dict and set(capsule)==CAPSULE_FIELDS and capsule['input_sha256']==digest(capsule['native_payload']),
             'SOURCE_INPUT_HASH')
        matches=[o for o in originals if o['cell_key']==capsule['cell_key'] and o['input_sha256']==capsule['input_sha256']]
        need(bool(matches),'SOURCE_ORIGINAL_REQUIRED')
        for original in matches:
            source_generated=stamp(original['original_generated_at'])
            need(original.get('already_forecast_with_candidate') is not True and
                 original['source_record_sha256'] in sources and stamp(capsule['captured_as_of'])<=source_generated<=selected_at<=
                 forecast_generated and any(source_generated<saved+timedelta(seconds=1)<stamp(capsule['cutoff_at'])
                     for saved in sources[original['source_record_sha256']]),'SOURCE_ORIGINAL_CLOCK')
            if manifest['schema']==future.MANIFEST_SCHEMA_V4 and capsule['cell_key']=='horse/'+LEARNED_ID:
                _historical_baseline(capsule,manifest,training,candidate_receipt,source_generated)
        if manifest['schema']==future.MANIFEST_SCHEMA_V4 and capsule['cell_key']=='horse/'+LEARNED_ID:baseline_count+=1
    need(all(any(o['cell_key']==c['cell_key'] and o['input_sha256']==c['input_sha256'] for c in capsules)
         for o in originals),'UNSELECTED_SOURCE_ORIGINAL')
    return baseline_count


def verify_origin_artifact(origin_raw,origin_metadata,native_raw,native_metadata,admission,records,*,now,candidate_cell_count):
    """Authenticate existing 19/30 future originals; never advance their clocks."""
    state_key('production')
    need(type(now) is datetime and now.utcoffset() is not None and type(candidate_cell_count) is int and
         candidate_cell_count in (19,30),'CLOCK_OR_CANDIDATE_COUNT')
    try:
        need(type(native_metadata) is dict and type(origin_metadata) is dict and type(admission) is dict and
             type(records) is list and 0<len(records)<=candidate_cell_count,'READER_CONTEXT')
        run=native_metadata['workflow_run'];native_saved=native_metadata_check(native_raw,native_metadata,now,run['id'],run['head_sha'])
        need(native_metadata['name']==f'all-existing-model-pairs-{run["id"]}-{future.ROUND}' and
             admission.get('artifact_id')==native_metadata['id'] and admission.get('artifact_digest')==native_metadata['digest'] and
             admission.get('workflow_run_id')==run['id'] and admission.get('head_sha')==run['head_sha'] and
             admission.get('saved_at')==native_metadata['created_at'] and
             admission.get('independent_pre_cutoff_receipt_verified') is True,'NATIVE_ADMISSION_BINDING')
        cipher,bundle=_origin_cipher(origin_raw,origin_metadata,native_metadata,now)
        need(type(bundle) is dict and set(bundle)=={'schema','manifest','generation','source_audit'} and
             bundle['schema']==future.ORIGIN_SCHEMA,'ORIGIN_SCHEMA')
        manifest=future.validate_manifest(bundle['manifest']);generation=bundle['generation'];audit=bundle['source_audit']
        profile='V4' if candidate_cell_count==19 else 'V3';expected_schema=future.MANIFEST_SCHEMA_V4 if profile=='V4' else future.MANIFEST_SCHEMA_V3
        need(manifest['schema']==expected_schema and manifest['candidate_cell_count']==candidate_cell_count and
             type(generation) is dict and _hash(generation.get('owner_generation_mac')) and
             hmac.compare_digest(generation['owner_generation_mac'],future._generation_mac_v3(generation)),
             'GENERATION_MAC_OR_SCOPE')
        need(generation.get('schema')==future.SCHEMA and generation.get('ready') is True and
             generation.get('candidate_cell_count')==candidate_cell_count and generation.get('manifest_sha256')==digest(manifest) and
             generation.get('source_audit_sha256')==digest(audit) and generation.get('workflow_run_id')==run['id'] and
             generation.get('expected_head_sha')==run['head_sha'] and generation.get('source_input_artifacts')==manifest['source_input_artifacts'],
             'GENERATION_BINDING')
        if profile=='V4':need(generation.get('future_protocol')=='V4_FIXED_NINETEEN_V1' and
             generation.get('horse_baseline_artifact')==manifest['horse_baseline_artifact'],'NINETEEN_BASELINE_PIN')
        else:need('future_protocol' not in generation,'THIRTY_PROTOCOL')
        need(audit.get('schema')=='RACE_AI_ALL_NATIVE_FUTURE_PROVENANCE_'+profile,'SOURCE_AUDIT_SCHEMA')
        training=records[0]['training'];receipt=records[0]['training_receipt']
        future._training_profile(training,audit.get('owner_research_record'),require_owner=True,profile=profile)
        record_hashes=sorted(digest(record) for record in records)
        need(generation.get('training_sha256')==training['training_sha256'] and
             generation.get('candidate_artifact_id')==manifest['candidate_artifact_id']==receipt['id'] and
             generation.get('candidate_digest')==manifest['candidate_digest']==receipt['digest'] and
             generation.get('local_record_sha256')==record_hashes==sorted(admission['record_sha256']) and
             len({record_partition_key(record) for record in records})==len(records) and
             all(record['training']==training and record['training_receipt']==receipt for record in records),
             'CANDIDATE_OR_RECORD_BINDING')
        with zipfile.ZipFile(io.BytesIO(native_raw)) as archive:_entries(archive)
        need(future._archive_member_hashes_v3(native_raw)==generation['local_member_sha256'],'NATIVE_MEMBER_BYTES')
        cutoff=min(_seal_cutoff(record) for record in records);origin_generated=stamp(generation['origin_generated_at'])
        origin_saved=stamp(origin_metadata['created_at']);selected_at=stamp(audit['selected_at'])
        generated=[stamp(record['generated_at']) for record in records]
        need(stamp(generation['cutoff_at'])==cutoff and selected_at<=min(generated)<=max(generated)<=origin_generated<=now and
             origin_generated<origin_saved+timedelta(seconds=1) and
             native_saved+timedelta(seconds=1)+future.MINIMUM_LEAD<cutoff and
             origin_saved+timedelta(seconds=1)+future.MINIMUM_LEAD<cutoff,'ORIGINAL_SAVE_CLOCK')
        available=stamp(receipt['created_at'])+timedelta(seconds=1)
        need(stamp(audit['candidate_available_at'])==available<=selected_at,'CANDIDATE_AVAILABILITY_CLOCK')
        for generated_at in generated:_training_receipt(training,receipt,generated_at)
        cells=future._profile_cells(profile);counts={sport:0 for sport in cells};cases={};capsules=[]
        for record in records:
            cell=record['cell_key'];sport,mid=cell.split('/',1);pair=record['pair'];info=registry.identity(mid,sport,record['native_payload'])
            need(sport in cells and cell in cells[sport] and _race_key(pair['race_id'],sport)==_race_key(info['race_id'],sport) and
                 stamp(pair['cutoff_at'])==stamp(info['race_cutoff_at']) and pair['input_sha256']==digest(record['native_payload']),
                 'NATIVE_RACE_BINDING')
            counts[sport]+=1;cases.setdefault(sport,[]).append((record,info));capsules.extend(record.get('captured_native_inputs',[]))
        selected=[]
        for sport,members in cases.items():
            first=members[0][1];race=_race_key(first['race_id'],sport);member_cutoff=stamp(first['race_cutoff_at'])
            need(len(members)==len(cells[sport]) and {r['cell_key'] for r,_ in members}==cells[sport] and
                 all(_race_key(info['race_id'],sport)==race and info['roster']==first['roster'] and
                     stamp(info['race_cutoff_at'])==member_cutoff and info['scope']==training['scope'] and
                     (sport!='boat' or info['stage']=='P1') for _,info in members),'COMPLETE_SPORT_CASE')
            selected.append((sport,race,member_cutoff))
        complete='all_nineteen_cells_produced' if profile=='V4' else 'all_thirty_cells_produced'
        held=generation['held_sports']
        need(generation.get('forecast_counts_by_sport')==counts and generation.get(complete) is (len(records)==candidate_cell_count) and
             set(held)=={sport for sport,count in counts.items() if count==0} and
             all(held[sport]['not_generated_cells']==sorted(cells[sport]) for sport in held) and
             {(item['sport'],item['race_id'],stamp(item['cutoff_at'])) for item in audit['selected_cases']}==set(selected),
             'PARTIAL_SPORT_BINDING')
        need(all(type(generation.get(field)) is int and generation[field]==len(records) for field in
             ('forecast_partition_count','baseline_forecast_count','learned_forecast_count','captured_native_input_count')) and
             admission.get('forecast_partition_count')==admission.get('partition_count')==len(records) and
             admission.get('frozen_input_only_partition_count')==0 and
             admission.get('captured_native_input_count')==len(capsules)==len(records),'FORECAST_COUNTS')
        need(len({(cap['cell_key'],cap['input_sha256']) for cap in capsules})==len(capsules) and
             all(any(cap['cell_key']==record['cell_key'] and cap['input_sha256']==digest(record['native_payload'])
                 for cap in capsules) for record in records),'EXACT_NATIVE_CAPSULES')
        baseline_count=_source_audit(audit,manifest,capsules,selected_at,min(generated),training,receipt)
        if profile=='V4':
            horse=[cap for cap in capsules if cap['cell_key']=='horse/'+LEARNED_ID]
            if horse:need(audit.get('horse_baseline_receipt')==horse[0]['native_payload']['baseline_attachment']['artifact_receipt'],
                'BASELINE_AUDIT_RECEIPT')
        summary=dict(schema=SCHEMA,origin_artifact_id=origin_metadata['id'],origin_artifact_digest=origin_metadata['digest'],
            native_artifact_id=native_metadata['id'],native_artifact_digest=native_metadata['digest'],candidate_cell_count=candidate_cell_count,
            training_sha256=training['training_sha256'],manifest_sha256=digest(manifest),source_audit_sha256=digest(audit),
            forecast_partition_count=len(records),forecast_counts_by_sport=counts,all_candidate_cells_produced=len(records)==candidate_cell_count,
            independent_origin_receipt_verified=True,independent_native_receipt_verified=True,
            original_owner_research_record_verified=True,original_source_provenance_authenticated=True,
            raw_source_documents_replayed=False,baseline_full_training_replayed=False,
            historical_baseline_attachment_count=baseline_count,current_training_admission_created=False,github_receipt_created=False)
        return dict(schema=SCHEMA,manifest=deepcopy(manifest),generation=deepcopy(generation),source_audit=deepcopy(audit),
            origin_metadata=deepcopy(origin_metadata),origin_cipher_sha256=sha256(cipher).hexdigest(),summary=summary)
    except (KeyError,TypeError,AttributeError,IndexError,OverflowError):
        raise ValueError('ALL_MODEL_CASH_ORIGIN_STRUCTURE_INVALID') from None
