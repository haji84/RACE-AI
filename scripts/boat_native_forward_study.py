"""Main-only prospective native comparison; no source, fit or promotion authority.

Private records enter only through the existing authenticated native reader.
The original server witness fixes the window. Public projections contain only
fixed states, counts and hashes; native plans and statistical detail stay local.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha256
import base64
import io
import itertools
import json
import math
import re
import stat
import zipfile

SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
SPEC_PATH = 'audit/state/boat-native-forward-study.json'
WORKFLOW = '.github/workflows/boat-owner-national-p1-matrix.yml'
WORKFLOW_NAME = 'BOAT nationally authenticated P1 matrix (no racing GET)'
REPORT_MEMBER = 'boat-national-p1-counts.json'
CELLS = tuple('boat/'+mid for mid in (
    'boat-observed-pairwise-factor-v1', 'boat-observed-pairwise-start-v1'))
POLICY = dict(minimum_matched_races=100, minimum_days=5, minimum_venue_day_blocks=10,
    bootstrap_samples=2000, bootstrap_seed=20261103,
    metrics=['HIT_AT_8', 'MULTICLASS_BRIER', 'LOG_LOSS'],
    multiplicity='ALL_CELLS_AND_ALL_METRICS_NO_BEST_CELL_SELECTION',
    denominator='ALL_REGISTERED_SCHEDULE_RACES_WITH_MISSING_PENDING_SPECIAL_COUNTS',
    analysis='FIXED_WINDOW_END_NO_EARLY_SUPPORT', production_promoted=False)
JST = timezone(timedelta(hours=9))
MAX_REPORT_BYTES = 1024*1024
MAX_RECORDS = 12000


def need(ok, reason):
    if not ok:raise ValueError('NATIVE_FORWARD_'+reason)


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()


def digest(value):return sha256(wire(value)).hexdigest()


def _hex(value, n=64):return type(value) is str and re.fullmatch('[a-f0-9]{'+str(n)+'}',value) is not None


def _id(value):return type(value) is int and 0<value<10**20


def _time(value):
    need(type(value) is str and 0<len(value)<=64,'CLOCK_INVALID')
    try:clock=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,TypeError):raise ValueError('NATIVE_FORWARD_CLOCK_INVALID') from None
    need(clock.utcoffset() is not None,'CLOCK_INVALID');return clock


def _now(value):
    need(type(value) is datetime and value.utcoffset() is not None,'AWARE_CLOCK_REQUIRED');return value


def _json(raw, limit=32768):
    need(type(raw) is bytes and 0<len(raw)<=limit,'JSON_BOUND')
    def unique(pairs):
        out={}
        for key,value in pairs:
            need(key not in out,'DUPLICATE_JSON_KEY');out[key]=value
        return out
    def bad(value):raise ValueError('NATIVE_FORWARD_NONFINITE_JSON')
    try:return json.loads(raw,object_pairs_hook=unique,parse_constant=bad)
    except (UnicodeError,json.JSONDecodeError):raise ValueError('NATIVE_FORWARD_JSON_INVALID') from None


def validate_spec(value):
    fields={'schema','nonce','source_commit','registration_parent_main_commit','legacy_protocol_blob_sha',
        'candidate_training_sha256','candidate_context_config_sha256','runtime_pointer_sha256','registry_sha256',
        'window_days','witness_retention_days','receipt_precision_seconds','stage','cells','policy'}
    need(type(value) is dict and set(value)==fields and value['schema']=='RACE_AI_NATIVE_FORWARD_STUDY_SPEC_V1', 'SPEC_SCHEMA')
    need(_hex(value['nonce']) and value['source_commit']==SOURCE and
        _hex(value['registration_parent_main_commit'],40) and
        value['legacy_protocol_blob_sha']=='073379c12648064305a8b7e03dfc172d2b448f73','SPEC_SOURCE')
    need(all(_hex(value[k]) for k in ('candidate_training_sha256','candidate_context_config_sha256',
        'runtime_pointer_sha256','registry_sha256')),'SPEC_PINS')
    need(type(value['window_days']) is int and 5<=value['window_days']<30 and
        type(value['witness_retention_days']) is int and value['witness_retention_days']==30 and
        type(value['receipt_precision_seconds']) is int and value['receipt_precision_seconds']==1 and
        value['stage']=='P1' and value['policy']==POLICY,'SPEC_POLICY')
    cells=value['cells'];need(type(cells) is dict and set(cells)==set(CELLS),'SPEC_CELLS')
    for cell in CELLS:
        need(cells[cell]==dict(model_id=cell[5:],kind='PROBABILITY',
            arm_versions=dict(baseline='0.1.0-UNTRAINED',learned=None)),'SPEC_ARM_IDENTITY')
    return deepcopy(value)


def load_spec(raw):return validate_spec(_json(raw))


def _boat_race(value):
    from race_ai.frozen_day_cycle import official_id
    if type(value) is str and re.fullmatch(r'20[0-9]{6}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',value):return value
    return official_id(value)


def candidate_bindings(spec, training):
    """The caller obtains training through the existing actual encrypted reader."""
    spec=validate_spec(spec)
    from race_ai.all_existing_model_learning import verify_training
    from race_ai.existing_model_dispatch import _race_key
    verify_training(training)
    need(training['training_sha256']==spec['candidate_training_sha256'] and
        training['scope']=='OPERATOR_SUPPLIED_RESEARCH','CANDIDATE_CHANGED')
    models={};excluded={};all_boat=set()
    for model in training['models'].values():
        if model['sport']=='boat':
            all_boat.update(_boat_race(_race_key(r,'boat')) for r in model['train_race_ids']+model['validation_race_ids'])
    for cell in CELLS:
        need(cell in training['models'],'CANDIDATE_UNRESOLVED')
        model=training['models'][cell]
        need(model['model_id']==cell[5:] and model['sport']=='boat' and _hex(model['model_sha256']), 'CANDIDATE_MODEL_CHANGED')
        version=model.get('model_version')
        need(version is None or type(version) is str and 0<len(version)<=128,'CANDIDATE_VERSION_UNKNOWN')
        models[cell]=dict(model_sha256=model['model_sha256'],model_version=version)
        excluded[cell]=sorted(set(model['train_race_ids']+model['validation_race_ids']))
    return dict(training_sha256=training['training_sha256'],models=models,
        excluded_races=excluded,excluded_boat_races=sorted(all_boat),
        model_map_sha256=digest(models),exclusion_inventory_sha256=digest(dict(per_cell=excluded,all_boat=sorted(all_boat))))


def registration_summary(raw_spec,candidate,*,main_commit,main_run_id,main_run_attempt):
    spec=load_spec(raw_spec)
    need(_hex(main_commit,40) and _id(main_run_id) and type(main_run_attempt) is int and main_run_attempt==1,
        'REGISTRATION_MAIN_IDENTITY')
    need(candidate['training_sha256']==spec['candidate_training_sha256'] and
        set(candidate['models'])==set(CELLS) and candidate['model_map_sha256']==digest(candidate['models']),
        'CANDIDATE_CHANGED')
    return dict(schema='RACE_AI_NATIVE_FORWARD_REGISTRATION_SUMMARY_V1',
        registration_status='REGISTERING_ORIGINAL_SERVER_WITNESS_REQUIRED',
        nonce=spec['nonce'],spec_sha256=sha256(raw_spec).hexdigest(),
        spec_git_blob_sha=sha1(f'blob {len(raw_spec)}\0'.encode()+raw_spec).hexdigest(),
        main_commit=main_commit,main_run_id=main_run_id,main_run_attempt=main_run_attempt,
        source_commit=spec['source_commit'],candidate_training_sha256=spec['candidate_training_sha256'],
        candidate_context_config_sha256=spec['candidate_context_config_sha256'],runtime_pointer_sha256=spec['runtime_pointer_sha256'],
        registry_sha256=spec['registry_sha256'],candidate_model_map_sha256=candidate['model_map_sha256'],
        candidate_bindings_sha256=digest(candidate),exclusion_inventory_sha256=candidate['exclusion_inventory_sha256'],
        registered_cell_count=len(CELLS),future_forecast_hashes_created=0,production_promoted=False)


def validate_registration_summary(value,raw_spec,candidate,**identity):
    need(type(value) is dict and value==registration_summary(raw_spec,candidate,**identity),'REGISTRATION_SUMMARY_CHANGED')


def _pages(get,path,key,*,maximum=1000):
    first=_json(get(path),1024*1024);total=first.get('total_count')
    need(type(total) is int and 0<=total<=maximum and type(first.get(key)) is list,'INVENTORY_BOUND')
    values=list(first[key]);need(len(values)==min(total,100),'INVENTORY_TRUNCATED')
    for page in range(2,(total+99)//100+1):
        value=_json(get(path+'&page='+str(page)),1024*1024)
        need(value.get('total_count')==total and type(value.get(key)) is list and
            len(value[key])==min(100,total-100*(page-1)),'INVENTORY_CHANGED')
        values.extend(value[key])
    need(len(values)==total and all(type(v) is dict and _id(v.get('id')) for v in values) and
        len({v['id'] for v in values})==total,'INVENTORY_DUPLICATE')
    return values


def _main_run(run,head,workflow,now):
    need(type(run) is dict and _id(run.get('id')) and run.get('head_sha')==head and
        run.get('head_branch')=='main' and run.get('event') in ('push','workflow_run') and
        type(run.get('run_attempt')) is int and run['run_attempt']==1 and
        run.get('workflow_id')==workflow and type(run['workflow_id']) is int and
        run.get('path')==WORKFLOW and run.get('name')==WORKFLOW_NAME and
        run.get('status')=='completed' and run.get('conclusion')=='success','WITNESS_RUN_IDENTITY')
    for name in ('repository','head_repository'):
        repo=run.get(name)
        need(type(repo) is dict and type(repo.get('id')) is int and repo['id']==1416489937 and
            repo.get('full_name')=='haji84/RACE-AI','WITNESS_REPOSITORY')
    need(_time(run['created_at'])<=now,'WITNESS_RUN_CLOCK')


def _report(raw):
    need(type(raw) is bytes and 0<len(raw)<=MAX_REPORT_BYTES,'REPORT_BOUND')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            need(archive.namelist()==[REPORT_MEMBER],'REPORT_ZIP_LAYOUT')
            entry=archive.getinfo(REPORT_MEMBER);mode=entry.external_attr>>16
            need(not entry.flag_bits&0x41 and entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                stat.S_IFMT(mode) in (0,stat.S_IFREG) and 0<entry.file_size<=MAX_REPORT_BYTES,'REPORT_ZIP_BOUND')
            with archive.open(entry) as stream:body=stream.read(MAX_REPORT_BYTES+1)
            need(len(body)==entry.file_size,'REPORT_ZIP_LENGTH')
            value=_json(body,MAX_REPORT_BYTES)
            need(type(value) is dict,'REPORT_SCHEMA');return value
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError):
        raise ValueError('NATIVE_FORWARD_REPORT_ZIP_INVALID') from None


def verify_registration_origin(spec,head,get):
    """Only the first main introduction may create this study's server witness."""
    spec=validate_spec(spec);need(_hex(head,40),'REGISTRATION_ORIGIN_CHANGED')
    commit=_json(get('git/commits/'+head),1024*1024)
    parent=spec['registration_parent_main_commit']
    need(commit.get('sha')==head and type(commit.get('parents')) is list and commit['parents'] and
        commit['parents'][0].get('sha')==parent,'REGISTRATION_ORIGIN_CHANGED')
    previous=_json(get('git/commits/'+parent),1024*1024)
    need(previous.get('sha')==parent and type(previous.get('tree')) is dict and
        _hex(previous['tree'].get('sha'),40),'REGISTRATION_PARENT_INVALID')
    tree_sha=previous['tree']['sha']
    tree=_json(get('git/trees/'+tree_sha+'?recursive=1'),4*1024*1024)
    need(tree.get('sha')==tree_sha and tree.get('truncated') is False and
        type(tree.get('tree')) is list and len(tree['tree'])<=16384 and
        all(type(e) is dict and type(e.get('path')) is str and 0<len(e['path'])<=1024 for e in tree['tree']),
        'REGISTRATION_PARENT_TREE_INCOMPLETE')
    need(not any(e['path']==SPEC_PATH for e in tree['tree']),'STUDY_ALREADY_INTRODUCED')


def verify_registration_witness(raw_spec,binding,*,candidate,get,now):
    """Fresh actual service bytes, fixed original identity, never a local clock."""
    spec=load_spec(raw_spec);now=_now(now)
    keys={'schema','status','nonce','spec_sha256','spec_git_blob_sha','main_commit','main_run_id','main_run_attempt',
        'workflow_id','run_created_at','report_artifact_id','report_artifact_name','report_artifact_digest',
        'report_artifact_created_at','candidate_bindings_sha256'}
    need(type(binding) is dict and set(binding)==keys and binding['schema']=='RACE_AI_NATIVE_FORWARD_STUDY_WITNESS_BINDING_V1'
        and binding['status']=='BOUND','WITNESS_UNBOUND')
    need(binding['nonce']==spec['nonce'] and binding['spec_sha256']==sha256(raw_spec).hexdigest() and
        binding['spec_git_blob_sha']==sha1(f'blob {len(raw_spec)}\0'.encode()+raw_spec).hexdigest() and
        _hex(binding['main_commit'],40) and all(_id(binding[k]) for k in ('main_run_id','report_artifact_id','workflow_id')) and
        type(binding['main_run_attempt']) is int and binding['main_run_attempt']==1 and
        binding['candidate_bindings_sha256']==digest(candidate),'WITNESS_BINDING_CHANGED')
    head=binding['main_commit'];ident=binding['main_run_id']
    run=_json(get(f'actions/runs/{ident}'),1024*1024)
    _main_run(run,head,binding['workflow_id'],now)
    need(run['id']==ident and run['created_at']==binding['run_created_at'],'WITNESS_RUN_CHANGED')
    verify_registration_origin(spec,head,get)
    content=_json(get(f'contents/{SPEC_PATH}?ref={head}'),65536)
    need(content.get('type')=='file' and content.get('path')==SPEC_PATH and content.get('encoding')=='base64' and
        content.get('sha')==binding['spec_git_blob_sha'] and type(content.get('size')) is int and
        content['size']==len(raw_spec) and type(content.get('content')) is str,'REGISTRATION_SPEC_CHANGED')
    try:original=base64.b64decode(content['content'].replace('\n',''),validate=True)
    except ValueError:raise ValueError('NATIVE_FORWARD_REGISTRATION_SPEC_CHANGED') from None
    need(original==raw_spec,'REGISTRATION_SPEC_CHANGED')
    history=_pages(get,f'actions/workflows/{binding["workflow_id"]}/runs?branch=main&head_sha={head}&per_page=100','workflow_runs')
    need(any(r['id']==ident and r.get('head_sha')==head for r in history),'WITNESS_HISTORY_MISSING')
    for row in history:
        need(row.get('head_sha')==head and row.get('head_branch')=='main' and
            row.get('workflow_id')==binding['workflow_id'],'WITNESS_HISTORY_CHANGED')
        if (_time(row['created_at']),row['id'])<(_time(run['created_at']),ident):
            need(row.get('status')=='completed' and row.get('conclusion')!='success','ORIGINAL_WITNESS_REQUIRED')
    listing=_pages(get,f'actions/runs/{ident}/artifacts?per_page=100','artifacts')
    name=f'boat-national-p1-model-coverage-{ident}'
    matches=[m for m in listing if m.get('name')==name]
    need(len(matches)==1 and matches[0]['id']==binding['report_artifact_id'] and
        binding['report_artifact_name']==name,'REPORT_ORIGINAL_REQUIRED')
    meta=_json(get(f'actions/artifacts/{binding["report_artifact_id"]}'),128*1024)
    fields=('id','name','expired','size_in_bytes','digest','created_at','expires_at','workflow_run')
    need(type(meta.get('id')) is int and meta['id']==binding['report_artifact_id'] and
        all(meta.get(k)==matches[0].get(k) for k in fields),'REPORT_METADATA_CHANGED')
    owner=meta.get('workflow_run')
    need(type(owner) is dict and type(owner.get('id')) is int and owner['id']==ident and owner.get('head_sha')==head and
        all(type(owner.get(k)) is int and owner[k]==1416489937 for k in ('repository_id','head_repository_id')),
        'REPORT_REPOSITORY')
    need(meta.get('expired') is False and type(meta.get('size_in_bytes')) is int and
        0<meta['size_in_bytes']<=MAX_REPORT_BYTES and meta.get('digest')==binding['report_artifact_digest'] and
        type(meta['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',meta['digest']) and
        meta.get('created_at')==binding['report_artifact_created_at'],'REPORT_METADATA_CHANGED')
    created=_time(meta['created_at']);expires=min(_time(meta['expires_at']),created+timedelta(days=30))
    need(_time(run['created_at'])<=created<=now<expires,'WITNESS_EXPIRED_OR_FUTURE')
    raw=get(f'actions/artifacts/{meta["id"]}/zip')
    need(type(raw) is bytes and len(raw)==meta['size_in_bytes'] and
        'sha256:'+sha256(raw).hexdigest()==meta['digest'],'REPORT_BYTES_CHANGED')
    report=_report(raw)
    validate_registration_summary(report.get('native_forward_study'),raw_spec,candidate,
        main_commit=head,main_run_id=ident,main_run_attempt=1)
    return dict(schema='RACE_AI_VERIFIED_NATIVE_FORWARD_REGISTRATION_V1',nonce=spec['nonce'],
        spec_sha256=sha256(raw_spec).hexdigest(),candidate_bindings_sha256=digest(candidate),
        main_commit=head,main_run_id=ident,report_artifact_id=meta['id'],report_artifact_digest=meta['digest'],
        run_created_at=run['created_at'],report_artifact_created_at=meta['created_at'],
        registered_after=(created+timedelta(seconds=1)).isoformat(),
        window_ends_at=(created+timedelta(seconds=1,days=spec['window_days'])).isoformat(),
        witness_expires_at=expires.isoformat())


def score_native_pair(payload,observation):
    from race_ai.all_existing_model_pdca import _score
    pair=payload['pair'];winner=observation['ordered_top3'];out={}
    for arm in ('baseline','learned'):
        plan=pair[arm+'_normalized'];ranked=plan['ranked']
        need(plan.get('kind')=='PROBABILITY' and type(ranked) is list and len(ranked)==120 and
            set(plan['roster'])==set('123456') and len(set(plan['roster'].values()))==6 and
            {tuple(r['combination']) for r in ranked}==set(itertools.permutations(range(1,7),3)) and
            all(type(r['score']) in (int,float) and math.isfinite(r['score']) and 0<=r['score']<=1 for r in ranked) and
            math.isclose(math.fsum(r['score'] for r in ranked),1.,abs_tol=1e-8) and
            ranked==sorted(ranked,key=lambda r:(-r['score'],r['combination'])) and
            plan['top']==[r['combination'] for r in ranked[:8]] and plan['ticket_count']==8,
            'FULL120_PROBABILITY_REQUIRED')
        out[arm]=dict(multiclass_brier=math.fsum((r['score']-int(r['combination']==winner))**2 for r in ranked),
            hit_at_1=int(ranked[0]['combination']==winner),hit_at_8=int(winner in plan['top']))
    native=_score(pair,observation)
    need(native['paired'] and native['state']=='SETTLED_PAIRED','MATCHED_NORMAL_REQUIRED')
    for arm in ('baseline','learned'):out[arm]['log_loss']=native[arm]['log_loss']
    return dict(out,native=native)


def evaluate_cell(rows):
    from race_ai.boat_ab_cohort import _block_bootstrap,_paired_bootstrap,_sign_test,wilson
    need(type(rows) is list and len(rows)<=MAX_RECORDS,'COHORT_BOUND')
    ids=[r['race_id'] for r in rows]
    need(len(ids)==len(set(ids)) and all(type(r) is str and re.fullmatch(r'20[0-9]{6}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',r) for r in ids),'COHORT_RACE_IDENTITY')
    n=len(rows);blocks=[r[:11] for r in ids]
    result=dict(matched_races=n,days=len({r[:8] for r in ids}),venue_day_blocks=len(set(blocks)),statistical_rule_satisfied=False)
    for arm in ('baseline','learned'):
        for row in rows:
            need(type(row[arm]['hit_at_8']) is int and row[arm]['hit_at_8'] in (0,1) and
                all(type(row[arm][k]) in (int,float) and math.isfinite(row[arm][k]) and row[arm][k]>=0
                    for k in ('multiclass_brier','log_loss')),'COHORT_SCORE_INVALID')
        result[arm]=dict(hits_at_8=sum(r[arm]['hit_at_8'] for r in rows),
            hit_at_8_wilson95=wilson(sum(r[arm]['hit_at_8'] for r in rows),n),
            mean_multiclass_brier=math.fsum(r[arm]['multiclass_brier'] for r in rows)/n if n else None,
            mean_log_loss=math.fsum(r[arm]['log_loss'] for r in rows)/n if n else None)
    for label,key in (('hit_at_8','hit_at_8'),('brier','multiclass_brier'),('log_loss','log_loss')):
        values=[r['learned'][key]-r['baseline'][key] for r in rows]
        result['delta_'+label+'_mean']=math.fsum(values)/n if n else None
        result['delta_'+label+'_paired95']=_paired_bootstrap(values)
        result['delta_'+label+'_block95']=_block_bootstrap(values,blocks)
    baseline_only=sum(r['baseline']['hit_at_8']>r['learned']['hit_at_8'] for r in rows)
    learned_only=sum(r['learned']['hit_at_8']>r['baseline']['hit_at_8'] for r in rows)
    result.update(baseline_only_hits=baseline_only,learned_only_hits=learned_only,
        discordance_exact_p=_sign_test(learned_only,baseline_only))
    if n>=100 and result['days']>=5 and result['venue_day_blocks']>=10:
        result['statistical_rule_satisfied']=(result['delta_hit_at_8_block95'][0]>0 and
            result['delta_brier_block95'][1]<0 and result['delta_log_loss_block95'][1]<0 and learned_only>baseline_only)
    return result


def analyze_native_cohort(spec,receipt,candidate,packets,*,now):
    """Authenticated private packets only; journal results remain unqualified."""
    from race_ai.all_existing_model_pairs import verify_private_record
    from race_ai.all_existing_model_receipt import _payload_clock
    from race_ai.all_existing_model_intake import _legacy_boat,_ordinary_result
    from race_ai.first_receipt_continuity import latest_result_observations
    from race_ai.existing_model_dispatch import _race_key
    spec=validate_spec(spec);now=_now(now)
    need(receipt.get('schema')=='RACE_AI_VERIFIED_NATIVE_FORWARD_REGISTRATION_V1' and
        receipt.get('nonce')==spec['nonce'] and receipt.get('candidate_bindings_sha256')==digest(candidate) and
        now<_time(receipt['witness_expires_at']),'REGISTRATION_PROOF_REQUIRED')
    lower=_time(receipt['registered_after']);upper=_time(receipt['window_ends_at'])
    need(lower<upper<=lower+timedelta(days=spec['window_days']) and lower<=now,'STUDY_WINDOW_CHANGED')
    need(type(packets) is list and len(packets)<=32,'HISTORY_BOUND')
    first={};counts=Counter();observations=[];schedule={};inventory=[]
    for packet in packets:
        run=packet['run'];need(run['head_sha']==spec['source_commit'],'SOURCE_CHANGED')
        records=packet['records'];need(type(records) is list and len(records)<=MAX_RECORDS,'RECORD_BOUND')
        need(type(packet['latest']) is dict and len(packet['latest'])<=MAX_RECORDS and
            type(packet.get('schedule',[])) is list and len(packet.get('schedule',[]))<=MAX_RECORDS,'SCHEDULE_BOUND')
        observations.extend(packet['latest'].values())
        need(len(observations)<=MAX_RECORDS*4,'COHORT_BOUND')
        for row in packet.get('schedule',[]):
            need(type(row) is dict and set(row)=={'race_id','cutoff_at','roster'} and
                _boat_race(row['race_id'])==row['race_id'] and type(row['roster']) is dict,'SCHEDULE_INVALID')
            rid=row['race_id'];need(rid not in schedule or schedule[rid]==row,'SCHEDULE_CONFLICT')
            schedule[rid]=row
            need(len(schedule)<=MAX_RECORDS,'SCHEDULE_BOUND')
        for item in sorted(records,key=lambda x:(_time(x['metadata']['created_at']),x['metadata']['id'])):
            payload=item['payload'];meta=item['metadata'];pair=payload.get('pair')
            need(meta.get('expired') is False and _time(meta['created_at'])<=now<_time(meta['expires_at']),
                'NATIVE_RECEIPT_EXPIRED_OR_FUTURE')
            verify_private_record(payload)
            _payload_clock(payload,_time(meta['created_at']),now)
            need(meta['workflow_run']['id']==run['id'] and meta['workflow_run']['head_sha']==spec['source_commit'],
                'FORECAST_RECEIPT_SOURCE')
            if pair is None:
                generated=_time(payload['generated_at'])
                if generated<=lower:category='pre_registration_input_only_record_count'
                elif generated>=upper:category='outside_window_input_only_record_count'
                else:
                    need(candidate_bindings(spec,payload['training'])==candidate,'CANDIDATE_CHANGED')
                    category='no_forecast_record_count'
                counts[category]+=1;inventory.append((category,digest(payload)));continue
            if pair['cell_key'] not in CELLS:counts['unregistered_cell_record_count']+=1;continue
            if pair['stage']!='P1':counts['other_stage_record_count']+=1;continue
            if _time(pair['input_as_of'])<=lower or _time(payload['generated_at'])<=lower:
                counts['pre_registration_record_count']+=1;continue
            if (_time(pair['input_as_of'])>=upper or _time(payload['generated_at'])>=upper or
                    _time(pair['race_cutoff_at'])>upper):
                counts['outside_window_record_count']+=1;continue
            need(candidate_bindings(spec,payload['training'])==candidate and
                pair['model_sha256']==candidate['models'][pair['cell_key']]['model_sha256'],'CANDIDATE_CHANGED')
            for arm in ('baseline','learned'):
                need(pair[arm].get('model_version')==spec['cells'][pair['cell_key']]['arm_versions'][arm],
                    'ARM_VERSION_CHANGED')
            need(_time(meta['created_at'])+timedelta(seconds=1)<_time(pair['race_cutoff_at']) and
                pair['input_sha256']==payload['source_sha256']==digest(payload['native_payload']), 'FUTURE_INPUT_BINDING')
            race=_boat_race(_race_key(pair['race_id'],'boat'))
            if race in candidate['excluded_boat_races']:counts['training_exclusion_record_count']+=1;continue
            key=(pair['cell_key'],race)
            descriptor=dict(payload=payload,metadata=meta,source_key=(_time(meta['created_at']),meta['id']),
                identity=dict(record_sha256=digest(payload),input_sha256=pair['input_sha256'],pair_sha256=pair['pair_sha256'],
                    arms={arm:dict(content_sha256=digest(pair[arm]),prediction_sha256=pair[arm].get('prediction_sha256'),
                        model_sha256=pair[arm].get('model_sha256'),model_version=pair[arm].get('model_version')) for arm in ('baseline','learned')}))
            if key in first:
                counts['repeat_record_count']+=1
                old=first[key]
                need(pair['baseline_normalized']['roster']==old['payload']['pair']['baseline_normalized']['roster'] and
                    pair['race_cutoff_at']==old['payload']['pair']['race_cutoff_at'],'FIRST_ORIGINAL_IDENTITY_CHANGED')
                if descriptor['source_key']==old['source_key']:
                    need(descriptor['identity']==old['identity'],'FIRST_ORIGINAL_CONFLICT')
                elif descriptor['source_key']<old['source_key']:first[key]=descriptor
            else:first[key]=descriptor
    need(len(first)<=MAX_RECORDS and len(observations)<=MAX_RECORDS*4,'COHORT_BOUND')
    combined,_=latest_result_observations(observations);latest={r['race_id']:r for r in combined}
    eligible={race:row for race,row in schedule.items() if lower<_time(row['cutoff_at'])<=upper and
        race not in candidate['excluded_boat_races']}
    ledger_states=Counter();normal=set()
    for race,row in sorted(eligible.items()):
        observation=latest.get(race)
        if observation is None:ledger_states['missing_result']+=1;continue
        unused,reason=_ordinary_result(_legacy_boat(observation),dict(race_id=race,
            race_cutoff_at=row['cutoff_at'],roster=row['roster']),now)
        ledger_states[reason or 'settled']+=1
        if reason is None:normal.add(race)
    cells={cell:[] for cell in CELLS};states={cell:Counter() for cell in CELLS}
    for (cell,race),item in sorted(first.items()):
        payload=item['payload'];pair=payload['pair'];observation=latest.get(race)
        if schedule:
            need(race in eligible and eligible[race]['cutoff_at']==pair['race_cutoff_at'] and
                eligible[race]['roster']==pair['baseline_normalized']['roster'],'REGISTERED_SCHEDULE_CHANGED')
        if observation is None:states[cell]['missing_result']+=1;continue
        info=dict(race_id=race,race_cutoff_at=pair['race_cutoff_at'],roster=pair['baseline_normalized']['roster'])
        native,reason=_ordinary_result(_legacy_boat(observation),info,now)
        if reason:states[cell][reason]+=1;continue
        score=score_native_pair(payload,{k:native[k] for k in ('race_id','sport','status','ordered_top3','roster',
            'captured_at','source_sha256','identity_verified','payout_per_100_yen','refund_numbers')})
        cells[cell].append(dict(race_id=race,baseline=score['baseline'],learned=score['learned']))
    private={cell:evaluate_cell(rows) for cell,rows in cells.items()}
    window_closed=now>=upper
    if not window_closed:
        for result in private.values():result['statistical_rule_satisfied']=None
    public=dict(schema='RACE_AI_NATIVE_FORWARD_STUDY_COUNTS_V1',registration_status='VERIFIED_ORIGINAL_SERVER_WITNESS',
        nonce=spec['nonce'],spec_sha256=receipt['spec_sha256'],candidate_bindings_sha256=digest(candidate),
        registration_main_run_id=receipt['main_run_id'],registration_report_artifact_id=receipt['report_artifact_id'],
        matched_races_by_cell={cell:len(rows) for cell,rows in cells.items()},
        days_by_cell={cell:private[cell]['days'] for cell in CELLS},
        venue_day_blocks_by_cell={cell:private[cell]['venue_day_blocks'] for cell in CELLS},
        result_state_counts={cell:dict(states[cell]) for cell in CELLS},
        registered_schedule_race_count=len(eligible) if schedule else None,
        all_registered_normal_race_count=len(normal) if schedule else None,
        schedule_result_state_counts=dict(ledger_states),registered_schedule_sha256=digest(sorted(eligible.items())),
        missing_forecast_races_by_cell={cell:len(normal-{race for selected_cell,race in first if selected_cell==cell}) if schedule else None for cell in CELLS},
        all_registered_hit_counts_by_cell={cell:{arm:sum(r[arm]['hit_at_8'] for r in rows) if schedule else None for arm in ('baseline','learned')}
            for cell,rows in cells.items()},
        **{key:counts[key] for key in ('repeat_record_count','pre_registration_record_count','outside_window_record_count',
            'no_forecast_record_count','pre_registration_input_only_record_count','outside_window_input_only_record_count',
            'unregistered_cell_record_count','other_stage_record_count','training_exclusion_record_count')},
        first_originals_sha256=digest([(list(k),v['identity'],v['metadata']['id']) for k,v in sorted(first.items())]),
        no_forecast_inventory_sha256=digest(inventory),result_revisions_sha256=digest(sorted(digest(r) for r in combined)),
        statistical_detail_sha256=digest(private),research_statistical_rule_satisfied_cell_count=(
            sum(v['statistical_rule_satisfied'] for v in private.values()) if window_closed else None),
        evaluation_status='WINDOW_OPEN_HOLD' if now<upper else 'JOURNAL_COMPARISON_ONLY_OFFICIAL_LEDGER_HOLD',
        result_scope='AUTHENTICATED_P0_SCHEDULE_PRODUCER_JOURNAL_ONLY_UNQUALIFIED',
        complete_official_ledger_verified=False,official_raw_qualified=False,
        qualifying_g8_count=0,promotion_allowed=False,new_forecasts=0,source_requests=0)
    return dict(public=public,private=dict(cells=private,first_originals={str(k):v['identity'] for k,v in first.items()}))
