"""Exercise preparation routing with authored local shells only; no credentials or services."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/'.github/workflows/forecast-audit-ui.yml'
JOB='official_result_recovery_issuer'
UPLOAD='actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'


def jobs(text):
    parts=re.split(r'^  ([a-z_][a-z_0-9]*):\n',text,flags=re.M)
    return dict(zip(parts[1::2],parts[2::2]))


def steps(job):return re.split(r'^      - ',job,flags=re.M)[1:]
def ident(items,value):return next((s for s in items if re.search(r'^        id: '+re.escape(value)+'$',s,re.M)),None)
def script(step):
    block=step.split('        run: ',1)[1]
    return '\n'.join(line[10:] for line in block[2:].splitlines()) if block.startswith('|\n') else block.splitlines()[0]


class PreparationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job=jobs(WORKFLOW.read_text())[JOB];self.steps=steps(self.job)

    def test_real_prefix_shell_routes_issue_and_preparation_exclusively(self):
        route=ident(self.steps,'issue_route');self.assertIsNotNone(route)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'git').write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_SUBJECT"\n');(root/'git').chmod(0o700)
            for subject,want in (
                ('official-results-issue: exact parent',{'requested':'true'}),
                ('official-results-prepare: unchanged KEIRIN plan',{'prepare_requested':'true'}),
                ('ordinary: code verification',{}),('official-results-prepare-extra: invalid',{}),
                ('official-results-collect: ordinary source',{})):
                output=root/'output';output.unlink(missing_ok=True)
                env=dict(PATH=str(root)+os.pathsep+os.environ.get('PATH',''),FIXTURE_SUBJECT=subject,GITHUB_OUTPUT=str(output))
                result=subprocess.run(['bash','-e','-o','pipefail','-c',script(route)],cwd=root,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                actual=dict(line.split('=',1) for line in output.read_text().splitlines()) if output.exists() else {}
                self.assertEqual(actual,want,subject)

    def test_shared_pr64_and_dependencies_cover_both_routes_but_secret_steps_do_not(self):
        shared="if: steps.issue_route.outputs.requested == 'true' || steps.issue_route.outputs.prepare_requested == 'true'"
        parser=next(s for s in self.steps if 'path: pr64-reference' in s)
        dependencies=next(s for s in self.steps if 'pip install' in s)
        self.assertIn(shared,parser)
        for condition in ("steps.issue_route.outputs.requested == 'true'","steps.issue_route.outputs.prepare_requested == 'true'","steps.frozen_execution.outputs.ready == 'true'"):
            self.assertIn(condition,dependencies)
        issue=ident(self.steps,'issue');prepare=ident(self.steps,'prepare')
        self.assertIsNotNone(prepare,'preparation must have its own secret-scoped step')
        self.assertIn("if: steps.issue_route.outputs.requested == 'true'",issue)
        self.assertIn("if: steps.issue_route.outputs.prepare_requested == 'true'",prepare)
        self.assertNotIn(' || ',issue.split('        env:',1)[0]);self.assertNotIn(' || ',prepare.split('        env:',1)[0])
        self.assertEqual([s for s in self.steps if 'RACE_AI_STATE_KEY:' in s],[issue,prepare])
        self.assertEqual(self.job.count('RACE_AI_STATE_KEY:'),2)

    def test_preparation_shell_uses_fixed_temp_output_and_keeps_hold_counts(self):
        prepare=ident(self.steps,'prepare');self.assertIsNotNone(prepare,'preparation shell missing')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);current=root/'mutable';current.mkdir()
            (current/'race_ai.py').write_text('raise AssertionError(\"MUTABLE_PROJECT_IMPORTED\")')
            execution=root/'trusted-fixture';execution.mkdir()
            reference=root/'pr64-reference/race_ai';reference.mkdir(parents=True)
            (execution/'race_ai').mkdir();(execution/'race_ai/__init__.py').write_text('')
            (execution/'scripts').mkdir();(execution/'scripts/__init__.py').write_text('')
            # This authored invocation stub checks the old counts/upload contract.
            # Actual bootstrap provenance is exercised by test_official_frozen_workflow.
            (execution/'scripts/all_existing_model_official_result_prepare.py').write_text(
                'import json,os\nfrom pathlib import Path\n'
                'def main(args):\n'
                ' Path(os.environ["FIXTURE_ARGS"]).write_text(json.dumps(args))\n'
                ' out=Path(args[1]);out.mkdir(mode=0o700)\n'
                ' (out/"counts.json").write_text(json.dumps({"ready":os.environ["FIXTURE_READY"]=="true"}))\n'
                ' if os.environ["FIXTURE_READY"]=="true":\n'
                '  (out/"sealedplan.enc").write_bytes(b"AUTHORED_CIPHER")\n'
                '  (out/"request.json").write_text("{}")\n'
                ' return 0 if os.environ["FIXTURE_READY"]=="true" else 1\n')
            for ready in ('true','false'):
                temp=root/('runner '+ready);temp.mkdir();args=root/'args.json'
                env=dict(PATH=os.environ.get('PATH',''),PYTHONPATH=str(current),RUNNER_TEMP=str(temp),FIXTURE_ARGS=str(args),FIXTURE_READY=ready,FROZEN_EXECUTION_ROOT=str(execution),FROZEN_GIT_ROOT=str(current),FROZEN_INTENT_HEAD='a'*40,FROZEN_EXECUTION_HEAD='b'*40)
                result=subprocess.run(['bash','-e','-o','pipefail','-c',script(prepare)],cwd=current,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0 if ready=='true' else 1,result.stderr)
                output=temp/'official-result-recovery-preparation'
                self.assertEqual(json.loads(args.read_text()),['--out-dir',str(output),'--frozen-git-root',str(current),'--frozen-intent-head','a'*40,'--frozen-execution-head','b'*40])
                self.assertEqual({p.name for p in output.iterdir()},
                    {'sealedplan.enc','request.json','counts.json'} if ready=='true' else {'counts.json'})

    def test_preparation_upload_is_always_exact_three_members_and_seven_days(self):
        upload=next((s for s in self.steps if 'name: official-result-recovery-preparation-' in s),None)
        self.assertIsNotNone(upload,'encrypted preparation upload missing')
        self.assertIn("if: always() && steps.issue_route.outputs.prepare_requested == 'true'",upload)
        self.assertIn('uses: '+UPLOAD,upload)
        self.assertIn('name: official-result-recovery-preparation-${{ github.run_id }}-1',upload)
        paths=re.search(r'^          path: \|\n((?:            [^\n]+\n)+)',upload,re.M)
        self.assertIsNotNone(paths)
        self.assertEqual([line.strip() for line in paths[1].splitlines()],
            ['${{ runner.temp }}/official-result-recovery-preparation/'+name for name in ('sealedplan.enc','request.json','counts.json')])
        self.assertIn('retention-days: 7',upload);self.assertIn('if-no-files-found: error',upload)

    def test_original_job_and_issue_outputs_remain_scoped(self):
        self.assertIn('timeout-minutes: 10',self.job);self.assertNotIn('\n    needs:',self.job)
        for clause in ("github.event_name == 'pull_request'","github.repository == 'haji84/RACE-AI'",
            'github.event.pull_request.number == 71','github.event.pull_request.head.repo.full_name == github.repository',
            "github.event.pull_request.head.ref == 'feat/four-sport-forecast-audit-view-20261022'",
            "github.actor == 'haji84'","github.actor_id == '173585154'","github.triggering_actor == 'haji84'","github.run_attempt == '1'"):
            self.assertIn(clause,self.job)
        self.assertIn('contents: write',self.job);self.assertIn('actions: read',self.job)
        issue=ident(self.steps,'issue');self.assertIn('from scripts.all_existing_model_official_result_issue import main',issue)
        self.assertIn("main(['--proof', str(Path(os.environ['RUNNER_TEMP']) / 'official-result-recovery-issue-proof.json'),",issue)
        for flag in ('--frozen-git-root','--frozen-intent-head','--frozen-execution-head'):
            self.assertIn(flag,issue)
        upload=next(s for s in self.steps if 'name: official-result-recovery-issue-proof-' in s)
        self.assertIn("if: always() && steps.issue_route.outputs.requested == 'true'",upload)
        self.assertIn('path: ${{ runner.temp }}/official-result-recovery-issue-proof.json',upload)

    def test_every_existing_job_shell_has_valid_bash_syntax(self):
        for step in self.steps:
            if '        run: ' not in step:continue
            result=subprocess.run(['bash','-n'],input=script(step),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
