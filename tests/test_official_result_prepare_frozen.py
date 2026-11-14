"""Frozen source-free V3 preparation; authored API/Git and fixture codecs only."""
from copy import deepcopy
from hashlib import sha256
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch

from race_ai import all_existing_model_official_prepare as P
from tests.test_official_result_prepare_reused_code import reused_context

V3='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3'
SOURCE_STEPS=('Collect explicitly requested due official results using normal public navigation',
    'Verify the collected result artifact against the original frozen inputs',
    'Verify the actual encrypted collection journal even when results remain held')


def second_jobs(source,first,current):
    from datetime import timedelta
    started=(P.R.clock(first['updated_at'])+timedelta(seconds=1)).isoformat();ended=current['updated_at']
    return dict(total_count=1,jobs=[dict(id=source['first_viewer_job_id']+1,run_id=source['run_id'],run_attempt=2,
        head_sha=source['head_sha'],name='Viewer audit contract',status='completed',conclusion='success',
        started_at=started,completed_at=ended,steps=[dict(name=name,number=n+1,status='completed',conclusion='success',
            started_at=started,completed_at=ended) for n,name in enumerate(SOURCE_STEPS)])])


def frozen_context(value=None,recovery_raw=None):
    original,ctx=reused_context();value=deepcopy(original if value is None else value);value['schema']=V3
    if 'verified_parent' in value:
        value.pop('verified_parent');source=value['previous_source'];value['verified_code_ancestor']=dict(
            head_sha=source['head_sha'],run_id=source['run_id'],run_attempt=1,first_viewer_job_id=source['first_viewer_job_id'])
    source=value['previous_source'];facts=ctx['snapshot'];intent=facts['head_sha']
    issue='a'*40;parent='c'*40;prepare_parent='1'*40;current='f'*40
    ctx['executed_workflow']['commit_sha']='0'*40
    latest=dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2',repository_id=P.I.REPOSITORY_ID,
        workflow_id=P.I.WORKFLOW,pull_request=71,target={k:source[k] for k in ('head_sha','run_id','run_attempt')},
        target_first_viewer_job_id=source['first_viewer_job_id'],recovery_request_sha256=source['recovery_request_sha256'],
        recovery_request_blob_sha256=source['recovery_request_blob_sha256'],
        tested_execution_head_sha=source['head_sha'],intent_parent_sha=parent,failed_issue_dispositions=[])
    if recovery_raw is not None:facts.update(recovery_raw=recovery_raw,current_recovery_raw=recovery_raw)
    facts.update(parents=[prepare_parent],intent_head_sha=intent,execution_head_sha=source['head_sha'],
        current_head_sha=current,latest_issue_head_sha=issue,source_issue_head=issue,
        latest_issue_raw=json.dumps(latest).encode(),protected_files_sha256='1'*64,
        preparation_raw=json.dumps(value).encode(),issue_history=[issue],
        source_issue_is_ancestor=True,source_parent_is_code_descendant=True,
        source_issue_commit=dict(head_sha=issue,parents=[parent],changed_files=[P.I.ISSUE_PATH],
            subject='official-results-issue: exact frozen source'))
    source_binding=dict(schema='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1',tested_execution_head_sha=source['head_sha'],
        intent_head_sha=issue,intent_parent_sha=parent,target=deepcopy(latest['target']),
        issue_request_blob_sha256=sha256(facts['latest_issue_raw']).hexdigest(),
        recovery_request_blob_sha256=source['recovery_request_blob_sha256'],protected_files_sha256='1'*64)
    facts['source_frozen_binding']=deepcopy(source_binding)
    facts['frozen_binding']=dict(schema='RACE_AI_OFFICIAL_FROZEN_EXECUTION_BINDING_V1',kind='prepare',
        intent_head_sha=intent,intent_parent_sha=prepare_parent,intent_blob_sha256=sha256(facts['preparation_raw']).hexdigest(),
        source_frozen_binding=source_binding)
    facts['current_admission']=dict(schema='RACE_AI_OFFICIAL_FROZEN_CURRENT_ADMISSION_V1',current_head_sha=current,
        intent_head_sha=intent,latest_issue_head_sha=issue,current_pr_head_sha=current,intent_is_ancestor=True,
        current_issue_head_sha=issue,issue_history_count=1,protected_files_sha256='1'*64)
    ctx['current_pr']['head']['sha']=current
    ctx['source_second_jobs']=second_jobs(source,ctx['source_first'],ctx['source_current'])
    return value,ctx


def frozen_crypto_fixture(factory):
    """Post-admission fixture; original AES/MAC/native/results remain real."""
    from tests.official_result_prepare_fixtures import KEY
    from scripts import all_existing_model_official_result_prepare as worker
    from race_ai.all_existing_model_official_frozen_capsule import wrap_capsule
    value,data,_,now=factory();value,ctx=frozen_context(value,worker.collector.future.wire(data['source_request']))
    source=value['previous_source'];proof=P._frozen_snapshot(value,ctx['prepare_run'],ctx['current_pr'],ctx['snapshot'],ctx['executed_workflow'])
    second=P._source_second_viewer(source,data['source_current_run'],data['source_first_attempt'],
        second_jobs(source,data['source_first_attempt'],data['source_current_run']),now)
    context=dict(verified_code_ancestor=value['verified_code_ancestor'],previous_source=source,
        verified_code_ancestor_proof={},previous_source_first_proof={},source_second_viewer_job_id=second['job_id'],
        source_second_viewer_proof=second,**proof)
    data['source_capsule_raw']=wrap_capsule(data['source_capsule_raw'],context['frozen_binding']['source_frozen_binding'],key=KEY)
    return value,data,context,now


class FrozenPreparationRequestTests(unittest.TestCase):
    def test_explicit_v3_keeps_exact_source_code_pins_and_rejects_unknown_fields(self):
        value,_=frozen_context()
        try:actual=P.validate_prepare_request(value)
        except ValueError as exc:self.fail('explicit frozen V3 request rejected: '+str(exc))
        self.assertEqual(actual,value)
        for change in ('extra','both','boolean','other_code','other_viewer'):
            wrong=deepcopy(value)
            if change=='extra':wrong['current_head_sha']='f'*40
            elif change=='both':wrong['verified_parent']=wrong['verified_code_ancestor']
            elif change=='boolean':wrong['verified_code_ancestor']['run_id']=True
            elif change=='other_code':wrong['verified_code_ancestor']['head_sha']='9'*40
            else:wrong['verified_code_ancestor']['first_viewer_job_id']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):P.validate_prepare_request(wrong)


class FrozenSnapshotBindingTests(unittest.TestCase):
    def admit(self,value,ctx):
        api=getattr(P,'_frozen_snapshot',None)
        self.assertTrue(callable(api),'frozen preparation snapshot binding is missing')
        return api(value,ctx['prepare_run'],ctx['current_pr'],ctx['snapshot'],ctx['executed_workflow'])

    def test_unrelated_current_code_uses_distinct_tested_intent_and_current_heads(self):
        value,ctx=frozen_context();before=deepcopy(ctx)
        result=self.admit(value,ctx)
        self.assertEqual(result['frozen_execution_head'],value['previous_source']['head_sha'])
        self.assertEqual(result['source_issue_head'],'a'*40)
        self.assertEqual(result['preparation_intent_head'],ctx['prepare_run']['head_sha'])
        self.assertEqual(result['admitted_current_pr_head'],'f'*40)
        self.assertTrue(result['frozen_code_execution']);self.assertFalse(result['current_pr_code_executed'])
        self.assertEqual(ctx,before)

    def test_missing_or_inconsistent_provenance_never_binds(self):
        for change in ('missing','code','intent','current','issue','workflow','fingerprint','issue_mode',
                       'issue_parent','issue_subject','prepare_extra','prepare_parent','ancestry','source_parent'):
            value,ctx=frozen_context();facts=ctx['snapshot'];binding=facts['frozen_binding']
            if change=='missing':facts.pop('frozen_binding')
            elif change=='code':binding['source_frozen_binding']['tested_execution_head_sha']='9'*40
            elif change=='intent':binding['intent_head_sha']='9'*40
            elif change=='current':facts['current_admission']['current_head_sha']='9'*40
            elif change=='issue':binding['source_frozen_binding']['intent_head_sha']='9'*40
            elif change=='workflow':ctx['executed_workflow']['blob_sha']='9'*40
            elif change=='fingerprint':binding['source_frozen_binding']['protected_files_sha256']='not-a-sha'
            elif change=='issue_mode':facts['source_issue_commit']['changed_files'].append('race_ai/code.py')
            elif change=='issue_parent':facts['source_issue_commit']['parents'].append('9'*40)
            elif change=='issue_subject':facts['source_issue_commit']['subject']='unrelated: code'
            elif change=='prepare_extra':facts['changed_files'].append('race_ai/code.py')
            elif change=='prepare_parent':facts['parents'].append('9'*40)
            elif change=='ancestry':facts['source_issue_is_ancestor']=False
            else:facts['source_parent_is_code_descendant']=False
            with self.subTest(change=change),self.assertRaises(ValueError):self.admit(value,ctx)

    def test_context_stability_excludes_only_fresh_admitted_pr_tip(self):
        value,ctx=frozen_context();initial=self.admit(value,ctx)
        api=getattr(P,'context_digest',None)
        self.assertTrue(callable(api),'stable frozen context digest is missing')
        advanced=deepcopy(initial);advanced['admitted_current_pr_head']='9'*40
        self.assertEqual(api(initial),api(advanced))
        for name in ('source_issue_head','preparation_intent_head','protected_files_sha256','frozen_binding'):
            changed=deepcopy(initial);changed[name]='changed'
            with self.subTest(name=name):self.assertNotEqual(api(initial),api(changed))
        legacy=dict(verified_parent={'head_sha':'a'*40})
        self.assertEqual(api(legacy),P.digest(legacy))


class FrozenFullContextTests(unittest.TestCase):
    def test_actual_source_full_first_and_fixed_two_bind_without_testing_current_code(self):
        value,ctx=frozen_context()
        try:proof=P.admit_context(value,**ctx)
        except (ValueError,KeyError) as exc:self.fail('frozen full source context rejected: '+str(exc))
        self.assertTrue(proof['frozen_code_execution']);self.assertFalse(proof['parent_whole_first_verified'])
        self.assertEqual(proof['verified_code_ancestor'],value['verified_code_ancestor'])
        self.assertEqual(proof['source_issue_head'],'a'*40)
        self.assertEqual(proof['admitted_current_pr_head'],'f'*40)
        self.assertNotIn('immediate_issuer_parent',proof)

    def test_unverified_source_and_foreign_current_scope_remain_holds(self):
        for change in ('running','attempt','first_failed','viewer_skipped','fork','closed','owner','base','branch'):
            value,ctx=frozen_context()
            if change=='running':ctx['source_current']['status']='in_progress'
            elif change=='attempt':ctx['source_current']['run_attempt']=3
            elif change=='first_failed':ctx['source_first']['conclusion']='failure'
            elif change=='viewer_skipped':ctx['source_jobs']['jobs'][0]['steps'][0]['conclusion']='skipped'
            elif change=='fork':ctx['current_pr']['head']['repo']['id']=7
            elif change=='closed':ctx['current_pr']['state']='closed'
            elif change=='owner':ctx['current_pr']['user']['id']=7
            elif change=='base':ctx['current_pr']['base']['ref']='different'
            else:ctx['current_pr']['head']['ref']='different'
            with self.subTest(change=change),self.assertRaises(ValueError):P.admit_context(value,**ctx)

    def test_actual_second_viewer_is_distinct_and_all_source_readbacks_completed(self):
        value,ctx=frozen_context();api=getattr(P,'_source_second_viewer',None)
        self.assertTrue(callable(api),'actual second-attempt Viewer proof is missing')
        source=value['previous_source'];jobs=ctx['source_second_jobs']
        proof=api(source,ctx['source_current'],ctx['source_first'],jobs,ctx['now'])
        self.assertEqual(proof['job_id'],source['first_viewer_job_id']+1)
        for change in ('missing','running','failed','old_job','old_attempt','wrong_head','missing_readback','skipped_readback','old_time','late_time'):
            wrong=deepcopy(jobs);job=wrong['jobs'][0]
            if change=='missing':wrong=dict(total_count=0,jobs=[])
            elif change=='running':job['status']='in_progress'
            elif change=='failed':job['conclusion']='failure'
            elif change=='old_job':job['id']=source['first_viewer_job_id']
            elif change=='old_attempt':job['run_attempt']=1
            elif change=='wrong_head':job['head_sha']='9'*40
            elif change=='missing_readback':job['steps'].pop()
            elif change=='skipped_readback':job['steps'][-1]['conclusion']='skipped'
            elif change=='old_time':job['started_at']=ctx['source_first']['updated_at']
            else:job['completed_at']=(P.R.clock(ctx['now'])+P.timedelta(days=1)).isoformat()
            with self.subTest(change=change),self.assertRaises(ValueError):api(source,ctx['source_current'],ctx['source_first'],wrong,ctx['now'])


class FrozenOutputTests(unittest.TestCase):
    def outcome(self):
        from scripts import all_existing_model_official_result_prepare as worker
        from tests.test_official_result_prepare import plans,DAY
        from tests.test_all_existing_model_official_recovery import KEY
        from race_ai.boat_all_model_store import seal_forecasts
        value,ctx=frozen_context();proof=P._frozen_snapshot(value,ctx['prepare_run'],ctx['current_pr'],
            ctx['snapshot'],ctx['executed_workflow'])
        old,journal=plans();plan=P.derive_plan(P.SINGLE,old,journal)
        cipher=seal_forecasts(plan,run_id='99',round_no=P.ROUND,key=KEY)
        request=P.build_recovery_request(value,json.loads(ctx['snapshot']['recovery_raw']),
            plan_sha256=sha256(cipher).hexdigest(),now=DAY)
        counts=dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARATION_COUNTS_V3',ready=True,
            plan_cipher_sha256=sha256(cipher).hexdigest(),recovery_request_sha256=P.digest(request),
            prepare_run_id=99,prepare_head_sha=ctx['prepare_run']['head_sha'],prepared_at=DAY.isoformat(),
            verified_code_ancestor=value['verified_code_ancestor'],previous_source=value['previous_source'],
            source_second_viewer_job_id=ctx['source_second_jobs']['jobs'][0]['id'],
            **{k:v for k,v in proof.items() if k!='frozen_binding'})
        return worker,dict(plan_cipher=cipher,request=request,counts=counts)

    def test_exact_three_outputs_require_all_frozen_provenance(self):
        worker,value=self.outcome()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            try:worker.write_outputs(root/'good',value)
            except ValueError as exc:self.fail('valid frozen outputs rejected: '+str(exc))
            self.assertEqual({p.name for p in (root/'good').iterdir()},{'sealedplan.enc','request.json','counts.json'})
            for key in ('frozen_execution_head','source_issue_head','preparation_intent_head','admitted_current_pr_head',
                        'protected_files_sha256','executed_workflow','frozen_code_execution','current_pr_code_executed',
                        'reused_code_ancestor','parent_whole_first_verified','source_second_viewer_job_id'):
                wrong=deepcopy(value);wrong['counts'].pop(key)
                with self.subTest(key=key),self.assertRaises(ValueError):worker.write_outputs(root/key,wrong)
                self.assertFalse((root/key).exists())

    def test_real_original_crypto_prepares_three_files_with_frozen_context(self):
        # This is the post-admission preparation boundary. Real Git/API
        # admission is exercised separately, without replacing source crypto.
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        from scripts import all_existing_model_official_result_prepare as worker
        value,data,context,now=frozen_crypto_fixture(single_fixture)
        try:result=P.prepare_from_evidence(value,data,context=context,run_id=501,
            head_sha=context['preparation_intent_head'],now=now,key=KEY)
        except (ValueError,KeyError) as exc:self.fail('frozen real source preparation rejected: '+str(exc))
        self.assertEqual(result['counts']['schema'],'RACE_AI_OFFICIAL_RESULT_PLAN_PREPARATION_COUNTS_V3')
        self.assertEqual(result['counts']['context_sha256'],P.context_digest(context))
        self.assertEqual(result['counts']['previous_normal_observation_count'],1)
        self.assertEqual((result['counts']['source_requests'],result['counts']['grants_issued']), (0,0))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'prepared';worker.write_outputs(output,result)
            self.assertEqual({p.name for p in output.iterdir()},{'sealedplan.enc','request.json','counts.json'})
        wrong=deepcopy(context);wrong['source_issue_head']='9'*40
        wrong['frozen_binding']['source_frozen_binding']['intent_head_sha']='9'*40
        with patch.object(P.C,'evidence',side_effect=AssertionError('WRONG_FROZEN_SOURCE_REACHED_REPLAY')):
            with self.assertRaises(ValueError):P.prepare_from_evidence(value,data,context=wrong,run_id=501,
                head_sha=context['preparation_intent_head'],now=now,key=KEY)

    def test_actual_wrapped_keirin_normal_probe_prepares_original_eight(self):
        from tests.official_result_prepare_fixtures import eight_fixture,KEY
        from scripts import all_existing_model_official_result_prepare as worker
        value,data,context,now=frozen_crypto_fixture(eight_fixture);before=deepcopy(data)
        result=P.prepare_from_evidence(value,data,context=context,run_id=601,
            head_sha=context['preparation_intent_head'],now=now,key=KEY)
        self.assertEqual((result['counts']['case_count'],result['counts']['maximum_new_requests']),(8,32))
        self.assertEqual(result['counts']['previous_normal_observation_count'],1)
        self.assertIsNone(result['counts']['old_source_requests_actual']);self.assertEqual(result['counts']['old_source_requests_upper_bound'],32)
        self.assertEqual(data,before)
        with tempfile.TemporaryDirectory() as directory:worker.write_outputs(Path(directory)/'prepared',result)

    def test_single_replays_an_original_probe_kept_in_a_frozen_outer(self):
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        from race_ai.all_existing_model_official_frozen_capsule import wrap_capsule
        from race_ai.boat_all_model_store import open_forecasts
        value,data,context,now=frozen_crypto_fixture(single_fixture)
        probe=open_forecasts(data['probe_capsule_raw'],key=KEY)['body']
        binding=deepcopy(context['frozen_binding']['source_frozen_binding'])
        binding.update(tested_execution_head_sha=probe['target']['head_sha'],
            intent_head_sha='8'*40,intent_parent_sha='7'*40,target=deepcopy(probe['target']),
            recovery_request_blob_sha256=sha256(json.dumps(probe['request'],sort_keys=True,
                separators=(',',':')).encode()).hexdigest())
        data['probe_capsule_raw']=wrap_capsule(data['probe_capsule_raw'],binding,key=KEY)
        before=deepcopy(data)
        result=P.prepare_from_evidence(value,data,context=context,run_id=501,
            head_sha=context['preparation_intent_head'],now=now,key=KEY)
        self.assertTrue(result['counts']['ready'])
        self.assertEqual((result['counts']['source_requests'],result['counts']['grants_issued']),(0,0))
        self.assertEqual(data,before)


class FrozenGitAdapterTests(unittest.TestCase):
    def fixture(self,root):
        from tests.test_official_frozen_execution import GitFixture,ObjectReader,PREP,wire
        fixture=GitFixture(root);value,_=frozen_context();source=value['previous_source']
        source.update(head_sha=fixture.base,run_id=17,first_viewer_job_id=101,
            recovery_request_sha256=fixture.issue['recovery_request_sha256'],
            recovery_request_blob_sha256=fixture.issue['recovery_request_blob_sha256'])
        for key in ('journal_artifact','result_artifact'):source[key].update(head_sha=fixture.base,run_id=17)
        value['verified_code_ancestor'].update(head_sha=fixture.base,run_id=17,first_viewer_job_id=101)
        files=dict(fixture.current_files,**{PREP:wire(value)})
        intent=fixture.commit(files,[fixture.current],'official-results-prepare: genuine data-only D')
        current=fixture.commit(dict(files,**{'unrelated.py':b"raise AssertionError('newer code must not execute')"}),[intent],'later owner code')
        return fixture,ObjectReader(fixture),value,intent,current,files

    def test_real_git_uses_exact_source_issue_and_stable_moving_tip(self):
        from scripts import all_existing_model_official_result_prepare as worker
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture,reader,value,intent,current,files=self.fixture(root)
            snapshot=worker.FrozenPrepareSnapshot(root,intent,fixture.base,reader=reader)
            initial_pr=fixture.pr(current);snapshot.refresh(initial_pr);facts=snapshot.prepare_facts(value)
            with patch.dict(os.environ,dict(GITHUB_SHA=intent,GITHUB_WORKFLOW_SHA=intent)):
                workflow=worker.executed_workflow(reader,intent,facts['tested_workflow_blob'])
            initial=P._frozen_snapshot(value,dict(head_sha=intent),initial_pr,facts,workflow)
            later=fixture.commit(dict(files,**{'another.py':b'unrelated later bytes'}),[current],'more owner code')
            later_pr=fixture.pr(later);snapshot.refresh(later_pr);fresh=snapshot.prepare_facts(value)
            changed=P._frozen_snapshot(value,dict(head_sha=intent),later_pr,fresh,workflow)
            self.assertEqual(P.context_digest(initial),P.context_digest(changed))
            self.assertNotEqual(initial['admitted_current_pr_head'],changed['admitted_current_pr_head'])
            self.assertEqual(initial['source_issue_head'],fixture.intent)
            self.assertEqual(initial['frozen_execution_head'],fixture.base)

    def test_changed_protected_git_data_holds_before_key_or_archive(self):
        from scripts import all_existing_model_official_result_prepare as worker
        from tests.test_official_frozen_execution import WORKFLOW
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture,reader,value,intent,current,files=self.fixture(root)
            bad=fixture.commit(dict(files,**{WORKFLOW:b'changed permission workflow'}),[current],'unreviewed workflow')
            original=reader.json
            reader.json=lambda path:fixture.pr(bad) if path=='pulls/71' else original(path)
            reader.archive=Mock(side_effect=AssertionError('NO_ARCHIVE'));key=Mock(side_effect=AssertionError('NO_KEY'))
            snapshot=worker.FrozenPrepareSnapshot(root,intent,fixture.base,reader=reader)
            with self.assertRaises(ValueError):worker.prepare_once(snapshot=snapshot,prepare_run_id=501,
                reader=reader,key_loader=key)
            key.assert_not_called();reader.archive.assert_not_called()


class FrozenWorkerOptionTests(unittest.TestCase):
    def test_invalid_runtime_witness_holds_before_key_or_archive(self):
        from scripts import all_existing_model_official_result_prepare as worker
        value,ctx=frozen_context();snapshot=Mock();snapshot.facts=ctx['snapshot']
        snapshot.read.return_value=json.dumps(value).encode();snapshot.prepare_facts.return_value=ctx['snapshot']
        snapshot.execution_witness.return_value=dict(frozen_code_execution=False,current_pr_code_executed=True,
            executed_workflow=ctx['executed_workflow'])
        reader=Mock();reader.json.return_value=ctx['current_pr'];key=Mock(side_effect=AssertionError('NO_KEY'))
        with patch.object(worker,'executed_workflow',return_value=ctx['executed_workflow']):
            with self.assertRaisesRegex(ValueError,'FROZEN_RUNTIME_WITNESS'):
                worker.prepare_once(snapshot=snapshot,prepare_run_id=ctx['prepare_run']['id'],reader=reader,
                    key_loader=key,clock=lambda:ctx['now'])
        key.assert_not_called();reader.archive.assert_not_called()

    def test_all_or_none_flags_require_private_tested_code_root_distinct_from_data(self):
        from argparse import Namespace
        from scripts import all_existing_model_official_result_prepare as worker
        from tests.test_official_frozen_execution import GitFixture
        api=getattr(worker,'frozen_options',None)
        self.assertTrue(callable(api),'frozen code/data-root options are missing')
        blank=Namespace(frozen_git_root=None,frozen_intent_head=None,frozen_execution_head=None)
        self.assertIsNone(api(blank,dict()))
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory);code=temp/'tested';code.mkdir(mode=0o700);f=GitFixture(code)
            data=temp/'data';data.mkdir();env=dict(head_sha='a'*40,temp=temp)
            args=Namespace(frozen_git_root=str(data),frozen_intent_head='a'*40,frozen_execution_head=f.current)
            with patch.object(worker,'ROOT',code):
                result=api(args,env)
                self.assertEqual(result,dict(git_root=data,intent_head='a'*40,execution_head=f.current))
                for change in ('partial','relative','intent','code','same','mode'):
                    bad=deepcopy(args)
                    if change=='partial':bad.frozen_execution_head=None
                    elif change=='relative':bad.frozen_git_root='relative'
                    elif change=='intent':bad.frozen_intent_head='b'*40
                    elif change=='code':bad.frozen_execution_head='b'*40
                    elif change=='same':bad.frozen_git_root=str(code)
                    else:code.chmod(0o755)
                    with self.subTest(change=change),self.assertRaises(ValueError):api(bad,env)
                    code.chmod(0o700)


class FrozenWorkerFlowTests(unittest.TestCase):
    def test_real_transport_crypto_and_fresh_tip_complete_without_current_code_import(self):
        """Authored Git/workflow witness; real route gate, AES/MAC and all labels."""
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        from tests.test_official_result_issue import actual_run
        from tests.test_official_recovery_preflight import jobs
        from race_ai.all_existing_model_official_issue_transport import GithubIssueTransport
        from race_ai.boat_all_model_store import open_forecasts
        from scripts import all_existing_model_official_result_prepare as worker
        value,data,_,now=frozen_crypto_fixture(single_fixture)
        _,ctx=frozen_context(value,worker.collector.future.wire(data['source_request']))
        facts=ctx['snapshot'];facts['intervening_issue_heads']=[];source=value['previous_source'];events=[]
        plans={data['source_request']['manifest']['plan_path']:data['source_plan_raw']}
        old=next(a for a in data['groups']['prior_journal_artifacts'] if a['metadata']['id']==P.R.OLD_ARTIFACT)
        oldbody=open_forecasts(worker.collector._journal_cipher(old['raw']),key=KEY)
        plans[oldbody['manifest']['plan_path']]=data['old_plan_raw']
        probe=open_forecasts(data['probe_capsule_raw'],key=KEY)['body'];probe_request=probe['request'];previous_head='2'*40
        previous=dict(schema=P.I.SCHEMA,repository_id=P.I.REPOSITORY_ID,workflow_id=P.I.WORKFLOW,pull_request=71,
            target=probe['target'],target_first_viewer_job_id=1002,recovery_request_sha256=P.digest(probe_request),
            recovery_request_blob_sha256=sha256(worker.collector.future.wire(probe_request)).hexdigest())
        previous_raw=worker.collector.future.wire(previous)
        facts['issue_history']=[facts['source_issue_head'],previous_head];facts['current_admission']['issue_history_count']=2
        class Snapshot:
            def __init__(self):self.facts=deepcopy(facts)
            def read(self,head,path,limit):
                if path==P.PATH:return self.facts['preparation_raw']
                if path==P.I.ISSUE_PATH:return previous_raw if head==previous_head else self.facts['latest_issue_raw']
                if path==P.I.REQUEST_PATH:
                    return worker.collector.future.wire(probe_request) if head==probe['target']['head_sha'] else self.facts['recovery_raw']
                return plans[path]
            def prepare_facts(self,_):return deepcopy(self.facts)
            def refresh(self,pr):
                head=pr['head']['sha'];self.facts['current_head_sha']=head
                self.facts['current_admission'].update(current_head_sha=head,current_pr_head_sha=head)
                return deepcopy(self.facts)
            def execution_witness(self,reader):return dict(frozen_code_execution=True,current_pr_code_executed=False,
                executed_workflow=ctx['executed_workflow'])
            def issue_history(self,head):
                return [previous_head] if head in (source['head_sha'],self.facts['source_issue_commit']['parents'][0]) else self.facts['issue_history']
            def previous_issue(self,head):return self.read(self.issue_history(head)[0],P.I.ISSUE_PATH,16384)
            def commit_facts(self,head):
                if head==previous_head:return dict(head_sha=head,parents=[probe['target']['head_sha']],
                    changed_files=[P.I.ISSUE_PATH],subject='official-results-issue: authored previous source')
                if head==self.facts['source_issue_head']:return self.facts['source_issue_commit']
                return dict(head_sha=head,parents=[],changed_files=[],subject='official-results-collect: authored tested source')
            def is_ancestor(self,before,after):
                order=[probe['target']['head_sha'],previous_head,source['head_sha'],self.facts['source_issue_commit']['parents'][0],
                    self.facts['source_issue_head'],self.facts['parents'][0],self.facts['head_sha'],'f'*40,'9'*40]
                return before==after or before in order and after in order and order.index(before)<=order.index(after)
        firsts={source['run_id']:data['source_first_attempt'],data['probe_first_attempt']['id']:data['probe_first_attempt']}
        runs={r['id']:r for r in (data['old_run'],*data['prior_runs'])}
        runs[501]=actual_run(dict(data['source_first_attempt'],id=501,head_sha=facts['head_sha'],
            run_attempt=1,status='in_progress',conclusion=None))
        archives={a['metadata']['id']:a for group in data['groups'].values() for a in group}
        pr_calls=0
        def request(method,path,body):
            nonlocal pr_calls
            events.append(path)
            if path=='pulls/71':
                pr_calls+=1;pr=deepcopy(ctx['current_pr']);pr['head']['sha']=('f' if pr_calls==1 else '9')*40
                return json.dumps(pr).encode()
            if '/artifacts?' in path:
                requested=int(path.split('/')[2]);rows=[a['metadata'] for a in archives.values() if a['metadata']['workflow_run']['id']==requested]
                return json.dumps(dict(total_count=len(rows),artifacts=rows)).encode()
            if path.startswith('actions/artifacts/'):
                ident=int(path.split('/')[2]);return archives[ident]['raw'] if path.endswith('/zip') else json.dumps(archives[ident]['metadata']).encode()
            ident=int(path.split('/')[2])
            if path.endswith('/attempts/1'):value=firsts[ident]
            elif path.endswith('/attempts/1/jobs?per_page=100'):
                value=jobs(firsts[ident]);value['jobs'][0]['id']=source['first_viewer_job_id'] if ident==source['run_id'] else 1002
            elif path.endswith('/attempts/2/jobs?per_page=100'):value=second_jobs(source,data['source_first_attempt'],data['source_current_run'])
            else:value=runs[ident]
            return json.dumps(value).encode()
        transport=GithubIssueTransport(request)
        class Reader:
            def json(self,path):return transport.json(path)
            def archive(self,pin):return transport.archive(pin)
            def head(self):return 'f'*40
            def read_file(self,commit,path,limit):
                return data['source_capsule_raw'] if path.endswith('/'+str(source['run_id'])+'/2.enc') else data['probe_capsule_raw']
        def key():events.append('KEY_LOOKUP');return KEY
        result=worker.prepare_once(snapshot=Snapshot(),prepare_run_id=501,reader=Reader(),key_loader=key,clock=lambda:now)
        self.assertTrue(result['counts']['ready']);self.assertEqual(result['counts']['admitted_current_pr_head'],'9'*40)
        self.assertEqual(events.count('KEY_LOOKUP'),1)
        self.assertLess(events.index('actions/runs/'+str(source['run_id'])+'/attempts/2/jobs?per_page=100'),events.index('KEY_LOOKUP'))
        with tempfile.TemporaryDirectory() as directory:worker.write_outputs(Path(directory)/'prepared',result)


if __name__=='__main__':unittest.main()
