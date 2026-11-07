"""Worker retention uses fictional keys, actual AES and in-memory Git only."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_all_existing_model_official_result_retention import MemoryRemote,MemoryGit,KEY
from tests import test_all_existing_model_official_results as result_fixture


class WorkerOfficialResultRetainTests(unittest.TestCase):
    def setUp(self):
        self.cli=importlib.import_module('scripts.all_existing_model_official_result_retain')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.root.chmod(0o700)
        fixture=result_fixture.OfficialResultsArchiveTests(methodName='runTest');fixture.setUp();self.fixture=fixture
        self.raw,self.metadata=fixture.archive();self.metadata_raw=json.dumps(self.metadata,indent=3).encode()+b'\n\n'
        self.pin=dict(id=801,digest=self.metadata['digest'],run_id=42,head_sha='a'*40)
        self.native_pin=dict(id=700,digest='sha256:'+'b'*64,run_id=41,head_sha='c'*40)
        self.manifest=dict(schema=self.cli.SCHEMA,native_artifacts=[self.native_pin],result_artifacts=[self.pin],allow_order_only=False)
        self.env=dict(run_id=501,head_sha='d'*40,temp=self.root)
        self.remote=MemoryRemote();self.writer=MemoryGit(self.remote,self.root/'writer');self.reader=MemoryGit(self.remote,self.root/'reader')
        setting=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),GITHUB_ACTIONS='true',
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='501',
            GITHUB_SHA='d'*40,RUNNER_TEMP=str(self.root))
        setting.start();self.addCleanup(setting.stop)
        forbid=patch('subprocess.run',side_effect=AssertionError('actual Git/network forbidden'));forbid.start();self.addCleanup(forbid.stop)

    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack();self.fetch=stack.enter_context(patch.object(self.cli.future,'gh',side_effect=lambda p:self.raw if p.endswith('/zip') else self.metadata_raw))
        self.current=stack.enter_context(patch.object(self.cli.future,'environment',return_value=self.env))
        self.natives=stack.enter_context(patch.object(self.cli.freeze,'frozen_inputs',return_value=[self.fixture.native]))
        stack.enter_context(patch.object(self.cli,'utc_now',return_value=self.fixture.now))
        self.auth=stack.enter_context(patch.object(self.cli,'git_auth'))
        return stack

    def run_retention(self,manifest=None,root=None):
        return self.cli.retain_manifest(self.manifest if manifest is None else manifest,self.root/'out' if root is None else root,
            self.env,transport=self.writer,readback_transport=self.reader)

    def test_manifest_exact_and_bounded_distinct_four_field_pins(self):
        self.assertEqual(self.cli.validate_manifest(self.manifest),self.manifest)
        for change in ({'extra':1},{'allow_order_only':1},{'result_artifacts':[]},
                       {'result_artifacts':[self.pin]*2},{'native_artifacts':[]},
                       {'native_artifacts':[dict(self.native_pin,head_sha='x'*40)]}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.cli.validate_manifest(dict(self.manifest,**change))

    def test_real_result_retained_exactly_and_authenticated_done_skips_all_external_work(self):
        original=deepcopy(self.remote.trees[self.remote.head])
        with self.patches():first=self.run_retention()
        self.assertTrue(first['ready']);self.assertEqual(first['retained_result_artifact_count'],1)
        pointer=first['pointers'][0]
        restored=self.cli.retention.restore(pointer,self.reader.repo,key=KEY,transport=self.reader)
        self.assertEqual((restored['raw_zip'],restored['metadata_raw']),(self.raw,self.metadata_raw))
        self.assertFalse(restored['provenance']['current_training_authorization_granted'])
        for name,value in original.items():self.assertEqual(self.remote.trees[self.remote.head][name],value)
        before={p.name:p.read_bytes() for p in (self.root/'out').iterdir()}
        with self.patches():
            self.fetch.side_effect=AssertionError('DONE must not fetch');self.natives.side_effect=AssertionError('DONE must not admit')
            self.current.side_effect=AssertionError('DONE must not query current run')
            second=self.run_retention()
            self.auth.assert_not_called()
        self.assertTrue(second['skipped']);self.assertEqual(len(self.writer.commits),1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'out').iterdir()})
        self.assertEqual({p.stat().st_mode&0o777 for p in (self.root/'out').iterdir()},{0o600})
        for secret in ('raw_zip','observations','ordered_top3','roster','source_ref'):self.assertNotIn(secret,json.dumps(first))

    def test_wrong_result_pin_is_rejected_before_zip_git_and_done_then_hold_does_not_retry(self):
        bad=deepcopy(self.manifest);bad['result_artifacts'][0]['digest']='sha256:'+'f'*64
        with self.patches(),self.assertRaises(ValueError):self.run_retention(bad)
        self.assertEqual(self.writer.commits,[])
        self.assertEqual(self.fetch.call_count,1)
        with self.patches():
            self.fetch.side_effect=AssertionError('held epoch must not retry');result=self.run_retention(bad)
        self.assertFalse(result['ready']);self.assertTrue(result['skipped'])
        self.assertFalse(any(p.name.startswith('done-') for p in (self.root/'out').iterdir()))

    def test_native_admission_failure_stops_before_result_download_or_state_access(self):
        with self.patches(),self.assertRaises(ValueError):
            self.natives.side_effect=ValueError('ALL_MODEL_PAIR_RECEIPT_PRE_CUTOFF_CLOCK_INVALID')
            self.run_retention()
        self.fetch.assert_not_called();self.auth.assert_not_called();self.assertEqual(self.writer.commits,[])

    def test_actual_result_run_head_repo_and_expiry_fail_before_zip_decryption(self):
        changes=[{'id':802},{'expired':True},{'expires_at':self.fixture.now.isoformat()},
                 {'workflow_run':dict(self.metadata['workflow_run'],head_sha='f'*40)},
                 {'workflow_run':dict(self.metadata['workflow_run'],id=43)},
                 {'workflow_run':dict(self.metadata['workflow_run'],repository_id=1)}]
        for index,change in enumerate(changes):
            with self.patches(),self.subTest(change=change),self.assertRaises(ValueError):
                self.fetch.return_value=json.dumps(dict(self.metadata,**change)).encode();self.fetch.side_effect=None
                self.run_retention(root=self.root/('bad-meta-'+str(index)))
            self.assertEqual(self.fetch.call_count,1)
        self.assertEqual(self.writer.commits,[])

    def test_done_mac_manifest_run_head_permissions_and_symlink_tamper_hold_closed(self):
        with self.patches():self.run_retention()
        marker=next((self.root/'out').glob('done-*.json'));saved=marker.read_bytes()
        for mutate in ('mac','head','mode','symlink'):
            marker.unlink();marker.write_bytes(saved);marker.chmod(0o600)
            if mutate in ('mac','head'):
                value=json.loads(saved)
                if mutate=='mac':value['mac']='0'*64
                else:value['state']['head_sha']='e'*40
                marker.write_text(json.dumps(value))
            if mutate=='mode':marker.chmod(0o644)
            if mutate=='symlink':
                outside=self.root/'other.json';outside.write_bytes(saved);outside.chmod(0o600);marker.unlink();marker.symlink_to(outside)
            with self.patches(),self.subTest(mutate=mutate),self.assertRaises(ValueError):self.run_retention()
            self.fetch.assert_not_called();self.current.assert_not_called()

    def test_two_results_chain_current_parent_and_keep_both_exact_metadata_originals(self):
        second_meta=dict(self.metadata,id=802);second_raw=json.dumps(second_meta,separators=(',',':')).encode()+b'\n'
        manifest=dict(self.manifest,result_artifacts=[self.pin,dict(self.pin,id=802)])
        def fetch(p):return self.raw if p.endswith('/zip') else second_raw if p.endswith('/802') else self.metadata_raw
        with self.patches():self.fetch.side_effect=fetch;status=self.run_retention(manifest)
        self.assertEqual(status['retained_result_artifact_count'],2);self.assertEqual(len(self.writer.commits),2)
        restored=[self.cli.retention.restore(p,self.reader.repo,key=KEY,transport=self.reader) for p in status['pointers']]
        self.assertEqual([r['metadata_raw'] for r in restored],[self.metadata_raw,second_raw])

    def test_failed_independent_readback_never_creates_done_or_retries_same_epoch(self):
        read=self.reader.read
        with self.patches(),patch.object(self.reader,'read',side_effect=lambda *a:read(*a)[:-1]+b'x'),self.assertRaises(ValueError):self.run_retention()
        self.assertEqual(len(self.writer.commits),1)
        self.assertFalse(any(p.name.startswith('done-') for p in (self.root/'out').iterdir()))
        with self.patches():self.fetch.side_effect=AssertionError('no automatic repeat after integrity failure');status=self.run_retention()
        self.assertFalse(status['ready']);self.assertTrue(status['skipped'])

    def test_done_write_failure_stays_hold_and_never_authenticates_success(self):
        write=self.cli._write_marker
        def failed(path,scope,key,kind,summary,now):
            if kind=='DONE':raise OSError('invented temporary filesystem failure')
            return write(path,scope,key,kind,summary,now)
        with self.patches(),patch.object(self.cli,'_write_marker',side_effect=failed),self.assertRaises(OSError):self.run_retention()
        with self.patches():
            self.fetch.side_effect=AssertionError('HOLD must not retry');status=self.run_retention()
        self.assertFalse(status['ready']);self.assertTrue(status['skipped'])

    def test_failure_after_done_bytes_are_written_keeps_hold_authoritative(self):
        write=self.cli._write_marker
        def failed(path,scope,key,kind,summary,now):
            value=write(path,scope,key,kind,summary,now)
            if kind=='DONE':raise OSError('invented post-write fsync failure')
            return value
        with self.patches(),patch.object(self.cli,'_write_marker',side_effect=failed),self.assertRaises(OSError):self.run_retention()
        self.assertTrue(any((self.root/'out').glob('done-*.json')))
        self.assertTrue(any((self.root/'out').glob('hold-*.json')))
        with self.patches():
            self.fetch.side_effect=AssertionError('HOLD must not retry');status=self.run_retention()
        self.assertFalse(status['ready']);self.assertTrue(status['skipped'])

    def test_key_and_local_actions_context_fail_before_api_git_or_private_output(self):
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps(self.manifest))
        for change in ({'RACE_AI_STATE_KEY':''},{'GITHUB_ACTIONS':'false'}):
            output=io.StringIO()
            with self.patches(),patch.dict(os.environ,change),redirect_stdout(output):self.cli.main(['--input',str(manifest),'--out-dir',str(self.root/'none')])
            self.fetch.assert_not_called();self.current.assert_not_called();self.assertFalse((self.root/'none').exists())
            self.assertFalse(json.loads(output.getvalue())['ready']);self.assertNotIn(str(self.root),output.getvalue())


if __name__=='__main__':unittest.main()
