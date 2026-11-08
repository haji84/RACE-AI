"""Execute the production keyless shell against real Git and stdlib bootstrap.

All GitHub receipts are synthetic metadata; no owner key, pip, or provider is
used. The bootstrap and dependency declaration are the actual project bytes.
"""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tests.test_official_result_prepare_workflow import jobs,steps,ident,script,WORKFLOW
from tests.test_official_frozen_execution import GitFixture,ObjectReader,wire,ISSUE,REQUEST,PREP,BOOTSTRAP


class FrozenWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job=jobs(WORKFLOW.read_text())['official_result_recovery_issuer']
        self.steps=steps(self.job)

    def test_bootstrap_and_dependencies_are_before_the_only_secret_steps(self):
        bootstrap=ident(self.steps,'frozen_execution')
        self.assertIsNotNone(bootstrap,'keyless frozen bootstrap must precede dependencies and owner key')
        self.assertIn('python -I -S -',script(bootstrap))
        self.assertNotIn('RACE_AI_STATE_KEY:',bootstrap)
        dependency=next(s for s in self.steps if 'pip install' in s)
        for step in (dependency,ident(self.steps,'issue'),ident(self.steps,'prepare')):
            self.assertIn("steps.frozen_execution.outputs.ready == 'true'",step)
            self.assertGreater(self.steps.index(step),self.steps.index(bootstrap))
            self.assertIn('working-directory: ${{ steps.frozen_execution.outputs.execution_root }}',step)
        for name in ('issue','prepare'):
            step=ident(self.steps,name)
            self.assertIn('python -I -',script(step))
            self.assertIn("execution.parent / 'pr64-reference' / 'race_ai'",script(step))
            for flag in ('--frozen-git-root','--frozen-intent-head','--frozen-execution-head'):
                self.assertIn(flag,script(step))
        self.assertEqual(sum('RACE_AI_STATE_KEY:' in s for s in self.steps),2)

    def fixture(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        home=Path(directory.name);root=home/'metadata';root.mkdir()
        f=GitFixture(root)
        # Preserve synthetic public request/terms, but execute the real stdlib
        # bootstrap and preserve the actual project dependency declaration.
        f.files['.github/workflows/forecast-audit-ui.yml']=WORKFLOW.read_bytes()
        f.files['requirements-history.txt']=(WORKFLOW.parents[2]/'requirements-history.txt').read_bytes()
        f.files['race_ai/__init__.py']=(WORKFLOW.parents[2]/'race_ai/__init__.py').read_bytes()
        f.base=f.commit(f.files,[],'official-results-collect: actual bootstrap bytes')
        f.tip=f.commit(dict(f.files,**{'race_ai/untrusted.py':b'raise AssertionError("CURRENT_CODE_EXECUTED")'}),[f.base],'unrelated untested Python')
        f.issue=f.marker(f.base,f.tip)
        f.intent_files=dict(f.files,**{'race_ai/untrusted.py':b'raise AssertionError("CURRENT_CODE_EXECUTED")',ISSUE:wire(f.issue)})
        f.intent=f.commit(f.intent_files,[f.tip],'official-results-issue: synthetic actual shell')
        f.current_files=dict(f.intent_files,**{'ui.txt':b'later unrelated UI'})
        f.current=f.commit(f.current_files,[f.intent],'later UI')
        f.git('reset','--hard','-q',f.intent)
        reader=ObjectReader(f)
        reader.overrides['actions/runs/17']=reader.json('actions/runs/17/attempts/1')
        reader.overrides['actions/runs/99']=dict(reader.json('actions/runs/17/attempts/1'),id=99,head_sha=f.intent,status='in_progress',conclusion=None)
        merge=f.commit(f.intent_files,[f.tip,f.intent],'synthetic executed workflow')
        reference=root/'pr64-reference'
        project=WORKFLOW.parents[2]
        # Viewer already checks out literal PR64 separately. Its object need
        # not be reachable from the mutable PR's primary Git object database.
        reference_source=project/'pr64-reference'
        if not (reference_source/'.git').exists():reference_source=project
        subprocess.run(['git','clone','--quiet','--shared','--no-checkout',str(reference_source),str(reference)],check=True,capture_output=True)
        subprocess.run(['git','checkout','--quiet','--detach','761247bee0209e37b1af6b8885e92cad3e9260a5'],cwd=reference,check=True,capture_output=True)
        runner=home/'runner';runner.mkdir()
        event=runner/'event.json';event.write_bytes(wire(dict(number=71,sender=dict(id=173585154,login='haji84'),repository=dict(id=1416489937,full_name='haji84/RACE-AI'),pull_request=f.pr(f.intent))))
        metadata={name:reader.json(name) for name in ('pulls/71','actions/runs/17','actions/runs/17/attempts/1','actions/runs/17/attempts/1/jobs?per_page=100','actions/runs/99')}
        metadata_file=runner/'metadata.json';metadata_file.write_text(json.dumps(metadata))
        binary=home/'bin';binary.mkdir();gh=binary/'gh'
        gh.write_text('#!'+os.sys.executable+'\nimport json,os,sys\nfrom pathlib import Path\nprefix="repos/haji84/RACE-AI/"\nassert sys.argv[1]=="api" and sys.argv[2].startswith(prefix)\npath=sys.argv[2][len(prefix):]\nprint(json.dumps(json.loads(Path(os.environ["FIXTURE_METADATA"]).read_text())[path]))\n');gh.chmod(0o700)
        env=dict(os.environ,GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_EVENT_NAME='pull_request',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='haji84',GITHUB_ACTOR_ID='173585154',GITHUB_TRIGGERING_ACTOR='haji84',GITHUB_REF='refs/pull/71/merge',GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/forecast-audit-ui.yml@refs/pull/71/merge',GITHUB_WORKFLOW_SHA=merge,GITHUB_SHA=merge,GITHUB_EVENT_PATH=str(event),GITHUB_RUN_ID='99',RUNNER_TEMP=str(runner),GITHUB_OUTPUT=str(runner/'output'),FROZEN_KIND='issue',FIXTURE_METADATA=str(metadata_file),PATH=str(binary)+os.pathsep+os.environ['PATH'])
        env.pop('RACE_AI_STATE_KEY',None)
        return f,reader,env,metadata_file

    def run_bootstrap(self,f,env):
        step=ident(self.steps,'frozen_execution');self.assertIsNotNone(step)
        return subprocess.run(['bash','-e','-o','pipefail','-c',script(step)],cwd=f.root,env=env,capture_output=True,text=True)

    def test_actual_keyless_shell_materializes_only_fully_tested_tree(self):
        f,reader,env,_=self.fixture();result=self.run_bootstrap(f,env)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        output=dict(line.split('=',1) for line in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
        self.assertEqual(output['ready'],'true');self.assertEqual(output['execution_head'],f.base)
        private=Path(output['execution_root'])
        self.assertEqual((private/BOOTSTRAP).read_bytes(),f.files[BOOTSTRAP])
        self.assertEqual((private/'requirements-history.txt').read_bytes(),f.files['requirements-history.txt'])
        self.assertFalse((private/'race_ai/untrusted.py').exists())
        self.assertTrue((private.parent/'pr64-reference/race_ai').is_dir())
        self.assertEqual(f.git('rev-parse','HEAD'),f.intent)

    def test_actual_prepare_shell_preserves_d_intent_and_original_c_binding(self):
        f,reader,env,metadata_file=self.fixture()
        prepare=dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3',
            verified_code_ancestor=dict(head_sha=f.base,run_id=17),previous_source=dict(head_sha=f.base,run_id=17))
        files=dict(f.current_files,**{PREP:wire(prepare)})
        head=f.commit(files,[f.current],'official-results-prepare: synthetic P3 shell')
        f.git('reset','--hard','-q',head)
        merge=f.commit(files,[f.current,head],'synthetic P3 workflow')
        event=json.loads(Path(env['GITHUB_EVENT_PATH']).read_text());event['pull_request']=f.pr(head)
        Path(env['GITHUB_EVENT_PATH']).write_text(json.dumps(event))
        env.update(FROZEN_KIND='prepare',GITHUB_SHA=merge,GITHUB_WORKFLOW_SHA=merge)
        metadata=json.loads(metadata_file.read_text());metadata['pulls/71']=f.pr(head)
        metadata['actions/runs/99']['head_sha']=head
        metadata['actions/runs/17']['run_attempt']=2
        metadata_file.write_text(json.dumps(metadata))
        result=self.run_bootstrap(f,env)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        output=dict(line.split('=',1) for line in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
        self.assertEqual(output['intent_head'],head);self.assertEqual(output['execution_head'],f.base)
        proof=json.loads(Path(output['provenance_path']).read_text())
        self.assertEqual(proof['source_frozen_binding']['intent_head_sha'],f.intent)
        self.assertEqual(proof['intent_head_sha'],head)

    def test_missing_local_merge_workflow_uses_only_authenticated_fixed_git_metadata(self):
        f,reader,env,metadata_file=self.fixture()
        head=env['GITHUB_WORKFLOW_SHA'];metadata=json.loads(metadata_file.read_text())
        commit=reader.json('git/commits/'+head);metadata['git/commits/'+head]=commit
        tree=commit['tree']['sha']
        for part in '.github/workflows/forecast-audit-ui.yml'.split('/'):
            obj=reader.json('git/trees/'+tree);metadata['git/trees/'+tree]=obj
            row=next(r for r in obj['tree'] if r['path']==part)
            if row['type']=='tree':tree=row['sha']
            else:metadata['git/blobs/'+row['sha']]=reader.json('git/blobs/'+row['sha'])
        metadata_file.write_text(json.dumps(metadata))
        (f.root/'.git/objects'/head[:2]/head[2:]).unlink()
        result=self.run_bootstrap(f,env)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertIn('ready=true',Path(env['GITHUB_OUTPUT']).read_text())

    def test_actual_workflow_or_legacy_intent_cannot_start_frozen_bootstrap(self):
        for change in ('workflow','legacy'):
            with self.subTest(change=change):
                f,reader,env,_=self.fixture()
                files=deepcopy(f.intent_files)
                if change=='workflow':
                    files['.github/workflows/forecast-audit-ui.yml']=b'untested workflow'
                    merge=f.commit(files,[f.tip,f.intent],'different actual workflow')
                    env['GITHUB_SHA']=env['GITHUB_WORKFLOW_SHA']=merge
                else:
                    marker=deepcopy(f.issue);marker['schema']='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
                    files[ISSUE]=wire(marker)
                    head=f.commit(files,[f.tip],'official-results-issue: legacy marker')
                    f.git('reset','--hard','-q',head)
                result=self.run_bootstrap(f,env)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(Path(env['GITHUB_OUTPUT']).exists())

    def test_bad_full_first_or_mutated_bootstrap_never_exports_secret_paths(self):
        for change in ('failed_first','dirty_bootstrap'):
            with self.subTest(change=change):
                f,reader,env,metadata_file=self.fixture()
                if change=='failed_first':
                    metadata=json.loads(metadata_file.read_text());metadata['actions/runs/17/attempts/1']['conclusion']='failure';metadata_file.write_text(json.dumps(metadata))
                else:
                    (f.root/BOOTSTRAP).write_text('raise AssertionError("UNTESTED_CURRENT_BOOTSTRAP")\n')
                result=self.run_bootstrap(f,env)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('UNTESTED_CURRENT_BOOTSTRAP',result.stderr)
                self.assertFalse(Path(env['GITHUB_OUTPUT']).exists())
                self.assertFalse((Path(env['RUNNER_TEMP'])/'official-frozen-execution'/'execution').exists())

    def test_only_live_source_calls_use_frozen_flag_and_full_git_history(self):
        viewer=jobs(WORKFLOW.read_text())['viewer_contract']
        checkout=steps(viewer)[0]
        for option in ('fetch-depth: 0','filter: blob:none','fetch-tags: false'):self.assertIn(option,checkout)
        source_lines=[line.strip() for line in viewer.splitlines() if 'python -m scripts.all_existing_model_official_result_recovery ' in line]
        self.assertEqual(len(source_lines),4)
        for line in source_lines:
            self.assertEqual('--frozen-source' in line,'--readback-' not in line)


if __name__=='__main__':unittest.main()
