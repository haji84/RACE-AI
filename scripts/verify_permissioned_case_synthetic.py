"""Fictional case→original wire→known-commit witness→revisions integration.

Actual pinned research code runs on authored examples. Source permissions,
publication, ACL decisions, executor pin, GitHub answers and results are all
fictional. No provider, external write, release, real freeze or device action.
"""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
REF=ROOT/'pr71-private-transport-reference'
PIN='ebe93f13062cf0461b81b924a5dc0482ada37b56'


def main():
    if not __debug__:raise RuntimeError('Verification requires enabled assertions')
    sys.path.insert(0,str(ROOT))
    from scripts.verify_offline_model_run_synthetic import check_reference
    check_reference()
    git_root=REF if (REF/'.git').exists() else ROOT
    rel='race_ai/github_freeze_receipt.py'
    original=subprocess.check_output(['git','-C',str(git_root),'show',PIN+':'+rel])
    if (REF/rel).read_bytes().replace(b'\r\n',b'\n')!=original.replace(b'\r\n',b'\n'):
        raise RuntimeError('Pinned external verifier changed')
    import race_ai
    import tests
    race_ai.__path__.append(str(REF/'race_ai'));tests.__path__.append(str(REF/'tests'))
    sys.path.insert(0,str(REF/'tests'))
    from test_permissioned_source_delivery import snapshot,gate,AT,FEED_SCHEMA
    from race_ai.comprehensive_four_sport_models import digest,validate
    from race_ai.four_sport_model_suite import ALL_MODELS
    from race_ai.permissioned_model_case import prepare_case,load_case
    from race_ai.github_witness_resolution import resolve_anchor_witness
    from race_ai.github_freeze_receipt import BASE,verify_github_freeze
    from race_ai.race_bound_freeze_receipt import verify_bound_receipt
    from race_ai.model_suite_settlement import audit_model_settlements
    day='2030-01-15';branch='audit/freeze-fictional-cases'
    versions={name:'0.1.0-UNTRAINED' for name in ALL_MODELS}
    declaration=tuple((name,versions[name],PIN) for name in ALL_MODELS)
    snapshots={sport:snapshot(sport) for sport in ('boat','keirin','autorace','horse')}
    # Small valid authored horse field; existing18-runner transport coverage is
    # retained separately. No real runner roster is altered by this fixture.
    # The pinned research suite currently requires exactly eight unique picks:
    # three entrants have only six possible trifectas and are unsupported here.
    # Preserve that inherited gap instead of weakening its binding guard.
    snapshots['horse']['participants']=snapshots['horse']['participants'][:4]
    records=[]
    for sport,snap in snapshots.items():
        family='horse_jra' if sport=='horse' else sport
        for n in (1,2):
            records.append({'race_id':f'{family}:{day}:fictional-venue:{n}',
                'sport':family,'venue':'fictional-venue','race_no':n,
                'sales_cutoff_at':snap['race']['sales_cutoff_at'],
                'cutoff_verified':False,'prediction':None,'result':None})
    ledger={'schema':'RACE_AI_FORECAST_AUDIT_V1','dataset_status':'AUDIT_ONLY',
            'event_date_jst':day,'records':records}
    policy=gate();now=[datetime.fromisoformat(AT)]
    def forbidden(*args,**kwargs):raise AssertionError('committed case recomputed or authority renewed')
    deliveries=[];freezes=[];api={};wire_hashes=[]
    with tempfile.TemporaryDirectory(prefix='race-ai-fictional-cases-') as temp:
        for index,(sport,snap) in enumerate(snapshots.items()):
            family='horse_jra' if sport=='horse' else sport
            race_id=f'{family}:{day}:fictional-venue:1'
            raw=json.dumps({'schema':FEED_SCHEMA,'snapshot':snap},sort_keys=True,
                           separators=(',',':')).encode()
            request={'schema':'RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V1',
                'case_id':'fictional-case-'+sport,'race_id':race_id,'ledger':deepcopy(ledger),
                'source_payload_sha256':hashlib.sha256(raw).hexdigest(),
                'policy_record_sha256':policy.document_sha256,'feature_snapshot_sha256':digest(snap),
                'as_of':snap['race']['as_of'],'sales_cutoff_at':snap['race']['sales_cutoff_at'],
                'expected_model_ids':list(ALL_MODELS),'expected_model_versions':versions,
                'model_source_sha40':PIN,'executor_source_sha40':'f'*40,
                'input_evidence_ref':'FICTIONAL_INPUT_NOT_AUTHORITY',
                'cutoff_evidence_ref':'FICTIONAL_CUTOFF_NOT_AUTHORITY',
                'model_declaration_evidence_ref':'FICTIONAL_DECLARATION_NOT_AUTHORITY'}
            path=Path(temp)/(sport+'.sqlite');now[0]=datetime.fromisoformat(AT)
            admissions={'private_path_verifier':lambda path,stage:True,
                'verify_input':lambda request,snapshot,policy_hash:True,
                'verify_cutoff':lambda row:True,
                'admit_model_roster':lambda value:value==declaration}
            first=prepare_case(path,request,raw,policy,clock=lambda:now[0],**admissions)
            assert first['status']=='PREPARED_NOT_EXTERNAL_FROZEN'
            loaded=load_case(path,expected_request_sha256=first['request_sha256'],
                private_path_verifier=admissions['private_path_verifier'])
            assert loaded['wire_sha256']==hashlib.sha256(loaded['wire']).hexdigest()
            wire_hashes.append(loaded['wire_sha256'])
            now[0]=datetime.fromisoformat(day+'T11:05:00+09:00')
            with patch('race_ai.permissioned_source_delivery.deliver',side_effect=forbidden):
                second=prepare_case(path,request,raw,policy,clock=lambda:now[0],
                    private_path_verifier=admissions['private_path_verifier'],
                    verify_input=forbidden,verify_cutoff=forbidden,admit_model_roster=forbidden)
            assert first==second
            again=load_case(path,expected_request_sha256=first['request_sha256'],
                            private_path_verifier=admissions['private_path_verifier'])
            assert again['wire']==loaded['wire'] and again['plans']==loaded['plans']
            deliveries.append({'race_id':race_id,'delivery':loaded['delivery']})
            for offset,(name,plan) in enumerate(zip(ALL_MODELS,loaded['plans'])):
                rid=100+index*4+offset;commit=f'{rid:040x}'
                run={'id':rid,'event':'push','head_sha':commit,'head_branch':branch,
                     'repository':{'full_name':'haji84/RACE-AI'},'created_at':day+'T00:40:00Z'}
                api[BASE+'/actions/runs?head_sha='+commit+'&event=push&per_page=100']={
                    'total_count':1,'workflow_runs':[deepcopy(run)]}
                api[BASE+'/actions/runs/'+str(rid)]=run
                anchor=(json.dumps(plan['anchor'],sort_keys=True,separators=(',',':'),
                                   ensure_ascii=False)+'\n').encode()
                api[BASE+'/contents/'+plan['path']+'?ref='+commit]={
                    'type':'file','encoding':'base64','content':base64.b64encode(anchor).decode()}
                seen=resolve_anchor_witness(plan,commit,loaded['persisted_at'],
                    expected_branch=branch,github_fetch=lambda url:deepcopy(api[url]),
                    trusted_legacy_verifier=verify_github_freeze,clock=lambda:now[0])
                assert seen['github_reads']==3 and seen['external_pre_cutoff_presence_verified']
                assert not seen['eligible_for_hit_at_8'] and not seen['source_rights_verified']
                freezes.append({'race_id':race_id,'model_id':name,
                    'prediction_sha256':plan['anchor']['prediction_sha256'],
                    'generated_at':loaded['generated_at'],'persisted_at':loaded['persisted_at'],
                    'cutoff_at':snap['race']['sales_cutoff_at'],'receipt':seen['receipt']})
        results=[{'race_id':row['race_id'],'status':'FINAL','trifecta_offered':True,
                  'payouts':[{'combination':[1,2,3],'yen_per_100':1000}],
                  'refund_status':'NONE','revision_no':1,
                  'confirmed_at':day+'T11:00:00+09:00',
                  'source_ref':'https://example.org/fictional-result'} for row in records]
        def external(receipt,sha,persisted,cutoff,*,expected_race_id):
            return verify_bound_receipt(receipt,sha,persisted,cutoff,
                expected_race_id=expected_race_id,trusted_legacy_verifier=verify_github_freeze,
                github_fetch=lambda url:deepcopy(api[url]))
        kwargs={'expected_model_ids':ALL_MODELS,'expected_model_versions':versions,
            'expected_model_source_sha40':PIN,'validate_snapshot':validate,'allow_source':policy.authorize}
        denied=audit_model_settlements(ledger,results,deliveries,freezes,**kwargs)
        assert all(row['formal_hit_at_8_all'] is None for row in denied['models'].values())
        gates={'admit_model_roster':lambda value:value==declaration,
            'verify_result':lambda row:True,'verify_cutoff':lambda row:True,
            'verify_coverage':lambda value:digest(value)==digest(ledger),
            'verify_model_freeze':external}
        report=audit_model_settlements(ledger,results,deliveries,freezes,**kwargs,**gates)
        for row in report['models'].values():
            assert row['eligible_verified_subset']==8 and row['freeze_verified_subset']==4
        correction=deepcopy(results[0]);correction['revision_no']=2
        correction['confirmed_at']=day+'T11:01:00+09:00'
        correction['payouts'][0]['combination']=[3,2,1]
        changed=audit_model_settlements(ledger,results+[correction],deliveries,freezes,**kwargs,**gates)
        assert changed['evaluation_sha256']!=report['evaluation_sha256']
        print(json.dumps({'scope':'FICTIONAL_PERMISSIONED_CASE_INTEGRATION_ONLY',
            'sports':4,'models':4,'private_cases':4,'prepared_plans':16,'fictional_receipts':16,
            'ledger_races':8,'eligible_each_model':8,'frozen_each_model_with_fictional_gates':4,
            'original_wire_preserved':len(wire_hashes)==4,'resumed_models':0,
            'result_revisions':9,'default_formal_metrics_available':False,
            'source_requests':0,'external_writes':0,'real_forecasts':0},sort_keys=True))
    return 0


if __name__=='__main__':
    def no_network(*args,**kwargs):
        raise AssertionError('network forbidden')
    with patch('socket.create_connection',side_effect=no_network), \
         patch('socket.socket.connect',side_effect=no_network), \
         patch('urllib.request.OpenerDirector.open',side_effect=no_network):
        raise SystemExit(main())
