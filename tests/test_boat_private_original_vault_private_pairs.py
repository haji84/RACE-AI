"""Known native pair containers interoperate with immutable boat-only state."""
import base64
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V,boat_original_recovery as R
from tests import test_boat_private_original_vault as F
from tests import test_all_existing_model_pairs as native_fixtures
from tests.test_boat_original_recovery import closed_run


class PrivatePairVaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):native_fixtures.AllExistingModelPrivatePairsTests.setUpClass()

    def setUp(self):
        self.f=F.VaultTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.native=native_fixtures.AllExistingModelPrivatePairsTests();self.native.setUp();self.addCleanup(self.native.doCleanups)
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(F.KEY).decode()):
            self.native.make()
        self.raw,self.members=self.native.archive();self.metadata=self.native.metadata(self.raw)

    def retain(self,raw=None,metadata=None,*,parent=None,key=F.KEY):
        return V.retain_original(self.raw if raw is None else raw,
            F.wire(self.metadata if metadata is None else metadata),self.f.writer.repo,
            expected_parent=self.f.parent if parent is None else parent,key=key,
            transport=self.f.writer,readback_transport=self.f.reader,now=F.NOW)

    def test_native_pair_original_restores_exact_bytes_and_unchanged_retry_is_independent(self):
        locator=self.retain();self.assertEqual(locator['kind'],'PRIVATE_PAIRS')
        before=self.f.writer.head()
        retried=self.retain(parent=before);self.assertEqual(self.f.writer.head(),before)
        self.assertEqual(retried['source_commit'],before)
        with patch('urllib.request.urlopen',side_effect=AssertionError('HTTP during restore')):
            restored=V.restore_original(locator,self.f.reader.repo,key=F.KEY,transport=self.f.reader)
        self.assertEqual(restored['raw_zip'],self.raw);self.assertEqual(restored['metadata_raw'],F.wire(self.metadata))
        self.assertEqual(restored['metadata']['created_at'],self.metadata['created_at'])

    def test_mixed_lookup_bucket_and_legacy_boat_closure_keep_exact_scope_without_get(self):
        p0=self.f.retain();metadata=deepcopy(self.metadata)
        metadata.update(id=102,name='all-existing-model-pairs-2-1');metadata['workflow_run']['id']=2
        run=json.loads(closed_run());run['updated_at']='2030-04-01T11:00:00Z'
        page=F.wire(dict(total_count=2,artifacts=[json.loads(F.original()[1]),metadata]))
        self.assertIsNone(R._native_kind(metadata['name'],2),'boat closure scope expanded to cross-sport pairs')
        closure=R.retain_closed_run_responses(F.wire(run),[('actions/runs/2/artifacts?per_page=100',page)],
            self.f.writer.repo,expected_parent=p0['source_commit'],key=F.KEY,
            transport=self.f.writer,readback_transport=self.f.reader,now=F.NOW)
        pair=self.retain(metadata=metadata,parent=closure['source_commit']);calls=[]
        def denied(endpoint):calls.append(endpoint);raise AssertionError('cached state used live GET')
        recovery=R.ArtifactRecovery(denied,self.f.reader.repo,key=F.KEY,transport=self.f.reader)
        rows=recovery.archived_artifact_pages(2)
        self.assertEqual(len(rows),2);self.assertEqual(rows[1],metadata);self.assertEqual(calls,[])
        reader=V.VaultArtifactReader(denied,self.f.reader.repo,key=F.KEY,transport=self.f.reader)
        self.assertEqual(reader('actions/artifacts/101/zip'),F.original()[0])
        self.assertEqual(reader('actions/artifacts/102/zip'),self.raw);self.assertEqual(calls,[])
        self.assertEqual(self.f.writer.head(),pair['source_commit'])

    def test_pair_cipher_sidecar_and_late_receipt_tampering_hold_before_publication(self):
        encrypted=next(name for name in self.members if name.endswith('/learning.enc'))
        changed=dict(self.members);body=bytearray(changed[encrypted]);body[-1]^=1;changed[encrypted]=bytes(body)
        bad=self.native.zip_members(changed);metadata=deepcopy(self.metadata)
        metadata.update(size_in_bytes=len(bad),digest='sha256:'+V._sha(bad))
        with self.assertRaises(ValueError):self.retain(bad,metadata)
        changed=dict(self.members);sidecar=next(name for name in changed if name.endswith('/summary.json'))
        value=json.loads(changed[sidecar]);value['baseline_forecast_count']+=1;changed[sidecar]=F.wire(value)
        bad=self.native.zip_members(changed);metadata=deepcopy(self.metadata)
        metadata.update(size_in_bytes=len(bad),digest='sha256:'+V._sha(bad))
        with self.assertRaises(ValueError):self.retain(bad,metadata)
        metadata=deepcopy(self.metadata);metadata['created_at']='2030-04-01T09:00:00Z'
        with self.assertRaises(ValueError):self.retain(metadata=metadata)
        with self.assertRaises(ValueError):self.retain(key=b'x'*32)
        self.assertEqual(self.f.writer.head(),self.f.parent)

    def test_only_the_exact_existing_native_pair_artifact_family_is_admitted(self):
        valid='all-existing-model-pairs-99-1'
        self.assertEqual(V._kind(dict(name=valid,workflow_run=dict(id=99))),'PRIVATE_PAIRS')
        for name in ('all-existing-model-pairs-98-1','all-existing-model-pairs-99-0',
                     'all-existing-model-pairs-99-01',valid+'-extra','private-pairs-99-1'):
            metadata=deepcopy(self.metadata);metadata['name']=name
            with self.subTest(name=name),self.assertRaises(ValueError):self.retain(metadata=metadata)
        metadata=deepcopy(self.metadata);metadata['workflow_run']['repository_id']=1
        with self.assertRaises(ValueError):self.retain(metadata=metadata)
        self.assertEqual(self.f.writer.head(),self.f.parent)

    def test_an_unknown_reference_kind_still_holds_before_any_live_get(self):
        locator=self.f.retain();path=V._lookup_path(101)
        value=V._unsigned(self.f.writer.read(locator['source_commit'],path,V.MAX_INDEX),V._keys(F.KEY)[1])
        value['entries']['101']['kind']='UNSUPPORTED'
        bad=self.f.writer.commit({path:V._signed(value,V._keys(F.KEY)[1])},locator['source_commit'])
        self.f.writer.push(bad,locator['source_commit'])
        reader=V.VaultArtifactReader(lambda _:self.fail('invalid known state used GET'),self.f.reader.repo,
            key=F.KEY,transport=self.f.reader)
        with self.assertRaisesRegex(ValueError,'VAULT_REFERENCE_KIND_INVALID'):reader('actions/artifacts/101/zip')

    def test_internal_unsupported_record_cannot_publish_an_unreadable_index(self):
        record=dict(files={'original.zip':F.original()[0],'metadata.json':F.original()[1]},
            summary=dict(kind='UNSUPPORTED',artifact_id=101,run_id=2,head_sha=F.HEAD,
                created_at='2030-04-01T01:43:00Z',month='2030-04'))
        with self.assertRaises(ValueError):
            V._retain([record],self.f.writer.repo,expected_parent=self.f.parent,key=F.KEY,
                transport=self.f.writer,readback_transport=self.f.reader,now=F.NOW)
        self.assertEqual(self.f.writer.head(),self.f.parent,'unsupported record was pushed before validation')


if __name__=='__main__':unittest.main()
