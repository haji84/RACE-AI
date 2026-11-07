"""Count-only mirrors use invented controls, actual fixture receipts and local Git."""
import base64
from copy import deepcopy
from datetime import datetime,timezone
import importlib
import json
import os
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from race_ai import boat_private_original_vault as V,boat_original_recovery as R
from race_ai import boat_source_control as safe
from tests import test_boat_private_original_vault as fixtures
from tests import test_boat_source_control as safe_fixtures

try:mirror=importlib.import_module('race_ai.boat_source_control_mirror')
except ModuleNotFoundError:mirror=None

KEY=fixtures.KEY;HEAD=fixtures.HEAD;NOW=fixtures.NOW


def run_record(ident=7,head=HEAD,created='2030-04-01T01:00:00Z'):
    return dict(id=ident,head_sha=head,head_branch=R.BRANCH,workflow_id=R.WORKFLOW,status='completed',
        conclusion='success',created_at=created,updated_at='2030-04-01T03:00:00Z',run_attempt=1,event='push',
        repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(mirror,'durable count-only source-control mirror is absent')
        self.f=fixtures.VaultTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        _,self.continuity,self.continuity_meta,self.summary,self.control,self.control_meta=safe_fixtures.SafeSourceControlTests().fixture(
            private_rows=[dict(secret='DO_NOT_PUBLISH_NATIVE')],source_url='https://private.invalid/DO_NOT_PUBLISH_NATIVE')
        for metadata in (self.continuity_meta,self.control_meta):metadata['expires_at']='2030-04-08T03:00:00Z'
        self.run=run_record()
        self.responses={'actions/runs/7':V._wire(self.run),
            'actions/runs/7/artifacts?per_page=100':V._wire(dict(total_count=2,artifacts=[self.continuity_meta,self.control_meta])),
            'actions/artifacts/70':V._wire(self.continuity_meta),'actions/artifacts/70/zip':self.continuity,
            'actions/artifacts/71':V._wire(self.control_meta),'actions/artifacts/71/zip':self.control}
        self.requests=[]
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_RUN_ID='900',GITHUB_SHA=HEAD,
            RUNNER_TEMP=str(self.f.root),RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),
            GH_TOKEN='fixture-token-only-not-a-credential')

    def get(self,path):self.requests.append(path);return self.responses[path]

    def publish(self,**kwargs):
        with patch.dict(os.environ,self.env,clear=True):
            return mirror.publish_control(7,self.f.writer.repo,get=kwargs.pop('get',self.get),
                expected_parent=kwargs.pop('expected_parent',self.f.parent),key=KEY,transport=self.f.writer,
                readback_transport=self.f.reader,now=kwargs.pop('now',NOW),**kwargs)

    def test_publication_contains_only_whitelisted_counts_receipts_and_opaque_locators(self):
        report=self.publish();raw=self.f.writer.read(report['source_commit'],report['record_path'],32768)
        self.assertNotIn(b'DO_NOT_PUBLISH_NATIVE',raw);self.assertNotIn(b'private.invalid',raw)
        verified=mirror.verify_record(raw,run=self.run,key=KEY)
        state=verified['state']
        self.assertEqual(set(state['summary']),safe.ROOT_FIELDS)
        self.assertEqual(set(state['summary']['control']),safe.CONTROL_FIELDS)
        self.assertEqual(state['summary'],self.summary)
        self.assertEqual(state['source_control_receipt']['id'],71)
        self.assertEqual(state['continuity_receipt']['digest'],self.continuity_meta['digest'])
        self.assertEqual(state['source_head'],HEAD)
        self.assertTrue(verified['hmac_verified']);self.assertTrue(report['latest_advanced'])
        self.assertEqual(self.f.writer.read(report['source_commit'],'unrelated/retained.enc',100),b'existing ciphertext')

    def test_keyless_host_verifies_actual_run_scope_without_claiming_hmac_or_decryption(self):
        report=self.publish();raw=self.f.writer.read(report['source_commit'],report['record_path'],32768)
        with patch.dict(os.environ,{},clear=True):
            value=mirror.verify_record(raw,run=self.run,source_commit=report['source_commit'])
        self.assertFalse(value['hmac_verified']);self.assertFalse(value['cipher_binding_verified_by_reader'])
        for mutate in (lambda r:r.update(id=8),lambda r:r.update(head_sha='b'*40),
                       lambda r:r.update(status='in_progress'),lambda r:r.update(workflow_id=1),
                       lambda r:r.update(head_branch='main'),lambda r:r['repository'].update(id=1)):
            run=deepcopy(self.run);mutate(run)
            with self.subTest(run=run['id']),self.assertRaises(ValueError):
                mirror.verify_record(raw,run=run,source_commit=report['source_commit'])

    def test_tampered_summary_digest_receipt_head_and_hmac_are_rejected(self):
        report=self.publish();raw=self.f.writer.read(report['source_commit'],report['record_path'],32768)
        body=json.loads(raw);body['mac']='0'*64
        with self.assertRaises(ValueError):mirror.verify_record(V._wire(body)+b'\n',run=self.run,key=KEY)
        self.control_meta['digest']='sha256:'+'f'*64
        self.responses['actions/artifacts/71']=V._wire(self.control_meta)
        # Already retained originals stay authoritative; a different run head
        # cannot turn a valid archived pair into a new mirror.
        self.run['head_sha']='b'*40;self.responses['actions/runs/7']=V._wire(self.run)
        with self.assertRaises(ValueError):self.publish(expected_parent=report['source_commit'])

    def test_publication_is_create_only_idempotent_and_stale_parent_does_not_write(self):
        first=self.publish();second=self.publish(expected_parent=first['source_commit'])
        self.assertEqual(second['source_commit'],first['source_commit'])
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.f.writer.head(),first['source_commit'])

    def test_missing_pair_is_distinct_from_denial_and_active_run_cannot_publish(self):
        self.responses['actions/runs/7/artifacts?per_page=100']=V._wire(dict(total_count=1,artifacts=[self.continuity_meta]))
        with self.assertRaises(mirror.MissingControlPair):self.publish()
        def denied(path):raise RuntimeError('HTTP_403_HALT')
        with self.assertRaises(RuntimeError):self.publish(get=denied)
        self.run['status']='in_progress';self.responses['actions/runs/7']=V._wire(self.run)
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.f.writer.head(),self.f.parent)

    def test_expired_pair_replays_from_vault_and_closed_responses_before_any_get(self):
        retained=V.retain_originals([
            (self.continuity,V._wire(self.continuity_meta)),
            dict(raw_zip=self.control,metadata_raw=V._wire(self.control_meta),
                 companion=(self.continuity,V._wire(self.continuity_meta)))],self.f.writer.repo,
            expected_parent=self.f.parent,key=KEY,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        closed=R.retain_closed_run_responses(V._wire(self.run),[
            ('actions/runs/7/artifacts?per_page=100',self.responses['actions/runs/7/artifacts?per_page=100'])],
            self.f.writer.repo,expected_parent=retained['source_commit'],key=KEY,transport=self.f.writer,
            readback_transport=self.f.reader,now=NOW)
        def denied(_):self.fail('archived pair attempted live GET')
        report=self.publish(expected_parent=closed['source_commit'],get=denied,
                            now=datetime(2030,4,20,12,tzinfo=timezone.utc))
        self.assertEqual(report['source_run_id'],7)

    def test_latest_closed_skips_missing_pair_but_never_denial(self):
        self.responses['actions/workflows/405276784/runs?per_page=16&status=completed']=V._wire(
            dict(total_count=2,workflow_runs=[run_record(8,created='2030-04-01T02:00:00Z'),self.run]))
        self.responses['actions/runs/8']=V._wire(run_record(8,created='2030-04-01T02:00:00Z'))
        self.responses['actions/runs/8/artifacts?per_page=100']=V._wire(dict(total_count=0,artifacts=[]))
        with patch.dict(os.environ,self.env,clear=True):
            report=mirror.publish_latest_closed(self.f.writer.repo,get=self.get,expected_parent=self.f.parent,
                key=KEY,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        self.assertEqual(report['source_run_id'],7);self.assertEqual(report['skipped_missing_pairs'],[8])
        self.assertLessEqual(report['scanned_closed_runs'],16)

    def add_run_pair(self,run_id):
        from tests.test_continuity_checkpoint import session
        cipher=V.native.seal_original_zip(fixtures.packed({'repeat-session.json':session(run_id=run_id)}),
            run_id=run_id,head_sha=HEAD,kind='CONTINUITY',key=KEY)
        continuity=fixtures.packed({'private-original.enc':cipher})
        summary=safe.build_summary(cipher,run_id=run_id,head_sha=HEAD,key=KEY)
        control=fixtures.packed({'source-control.json':V._wire(summary)})
        run=run_record(run_id,created='2030-04-01T02:00:00Z')
        values=[]
        for role,raw,ident,created in [('race-cycle-continuity',continuity,run_id*10,'2030-04-01T02:30:00Z'),
                                       ('race-source-control',control,run_id*10+1,'2030-04-01T02:30:01Z')]:
            metadata=dict(id=ident,name=f'{role}-{run_id}',expired=False,created_at=created,
                expires_at='2030-04-08T03:00:00Z',digest='sha256:'+V._sha(raw),size_in_bytes=len(raw),
                workflow_run=dict(id=run_id,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD))
            values.append(metadata);self.responses[f'actions/artifacts/{ident}']=V._wire(metadata)
            self.responses[f'actions/artifacts/{ident}/zip']=raw
        self.responses[f'actions/runs/{run_id}']=V._wire(run)
        self.responses[f'actions/runs/{run_id}/artifacts?per_page=100']=V._wire(dict(total_count=2,artifacts=values))

    def test_backfill_keeps_newer_latest_and_detects_corrupt_existing_latest_record(self):
        first=self.publish();self.add_run_pair(8)
        with patch.dict(os.environ,self.env,clear=True):
            newer=mirror.publish_control(8,self.f.writer.repo,get=self.get,expected_parent=first['source_commit'],
                key=KEY,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        latest=self.f.writer.read(newer['source_commit'],mirror.LATEST,32768)
        older=self.publish(expected_parent=newer['source_commit'])
        self.assertFalse(older['latest_advanced'])
        self.assertEqual(self.f.writer.read(older['source_commit'],mirror.LATEST,32768),latest)
        bad=self.f.writer.commit({newer['record_path']:b'corrupt public record'},older['source_commit'])
        self.f.writer.push(bad,older['source_commit'])
        with self.assertRaises(ValueError):self.publish(expected_parent=bad)

    def test_latest_closed_denial_stops_before_an_older_pair_and_publication_requires_actions(self):
        self.responses['actions/workflows/405276784/runs?per_page=16&status=completed']=V._wire(
            dict(workflow_runs=[run_record(8,created='2030-04-01T02:00:00Z'),self.run]))
        self.responses['actions/runs/8']=V._wire(run_record(8,created='2030-04-01T02:00:00Z'))
        def denied(path):
            if path.startswith('actions/runs/8/artifacts'):raise RuntimeError('HTTP_403_HALT')
            return self.get(path)
        with patch.dict(os.environ,self.env,clear=True),self.assertRaises(RuntimeError):
            mirror.publish_latest_closed(self.f.writer.repo,get=denied,expected_parent=self.f.parent,
                key=KEY,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        self.assertNotIn('actions/runs/7',self.requests)
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):
            mirror.publish_control(7,self.f.writer.repo,get=self.get,expected_parent=self.f.parent,key=KEY,
                transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        self.assertEqual(self.f.writer.head(),self.f.parent)

    def test_mirror_does_not_download_unrelated_forecast_documents(self):
        unrelated=deepcopy(self.continuity_meta);unrelated.update(id=72,name='boat-p0-existing-7')
        self.responses['actions/runs/7/artifacts?per_page=100']=V._wire(
            dict(total_count=3,artifacts=[unrelated,self.continuity_meta,self.control_meta]))
        self.publish()
        self.assertFalse(any(path.startswith('actions/artifacts/72') for path in self.requests))

    def test_latest_closed_cli_exposes_the_exact_bounded_command(self):
        try:cli=importlib.import_module('scripts.boat_source_control_mirror')
        except ModuleNotFoundError:cli=None
        self.assertIsNotNone(cli,'count mirror CLI is absent')
        self.responses['actions/workflows/405276784/runs?per_page=16&status=completed']=V._wire(
            dict(workflow_runs=[self.run]))
        output=io.StringIO();path=self.f.root/'mirror-report.json'
        with patch.dict(os.environ,self.env,clear=True),redirect_stdout(output):
            result=cli.main(['latest-closed','--repo-root',str(self.f.writer.repo),'--output',str(path)],
                get=self.get,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        self.assertEqual(result,0,output.getvalue())
        self.assertEqual(json.loads(path.read_bytes())['source_run_id'],7)

    def test_independent_source_readback_rejects_different_public_counts(self):
        report=self.publish()
        state=json.loads(self.f.writer.read(report['source_commit'],report['record_path'],32768))['state']
        state['summary']['control']['requests_used']+=1
        safe.validate_summary(state['summary'])
        with self.assertRaises(ValueError):mirror._readback_sources(state,self.f.reader,KEY)

    def test_rerun_cannot_publish_old_attempt_pair_before_a_first_mirror_exists(self):
        self.run['run_attempt']=2;self.responses['actions/runs/7']=V._wire(self.run)
        with self.assertRaisesRegex(ValueError,'CONTROL_MIRROR_ATTEMPT_PROVENANCE_UNAVAILABLE'):
            self.publish()
        self.assertEqual(self.f.writer.head(),self.f.parent)
        self.assertFalse(self.f.writer.exists(self.f.parent,mirror.LATEST))
        self.assertFalse(any(path.endswith('/zip') for path in self.requests))

    def test_rerun_preserves_existing_mirror_and_keyless_verifier_holds(self):
        first=self.publish();raw=self.f.writer.read(first['source_commit'],first['record_path'],32768)
        self.run['run_attempt']=2;self.responses['actions/runs/7']=V._wire(self.run)
        with self.assertRaisesRegex(ValueError,'CONTROL_MIRROR_ATTEMPT_PROVENANCE_UNAVAILABLE'):
            self.publish(expected_parent=first['source_commit'])
        with self.assertRaisesRegex(ValueError,'CONTROL_MIRROR_ATTEMPT_PROVENANCE_UNAVAILABLE'):
            mirror.verify_record(raw,run=self.run,source_commit=first['source_commit'])
        self.assertEqual(self.f.writer.head(),first['source_commit'])
        self.assertEqual(self.f.writer.read(first['source_commit'],first['record_path'],32768),raw)

    def test_latest_closed_current_rerun_holds_before_cached_attempt_one_can_publish(self):
        # Current listing metadata is an independent warning even when the
        # archive layer has a completed attempt-one response for that run ID.
        current=deepcopy(self.run);current['run_attempt']=2
        self.responses['actions/workflows/405276784/runs?per_page=16&status=completed']=V._wire(
            dict(workflow_runs=[current]))
        with patch.dict(os.environ,self.env,clear=True),self.assertRaisesRegex(ValueError,
                'CONTROL_MIRROR_ATTEMPT_PROVENANCE_UNAVAILABLE'):
            mirror.publish_latest_closed(self.f.writer.repo,get=self.get,expected_parent=self.f.parent,
                key=KEY,transport=self.f.writer,readback_transport=self.f.reader,now=NOW)
        self.assertEqual(self.f.writer.head(),self.f.parent)


if __name__=='__main__':unittest.main()
