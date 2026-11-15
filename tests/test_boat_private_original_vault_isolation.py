"""New vault writers cannot race legacy source workers on the transfer ref."""
from pathlib import Path
import os
import subprocess
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V
from race_ai.boat_pdca_github_handoff import GitStateRepository,TRANSFER_REF
from tests import test_boat_private_original_vault as F
from tests import test_boat_private_original_vault_cli as C

NEW_REF='state/boat-private-originals'


class VaultIsolationTests(unittest.TestCase):
    def setUp(self):
        self.f=F.VaultTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def isolated(self):
        writer=F.LocalGit(self.f.writer.repo)
        self.assertEqual(writer.ref,NEW_REF,'default vault still writes the active legacy transfer ref')
        writer.push(self.f.parent,None)
        reader=self.f.git('isolated-reader',ref=NEW_REF)
        return writer,reader

    def test_default_vault_is_isolated_from_a_foreign_legacy_source_writer(self):
        writer,reader=self.isolated()
        foreign=self.f.writer.commit({'venue/current.enc':b'active source ciphertext'},self.f.parent)
        self.f.writer.push(foreign,self.f.parent)
        locator=V.retain_original(*F.original(),writer.repo,expected_parent=self.f.parent,key=F.KEY,
            transport=writer,readback_transport=reader,now=F.NOW)
        self.assertEqual(locator['ref'],NEW_REF)
        self.assertEqual(self.f.writer.head(),foreign)
        self.assertEqual(self.f.writer.read(foreign,'venue/current.enc',100),b'active source ciphertext')
        self.assertEqual(V.restore_original(locator,reader.repo,key=F.KEY,transport=reader)['raw_zip'],F.original()[0])
        with self.assertRaises(ValueError):GitStateRepository(writer.repo,ref=NEW_REF)

    def test_literal_legacy_locator_restores_after_zero_copy_new_ref_seed(self):
        legacy=self.f.retain();self.assertEqual(legacy['ref'],TRANSFER_REF)
        writer=F.LocalGit(self.f.writer.repo);self.assertEqual(writer.ref,NEW_REF)
        writer.push(legacy['source_commit'],None)
        reader=self.f.git('new-ref-readback',ref=NEW_REF)
        newer=V.retain_original(*F.original(ident=102,run=3),writer.repo,expected_parent=legacy['source_commit'],
            key=F.KEY,transport=writer,readback_transport=reader,now=F.NOW)
        self.assertEqual(newer['ref'],NEW_REF)
        self.assertEqual(V._validate_locator(legacy),legacy)
        self.assertEqual(V.restore_original(legacy,reader.repo,key=F.KEY,transport=reader)['metadata_raw'],F.original()[1])
        self.assertEqual(self.f.writer.head(),legacy['source_commit'])

    def test_missing_new_ref_holds_without_automatic_initialization(self):
        writer=F.LocalGit(self.f.writer.repo);self.assertEqual(writer.ref,NEW_REF)
        reader=self.f.git('missing-new-ref-reader',ref=NEW_REF)
        with self.assertRaises(ValueError):
            V.retain_original(*F.original(),writer.repo,expected_parent=self.f.parent,key=F.KEY,
                transport=writer,readback_transport=reader,now=F.NOW)
        self.assertIsNone(writer.head())
        with self.assertRaises(ValueError):V.refresh_parent(writer,self.f.parent)

    def test_refresh_proves_descendants_from_shallow_commit_headers_without_blobs(self):
        writer,reader=self.isolated();head=self.f.parent
        for number in range(3):
            child=writer.commit({f'other/{number}.json':b'actual concurrent metadata'},head)
            writer.push(child,head);head=child
        self.assertEqual(V.refresh_parent(reader,self.f.parent),head)
        self.assertEqual(V.refresh_parent(reader,head),head)
        oid=writer._run(['rev-parse',self.f.parent+':unrelated/retained.enc']).decode().strip()
        result=subprocess.run(['git','-C',str(reader.repo),'cat-file','-e',oid],
            env=dict(os.environ,GIT_NO_LAZY_FETCH='1'),capture_output=True)
        self.assertNotEqual(result.returncode,0,'parent refresh downloaded unrelated ciphertext')
        foreign=writer.commit({'different-root.enc':b'ciphertext'},None)
        with self.assertRaisesRegex(ValueError,'VAULT_PARENT_REFRESH_ANCESTRY_UNVERIFIED'):
            V.refresh_parent(reader,foreign)

    def test_refresh_stops_after_64_commit_headers(self):
        writer,reader=self.isolated();head=self.f.parent
        for number in range(65):head=writer.commit({'other/progress.json':str(number).encode()},head)
        writer.push(head,self.f.parent)
        with self.assertRaisesRegex(ValueError,'VAULT_PARENT_REFRESH_ANCESTRY_UNVERIFIED'):
            V.refresh_parent(reader,self.f.parent)


class VaultCaptureRefreshTests(unittest.TestCase):
    def setUp(self):
        self.f=C.VaultCliTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.raw,self.metadata=F.original()
        self.responses={'actions/artifacts/101':self.metadata,'actions/artifacts/101/zip':self.raw,
            'actions/runs/2':F.wire(dict(id=2,head_sha=F.HEAD,workflow_id=405276784,
                head_branch='feat/four-sport-forecast-audit-view-20261022',
                repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937,full_name='haji84/RACE-AI')))}

    def test_current_capture_refreshes_after_metadata_get_without_repeating_gets(self):
        calls=[];foreign=[]
        def get(path):
            calls.append(path)
            if path.endswith('/zip'):
                child=self.f.writer.commit({'other/live.enc':b'concurrent ciphertext'},self.f.parent)
                self.f.writer.push(child,self.f.parent);foreign.append(child)
            return self.responses[path]
        code,report=self.f.run_cli(['capture','--artifact','101','--expected-parent','current'],get=get)
        self.assertEqual(code,0,report)
        self.assertEqual(len(calls),3);self.assertEqual(len(set(calls)),3)
        self.assertEqual(self.f.writer.read(report['source_commit'],'other/live.enc',100),b'concurrent ciphertext')

    def test_capture_retries_only_known_cas_three_times_with_identical_get_bytes(self):
        calls=[];races=[];real_push=self.f.writer.push
        def get(path):calls.append(path);return self.responses[path]
        def racing_push(commit,parent):
            if len(races)<2:
                foreign=self.f.writer.commit({'other/race.json':str(len(races)).encode()},parent)
                real_push(foreign,parent);races.append(foreign)
            return real_push(commit,parent)
        with patch.object(self.f.writer,'push',side_effect=racing_push):
            code,report=self.f.run_cli(['capture','--artifact','101','--expected-parent','current'],get=get)
        self.assertEqual(code,0,report);self.assertEqual(len(races),2)
        self.assertEqual(len(calls),3)

    def test_capture_stops_after_third_known_cas_without_repeating_gets(self):
        calls=[];races=[];real_push=self.f.writer.push
        def get(path):calls.append(path);return self.responses[path]
        def racing_push(commit,parent):
            foreign=self.f.writer.commit({'other/race.json':str(len(races)).encode()},parent)
            real_push(foreign,parent);races.append(foreign)
            return real_push(commit,parent)
        with patch.object(self.f.writer,'push',side_effect=racing_push):
            code,_=self.f.run_cli(['capture','--artifact','101','--expected-parent','current'],get=get)
        self.assertEqual(code,2);self.assertEqual(len(races),3);self.assertEqual(len(calls),3)
        self.assertIsNone(V.lookup_original(101,self.f.writer.repo,key=F.KEY,transport=self.f.writer))

    def test_explicit_parent_is_strict_and_unknown_write_failure_never_retries(self):
        calls=[]
        def get(path):
            calls.append(path)
            if path.endswith('/zip'):
                child=self.f.writer.commit({'other/live.enc':b'concurrent ciphertext'},self.f.parent)
                self.f.writer.push(child,self.f.parent)
            return self.responses[path]
        with patch.object(V,'refresh_parent',side_effect=AssertionError('strict capture refreshed')):
            code,_=self.f.run_cli(['capture','--artifact','101','--expected-parent',self.f.parent],get=get)
        self.assertEqual(code,2);self.assertEqual(len(calls),3)
        for message in ('STATE_GIT_OPERATION_FAILED','GITHUB_API_READ_HTTP_403_HALT','VAULT_CHUNK_HASH_INVALID'):
            with self.subTest(message=message),patch.object(self.f.writer,'push',side_effect=ValueError(message)) as push:
                code,_=self.f.run_cli(['capture','--artifact','101','--expected-parent','current'],
                    get=lambda path:self.responses[path])
                self.assertEqual(code,2);self.assertEqual(push.call_count,1)

    def test_all_cached_capture_independently_detects_a_corrupt_remote_cipher(self):
        first=V.retain_original(self.raw,self.metadata,self.f.writer.repo,expected_parent=self.f.parent,key=F.KEY,
            transport=self.f.writer,readback_transport=self.f.reader,now=F.NOW)
        paths=self.f.writer._run(['ls-tree','-r','--name-only',first['source_commit']]).decode().splitlines()
        chunk=next(path for path in paths if '/chunks/' in path)
        good=self.f.writer.read(first['source_commit'],chunk,8*1024*1024)
        bad=self.f.writer.commit({chunk:b'corrupt remote cipher'},first['source_commit']);self.f.writer.push(bad,first['source_commit'])
        real_read=self.f.writer.read
        def producer_cache(commit,path,limit):return good if path==chunk else real_read(commit,path,limit)
        with patch.dict(os.environ,self.f.env,clear=True),patch.object(self.f.writer,'read',side_effect=producer_cache),self.assertRaises(ValueError):
            C.cli._capture([101],self.f.writer.repo,bad,self.f.writer,self.f.reader,
                lambda _:self.fail('cached entry made a GitHub GET'),F.NOW)

    def test_mixed_cached_and_new_locators_are_verified_at_the_same_commit(self):
        first=V.retain_original(self.raw,self.metadata,self.f.writer.repo,expected_parent=self.f.parent,key=F.KEY,
            transport=self.f.writer,readback_transport=self.f.reader,now=F.NOW)
        raw,metadata=F.original(ident=102,run=2)
        responses=dict(self.responses,**{'actions/artifacts/102':metadata,'actions/artifacts/102/zip':raw})
        calls=[]
        def get(path):calls.append(path);return responses[path]
        with patch.dict(os.environ,self.f.env,clear=True):
            report=C.cli._capture([101,102],self.f.writer.repo,first['source_commit'],self.f.writer,self.f.reader,get,F.NOW)
        self.assertEqual(len(calls),3);self.assertEqual({item['artifact_id'] for item in report['locators']},{101,102})
        self.assertEqual({item['source_commit'] for item in report['locators']},{report['source_commit']})
        for locator in report['locators']:
            restored=V.restore_original(locator,self.f.reader.repo,key=F.KEY,transport=self.f.reader)
            self.assertEqual(restored['raw_zip'],self.raw if locator['artifact_id']==101 else raw)


if __name__=='__main__':unittest.main()
