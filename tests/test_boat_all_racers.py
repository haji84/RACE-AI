"""Offline CLI: fictional data, absent-key stops, encrypted restore contracts."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from scripts.boat_all_racers import inspect_files,capture,restore_checkpoint
from tests.test_boat_racer_database import term_archive

class BulkCLITests(unittest.TestCase):
    def test_actual_file_interface_counts_all_and_contains_no_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'term.lzh';p.write_bytes(term_archive())
            report=inspect_files(p)
            self.assertEqual(report['population']['term_racers'],2)
            self.assertEqual(report['lookup_verified_racers'],2)
            self.assertEqual(report['zero_national_sample_racers'],0)
            self.assertEqual(report['zero_course_sample_rows'],0)
            self.assertNotIn('racers',report);self.assertNotIn('架空',str(report))
            self.assertTrue(report['serialized_readback_verified'])
            self.assertFalse(report['durable_encrypted_storage_verified'])
    def test_missing_owner_key_causes_no_get_and_no_ciphertext(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),patch('scripts.boat_all_racers._download',side_effect=AssertionError('unexpected upstream GET')):
            result=capture(Path(folder))
            self.assertEqual(result['status'],'HOLD_OWNER_STATE_KEY_MISSING')
            self.assertEqual(result['upstream_gets'],0)
            self.assertFalse((Path(folder)/'racers.checkpoint').exists())
    def test_invalid_or_public_fixture_key_is_stopped_before_get(self):
        import base64,hashlib
        public=base64.b64encode(hashlib.sha256(b'RACE_AI_PUBLIC_SYNTHETIC_FIXTURE_KEY_V1_NOT_FOR_REAL_DATA').digest()).decode()
        for key in ('bad',public):
            with self.subTest(keylen=len(key)),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}),patch('scripts.boat_all_racers._download',side_effect=AssertionError('unexpected GET')):
                with self.assertRaises(ValueError):capture(Path(folder))
    def test_synthetic_encrypted_sqlite_restore_uses_existing_generic_codec(self):
        import json,subprocess
        from race_ai.boat_racer_database import RacerDatabase
        from race_ai.boat_racer_term import term_info
        from datetime import datetime,timezone
        import hashlib
        db=RacerDatabase();now=datetime.now(timezone.utc).isoformat()
        db.import_term(term_archive(),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=now)
        raw=db.serialize()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'plain.sqlite').write_bytes(raw)
            scope=dict(schema='RACE_AI_GITHUB_SQLITE_V1',repository_id='1416489937',mode='synthetic',generation=1,previous_cipher_sha256=None)
            (p/'scope.json').write_text(json.dumps(scope))
            proc=subprocess.run(['node','scripts/keirin_github_checkpoint.mjs','seal',str(p/'plain.sqlite'),str(p/'racers.checkpoint'),str(p/'scope.json')],capture_output=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            cipher=(p/'racers.checkpoint').read_bytes();self.assertNotIn(b'SQLite format 3',cipher)
            (p/'summary.json').write_text(json.dumps(dict(scope=scope,ciphertext_sha256=hashlib.sha256(cipher).hexdigest(),sqlite_sha256=hashlib.sha256(raw).hexdigest(),population=db.summary())))
            with self.assertRaises(ValueError):restore_checkpoint(p) # real restore rejects synthetic mode

    def test_owner_key_path_encrypts_and_restores_fictional_population(self):
        import base64,hashlib
        from scripts import boat_all_racers as cli
        from datetime import datetime,timezone
        raw=term_archive();now=datetime.now(timezone.utc).isoformat();key=base64.b64encode(os.urandom(32)).decode()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}), \
             patch.object(cli,'_download',return_value=(raw,now)),patch.object(cli,'PINNED_ARCHIVE_SHA',hashlib.sha256(raw).hexdigest()):
            capture(Path(folder));out=restore_checkpoint(Path(folder))
            self.assertTrue(out['durable_encrypted_storage_verified'])
            self.assertEqual(out['lookup_verified_racers'],2)
            cipher=Path(folder)/'racers.checkpoint';cipher.write_bytes(cipher.read_bytes()+b'tamper')
            with self.assertRaises(ValueError):restore_checkpoint(Path(folder))

    def test_verified_encrypted_cache_reuses_without_provider_get(self):
        import base64,hashlib
        from scripts import boat_all_racers as cli
        from datetime import datetime,timezone
        raw=term_archive();now=datetime.now(timezone.utc).isoformat();key=base64.b64encode(os.urandom(32)).decode()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}), \
             patch.object(cli,'PINNED_ARCHIVE_SHA',hashlib.sha256(raw).hexdigest()):
            p=Path(folder)
            with patch.object(cli,'_download',return_value=(raw,now)):capture(p/'first')
            with patch.object(cli,'_download',side_effect=AssertionError('duplicate upstream GET')):
                out=capture(p/'second',reuse_dir=p/'first')
            self.assertEqual(out['upstream_gets'],0)
            self.assertEqual(out['status'],'VERIFIED_ENCRYPTED_ALL_RACERS_CACHE_REUSED')
            self.assertTrue(restore_checkpoint(p/'second')['durable_encrypted_storage_verified'])
