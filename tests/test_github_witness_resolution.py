"""Fictional read-only GitHub evidence; no network, write, model or rights grant."""
import base64
from copy import deepcopy
from datetime import datetime
import json
import traceback
import unittest

from race_ai.append_only_freeze_writer import prepare_anchor
from race_ai.github_witness_resolution import resolve_anchor_witness, WitnessResolutionError

BASE='https://api.github.com/repos/haji84/RACE-AI'
SHA='b'*40
BRANCH='audit/freeze-fictional'
PERSISTED='2030-01-15T09:01:00+09:00'
CUTOFF='2030-01-15T10:00:00+09:00'
NOW='2030-01-15T11:00:00+09:00'  # Read-only recovery may occur after cutoff.


def prepared():
    return prepare_anchor({'schema':'RACE_AI_P0_SOURCE_MODEL_BINDING_V1',
        'model_race_id':'boat:2030-01-15:fictional:1','event_date_jst':'2030-01-15',
        'model_claimed_cutoff_at':CUTOFF,'external_freeze_verified':False,
        'eligible_for_scoring':False,'models':[{'model_id':'fictional-model',
        'prediction_sha256':'a'*64}]},'fictional-model',
        '2030-01-15T09:00:00+09:00',PERSISTED)


def fixture():
    p=prepared()
    run={'id':42,'event':'push','head_sha':SHA,'head_branch':BRANCH,
         'created_at':'2030-01-15T00:02:00Z',
         'repository':{'full_name':'haji84/RACE-AI'}}
    raw=(json.dumps(p['anchor'],sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
    blob={'type':'file','encoding':'base64','content':base64.b64encode(raw).decode()}
    data={BASE+'/actions/runs?head_sha='+SHA+'&event=push&per_page=100':
          {'total_count':1,'workflow_runs':[deepcopy(run)]},
          BASE+'/actions/runs/42':run,
          BASE+'/contents/'+p['path']+'?ref='+SHA:blob}
    return p,data


def legacy(receipt,sha,persisted,cutoff,*,_fetch):
    run=_fetch(BASE+'/actions/runs/'+str(receipt['run_id']))
    anchor=_fetch(BASE+'/contents/'+receipt['path']+'?ref='+run['head_sha'])
    return run['id']==receipt['run_id'] and anchor['type']=='file'


def resolve(p,data,*,reader=None,verifier=legacy,sha=SHA,clock=None):
    calls=[]
    def get(url):
        calls.append(url)
        return deepcopy(data[url]) if reader is None else reader(url)
    answer=resolve_anchor_witness(p,sha,PERSISTED,expected_branch=BRANCH,
        github_fetch=get,trusted_legacy_verifier=verifier,
        clock=clock or (lambda:datetime.fromisoformat(NOW)))
    return answer,calls


class WitnessResolutionTests(unittest.TestCase):
    def test_exact_three_reads_resolve_original_hash_after_cutoff(self):
        p,data=fixture();out,calls=resolve(p,data)
        self.assertEqual(len(calls),3)
        self.assertEqual(out['receipt'],{'run_id':42,'path':p['path']})
        self.assertEqual(out['commit_sha'],SHA)
        self.assertEqual(out['external_server_time'],'2030-01-15T00:02:00Z')
        self.assertTrue(out['external_pre_cutoff_presence_verified'])
        self.assertFalse(out['eligible_for_hit_at_8'])
        self.assertFalse(out['source_rights_verified'])
        self.assertFalse(out['full_private_payload_retention_verified'])

    def test_unknown_commit_stays_stopped_with_zero_reads(self):
        p,data=fixture();out,calls=resolve(p,data,sha=None)
        self.assertEqual(calls,[])
        self.assertEqual(out['status'],'STOPPED_COMMIT_UNKNOWN_DO_NOT_WRITE')
        self.assertIsNone(out['receipt'])

    def test_default_reader_and_verifier_do_not_use_network(self):
        p,_=fixture()
        with self.assertRaises(WitnessResolutionError):
            resolve_anchor_witness(p,SHA,PERSISTED,expected_branch=BRANCH)

    def test_invalid_commit_or_path_fails_before_read(self):
        for sha in ('A'*40,'../main',True):
            p,data=fixture()
            with self.subTest(sha=sha),self.assertRaises(WitnessResolutionError):resolve(p,data,sha=sha)
        p,data=fixture();p['path']='audit/freezes/2030-01-15/../../secret'
        with self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_missing_truncated_or_malformed_list_cannot_be_receipt(self):
        for change in ({'total_count':True},{'total_count':101},{'total_count':0},
                       {'workflow_runs':[]},{'total_count':-1},{'workflow_runs':[None]}):
            p,data=fixture();next(iter(data.values())).update(change)
            with self.subTest(change=change),self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_empty_complete_list_stays_unresolved(self):
        p,data=fixture();data[next(iter(data))]={'total_count':0,'workflow_runs':[]}
        with self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_individual_run_must_match_commit_branch_repo_and_id(self):
        for field,value in (('head_sha','c'*40),('head_branch','audit/freeze-other'),
                            ('event','workflow_dispatch'),('id',True),('id',43),
                            ('repository',{'full_name':'someone/else'})):
            p,data=fixture();data[BASE+'/actions/runs/42'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_individual_server_time_is_not_list_time(self):
        for value in (CUTOFF,'2030-01-15T11:01:00+09:00','2030-01-15T00:00:00Z',
                      '2030-01-15T00:03:00Z','2030-01-15T00:02:00'):
            p,data=fixture();data[BASE+'/actions/runs/42']['created_at']=value
            with self.subTest(value=value),self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_extra_fields_or_reformatted_anchor_are_not_original_bytes(self):
        for raw in ((json.dumps(prepared()['anchor'])+'\n').encode(),
                    json.dumps({**prepared()['anchor'],'added':True}).encode(),b'corrupt'):
            p,data=fixture();data[list(data)[2]]['content']=base64.b64encode(raw).decode()
            with self.subTest(raw=raw[:20]),self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_wrong_anchor_identity_hash_or_cutoff_rejected(self):
        for field,value in (('race_id','boat:2030-01-15:fictional:2'),
                            ('prediction_sha256','c'*64),('cutoff_at','2030-01-15T10:01:00+09:00')):
            p,data=fixture();obj=deepcopy(p['anchor']);obj[field]=value
            data[list(data)[2]]['content']=base64.b64encode(
                (json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode()).decode()
            with self.subTest(field=field),self.assertRaises(WitnessResolutionError):resolve(p,data)

    def test_verifier_cannot_skip_repeat_or_fetch_another_endpoint(self):
        def skip(*a,**kw):return True
        def repeat(r,*a,_fetch,**kw):
            _fetch(BASE+'/actions/runs/42');_fetch(BASE+'/actions/runs/42');return True
        def other(*a,_fetch,**kw):_fetch('https://example.invalid/leak');return True
        for verifier in (skip,repeat,other):
            p,data=fixture()
            with self.subTest(verifier=verifier.__name__),self.assertRaises(WitnessResolutionError):
                resolve(p,data,verifier=verifier)

    def test_input_mutation_during_callback_does_not_retarget_resolution(self):
        p,data=fixture();original=deepcopy(p)
        def reader(url):
            p['anchor']['race_id']='boat:2030-01-15:changed:9'
            p['path']='changed'
            return deepcopy(data[url])
        out,_=resolve(p,data,reader=reader)
        self.assertEqual(out['receipt']['path'],original['path'])
        self.assertEqual(out['model_race_id'],original['anchor']['race_id'])

    def test_two_eligible_runs_use_earliest_server_time_then_id(self):
        p,data=fixture();first=data[next(iter(data))];second=deepcopy(first['workflow_runs'][0])
        second['id']=43;second['created_at']='2030-01-15T00:03:00Z'
        first['total_count']=2;first['workflow_runs'].insert(0,second)
        out,_=resolve(p,data)
        self.assertEqual(out['receipt']['run_id'],42)

    def test_clock_rollback_and_naive_clock_reject(self):
        p,data=fixture();times=iter([datetime.fromisoformat(NOW),datetime.fromisoformat(PERSISTED)])
        with self.assertRaises(WitnessResolutionError):resolve(p,data,clock=lambda:next(times))
        with self.assertRaises(WitnessResolutionError):resolve(p,data,clock=lambda:datetime(2030,1,15))

    def test_transport_error_is_sanitized_and_does_not_enable_write(self):
        p,data=fixture()
        def reader(url):raise OSError('sensitive-provider-response')
        with self.assertRaises(WitnessResolutionError) as caught:resolve(p,data,reader=reader)
        self.assertNotIn('sensitive',str(caught.exception))

    def test_verifier_cannot_return_a_mutated_unverified_receipt(self):
        p,data=fixture()
        def mutating(receipt,*args,**kwargs):
            passed=legacy(receipt,*args,**kwargs)
            receipt.update(run_id=999,path='audit/freezes/2030-01-15/other.json')
            return passed
        with self.assertRaises(WitnessResolutionError):resolve(p,data,verifier=mutating)

    def test_sanitized_exception_traceback_does_not_expose_upstream_text(self):
        def transport(url):raise OSError('fictional-secret-transport-response')
        def verifier(*args,**kwargs):raise OSError('fictional-secret-verifier-response')
        for kwargs in ({'reader':transport},{'verifier':verifier}):
            p,data=fixture()
            try:resolve(p,data,**kwargs)
            except WitnessResolutionError:
                report=traceback.format_exc()
                self.assertNotIn('fictional-secret-',report)
            else:self.fail('expected safe refusal')

    def test_swallowed_guard_violation_still_invalidates_verification(self):
        def swallowed(receipt,sha,persisted,cutoff,*,_fetch):
            try:_fetch('https://example.invalid/unexpected')
            except WitnessResolutionError:pass
            return legacy(receipt,sha,persisted,cutoff,_fetch=_fetch)
        p,data=fixture()
        with self.assertRaises(WitnessResolutionError):resolve(p,data,verifier=swallowed)

    def test_swallowed_required_run_validation_or_read_failure_cannot_verify(self):
        def swallowed(receipt,sha,persisted,cutoff,*,_fetch):
            try:_fetch(BASE+'/actions/runs/42')
            except WitnessResolutionError:pass
            _fetch(BASE+'/contents/'+receipt['path']+'?ref='+SHA)
            return True
        p,data=fixture();data[BASE+'/actions/runs/42']['head_sha']='c'*40
        with self.assertRaises(WitnessResolutionError):resolve(p,data,verifier=swallowed)
        p,data=fixture()
        def reader(url):
            if url==BASE+'/actions/runs/42':raise OSError('fictional-private-error')
            return deepcopy(data[url])
        with self.assertRaises(WitnessResolutionError):resolve(p,data,verifier=swallowed,reader=reader)


if __name__=='__main__':unittest.main()
