"""Invented candidates/receipts, real encryption and existing native trainer."""
import base64
import contextlib
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_venue_research_runtime as runtime
from race_ai.boat_venue_learning import fit_venue_rows, read_candidate, seal_candidate
from race_ai.boat_venue_learning_handoff import publish_learning_candidate
from race_ai.github_freeze_receipt import BASE
from tests.test_boat_venue_learning import POINTER, venue_data
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_observed_weight_learning import NOW


class CandidateRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *_: True)
        cls.owner = base64.b64encode(os.urandom(32)).decode()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='candidate-restore-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root/'runner'; self.base.mkdir(mode=0o700)
        self.output = self.base/'boat-venue-candidate-restore'
        self.env = dict(GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_RUN_ID='99',
                        GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40,
                        RACE_AI_CANDIDATE_RESTORE_REQUIRED='true')
        guard = patch.dict(os.environ, RACE_AI_STATE_KEY=self.owner)
        guard.start(); self.addCleanup(guard.stop)
        self.original = self.root/'original'
        seal_candidate(deepcopy(self.payload), self.original)
        self.git = MemoryGit()
        self.pointer = publish_learning_candidate(self.original, self.root, transport=self.git)
        self.config = dict(schema=runtime.SCHEMA, repository_id='1416489937', artifact_id=700,
                           training_sha256=self.payload['training']['training_sha256'],
                           head_sha='b'*40, run_id=98)
        self.config_path = self.root/'old-context.json'
        self.pointer_path = self.root/'retained.json'
        self.config_path.write_text(json.dumps(self.config))
        self.pointer_path.write_text(json.dumps(self.pointer))
        # Only invented crypto fixtures replace release pins; no production
        # data, key, artifact or GitHub call is used by these tests.
        for name, value in [('RETAINED_POINTER', self.pointer),
                            ('RECOVERY_TRAINING_SHA', self.config['training_sha256'])]:
            patcher = patch.object(runtime, name, value, create=True)
            patcher.start(); self.addCleanup(patcher.stop)
        self.calls = []

    def api(self, name):
        value = getattr(runtime, name, None)
        self.assertTrue(callable(value), 'same-candidate private restoration API is missing: '+name)
        return value

    def prepare(self, **kwargs):
        return self.api('restore_learning_context')(
            self.config_path, self.pointer_path, self.output, self.root,
            env=self.env, now=NOW, transport=self.git, **kwargs)

    def artifact(self, *, changed=None):
        contents={n:(self.original/n).read_bytes() for n in ('learning.enc','learning.json','summary.json')}
        if changed: contents.update(changed)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name, raw in contents.items():z.writestr(name,raw)
        raw=data.getvalue()
        metadata=dict(id=701,name='boat-venue-learning-99-1',expired=False,
                      size_in_bytes=len(raw),digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                      created_at=(NOW+timedelta(seconds=2)).isoformat(),
                      expires_at=(NOW+timedelta(days=7)).isoformat(),
                      workflow_run=dict(id=99,repository_id=1416489937,
                                        head_repository_id=1416489937,head_sha='a'*40))
        return raw, metadata

    def github(self, raw, metadata):
        def get(path):
            self.calls.append(path)
            if path=='actions/artifacts/701/zip':return raw
            if path=='actions/artifacts/701':return json.dumps(metadata).encode()
            self.fail('unexpected external route')
        return get

    def verify(self, raw=None, metadata=None):
        default_raw, default_metadata=self.artifact()
        return self.api('readback_learning_context')(
            self.config_path, self.pointer_path, self.output, 701, self.root,
            env=self.env, gh=self.github(raw or default_raw, metadata or default_metadata),
            clock=iter((NOW+timedelta(minutes=1),NOW+timedelta(minutes=1,seconds=1))).__next__)

    def selected(self, **kwargs):
        return self.api('select_learning_context')(
            self.config_path, self.base, env=self.env, now=NOW+timedelta(minutes=2), **kwargs)

    def test_exact_ciphertext_is_restored_without_fitting_or_mutating_original(self):
        before={n:(self.original/n).read_bytes() for n in ('learning.enc','learning.json','summary.json')}
        with patch('race_ai.observed_weight_learning.fit_from_verified',side_effect=AssertionError('no fitting')):
            result=self.prepare()
        self.assertEqual(result['state'],'SAME_CANDIDATE_RESTORED_PRIVATE_ONLY')
        self.assertFalse(result['external_receipt_verified'])
        self.assertEqual(read_candidate(self.output/'candidate'),self.payload)
        self.assertEqual({n:(self.output/'candidate'/n).read_bytes() for n in before},before)
        self.assertEqual({n:(self.original/n).read_bytes() for n in before},before)
        self.assertFalse((self.output/'ready.json').exists())
        with self.assertRaisesRegex(ValueError,'READY_REQUIRED'):self.selected()

    def test_actual_artifact_readback_creates_run_bound_private_override_only(self):
        self.prepare();result=self.verify()
        self.assertEqual(result['state'],'SAME_CANDIDATE_READY_VERIFIED')
        self.assertTrue(result['external_receipt_verified'])
        path=self.selected()
        value=json.loads(path.read_bytes())
        self.assertEqual(value,dict(self.config,artifact_id=701,run_id=99,head_sha='a'*40))
        self.assertEqual(json.loads(self.config_path.read_bytes()),self.config)
        self.assertEqual(self.calls,['actions/artifacts/701/zip','actions/artifacts/701'])
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertFalse(result['production_promoted'])
        self.assertNotIn('weights',json.dumps(result))

    def test_missing_key_rejects_before_reading_inputs_or_contacting_git(self):
        self.config_path.unlink();self.pointer_path.unlink()
        with patch.dict(os.environ,RACE_AI_STATE_KEY=''), \
             self.assertRaisesRegex(ValueError,'OWNER_STATE_KEY_REQUIRED'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_different_training_or_mutable_pointer_rejects_before_git_or_output(self):
        variants=[dict(self.config,training_sha256='f'*64)]
        for config in variants:
            self.config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'INTENDED_CANDIDATE'):self.prepare()
            self.assertFalse(self.output.exists())
        self.config_path.write_text(json.dumps(self.config))
        for field,value in [('source_commit','b'*40),('manifest_sha256','d'*64),
                            ('training_sha256','f'*64),('repository_id','1')]:
            with self.subTest(field=field):
                self.pointer_path.write_text(json.dumps(dict(self.pointer,**{field:value})))
                with self.assertRaisesRegex(ValueError,'RETAINED_PIN'):self.prepare()
                self.assertFalse(self.output.exists())

    def test_partial_existing_output_and_corrupt_cipher_do_not_produce_ready(self):
        self.output.mkdir(mode=0o700);(self.output/'partial').write_text('keep')
        with self.assertRaisesRegex(ValueError,'OUTPUT_EXISTS'):self.prepare()
        self.assertEqual((self.output/'partial').read_text(),'keep')
        (self.output/'partial').unlink();self.output.rmdir()
        prefix=self.pointer['manifest_path'].removesuffix('learning.json')
        self.git.trees[self.pointer['source_commit']][prefix+'learning.enc']+=b'changed'
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.output/'ready.json').exists())

    def test_changed_local_or_uploaded_candidate_bytes_reject_readback(self):
        self.prepare();target=self.output/'candidate'/'summary.json'
        target.write_bytes(target.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'RESTORED_BYTES'):self.verify()
        self.assertEqual(self.calls,[])
        target.write_bytes((self.original/'summary.json').read_bytes())
        raw,metadata=self.artifact(changed={'summary.json':target.read_bytes()+b' '})
        with self.assertRaisesRegex(ValueError,'ARTIFACT_BYTES'):self.verify(raw,metadata)
        self.assertFalse((self.output/'ready.json').exists())

    def test_foreign_run_head_name_expired_digest_and_old_save_time_reject(self):
        self.prepare();raw,original=self.artifact()
        changed=[]
        for field,value in [('name','boat-venue-learning-98-1'),('expired',True),
                            ('digest','sha256:'+'f'*64),('created_at',(NOW-timedelta(seconds=2)).isoformat())]:
            changed.append(dict(original,**{field:value}))
        for field,value in [('id',98),('head_sha','b'*40),('repository_id',1)]:
            v=deepcopy(original);v['workflow_run'][field]=value;changed.append(v)
        for value in changed:
            with self.subTest(metadata=value),self.assertRaises(ValueError):self.verify(raw,value)
            self.assertFalse((self.output/'ready.json').exists())

    def test_forged_ready_changed_config_and_other_worker_cannot_select_override(self):
        self.prepare();self.verify();path=self.selected()
        original=path.read_bytes();path.write_text(json.dumps(dict(self.config,artifact_id=999)))
        with self.assertRaisesRegex(ValueError,'READY'):self.selected()
        path.write_bytes(original)
        oldenv=self.env.copy();self.env['GITHUB_RUN_ID']='100'
        with self.assertRaisesRegex(ValueError,'READY'):self.selected()
        self.env=oldenv
        self.config_path.write_text(json.dumps(dict(self.config,artifact_id=999)))
        with self.assertRaisesRegex(ValueError,'READY'):self.selected()

    def test_absent_optional_override_keeps_legacy_and_required_mode_holds(self):
        with self.assertRaisesRegex(ValueError,'READY_REQUIRED'):self.selected()
        self.env.pop('RACE_AI_CANDIDATE_RESTORE_REQUIRED')
        self.assertEqual(self.selected(),self.config_path)

    def test_parent_symlink_cannot_redirect_private_candidate_restore(self):
        link=self.root/'redirect';link.symlink_to(self.base,target_is_directory=True)
        self.output=link/'boat-venue-candidate-restore'
        with self.assertRaisesRegex(ValueError,'PRIVATE_PATH'):self.prepare()
        self.assertFalse((self.base/'boat-venue-candidate-restore').exists())

    def test_forged_ready_mac_and_wrong_owner_key_reject_before_any_external_request(self):
        self.prepare();self.verify();self.calls.clear()
        ready=self.output/'ready.json';original=ready.read_bytes()
        record=json.loads(original);record['state']['config']['artifact_id']=999
        ready.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'READY_AUTHENTICATION'):self.selected()
        ready.write_bytes(original)
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()), \
             self.assertRaisesRegex(ValueError,'READY_AUTHENTICATION'):self.selected()
        self.assertEqual(self.calls,[])

    def test_existing_round_preloader_uses_ready_config_and_reverifies_new_artifact(self):
        from scripts import github_existing_cycle as cycle
        self.prepare();self.verify();self.calls.clear()
        repo=self.root/'repo';state=repo/'audit/state';state.mkdir(parents=True)
        (state/'boat-venue-learning-context-input.json').write_bytes(self.config_path.read_bytes())
        (state/'boat-venue-dataset-input.json').write_text(json.dumps(POINTER))
        raw,metadata=self.artifact()
        def dataset(pointer,output,_repo):
            self.assertEqual(pointer,POINTER)
            Path(output).mkdir(mode=0o700)
            return dict(status='ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED',plaintext_published=False)
        with patch.dict(os.environ,dict(self.env,RUNNER_TEMP=str(self.base))), \
             patch.object(cycle,'ROOT',repo),patch.object(cycle,'gh',side_effect=self.github(raw,metadata)), \
             patch.object(runtime,'readback_dataset',side_effect=dataset):
            loaded,error=cycle._venue_research_preload(round_no=1,clock=lambda:NOW+timedelta(minutes=2))
        self.assertIsNone(error)
        self.assertEqual(loaded['context']['receipt']['id'],701)
        self.assertEqual(self.calls,['actions/artifacts/701/zip','actions/artifacts/701'])

    def test_required_round_preload_without_ready_never_contacts_artifact_or_source(self):
        from scripts import github_existing_cycle as cycle
        repo=self.root/'repo';state=repo/'audit/state';state.mkdir(parents=True)
        (state/'boat-venue-learning-context-input.json').write_bytes(self.config_path.read_bytes())
        with patch.dict(os.environ,dict(self.env,RUNNER_TEMP=str(self.base))), \
             patch.object(cycle,'ROOT',repo),patch.object(cycle,'gh',side_effect=AssertionError('no external IO')):
            loaded,error=cycle._venue_research_preload(round_no=1)
        self.assertIsNone(loaded)
        self.assertEqual(error,'VENUE_RESEARCH_PRELOAD_REJECTED')

    def test_missing_ready_reports_challenger_hold_after_native_baseline_saved(self):
        from scripts import github_existing_cycle as cycle
        from tests.test_boat_venue_cycle_connection import PrivateVenueCycleTests
        repo=self.root/'repo';state=repo/'audit/state';state.mkdir(parents=True)
        (state/'boat-venue-learning-context-input.json').write_bytes(self.config_path.read_bytes())
        with patch.dict(os.environ,dict(self.env,RUNNER_TEMP=str(self.base))), \
             patch.object(cycle,'ROOT',repo),patch.object(cycle,'gh',side_effect=AssertionError('no old-artifact fallback')):
            loaded,error=cycle._venue_research_preload(round_no=1)
        self.assertIsNone(loaded)
        events,report=PrivateVenueCycleTests().run_cycle(preload_error=error)
        self.assertEqual(events,['fresh-baseline','private-preload'])
        self.assertEqual(len(report['observed_pairwise_p1_bundles']),1)
        self.assertEqual(report['venue_research_summary']['generated_races'],0)
        self.assertEqual(report['venue_research_summary']['reason'],'VENUE_RESEARCH_PRELOAD_REJECTED')

    def test_cli_emits_upload_ready_only_after_real_same_candidate_restore(self):
        from scripts import boat_venue_learning_handoff as cli
        original_restore=runtime.restore_learning_context
        def restore(*args,**kwargs):return original_restore(*args,**kwargs,transport=self.git)
        output=self.root/'github-output'
        with patch.dict(os.environ,dict(self.env,GITHUB_OUTPUT=str(output))), \
             patch.object(runtime,'restore_learning_context',side_effect=restore), \
             patch.object(cli,'datetime') as clock,contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value=NOW
            code=cli.main(['--repo',str(self.root),'restore-context','--context-input',str(self.config_path),
                           '--retained-input',str(self.pointer_path),'--out-dir',str(self.output)])
        self.assertEqual(code,0)
        self.assertTrue(output.exists(),'verified local ciphertext has no success-only upload gate')
        self.assertEqual(output.read_text(),'ready=true\n')


    def context_cli(self, command):
        from scripts import boat_venue_learning_handoff as cli
        argv=['--repo',str(self.root),command,'--context-input',str(self.config_path),
              '--retained-input',str(self.pointer_path),'--out-dir',str(self.output)]
        if command=='verify-context':argv.extend(['--artifact-id','701'])
        stream=io.StringIO()
        with patch.dict(os.environ,dict(self.env,GITHUB_OUTPUT=str(self.root/'cli-ready-output'))), \
             contextlib.redirect_stdout(stream):
            code=cli.main(argv)
        return code,json.loads(stream.getvalue())

    def test_cli_wrong_candidate_retains_fixed_reason_without_issuing_ready(self):
        self.config_path.write_text(json.dumps(dict(self.config,training_sha256='f'*64)))
        with patch.object(runtime,'restore_learning_candidate',side_effect=AssertionError('no Git')):
            code,status=self.context_cli('restore-context')
        self.assertEqual(code,2)
        self.assertEqual(status['reason'],'VENUE_RESEARCH_RUNTIME_INTENDED_CANDIDATE_REQUIRED')
        self.assertFalse((self.root/'cli-ready-output').exists())

    def test_cli_wrong_retained_pin_keeps_fixed_reason_without_git(self):
        self.pointer_path.write_text(json.dumps(dict(self.pointer,source_commit='f'*40)))
        with patch.object(runtime,'restore_learning_candidate',side_effect=AssertionError('no Git')):
            code,status=self.context_cli('restore-context')
        self.assertEqual(code,2)
        self.assertEqual(status['reason'],'VENUE_RESEARCH_RUNTIME_RETAINED_PIN_MISMATCH')
        self.assertFalse((self.root/'cli-ready-output').exists())

    def test_cli_foreign_new_receipt_keeps_fixed_identity_reason_and_no_ready(self):
        from scripts import github_existing_cycle as cycle
        self.prepare();raw,metadata=self.artifact();metadata['workflow_run']['head_sha']='b'*40
        original=runtime.readback_learning_context
        def with_clock(*args,**kwargs):
            return original(*args,**kwargs,clock=iter((NOW+timedelta(minutes=1),NOW+timedelta(minutes=2))).__next__)
        with patch.object(runtime,'readback_learning_context',side_effect=with_clock), \
             patch.object(cycle,'_live_gh',side_effect=self.github(raw,metadata)):
            code,status=self.context_cli('verify-context')
        self.assertEqual(code,2)
        self.assertEqual(status['reason'],'VENUE_RESEARCH_RUNTIME_CURRENT_ARTIFACT_IDENTITY_REQUIRED')
        self.assertFalse((self.output/'ready.json').exists())
        self.assertFalse((self.root/'cli-ready-output').exists())

    def test_cli_unknown_runtime_prefix_and_private_text_stay_sanitized(self):
        for error in (ValueError('VENUE_RESEARCH_RUNTIME_PRIVATE_SOURCE_DOCUMENT_SECRET'),
                      ValueError('VENUE_RESEARCH_RUNTIME_INTENDED_CANDIDATE_REQUIRED\nprivate source body'),
                      RuntimeError('VENUE_RESEARCH_RUNTIME_RETAINED_PIN_MISMATCH')):
            with self.subTest(error_type=type(error).__name__), \
                 patch.object(runtime,'restore_learning_context',side_effect=error):
                code,status=self.context_cli('restore-context')
            self.assertEqual(code,2)
            self.assertEqual(status['reason'],'VENUE_LEARNING_HANDOFF_REJECTED')
            self.assertNotIn('PRIVATE_SOURCE_DOCUMENT_SECRET',json.dumps(status))
            self.assertNotIn('private source body',json.dumps(status))


class CandidateRestoreEntryTests(unittest.TestCase):
    def test_missing_key_cli_stops_restore_and_verification_with_structured_hold(self):
        with tempfile.TemporaryDirectory() as temporary:
            for command in ('restore-context','verify-context'):
                output=Path(temporary)/command
                argv=[sys.executable,'-m','scripts.boat_venue_learning_handoff',command,'--out-dir',str(output)]
                if command=='verify-context':argv.extend(['--artifact-id','701'])
                env=dict(os.environ,RACE_AI_STATE_KEY='')
                result=subprocess.run(argv,capture_output=True,text=True,env=env)
                self.assertEqual(result.returncode,2)
                self.assertIn('HOLD_OWNER_STATE_KEY_MISSING',result.stdout)
                self.assertFalse(output.exists())

    def test_owner_challenger_failure_preserves_baseline_and_never_issues_ready(self):
        source=Path('.github/workflows/boat-nationwide-ab-one-shot.yml').read_text()
        owner=source.split('  official_national:',1)[1]
        blocks=re.split(r'(?=^      - name: )',owner,flags=re.MULTILINE)
        ids={re.search(r'^        id: ([a-z_]+)$',block,re.MULTILINE).group(1):block
             for block in blocks if re.search(r'^        id: ([a-z_]+)$',block,re.MULTILINE)}
        self.assertIn('venue_candidate_restore',ids,'owner has no exact-candidate restore gate')
        self.assertIn('venue_candidate_upload',ids)
        self.assertIn('venue_candidate_readback',ids)
        restore,upload,readback=(ids[k] for k in ('venue_candidate_restore','venue_candidate_upload','venue_candidate_readback'))
        self.assertLess(owner.index(restore),owner.index(upload))
        self.assertLess(owner.index(upload),owner.index(readback))
        self.assertLess(owner.index(readback),owner.index('first_p0_bootstrap.py capture'))
        self.assertIn("RACE_AI_CANDIDATE_RESTORE_REQUIRED: 'true'",owner.split('    steps:',1)[0])
        for block in (restore,upload,readback):
            self.assertIn('continue-on-error: true',block,'optional challenger failure must preserve baseline owner')
        self.assertNotIn('        if:',restore)
        self.assertIn("steps.venue_candidate_restore.outcome == 'success'",upload)
        self.assertIn("steps.venue_candidate_restore.outputs.ready == 'true'",upload)
        self.assertIn("steps.venue_candidate_upload.outcome == 'success'",readback)
        self.assertIn("steps.venue_candidate_upload.outputs.artifact-id != ''",readback)
        self.assertIn('restore-context',restore)
        self.assertIn('verify-context',readback)
        self.assertIn("steps.venue_candidate_upload.outputs.artifact-id",readback)
        self.assertIn('name: boat-venue-learning-${{ github.run_id }}-${{ github.run_attempt }}',upload)
        files=re.findall(r'^            (.+)$',upload,re.MULTILINE)
        self.assertEqual(set(files),{
            '${{ runner.temp }}/boat-venue-candidate-restore/candidate/learning.enc',
            '${{ runner.temp }}/boat-venue-candidate-restore/candidate/learning.json',
            '${{ runner.temp }}/boat-venue-candidate-restore/candidate/summary.json'})
        self.assertEqual(re.findall(r'^  ([a-z_]+):$',source.split('jobs:',1)[1],re.MULTILINE),
                         ['main_entry_contract','saved_view_publication','official_national'])


if __name__=='__main__':unittest.main()
