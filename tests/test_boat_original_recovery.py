"""Closed-run recovery uses exact archived API bytes and no live fallback."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V
from tests import test_boat_private_original_vault as fixtures
KEY, HEAD, NOW, original, wire = fixtures.KEY, fixtures.HEAD, fixtures.NOW, fixtures.original, fixtures.wire

try:
    recovery = importlib.import_module('race_ai.boat_original_recovery')
except ModuleNotFoundError:
    recovery = None


def closed_run(*, status='completed'):
    return json.dumps(dict(id=2,status=status,conclusion='failure' if status == 'completed' else None,
        workflow_id=405276784,head_branch='feat/four-sport-forecast-audit-view-20261022',event='push',head_sha=HEAD,
        created_at='2030-04-01T01:00:00Z',updated_at='2030-04-01T04:00:00Z',run_attempt=1,
        repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937,full_name='haji84/RACE-AI')),indent=3).encode()+b'\n\n'


def page_responses(metadata, *, count=201):
    rows=[deepcopy(json.loads(metadata))]
    # Expiry is the listing's actual operational status; it must not be changed.
    rows[0]['expired']=True
    for ident in range(1000,1000+count-1):
        row=deepcopy(rows[0]);row.update(id=ident,name=f'fixture-source-code-{ident}')
        rows.append(row)
    return [(f'actions/runs/2/artifacts?per_page=100'+('' if page == 1 else f'&page={page}'),
             json.dumps(dict(total_count=count,artifacts=rows[(page-1)*100:page*100]),indent=2).encode()+b'\n')
            for page in range(1,(count+99)//100+1)]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(recovery,'closed-run original recovery is absent')
        self.fixture=fixtures.VaultTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.raw,self.metadata=original()
        self.original_locator=self.fixture.retain((self.raw,self.metadata))
        self.parent=self.original_locator['source_commit']
        self.run_raw=closed_run();self.pages=page_responses(self.metadata)

    def retain(self,**kwargs):
        return recovery.retain_closed_run_responses(kwargs.pop('run_raw',self.run_raw),kwargs.pop('pages',self.pages),
            self.fixture.writer.repo,expected_parent=kwargs.pop('expected_parent',self.parent),key=KEY,
            transport=self.fixture.writer,readback_transport=self.fixture.reader,now=kwargs.pop('now',NOW),**kwargs)

    def reader(self,get):
        return recovery.ArtifactRecovery(get,self.fixture.reader.repo,key=KEY,transport=self.fixture.reader)

    def remove_paths(self,parent,paths,files=None):
        git=self.fixture.writer
        with tempfile.TemporaryDirectory() as folder:
            env=dict(os.environ,GIT_INDEX_FILE=str(Path(folder)/'index'))
            git._run(['read-tree',parent],env=env)
            for path in paths:git._run(['update-index','--force-remove',path],env=env)
            for path,raw in (files or {}).items():
                blob=git._run(['hash-object','-w','--stdin'],body=raw,env=env).decode().strip()
                git._run(['update-index','--add','--cacheinfo','100644,'+blob+','+path],env=env)
            tree=git._run(['write-tree'],env=env).decode().strip()
        commit=git._run(['-c','user.name=fixture','-c','user.email=fixture@example.test',
            'commit-tree',tree,'-p',parent],body=b'fixture legacy catalog\n').decode().strip()
        git.push(commit,parent)
        return commit

    def test_closed_three_pages_and_expired_listing_restore_exact_metadata_zip_without_get(self):
        report=self.retain();calls=[]
        def denied(path):
            calls.append(path);raise RuntimeError('HTTP_410_HALT')
        reader=self.reader(denied)
        listed=reader.archived_artifact_pages(2)
        self.assertEqual(len(listed),201);self.assertEqual(listed[0],json.loads(self.metadata))
        self.assertIs(listed[0]['expired'],False)
        self.assertEqual(reader.provenance[101]['receipt_scope'],'ARCHIVED_AVAILABLE_ORIGINALS')
        self.assertIs(json.loads(reader(self.pages[0][0]))['artifacts'][0]['expired'],True)
        self.assertEqual(reader('actions/runs/2'),self.run_raw)
        for endpoint,raw in self.pages:self.assertEqual(reader(endpoint),raw)
        self.assertEqual(reader('actions/artifacts/101'),self.metadata)
        self.assertEqual(reader('actions/artifacts/101/zip'),self.raw)
        self.assertEqual(calls,[])
        self.assertEqual(reader.provenance['actions/artifacts/101']['receipt_scope'],'ARCHIVED_GITHUB_ARTIFACT_RESPONSE')
        self.assertTrue(report['complete'])

    def test_missing_catalog_selects_live_once_and_denial_never_reselects_archive(self):
        calls=[]
        def denied(path):calls.append(path);raise RuntimeError('HTTP_403_HALT')
        reader=self.reader(denied)
        self.assertIsNone(reader.archived_artifact_pages(2))
        with self.assertRaises(RuntimeError):reader('actions/runs/2/artifacts?per_page=100')
        self.retain()
        with self.assertRaises(RuntimeError):reader('actions/runs/2')
        self.assertEqual(calls,['actions/runs/2/artifacts?per_page=100','actions/runs/2'])

    def test_incomplete_duplicate_active_and_foreign_closures_reject_without_publication(self):
        duplicate=list(self.pages);duplicate[1]=(duplicate[1][0],duplicate[0][1])
        foreign=json.loads(self.run_raw);foreign['repository']['id']=1
        for run,pages in ((self.run_raw,self.pages[:-1]),(self.run_raw,duplicate),
                          (closed_run(status='in_progress'),self.pages),(wire(foreign),self.pages)):
            with self.subTest(run=len(run),pages=len(pages)),self.assertRaises(ValueError):
                self.retain(run_raw=run,pages=pages)
        self.assertEqual(self.fixture.writer.head(),self.parent)

    def test_same_exact_closed_state_is_idempotent_and_different_state_is_rejected(self):
        first=self.retain()
        second=self.retain(expected_parent=first['source_commit'],now=datetime(2030,4,1,12,1,tzinfo=timezone.utc))
        self.assertEqual(second['source_commit'],first['source_commit'])
        changed=json.loads(self.run_raw);changed['conclusion']='success'
        with self.assertRaises(ValueError):self.retain(run_raw=wire(changed),expected_parent=first['source_commit'])
        self.assertEqual(self.fixture.writer.head(),first['source_commit'])

    def test_missing_native_original_and_listing_identity_conflict_stop(self):
        bad=json.loads(self.pages[0][1]);bad['artifacts'][0]['digest']='sha256:'+'f'*64
        with self.assertRaises(ValueError):self.retain(pages=[(self.pages[0][0],wire(bad)),*self.pages[1:]])
        bad=json.loads(self.pages[0][1]);bad['artifacts'][0]['id']=102
        with self.assertRaises(ValueError):self.retain(pages=[(self.pages[0][0],wire(bad)),*self.pages[1:]])
        self.assertEqual(self.fixture.writer.head(),self.parent)

    def test_bad_catalog_and_missing_capture_bundle_raise_without_live_get(self):
        report=self.retain();path=report['catalog_path']
        broken=self.fixture.writer.commit({path:b'{"state":{},"mac":"'+b'0'*64+b'"}'},report['source_commit'])
        self.fixture.writer.push(broken,report['source_commit'])
        reader=self.reader(lambda _:self.fail('corrupt archive used live fallback'))
        with self.assertRaises(ValueError):reader.archived_artifact_pages(2)
        with self.assertRaises(ValueError):reader('actions/runs/2')

    def test_catalog_never_changes_noncanonical_actual_run_or_metadata_bytes(self):
        report=self.retain();reader=self.reader(lambda _:self.fail('live read'))
        self.assertEqual(reader('actions/runs/2'),self.run_raw)
        self.assertEqual(reader('actions/artifacts/101'),self.metadata)
        paths=self.fixture.writer._run(['ls-tree','-r','--name-only',report['source_commit']]).decode().splitlines()
        for path in paths:
            body=self.fixture.writer.read(report['source_commit'],path,8*1024*1024)
            self.assertNotIn(self.run_raw,body)

    def test_archived_freshness_exception_requires_completed_actual_vault_restore(self):
        reader=self.reader(lambda endpoint:b'live unchanged response')
        self.assertFalse(reader.is_archived(101))
        self.assertEqual(reader('actions/artifacts/101'),self.metadata)
        self.assertTrue(reader.is_archived(101))
        proof=reader.provenance[101]
        self.assertTrue(proof['authenticated_archive'])
        self.assertEqual(proof['metadata_response_sha256'],V._sha(self.metadata))
        self.assertEqual(proof['zip_sha256'],V._sha(self.raw))
        self.assertEqual(proof['locator']['artifact_id'],101)
        self.assertEqual(reader('actions/artifacts/999'),b'live unchanged response')
        self.assertFalse(reader.is_archived(999))

    def test_authenticated_catalog_with_missing_required_capture_entry_never_uses_live_get(self):
        report=self.retain();git=self.fixture.writer
        state=V._unsigned(git.read(report['source_commit'],report['catalog_path'],1024*1024),recovery._key(KEY))
        state['capture_locator']['entry_sha256']='f'*64
        raw=V._signed(state,recovery._key(KEY))
        selector_path='state/boat-original-recovery/v1/runs/2/latest.json'
        selector=V._unsigned(git.read(report['source_commit'],selector_path,16384),recovery._key(KEY))
        selector['catalog_sha256']=V._sha(raw)
        bad=git.commit({report['catalog_path']:raw,selector_path:V._signed(selector,recovery._key(KEY))},report['source_commit'])
        git.push(bad,report['source_commit'])
        reader=self.reader(lambda _:self.fail('missing required capture used live fallback'))
        with self.assertRaises(ValueError):reader.archived_artifact_pages(2)
        with self.assertRaises(ValueError):reader('actions/runs/2')

    def test_later_attempt_is_selected_without_replacing_the_first_attempt_bytes(self):
        first=self.retain();git=self.fixture.writer
        first_catalog=git.read(first['source_commit'],first['catalog_path'],1024*1024)
        raw,metadata=original(ident=102)
        value=json.loads(metadata);value['name']='boat-p0-existing-2-cycle-02';metadata=wire(value)
        saved=self.fixture.retain((raw,metadata),expected_parent=first['source_commit'])
        run=json.loads(self.run_raw);run['run_attempt']=2;run['updated_at']='2030-04-01T05:00:00Z'
        run_raw=wire(run)
        pages=[('actions/runs/2/artifacts?per_page=100',wire(dict(total_count=2,
            artifacts=[json.loads(self.metadata),value])))]
        try:second=self.retain(run_raw=run_raw,pages=pages,expected_parent=saved['source_commit'])
        except ValueError as exc:self.fail('later attempt was not retained: '+str(exc))
        self.assertNotEqual(first['catalog_path'],second['catalog_path'])
        self.assertEqual(git.read(second['source_commit'],first['catalog_path'],1024*1024),first_catalog)
        reader=self.reader(lambda _:self.fail('newest archived attempt used a live GET'))
        self.assertEqual(reader('actions/runs/2'),run_raw)
        self.assertEqual([row['id'] for row in reader.archived_artifact_pages(2)],[101,102])
        self.assertEqual(reader('actions/artifacts/102/zip'),raw)
        old=recovery._catalog(first_catalog,recovery._key(KEY))
        self.assertEqual(recovery._restore(old,git.repo,key=KEY,transport=git)['responses']['actions/runs/2'],self.run_raw)

    def test_descriptor_reserves_response_bytes_without_reading_any_chunks(self):
        self.retain();reader=self.reader(lambda _:self.fail('descriptor used a live GET'))
        self.assertTrue(callable(getattr(reader,'closed_run_descriptor',None)),
                        'closed-run descriptor API is missing')
        read=self.fixture.reader.read
        def descriptors_only(commit,path,limit):
            self.assertNotIn('/chunks/',path,'descriptor downloaded retained private bytes')
            return read(commit,path,limit)
        with patch.object(self.fixture.reader,'read',side_effect=descriptors_only):
            descriptor=reader.closed_run_descriptor(2)
        self.assertEqual(descriptor['state']['identity']['run_attempt'],1)
        self.assertEqual([item['artifact_id'] for item in descriptor['state']['originals']],[101])
        self.assertGreater(descriptor['capture_cipher_bytes'],descriptor['capture_plain_bytes'])
        self.assertGreater(descriptor['capture_plain_bytes'],len(self.run_raw))
        self.assertNotIn(self.run_raw,wire(descriptor))
        with patch.object(V,'restore_original',side_effect=AssertionError('closure check hydrated a native ZIP')):
            self.assertTrue(reader.has_closed_run(2))
        self.assertEqual(reader.artifacts.cache,{})

    def test_legacy_run_catalog_remains_readable_before_and_after_a_new_attempt(self):
        first=self.retain();git=self.fixture.writer
        raw=git.read(first['source_commit'],first['catalog_path'],1024*1024)
        legacy='state/boat-original-recovery/v1/runs/2.json'
        selector='state/boat-original-recovery/v1/runs/2/latest.json'
        parent=self.remove_paths(first['source_commit'],[selector,first['catalog_path']],{legacy:raw})
        reader=self.reader(lambda _:self.fail('legacy catalog used a live GET'))
        self.assertEqual(reader('actions/runs/2'),self.run_raw)
        changed=json.loads(self.run_raw);changed['run_attempt']=2
        try:second=self.retain(run_raw=wire(changed),expected_parent=parent)
        except ValueError as exc:self.fail('legacy catalog prevented a later attempt: '+str(exc))
        self.assertEqual(git.read(second['source_commit'],legacy,1024*1024),raw)
        reader=self.reader(lambda _:self.fail('new selector used a live GET'))
        self.assertEqual(json.loads(reader('actions/runs/2'))['run_attempt'],2)
        retry=self.retain(expected_parent=second['source_commit'])
        self.assertEqual(retry['source_commit'],second['source_commit'])
        changed=json.loads(self.run_raw);changed['conclusion']='success'
        with self.assertRaises(ValueError):
            self.retain(run_raw=wire(changed),expected_parent=second['source_commit'])
        self.assertEqual(git.head(),second['source_commit'])
        reader=self.reader(lambda _:self.fail('older retry changed the selected attempt'))
        self.assertEqual(json.loads(reader('actions/runs/2'))['run_attempt'],2)

    def test_selector_identity_or_catalog_hash_mismatch_stops_without_legacy_fallback(self):
        first=self.retain();git=self.fixture.writer
        path='state/boat-original-recovery/v1/runs/2/latest.json'
        self.assertTrue(git.exists(first['source_commit'],path),'authenticated latest-attempt selector is missing')
        selector=V._unsigned(git.read(first['source_commit'],path,16384),recovery._key(KEY))
        legacy='state/boat-original-recovery/v1/runs/2.json'
        original_catalog=git.read(first['source_commit'],first['catalog_path'],1024*1024)
        parent=first['source_commit']
        for field,value in (('catalog_sha256','f'*64),('run_attempt',2),('run_id',3),('catalog_path',legacy)):
            with self.subTest(field=field):
                state=dict(selector,**{field:value})
                commit=git.commit({path:V._signed(state,recovery._key(KEY)),legacy:original_catalog},parent)
                git.push(commit,parent);parent=commit
                reader=self.reader(lambda _:self.fail('invalid selector used a live GET'))
                with self.assertRaises(ValueError):reader.closed_run_descriptor(2)
                with self.assertRaises(ValueError):reader('actions/runs/2')


if __name__=='__main__':unittest.main()
