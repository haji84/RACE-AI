"""Invented owner files and display-only keys; no provider calls or state key."""
import base64
from hashlib import sha256
import importlib
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest


class NoteViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.site = self.root / 'site'
        folder = self.site / 'data' / '2030-01-15'
        folder.mkdir(parents=True)
        self.raw = b'{"date":"2030-01-15","races":[{"race_id":"203001159801","venue":"Invented","race_no":1,"riders":[]}]}\n'
        (folder / 'races.json').write_bytes(self.raw)
        (folder / 'forecasts.json').write_text('[{"race_id":"203001159801","tickets":[]}]\n')

    def api(self):
        return importlib.import_module('race_ai.keirin_note_view')

    def test_original_json_bytes_and_hashes_survive_owner_import(self):
        note = self.api().import_site(self.site, source_commit='a'*40)
        source = note['files']['data/2030-01-15/races.json']
        self.assertEqual(source['text'].encode(), self.raw)
        self.assertEqual(source['sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(note['schema'], 'RACE_AI_KEIRIN_NOTE_VIEW_V1')
        self.assertIs(note['formal_model_admission'], False)
        self.assertIs(note['production_weight_switch'], False)

    def test_display_cipher_uses_existing_outer_format_and_separate_owner_key(self):
        api = self.api()
        note = api.import_site(self.site, source_commit='a'*40)
        result = api.seal_note(note, self.root/'encrypted', self.root/'owner')
        wire = Path(result['cipher_file']).read_bytes()
        self.assertEqual(sha256(wire).hexdigest(), result['cipher_sha256'])
        envelope = json.loads(wire)
        self.assertEqual(set(envelope), {'header', 'nonce', 'ciphertext'})
        self.assertEqual(envelope['header']['schema'], 'RACE_AI_SAVED_WEB_VIEW_V1')
        self.assertEqual(set(envelope['header']), {'schema', 'source_content_sha256'})
        self.assertEqual(len(base64.b64decode(envelope['nonce'])), 12)
        private = json.loads(Path(result['private_viewer']).read_text())
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = base64.urlsafe_b64decode(private['key']+'=')
        plain = AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),
            base64.b64decode(envelope['ciphertext']), api.canonical(envelope['header']))
        self.assertEqual(json.loads(plain), note)
        self.assertEqual(sha256(plain).hexdigest(), envelope['header']['source_content_sha256'])
        self.assertNotIn(private['key'].encode(), wire)
        self.assertEqual(stat.S_IMODE(Path(result['private_viewer']).stat().st_mode), 0o600)
        self.assertTrue(Path(result['owner_url']).read_text().startswith(
            'https://haji84.github.io/RACE-AI/#note='))

    def test_existing_cipher_or_owner_files_are_never_overwritten(self):
        api = self.api()
        note = api.import_site(self.site, source_commit='a'*40)
        out = api.seal_note(note, self.root/'encrypted', self.root/'owner')
        before = Path(out['private_viewer']).read_bytes()
        with self.assertRaises(ValueError):
            api.seal_note(note, self.root/'encrypted', self.root/'owner')
        self.assertEqual(Path(out['private_viewer']).read_bytes(), before)

    def test_symlink_duplicate_key_and_unknown_day_are_rejected(self):
        api = self.api()
        path = self.site/'data/2030-01-15/races.json'
        path.write_text('{"races":[],"races":[]}')
        with self.assertRaises(ValueError):
            api.import_site(self.site, source_commit='a'*40)
        path.unlink()
        path.symlink_to('/etc/hostname')
        with self.assertRaises(ValueError):
            api.import_site(self.site, source_commit='a'*40)

    def test_private_key_output_cannot_enter_public_checkout(self):
        api = self.api()
        note = api.import_site(self.site, source_commit='a'*40)
        checkout = self.root/'checkout'
        (checkout/'.git').mkdir(parents=True)
        with self.assertRaises(ValueError):
            api.seal_note(note, self.root/'encrypted', checkout/'owner')

    def test_private_source_archive_retains_exact_bytes_inside_encryption(self):
        api=self.api();note=api.import_site(self.site,source_commit='a'*40)
        result=api.attach_archive(note,'source-site.tar.gz',b'invented archive bytes')
        entry=result['preserved_archives']['source-site.tar.gz']
        self.assertEqual(base64.b64decode(entry['base64']),b'invented archive bytes')
        self.assertEqual(entry['sha256'],sha256(b'invented archive bytes').hexdigest())
        self.assertNotIn('preserved_archives',note)
        with self.assertRaises(ValueError):api.attach_archive(result,'source-site.tar.gz',b'changed')


if __name__ == '__main__':
    unittest.main()
