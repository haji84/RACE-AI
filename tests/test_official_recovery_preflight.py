"""Same-head test reuse needs actual-shaped evidence; no provider or real keys."""
import base64
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_recovery as recovery
from scripts import all_existing_model_official_result_recovery as worker
from tests.test_all_existing_model_official_recovery import fixture,KEY,HEAD,NOW


FULL_STEPS=('Python synthetic journal to viewer projection tests',
    'Verify isolated experimental video decoding and measurements')


def jobs(first):
    return dict(total_count=1,jobs=[dict(id=1001,run_id=first['id'],run_attempt=1,head_sha=first['head_sha'],
        name='Viewer audit contract',status='completed',conclusion='success',
        steps=[dict(name=name,number=index+1,status='completed',conclusion='success',
            started_at=(NOW-timedelta(minutes=5)).isoformat(),
            completed_at=(NOW-timedelta(minutes=2)).isoformat()) for index,name in enumerate(FULL_STEPS)])])


class RecoveryPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.data,self.body,self.cipher=fixture();self.issuer=recovery.issue_consume_capsule;self.raw=self.issuer(self.data,KEY)
        self.current=dict(deepcopy(self.data['first_attempt']),run_attempt=2,status='in_progress',conclusion=None)
        self.env=dict(run_id=77,head_sha=HEAD,temp=self.root);self.now=NOW;self.job_document=jobs(self.data['first_attempt'])
        self.input=self.root/'request.json';self.input.write_text(json.dumps(self.data['request']))
        self.event=self.root/'event.json';self.event.write_text(json.dumps(dict(number=71,pull_request=dict(
            head=dict(sha=HEAD,repo=dict(full_name='haji84/RACE-AI'))))))
        self.output=self.root/'outputs';self.api_calls=[]
        environment=patch.dict(os.environ,dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937',GITHUB_EVENT_NAME='pull_request',GITHUB_RUN_ATTEMPT='2',
            GITHUB_EVENT_PATH=str(self.event),GITHUB_OUTPUT=str(self.output),RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()))
        environment.start();self.addCleanup(environment.stop)
        def api(path):
            self.api_calls.append(path)
            if path=='actions/runs/77':return deepcopy(self.current)
            if path=='actions/runs/77/attempts/1':return deepcopy(self.data['first_attempt'])
            if path=='actions/runs/77/attempts/1/jobs?per_page=100':return deepcopy(self.job_document)
            if path=='actions/runs/'+str(recovery.OLD_RUN):return deepcopy(self.data['old_run'])
            for item in self.data.get('prior_runs',[]):
                if path=='actions/runs/'+str(item['id']):return deepcopy(item)
            raise AssertionError('unexpected GitHub route')
        def plan(manifest,**kwargs):
            return deepcopy(self.data['old_plan'] if manifest['plan_sha256']=='f'*64 else self.data['new_plan'])
        for mocked in (patch.object(worker,'_api',side_effect=api),
                patch.object(worker,'_capsule',side_effect=lambda *_:self.raw),
                patch.object(worker.collector.future,'environment',return_value=self.env),
                patch.object(worker.collector,'utc_now',side_effect=lambda:self.now),
                patch.object(worker.collector,'_journal_artifact',side_effect=lambda *_args,**_kwargs:
                    (deepcopy(self.body),self.cipher,deepcopy(self.data['old_journal_metadata']))),
                patch.object(worker.collector,'load_plan',side_effect=plan),
                patch.object(worker.collector,'collect',side_effect=AssertionError('provider dispatch forbidden')),
                patch.object(worker.recovery,'issue_consume_capsule',side_effect=AssertionError('issuance forbidden')),
                patch.object(worker,'_write',side_effect=AssertionError('marker/private write forbidden'))):
            mocked.start();self.addCleanup(mocked.stop)
    def run_preflight(self):
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(worker.main(['--preflight','--input',str(self.input),'--out-dir',str(self.root/'unused')]),0)
        return json.loads(output.getvalue())
    def test_real_capsule_and_full_same_head_first_attempt_enable_reuse_without_consumption(self):
        before={p.name for p in self.root.iterdir()};result=self.run_preflight()
        self.assertTrue(result['reuse_prior_verification'],result)
        self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)
        self.assertFalse(result['full_verification_executed_in_this_attempt'])
        self.assertEqual(result['verified_first_attempt'],1)
        self.assertEqual(result['verified_first_head_sha'],HEAD)
        self.assertEqual(result['prior_full_jobs_sha256'],digest(self.job_document))
        self.assertRegex(result['prior_full_verification_sha256'],r'^[a-f0-9]{64}$')
        self.assertIn('reuse_prior_verification=true\n',self.output.read_text())
        self.assertEqual({p.name for p in self.root.iterdir()},before|{'outputs'})
        self.assertFalse((self.root/'unused').exists());self.assertIn('actions/runs/77/attempts/1/jobs?per_page=100',self.api_calls)
    def test_forged_missing_expired_wrong_head_and_incomplete_first_attempt_never_skip(self):
        for change in ('forged','missing','expired','wrong_head','first_failed','python_skipped','video_failed',
                'job_wrong_head','job_wrong_attempt','partial_jobs','missing_step'):
            raw=self.raw;current=deepcopy(self.current);first=deepcopy(self.data['first_attempt']);doc=deepcopy(self.job_document)
            now=self.now
            if change=='forged':self.raw=raw[:-1]+bytes([raw[-1]^1])
            elif change=='missing':self.raw=None
            elif change=='expired':self.now=NOW+timedelta(hours=1)
            elif change=='wrong_head':self.current['head_sha']='b'*40
            elif change=='first_failed':self.data['first_attempt']['conclusion']='failure'
            elif change=='python_skipped':self.job_document['jobs'][0]['steps'][0]['conclusion']='skipped'
            elif change=='video_failed':self.job_document['jobs'][0]['steps'][1]['conclusion']='failure'
            elif change=='job_wrong_head':self.job_document['jobs'][0]['head_sha']='b'*40
            elif change=='job_wrong_attempt':self.job_document['jobs'][0]['run_attempt']=2
            elif change=='partial_jobs':self.job_document['total_count']=2
            else:self.job_document['jobs'][0]['steps'].pop()
            with self.subTest(change=change):
                result=self.run_preflight();self.assertFalse(result['reuse_prior_verification'],result)
                self.assertEqual(result['source_requests'],0)
            self.raw=raw;self.current=current;self.data['first_attempt']=first;self.job_document=doc;self.now=now
    def test_clock_is_sampled_after_admission_and_jobs_and_exact_three_minute_boundary_is_required(self):
        real_api=worker._api
        for remaining in (180,179,0):
            self.now=NOW
            def api(path):
                response=real_api(path)
                if '/jobs?' in path:self.now=NOW+timedelta(minutes=30)-timedelta(seconds=remaining)
                return response
            with patch.object(worker,'_api',side_effect=api):result=self.run_preflight()
            with self.subTest(remaining=remaining):self.assertIs(result['reuse_prior_verification'],remaining>=180)
    def test_last_plan_read_cannot_reuse_a_stale_three_minute_clock(self):
        real_plan=worker.collector.load_plan;calls=[]
        def slow_plan(*args,**kwargs):
            result=real_plan(*args,**kwargs);calls.append(1)
            if len(calls)==3:self.now=NOW+timedelta(minutes=28)
            return result
        with patch.object(worker.collector,'load_plan',side_effect=slow_plan):result=self.run_preflight()
        self.assertEqual(len(calls),3);self.assertFalse(result['reuse_prior_verification'],result)
    def test_old_plans_and_all_prior_terminal_run_receipts_are_reauthenticated(self):
        pin=dict(id=13562617631,digest='sha256:'+'b'*64,run_id=42343017180,head_sha='c'*40)
        self.data['request']['manifest']['prior_journal_artifacts'].insert(0,pin)
        other=dict(deepcopy(self.data['old_run']),id=pin['run_id'],head_sha=pin['head_sha'])
        self.data['prior_runs']=[other]
        # Fixture issuance is outside preflight; the worker's issuer is still
        # patched to fail if production dispatch calls it.
        self.raw=self.issuer(self.data,KEY)
        self.input.write_text(json.dumps(self.data['request']))
        self.assertTrue(self.run_preflight()['reuse_prior_verification'])
        self.assertIn('actions/runs/'+str(pin['run_id']),self.api_calls)
        self.data['prior_runs'][0]['status']='in_progress';self.assertFalse(self.run_preflight()['reuse_prior_verification'])
        self.data['prior_runs'][0]['status']='completed';self.data['new_plan']['terms_manifest']['changed']=True
        self.assertFalse(self.run_preflight()['reuse_prior_verification'])
    def test_attempt_one_fork_local_and_missing_key_default_to_full_checks_without_issuance_or_provider(self):
        for field,value in (('GITHUB_RUN_ATTEMPT','1'),('GITHUB_RUN_ATTEMPT','3'),('GITHUB_ACTIONS','false'),
                ('GITHUB_REPOSITORY','foreign/repo'),('GITHUB_EVENT_NAME','workflow_dispatch'),('RACE_AI_STATE_KEY','')):
            with self.subTest(field=field,value=value),patch.dict(os.environ,{field:value}):
                self.assertFalse(self.run_preflight()['reuse_prior_verification'])
        event=json.loads(self.event.read_text());event['pull_request']['head']['repo']['full_name']='fork/RACE-AI'
        self.event.write_text(json.dumps(event));self.assertFalse(self.run_preflight()['reuse_prior_verification'])


class RecoveryPreflightWorkflowTests(unittest.TestCase):
    def test_only_video_step_can_reuse_prior_checks_and_python_shards_remain_mandatory(self):
        text=Path('.github/workflows/forecast-audit-ui.yml').read_text()
        blocks=re.split(r'^      - ',text,flags=re.M)
        skips=[block for block in blocks if "if: steps.official_recovery_preflight.outputs.reuse_prior_verification != 'true'" in block]
        # Legacy receipt fixtures still require both old step witnesses. The
        # current layout always executes Python in mandatory unprivileged jobs;
        # only the video step can reuse a separately verified first attempt.
        self.assertEqual(len(skips),1)
        self.assertEqual({block.splitlines()[0].removeprefix('name: ') for block in skips},{FULL_STEPS[1]})
        from tests.test_official_future_source_workflow import jobs, steps
        workflow_jobs=jobs(text)
        shard=workflow_jobs['viewer_python_full']
        viewer=workflow_jobs['viewer_contract']
        self.assertRegex(shard,r"(?m)^    if: github.event_name == 'pull_request'$")
        self.assertRegex(viewer,r'(?m)^    needs: viewer_python_full$')
        self.assertIn('shard: [0, 1, 2, 3]',shard)
        self.assertIn('fail-fast: false',shard)
        self.assertIn('permissions:\n      contents: read',shard)
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}',shard)
        for forbidden in ('reuse_prior_verification','continue-on-error','secrets.',
                          'RACE_AI_STATE_KEY','contents: write'):
            self.assertNotIn(forbidden,shard)
        executions=[step for step in steps(shard) if 'run: python -m scripts.ci_unittest_shard ' in step]
        self.assertEqual(len(executions),1)
        self.assertIn("--index '${{ matrix.shard }}' --count 4",executions[0])
        self.assertNotRegex(executions[0],r'(?m)^        if:')
        preflight=next(block for block in blocks if 'id: official_recovery_preflight' in block)
        self.assertIn("github.run_attempt == '2'",preflight)
        for part in ("github.repository == 'haji84/RACE-AI'","github.event.pull_request.number == 71",
                'github.event.pull_request.head.repo.full_name == github.repository','--preflight'):
            self.assertIn(part,preflight)
        self.assertLess(text.index('Install pinned private history cache crypto'),text.index('id: official_recovery_preflight'))
        self.assertLess(text.index('id: official_recovery_preflight'),text.index(FULL_STEPS[1]))
        for name in ('Verify owner-requested seller retirement and legacy readback',
                'Validate history formats, official reconciliation and unchanged model contracts offline',
                'Integrated product UI contracts','Install isolated pinned browser test tooling',
                'Collect explicitly requested due official results using normal public navigation',
                'Verify the collected result artifact against the original frozen inputs',
                'Exercise seven product pages at four viewport widths'):
            block=next(block for block in blocks if block.startswith('name: '+name+'\n'))
            self.assertNotIn('reuse_prior_verification',block)


if __name__=='__main__':unittest.main()
