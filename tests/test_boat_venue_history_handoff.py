"""Synthetic monthly source, owner encryption and append-only Git handoff."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_boat_history_catalog import index,menu
from tests.test_boat_venue_history import archive
from tests.test_boat_pdca_recipient import OWNER
import base64

class MemoryGit:
    def __init__(self):self.current='a'*40;self.trees={self.current:{'unrelated.enc':b'preserve'}}
    def head(self):return self.current
    def fetch(self,c):pass
    def exists(self,c,p):return p in self.trees[c]
    def read(self,c,p,limit):
        raw=self.trees[c][p];assert len(raw)<=limit;return raw
    def commit(self,files,parent):
        c=f'{len(self.trees):040x}';self.trees[c]=dict(self.trees[parent],**files);return c
    def push(self,c,parent):assert parent==self.current;self.current=c

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(OWNER).decode());self.env.start();self.addCleanup(self.env.stop)
    def collection(self,raw=None,day='2026-11-04'):
        from scripts.boat_venue_history import capture_month,_store_progress
        root=self.root/'source';root.mkdir()
        with patch('scripts.boat_venue_history._now',return_value='2030-01-01T00:00:02Z'),patch('scripts.boat_venue_history._http',side_effect=[(menu(),'2030-01-01T00:00:00Z'),(index(days=(day[-2:],)),'2030-01-01T00:00:00Z'),(archive(day=day) if raw is None else raw,'2030-01-01T00:00:01Z')]):
            r=capture_month(root/'202611/attempt-000001',month='202611',not_after=day)
        _store_progress(root,dict(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1',months=['202611'],menu_sha256='a'*64,
            captured_at='2030-01-01T00:00:00Z',not_after=day,heads={'202611':dict(kind='ENCRYPTED',folder='202611/attempt-000001',
            ciphertext_sha256=r['ciphertext_sha256'],attempt=1,generation=1,month_complete=r['catalog']['month_complete'])}))
        return root
    def test_publish_restore_and_repeat_keeps_other_state_and_original_cipher(self):
        from race_ai.boat_venue_history_handoff import publish_collection,readback_collection
        root=self.collection();git=MemoryGit()
        p=publish_collection(root,self.root,transport=git)
        self.assertEqual(git.trees[git.current]['unrelated.enc'],b'preserve')
        r=readback_collection(p,self.root/'restored',self.root,transport=git)
        self.assertEqual(r['parsed_days'],1);self.assertEqual(r['months_restored'],1)
        before=git.current;p2=publish_collection(root,self.root,transport=git)
        self.assertEqual(p,p2);self.assertEqual(git.current,before)
    def test_source_manifest_mac_and_remote_cipher_tampering_stop(self):
        from race_ai.boat_venue_history_handoff import publish_collection,readback_collection
        root=self.collection();git=MemoryGit();p=publish_collection(root,self.root,transport=git)
        c=next(k for k in git.trees[git.current] if k.endswith('history.checkpoint'))
        git.trees[git.current][c]+=b'bad'
        with self.assertRaises(ValueError):readback_collection(p,self.root/'bad',self.root,transport=git)
        record=json.loads((root/'collection.json').read_text());record['state']['heads']={};(root/'collection.json').write_text(json.dumps(record))
        with self.assertRaises(ValueError):publish_collection(root,self.root,transport=git)

    def test_prior_generation_chain_survives_remote_restore_and_resume(self):
        from scripts.boat_venue_history import capture_month,_store_progress
        from race_ai.boat_venue_history_handoff import publish_collection,readback_collection,_chain
        root=self.collection();record=json.loads((root/'collection.json').read_text());old=record['state']['heads']['202611']
        with patch('scripts.boat_venue_history._http',side_effect=AssertionError('no GET')):
            report=capture_month(root/'202611/attempt-000002',month='202611',resume=root/old['folder'],reparse_only=True)
        record['state']['heads']['202611']=dict(old,folder='202611/attempt-000002',generation=2,attempt=2,ciphertext_sha256=report['ciphertext_sha256'])
        _store_progress(root,record['state']);git=MemoryGit();p=publish_collection(root,self.root,transport=git)
        out=self.root/'all-generations';readback_collection(p,out,self.root,transport=git)
        chain=_chain(out,'202611',record['state']['heads']['202611']);self.assertEqual(len(chain),2)

    def test_authenticated_partial_source_does_not_become_complete_on_handoff(self):
        from race_ai.boat_venue_history_handoff import publish_collection,readback_collection
        from tests.test_boat_entry_observations import uncompressed_lzh
        raw=uncompressed_lzh('STARTK\n01KBGN\nボートレース桐生\nデータは、この場の全レース終了後に登録されます。\n01KEND\nFINALK'.encode('cp932'),'K261104.TXT')
        root=self.collection(raw);git=MemoryGit();p=publish_collection(root,self.root,transport=git)
        report=readback_collection(p,self.root/'partial-restored',self.root,transport=git)
        self.assertFalse(report['all_period_collection_complete'])
        self.assertEqual(report['partial_source_days'],1)

    def test_default_readback_uses_existing_bounded_blob_reader(self):
        from race_ai import boat_venue_history_handoff as api
        source=self.collection();git=MemoryGit();pointer=api.publish_collection(source,self.root,transport=git)
        with patch.object(api,'GitStateRepository',side_effect=AssertionError('full ancestry fetch is forbidden')),patch('race_ai.boat_private_original_vault.VaultGitRepository',return_value=git):
            result=api.readback_collection(pointer,self.root/'bounded-reader',self.root)
        self.assertEqual(result['months_restored'],1)
        self.assertEqual(result['parsed_days'],1)

    def test_default_grid_readback_uses_existing_bounded_blob_reader(self):
        from race_ai import boat_venue_dataset as api
        source=self.collection();grid=self.root/'bounded-grid-source'
        with patch.object(api,'_now',return_value='2030-01-01T00:00:04Z'):
            api.build_dataset(source,grid,end='2026-11-04')
        git=MemoryGit();pointer=api.publish_dataset(grid,self.root,transport=git)
        with patch.object(api,'GitStateRepository',side_effect=AssertionError('full ancestry fetch is forbidden')),patch('race_ai.boat_private_original_vault.VaultGitRepository',return_value=git):
            result=api.readback_dataset(pointer,self.root/'bounded-grid-reader',self.root)
        self.assertEqual(result['venues'],24)
        self.assertGreater(result['verified_cells'],0)
