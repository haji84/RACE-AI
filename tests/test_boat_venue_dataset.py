"""Invented data: encrypted venue grid, missing values and as-of contracts."""
import base64,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_boat_venue_history_handoff import HandoffTests,MemoryGit

class VenueDatasetTests(HandoffTests):
    def test_all_month_heads_with_only_partial_day_cannot_claim_acquisition_complete(self):
        from race_ai.boat_venue_dataset import build_dataset,verify_dataset
        from tests.test_boat_entry_observations import uncompressed_lzh
        raw=uncompressed_lzh('STARTK\n01KBGN\nボートレース桐生\nデータは、この場の全レース終了後に登録されます。\n01KEND\nFINALK'.encode('cp932'),'K261104.TXT')
        root=self.collection(raw);out=self.root/'partial-dataset'
        with patch('race_ai.boat_venue_dataset._now',return_value='2030-01-02T00:00:00+00:00'):
            build_dataset(root,out,roster=['4999'],end='2026-11-04')
        self.assertFalse(verify_dataset(out)['acquisition_complete'])

    def test_encrypted_grid_roundtrip_and_capture_clock_cannot_be_backdated(self):
        from race_ai.boat_venue_dataset import build_dataset,verify_dataset,lookup
        root=self.collection();out=self.root/'dataset'
        with patch('race_ai.boat_venue_dataset._now',return_value='2030-01-02T00:00:00+00:00'):
            report=build_dataset(root,out,roster=['4999'],end='2026-11-04')
        self.assertEqual(report['grid_cells'],7*24)
        self.assertEqual(verify_dataset(out)['verified_cells'],7*24)
        p=lookup(out,'4001','17',as_of='2030-01-02T00:00:00+00:00')
        self.assertEqual(p['stats']['opportunities'],3)
        empty=lookup(out,'4999','17',as_of='2030-01-02T00:00:00+00:00')
        self.assertIsNone(empty['stats']['win_rate_numeric'])
        with self.assertRaises(ValueError):lookup(out,'4001','17',as_of='2026-11-05T00:00:00+00:00')
        self.assertFalse(any(out.rglob('*.sqlite')))
        from race_ai.boat_venue_dataset import publish_dataset,readback_dataset
        git=MemoryGit();pointer=publish_dataset(out,self.root,transport=git)
        restored=readback_dataset(pointer,self.root/'git-grid',self.root,transport=git)
        self.assertEqual(restored['verified_cells'],7*24)
        self.assertEqual(git.trees[git.current]['unrelated.enc'],b'preserve')
        manifest=json.loads((out/'dataset.json').read_text())
        part=out/manifest['state']['parts'][0]['path'];part.write_bytes(part.read_bytes()+b'corrupt')
        with self.assertRaises(ValueError):verify_dataset(out)
