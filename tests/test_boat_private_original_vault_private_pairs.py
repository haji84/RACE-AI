"""Public fixture keys and invented native originals; no provider requests."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_private_original_vault as vault
from race_ai.actions_contract import digest
from race_ai.all_existing_model_learning import fit
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.all_existing_model_receipt import verify_private_pairs_artifact
from race_ai.boat_venue_learning import seal_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.four_sport_model_suite import ALL_MODELS
from tests.test_all_existing_model_learning import observed_records
from tests.test_all_existing_model_matrix import native_payload
from tests import test_all_existing_model_pairs as pair_fixtures

FORECAST_NOW=pair_fixtures.FORECAST_NOW
HEAD=pair_fixtures.HEAD
NOW=pair_fixtures.NOW

KEY=bytes(range(32))


def packed(members):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,body in members.items():archive.writestr(name,body)
    return out.getvalue()


class MemoryRemote:
    """A fixture for existing CAS/readback interfaces, without local Git refs."""
    def __init__(self):
        self.current='f'*40
        self.objects={self.current:{'unrelated/kept.enc':b'earlier ciphertext'}}


class MemoryVault:
    def __init__(self,remote,repo):self.remote=remote;self.repo=repo;self.ref=vault.VAULT_REF;self.objects={}
    def head(self):return self.remote.current
    def fetch(self,commit):self.objects[commit]=deepcopy(self.remote.objects[commit])
    def exists(self,commit,path):return path in self.objects[commit]
    def read(self,commit,path,limit):
        raw=self.objects[commit][path]
        if len(raw)>limit:raise ValueError('fixture read bound')
        return raw
    def commit(self,files,parent):
        tree=dict(self.objects[parent],**files)
        commit=sha256(parent.encode()+b''.join(name.encode()+body for name,body in sorted(tree.items()))).hexdigest()[:40]
        self.objects[commit]=tree;return commit
    def push(self,commit,parent):
        if self.remote.current!=parent:raise ValueError('STATE_REF_CONCURRENT_UPDATE')
        self.remote.objects[commit]=deepcopy(self.objects[commit]);self.remote.current=commit


class PrivatePairsVaultTests(unittest.TestCase):
    native=pair_fixtures.AllExistingModelPrivatePairsTests.native
    extra_native_requests=pair_fixtures.AllExistingModelPrivatePairsTests.extra_native_requests

    @classmethod
    def setUpClass(cls):
        source=observed_records();mid=source[0]['model_id']
        cls.records=[row for row in source if row['model_id']==mid]
        cls.training=fit(cls.records,now=NOW);cls.cell=next(iter(cls.training['models']))

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        environment=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment.start();self.addCleanup(environment.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider/GitHub GET forbidden'))
        network.start();self.addCleanup(network.stop)
        process=patch.object(vault.VaultGitRepository,'_run',side_effect=AssertionError('no Git mutation in this fixture'))
        process.start();self.addCleanup(process.stop)
        candidate=self.root/'candidate'
        seal_candidate(dict(training=deepcopy(self.training),excluded=[],summary=dict(
            state=self.training['state'],fitted_model_count=1,production_promoted=False,
            actual_purchases=False,plaintext_published=False)),candidate)
        raw=packed({name:(candidate/name).read_bytes() for name in ('learning.json','learning.enc','summary.json')})
        metadata=dict(id=700,name='all-existing-model-learning-99-1',expired=False,size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(),created_at=(NOW+timedelta(seconds=2)).isoformat(),
            expires_at=(NOW+timedelta(days=7)).isoformat(),workflow_run=dict(id=99,repository_id=1416489937,
            head_repository_id=1416489937,head_sha=HEAD))
        self.context=context_from_encrypted_artifact(raw,700,now=FORECAST_NOW,_fetch=lambda _:deepcopy(metadata))
        self.remote=MemoryRemote();self.writer=MemoryVault(self.remote,self.root/'writer')
        self.reader=MemoryVault(self.remote,self.root/'independent-reader');self.parent=self.remote.current

    def artifact(self,*,input_only=False):
        if input_only:
            requests=[]
            for number in range(1,9):
                native=native_payload(ALL_MODELS[0],'horse')
                snapshot=native['snapshot'];race=snapshot['race']
                race.update(race_id=f'horse:2030-04-01:fictional-track:{number}',event_date_jst='2030-04-01',
                    as_of=(FORECAST_NOW-timedelta(seconds=1)).isoformat(),
                    sales_cutoff_at=(FORECAST_NOW+timedelta(minutes=20+number)).isoformat())
                for mid in (*ALL_MODELS,LEARNED_ID):
                    requests.append(dict(cell_key='horse/'+mid,native_payload=deepcopy(native)))
        else:
            from race_ai.boat_observed_pairwise_models import MODEL_IDS
            requests=self.extra_native_requests()+[dict(cell_key='boat/'+mid,native_payload=self.native()) for mid in MODEL_IDS]
        folder=self.root/('input-only' if input_only else 'forecast')
        summary=make_private_pairs(self.context,requests,folder,now=FORECAST_NOW)
        members={part.name+'/'+name:(part/name).read_bytes() for part in folder.iterdir() if part.is_dir()
                 for name in ('learning.json','learning.enc','summary.json')}
        raw=packed(members)
        metadata=dict(id=800 if input_only else 801,name='all-existing-model-pairs-99-900002',expired=False,
            size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(FORECAST_NOW+timedelta(seconds=3)).isoformat(),expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=99,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD))
        # Retention must preserve even the original metadata serialization.
        return raw,json.dumps(metadata,indent=3).encode()+b'\n\n',members,summary

    def retain(self,raw,metadata_raw,**changes):
        args=dict(expected_parent=self.parent,key=KEY,transport=self.writer,readback_transport=self.reader,
                  now=FORECAST_NOW+timedelta(hours=1),expected_kind='PRIVATE_PAIRS')
        args.update(changes)
        return vault.retain_original(raw,metadata_raw,self.writer.repo,**args)

    def test_forecast_and_five_retained_inputs_roundtrip_with_no_owner_environment_key(self):
        raw,metadata_raw,_,summary=self.artifact()
        self.assertEqual((summary['forecast_partition_count'],summary['captured_native_input_count']),(1,5))
        with patch.dict(os.environ):
            os.environ.pop('RACE_AI_STATE_KEY',None)
            locator=self.retain(raw,metadata_raw)
            restored=vault.restore_original(locator,self.reader.repo,key=KEY,transport=self.reader)
            self.assertNotIn('RACE_AI_STATE_KEY',os.environ)
        self.assertEqual(locator['kind'],'PRIVATE_PAIRS');self.assertEqual(locator['ref'],vault.VAULT_REF)
        self.assertEqual((restored['raw_zip'],restored['metadata_raw']),(raw,metadata_raw))
        self.assertEqual(restored['provenance']['current_artifact_status'],'NOT_QUERIED')
        self.assertEqual(vault.lookup_original(801,self.reader.repo,key=KEY,transport=self.reader),locator)

    def test_eight_input_only_races_forty_native_capsules_preserve_exact_originals(self):
        raw,metadata_raw,_,summary=self.artifact(input_only=True)
        self.assertEqual((summary['forecast_partition_count'],summary['frozen_input_only_partition_count'],
                          summary['captured_native_input_count']),(0,8,40))
        admitted=verify_private_pairs_artifact(raw,json.loads(metadata_raw),now=FORECAST_NOW+timedelta(hours=1),
            expected_run_id=99,expected_head_sha=HEAD)
        self.assertEqual(admitted['captured_native_input_count'],40)
        locator=self.retain(raw,metadata_raw)
        restored=vault.restore_original(locator,self.reader.repo,key=KEY,transport=self.reader)
        self.assertEqual(restored['raw_zip'],raw);self.assertEqual(restored['metadata_raw'],metadata_raw)
        for name,body in self.remote.objects[locator['source_commit']].items():
            self.assertNotIn('original.zip',name)
            self.assertNotIn(b'"native_payload"',body);self.assertNotIn(b'"ordered_top8"',body)
            self.assertNotIn(b'"parameters"',body)
        self.assertEqual(self.remote.objects[locator['source_commit']]['unrelated/kept.enc'],b'earlier ciphertext')

    def test_wrong_names_metadata_and_late_upload_never_publish(self):
        raw,metadata_raw,_,_=self.artifact()
        original=json.loads(metadata_raw)
        changes=[dict(name='all-existing-model-pairs-99-0'),dict(name='all-existing-model-pairs-99-01'),
            dict(name='all-existing-model-pairs-99-1-extra'),dict(name='all-existing-model-pairs-98-1'),
            dict(digest='sha256:'+'f'*64),dict(expired=True),dict(size_in_bytes=len(raw)+1),
            dict(created_at=(FORECAST_NOW+timedelta(minutes=20)).isoformat()),
            dict(workflow_run=dict(original['workflow_run'],repository_id=1)),
            dict(workflow_run=dict(original['workflow_run'],head_sha='INVALID'))]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.retain(raw,json.dumps(dict(original,**change)).encode())
            self.assertEqual(self.remote.current,self.parent)

    def test_native_cipher_tamper_is_rejected_even_with_recomputed_outer_digest(self):
        raw,metadata_raw,members,_=self.artifact(input_only=True)
        member=next(name for name in members if name.endswith('/learning.enc'))
        damaged=dict(members);damaged[member]=damaged[member][:-1]+bytes([damaged[member][-1]^1])
        raw=packed(damaged);metadata=json.loads(metadata_raw)
        metadata.update(size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        with patch.dict(os.environ,RACE_AI_STATE_KEY='fictional-prior-environment-value'):
            with self.assertRaises(ValueError):self.retain(raw,json.dumps(metadata).encode())
            self.assertEqual(os.environ['RACE_AI_STATE_KEY'],'fictional-prior-environment-value')
        self.assertEqual(self.remote.current,self.parent)

    def test_input_only_upload_after_any_capsule_cutoff_is_rejected(self):
        raw,metadata_raw,_,_=self.artifact(input_only=True)
        metadata=json.loads(metadata_raw)
        # The first race cutoff is 21 minutes; every capsule must precede it.
        metadata['created_at']=(FORECAST_NOW+timedelta(minutes=21)).isoformat()
        with self.assertRaisesRegex(ValueError,'CAPTURED_INPUT_PRE_CUTOFF_CLOCK_INVALID'):
            self.retain(raw,json.dumps(metadata).encode())
        self.assertEqual(self.remote.current,self.parent)

    def test_private_pairs_never_satisfies_another_requested_kind(self):
        raw,metadata_raw,_,_=self.artifact()
        with self.assertRaisesRegex(ValueError,'ARTIFACT_KIND_INVALID'):
            self.retain(raw,metadata_raw,expected_kind='ALL_MODEL')
        self.assertEqual(self.remote.current,self.parent)

    def test_archived_receipt_replays_at_original_admission_time_after_expiry(self):
        raw,metadata_raw,_,_=self.artifact(input_only=True)
        locator=self.retain(raw,metadata_raw)
        with self.assertRaises(ValueError):
            self.retain(raw,metadata_raw,expected_parent=locator['source_commit'],now=NOW+timedelta(days=8))
        restored=vault.restore_original(locator,self.reader.repo,key=KEY,transport=self.reader)
        self.assertEqual(restored['metadata_raw'],metadata_raw)
        self.assertEqual(restored['metadata']['expires_at'],json.loads(metadata_raw)['expires_at'])
        self.assertEqual(restored['provenance']['receipt_scope'],'ARCHIVED_GITHUB_ARTIFACT_RESPONSE')

# Independent local-Git mixed-bucket, catalog and pre-publication regressions.
from race_ai import boat_private_original_vault as V, boat_original_recovery as R
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
