"""Reuse frozen artifacts and observe later official results in the same workflow.

The forecast process and outcome process never share result inputs. This runner
is not a scheduler, does not publish raw pages or change model coefficients.
"""
from datetime import datetime,timezone,timedelta,date
import argparse,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from urllib import request,error
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
race_ai.__path__.append(str(ROOT/'pr64-reference'/'race_ai'))
from race_ai.frozen_day_cycle import read_p0,read_p1,evaluate,need,ts
from race_ai.first_receipt_continuity import first_receipt_rows,latest_result_observations
from race_ai.cycle_recovery import recover,load_state,due_rows,result_request_budget
from race_ai.observed_weight_learning import attach_snapshots
JST=timezone(timedelta(hours=9));REPO='haji84/RACE-AI'

def event_day(*,now=None):
    """Pin one real transaction's event day, never a client supplied clock."""
    now=now or datetime.now(timezone.utc)
    need(now.utcoffset() is not None,'aware event clock')
    today=now.astimezone(JST).date()
    value=os.environ.get('RACE_AI_EVENT_DAY')
    if value is None:return today.isoformat()
    pinned=date.fromisoformat(value)
    need(pinned.isoformat()==value and today-timedelta(days=1)<=pinned<=today,
         'EVENT_DAY_PIN_REJECTED')
    return value

def source_identity_conflict(reason):
    """Only definite provenance contradictions quarantine the shared source."""
    return reason in {
        'B_SOURCE_IDENTITY','foreign program source','B cutoff identity mismatch',
        'B registration mismatch','B duplicate allocation','duplicate or foreign B race',
        'OFFICIAL_RESULT_SOURCE_IDENTITY_MISMATCH','update URL race identity mismatch',
        'update body day or venue mismatch','update selected race mismatch',
        'explicit result program race identity conflict','result and program racer name conflict',
        'external official archive redirect rejected','redirect rejected','unexpected archive entry name',
    }

_ORIGINAL_READER=None

def original_reader():
    """Opt-in owner-key archive selection; never starts a source session."""
    if os.environ.get('RACE_AI_ORIGINAL_VAULT_ENABLED')!='true':return None
    global _ORIGINAL_READER
    if _ORIGINAL_READER is None:
        from scripts.boat_saved_view_feed import git_auth
        from race_ai.boat_original_recovery import ArtifactRecovery
        git_auth()
        _ORIGINAL_READER=ArtifactRecovery(_live_gh,ROOT)
    return _ORIGINAL_READER

def gh(path):
    reader=original_reader()
    return reader(path) if reader is not None else _live_gh(path)

def _archived_pages(run):
    reader=original_reader()
    return reader.archived_artifact_pages(run) if reader is not None else None

def _is_archived(ident):
    reader=original_reader()
    return reader is not None and reader.is_archived(ident)

gh.archived_artifact_pages=_archived_pages
gh.is_archived=_is_archived

def _live_gh(path):
    """Read GitHub receipt; retry *only explicit 5xx or transport timeout*.

    Never retry 4xx/429, unknown CLI failures or integrity mismatches. Raw
    CLI stderr may contain private identifiers, so expose only a status class.
    Independent callers must still verify server digest and original ZIP bytes.
    """
    command=['gh','api',f'repos/{REPO}/'+path]
    for attempt in range(3):
        try:
            result=subprocess.run(command,check=False,capture_output=True,timeout=50)
        except subprocess.TimeoutExpired:
            if attempt==2:raise RuntimeError('GITHUB_API_TIMEOUT_HALT') from None
            time.sleep(attempt+1)
            continue
        if result.returncode==0:return result.stdout
        message=result.stderr.decode('utf-8',errors='replace')
        match=re.search(r'(?i)\bHTTP[\s:]+([45][0-9]{2})\b',message)
        status=int(match.group(1)) if match else None
        if status is not None and 500<=status<=599 and attempt<2:
            time.sleep(attempt+1)
            continue
        reason=f'HTTP_{status}' if status else 'UNCLASSIFIED_CLI_ERROR'
        raise RuntimeError(f'GITHUB_API_READ_{reason}_HALT') from None
    raise RuntimeError('GITHUB_API_READ_ATTEMPTS_EXHAUSTED_HALT')

def original(day):
    index=ROOT/'docs/evidence'/day/'p0-first-receipt.json'
    if not index.is_file():raise ValueError('FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION')
    known=json.loads(index.read_text());ident=known['artifact_id']
    receipt=json.loads(gh(f'actions/artifacts/{ident}'));raw=gh(f'actions/artifacts/{ident}/zip')
    need(receipt['created_at']==known['server_created_at'] and receipt['digest']=='sha256:'+known['zip_sha256'],'original receipt changed')
    doc,rows=read_p0(raw,receipt,expected_day=day)
    need(rows[0]['original_json_sha256']==known['json_sha256'],'original body changed')
    return doc,attach_snapshots(doc,rows),receipt,raw

def _video_sources(state,requested,reader=None):
    """Lazy optional archive reads; no video source GET occurs in the default flow."""
    from race_ai.boat_video_archive import VideoContextArchiveReader
    reader=reader or VideoContextArchiveReader(gh)
    try:
        inherited=state.get('video_context_artifact_ids',[])
        need(type(inherited) is list and type(requested) in (tuple,list),
             'BOAT_VIDEO_ARCHIVE_REJECTED')
        reader.load(inherited+list(requested))
        return reader,None
    except (ValueError,KeyError,TypeError):
        return reader,'BOAT_VIDEO_ARCHIVE_REJECTED'

def restore(day,*,video_context_artifacts=(),video_reader=None):
    from race_ai.boat_private_original_archive import open_original_zip
    doc,rows,meta,raw=original(day);folder=ROOT/'boat_all_day_output';folder.mkdir(exist_ok=True)
    with open_original_zip(raw,meta,expected_kind='P0',max_plain_zip_bytes=32*1024*1024) as z:body=z.read('forecasts.json')
    target=folder/'forecasts.json'
    if target.exists():
        need(target.read_bytes()==body,'FIRST_P0_RESTORE_LOCAL_BYTES_CONFLICT')
    else:
        with target.open('xb') as f:f.write(body)
    (folder/'first-receipt.json').write_text(json.dumps(meta,ensure_ascii=False))
    reader,error=_video_sources({},video_context_artifacts,video_reader)
    state=recover(gh,day,current_run=int(os.environ['GITHUB_RUN_ID']),out=ROOT/'cycle_recovery_output',
                  video_receipt_verifier=reader.verify)
    # Reconcile the prior uncommitted round from its actual saved originals.
    # No source session or new forecast is admitted until vault readback succeeds.
    from scripts.boat_recover_failed_owner import recover_restored_pending
    state=recover_restored_pending(state,gh,ROOT)
    if state.get('pending_round_recovery_vault_commit'):
        from race_ai.repeated_cycle import write_state
        write_state(ROOT/'cycle_recovery_output/continuity.json',state,key='state_sha256')
    if reader.artifact_ids or error:
        from race_ai.repeated_cycle import write_state
        if reader.artifact_ids:
            state['video_context_artifact_ids']=sorted(set(state.get('video_context_artifact_ids',[]))|
                                                       set(reader.artifact_ids))
        if error:
            state.setdefault('video_context_rejections',[]).append({'reason':error})
        write_state(ROOT/'cycle_recovery_output/continuity.json',state,key='state_sha256')
    print(json.dumps(dict(state='ORIGINAL_REUSED_NO_REGENERATION',races=doc['race_count'],forecasts=len(rows),artifact_id=meta['id'])))

def _venue_research_preload(*,round_no,clock=None):
    """Optional private I/O finishes before fresh official P1 capture begins."""
    config=ROOT/'audit/state/boat-venue-learning-context-input.json'
    if not config.is_file():return None,None
    import tempfile,shutil
    folder=None
    try:
        need(type(round_no) is int and 1<=round_no<=1_000_000,'VENUE_RESEARCH_ROUND_REQUIRED')
        private_base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
        # Both restored plaintext and sealed forecasts stay outside Git.
        private_base=private_base.resolve()
        need(private_base!=ROOT.resolve() and ROOT.resolve() not in private_base.parents,
             'VENUE_RESEARCH_PRIVATE_ROOT_REQUIRED')
        folder=Path(tempfile.mkdtemp(prefix='boat-venue-preload-',dir=private_base))
        from race_ai.boat_venue_research_runtime import preload_venue_research
        runtime=preload_venue_research(config,ROOT/'audit/state/boat-venue-dataset-input.json',
            folder,ROOT,gh=gh,clock=clock)
        runtime['preload_folder']=folder
        runtime['output_folder']=private_base/'boat-venue-research-p1'/f'cycle-{round_no}'
        need(not runtime['output_folder'].exists(),'VENUE_RESEARCH_OUTPUT_EXISTS_NO_RESET')
        return runtime,None
    except Exception:
        if folder is not None:shutil.rmtree(folder,ignore_errors=True)
        return None,'VENUE_RESEARCH_PRELOAD_REJECTED'


def _venue_research_generate(result,runtime,error):
    """Only successful sealed candidates enter the private upload directory."""
    if runtime is None and error is None:return
    from race_ai.boat_venue_research_forecast import forecast_private_venue_p1
    from race_ai.boat_venue_feature_adapter import RIGHTS
    from scripts.boat_history_collect import private_root
    import re,shutil,tempfile
    summary=dict(generated_races=0,learned_shadow_count=0,rejected_races=0,
        independent_pre_cutoff_receipt_verified=False,production_promoted=False,
        plaintext_published=False,provider_permission_confirmed=False,actual_purchases=False)
    try:
        if error:
            summary['reason']=error
        else:
            private_root(runtime['output_folder'])
            pointer=runtime['dataset_pointer']
            url='https://raw.githubusercontent.com/haji84/RACE-AI/'+pointer['source_commit']+'/'+pointer['dataset_path']
            attempt_base=private_root(runtime['preload_folder']/'attempts')
            for bundle in result.get('observed_pairwise_p1_bundles',[]):
                attempt=None
                try:
                    source_pairs={(s['source_url'],s['source_rights_ref']) for s in bundle['snapshot']['sources']}
                    source_pairs.add((url,RIGHTS))
                    def owner_analysis(source,rights,purpose):
                        return purpose=='analysis' and (source,rights) in source_pairs
                    rid=bundle['race_id']
                    need(type(rid) is str and re.fullmatch(r'\d{8}-\d{2}-\d{2}',rid),
                         'VENUE_RESEARCH_RACE_ID_REQUIRED')
                    destination=runtime['output_folder']/rid
                    need(not destination.exists(),'VENUE_RESEARCH_ORIGINAL_EXISTS_NO_RESET')
                    attempt=attempt_base/rid
                    status=forecast_private_venue_p1(bundle,runtime['context'],runtime['dataset_folder'],
                        pointer,attempt,now=datetime.now(timezone.utc),
                        dataset_verified_at=runtime['dataset_verified_at'],allow_source=owner_analysis)
                    need(not destination.exists(),'VENUE_RESEARCH_ORIGINAL_EXISTS_NO_RESET')
                    attempt.rename(destination)
                    summary['generated_races']+=1
                    summary['learned_shadow_count']+=status['learned_shadow_count']
                except Exception:
                    summary['rejected_races']+=1
                    if attempt is not None and attempt.exists():
                        # Keep late/partial ciphertext, excluding it from the
                        # all-or-none archive of successful original forecasts.
                        base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
                        quarantine=private_root(base/'boat-venue-research-quarantine')
                        target=Path(tempfile.mkdtemp(prefix='rejected-',dir=quarantine))/'cipher'
                        attempt.rename(target)
    except Exception:
        summary['reason']='VENUE_RESEARCH_GENERATION_REJECTED'
    finally:
        if runtime is not None and runtime.get('preload_folder'):
            shutil.rmtree(runtime['preload_folder'],ignore_errors=True)
    result['venue_research_summary']=summary


def venue_research_forecast(day,round_no):
    """Run private research only AFTER the independent baseline upload step."""
    try:
        result=json.loads((ROOT/'boat_nationwide_output/national.json').read_text())
        if not result.get('observed_pairwise_p1_bundles') and not _native_pending_folder(round_no).is_dir():
            summary=dict(state='NO_PRIVATE_P1_INPUT',generated_races=0,learned_shadow_count=0,
                independent_pre_cutoff_receipt_verified=False,production_promoted=False,plaintext_published=False)
            print(json.dumps(summary,sort_keys=True));return summary
        runtime,error=_venue_research_preload(round_no=round_no)
        if runtime and runtime['context']['training'].get('schema')=='RACE_AI_ALL_EXISTING_MODEL_FIT_V1':
            summary=_all_model_research_generate(runtime,round_no)
        else:
            _venue_research_generate(result,runtime,error)
            summary=result.get('venue_research_summary',dict(state='PRIVATE_VENUE_RESEARCH_NOT_CONFIGURED'))
    except Exception:
        summary=dict(state='HOLD_PRIVATE_VENUE_FORECAST',plaintext_published=False,
                     production_promoted=False)
    print(json.dumps(summary,sort_keys=True));return summary


def _native_pending_folder(round_no):
    import tempfile
    need(type(round_no) is int and 1<=round_no<=1_000_000,'ALL_MODEL_ROUND_REQUIRED')
    return Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))/'all-existing-model-inputs'/f'cycle-{round_no}'


def _verified_round_additional_requests(round_no,*,now):
    """Continue only the current round's already-read-back private ciphertext.

    A missing readback marker is the legacy/default path. A present marker
    must bind the exact sealed bytes, current run/head/round, private view and
    append-only pointer. No Git/provider operation or external receipt refresh
    occurs here; the preceding Actions readback acquired that actual receipt.
    """
    from copy import deepcopy
    from datetime import datetime as AwareDatetime
    from race_ai.actions_contract import digest
    from race_ai import boat_all_model_cycle as engine,boat_all_model_store as store
    from race_ai.all_existing_model_inputs import _location
    from race_ai.all_existing_model_runtime import _private_file
    from race_ai import all_existing_model_registry as registry
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.permissioned_source_delivery import read_json_bytes
    from scripts import boat_all_model_cycle as cycle
    need(type(round_no) is int and 1<=round_no<=999999,'ALL_MODEL_NATIVE_ROUND_REQUIRED')
    need(type(now) is AwareDatetime and now.utcoffset() is not None,'ALL_MODEL_NATIVE_CLOCK_REQUIRED')
    marker=Path(os.environ.get('RUNNER_TEMP',''))/'boat-all-model-readback.json'
    if not marker.exists() and not marker.is_symlink():return []
    env=cycle._environment()
    need(marker==env['temp']/'boat-all-model-readback.json','ALL_MODEL_NATIVE_MARKER_PATH_INVALID')
    def read(path,limit):
        path=Path(path)
        _location(path.parent)
        _private_file(path)
        return cycle._read(path,limit,private=True)
    reference=read_json_bytes(read(marker,128*1024))
    fields={'schema','pointer','receipt','private_view_path','view_sha256','round_no','run_id'}
    need(type(reference) is dict and set(reference)==fields and reference['schema']==cycle.READBACK_SCHEMA and
         type(reference['round_no']) is int and reference['round_no']==round_no and
         reference['run_id']==env['run_id'],'ALL_MODEL_NATIVE_READBACK_IDENTITY_INVALID')
    path,manifest_path=cycle._paths(env,round_no)
    cipher=read(path,store.MAX_WIRE)
    payload=store.open_forecasts(cipher)  # Normal owner-key API; no raw key lookup/output here.
    header=store.forecast_header(cipher);cipher_sha=hashlib.sha256(cipher).hexdigest()
    need(header['run_id']==env['run_id'] and header['round_no']==round_no and
         payload.get('schema')==engine.SCHEMA and payload.get('stage')=='P1' and
         payload.get('source_code_commit')==env['head'] and str(payload.get('run_id'))==env['run_id'],
         'ALL_MODEL_NATIVE_CIPHER_IDENTITY_INVALID')
    pointer=store._validate_pointer(reference['pointer'])
    need(pointer['cipher_sha256']==cipher_sha and pointer['header']==header,
         'ALL_MODEL_NATIVE_READBACK_CIPHER_MISMATCH')
    manifest=read_json_bytes(read(manifest_path,8192))
    manifest_fields={'operation','round_no','run_id','head_sha','inputs_sha256','baseline_artifact',
                     'cipher_sha256','payload_sha256'}
    need(type(manifest) is dict and set(manifest)==manifest_fields and manifest['operation']=='generate' and
         type(manifest['round_no']) is int and manifest['round_no']==round_no and
         manifest['run_id']==env['run_id'] and manifest['head_sha']==env['head'] and
         manifest['cipher_sha256']==cipher_sha and manifest['payload_sha256']==digest(payload) and
         type(manifest['inputs_sha256']) is str and re.fullmatch('[a-f0-9]{64}',manifest['inputs_sha256']) and
         (manifest['baseline_artifact'] is None or type(manifest['baseline_artifact']) is int and
          manifest['baseline_artifact']>0),'ALL_MODEL_NATIVE_SEAL_MANIFEST_MISMATCH')
    baseline=payload.get('baseline')
    need((baseline is None and manifest['baseline_artifact'] is None) or
         type(baseline) is dict and type(baseline.get('receipt')) is dict and
         baseline['receipt'].get('artifact_id')==manifest['baseline_artifact'],
         'ALL_MODEL_NATIVE_BASELINE_BINDING_INVALID')
    receipt=engine._receipt(reference['receipt'],digest(payload),env['head'],env['run_id'])
    saved=ts(receipt['created_at']);generated=ts(payload['generated_at'])
    need(saved<=now and generated<=now and engine._not_before(payload['generated_at'],receipt['created_at']),
         'ALL_MODEL_NATIVE_READBACK_CLOCK_INVALID')
    expected_view=env['temp']/'boat-all-model-views'/f'cycle-{round_no}.json'
    need(reference['private_view_path']==str(expected_view),'ALL_MODEL_NATIVE_VIEW_PATH_INVALID')
    view_raw=read(expected_view,store.MAX_PLAIN)
    need(reference['view_sha256']==hashlib.sha256(view_raw).hexdigest(),'ALL_MODEL_NATIVE_VIEW_HASH_INVALID')
    view=read_json_bytes(view_raw)
    need(type(view) is dict and view.get('schema')=='RACE_AI_PRIVATE_CYCLE_VIEW_V1' and
         view.get('independent_receipts_verified') is True and view.get('source_requests')==0 and
         ts(view['as_of'])==ts(payload['as_of']),'ALL_MODEL_NATIVE_VIEW_BINDING_INVALID')
    # Replay uses the exact source-authorizer scope signed in each capsule.
    # Older ciphertext has no capsules and contributes no reconstructed inputs.
    capsules=engine.verify_native_input_capsules(payload)
    requests=[];known={c['cell_key']:c for c in registry.cells()};seen={}
    for capsule in capsules:
        need(capsule['stage']=='P1' and capsule['sport']=='boat','ALL_MODEL_NATIVE_STAGE_INVALID')
        for group,native in capsule['native_inputs'].items():
            for mid in capsule['group_model_ids'][group]:
                key=registry.cell_key('boat',mid)
                need(key in known and known[key]['group']==group,'ALL_MODEL_NATIVE_CELL_INVALID')
                info=registry.identity(mid,'boat',native)
                need(info['scope']=='OPERATOR_SUPPLIED_RESEARCH' and info['stage']=='P1' and
                     ts(info['as_of'])<=generated and saved+timedelta(seconds=1)<ts(info['cutoff_at']),
                     'ALL_MODEL_NATIVE_PRE_CUTOFF_INPUT_REQUIRED')
                identity=(key,_race_key(info['race_id'],'boat'));fingerprint=digest(native)
                if identity in seen:
                    need(seen[identity]==fingerprint,'ALL_MODEL_NATIVE_CONFLICTING_INPUT')
                    continue
                seen[identity]=fingerprint
                requests.append(dict(cell_key=key,native_payload=deepcopy(native)))
    return requests


def _prospective_carrier_pairs(runtime,requests,output,*,now):
    """Seal the exact newly frozen fourteen inputs without canonical enrichment."""
    from race_ai.boat_venue_future_grid import prospective_requests
    from race_ai.all_existing_model_learning import _sources
    from race_ai.all_existing_model_pairs import make_private_pairs
    selected=prospective_requests(requests,now=now)
    from scripts import boat_prospective_forward as forward
    if forward.active():forward.validate_rows(selected,now=now)
    refs=set().union(*(_sources(row['native_payload']) for row in selected))
    summary=make_private_pairs(runtime['context'],selected,output,now=now,
        allow_source=lambda ref,rights,purpose:purpose=='analysis' and (ref,rights) in refs)
    summary['prospective_grid_carrier']=True
    summary['original_pending_inputs_unchanged']=True
    return summary


def _prospective_round_requested(round_no):
    """An admitted explicit mode remains explicit even when generation held."""
    from scripts import boat_all_model_cycle as cycle
    from race_ai.boat_venue_future_grid import open_capability
    temporary=os.environ.get('RUNNER_TEMP')
    if not temporary:return False
    path=Path(temporary)/'boat-all-model-runtime'/'runtime-ready.json'
    if not path.exists() and not path.is_symlink():return False
    marker=cycle._json(cycle._read(path,128*1024,private=True),128*1024)
    if 'prospective_grid' not in marker:return False
    env=cycle._environment()
    open_capability(marker['prospective_grid'],key=cycle._owner(),run_id=env['run_id'],
        head_sha=env['head'],round_no=round_no)
    return True


def _all_model_research_generate(runtime,round_no):
    """Only verified ciphertext partitions enter the existing upload root."""
    import re,shutil,tempfile
    from race_ai.all_existing_model_runtime import generate_current_pairs
    from scripts.boat_history_collect import private_root
    staging=runtime['preload_folder']/'native-pairs'
    summary=dict(state='HOLD_PRIVATE_NATIVE_INPUTS',production_promoted=False,plaintext_published=False)
    try:
        additional=_verified_round_additional_requests(round_no,now=datetime.now(timezone.utc))
        options=dict(now=datetime.now(timezone.utc))
        prospective=_prospective_round_requested(round_no) or any('prospective_grid_evidence' in row['native_payload'] for row in additional)
        if prospective:
            summary=_prospective_carrier_pairs(runtime,additional,staging,**options)
        else:
            if additional:options['additional_requests']=additional
            summary=generate_current_pairs(runtime,_native_pending_folder(round_no),staging,**options)
        if (summary.get('pending_removed') is True or summary.get('prospective_grid_carrier') is True) and summary.get('encrypted_readback_verified') is True:
            destination=runtime['output_folder']
            private_root(destination.parent)
            need(not destination.exists(),'ALL_MODEL_ORIGINAL_EXISTS_NO_RESET')
            children=[p for p in staging.iterdir() if re.fullmatch('[a-f0-9]{64}',p.name)]
            need(len(children)==summary['partition_count'],'ALL_MODEL_PARTITION_COUNT_MISMATCH')
            need({path.name for path in staging.iterdir()}=={'summary.json'}|{path.name for path in children},
                 'ALL_MODEL_UPLOAD_LAYOUT_INVALID')
            (staging/'summary.json').unlink()
            staging.rename(destination)
            # Root aggregate status is deliberately excluded from the all-or-none
            # receipt ZIP; each opaque partition has its own codec summary.
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                    output.write('all_model_pairs=true\n')
    except Exception:
        summary=dict(state='HOLD_PRIVATE_NATIVE_INPUTS',production_promoted=False,plaintext_published=False)
    finally:
        if staging.exists() and any(staging.iterdir()):
            base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
            quarantine=private_root(base/'boat-venue-research-quarantine')
            target=Path(tempfile.mkdtemp(prefix='native-',dir=quarantine))/'cipher'
            staging.rename(target)
        shutil.rmtree(runtime['preload_folder'],ignore_errors=True)
    return summary


def venue_research_readback(artifact_id):
    """Admit only ciphertext independently saved before every race cutoff."""
    from race_ai.boat_venue_research_receipt import verify_private_p1_artifact
    from race_ai.boat_pdca_state import state_key
    try:
        state_key('production')
        need(type(artifact_id) is int and artifact_id>0,'VENUE_RESEARCH_ARTIFACT_REQUIRED')
        metadata=json.loads(gh(f'actions/artifacts/{artifact_id}'))
        raw=gh(f'actions/artifacts/{artifact_id}/zip')
        if metadata.get('name','').startswith('all-existing-model-pairs-'):
            from race_ai.all_existing_model_receipt import verify_private_pairs_artifact
            verifier=verify_private_pairs_artifact
        else:verifier=verify_private_p1_artifact
        report=verifier(raw,metadata,now=datetime.now(timezone.utc),
            expected_run_id=int(os.environ['GITHUB_RUN_ID']),expected_head_sha=os.environ['GITHUB_SHA'])
        from race_ai.boat_venue_research_receipt import validate_research_refs
        from race_ai.repeated_cycle import write_state
        path=ROOT/'cycle_recovery_output/continuity.json'
        continuity=load_state(path,event_day())
        reference=dict(artifact_id=artifact_id,run_id=metadata['workflow_run']['id'],
            head_sha=metadata['workflow_run']['head_sha'],digest=metadata['digest'])
        continuity['venue_research_artifact_refs']=validate_research_refs(
            continuity.get('venue_research_artifact_refs',[])+[reference])
        write_state(path,continuity,key='state_sha256')
    except Exception:
        report=dict(status='HOLD_PRIVATE_VENUE_P1_READBACK',
            independent_pre_cutoff_receipt_verified=False,production_promoted=False,plaintext_published=False)
    print(json.dumps(report,sort_keys=True));return report


def venue_research_pdca(day,round_no):
    """Revisit all retained private handles using already-observed official results."""
    import tempfile
    from race_ai.boat_venue_research_receipt import validate_research_refs
    from race_ai.boat_venue_research_pdca import score_private_p1_artifact
    from race_ai.boat_pdca_state import state_key
    result=dict(status='PRIVATE_VENUE_PDCA_NOT_RUN',archives_processed=0,paired_forecasts=0,rejected_archives=0,
        production_promoted=False,plaintext_published=False,actual_purchases=False)
    try:
        state_key('production')
        need(type(round_no) is int and round_no>0,'VENUE_RESEARCH_ROUND_REQUIRED')
        continuity=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
        references=validate_research_refs(continuity.get('venue_research_artifact_refs',[]))
        if references:
            observations=json.loads((ROOT/'existing_cycle_output/official-result-observations.json').read_text())
            latest,_=latest_result_observations(observations)
            private_base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
            root=private_base/'boat-venue-research-pdca'/f'cycle-{round_no}'
            from scripts.boat_history_collect import private_root
            private_root(root)
            for reference in references:
                try:
                    ident=reference['artifact_id'];meta=json.loads(gh(f'actions/artifacts/{ident}'))
                    need(meta['digest']==reference['digest'],'VENUE_RESEARCH_ORIGINAL_DIGEST_CHANGED')
                    raw=gh(f'actions/artifacts/{ident}/zip')
                    archive_base=private_root(private_base/'boat-venue-research-archives')
                    archive=private_root(archive_base/str(ident))
                    from scripts.boat_history_collect import save
                    save(archive/'archive.zip',raw)
                    save(archive/'metadata.json',json.dumps(meta,sort_keys=True).encode())
                    if meta.get('name','').startswith('all-existing-model-pairs-'):
                        from race_ai.all_existing_model_pdca import _score_verified_private_pairs,RESULT_FIELDS
                        from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
                        from race_ai.all_existing_model_intake import _results
                        from race_ai.existing_model_dispatch import _race_key
                        now=datetime.now(timezone.utc)
                        admission,records=_verified_private_pairs_artifact(raw,meta,now=now,
                            expected_run_id=reference['run_id'],expected_head_sha=reference['head_sha'])
                        forecasts=[record for record in records if 'pair' in record]
                        wanted={(record['pair']['sport'],_race_key(record['pair']['race_id'],record['pair']['sport']))
                                for record in forecasts}
                        converted,_=_results(latest,now)
                        labels=[{key:item['result'][key] for key in RESULT_FIELDS} for identity,item in converted.items()
                                if identity in wanted and item['result']['status']!='pending']
                        scored=_score_verified_private_pairs(admission,records,labels,root/str(ident),now=now)
                    else:
                        scored=score_private_p1_artifact(raw,meta,latest,root/str(ident),now=datetime.now(timezone.utc),
                            expected_run_id=reference['run_id'],expected_head_sha=reference['head_sha'])
                    result['archives_processed']+=1
                    result['paired_forecasts']+=scored['paired_forecasts']
                except Exception:result['rejected_archives']+=1
        result['status']='PRIVATE_VENUE_PDCA_CIPHERTEXT_PREPARED'
    except Exception:result['status']='HOLD_PRIVATE_VENUE_PDCA'
    print(json.dumps(result,sort_keys=True));return result


def venue_research_retain(round_no):
    """Retain exact forecast/PDCA ciphertext on the existing GitHub state ref."""
    import tempfile
    from race_ai.boat_venue_research_retention import retain_private_research
    result=dict(status='PRIVATE_VENUE_RETENTION_NOT_NEEDED',retained_candidates=0,
                production_promoted=False,plaintext_published=False)
    try:
        need(type(round_no) is int and round_no>0,'VENUE_RESEARCH_ROUND_REQUIRED')
        base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
        folders=[]
        for kind in ('boat-venue-research-p1','boat-venue-research-pdca'):
            folders.extend(p.parent for p in (base/kind/f'cycle-{round_no}').rglob('learning.json'))
        if folders:result=retain_private_research(folders,ROOT)
        archives=[p.parent for p in (base/'boat-venue-research-archives').glob('*/archive.zip')]
        if archives:
            from race_ai.boat_venue_research_retention import retain_private_source_archives
            result['source_archives']=retain_private_source_archives(archives,ROOT)
    except Exception:
        result=dict(status='HOLD_PRIVATE_VENUE_RETENTION',retained_candidates=0,
                    production_promoted=False,plaintext_published=False)
    out=ROOT/'existing_cycle_output';out.mkdir(exist_ok=True)
    # Pointers and aggregate status only; all source/prediction bytes stay encrypted.
    (out/'venue-research-retention.json').write_text(json.dumps(result,sort_keys=True))
    print(json.dumps({k:v for k,v in result.items() if k!='pointers'},sort_keys=True));return result


def _all_model_capture(round_no):
    """Read the prepared private inventory before any fresh official source."""
    if round_no is None:return None,None
    try:
        need(type(round_no) is int and 1<=round_no<=999999,'ALL_MODEL_ROUND_REQUIRED')
        base=Path(os.environ['RUNNER_TEMP']).absolute()
        need(base!=ROOT.resolve() and ROOT.resolve() not in base.parents,'ALL_MODEL_PRIVATE_ROOT_REQUIRED')
        root=base/'boat-all-model-runtime'
        def read(name,maximum):
            path=root/name
            need(not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file()
                 and not path.stat().st_mode&0o077 and not root.stat().st_mode&0o077,
                 'ALL_MODEL_PRIVATE_FILE_REQUIRED')
            need(0<path.stat().st_size<=maximum,'ALL_MODEL_PRIVATE_FILE_BOUND')
            with path.open('rb') as stream:raw=stream.read(maximum+1)
            need(0<len(raw)<=maximum,'ALL_MODEL_PRIVATE_FILE_BOUND')
            return raw
        def pairs(items):
            out={}
            for key,value in items:
                need(key not in out,'ALL_MODEL_DUPLICATE_JSON_KEY');out[key]=value
            return out
        marker=json.loads(read('runtime-ready.json',128*1024),object_pairs_hook=pairs)
        run=os.environ.get('GITHUB_RUN_ID');head=os.environ.get('GITHUB_SHA')
        import re
        need(type(run) is str and re.fullmatch(r'[1-9][0-9]*',run) and type(head) is str
             and re.fullmatch(r'[0-9a-f]{40}',head),'ALL_MODEL_RUN_HEAD_REQUIRED')
        need(type(marker) is dict and marker.get('schema')=='RACE_AI_BOAT_ALL_MODEL_RUNTIME_READY_V1'
             and marker.get('ready') is True and type(marker.get('round_no')) is int and marker.get('round_no')==round_no
             and marker.get('run_id')==run and marker.get('source_code_commit')==head
             and all(marker.get(k) is True for k in ('verified_runtime','history_identity_verified','owner_reviewed')),
             'ALL_MODEL_PREPARED_RUNTIME_REQUIRED')
        files=marker.get('runtime_files')
        need(type(files) is dict and files.get('source_code_commit')==head and files.get('run_id')==run
             and all(files.get(k) is True for k in ('verified_runtime','history_identity_verified','owner_reviewed')),
             'ALL_MODEL_RUNTIME_BINDING_REQUIRED')
        for name in ('pointer_sha256','metadata_sha256','issued_models_sha256'):
            need(type(marker.get(name)) is str and re.fullmatch(r'[0-9a-f]{64}',marker[name]),'ALL_MODEL_RUNTIME_HASH_REQUIRED')
        raw=read('issued-models.json',4*1024*1024)
        need(hashlib.sha256(raw).hexdigest()==marker['issued_models_sha256'],'ALL_MODEL_ISSUED_MATRIX_CHANGED')
        issued=json.loads(raw,object_pairs_hook=pairs)
        from scripts.boat_nationwide_ab_pilot import validated_issued_models
        validated_issued_models(issued)
        from race_ai.boat_all_model_cycle import retain_current_input
        folder=base/'boat-all-model-inputs'/f'cycle-{round_no}'
        def sink(program,beforeinfo,as_of):
            return retain_current_input(program,beforeinfo,as_of,folder)
        return dict(issued_models=issued,input_sink=sink),None
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):
        return None,'ALL_MODEL_RUNTIME_UNAVAILABLE_OR_REJECTED'


def forecast(day,*,video_context_artifacts=(),video_reader=None,round_no=None,prospective_grid_input=None):
    from scripts import boat_prospective_forward as forward
    research_request=forward.request(round_no)
    capability=None
    if prospective_grid_input is not None:
        from scripts.boat_all_model_cycle import require_prospective_prepared
        capability=require_prospective_prepared(round_no,prospective_grid_input)
    if research_request is not None:
        need(capability is not None and prospective_grid_input==research_request['grid_input_path'],
             'EXPLICIT_FORWARD_GRID_REQUIRED')
    from scripts import boat_nationwide_ab_pilot as pilot
    state=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    index=json.loads(pilot.FROZEN_INDEX.read_text())
    first={}
    for row in sorted(index['entries']+state['index_entries'],key=lambda x:(ts(x['server_created_at']),x['artifact_id'])):
        first.setdefault(row['race_id'],row)
    index['entries']=list(first.values())
    target=ROOT/'cycle_recovery_output/freeze-index.json'
    target.write_text(json.dumps(index,ensure_ascii=False))
    # Point the unchanged predictor at the verified union, not yesterday alone.
    pilot.FROZEN_INDEX=target
    from race_ai.repeated_cycle import SourceGuard
    session=ROOT/'cycle_recovery_output/repeat-session.json'
    if session.exists():pilot.SOURCE_GUARD=SourceGuard(session)
    pilot.OBSERVED_HISTORY_CONTEXT=state.get('history_context')
    pilot.ENTRY_OBSERVATION_HISTORY=state.get('entry_observation_history')
    # Optional archive I/O precedes fresh official model snapshots. It must not
    # consume the remaining physical-save window of already generated P1 rows.
    reader,video_error=_video_sources(state,video_context_artifacts,video_reader)
    model_capture,capture_error=_all_model_capture(round_no)
    prospective_retained=[];prospective_rejected=[]
    if capability is not None:
        need(model_capture is not None,'PROSPECTIVE_GRID_NATIVE_CAPTURE_REQUIRED')
        from race_ai.boat_venue_future_grid import require_before_source
        original_sink=model_capture['input_sink']
        def prospective_sink(program,beforeinfo,as_of):
            try:
                require_before_source(capability,as_of)
                result=original_sink(program,beforeinfo,as_of)
                prospective_retained.append(True)
                return result
            except Exception:
                prospective_rejected.append(True)
                raise
        model_capture['input_sink']=prospective_sink
    prior_sink,prior_issued=pilot.MODEL_INPUT_SINK,pilot.ISSUED_MODELS
    pilot.MODEL_INPUT_SINK=model_capture['input_sink'] if model_capture is not None else None
    pilot.ISSUED_MODELS=model_capture['issued_models'] if model_capture is not None else None
    native_events=[];previous_sink=pilot.NATIVE_INPUT_SINK
    capture=(round_no is not None and (ROOT/'audit/state/all-existing-model-owner-research.json').is_file())
    if capture:pilot.NATIVE_INPUT_SINK=native_events.append
    try:
        options={} if research_request is None else dict(research_target=research_request['target'])
        result=pilot.run(schedule_snapshot=state.get('schedule_cache'),**options)
    finally:
        pilot.MODEL_INPUT_SINK,pilot.ISSUED_MODELS=prior_sink,prior_issued
        pilot.NATIVE_INPUT_SINK=previous_sink
    if capability is not None:
        # The legacy pilot records retention errors without throwing. An
        # explicitly selected experiment must not become a default fallback.
        need(prospective_retained and not prospective_rejected,'PROSPECTIVE_GRID_FRESH_CAPTURE_REQUIRED')
    if round_no is not None:
        result['all_model_collection']=dict(state='PREPARED_RUNTIME_ADMITTED' if model_capture is not None else
            'ADDITIONAL_FAMILIES_UNAVAILABLE',**({'reason':capture_error} if capture_error else {}))
    from race_ai.observed_weight_learning import make_shadows
    result['learned_pairwise_shadows']=[];result['learning_failures']=[]
    if video_error:
        result['learning_failures'].append({'reason':video_error})
    context=state.get('learning_context')
    for bundle in result.get('observed_pairwise_p1_bundles',[]):
        if context is None or 'suite' not in bundle:continue
        try:
            need(ts(bundle['snapshot']['sales_cutoff_at'])-datetime.now(timezone.utc)>timedelta(seconds=210),
                 'learned inference too near cutoff')
            if context['training']['schema']=='RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1':
                need(video_error is None,video_error)
                envelope=reader.select(bundle['snapshot'])
                need(envelope is not None,'AUTHENTICATED_VIDEO_CONTEXT_UNAVAILABLE')
                result['learned_pairwise_shadows']+=make_shadows(bundle['snapshot'],bundle['suite'],context,
                    video_context=envelope,video_receipt_verifier=reader.verify)
            else:
                result['learned_pairwise_shadows']+=make_shadows(bundle['snapshot'],bundle['suite'],context)
        except (ValueError,KeyError,TypeError) as exc:
            result['learning_failures'].append({'race_id':bundle['race_id'],'reason':str(exc)[:180]})
    if reader.artifact_ids:
        result['video_context_artifact_ids']=reader.artifact_ids
    (pilot.OUTPUT/'national.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    # This optional private handoff follows the exact baseline write. Failure
    # cannot alter that original or cause additional official source requests.
    if capture and native_events:
        try:
            from race_ai.all_existing_model_inputs import current_requests,write_private_pending_requests
            write_private_pending_requests(current_requests(native_events),_native_pending_folder(round_no))
        except Exception:pass


def supplement(day,round_no=None):
    """Fill only previously absent future P0 rows; never edit first morning bytes."""
    need(round_no is None or type(round_no) is int and round_no>=1,'invalid supplement round')
    folder=ROOT/'p0_supplement_output'
    if round_no is not None:folder=folder/f'cycle-{round_no}'
    need(not (folder/'forecasts.json').exists(),'P0_SUPPLEMENT_ALREADY_EXISTS_NO_REGENERATION')
    _,rows,_,_=original(day)
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    from scripts.existing_day_program import collect
    frozen={(x['race_id'],x['model_id']) for x in rows+recovered['rows'] if x['stage']=='P0'}
    from race_ai.repeated_cycle import SourceGuard,load as load_session
    from race_ai.source_retry_policy import SourceWait
    guard=SourceGuard(ROOT/'cycle_recovery_output/repeat-session.json')
    def finish(ready,state,**details):
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('supplement_ready='+('true' if ready else 'false')+'\n')
                output.write('supplement_state='+state+'\n')
        record=dict(state=state,supplement_ready=ready,**details)
        print(json.dumps(record));return record
    def actual_day_clock():
        now=datetime.now(timezone.utc)
        if now.astimezone(JST).date().isoformat()!=day:raise SourceWait('DAY_HANDOFF')
        handoff=os.environ.get('RACE_AI_WORKER_HANDOFF_AT')
        if handoff and now>=ts(handoff):raise SourceWait('WORKER_HANDOFF')
        return now
    try:
        result=collect(already_frozen_models=frozen,clock=actual_day_clock,source_guard=guard)
    except (SourceWait,ValueError) as exc:
        if not isinstance(exc,SourceWait) and str(exc) not in ('DAY_HANDOFF','WORKER_HANDOFF'):raise
        return finish(False,str(exc) if str(exc) in ('DAY_HANDOFF','WORKER_HANDOFF') else 'SOURCE_WAIT',
                      source_wait=load_session(guard.path).get('source_wait'))
    status=result.get('http_status')
    if isinstance(status,int) and status>=400:
        guard.http_failure(status,result.get('source_response_headers',{}),
                           not_yet_published=status==404)
    elif 'failure_class' in result and (result.get('source_error_kind')=='TRANSPORT' or
                                       result['failure_class'] in ('TimeoutError','URLError','OSError')):
        guard.http_failure(None)
    elif 'failure_class' in result and source_identity_conflict(result.get('reason')):
        guard.verification_failure()
    elif 'failure_class' not in result:
        guard.http_success()
    if 'failure_class' in result:
        waiting=load_session(guard.path).get('source_wait')
        return finish(False,result.get('source_control_reason','SOURCE_WAIT' if waiting else 'SOURCE_DATA_PENDING'),
                      source_wait=waiting)
    if not result['predictions']:
        return finish(False,'NO_MISSING_FUTURE_P0',race_count=0)
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'forecasts.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return finish(True,'MISSING_FUTURE_P0_ONLY',race_count=result['race_count'],
                  original_model_slots_not_regenerated=len(frozen))

def observe_due_results(due,observations,day,guard=None):
    """Keep unsupported formats pending while other qualified races proceed."""
    from race_ai.official_race_updates import endpoint,parse_update,MAX_BYTES
    from race_ai.tokuyama_day_worker import NoRedirects
    observations=list(observations);failures=[];requests_used=0
    from race_ai.source_retry_policy import SourceWait
    blocked=False
    for row in due:
        if blocked:break
        rid=row['race_id'];d=date.fromisoformat(day);venue=rid[9:11];n=int(rid[-2:]);url=endpoint(d,venue,n,'raceresult')
        try:
            req=request.Request(url,headers={'User-Agent':'RACE-AI-owner-existing-result-audit/1.0','Accept':'text/html'})
            if guard is not None:guard.charge('result')
            requests_used+=1
            with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
                raw=response.read(MAX_BYTES+1)
                need(response.status==200,'official response status rejected')
                need(response.geturl()==url,'OFFICIAL_RESULT_SOURCE_IDENTITY_MISMATCH')
                need(0<len(raw)<=MAX_BYTES,'official response body rejected')
            at=datetime.now(timezone.utc).isoformat()
            if os.environ.get('RACE_AI_SAVED_VIEW_CAPTURE')=='true':
                try:
                    from race_ai.saved_view_feed import retain_capture
                    retain_capture(Path(os.environ['RUNNER_TEMP'])/'boat-saved-view-captures',raw,
                        dict(source_url=url,captured_at=at,source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200))
                except Exception:
                    failures.append(dict(race_id=rid,state='DISPLAY_SOURCE_CACHE_UNAVAILABLE',reason='PRIVATE_DISPLAY_CAPTURE_FAILED'))
            observation=parse_update(raw,kind='raceresult',day=d,venue=venue,race_no=n,source_url=url,captured_at=at,entries=None)
            observation.update(source_url=url,source_sha256=hashlib.sha256(raw).hexdigest())
            if guard is not None:guard.http_success()
            observations.append(observation);time.sleep(.35)
        except Exception as exc:
            if isinstance(exc,SourceWait):
                blocked=True
                failures.append(dict(race_id=rid,state='SOURCE_WAIT',reason=exc.reason,
                                     retry_at=exc.retry_at))
                continue
            if str(exc) in ('DAY_HANDOFF','WORKER_HANDOFF'):
                blocked=True
                failures.append(dict(race_id=rid,state=str(exc),reason=str(exc)))
                continue
            if isinstance(exc,error.HTTPError):
                blocked=True
                if guard is not None:
                    guard.http_failure(exc.code,exc.headers,not_yet_published=exc.code==404)
            elif isinstance(exc,(error.URLError,TimeoutError,OSError)):
                blocked=True
                if guard is not None:guard.http_failure(None)
            elif source_identity_conflict(str(exc)):
                blocked=True
                if guard is not None:guard.verification_failure()
            failures.append(dict(race_id=rid,state='SOURCE_OR_PARSE_UNAVAILABLE',reason=type(exc).__name__+': '+str(exc)[:120]))
    return observations,failures,requests_used

def audit(day,p1_id,p0_supplement=None,round_no=None,*,video_context_artifacts=(),video_reader=None):
    doc,rows,p0_meta,p0_zip=original(day);sources=[p0_meta];p1_doc=None;p1_meta=None
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    reader,video_error=_video_sources(recovered,video_context_artifacts,video_reader)
    rows+=recovered['rows'];sources+=recovered['receipts']
    out=ROOT/'existing_cycle_output';out.mkdir(exist_ok=True)
    (out/'first-p0-original.zip').write_bytes(p0_zip)
    if p0_supplement and p0_supplement != p0_meta['id']:
        meta=json.loads(gh(f'actions/artifacts/{p0_supplement}'));raw=gh(f'actions/artifacts/{p0_supplement}/zip')
        supplement_doc,additional=read_p0(raw,meta,expected_day=day);rows+=attach_snapshots(supplement_doc,additional);sources.append(meta)
        (out/'supplement-p0-original.zip').write_bytes(raw)
    if p1_id:
        meta=json.loads(gh(f'actions/artifacts/{p1_id}'));raw=gh(f'actions/artifacts/{p1_id}/zip')
        p1_doc,p1rows=read_p1(raw,meta);rows+=attach_snapshots(p1_doc,p1rows);sources.append(meta);p1_meta=meta
        (out/'current-p1-original.zip').write_bytes(raw)
    rows,excluded=first_receipt_rows(rows)
    excluded=recovered['excluded_repeats']+excluded
    from race_ai.repeated_cycle import SourceGuard,load as load_session,checkpoint
    session_path=ROOT/'cycle_recovery_output/repeat-session.json'
    guard=SourceGuard(session_path) if session_path.exists() else None
    at=datetime.now(timezone.utc)
    # These P1 rows already passed read_p1/first_receipt_rows. Prioritizing their
    # due keys creates no new archive/source request and never advances a cutoff.
    priority={row['race_id'] for row in rows if row.get('stage')=='P1'}
    due=due_rows(rows,recovered['observations'],at,priority_races=priority)
    eligible_due_count=len(due)
    allowance=result_request_budget(load_session(session_path),at) if guard is not None else None
    if allowance is not None:due=due[:allowance]
    observations,failures,requests_used=observe_due_results(due,recovered['observations'],day,guard)
    latest_observations,observations=latest_result_observations(observations)
    report=evaluate([{k:v for k,v in r.items() if k not in ('learning_snapshot','learning_snapshot_sha256')} for r in rows],latest_observations)
    report.update(day_jst=day,updated_at=datetime.now(timezone.utc).isoformat(),run_id=os.environ.get('GITHUB_RUN_ID'),
        code_sha=os.environ.get('GITHUB_SHA'),first_forecast_artifacts=sources,source_request_count=requests_used,
        result_source_due_count=eligible_due_count,result_source_deferred_count=eligible_due_count-len(due),
        schedule=doc['schedule'],scheduled_boat_races=len(doc['schedule']),
        original_p0_skips=doc['skipped'],no_p0_forecast=[x for x in doc['skipped'] if x['race_id'] not in {r['race_id'] for r in rows if r['stage']=='P0'}],
        result_source_failures=failures,excluded_repeat_forecasts=excluded,
        restored_run_ids=recovered['scanned_runs'],result_observation_versions=len(observations),raw_sources_published=False,continuous_operation_proven=False,
        all_models_operational=False,other_sports_status='LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED',
        archive_retention_days=7,permanent_private_retention_proven=False)
    from race_ai.existing_model_coverage import coverage
    schedule_counts={'boat':len(doc['schedule'])}
    if day=='2026-11-04':
        schedule_counts.update(keirin=75,autorace=20,horse=59)
        report['nonboat_discovery_receipt']={'artifact_id':13283229052,'zip_sha256':'86ffb2b44fdbb2119a0401533cd9f182eca0d918ab555c48870d01ef422e0e9d','state':'154_CAPTURED_CARDS_NOT_154_FORECASTS'}
    report['model_coverage']=coverage(rows,schedule_counts,active_only=True)
    # Private originals are not copied into public GitHub. This whitelist-only
    # projection keeps their research grade separate from frozen/scored counts.
    from race_ai.external_research_registry import attach_to_report
    manifest_path=ROOT/'docs/evidence'/day/'autorace-research-import.json'
    if manifest_path.is_file():
        try:
            attach_to_report(report,json.loads(manifest_path.read_text()),day=day)
        except (ValueError,KeyError,TypeError) as exc:
            report['external_research']={'state':'IMPORT_REJECTED','reason':str(exc)[:160],
                'research_forecast_count':None,'included_in_formal_scoreboard':False}
    else:
        report['external_research']={'state':'NO_AUDITED_IMPORT_MANIFEST','research_forecast_count':None,
                                     'included_in_formal_scoreboard':False}
    (out/'external_research_summary.json').write_text(json.dumps(report['external_research'],ensure_ascii=False,indent=2))

    from race_ai.observed_weight_learning import (fit_from_verified,
        merge_shadow_rows,score_shadows,coverage_audit)
    shadow_rows=list(recovered.get('learning_shadows',[]))
    from race_ai.boat_video_archive import read_optional_video_shadows,validate_optional_video_training
    video_rejections=list(recovered.get('video_shadow_rejections',[]))
    if p1_doc is not None:
        accepted,rejected=read_optional_video_shadows(p1_doc,p1_meta,rows,receipt_verifier=reader.verify)
        shadow_rows+=accepted;video_rejections+=rejected
    shadow_rows=merge_shadow_rows(shadow_rows)
    shadow_rows,rejected=validate_optional_video_training(shadow_rows,recovered.get('training_proofs',{}))
    video_rejections+=rejected
    if video_rejections:
        report['video_shadow_rejections']=video_rejections
    if p1_doc is not None:
        from race_ai.cycle_recovery import validate_document_history
        validate_document_history(p1_doc,recovered.get('history_proofs',{}))
    recovered['learning_shadows']=shadow_rows
    report['learned_shadow_comparison']=score_shadows(shadow_rows,rows,latest_observations)
    report['coverage_audit']=coverage_audit(rows,doc['schedule'],now=datetime.now(timezone.utc),
        observations=latest_observations,learned_rows=shadow_rows)
    training_path=out/'trained_observed_models.json'
    try:
        need(video_error is None,video_error)
        if reader.artifact_ids:
            training=fit_from_verified(rows,latest_observations,now=datetime.now(timezone.utc),
                video_contexts=reader.contexts_for_rows(rows),video_receipt_verifier=reader.verify)
        else:
            training=fit_from_verified(rows,latest_observations,now=datetime.now(timezone.utc))
        prior=(recovered.get('learning_context') or {}).get('training')
        if prior is not None and {k:v for k,v in prior.items() if k not in ('created_at','training_sha256')}=={k:v for k,v in training.items() if k not in ('created_at','training_sha256')}:
            training=prior  # Do not invent a new candidate version for unchanged evidence.
        training_path.write_text(json.dumps(training,ensure_ascii=False,sort_keys=True))
        report['automatic_learning']={k:v for k,v in training.items() if k not in ('source_lineage','excluded_races')}
    except (ValueError,KeyError,TypeError) as exc:
        if training_path.exists():training_path.unlink()
        report['automatic_learning']={'state':'LEARNING_INPUT_REJECTED','reason':str(exc)[:200],
                                      'auto_promoted':False,'accuracy_improvement_proven':False}
    report['next_action']='FREEZE_TRAINED_CANDIDATES_THEN_COMPARE_FUTURE_RACES'
    if recovered.get('venue_research_artifact_refs'):
        report['venue_research_artifact_refs']=recovered['venue_research_artifact_refs']
    if reader.artifact_ids:
        report['video_context_artifact_ids']=reader.artifact_ids
    if video_error:
        report['video_context_status']=video_error
    report['updated_at']=datetime.now(timezone.utc).isoformat()
    report['round_no']=round_no
    if session_path.exists():report['bounded_repeat_session']=load_session(session_path)
    report['report_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'official-result-observations.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2))
    import csv
    with (out/'forecasts.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['race_id','phase','model','cutoff','first_saved_at','top8','artifact_id'])
        for r in rows:writer.writerow([r['race_id'],r['stage'],r['model_id'],r['cutoff_at'],r['server_saved_at'],' / '.join('-'.join(map(str,t)) for t in r['top8']),r['artifact_id']])
    lines=['# Existing-model actual execution status',f'Day: {day}; run: '+str(report['run_id']),
        f'Frozen forecast rows: {len(rows)}; races: {report["distinct_races"]}; scored: {report["scored_forecasts"]}.',
        'Research only. No wagering, model auto-promotion, retrospective forecast edits or all-model completion claim.',
        '| Phase | Model | Forecasts | Scored | Hit | ROI |','|---|---|---:|---:|---:|---:|']
    for x in report['scoreboard']:
        lines.append(f'|{x["stage"]}|{x["model_id"]}|{x["forecast_count"]}|{x["scored"]}|{x["hits"]}|{x["roi"] if x["roi"] is not None else "pending"}|')
    (out/'model_coverage.json').write_text(json.dumps(report['model_coverage'],ensure_ascii=False,indent=2))
    (out/'improvement_candidates.json').write_text(json.dumps(report['improvement_candidates'],ensure_ascii=False,indent=2))
    lines+=['',f'Repeated later predictions excluded: {len(excluded)}; recovered previous runs: {len(recovered["scanned_runs"])}.', 'Unmet: all four sports/all models, perpetual private storage, continuous per-deadline coverage.']
    research=report['external_research']
    lines+=['', '## Separately audited external research (not formal scores)',
            'Imported research forecast count: '+str(research.get('research_forecast_count')),
            'No private picks or source pages copied. Receipt-unverified research is excluded from the scoreboard.']
    text='\n'.join(lines)+'\n';(out/'STATUS.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    if round_no is not None:
        checkpoint(ROOT/'cycle_recovery_output/continuity.json',recovered,rows,observations,sources,p1_doc=p1_doc,p1_receipt=p1_meta)
    print(json.dumps({k:report[k] for k in ('day_jst','forecast_count','distinct_races','scored_forecasts','source_request_count','auto_promoted')},ensure_ascii=False))

def _restored_window_cutoffs(day,now):
    """Use the already restored first P0 bytes; never read a source or GitHub."""
    def read(path,limit):
        need(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents))
             and 0<path.stat().st_size<=limit,'SOURCE_WINDOW_RESTORED_INPUT_REQUIRED')
        with path.open('rb') as source:raw=source.read(limit+1)
        need(len(raw)<=limit,'SOURCE_WINDOW_RESTORED_INPUT_BOUND')
        return raw
    body=read(ROOT/'boat_all_day_output/forecasts.json',32*1024*1024)
    known=json.loads(read(ROOT/'docs/evidence'/day/'p0-first-receipt.json',32*1024))
    meta=json.loads(read(ROOT/'boat_all_day_output/first-receipt.json',128*1024))
    run=meta.get('workflow_run',{})
    need(known.get('schema')=='RACE_AI_P0_FIRST_RECEIPT_V1' and known.get('day_jst')==day
         and known.get('json_sha256')==hashlib.sha256(body).hexdigest()
         and type(known.get('artifact_id')) is int and known['artifact_id']>0
         and meta.get('id')==known['artifact_id'] and meta.get('expired') is False
         and meta.get('created_at')==known.get('server_created_at')
         and meta.get('digest')=='sha256:'+known.get('zip_sha256','')
         and run.get('id')==known.get('run_id') and type(run.get('id')) is int and run['id']>0
         and run.get('head_repository_id')==1416489937,'SOURCE_WINDOW_RESTORED_P0_BINDING_REJECTED')
    from race_ai.repeated_cycle import matches
    need(matches(meta.get('name'),f'boat-p0-existing-{run["id"]}') and ts(meta['created_at'])<=now,
         'SOURCE_WINDOW_RESTORED_P0_CLOCK_REJECTED')
    document=json.loads(body)
    need(document.get('schema')=='RACE_AI_EXISTING_P0_DAY_V1' and document.get('day_jst')==day
         and document.get('actual_purchases') is False,'SOURCE_WINDOW_RESTORED_P0_DAY_REJECTED')
    schedule=document.get('schedule',[]);suites=document.get('predictions',[])
    need(type(schedule) is list and len(schedule)<=24*12 and type(suites) is list and len(suites)<=24*12,
         'SOURCE_WINDOW_RESTORED_SCHEDULE_BOUND')
    from race_ai.frozen_day_cycle import official_id
    rows=[(r.get('race_id'),r.get('cutoff_at')) for r in schedule if type(r) is dict]
    need(len(rows)==len(schedule) and all(type(r) is dict for r in suites),
         'SOURCE_WINDOW_RESTORED_SCHEDULE_REJECTED')
    rows.extend((official_id(r['race_id']),r.get('sales_cutoff_at')) for r in suites)
    cutoffs={}
    for rid,value in rows:
        need(type(rid) is str and re.fullmatch(day.replace('-','')+r'-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',rid),
             'SOURCE_WINDOW_RESTORED_RACE_REJECTED')
        cutoff=ts(value)
        need(cutoff.astimezone(JST).date().isoformat()==day
             and (rid not in cutoffs or cutoffs[rid]==cutoff),'SOURCE_WINDOW_RESTORED_CUTOFF_REJECTED')
        cutoffs[rid]=cutoff
    return sorted(cutoffs.values())


def _restored_pending_result_count(day,now):
    """Work inventory only; existing SourceGuard remains the request authority."""
    path=ROOT/'cycle_recovery_output/continuity.json'
    if not path.exists() and not path.is_symlink():return 0
    need(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),
         'SOURCE_WINDOW_RESULT_STATE_PATH_REJECTED')
    restored=load_state(path,day)
    rows=restored.get('rows');observations=restored.get('observations')
    need(type(rows) is list and type(observations) is list,'SOURCE_WINDOW_RESULT_STATE_REJECTED')
    latest,_=latest_result_observations(observations)
    confirmed={o['race_id'] for o in latest if (o.get('data') or {}).get('confirmed') is True
               and (o.get('data') or {}).get('status') in ('settled','cancelled','no_contest')}
    pending=set()
    for row in rows:
        need(type(row) is dict and type(row.get('race_id')) is str and
             re.fullmatch(day.replace('-','')+r'-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',row['race_id']),
             'SOURCE_WINDOW_RESULT_RACE_REJECTED')
        cutoff=ts(row.get('cutoff_at'))
        need(cutoff.astimezone(JST).date().isoformat()==day,'SOURCE_WINDOW_RESULT_DAY_REJECTED')
        if cutoff<=now and row['race_id'] not in confirmed:pending.add(row['race_id'])
    return len(pending)


def wait_for_window(day=None,*,clock=None,sleeper=None):
    """Wait source-free for T-15, before starting the bounded source session."""
    clock=clock or (lambda:datetime.now(timezone.utc));sleeper=sleeper or time.sleep
    started=clock();need(isinstance(started,datetime) and started.utcoffset() is not None,'SOURCE_WINDOW_AWARE_CLOCK_REQUIRED')
    day=day or os.environ.get('RACE_AI_EVENT_DAY') or started.astimezone(JST).date().isoformat()
    need(date.fromisoformat(day).isoformat()==day,'SOURCE_WINDOW_EVENT_DAY_REJECTED')
    def finish(state,now,**work):
        reason='DAY_HANDOFF' if state=='NO_FUTURE_WINDOW' else state if state in ('DAY_HANDOFF','WORKER_HANDOFF') else None
        path=ROOT/'cycle_recovery_output/bootstrap-source-control.json'
        if reason is not None and (path.exists() or path.is_symlink()):
            need(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),
                 'SOURCE_WINDOW_BOOTSTRAP_CONTROL_REJECTED')
            from scripts.first_p0_bootstrap import bootstrap_control,_save_control
            control=bootstrap_control(day,int(os.environ['GITHUB_RUN_ID']))
            normal=(None,'BOUNDED_SESSION_END','MAX_ROUNDS_REACHED','SESSION_SOURCE_BUDGET_EXHAUSTED',
                    'SOURCE_BUDGET_EXHAUSTED','DAY_CHANGED','DAY_HANDOFF','WORKER_HANDOFF')
            if control.get('control_reason') in normal and control.get('control_reason')!=reason:
                control['control_reason']=reason
                _save_control(control)
        ready=state=='SOURCE_WINDOW_READY'
        result=dict(state=state,window_ready=ready,source_requests=0,source_session_started=False,
                    waited_seconds=max(0,(now-started).total_seconds()))
        result.update(work)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('window_ready='+('true' if ready else 'false')+'\n')
                output.write('handoff_reason='+('' if ready else state)+'\n')
        print(json.dumps(result,sort_keys=True),flush=True)
        return result
    if started.astimezone(JST).date().isoformat()!=day:return finish('DAY_HANDOFF',started)
    deadline=os.environ.get('RACE_AI_WORKER_HANDOFF_AT')
    need(deadline is not None,'WORKER_HANDOFF_DEADLINE_REQUIRED')
    deadline=ts(deadline)
    need(deadline<=started+timedelta(minutes=330),'WORKER_HANDOFF_DEADLINE_REJECTED')
    if started>=deadline:return finish('WORKER_HANDOFF',started)
    need(not (ROOT/'cycle_recovery_output/repeat-session.json').exists(),'SOURCE_WINDOW_SESSION_ALREADY_STARTED')
    cutoffs=_restored_window_cutoffs(day,started)
    from scripts import boat_prospective_forward as forward
    research_request=forward.request()
    if research_request is not None:
        cutoff=ts(research_request['target']['cutoff_at'])
        need(cutoff in cutoffs,'EXPLICIT_TARGET_MISSING_FROM_AUTHENTICATED_FIRST_P0')
        cutoffs=[cutoff]
    now=started
    while True:
        if now.astimezone(JST).date().isoformat()!=day:return finish('DAY_HANDOFF',now)
        if now>=deadline:return finish('WORKER_HANDOFF',now)
        remaining=[cutoff for cutoff in cutoffs if cutoff>now]
        if not remaining:
            pending=_restored_pending_result_count(day,now)
            if pending:
                return finish('SOURCE_WINDOW_READY',now,work_scope='PENDING_RESULTS',
                              pending_result_races=pending)
            return finish('NO_FUTURE_WINDOW',now)
        opening=remaining[0]-timedelta(minutes=15)
        if now>=opening:return finish('SOURCE_WINDOW_READY',now)
        seconds=min(30.,(opening-now).total_seconds(),(deadline-now).total_seconds())
        print(json.dumps(dict(state='WAITING_FIRST_EXHIBITION_WINDOW',wait_seconds=seconds,
            source_requests=0,source_session_started=False),sort_keys=True),flush=True)
        sleeper(seconds)
        current=clock()
        need(isinstance(current,datetime) and current.utcoffset() is not None and current>=now,
             'SOURCE_WINDOW_CLOCK_REGRESSION_HANDOFF')
        now=current


def repeat_start(day):
    from race_ai.repeated_cycle import start, write_state
    need(int(os.environ.get('GITHUB_RUN_ATTEMPT','1'))==1,'RETRY_REQUIRES_NEW_TRIGGER_TO_PRESERVE_RECEIPTS')
    path=ROOT/'cycle_recovery_output/repeat-session.json'
    recovered_path=ROOT/'cycle_recovery_output/continuity.json'
    recovered=load_state(recovered_path,day) if recovered_path.exists() else {}
    control=recovered.get('source_control')
    bootstrap_path=ROOT/'cycle_recovery_output/bootstrap-source-control.json'
    bootstrap=None
    if bootstrap_path.exists():
        from scripts.first_p0_bootstrap import bootstrap_control
        bootstrap=bootstrap_control(day,int(os.environ['GITHUB_RUN_ID']))
        control=dict(control or {})
        need(bootstrap['lifetime_requests_base']==control.get('lifetime_requests',0),
             'SOURCE_CONTROL_CHANGED_DURING_BOOTSTRAP')
        control['source_wait']=bootstrap.get('source_wait')
        control['previous_halted_reason']=bootstrap.get('previous_halted_reason')
        # Preserve the day-scoped cap across workers as well as the
        # immutable all-time counter read from the prior encrypted checkpoint.
        control['day_start_lifetime_requests']=bootstrap['day_start_lifetime_requests']
        control['day_jst']=day
    if datetime.now(timezone.utc).astimezone(JST).date().isoformat()!=day:
        from scripts.first_p0_bootstrap import bootstrap_control,_save_control
        bootstrap=bootstrap or bootstrap_control(day,int(os.environ['GITHUB_RUN_ID']),inherited=control)
        bootstrap['control_reason']='DAY_HANDOFF';_save_control(bootstrap)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('session_ready=false\nhandoff_reason=DAY_HANDOFF\n')
        return dict(state='DAY_HANDOFF',session_ready=False)
    now=datetime.now(timezone.utc)
    handoff=os.environ.get('RACE_AI_WORKER_HANDOFF_AT')
    need(handoff is None or now<ts(handoff)<=now+timedelta(minutes=360),'WORKER_HANDOFF_DEADLINE_REJECTED')
    state=start(path,day=day,run_id=int(os.environ['GITHUB_RUN_ID']),now=now,
                source_control=control)
    need(state.get('worker_handoff_at') in (None,handoff),'WORKER_HANDOFF_PIN_CHANGED')
    state['worker_handoff_at']=handoff
    state=write_state(path,state)
    # First-day B GET belongs to this SAME bounded source session.
    if os.environ.get('RACE_AI_FIRST_P0_CAPTURED')=='true':
        first=json.loads((ROOT/'boat_all_day_output/forecasts.json').read_text())
        count=bootstrap['requests_used'] if bootstrap is not None else 1
        need(first['day_jst']==day and first['source_requests']==1 and
             first['race_count']>0 and type(count) is int and count>=1,
             'FIRST_P0_GET_BUDGET_ACCOUNTING_REJECTED')
        if not state.get('bootstrap_requests_accounted'):
            need(state['requests_used']==0,'FIRST_P0_GET_ACCOUNTING_CONFLICT')
            state['requests_used']=count
            state['requests_by_kind']={'forecast':count}
            state['bootstrap_requests_accounted']=count
            write_state(path,state)
        else:need(state['bootstrap_requests_accounted']==count,'FIRST_P0_GET_ACCOUNTING_CONFLICT')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('session_ready=true\n')
    return dict(state='SOURCE_SESSION_READY',session_ready=True)

def repeat_prepare(day,round_no):
    from scripts import boat_prospective_forward as forward
    if forward.active():
        if forward.done():
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('active=false\nreason=EXPLICIT_RESEARCH_COMPLETE\n')
            return dict(active=False,wait_seconds=0,reason='EXPLICIT_RESEARCH_COMPLETE')
        forward.request(round_no)
    from race_ai.repeated_cycle import prepare,load,write_state
    path=ROOT/'cycle_recovery_output/repeat-session.json'
    continuity_path=ROOT/'cycle_recovery_output/continuity.json'
    continuity=load_state(continuity_path,day) if continuity_path.exists() else {}
    next_action=(continuity.get('schedule_cache') or {}).get('next_check_at')
    handoff=ts(os.environ['RACE_AI_WORKER_HANDOFF_AT']) if os.environ.get('RACE_AI_WORKER_HANDOFF_AT') else None
    def decide():
        now=datetime.now(timezone.utc)
        if handoff is not None and now>=handoff:
            # The final encrypted CONTINUITY artifact must distinguish a
            # normal worker handoff from an uncommitted round or source HOLD.
            state=load(path)
            need(state['day_jst']==day,'WORKER_HANDOFF_DAY_MISMATCH')
            need(state['prepared_round'] is None,'WORKER_HANDOFF_UNCOMMITTED_ROUND')
            if state['halted_reason'] is None:
                state['halted_reason']='WORKER_HANDOFF'
                write_state(path,state)
            return dict(active=False,wait_seconds=0,reason=state['halted_reason'])
        return prepare(path,round_no,now=now,next_action_at=next_action)
    decision=decide()
    while decision['wait_seconds']:
        time.sleep(min(decision['wait_seconds'],30))
        decision=decide()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        for k,v in decision.items():
            if k=='active':v='true' if v else 'false'
            print(f'{k}={v}',file=f)
    print(json.dumps(dict(round=round_no,**decision)))

def repeat_complete(day,round_no,p1_id,result_id):
    from race_ai.boat_private_original_archive import open_original_zip
    from race_ai.repeated_cycle import artifact_name,complete
    from race_ai.cycle_recovery import result_archive
    run_id=int(os.environ['GITHUB_RUN_ID'])
    # GitHub upload completion can precede metadata visibility. Wait before the
    # single strict remote readback; never retry or ignore an HTTP 4xx/429.
    time.sleep(5)
    meta=json.loads(gh(f'actions/artifacts/{result_id}'))
    need(meta['workflow_run']['id']==run_id and
         meta['name']==artifact_name('race-existing-cycle',run_id,round_no),'round result receipt identity')
    raw=gh(f'actions/artifacts/{result_id}/zip')
    result_archive(raw,meta,day)
    with open_original_zip(raw,meta,expected_kind='RESULT',max_plain_zip_bytes=32*1024*1024) as archive:
        report=json.loads(archive.read('status.json'))
    local=json.loads((ROOT/'existing_cycle_output/status.json').read_text())
    need(report==local and report['round_no']==round_no and str(report['run_id'])==str(run_id),'round result readback mismatch')
    from race_ai.observed_weight_learning import context_from_result_archive,training_proof
    from race_ai.repeated_cycle import write_state
    context=context_from_result_archive(raw,meta)
    from race_ai.observed_result_history import context_from_result_archive as history_from_archive,history_proof
    prior_history=history_from_archive(raw,meta,verified_at=datetime.now(timezone.utc).isoformat())
    continuity=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    continuity['history_context']=prior_history
    continuity.setdefault('history_proofs',{})[str(meta['id'])]=history_proof(prior_history)
    if context is not None:
        continuity['learning_context']=context
        continuity.setdefault('training_proofs',{})[str(meta['id'])]=training_proof(context)
    if 'video_context_artifact_ids' in report:
        handles=report['video_context_artifact_ids']
        need(type(handles) is list and all(type(ident) is int and ident>0 for ident in handles) and
             handles==sorted(set(handles)),'BOAT_VIDEO_ARCHIVE_REJECTED')
        continuity['video_context_artifact_ids']=handles
    write_state(ROOT/'cycle_recovery_output/continuity.json',continuity,key='state_sha256')
    state=complete(ROOT/'cycle_recovery_output/repeat-session.json',round_no,
                   now=datetime.now(timezone.utc),forecast_artifact=p1_id,result_artifact=result_id)
    print(json.dumps(dict(state='ROUND_SAVED_AND_READBACK_VERIFIED',round=round_no,
                         forecast_count=report['forecast_count'],scored_forecasts=report['scored_forecasts'],
                         p1_artifact=p1_id,result_artifact=result_id,session_requests=state['requests_used'])))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['restore','forecast','audit','supplement','wait-for-window','repeat-start','repeat-prepare','repeat-complete',
        'venue-research-forecast','venue-research-readback','venue-research-pdca','venue-research-retain'])
    p.add_argument('--p1-artifact',type=int);p.add_argument('--p0-supplement',type=int)
    p.add_argument('--result-artifact',type=int);p.add_argument('--round',type=int)
    p.add_argument('--prospective-grid-input',help='Explicit pre-admitted research grid; forecast only')
    p.add_argument('--video-context-artifact',type=int,action='append',default=[],
                   help='Optional independently read existing-run video-context artifact ID; repeatable')
    a=p.parse_args()
    if a.video_context_artifact and a.command not in ('restore','forecast','audit'):
        p.error('--video-context-artifact applies only to restore, forecast or audit')
    if a.prospective_grid_input is not None and a.command!='forecast':
        p.error('--prospective-grid-input applies only to forecast')
    video_options={'video_context_artifacts':a.video_context_artifact} if a.video_context_artifact else {}
    if a.command=='wait-for-window':
        wait_for_window()
        return
    day=event_day()
    if a.command=='restore':restore(day,**video_options)
    elif a.command=='forecast':forecast(day,**dict(video_options,
        **({'round_no':a.round} if a.round is not None else {}),
        **({'prospective_grid_input':a.prospective_grid_input} if a.prospective_grid_input is not None else {})))
    elif a.command=='venue-research-forecast':venue_research_forecast(day,a.round)
    elif a.command=='venue-research-readback':venue_research_readback(a.p1_artifact)
    elif a.command=='venue-research-pdca':venue_research_pdca(day,a.round)
    elif a.command=='venue-research-retain':venue_research_retain(a.round)
    elif a.command=='supplement':supplement(day,a.round)
    elif a.command=='repeat-start':repeat_start(day)
    elif a.command=='repeat-prepare':repeat_prepare(day,a.round)
    elif a.command=='repeat-complete':repeat_complete(day,a.round,a.p1_artifact,a.result_artifact)
    else:audit(day,a.p1_artifact,a.p0_supplement,a.round,**video_options)
if __name__=='__main__':main()
