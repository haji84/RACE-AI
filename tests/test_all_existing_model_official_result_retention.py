"""Public fixture keys, actual RESULT codecs and in-memory transfer-ref CAS."""
import base64
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
import zipfile

from race_ai import all_existing_model_official_results as results
from race_ai import boat_all_model_store as store
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.manual_official_capture import official_rights_ref
from tests import test_all_existing_model_official_results as result_fixtures
from tests import test_autorace_official_result_adapter as auto

try:retention=importlib.import_module('race_ai.all_existing_model_result_retention')
except ModuleNotFoundError:retention=None
KEY=bytes(range(32))


class MemoryRemote:
    def __init__(self):
        self.head='f'*40
        self.trees={self.head:{'forecasts/latest.json':b'existing forecast pointer',
            'state/boat-private-originals/v1/lookup/1.json':b'existing authenticated bucket',
            'source/current.enc':b'active worker ciphertext'}}


class MemoryGit:
    def __init__(self,remote,repo):
        self.remote=remote;self.repo=repo;self.ref=TRANSFER_REF;self.objects={};self.commits=[];self.fetches=[]
    def head(self):return self.remote.head
    def fetch(self,commit):self.fetches.append(commit);self.objects[commit]=deepcopy(self.remote.trees[commit])
    def exists(self,commit,path):return path in self.objects[commit]
    def read(self,commit,path,limit):
        raw=self.objects[commit][path]
        if not 0<len(raw)<=limit:raise ValueError('fixture read bound')
        return raw
    def commit(self,files,parent):
        tree=dict(self.objects[parent],**files)
        commit=sha256(parent.encode()+b''.join(name.encode()+body for name,body in sorted(tree.items()))).hexdigest()[:40]
        self.objects[commit]=tree;self.commits.append(dict(files));return commit
    def push(self,commit,parent):
        if self.remote.head!=parent:raise ValueError('STATE_REF_CONCURRENT_UPDATE')
        self.remote.trees[commit]=deepcopy(self.objects[commit]);self.remote.head=commit


class OfficialResultRetentionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(retention,'result retention module is missing')
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.fixture=result_fixtures.OfficialResultsArchiveTests(methodName='runTest');self.fixture.setUp()
        self.raw,metadata=self.fixture.archive();self.metadata_raw=json.dumps(metadata,indent=3).encode()+b'\n\n'
        self.native=[self.fixture.native];self.now=self.fixture.now
        self.remote=MemoryRemote();self.writer=MemoryGit(self.remote,self.root/'writer')
        self.reader=MemoryGit(self.remote,self.root/'independent-object-database');self.parent=self.remote.head
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider/GitHub GET forbidden'))
        network.start();self.addCleanup(network.stop)
        process=patch('subprocess.run',side_effect=AssertionError('actual Git forbidden'))
        process.start();self.addCleanup(process.stop)

    def retain(self,raw=None,metadata_raw=None,frozen=None,**changes):
        options=dict(expected_parent=self.parent,key=KEY,transport=self.writer,readback_transport=self.reader,now=self.now)
        options.update(changes)
        return retention.retain(self.raw if raw is None else raw,self.metadata_raw if metadata_raw is None else metadata_raw,
            self.native if frozen is None else frozen,self.writer.repo,**options)

    def restore(self,pointer,**changes):
        options=dict(key=KEY,transport=self.reader);options.update(changes)
        return retention.restore(pointer,self.reader.repo,**options)

    def test_exact_roundtrip_after_expiry_preserves_entire_transfer_tree_and_no_public_labels(self):
        original=deepcopy(self.remote.trees[self.parent]);pointer=self.retain();restored=self.restore(pointer)
        self.assertEqual(pointer['ref'],TRANSFER_REF)
        prefix='state/all-existing-model-official-results/v1/'+sha256(self.raw).hexdigest()+'/'
        self.assertTrue(pointer['cipher_path'].startswith(prefix));self.assertNotIn('latest',pointer['cipher_path'])
        self.assertEqual((restored['raw_zip'],restored['metadata_raw']),(self.raw,self.metadata_raw))
        provenance=restored['provenance']
        self.assertEqual(provenance['current_artifact_status'],'NOT_QUERIED')
        self.assertFalse(provenance['github_artifact_receipt_created'])
        self.assertFalse(provenance['current_training_authorization_granted'])
        self.assertEqual(provenance['original_saved_at'],json.loads(self.metadata_raw)['created_at'])
        for name,body in original.items():self.assertEqual(self.remote.trees[pointer['source_commit']][name],body)
        self.assertEqual(len(self.writer.commits),1)
        self.assertTrue(all(name.startswith(prefix) for name in self.writer.commits[0]))
        public=json.dumps(pointer)
        for private in ('raw_base64','ordered_top3','roster','frozen_native_payloads','source_ref'):
            self.assertNotIn(private,public)
        with patch.object(retention,'utc_now',return_value=self.now+timedelta(days=30)):
            later=self.restore(pointer)
        self.assertEqual(later['metadata_raw'],self.metadata_raw)
        self.assertEqual(json.loads(later['metadata_raw'])['expires_at'],json.loads(self.metadata_raw)['expires_at'])

    def test_unchanged_retry_keeps_original_archive_clock_and_independently_reads_again(self):
        first=self.retain();fetches=len(self.reader.fetches)
        second=self.retain(expected_parent=first['source_commit'],now=self.now+timedelta(seconds=2))
        self.assertEqual(first,second);self.assertEqual(len(self.writer.commits),1)
        self.assertGreater(len(self.reader.fetches),fetches)
        path=first['cipher_path'];good=self.remote.trees[first['source_commit']][path]
        self.remote.trees[first['source_commit']][path]=good[:-1]+bytes([good[-1]^1])
        with self.assertRaises(ValueError):self.retain(expected_parent=first['source_commit'])
        self.assertEqual(len(self.writer.commits),1)

    def test_existing_exact_original_survives_additional_unrelated_admitted_native_inputs(self):
        first=self.retain();before=deepcopy(self.remote.trees[first['source_commit']])
        extra=deepcopy(self.native[0])
        extra['snapshot']['race']['race_id']='horse:2026-11-07:jra-03:10'
        # Another independently admitted race changes the current admission
        # context, not these exact RESULT ZIP/metadata original bytes.
        second=self.retain(frozen=self.native+[extra],expected_parent=first['source_commit'])
        self.assertEqual(second,first)
        self.assertEqual(self.remote.trees[first['source_commit']],before)
        self.assertEqual(len(self.writer.commits),1)
        self.assertEqual(self.restore(second)['raw_zip'],self.raw)

    def test_existing_full_result_original_keeps_original_mode_when_current_mode_is_order_only(self):
        first=self.retain(allow_order_only=False)
        second=self.retain(allow_order_only=True,expected_parent=first['source_commit'])
        self.assertEqual(second,first)
        self.assertEqual(len(self.writer.commits),1)
        restored=self.restore(second)
        self.assertFalse(restored['provenance']['original_allow_order_only'])
        self.assertEqual(restored['metadata_raw'],self.metadata_raw)

    def test_existing_original_still_requires_current_native_and_stored_admission_replay(self):
        pointer=self.retain();commit=pointer['source_commit'];path=pointer['cipher_path']
        changed=deepcopy(self.native)
        changed[0]['snapshot']['participants'][0]['identity']='jra:9999999999'
        with self.assertRaises(ValueError):
            self.retain(frozen=changed,expected_parent=commit)
        original=self.remote.trees[commit][path]
        payload=store.open_forecasts(original,key=KEY)
        payload['admission_receipt']['frozen_inputs_sha256']='0'*64
        self.remote.trees[commit][path]=store.seal_forecasts(payload,run_id='42',round_no=1,key=KEY)
        with self.assertRaisesRegex(ValueError,'ORIGINAL_ADMISSION_BINDING_INVALID'):
            self.retain(expected_parent=commit)
        self.assertEqual(len(self.writer.commits),1)

    def test_duplicate_native_inputs_are_deduplicated_without_mutating_callers(self):
        frozen=deepcopy(self.native)*5;before=deepcopy(frozen)
        pointer=self.retain(frozen=frozen)
        cipher=self.remote.trees[pointer['source_commit']][pointer['cipher_path']]
        payload=store.open_forecasts(cipher,key=KEY)
        self.assertEqual(len(payload['frozen_native_payloads']),1)
        self.assertEqual(frozen,before)
        self.assertEqual(self.restore(pointer)['raw_zip'],self.raw)

    def test_failed_fresh_readback_cannot_return_success_and_retry_keeps_original_bytes(self):
        original_read=self.reader.read
        def damaged(commit,path,limit):
            raw=original_read(commit,path,limit)
            return raw[:-1]+bytes([raw[-1]^1])
        with patch.object(self.reader,'read',side_effect=damaged),self.assertRaisesRegex(ValueError,'CIPHER_HASH_INVALID'):
            self.retain()
        self.assertEqual(len(self.writer.commits),1)
        pointer=self.retain(expected_parent=self.remote.head)
        self.assertEqual(len(self.writer.commits),1)
        self.assertEqual(self.restore(pointer)['metadata_raw'],self.metadata_raw)

    def test_same_zip_with_new_exact_receipt_appends_and_preserves_both(self):
        first=self.retain();metadata=json.loads(self.metadata_raw);metadata['id']=802
        second_raw=json.dumps(metadata,indent=2).encode()+b'\n'
        second=self.retain(metadata_raw=second_raw,expected_parent=first['source_commit'])
        self.assertNotEqual(first['cipher_path'],second['cipher_path'])
        self.assertEqual(first['original_zip_sha256'],second['original_zip_sha256'])
        self.assertEqual(self.restore(first)['metadata_raw'],self.metadata_raw)
        self.assertEqual(self.restore(second)['metadata_raw'],second_raw)
        self.assertEqual(len(self.writer.commits),2)

    def test_native_metadata_frozen_and_key_fail_before_any_publication(self):
        metadata=json.loads(self.metadata_raw)
        for change in (dict(expired=True),dict(digest='sha256:'+'a'*64),dict(size_in_bytes=1),
                       dict(expires_at=self.now.isoformat()),dict(created_at='2030-01-01T00:00:00Z')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.retain(metadata_raw=json.dumps(dict(metadata,**change)).encode())
        changed=deepcopy(self.native);changed[0]['snapshot']['participants'][0]['identity']='jra:9999999999'
        with self.assertRaises(ValueError):self.retain(frozen=changed)
        with self.assertRaises(ValueError):self.retain(key=bytes(reversed(range(32))))
        with self.assertRaises(ValueError):self.retain(allow_order_only=1)
        self.assertEqual(self.remote.head,self.parent);self.assertEqual(self.writer.commits,[])

    def test_wrong_pointer_cipher_and_independence_or_cas_fail_closed(self):
        with self.assertRaises(ValueError):self.retain(expected_parent='e'*40)
        with self.assertRaises(ValueError):self.retain(readback_transport=self.writer)
        self.writer.ref=store.FORECAST_REF
        with self.assertRaisesRegex(ValueError,'EXISTING_TRANSFER_REF_REQUIRED'):self.retain()
        self.writer.ref=TRANSFER_REF
        self.assertEqual(self.writer.commits,[])
        pointer=self.retain()
        for key,value in (('ref',store.FORECAST_REF),('cipher_sha256','e'*64),('metadata_sha256','d'*64),
                          ('cipher_path','forecasts/latest.json'),('archived_at','2030-01-01T00:00:00Z')):
            with self.subTest(key=key),self.assertRaises(ValueError):self.restore(dict(pointer,**{key:value}))
        with self.assertRaises(ValueError):self.restore(pointer,key=bytes(reversed(range(32))))

    def test_plain_backup_bound_rejects_without_truncating_or_pushing(self):
        native_plain=store.forecast_header(results._cipher(self.raw))['plain_size']
        with patch.object(store,'MAX_PLAIN',native_plain+1), \
                self.assertRaisesRegex(ValueError,'PLAIN_BOUND'):
            self.retain()
        self.assertEqual(self.remote.head,self.parent);self.assertEqual(self.writer.commits,[])

    def test_order_only_requires_original_explicit_flag_and_restore_replays_it(self):
        from race_ai.autorace_official_result_adapter import parse_result
        data=auto.fixture();data['metadata'].pop('auto_result_archive_context')
        raw=auto.wire(data['result']);frozen=[data['frozen']]
        observation=parse_result(raw,data['metadata'],frozen_native_payload=frozen[0],now=auto.NOW,
            source_rights_ref=official_rights_ref('autorace'),allow_order_only=True)
        self.assertEqual(observation['status'],'rank_confirmed')
        payload=results.build_result_payload([dict(raw_base64=base64.b64encode(raw).decode(),metadata=data['metadata'])],
            [observation],run_id=42,code_sha='a'*40,generated_at=auto.NOW,day_jst='2030-01-15',
            frozen_native_payloads=frozen,allow_order_only=True)
        cipher=results.seal_results(payload,round_no=1,frozen_native_payloads=frozen,key=KEY,allow_order_only=True)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        original=out.getvalue();metadata=json.loads(self.metadata_raw)
        metadata.update(size_in_bytes=len(original),digest='sha256:'+sha256(original).hexdigest(),
            created_at=(auto.NOW+timedelta(seconds=2)).isoformat(),expires_at=(auto.NOW+timedelta(days=7)).isoformat())
        encoded=json.dumps(metadata).encode();now=auto.NOW+timedelta(seconds=10)
        with self.assertRaises(ValueError):self.retain(original,encoded,frozen,now=now)
        pointer=self.retain(original,encoded,frozen,now=now,allow_order_only=True)
        restored=self.restore(pointer)
        self.assertEqual((restored['raw_zip'],restored['metadata_raw']),(original,encoded))
        self.assertTrue(restored['provenance']['original_allow_order_only'])
        self.assertFalse(restored['provenance']['current_training_authorization_granted'])
        with self.assertRaises(ValueError):
            self.retain(original,encoded,frozen,now=now,expected_parent=pointer['source_commit'])
        self.assertEqual(len(self.writer.commits),1)


if __name__=='__main__':unittest.main()
