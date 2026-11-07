"""Synthetic owner issuance; never reads an actual key or contacts a service."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts, seal_forecasts
from tests.test_all_existing_model_official_recovery import fixture, KEY, HEAD, NOW
from tests.test_official_recovery_preflight import jobs

try:
    from race_ai import all_existing_model_official_issue as issue
except ImportError:
    issue=None

ISSUER='b'*40
REPO='haji84/RACE-AI'
BRANCH='feat/four-sport-forecast-audit-view-20261022'
PATH='audit/state/official-result-recovery-issue-request.json'


def actual_run(run):
    return dict(deepcopy(run), workflow_id=392270247,path='.github/workflows/forecast-audit-ui.yml',
        head_branch=BRANCH,event='pull_request', actor=dict(id=173585154,login='haji84'),
        triggering_actor=dict(id=173585154,login='haji84'))


def context():
    data,_,_=fixture();raw=json.dumps(data['request'],sort_keys=True).encode()
    request=dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1',repository_id=1416489937,
        workflow_id=392270247,pull_request=71,target=data['target'],target_first_viewer_job_id=1001,
        recovery_request_sha256=digest(data['request']),recovery_request_blob_sha256=sha256(raw).hexdigest())
    issuer=actual_run(dict(data['first_attempt'],id=88,head_sha=ISSUER,status='in_progress',conclusion=None))
    pr=dict(number=71,state='open',user=dict(id=173585154,login='haji84'),head=dict(sha=ISSUER,ref=BRANCH,
        repo=dict(id=1416489937,full_name=REPO)),base=dict(ref='codex/actions-four-sport-e2e',repo=dict(id=1416489937,full_name=REPO)))
    snapshot=dict(head_sha=ISSUER,parents=[HEAD],changed_files=[PATH],subject='official-results-issue: exact parent',
        target_subject='official-results-collect: exact case',recovery_raw=raw,current_recovery_raw=raw)
    return request,dict(issuer_run=issuer,current_pr=pr,snapshot=snapshot,target_run=actual_run(data['first_attempt']),
        first_attempt=actual_run(data['first_attempt']),jobs=jobs(data['first_attempt']),now=NOW),data


def bootstrap_manifest():
    # Reviewed 6a18873b pins plus the last actual 901 journal. Execution requests
    # advance cumulatively; they must not redefine this immutable bootstrap.
    return json.loads((Path(__file__).resolve().parent/'fixtures/official-result-issue-bootstrap-pins.json').read_bytes())


class OfficialIssueTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(issue,'Actions-only issue core must exist')
        return issue

    def test_exact_parent_target_with_real_full_first_attempt_produces_safe_proof(self):
        api=self.api();request,ctx,_=context();before=deepcopy(ctx)
        proof=api.admit_context(request,**ctx)
        self.assertEqual(proof['target'],dict(head_sha=HEAD,run_id=77,run_attempt=2))
        self.assertEqual(proof['target_first_viewer_job_id'],1001)
        self.assertEqual(proof['verified_first_head_sha'],HEAD)
        self.assertEqual(ctx,before)

    def test_untrusted_actor_changed_code_or_different_request_cannot_issue(self):
        api=self.api()
        for change in ('actor','trigger','fork','current_head','parent','extra_file','prefix','target_prefix',
                'request_bytes','target_attempt','target_workflow','target_event','target_branch','first_failure',
                'python_skipped','partial_jobs','job_id','issuer_attempt'):
            request,ctx,_=context()
            if change=='actor':ctx['issuer_run']['actor']['id']=9
            elif change=='trigger':ctx['issuer_run']['triggering_actor']['id']=9
            elif change=='fork':ctx['current_pr']['head']['repo']['id']=9
            elif change=='current_head':ctx['current_pr']['head']['sha']='c'*40
            elif change=='parent':ctx['snapshot']['parents']=['c'*40]
            elif change=='extra_file':ctx['snapshot']['changed_files'].append('race_ai/unsafe.py')
            elif change=='prefix':ctx['snapshot']['subject']='other'
            elif change=='target_prefix':ctx['snapshot']['target_subject']='official-results-issue: other'
            elif change=='request_bytes':ctx['snapshot']['current_recovery_raw']+=b' '
            elif change=='target_attempt':ctx['target_run']['run_attempt']=2
            elif change=='target_workflow':ctx['target_run']['workflow_id']=9
            elif change=='target_event':ctx['target_run']['event']='workflow_dispatch'
            elif change=='target_branch':ctx['target_run']['head_branch']='main'
            elif change=='first_failure':ctx['first_attempt']['conclusion']='failure'
            elif change=='python_skipped':ctx['jobs']['jobs'][0]['steps'][0]['conclusion']='skipped'
            elif change=='partial_jobs':ctx['jobs']['total_count']=2
            elif change=='job_id':request['target_first_viewer_job_id']=99
            else:ctx['issuer_run']['run_attempt']=2
            with self.subTest(change=change),self.assertRaises(ValueError):api.admit_context(request,**ctx)

    def test_unknown_schema_extra_fields_and_boolean_ids_are_rejected(self):
        api=self.api()
        for change in ('schema','extra','bool','attempt','digest'):
            request,_,_=context()
            if change=='schema':request['schema']='wildcard'
            elif change=='extra':request['key_path']='/private/key'
            elif change=='bool':request['target']['run_id']=True
            elif change=='attempt':request['target']['run_attempt']=3
            else:request['recovery_request_blob_sha256']='G'*64
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_issue_request(request)

    def test_bootstrap_requires_exact_approved_four_journal_pinset(self):
        api=self.api();manifest=bootstrap_manifest();api.check_pin_continuity(manifest)
        for field in ('native_artifacts','checkpoint_artifacts','prior_journal_artifacts'):
            value=deepcopy(manifest);value[field][-1]['digest']='sha256:'+'0'*64
            with self.subTest(field=field),self.assertRaises(ValueError):api.check_pin_continuity(value)
        value=deepcopy(manifest);value['prior_journal_artifacts'].pop()
        with self.assertRaises(ValueError):api.check_pin_continuity(value)

    def test_cumulative_appends_cannot_hide_a_missing_or_changed_bootstrap_pin(self):
        api=self.api();seed=bootstrap_manifest();manifest=deepcopy(seed)
        for index,field in enumerate(('checkpoint_artifacts','prior_journal_artifacts'),1):
            manifest[field].append(dict(id=9000000000+index,run_id=9000000000,
                head_sha='d'*40,digest='sha256:'+str(index)*64))
        # Continuity permits later epochs; issuance separately authenticates
        # every supplied archive. Appends cannot replace any required seed.
        api.check_pin_continuity(manifest)
        for field,pins in seed.items():
            for index,pin in enumerate(pins):
                for change in ('digest','omitted'):
                    value=deepcopy(manifest)
                    if change=='digest':value[field][index]['digest']='sha256:'+'0'*64
                    else:value[field].pop(index)
                    with self.subTest(field=field,pin=pin['id'],change=change),self.assertRaises(ValueError):
                        api.check_pin_continuity(value)

    def test_previous_issued_epoch_must_have_terminal_attempt_two_and_every_actual_output_pin(self):
        api=self.api();data,_,_=fixture();previous=deepcopy(data['request']);manifest=deepcopy(previous['manifest'])
        run=actual_run(dict(data['first_attempt'],run_attempt=2))
        journal=dict(id=500,name='official-result-collection-journal-77',digest='sha256:'+'1'*64,
            workflow_run=dict(id=77,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
        result=dict(id=501,name='all-existing-official-results-77-900005',digest='sha256:'+'2'*64,
            workflow_run=deepcopy(journal['workflow_run']))
        for meta,field in ((journal,'prior_journal_artifacts'),(result,'checkpoint_artifacts')):
            manifest[field].append(dict(id=meta['id'],digest=meta['digest'],run_id=77,head_sha=HEAD))
        api.check_pin_continuity(manifest,previous_request=previous,previous_run=run,previous_artifacts=[journal,result])
        for change in ('missing_journal','omitted_result','unknown','dropped_prior','duplicate_journal'):
            value=deepcopy(manifest);current=deepcopy(run);artifacts=[deepcopy(journal),deepcopy(result)]
            if change=='missing_journal':artifacts.pop(0)
            elif change=='omitted_result':value['checkpoint_artifacts'].pop()
            elif change=='unknown':current['status']='in_progress'
            elif change=='dropped_prior':value['checkpoint_artifacts'].pop(0)
            else:artifacts.append(dict(deepcopy(journal),id=502))
            with self.subTest(change=change),self.assertRaises(ValueError):api.check_pin_continuity(value,
                previous_request=previous,previous_run=current,previous_artifacts=artifacts)

    def test_publication_verifies_real_mac_at_actual_attempt_one_without_runtime_capability(self):
        api=self.api();data,_,_=fixture()
        from race_ai import all_existing_model_official_recovery as authority
        raw=authority.issue_consume_capsule(data,KEY)
        with patch.object(authority,'validate_capsule',side_effect=AssertionError('no fabricated runtime attempt2')):
            proof=api.verify_publication(raw,data=data,current_run=actual_run(data['first_attempt']),now=NOW,key=KEY,expected_raw=raw)
        self.assertEqual(proof['old_source_requests_upper_bound'],32)
        self.assertIsNone(proof['old_source_requests_actual'])
        self.assertEqual(proof['maximum_new_requests'],8)
        self.assertFalse(hasattr(proof,'validate_collector'))
        for change in ('tamper','attempt2','expired','different_bytes','first'):
            value=raw;current=actual_run(data['first_attempt']);now=NOW;expected=raw
            if change=='tamper':value=raw[:-1]+bytes([raw[-1]^1])
            elif change=='attempt2':current['run_attempt']=2
            elif change=='expired':now+=timedelta(hours=2)
            elif change=='different_bytes':expected=b'other'
            else:current['conclusion']='failure'
            with self.subTest(change=change),self.assertRaises(ValueError):api.verify_publication(value,
                data=data,current_run=current,now=now,key=KEY,expected_raw=expected)

    def test_archival_authority_rejects_denial_and_wrong_target_mac(self):
        api=self.api();data,_,_=fixture()
        from race_ai import all_existing_model_official_recovery as authority
        raw=authority.issue_consume_capsule(data,KEY)
        body=api.archival_authority(raw,request=data['request'],target=data['target'],first_attempt=data['first_attempt'],key=KEY)
        self.assertEqual(body['old_browser_outcome'],'UNKNOWN')
        for change in ('target','request','key'):
            target=deepcopy(data['target']);request=deepcopy(data['request']);key=KEY
            if change=='target':target['run_id']=78
            elif change=='request':request['probe_sport']='keirin'
            else:key=bytes(reversed(KEY))
            with self.subTest(change=change),self.assertRaises(ValueError):api.archival_authority(raw,
                request=request,target=target,first_attempt=data['first_attempt'],key=key)

    def test_valid_mac_cannot_hide_changed_budget_or_authenticated_evidence(self):
        api=self.api();data,_,_=fixture()
        from race_ai import all_existing_model_official_recovery as authority
        original=authority.issue_consume_capsule(data,KEY)
        for change in ('budget','prior_runs','old_journal','latest'):
            document=open_forecasts(original,key=KEY);body=document['body']
            if change=='budget':body['maximum_new_requests']=999
            elif change=='prior_runs':body['prior_runs']=[]
            elif change=='old_journal':body['old_journal']['cipher_sha256']='0'*64
            else:body['latest_possible_old_activity_at']='2000-01-01T00:00:00+00:00'
            document['mac']=authority._mac(body,KEY)
            raw=seal_forecasts(document,run_id='77',round_no=authority.ROUND,key=KEY)
            with self.subTest(change=change),self.assertRaises(ValueError):api.verify_publication(raw,
                data=data,current_run=actual_run(data['first_attempt']),now=NOW,key=KEY,expected_raw=raw)

    def test_integrated_sixteen_profile_replays_its_own_complete_publication_body(self):
        if importlib.util.find_spec('race_ai.all_existing_model_official_probe16') is None:
            self.skipTest('committed S dependency is tested in combined integration checkout')
        api=self.api()
        from race_ai import all_existing_model_official_probe16 as authority
        from tests.test_all_existing_model_official_probe16 import fixture as sixteen_fixture
        data,_,_=sixteen_fixture();raw=authority.issue_consume_capsule(data,KEY)
        with patch.object(authority,'validate_capsule',side_effect=AssertionError('no invented runtime attempt2')):
            proof=api.verify_publication(raw,data=data,current_run=actual_run(data['first_attempt']),
                now=NOW,key=KEY,expected_raw=raw)
        self.assertEqual(proof['maximum_new_requests'],16)
        value=open_forecasts(raw,key=KEY);value['body']['maximum_new_requests']=17
        value['mac']=authority._mac(value['body'],KEY)
        altered=seal_forecasts(value,run_id='77',round_no=authority.ROUND,key=KEY)
        with self.assertRaises(ValueError):api.verify_publication(altered,data=data,
            current_run=actual_run(data['first_attempt']),now=NOW,key=KEY,expected_raw=altered)

    def test_literal_registry_rejects_arbitrary_module_and_mode(self):
        api=self.api();data,_,_=fixture()
        self.assertEqual(api.authority_for(data['request']).__name__,'race_ai.all_existing_model_official_recovery')
        value=deepcopy(data['request']);value['mode']='IMPORT_anything'
        with self.assertRaises(ValueError):api.authority_for(value)
