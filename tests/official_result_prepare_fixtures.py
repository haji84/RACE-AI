"""Entirely authored preparation evidence through the real fixture AES/MAC codecs.

No source transport, owner key or persistent state is used. Additional race
identities below are invented before sealing their native inputs.
"""
import base64
import json
from copy import deepcopy
from datetime import datetime,timedelta
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import tempfile

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
from race_ai import all_existing_model_official_continuation as C
from race_ai import all_existing_model_official_probe16 as S
from race_ai import all_existing_model_official_recovery as R
from race_ai import all_existing_model_official_historical as H
from race_ai import all_existing_model_official_results as official
from scripts import all_existing_model_official_result_collect as collector
from tests import test_all_existing_model_official_continuation as seed
from tests import test_all_existing_model_official_probe16_continuation as sixteen
from tests import test_all_existing_model_order_only_pdca as pairs
from tests.test_all_existing_model_official_recovery import KEY
from tests.test_official_result_issue import actual_run


def _plan(raw_plan,run=500):
    raw=seal_forecasts(raw_plan,run_id=str(run),round_no=900033,key=KEY)
    checksum=sha256(raw).hexdigest()
    return raw,dict(plan_path='audit/state/official-result-collection-plan-'+checksum+'.enc',plan_sha256=checksum)


def _journal(body,ident,run,head,saved):
    raw=seed.zipped(seal_forecasts(body,run_id=str(run),round_no=900006,key=KEY),'collection.enc')
    return dict(raw=raw,metadata=seed.metadata(raw,ident,'official-result-collection-journal-'+str(run),run,head,saved))


def _result(journal,natives,ident,run,head,end,event_day):
    case=next(c for c in journal['cases'] if c['state']=='rank_confirmed')
    native=next(n for n in natives if n['snapshot']['race']['race_id']==case['race_id'])
    label=collector._parse(journal['captures'][0],native,case['sport'],now=end,allow_order_only=True)
    payload=official.build_result_payload(journal['captures'],[label],run_id=run,code_sha=head,
        generated_at=end,day_jst=event_day,frozen_native_payloads=natives,allow_order_only=True)
    raw=seed.zipped(seal_forecasts(payload,run_id=str(run),round_no=collector.ROUND,key=KEY),'results.enc')
    return dict(raw=raw,metadata=seed.metadata(raw,ident,'all-existing-official-results-'+str(run)+'-'+str(collector.ROUND),run,head,end+timedelta(seconds=2)))


@lru_cache(maxsize=1)
def _single_fixture():
    data,_,issued=sixteen.authored_continuation(historical=True)
    data=deepcopy(data);issued=deepcopy(issued)
    old_item=deepcopy(data['journal_archives'][0]);old_body=open_forecasts(collector._journal_cipher(old_item['raw']),key=KEY)
    old_plan=deepcopy(data['old_plan']);auto_case=deepcopy(old_plan['cases'][0])
    requests=[];auto_cases=[];kei_cases=[]
    for sport in ('autorace','keirin'):
        template=deepcopy(pairs.templates()[sport][2]);original=template['snapshot']['race']['race_id']
        first=int(original.rsplit(':',1)[1])
        for number in range(first,first+8):
            native=deepcopy(template);rid=original.rsplit(':',1)[0]+':'+str(number)
            native['snapshot']['race']['race_id']=rid
            native['adapter_lineage']['race_id']=rid
            # Two fitted template forecasts plus fourteen genuine codec-retained
            # input-only cells keep this intake fixture small; all sixteen
            # native originals still undergo the normal artifact admission.
            model=pairs.ALL_MODELS[0] if number==first else pairs.ALL_MODELS[1]
            requests.append(dict(cell_key=sport+'/'+model,native_payload=native))
            route=deepcopy(auto_case['route']) if sport=='autorace' else dict(kind='NORMAL_UI',ui_entry_url='https://keirin.jp/pc/top',ui_venue_name='四日市')
            case=dict(sport=sport,race_id=rid,route=route)
            (auto_cases if sport=='autorace' else kei_cases).append(case)
    pairs.OrderOnlyPrivatePDCATests.setUpClass()
    inputs=pairs.OrderOnlyPrivatePDCATests(methodName='runTest');inputs.setUp()
    try:
        native_raw,native_meta=inputs.native_archive(requests,'sixteen-invented-originals',800,1)
    finally:inputs.doCleanups()
    native_archives=[]
    for number in range(4):
        meta=deepcopy(native_meta);meta['id']=800+number
        native_archives.append(dict(raw=native_raw,metadata=meta))
    native_pins=[seed.pin(x['metadata']) for x in native_archives]
    natives=[r['native_payload'] for r in requests]
    old_plan['cases']=auto_cases+kei_cases
    term=deepcopy(old_plan['terms_manifest']['terms'][0]);term.update(sport='keirin',terms_url='https://keirin.jp/fixture-policy',source_urls=['https://keirin.jp/pc/top'])
    old_plan['terms_manifest']['terms'].append(term)
    old_raw,old_binding=_plan(old_plan)
    old_body['manifest'].update(old_binding,native_artifacts=native_pins)
    old_body.update(manifest_sha256=digest(old_body['manifest']),collection_plan_sha256=old_binding['plan_sha256'],
        cases=[dict(sport=c['sport'],race_id=c['race_id'],state='HOLD_BROWSER_SOURCE_UNVERIFIED') for c in old_plan['cases']])
    old_item=_journal(old_body,R.OLD_ARTIFACT,R.OLD_RUN,R.OLD_HEAD,datetime.fromisoformat(old_item['metadata']['created_at']))
    one_plan=deepcopy(old_plan);one_plan.update(cases=auto_cases[:1],maximum_requests=16)
    _,one_binding=_plan(one_plan)
    issued['request']['manifest'].update(one_binding,native_artifacts=native_pins,prior_journal_artifacts=[seed.pin(old_item['metadata'])])
    issued.update(old_plan=old_plan,new_plan=one_plan,old_journal_raw=old_item['raw'],old_journal_metadata=old_item['metadata'],prior_journal_archives=[old_item])
    probe_capsule=S.issue_consume_capsule(issued,KEY)
    probe_start=datetime.fromisoformat(issued['issued_at'])
    probe_active=dict(issued['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
    probe_auth=S.validate_capsule(probe_capsule,data=issued,current_run=probe_active,now=probe_start,key=KEY)
    journal=open_forecasts(collector._journal_cipher(data['journal_archives'][1]['raw']),key=KEY)
    journal.update(manifest=deepcopy(issued['request']['manifest']),manifest_sha256=digest(issued['request']['manifest']),
        collection_plan_sha256=one_binding['plan_sha256'],recovery_authorization=probe_auth.audit())
    probe_end=datetime.fromisoformat(journal['browser_attempt']['completed_at'])
    probe_result=_result(journal,natives,sixteen.PROBE_RESULT_ID,sixteen.PROBE_RUN,sixteen.PROBE_HEAD,probe_end,old_plan['execution_day'])
    probe_journal=_journal(journal,sixteen.PROBE_JOURNAL_ID,sixteen.PROBE_RUN,sixteen.PROBE_HEAD,probe_end+timedelta(seconds=2))
    auto_plan=deepcopy(old_plan);auto_plan.update(cases=auto_cases,maximum_requests=32)
    source_raw,source_binding=_plan(auto_plan)
    source=deepcopy(data['request']);source['manifest'].update(source_binding,native_artifacts=native_pins,
        prior_journal_artifacts=[seed.pin(old_item['metadata']),seed.pin(probe_journal['metadata'])],checkpoint_artifacts=[seed.pin(probe_result['metadata'])])
    source['probe_request_sha256']=digest(issued['request'])
    data.update(request=source,old_plan=old_plan,new_plan=auto_plan,native_archives=native_archives,
        journal_archives=[old_item,probe_journal],checkpoint_archives=[probe_result],probe_capsule_raw=probe_capsule)
    source_capsule=C.issue_consume_capsule(data,KEY)
    start=datetime.fromisoformat(data['issued_at'])+timedelta(seconds=1);end=start+timedelta(seconds=20)
    source_active=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
    source_auth=C.validate_capsule(source_capsule,data=data,current_run=source_active,now=start,key=KEY)
    source_journal=deepcopy(journal)
    source_journal.update(manifest=deepcopy(source['manifest']),manifest_sha256=digest(source['manifest']),
        collection_plan_sha256=source_binding['plan_sha256'],epoch_started_at=start.isoformat(),maximum_requests=32,
        workflow_run_id=data['target']['run_id'],code_sha=data['target']['head_sha'],recovery_authorization=source_auth.audit(),
        cases=[dict(sport=c['sport'],race_id=c['race_id'],state='rank_confirmed' if i==1 else 'HOLD_BROWSER_SOURCE_UNVERIFIED') for i,c in enumerate(auto_cases)])
    source_journal['browser_attempt'].update(reserved_request_limit=32,started_at=start.isoformat(),completed_at=end.isoformat())
    with tempfile.TemporaryDirectory(prefix='invented-auto32-closure-') as directory:
        root=Path(directory);root.chmod(0o700)
        index=sixteen._unpack_wire(journal,root,delta=start-probe_start)
        index.update(maximum_requests=32,completed_at=end.isoformat())
        # Author a different normal race than the original confirmed probe.
        # The ordinary collector skips the probe's already-confirmed case.
        for row in index['responses'][:2]:
            request_path=root/row['request_body_file'];request_body=json.loads(request_path.read_bytes())
            request_body['raceNo']='2';request_raw=sixteen._wire(request_body);sixteen._write_private(request_path,request_raw)
            body_path=root/row['body_file'];raw=body_path.read_bytes()
            if row['sequence']==1:
                value=json.loads(raw);value['body']['raceNo']='2';raw=sixteen._wire(value)
                sixteen._write_private(body_path,raw)
            meta_path=root/row['metadata_file'];meta=json.loads(meta_path.read_bytes())
            meta.update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),request_body_sha256=sha256(request_raw).hexdigest())
            sixteen._write_private(meta_path,sixteen._wire(meta))
        index['cases'][0]['race_id']=auto_cases[1]['race_id']
        dom=index['cases'][0]['rendered_dom'];dom_path=root/dom['file']
        dom_raw=dom_path.read_bytes().replace('予選1R'.encode(),'予選2R'.encode())
        sixteen._write_private(dom_path,dom_raw);dom.update(byte_count=len(dom_raw),source_sha256=sha256(dom_raw).hexdigest())
        dom['final_url']=dom['final_url'].replace('_1','_2')
        for row in journal['browser_quarantine']['files']:
            if row['kind']=='ORIGINAL_INDEX':sixteen._write_private(root/row['file'],sixteen._wire(index))
        planned=[dict(sport=c['sport'],race_id=c['race_id']) for c in auto_cases]
        found,_,originals=collector.browser_sources(index,root,planned,started=start,now=end,remaining=32)
        source_journal['captures']=[row[2] for row in found];source_journal['browser_captures']=originals
        sixteen._refresh_wire_projection(source_journal,index,root)
    source_run=data['target']['run_id'];source_head=data['target']['head_sha']
    source_result=_result(source_journal,natives,290002,source_run,source_head,end,old_plan['execution_day'])
    current_item=_journal(source_journal,290001,source_run,source_head,end+timedelta(seconds=2))
    current=actual_run(dict(data['first_attempt'],run_attempt=2,status='completed',conclusion='success',updated_at=(end+timedelta(seconds=3)).isoformat()))
    now=end+timedelta(hours=1,seconds=10)
    parent=dict(head_sha='9'*40,run_id=500,run_attempt=1,first_viewer_job_id=5001)
    previous=dict(head_sha=source_head,run_id=source_run,run_attempt=2,first_viewer_job_id=1002,
        recovery_request_sha256=digest(source),recovery_request_blob_sha256=sha256(collector.future.wire(source)).hexdigest(),
        journal_artifact=seed.pin(current_item['metadata']),result_artifact=seed.pin(source_result['metadata']))
    value=dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V1',repository_id=1416489937,workflow_id=392270247,
        pull_request=71,verified_parent=parent,kind='KEIRIN_SINGLE_SIXTEEN_PROBE',target_event_day=old_plan['execution_day'],previous_source=previous)
    context=dict(verified_parent=deepcopy(parent),previous_source=deepcopy(previous),verified_parent_proof={},previous_source_first_proof={})
    evidence=dict(groups=dict(native_artifacts=native_archives,checkpoint_artifacts=[probe_result,source_result],
        prior_journal_artifacts=[old_item,probe_journal,current_item]),source_request=source,source_capsule_raw=source_capsule,
        source_first_attempt=actual_run(data['first_attempt']),source_current_run=current,old_plan_raw=old_raw,source_plan_raw=source_raw,
        probe_capsule_raw=probe_capsule,probe_first_attempt=actual_run(data['probe_first_attempt']),old_run=actual_run(data['old_run']),
        prior_runs=[actual_run(r) for r in data['prior_runs']]+[current])
    return value,evidence,context,now


def single_fixture():
    """Return an independent copy of sixteen authored inputs and full crypto chain."""
    return deepcopy(_single_fixture())


@lru_cache(maxsize=1)
def _eight_fixture():
    """A complete authored KEIRIN S16 source with its own original two-wire UI."""
    from tests import test_keirin_official_result_adapter as keirin
    value,data,_,now=single_fixture()
    original=open_forecasts(data['old_plan_raw'],key=KEY)
    old_item=data['groups']['prior_journal_artifacts'][0]
    old_body=open_forecasts(collector._journal_cipher(old_item['raw']),key=KEY)
    cases=[c for c in original['cases'] if c['sport']=='keirin'];case=deepcopy(cases[0])
    one=deepcopy(original);one.update(cases=[case],maximum_requests=16)
    one_raw,binding=_plan(one,600)
    manifest=deepcopy(data['source_request']['manifest'])
    manifest.update(binding,prior_journal_artifacts=[seed.pin(a['metadata']) for a in data['groups']['prior_journal_artifacts']],
        checkpoint_artifacts=[seed.pin(a['metadata']) for a in data['groups']['checkpoint_artifacts']])
    request=dict(schema=S.REQUEST,repository_id=R.REPOSITORY_ID,pull_request=71,mode=S.HISTORICAL_MODE,
        probe_sport='keirin',old_journal_artifact_id=R.OLD_ARTIFACT,manifest=manifest)
    first=deepcopy(data['source_first_attempt']);first.update(id=600,head_sha='6'*40,
        updated_at=(now-timedelta(seconds=1)).isoformat(),run_started_at=(now-timedelta(minutes=10)).isoformat())
    issued=dict(request=request,target=dict(run_id=600,head_sha='6'*40,run_attempt=2),issued_at=now.isoformat(),
        not_before=now.isoformat(),expires_at=(now+timedelta(minutes=30)).isoformat(),old_journal_raw=old_item['raw'],
        old_journal_metadata=old_item['metadata'],old_run=data['old_run'],prior_runs=data['prior_runs'],first_attempt=first,
        old_plan=original,new_plan=one,prior_journal_archives=data['groups']['prior_journal_artifacts'])
    capsule=S.issue_consume_capsule(issued,KEY)
    auth=S.validate_capsule(capsule,data=issued,current_run=dict(first,run_attempt=2,status='in_progress',conclusion=None),now=now,key=KEY)
    _,result_raw,result_meta,_=keirin.fixture(unit=False)
    context=result_meta['keirin_result_archive_context'];browser=context['browser_capture']['metadata']
    delta=now-datetime.fromisoformat(browser['started_at'])
    result_meta=sixteen._shift_timestamps(result_meta,delta)
    context=result_meta.pop('keirin_result_archive_context');browser=context['browser_capture']['metadata']
    for row in browser['ledger']:
        if 'sequence' in row:row['headers_received_at']=row['response_received_at']
    identity_raw=base64.b64decode(context['identity_capture']['raw_base64']);identity_meta=context['identity_capture']['metadata']
    dom_raw=base64.b64decode(context['browser_capture']['rendered_dom_base64'])
    end=now+timedelta(seconds=20);planned=[dict(sport='keirin',race_id=case['race_id'])]
    index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=now.isoformat(),completed_at=end.isoformat(),
        maximum_requests=16,actual_request_count=2,normal_ui_only=True,manual_api_requests=0,stop_reason='FINISHED',
        responses=[],ledger=deepcopy(browser['ledger']),cases=[])
    with tempfile.TemporaryDirectory(prefix='invented-keirin16-closure-') as directory:
        root=Path(directory);root.chmod(0o700)
        for sequence,raw,meta in ((1,identity_raw,identity_meta),(2,result_raw,result_meta)):
            meta=deepcopy(meta);meta.update(method='GET',http_method='GET',resource_type='xhr')
            body_name='keirin-%d.body'%sequence;meta_name='keirin-%d.metadata.json'%sequence
            sixteen._write_private(root/body_name,raw);sixteen._write_private(root/meta_name,sixteen._wire(meta))
            index['responses'].append(dict(sequence=sequence,body_file=body_name,metadata_file=meta_name))
        sixteen._write_private(root/'keirin-dom.html',dom_raw)
        dom=dict(file='keirin-dom.html',captured_at=browser['captured_at'],byte_count=len(dom_raw),source_sha256=sha256(dom_raw).hexdigest())
        index['cases']=[dict(sport='keirin',race_id=case['race_id'],state='CAPTURED',responses=[dict(role='identity',sequence=1),
            dict(role='result',sequence=2)],rendered_dom=dom,browser_metadata=deepcopy(browser))]
        sixteen._write_private(root/'capture-index.json',sixteen._wire(index))
        found,states,originals=collector.browser_sources(index,root,planned,started=now,now=end,remaining=16)
        if states!=[dict(sport='keirin',race_id=case['race_id'],state='CAPTURED')]:raise AssertionError('AUTHORED_KEIRIN_CAPTURE_CLOSURE')
        journal=dict(schema=collector.JOURNAL_V3,execution_day=manifest['execution_day'],target_event_day=manifest['target_event_day'],
            manifest_sha256=digest(manifest),maximum_requests=16,epoch_started_at=now.isoformat(),attempts=[],
            captures=[row[2] for row in found],cases=[dict(sport='keirin',race_id=case['race_id'],state='rank_confirmed')],
            manifest=manifest,workflow_run_id=600,code_sha='6'*40,collection_plan_sha256=binding['plan_sha256'],
            recovery_authorization=auth.audit(),browser_attempt=dict(state='COMPLETE',reserved_request_limit=16,
                actual_request_count=2,started_at=now.isoformat(),completed_at=end.isoformat(),stop_reason='FINISHED'),browser_captures=originals)
        sixteen._refresh_wire_projection(journal,index,root)
    natives=[]
    for sport,(_,_,template,_,_) in pairs.templates().items():
        for source_case in original['cases']:
            if source_case['sport']==sport:
                native=deepcopy(template);native['snapshot']['race']['race_id']=source_case['race_id']
                native['adapter_lineage']['race_id']=source_case['race_id'];natives.append(native)
    result=_result(journal,natives,390002,600,'6'*40,end,original['execution_day'])
    current_item=_journal(journal,390001,600,'6'*40,end+timedelta(seconds=2))
    current=actual_run(dict(first,run_attempt=2,status='completed',conclusion='success',updated_at=(end+timedelta(seconds=3)).isoformat()))
    source=dict(head_sha='6'*40,run_id=600,run_attempt=2,first_viewer_job_id=6001,recovery_request_sha256=digest(request),
        recovery_request_blob_sha256=sha256(collector.future.wire(request)).hexdigest(),journal_artifact=seed.pin(current_item['metadata']),result_artifact=seed.pin(result['metadata']))
    value.update(kind='KEIRIN_FIRST_EIGHT_AFTER_VERIFIED_SIXTEEN',previous_source=source)
    context=dict(verified_parent=deepcopy(value['verified_parent']),previous_source=deepcopy(source),verified_parent_proof={},previous_source_first_proof={})
    evidence=dict(groups=dict(native_artifacts=data['groups']['native_artifacts'],
        checkpoint_artifacts=data['groups']['checkpoint_artifacts']+[result],prior_journal_artifacts=data['groups']['prior_journal_artifacts']+[current_item]),
        source_request=request,source_capsule_raw=capsule,source_first_attempt=actual_run(first),source_current_run=current,
        old_plan_raw=data['old_plan_raw'],source_plan_raw=one_raw,probe_capsule_raw=capsule,probe_first_attempt=actual_run(first),
        old_run=data['old_run'],prior_runs=data['prior_runs']+[current])
    return value,evidence,context,end+timedelta(hours=1,seconds=10)


def eight_fixture():
    """Return an independent copy of complete fixture KEIRIN16→32 evidence."""
    return deepcopy(_eight_fixture())
