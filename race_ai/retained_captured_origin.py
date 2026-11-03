"""Explicit retained B+K origin admission; no I/O, inference or authentication.

The caller supplies byte pins. Historical outcomes were already supplied in
memory; only the lazy journal can reserve declared exposure before reading them.
Git blobs are reconstructed, but complete Git commit/tree objects are not.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import math
import re

from .boat_captured_history_bridge import build_program_history_snapshot
from .retained_prediction_audit import (ALIASES, JST, RetainedAuditError, byte_sha,
    canonical, decode, digest, moment, require, valid_sha, _forbid_results,
    _race_identity, _ticket)

PROFILE = 'RACE41_CAPTURED_HISTORY_V1'
ROLES = {'facts','bundle','seal','manifest','proof','registry','history','parent','witness','witness_source'}
RUNNABLE = {'boat-observed-pairwise-factor-v1','boat-observed-pairwise-start-v1',
            'official-program-uniform-pl','official-program-rating-pl'}
MISSING = {
    **{mid:'FULL_COMMON_SPORT_ENVIRONMENT_FEATURES_UNAVAILABLE' for mid in (
        'multisport-factor-interaction-v1','multisport-scenario-ensemble-v1',
        'multisport-conditional-duel-v1','multisport-race-trajectory-v1')},
    'multisport-chronological-ranker-v1':'NO_ELIGIBLE_PRIOR_FITTED_ARTIFACT_AND_FULL_INPUT',
    'boat-comprehensive-v1':'SEVEN_RATINGS_AND_TRUE_WEATHER_CONDITIONS_UNAVAILABLE',
    'boat-scenario-mixture-v1':'SEVEN_RATINGS_AND_TRUE_WEATHER_CONDITIONS_UNAVAILABLE',
    'boat-b-lite-v1-untrained':'CORE_SAMPLE_COUNTS_PUBLICATION_AND_COURSE_SCORE_UNAVAILABLE',
    'boat-enriched-v1-untrained':'CORE_SAMPLE_COUNTS_PUBLICATION_AND_COURSE_SCORE_UNAVAILABLE',
    'official-beforeinfo-display-pl':'NO_OBSERVED_EXHIBITION_AT_P0',
    'official-display-original-pl':'NO_OBSERVED_ORIGINAL_TIMINGS_AT_P0',
    'name-bound-display':'NO_GENUINE_NAME_BINDING_AND_EXHIBITION_AT_P0',
    'name-bound-original':'NO_GENUINE_NAME_BINDING_AND_EXHIBITION_AT_P0',
    'history-course-plackett-luce':'NO_VERIFIED_CURRENT_COURSE_OR_PUBLISHED_HISTORY_ADMISSION',
    'linear-plackett-luce-research':'NO_ELIGIBLE_PRIOR_FITTED_ARTIFACT_AND_FEATURES'}
MODEL_PATHS = {
    **{'legacy:web/'+name+'.py':'/web/'+name+'.py' for name in (
        'evaluation_contract','exhibition_contract','original_exhibition_contract',
        'original_prediction_contract','race_contract','research_contract')},
    **{'pr71:race_ai/'+name+'.py':'/race_ai/'+name+'.py' for name in (
        'actions_contract','boat_observed_pairwise_models','legacy_boat_rank')}}
SOURCE_FIELDS = {'source_id','source_url','source_sha256','source_rights_ref','published_at','captured_at','evidence_basis'}
SUCCESS = 'PRIVATE_INPUT_AND_PREDICTIONS_RETAINED_EXTERNAL_WITNESS_PENDING'


def _wire_sha(value):
    return byte_sha(canonical(value)+b'\n')


def _fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required)|set(optional), 'CAPTURED_FIELDS')


def _false(value, names):
    require(all(value.get(name) is False for name in names), 'CAPTURED_AUTHORITY_UPGRADE')


def _code_pin(pins, suffix):
    candidates = [value for path,value in pins.items() if path.replace('\\','/').endswith(suffix)]
    require(len(candidates) == 1, 'CODE_ROLE_AMBIGUOUS')
    return candidates[0]


def _source(source, day, kind):
    _fields(source, SOURCE_FIELDS)
    compact=day.replace('-','')
    require(source['source_url'] == f'https://www1.mbrace.or.jp/od2/{kind}/{compact[:6]}/{kind.lower()}{compact[2:]}.lzh'
            and valid_sha(source['source_sha256']), 'SOURCE_IDENTITY')
    require(all(type(source[k]) is str and re.fullmatch('[A-Za-z0-9_.:/-]{1,200}',source[k])
                for k in ('source_id','source_rights_ref')), 'SOURCE_REFERENCE')
    require(source['published_at'] is None and source['evidence_basis'] == 'CAPTURED_BY_CLAIM', 'SOURCE_CLOCK_BASIS')
    return moment(source['captured_at'])


def _metadata(values):
    """Optional known metadata is typed evidence, never an arbitrary container."""
    f,b,m=values['facts'],values['bundle'],values['manifest']
    if 'selection' in b:
        require(b['selection']=='ALL_B28_DISCOVERED_RACES_CLOSED_RETAINED_FUTURE_IN_PLANNED_CUTOFF_ORDER','SELECTION_METADATA')
    for key in ('public_payload_allowed','raw_source_persisted'):
        if key in m:require(m[key] is False,'MANIFEST_AUTHORITY')
    if 'normalized_facts_persisted' in m:require(m['normalized_facts_persisted'] is True,'MANIFEST_RETENTION')
    if 'purpose' in m:require(m['purpose']=='pre_race_program_private_analysis','MANIFEST_PURPOSE')
    for key in ('owner_config_sha256','python_sha256'):
        if key in m:require(valid_sha(m[key]),'MANIFEST_METADATA_HASH')
    if 'python_path' in m:
        require(type(m['python_path']) is str and 1<=len(m['python_path'])<=4096 and
                not any(c in m['python_path']for c in '\x00\r\n<>'),'MANIFEST_PATH')
    if 'prior_B_attempt_index' in m:
        index=m['prior_B_attempt_index']
        require(type(index) is dict and len(index)<=1000 and all(type(k) is str and
            re.fullmatch(r'B[0-9]{8}-[a-zA-Z0-9_-]{1,200}\.json',k) and valid_sha(v)for k,v in index.items()),'MANIFEST_PRIOR_INDEX')
    if 'caps' in m:
        caps={'compressed_cap':4000000,'extracted_cap':20000000,'lifecycle_seconds':120,'max_GETs':1,
            'parent_child_timeout_seconds':150,'parent_reap_timeout_seconds':5,'pre_get_seconds':20,'retries':0,'socket_timeout_seconds':10}
        require(type(m['caps']) is dict and m['caps']==caps and all(type(v) is int for v in m['caps'].values()),'MANIFEST_CAPS')
    if 'transport_receipt' in f:
        receipt=f['transport_receipt']
        flags={'allowed_in_predictive_snapshot','allowed_in_verified_settlement','published_content_to_github',
            'source_archive_identity_verified_by_decompressed_contents','source_publication_time_independently_verified',
            'source_sample_sizes_verified','source_terms_legally_verified_by_code'}
        _fields(receipt,flags|{'schema','status','captured_at_local_clock_claimed','compressed_bytes','etag_sha256_if_present',
            'event_date_jst','http_date_response_header_unverified','kind','last_modified_response_header_unverified',
            'provider_archive_sha256','purpose_requested','source_url'})
        _false(receipt,flags)
        require(receipt['schema']=='RACE_AI_BK_ONE_SHOT_ARCHIVE_RECEIPT_V1' and receipt['status']=='PRIVATE_QUARANTINE_BK_ARCHIVE_ONLY'
            and receipt['kind']=='B' and receipt['purpose_requested']=='pre_race_program_private_analysis'
            and receipt['event_date_jst']==m['day_jst'] and receipt['source_url']==b['source']['source_url']
            and receipt['provider_archive_sha256']==b['source']['source_sha256']
            and receipt['captured_at_local_clock_claimed']==b['source']['captured_at'],'TRANSPORT_RECEIPT_BINDING')
        require(type(receipt['compressed_bytes']) is int and 0<receipt['compressed_bytes']<=4000000 and
            (receipt['etag_sha256_if_present'] is None or valid_sha(receipt['etag_sha256_if_present'])),'TRANSPORT_RECEIPT_SIZE')
        for key in ('http_date_response_header_unverified','last_modified_response_header_unverified'):
            value=receipt[key]
            require(value is None or type(value) is str and re.fullmatch(
                r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT',value), 'TRANSPORT_HEADER_SHAPE')


def _history(packet, bundle, manifest, pins):
    _fields(packet, {'status','day','source_get_attempts','raw_source_persisted','source','history'},
        {'completed_at','current_race_prediction_input','historical_event_day_only','manifest_sha256','models_executed',
         'normalizer_sha256','odds_or_payouts_extracted','parser_sha256','retries','runtime_sha256','started_at'})
    require(packet['status']=='PRIVATE_NORMALIZED_HISTORY_ONLY' and type(packet['source_get_attempts']) is int
            and packet['source_get_attempts']==1 and packet['raw_source_persisted'] is False, 'HISTORY_ORIGIN')
    for key in ('models_executed','current_race_prediction_input','odds_or_payouts_extracted'):
        if key in packet:require(packet[key] is False,'HISTORY_AUTHORITY')
    if 'historical_event_day_only' in packet:require(packet['historical_event_day_only'] is True,'HISTORY_DAY_AUTHORITY')
    day=packet['day']; _race_identity(day.replace('-','')+'-01-01')
    require(day < manifest['day_jst'], 'HISTORY_TARGET_DAY')
    source=packet['source']
    _fields(source, SOURCE_FIELDS-{'source_id'}|{'event_date_jst','kind','purpose','source_rights_basis'},
            {'archive_bytes','extracted_bytes','extracted_text_sha256'})
    projected={key:source[key]for key in SOURCE_FIELDS-{'source_id'}}
    projected['source_id']='race39-retained-k'+day.replace('-','')
    require(projected==bundle['history_source'] and source['event_date_jst']==day and source['kind']=='K'
            and source['purpose']=='post_race_results_private_audit'
            and source['source_rights_basis']=='OWNER_ATTESTATION_NOT_INDEPENDENT_AUDIT','HISTORY_SOURCE')
    _source(projected,day,'K')
    require(manifest['history_packet_sha256']==bundle['history_packet_sha256']==pins['history']
            and manifest['history_archive_sha256']==projected['source_sha256'],'HISTORY_HASH')
    history=packet['history']
    _fields(history,{'rows','complete_races','whole_day_completeness_proven','provider_finality_verified','race_at_semantics'},
            {'empty_venue_blocks','race_headers','race_time_precision','rejected_races'})
    require(type(history['rows']) is list and len(history['rows'])==864 and history['complete_races']==144,
            'HISTORY_MEMBERSHIP_SIZE')
    _false(history,('whole_day_completeness_proven','provider_finality_verified'))
    require(history['race_at_semantics']=='PARSER_DATE_SENTINEL_UTC_MIDNIGHT_NOT_ACTUAL_START'
            and history.get('race_time_precision')=='DATE_ONLY','HISTORY_TIME_SEMANTICS')
    ids=sorted({row['race_id']for row in history['rows']})
    require(len(ids)==144 and all(_race_identity(rid)['event_date_jst']==day for rid in ids),'HISTORY_RACE_SET')
    return history['rows'],projected,ids


def _models(entries, registry, closed):
    require(type(entries) is list and len(entries)==19 and [x['model_id']for x in entries]==[x['model_id']for x in registry],
            'MODEL_MATRIX_CHANGED')
    all_tickets=set(itertools.permutations(range(1,7),3)); output=[]
    for entry,registered in zip(entries,registry):
        mid=entry['model_id']; require(entry['stage']=='P0' and entry['model_version']==registered['model_version'], 'MODEL_VERSION')
        if closed or mid not in RUNNABLE:
            _fields(entry,{'model_id','model_version','stage','status','reason','top8','scores120'}, {'numerical_alias_of'})
            require(entry['status']=='NO_FORECAST' and entry['top8'] is None and entry['scores120'] is None
                    and entry['reason']==('CLOSED_BEFORE_INFERENCE'if closed else MISSING[mid]),'MISSING_FORECAST_CHANGED')
            model=deepcopy(entry);model['inner_digest_verification']='NO_FORECAST'
        else:
            pair=mid.startswith('boat-observed-pairwise-')
            _fields(entry, {'model_id','model_version','stage','status','top8','scores120','method','forecast_sha256','numerical_alias_of'},
                    {'source_model_status'}if pair else{'baseline_model_id'})
            require(entry['status']=='FORECAST' and valid_sha(entry['forecast_sha256']) and entry['numerical_alias_of'] is None
                    and entry['method']==('EXACT_PR71_PREDICT_PAIR'if pair else'PINNED_LEGACY_NUMERIC_FORMULA_AND_PL_KERNEL'), 'FORECAST_METHOD')
            if pair:require(entry.get('source_model_status') in ('OBSERVED_CONTRASTS','UNINFORMATIVE_TIE_BREAK'),'MODEL_STATUS')
            else:require(entry.get('baseline_model_id') is None,'LEGACY_BASELINE')
            rows=entry['scores120'];require(type(rows) is list and len(rows)==120,'COMPLETE_SCORE_ARRAY')
            pairs=[]
            for row in rows:
                _fields(row,{'combination','score'});score=row['score']
                require(type(score) in(int,float) and math.isfinite(score) and 0<=score<=1,'SCORE_NUMBER')
                pairs.append((_ticket(row['combination']),score))
            require({tuple(t)for t,_ in pairs}==all_tickets and pairs==sorted(pairs,key=lambda x:(-x[1],x[0])), 'SCORE_COVERAGE_OR_ORDER')
            require(abs(math.fsum(s for _,s in pairs)-1)<=1e-12,'SCORE_MASS')
            top=[_ticket(t)for t in entry['top8']]
            require(len(top)==8 and top==[t for t,_ in pairs[:8]],'TOP8_SCORE_MISMATCH')
            model=deepcopy(entry);model['top8']=top;model['score_array_sha256']=digest(rows)
            model['inner_digest_verification']='FULL_SOURCE_MODEL_PREIMAGE_NOT_RETAINED'
            if not pair:
                require(digest({k:v for k,v in entry.items()if k!='forecast_sha256'})==entry['forecast_sha256'],'LEGACY_INNER_DIGEST_CHANGED')
                model['inner_digest_verification']='LEGACY_PREIMAGE_VERIFIED'
        model['numerical_alias_of']=ALIASES.get(mid);output.append(model)
    return output


def _witness(values, pins, races, manifest, readback):
    witness=values['witness'];source=values['witness_source']
    _fields(witness,{'schema','all_17_anchor_git_blobs_exact','bundle_sha256','seal_sha256','source_proof_sha256',
        'formal_hit_at_8_all_eligible','individual_model_receipt','official_final_cutoff_authenticated',
        'source_publication_or_capture_authenticated','proof_type','pre_cutoff_count','late_count','run','races'})
    require(witness['schema']=='RACE41_TODAY_GITHUB_BUNDLE_WITNESS_V1' and witness['all_17_anchor_git_blobs_exact'] is True
            and witness['bundle_sha256']==pins['bundle'] and witness['seal_sha256']==pins['seal']
            and witness['source_proof_sha256']==pins['witness_source'],'WITNESS_PARENT')
    _false(witness,('formal_hit_at_8_all_eligible','individual_model_receipt','official_final_cutoff_authenticated','source_publication_or_capture_authenticated'))
    require(witness['proof_type']=='WHOLE_BUNDLE_SHA_PRESENT_ON_GITHUB_BEFORE_PLANNED_CUTOFF','WITNESS_SCOPE')
    _fields(source,{'schema','observed_at','private_payload_public','run','commit','tree'},
            {'smoke_manual_only_fresh','smoke_read_parse_error_then_verified'})
    require(source['schema']=='RACE41_GITHUB_HASH_WITNESS_SOURCE_V1' and source['private_payload_public'] is False,'WITNESS_SOURCE')
    if 'smoke_manual_only_fresh'in source:require(source['smoke_manual_only_fresh'] is True,'WITNESS_WORKFLOW_METADATA')
    if 'smoke_read_parse_error_then_verified'in source:
        require(type(source['smoke_read_parse_error_then_verified']) is str and len(source['smoke_read_parse_error_then_verified'])<=2000,'WITNESS_METADATA')
    run=witness['run'];require(run==source['run'],'WITNESS_RUN_PARENT')
    _fields(run,{'id','created_at','head_sha','head_branch','path','workflow_id','run_attempt','event','status','conclusion','html_url'})
    require(all(type(run[k]) is int and run[k]>0 for k in('id','workflow_id')) and run['run_attempt']==1
            and run['event']=='push' and run['status']=='completed' and run['conclusion']=='success'
            and run['path']=='.github/workflows/p0-freeze-witness.yml'
            and run['head_branch']=='audit/freeze-race41-'+manifest['day_jst'].replace('-',''),'WITNESS_RUN')
    require(type(run['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',run['head_sha'])
            and type(run['html_url']) is str and re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/'+str(run['id']),run['html_url']), 'WITNESS_RUN_ID')
    at=moment(run['created_at']);require(readback<=at,'WITNESS_BEFORE_READBACK')
    observed=source['observed_at']
    if type(observed) is str and re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC',observed):
        observed=datetime.strptime(observed,'%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc).isoformat()
    require(at<=moment(observed),'WITNESS_OBSERVATION_CLOCK')
    commit,tree=source['commit'],source['tree']
    _fields(commit,{'sha','tree_sha','parents','files'});_fields(tree,{'sha','truncated','entries'})
    require(commit['sha']==run['head_sha'] and type(tree['sha']) is str and re.fullmatch('[a-f0-9]{40}',tree['sha'])
            and tree['sha']==commit['tree_sha'] and commit['parents']==[manifest['pr72_head']]
            and tree['truncated'] is False,'WITNESS_TREE')
    computed={r['race_id']:r for r in races if r['state']=='COMPUTED_BEFORE_PLANNED_CUTOFF'}
    wr={r['race_id']:r for r in witness['races']};files={r['path']:r for r in commit['files']};blobs={r['path']:r for r in tree['entries']}
    require(len(wr)==len(witness['races'])==len(files)==len(commit['files'])==len(blobs)==len(tree['entries'])==17
            and set(wr)==set(computed) and set(files)==set(blobs),'WITNESS_SET')
    timely=0;expected_paths=set()
    for rid,race in computed.items():
        row=wr[rid];_fields(row,{'race_id','planned_cutoff_at','anchor_path','hash_witness_before_planned_cutoff'})
        require(row['planned_cutoff_at']==race['planned_cutoff_at'],'WITNESS_CUTOFF')
        flag=at<moment(race['planned_cutoff_at'])
        require(type(row['hash_witness_before_planned_cutoff']) is bool and row['hash_witness_before_planned_cutoff']==flag,'WITNESS_TIMING_FLAG')
        body=canonical({'schema':'RACE_AI_GITHUB_FREEZE_ANCHOR_V1','race_id':rid,'prediction_sha256':pins['seal'],
                        'cutoff_at':race['planned_cutoff_at']})+b'\n'
        path='audit/freezes/'+manifest['day_jst']+'/'+byte_sha((rid+'\0RACE41_WHOLE_BUNDLE_SEAL\0'+pins['seal']).encode())+'.json'
        require(row['anchor_path']==path and path in files and path in blobs,'WITNESS_ANCHOR_PATH');expected_paths.add(path)
        blob=blobs[path];file=files[path];_fields(blob,{'path','sha','type','size'});_fields(file,{'path','status','sha'})
        expected=hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()
        require(blob['type']=='blob' and type(blob['size']) is int and blob['size']==len(body) and blob['sha']==expected
                and file['status']=='added' and file['sha']==expected,'WITNESS_BLOB')
        race['witness_state']='TIMELY_HASH_WITNESS'if flag else'LATE_HASH_WITNESS'
        race['hash_witness_before_planned_cutoff']=flag;timely+=flag
    require(expected_paths==set(files) and timely==witness['pre_cutoff_count']==16 and witness['late_count']==1,'WITNESS_COUNTS')
    return run['created_at']


def _adapt(files, pins):
    require(type(files) is dict and type(pins) is dict and set(files)==set(pins)==ROLES,'ORIGIN_CLOSURE')
    values={}
    for role in sorted(ROLES):
        require(type(files[role]) is bytes and valid_sha(pins[role]) and byte_sha(files[role])==pins[role],'ORIGIN_HASH_CHANGED')
        values[role]=decode(files[role]);require(type(values[role]) is dict,'ORIGIN_OBJECT');_forbid_results(values[role])
    f,b,s,m,p,registry,h,parent=[values[k]for k in('facts','bundle','seal','manifest','proof','registry','history','parent')]
    _fields(f,{'schema','history_packet_sha256','independent_capture_timestamp','normalized','observation_id',
        'raw_lzh_or_text_retained','source','source_publication_at'},{'transport_receipt'})
    _fields(b,{'schema','adapter_sha256','before_write_local_clock_claimed','decompressor_runtime_sha256','external_timestamp_verified',
        'formal_prospective_forecast','history_packet_sha256','history_source','manifest_sha256','model_code_sha256','model_registry',
        'no_target_outcome_or_odds_input','normalized_facts_sha256','observation_id','races','source','stage'},{'selection'})
    _fields(s,{'schema','bundle_sha256','external_timestamp_verified','formal_prospective_forecast','history_packet_sha256',
        'local_storage_immutable','normalized_facts_sha256','observation_id','races','readback_at_local_clock_claimed'})
    _fields(m,{'schema','code_pins','day_jst','history_archive_sha256','history_packet_sha256','observation_id','pr71_head','pr72_head',
        'prepared_at','source_url'},{'caps','normalized_facts_persisted','owner_config_sha256','prior_B_attempt_index',
        'public_payload_allowed','purpose','python_path','python_sha256','raw_source_persisted'})
    _fields(p,{'schema','actual_forecasts','automatic_retry_allowed','bundle_sha256','caller_sha256','completed_at_local_clock_claimed',
        'external_timestamp_verified','formal_prospective_forecast','history_packet_sha256','local_storage_immutable','manifest_sha256',
        'model_slots','normalized_facts_sha256','observation_id','phase','races_computed','races_local_pre_cutoff_readback','raw_source_saved',
        'registry_models','seal_sha256','source_GETs','source_archive_sha256','started_at_local_clock_claimed','status','total_races'})
    _fields(parent,{'accepted_complete','caller_sha256','child_reaped','cleanup_failed','completed_at','exit_code','interrupted',
        'kill_failed','manifest_sha256','proof_sha256','reap_failed','retries','source_GETs','status','timed_out'},
        {'elapsed_seconds','stderr_bytes','stderr_sha256','stdout_bytes','stdout_sha256'})
    for value,schema in((f,'RACE41_TODAY_PRIVATE_NORMALIZED_FACTS_V1'),(b,'RACE41_TODAY_ALL19_PRIVATE_PREDICTION_BUNDLE_V1'),
        (s,'RACE41_TODAY_LOCAL_READBACK_SEAL_V1'),(m,'RACE41_TODAY_CALLER_MANIFEST_V1'),(p,'RACE41_TODAY_EXECUTION_PROOF_V1'),
        (registry,'RACE38_SOURCE_ONLY_MODEL_INVENTORY_V1')):
        require(value.get('schema')==schema,'ORIGIN_SCHEMA')
    observation=m['observation_id'];require(type(observation) is str and 1<=len(observation)<=200
        and all(x['observation_id']==observation for x in(f,b,s,p)),'OBSERVATION_BINDING')
    _metadata(values)
    code=m['code_pins'];require(type(code) is dict and code and all(type(k) is str and 1<=len(k)<=4096 and '\x00'not in k and valid_sha(v)
        for k,v in code.items()) and len({k.replace('\\','/')for k in code})==len(code),'CODE_PINS')
    require(all(type(m[key]) is str and re.fullmatch('[a-f0-9]{40}',m[key])for key in('pr72_head','pr71_head')),'SOURCE_REVISION')
    runtime=b['decompressor_runtime_sha256']
    require(type(runtime) is dict and runtime and all(path in code and valid_sha(value) and code[path]==value for path,value in runtime.items()),'DECOMPRESSOR_CODE_BINDING')
    caller=_code_pin(code,'/artifacts/race41-today-caller.py');_code_pin(code,'/artifacts/race41-today-parent.py')
    require(_code_pin(code,'/artifacts/race38-model-inventory.json')==pins['registry']
            and _code_pin(code,'/race_ai/boat_captured_history_bridge.py')==b['adapter_sha256'],'REGISTRY_OR_ADAPTER_PIN')
    require(type(b['model_code_sha256']) is dict and set(b['model_code_sha256'])==set(MODEL_PATHS)
            and all(b['model_code_sha256'][name]==_code_pin(code,suffix)for name,suffix in MODEL_PATHS.items()),'MODEL_CODE_BINDING')
    require(b['manifest_sha256']==p['manifest_sha256']==parent['manifest_sha256']==pins['manifest'] and p['caller_sha256']==parent['caller_sha256']==caller,'MANIFEST_BINDING')
    require(b['normalized_facts_sha256']==s['normalized_facts_sha256']==p['normalized_facts_sha256']==pins['facts']
            and s['bundle_sha256']==p['bundle_sha256']==pins['bundle'] and p['seal_sha256']==pins['seal']
            and parent['proof_sha256']==pins['proof'],'PROOF_BINDING')
    require(parent['accepted_complete'] is True and parent['child_reaped'] is True and type(parent['exit_code']) is int and parent['exit_code']==0
            and parent['source_GETs']==1 and parent['retries']==0 and parent['status']==p['status']==SUCCESS,'PARENT_COMPLETION')
    _false(parent,('timed_out','interrupted','reap_failed','kill_failed','cleanup_failed'))
    require(p['phase']=='COMPLETE' and p['source_GETs']==1 and b['stage']=='P0' and b['no_target_outcome_or_odds_input'] is True,'ORIGIN_COMPLETE')
    _false(p,('automatic_retry_allowed','raw_source_saved','external_timestamp_verified','formal_prospective_forecast','local_storage_immutable'))
    _false(b,('external_timestamp_verified','formal_prospective_forecast'));_false(s,('external_timestamp_verified','formal_prospective_forecast','local_storage_immutable'))
    _fields(registry,{'schema','models'},{'review_date_jst','roots','pins','actual_result_values_read','network_used','counts','profiles','duplicates','archived_boat_subset'})
    require(registry.get('actual_result_values_read',False) is False and registry.get('network_used',False) is False,'REGISTRY_SOURCE_ONLY')
    model_fields={'model_id','model_version','source_root','source_pin','source_file','entrypoint','line','kind','required_input_profile','top8','notes'}
    require(type(registry['models']) is list and all(type(x) is dict and set(x)<=model_fields for x in registry['models']),'REGISTRY_FIELDS')
    models=[x for x in registry['models']if x['kind']!='synthetic_test_only']
    require(len(models)==19 and b['model_registry']==models and {x['model_id']for x in models}==RUNNABLE|set(MISSING)
            and all(type(x['model_version']) is str and 1<=len(x['model_version'])<=200 for x in models),'REGISTRY_IDENTITY')
    source=b['source'];normalized=f['normalized'];day=m['day_jst'];capture=_source(source,day,'B')
    _fields(normalized,{'date_jst','source_url','source_sha256','first_observed_at','venues','races','complete_six_boat_races'},
            {'extracted_text_sha256','source_hash_scope'})
    require(type(normalized['venues']) is list,'B_VENUES')
    for venue in normalized['venues']:
        _fields(venue,{'venue','races'});require(type(venue['venue']) is str and re.fullmatch('0[1-9]|1[0-9]|2[0-4]',venue['venue'])
            and type(venue['races']) is list and all(r['race_id'][9:11]==venue['venue']for r in venue['races']),'B_VENUE_IDENTITY')
    require(len({v['venue']for v in normalized['venues']})==len(normalized['venues']),'B_VENUE_DUPLICATE')
    require(source['source_id']==observation and source==f['source'] and source['source_url']==m['source_url']==normalized['source_url']
            and normalized['date_jst']==day and source['source_sha256']==normalized['source_sha256']==p['source_archive_sha256']
            and source['captured_at']==normalized['first_observed_at'],'PROGRAM_SOURCE')
    _false(f,('raw_lzh_or_text_retained','independent_capture_timestamp'));require(f['source_publication_at'] is None,'PROGRAM_PUBLICATION')
    history_rows,history_source,history_ids=_history(h,b,m,pins)
    require(all(x['history_packet_sha256']==pins['history']for x in(f,s,p)),'HISTORY_PACKET_LINK')
    history_capture=moment(history_source['captured_at']);written=moment(b['before_write_local_clock_claimed'])
    readback=moment(s['readback_at_local_clock_claimed']);completed=moment(p['completed_at_local_clock_claimed'])
    require(moment(m['prepared_at'])<=moment(p['started_at_local_clock_claimed'])<=capture<=written<=readback<=completed<=moment(parent['completed_at']), 'ORIGIN_CLOCK_ORDER')
    facts=[race for venue in normalized['venues']for race in venue['races']]
    require(len(facts)==normalized['races']==normalized['complete_six_boat_races']==len(b['races'])==len(s['races'])==132,'FULL_COHORT_REQUIRED')
    facts_by={r['race_id']:r for r in facts};seals={r['race_id']:r for r in s['races']}
    require(len(facts_by)==len(seals)==len({r['race_id']for r in b['races']})==132 and set(facts_by)==set(seals)=={r['race_id']for r in b['races']},'RACE_SET')
    require(b['races']==sorted(b['races'],key=lambda r:(moment(r['planned_cutoff_at']),r['race_id'])),'RACE_ORDER')
    output=[];previous=None
    for race in b['races']:
        _fields(race,{'race_id','planned_cutoff_at','race_revision_claim','stage','as_of','input','input_sha256','generated_at',
            'state','models','history_audit','history_packet_sha256','actual_cutoff_verified','roster_withdrawals_verified','formal_prospective_forecast'})
        rid=race['race_id'];identity=_race_identity(rid);fact=facts_by[rid];seal=seals[rid];cutoff=moment(race['planned_cutoff_at']);asof=moment(race['as_of'])
        _fields(seal,{'race_id','planned_cutoff_at','bundle_sha256','local_pre_cutoff_readback'},{'required_external_witness'})
        if 'required_external_witness'in seal:
            require(seal['required_external_witness']=='EXACT_BUNDLE_AND_SEAL_DIGEST_BEFORE_THIS_CUTOFF','SEAL_WITNESS_SCOPE')
        require(identity['event_date_jst']==day and cutoff.astimezone(JST).date().isoformat()==day and race['stage']=='P0'
                and type(race['race_revision_claim']) is int and race['race_revision_claim']==1 and race['history_packet_sha256']==pins['history'],'RACE_IDENTITY')
        _false(race,('actual_cutoff_verified','roster_withdrawals_verified','formal_prospective_forecast'))
        require(max(capture,history_capture)<=asof<=written and(previous is None or previous<=asof),'RACE_CLOCK_ORDER')
        _fields(fact,{'race_id','boats','closed_at','preview_available'})
        require(fact['preview_available'] is False and fact['closed_at']==race['planned_cutoff_at']==seal['planned_cutoff_at']
                and seal['bundle_sha256']==pins['bundle'],'RACE_CUTOFF_BINDING')
        boats=fact['boats'];require(type(boats) is list and len(boats)==6 and all(type(x['lane']) is int for x in boats)
            and {x['lane']for x in boats}==set(range(1,7)),'SIX_BOATS')
        allowed={'lane','racer_registration_id','motor_no','boat_no','name','grade','national_win_rate','local_win_rate','national_top2_rate',
                 'local_top2_rate','motor_top2_rate','boat_top2_rate','average_st','display_time','preview_course','entry_status'}
        require(all(type(x) is dict and set(x)<=allowed and all(x.get(k) is None for k in('average_st','display_time','preview_course'))
                    and x.get('entry_status','listed')=='listed'for x in boats),'BOAT_FIELDS')
        for key in('motor_no','boat_no'):
            require(all(type(x.get(key)) is int and 1<=x[key]<=999 for x in boats) and len({x[key]for x in boats})==6,'B_ALLOCATION')
        registrations={str(x['lane']):x['racer_registration_id']for x in boats}
        require(len(set(registrations.values()))==6 and all(type(x) is str and re.fullmatch('[0-9]{4}',x)for x in registrations.values()),'REGISTRATIONS')
        closed=race['state']=='CLOSED_BEFORE_INFERENCE'
        require(closed or race['state']=='COMPUTED_BEFORE_PLANNED_CUTOFF','RACE_STATE')
        if closed:
            require(race['input'] is None and race['input_sha256'] is None and race['generated_at'] is None and race['history_audit'] is None and asof>=cutoff,'CLOSED_FIELDS')
            previous=asof
        else:
            generated=moment(race['generated_at']);require(asof<=generated<cutoff and generated<=written,'GENERATION_CLOCK');previous=generated
            projected=build_program_history_snapshot(fact,source,history_rows,history_source,event_date_jst=day,as_of=race['as_of'],race_revision=1)
            expected={'case_id':rid,'stage':'P0','legacy':{'boats':[{'lane':x['lane'],'national_win_rate':x.get('national_win_rate')}for x in boats]},
                'source_manifest_sha256':_wire_sha({'program':source,'history':history_source,'history_packet_sha256':pins['history']}),
                'observed_pairwise_snapshot':projected['snapshot']}
            require(canonical(race['input'])==canonical(expected) and race['input_sha256']==_wire_sha(expected)
                    and canonical(race['history_audit'])==canonical(projected['history_audit']),'RETAINED_HISTORY_PROJECTION_CHANGED')
        timely=not closed and readback<cutoff
        require(type(seal['local_pre_cutoff_readback']) is bool and seal['local_pre_cutoff_readback']==timely,'READBACK_FLAG')
        output.append({'race_id':rid,'identity':identity,'registration_ids':registrations,'stage':'P0','planned_cutoff_at':race['planned_cutoff_at'],
            'as_of':race['as_of'],'generated_at':race['generated_at'],'input_sha256':race['input_sha256'],'state':race['state'],
            'models':_models(race['models'],models,closed),'local_pre_cutoff_readback':timely,'actual_cutoff_verified':False,
            'roster_withdrawals_verified':False,'witness_state':'NO_ANCHOR','hash_witness_before_planned_cutoff':None})
    require(Counter(r['state']for r in output)=={'CLOSED_BEFORE_INFERENCE':115,'COMPUTED_BEFORE_PLANNED_CUTOFF':17},'COHORT_COUNTS')
    require(p['total_races']==132 and p['registry_models']==19 and p['model_slots']==2508 and p['actual_forecasts']==68
            and p['races_computed']==17 and p['races_local_pre_cutoff_readback']==sum(r['local_pre_cutoff_readback']for r in output)==17,'PROOF_COUNTS')
    witness_at=_witness(values,pins,output,m,readback)
    return {'profile':PROFILE,'models':[{**deepcopy(x),'numerical_alias_of':ALIASES.get(x['model_id'])}for x in models],
        'races':output,'original_completed_at':p['completed_at_local_clock_claimed'],'original_readback_at':s['readback_at_local_clock_claimed'],
        'original_model_code_sha256':deepcopy(b['model_code_sha256']),'original_source_code_sha256':deepcopy(code),'source':deepcopy(source),
        'history_race_ids':history_ids,'history_source':deepcopy(history_source),'witness_at':witness_at,
        'execution_code_identity_for_missing_models':'NOT_ESTABLISHED_BY_EXECUTED_CODE_SET'}


def adapt_race41(files, pins):
    """Return detached retained evidence; hashes do not authenticate its claims."""
    try:
        return _adapt(files,pins)
    except RetainedAuditError:
        raise
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RecursionError):
        raise RetainedAuditError('CAPTURED_ORIGIN_REJECTED') from None
