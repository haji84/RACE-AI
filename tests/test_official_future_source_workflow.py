"""Run only workflow shell/bootstrap fixtures; no source, key or GitHub I/O."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/'.github/workflows/forecast-audit-ui.yml'
JOB='official_future_source_capture'
MANIFEST='audit/state/official-future-source-capture-input.json'
MODULE='scripts.all_existing_model_future_source_capture'
JRA_MODULE='scripts.jra_future_source_capture'
RESULT_MODULE='scripts.all_existing_model_future_result_capture'
SCHEMAS={'autorace-keirin':'RACE_AI_OFFICIAL_FUTURE_SOURCE_CAPTURE_INPUT_V1','horse':'RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_INPUT_V1',
         'official-result':'RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V1'}
PREFIXES={'autorace-keirin':'official-future-source-capture','horse':'official-jra-future-source-capture',
          'official-result':'official-future-result-capture'}
UPLOAD='actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'


def jobs(text):
    parts=re.split(r'^  ([a-z_][a-z_0-9]*):\n',text,flags=re.M)
    return dict(zip(parts[1::2],parts[2::2]))


def steps(job):return re.split(r'^      - ',job,flags=re.M)[1:]
def ident(items,value):return next((s for s in items if re.search(r'^        id: '+re.escape(value)+'$',s,re.M)),None)
def script(step):
    block=step.split('        run: ',1)[1]
    return '\n'.join(line[10:] for line in block[2:].splitlines()) if block.startswith('|\n') else block.splitlines()[0]


class FutureSourceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text=WORKFLOW.read_text();self.jobs=jobs(self.text)
        self.assertTrue(JOB in self.jobs,'dedicated future source job is missing')
        self.job=self.jobs[JOB];self.steps=steps(self.job)

    def test_only_owner_same_feature_pr71_attempt_one_after_required_success_can_capture(self):
        for clause in ("github.event_name == 'pull_request'","github.repository == 'haji84/RACE-AI'",
            'github.event.pull_request.number == 71','github.event.pull_request.head.repo.full_name == github.repository',
            "github.event.pull_request.head.ref == 'feat/four-sport-forecast-audit-view-20261022'",
            "github.event.pull_request.base.ref == 'codex/actions-four-sport-e2e'","github.actor == 'haji84'",
            "github.actor_id == '173585154'","github.triggering_actor == 'haji84'","github.run_attempt == '1'"):
            self.assertIn(clause,self.job)
        required=('train_only_tests','pr64_cross_branch_bridge','boat_pdca_state_producer','boat_pdca_state_consumer','viewer_contract')
        line=re.search(r'^    needs: \[([^\]]+)\]$',self.job,re.M)
        self.assertIsNotNone(line);self.assertEqual({x.strip() for x in line[1].split(',')},set(required))
        for job in required:self.assertIn("needs."+job+".result == 'success'",self.job)
        self.assertNotIn('official_all_racer_readback',self.job)
        self.assertRegex(self.job,r'permissions:\n      contents: write[^\n]*\n      actions: read\n')
        self.assertRegex(self.text,re.compile(r'^permissions:\n  contents: read\n',re.M))
        self.assertRegex(self.jobs['viewer_contract'],r'permissions:\n      contents: read\n      actions: read\n')
        self.assertFalse(re.search(r'^  schedule:',self.text,re.M))
        timeout=int(re.search(r'^    timeout-minutes: ([0-9]+)$',self.job,re.M)[1]);self.assertEqual(timeout,80)

    def test_prefix_and_manifest_gate_every_dependency_and_no_secret_exists_in_setup(self):
        route=ident(self.steps,'future_source_route');self.assertIsNotNone(route)
        self.assertIn('official-future-source-capture:*',route);self.assertIn('-f '+MANIFEST,route)
        checkout=self.steps[0]
        self.assertIn('actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683',checkout)
        self.assertIn('persist-credentials: false',checkout);self.assertIn('ref: ${{ github.event.pull_request.head.sha }}',checkout)
        for item in self.steps[2:]:
            if 'uses: actions/upload-artifact@' in item or 'id: future_source_readback' in item:continue
            self.assertIn("steps.future_source_route.outputs.requested == 'true'",item)
        capture=ident(self.steps,'future_source_capture');readback=ident(self.steps,'future_source_readback')
        self.assertEqual([s for s in self.steps if 'RACE_AI_STATE_KEY:' in s],[capture,readback])
        for item in self.steps:
            if item not in (capture,readback):self.assertNotIn('GH_TOKEN:',item)
        for ref in ('761247bee0209e37b1af6b8885e92cad3e9260a5','7a432e5acc4d3495a0e82bd79726929e2f8085fe'):
            dep=next(s for s in self.steps if 'ref: '+ref in s)
            self.assertIn('persist-credentials: false',dep)

    def execute(self,step,*,subject='official-future-source-capture: fixture',manifest=True,native_id='',source_id='802',
                scope='autorace-keirin',schema=None,reject=False,result_id='',capture_kind=None):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=root/'commands';commands.mkdir();runner=root/'private temp';runner.mkdir()
            log=root/'calls.jsonl';output=root/'output'
            git=commands/'git';git.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_SUBJECT"\n');git.chmod(0o700)
            if manifest:
                file=root/MANIFEST;file.parent.mkdir(parents=True)
                file.write_text(json.dumps(dict(schema=schema or SCHEMAS[scope],reject=reject)))
            (root/'race_ai').mkdir();(root/'race_ai'/'__init__.py').write_text('')
            (root/'race_ai'/'permissioned_source_delivery.py').write_text('from json import loads\ndef read_json_bytes(raw):return loads(raw)\n')
            (root/'scripts').mkdir();(root/'scripts'/'__init__.py').write_text('')
            for fixture_scope,core_name,cli in (
                ('autorace-keirin','all_existing_model_future_source_capture',MODULE),('horse','jra_future_source_capture',JRA_MODULE),
                ('official-result','all_existing_model_future_result_capture',RESULT_MODULE)):
                accepted=(SCHEMAS[fixture_scope],)+(('RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2',) if fixture_scope=='official-result' else ())
                (root/'race_ai'/(core_name+'.py')).write_text(
                    'def validate_manifest(value,*,now):\n'
                    ' assert now.utcoffset() is not None\n'
                    ' if value["schema"] not in '+repr(accepted)+' or value.get("reject"):raise ValueError("private fixture error")\n'
                    ' return value\n')
                (root/'scripts'/(cli.split('.')[-1]+'.py')).write_text(
                    'import json,os\nfrom pathlib import Path\n'
                    'def main(args):\n'
                    ' with open(os.environ["FIXTURE_LOG"],"a") as f:f.write(json.dumps([__name__,args])+"\\n")\n'
                    ' return 0\n')
            env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],RUNNER_TEMP=str(runner),
                GITHUB_OUTPUT=str(output),FIXTURE_SUBJECT=subject,FIXTURE_LOG=str(log),
                NATIVE_INPUT_ARTIFACT_ID=native_id,RESULT_ARTIFACT_ID=result_id,SOURCE_CAPTURE_ARTIFACT_ID=source_id,FUTURE_SOURCE_SCOPE=scope,
                FUTURE_CAPTURE_KIND=capture_kind or ('RESULT' if scope=='official-result' else 'SOURCE'))
            result=subprocess.run(['bash','-e','-o','pipefail','-c',script(step)],cwd=root,env=env,
                capture_output=True,text=True,timeout=10)
            recorded=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            calls=[row[1] for row in recorded];self.last_fixture_modules=[row[0] for row in recorded]
            values=dict(line.split('=',1) for line in output.read_text().splitlines()) if output.exists() else {}
            status=runner/'official-future-source-capture.status.json'
            proof=json.loads(status.read_text()) if status.exists() else None
            return result,calls,values,proof,str(runner)

    def test_full_keyless_scope_validation_selects_only_the_matching_native_cli(self):
        validate=ident(self.steps,'future_source_scope');self.assertIsNotNone(validate,'validated scope routing is missing')
        self.assertNotIn('RACE_AI_STATE_KEY',validate);self.assertNotIn('GH_TOKEN:',validate)
        self.assertIn('validate_manifest',validate)
        for scope in SCHEMAS:
            result,calls,values,_,_=self.execute(validate,scope=scope)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[])
            self.assertEqual(values,dict(scope=scope,source_artifact_prefix=PREFIXES[scope]))
        for options in (dict(schema='UNSUPPORTED'),dict(reject=True),dict(scope='horse',reject=True)):
            result,calls,values,_,_=self.execute(validate,**options)
            self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[]);self.assertEqual(values,{})
            self.assertNotIn('private fixture error',result.stderr)

    def test_jra_dispatch_uses_same_job_without_browser_and_preserves_source_only_readback(self):
        self.assertEqual(self.text.count('  official_future_source_capture:\n'),1)
        capture=ident(self.steps,'future_source_capture');readback=ident(self.steps,'future_source_readback')
        for step in (capture,readback):self.assertIn('FUTURE_SOURCE_SCOPE:',step)
        result,calls,_,proof,runner=self.execute(capture,scope='horse')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.last_fixture_modules,[JRA_MODULE])
        self.assertEqual(proof['schema'],'RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_COUNTS_V1')
        self.assertEqual(calls,[['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture']])
        for native_id in ('','801'):
            result,calls,_,_,runner=self.execute(readback,scope='horse',native_id=native_id)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.last_fixture_modules,[JRA_MODULE])
            expected=['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture','--readback-source','802']
            if native_id:expected+=['--readback-native','801']
            self.assertEqual(calls,[expected])
        for item in self.steps:
            if 'actions/setup-node@' in item or 'playwright@1.62.1' in item or 'id: future_source_browser' in item:
                self.assertIn("steps.future_source_scope.outputs.scope == 'autorace-keirin'",item)

    def test_route_is_inert_for_routine_wrong_prefix_and_missing_public_manifest(self):
        route=ident(self.steps,'future_source_route')
        for subject,exists in (('routine CI',True),('official-future-source-capture',True),
            ('prefix official-future-source-capture: nope',True),('official-future-source-capture: fixture',False)):
            with self.subTest(subject=subject,exists=exists):
                result,calls,values,_,_=self.execute(route,subject=subject,manifest=exists)
                self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[]);self.assertEqual(values,{})
        result,calls,values,_,_=self.execute(route)
        self.assertEqual(result.returncode,0);self.assertEqual(values,{'requested':'true'})

    def test_exact_pinned_tools_fixed_chromium_and_cli_bootstrap_are_bound(self):
        browser=ident(self.steps,'future_source_browser');self.assertIsNotNone(browser)
        tooling=next(s for s in self.steps if 'playwright@1.62.1' in s)
        self.assertIn('race-ai-future-ui-tools',tooling);self.assertIn('--ignore-scripts',tooling)
        self.assertIn('--no-package-lock',tooling);self.assertIn('install --with-deps chromium',tooling)
        self.assertIn('1.62.1',browser);self.assertIn('chromium.executablePath()',browser)
        capture=ident(self.steps,'future_source_capture')
        self.assertIn('NODE_PATH: ${{ runner.temp }}/race-ai-future-ui-tools/node_modules',capture)
        self.assertIn('CHROMIUM_PATH: ${{ steps.future_source_browser.outputs.chromium_path }}',capture)
        for path in ('pr64-reference/race_ai','pr72-reference/race_ai'):self.assertIn(path,capture)
        result,calls,_,proof,runner=self.execute(capture)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,[['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture']])
        self.assertFalse(proof['ready']);self.assertIsNone(proof['source_requests'])
        self.assertEqual(proof['source_request_upper_bound'],32);self.assertIsNone(proof['old_source_requests_actual'])

    def test_always_cipher_only_source_upload_and_actual_readback_survive_native_hold(self):
        native=ident(self.steps,'future_source_native_upload');source=ident(self.steps,'future_source_upload')
        proof=ident(self.steps,'future_source_proof');readback=ident(self.steps,'future_source_readback')
        self.assertIn("if: steps.future_source_capture.outputs.ready == 'true'",native)
        self.assertIn('name: ${{ steps.future_source_capture.outputs.artifact_name }}',native)
        self.assertIn('path: ${{ runner.temp }}/official-future-source-capture/native/',native)
        self.assertIn("if: always() && steps.future_source_route.outputs.requested == 'true'",source)
        self.assertIn('steps.future_source_capture.outputs.source_artifact_name',source)
        self.assertIn("format('{0}-{1}', steps.future_source_scope.outputs.source_artifact_prefix, github.run_id)",source)
        self.assertIn('path: ${{ runner.temp }}/official-future-source-capture/source/*.enc',source)
        for item in (native,source,proof):
            self.assertIn('uses: '+UPLOAD,item);self.assertNotIn('env:',item);self.assertNotIn('overwrite:',item)
            self.assertNotIn('.browser',item);self.assertNotIn('.plan.json',item)
        self.assertIn("if: always() && steps.future_source_upload.outputs.artifact-id != ''",readback)
        for native_id in ('','801'):
            result,calls,_,_,runner=self.execute(readback,native_id=native_id)
            self.assertEqual(result.returncode,0,result.stderr)
            expected=['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture','--readback-source','802']
            if native_id:expected+=['--readback-native','801']
            self.assertEqual(calls,[expected])
        self.assertIn("if: always() && steps.future_source_route.outputs.requested == 'true'",proof)
        self.assertIn('path: ${{ runner.temp }}/official-future-source-capture.status.json',proof)
        self.assertLess(self.steps.index(source),self.steps.index(readback));self.assertLess(self.steps.index(readback),self.steps.index(proof))


if __name__=='__main__':unittest.main()
