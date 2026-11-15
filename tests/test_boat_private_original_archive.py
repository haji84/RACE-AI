"""Invented original bytes, synthetic receipts and ephemeral owner test keys."""
from copy import deepcopy
import base64
from contextlib import redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import warnings
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

try:
    archive = importlib.import_module('race_ai.boat_private_original_archive')
except ModuleNotFoundError:
    archive = None
try:
    producer = importlib.import_module('scripts.boat_private_original_archive')
except ModuleNotFoundError:
    producer = None

KEY = os.urandom(32)
HEAD = 'a'*40
BODY = '{ "synthetic": "合成専用の原本", "tickets": [[1,3,6]] }\n'.encode()
NAMES = {'P0': 'boat-p0-existing-42', 'P1': 'boat-national-cutoff-42',
         'RESULT': 'race-existing-cycle-42', 'CONTINUITY': 'race-cycle-continuity-42'}


def zipped(items):
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            for name, body in items:
                target.writestr(name, body)
    return output.getvalue()


def metadata(raw, kind='P0', *, legacy=False, suffix=''):
    run = dict(id=42, head_repository_id=1416489937)
    if not legacy:
        run.update(repository_id=1416489937, head_sha=HEAD)
    return dict(id=7, name=NAMES[kind]+suffix, expired=False,
                digest='sha256:'+hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw),
                created_at='2030-04-01T01:00:00Z', workflow_run=run)


def outer(cipher):
    return zipped([('private-original.enc', cipher)])


class PrivateOriginalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(archive, 'private original archive helper is required')

    def seal(self, raw=None, *, kind='P0'):
        return archive.seal_original_zip(zipped([('forecasts.json', BODY)]) if raw is None else raw,
                                         run_id='42', head_sha=HEAD, kind=kind, key=KEY)

    def test_encrypted_roundtrip_preserves_native_member_bytes_and_actual_receipt(self):
        plain = zipped([('forecasts.json', BODY), ('nested/opaque.bin', b'\0\xff\x80')])
        cipher = self.seal(plain)
        self.assertNotIn(BODY, cipher)
        self.assertNotIn('合成専用'.encode(), cipher)
        raw = outer(cipher); receipt = metadata(raw); before = deepcopy(receipt)
        with archive.open_original_zip(raw, receipt, expected_kind='P0', key=KEY) as source:
            self.assertEqual(source.read('forecasts.json'), BODY)
            self.assertEqual(source.read('nested/opaque.bin'), b'\0\xff\x80')
            self.assertEqual(hashlib.sha256(source.read('forecasts.json')).digest(), hashlib.sha256(BODY).digest())
        self.assertEqual(receipt, before)
        self.assertIsNone(source.fp)
        self.assertNotEqual(cipher, self.seal(plain))

    def test_all_kind_run_names_and_legacy_zip_read_without_owner_key(self):
        plain = zipped([('original.json', BODY)])
        for kind in NAMES:
            for suffix in ('', '-cycle-02') if kind != 'CONTINUITY' else ('',):
                with self.subTest(kind=kind, suffix=suffix):
                    raw = outer(self.seal(plain, kind=kind))
                    with archive.open_original_zip(raw, metadata(raw, kind, suffix=suffix), expected_kind=kind, key=KEY) as source:
                        self.assertEqual(source.read('original.json'), BODY)
            receipt = metadata(plain, kind, legacy=True)
            receipt.pop('created_at')
            with patch.dict(os.environ, {}, clear=True):
                with archive.open_original_zip(plain, receipt, expected_kind=kind) as source:
                    self.assertEqual(source.read('original.json'), BODY)

    def test_receipt_cipher_kind_run_head_and_repository_tampering_rejected(self):
        raw = outer(self.seal())
        mutations = (
            lambda r: r.update(digest='sha256:'+'0'*64),
            lambda r: r.update(expired=True),
            lambda r: r.update(name='boat-national-cutoff-42'),
            lambda r: r.update(name='boat-p0-existing-43'),
            lambda r: r.update(size_in_bytes=len(raw)+1),
            lambda r: r['workflow_run'].update(id=43),
            lambda r: r['workflow_run'].update(head_sha='b'*40),
            lambda r: r['workflow_run'].update(repository_id=1),
            lambda r: r['workflow_run'].update(head_repository_id=1),
            lambda r: r['workflow_run'].pop('repository_id'),
            lambda r: r['workflow_run'].pop('head_sha'),
            lambda r: r.update(created_at='2030-04-01T01:00:00'),
        )
        for mutate in mutations:
            receipt = metadata(raw); mutate(receipt)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                with archive.open_original_zip(raw, receipt, key=KEY):
                    pass
        for key in (os.urandom(32), b'viewer-key'):
            with self.assertRaises(ValueError):
                with archive.open_original_zip(raw, metadata(raw), key=key):
                    pass
        with self.assertRaises(ValueError):
            with archive.open_original_zip(raw, metadata(raw), expected_kind='P1', key=KEY):
                pass
        for bad_name in ('boat-p0-existing-42-r2', 'boat-p0-existing-42-cycle-00',
                         'boat-national-cutoff-42-cycle-01', 'race-cycle-continuity-42-cycle-02'):
            bad_receipt = metadata(raw); bad_receipt['name'] = bad_name
            with self.subTest(name=bad_name), self.assertRaises(ValueError):
                with archive.open_original_zip(raw, bad_receipt, key=KEY):
                    pass

    def test_cipher_header_bytes_and_domain_separation_are_authenticated(self):
        plain = zipped([('forecasts.json', BODY)])
        cipher = self.seal(plain)
        size = struct.unpack('>I', cipher[8:12])[0]
        header_bytes = cipher[12:12+size]
        header = json.loads(header_bytes)
        self.assertEqual(header['schema'], 'RACE_AI_BOAT_PRIVATE_ORIGINAL_ARCHIVE_V1')
        self.assertEqual(header['repository_id'], '1416489937')
        nonce, body = cipher[12+size:24+size], cipher[24+size:]
        domain = b'RACE_AI_BOAT_PRIVATE_ORIGINAL_ARCHIVE_V1'
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=b'1416489937', info=domain).derive(KEY)
        self.assertEqual(AESGCM(derived).decrypt(nonce, body, domain+b'\0'+header_bytes+nonce), plain)
        for info in (b'RACE_AI_BOAT_ALL_MODEL_FORECAST_V1', b'RACE_AI_BOAT_MODEL_RUNTIME_V1'):
            wrong = HKDF(algorithm=hashes.SHA256(), length=32, salt=b'1416489937', info=info).derive(KEY)
            with self.assertRaises(InvalidTag):
                AESGCM(wrong).decrypt(nonce, body, domain+b'\0'+header_bytes+nonce)
        modified = bytearray(cipher); modified[-1] ^= 1
        changed_header = dict(header, head_sha='b'*40)
        encoded = json.dumps(changed_header, sort_keys=True, separators=(',', ':')).encode()
        for bad in (bytes(modified), cipher+b'\0', cipher[:12]+encoded+cipher[12+size:], cipher[:8]+struct.pack('>I', 999999)+cipher[12:]):
            raw = outer(bad)
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                with archive.open_original_zip(raw, metadata(raw), key=KEY):
                    pass

    def test_inner_and_outer_zip_paths_duplicates_symlinks_crc_and_bounds(self):
        invalid = [zipped([('../escape.json', BODY)]), zipped([('/absolute.json', BODY)]),
                   zipped([('a\\b.json', BODY)]), zipped([('same.json', BODY), ('same.json', BODY)]),
                   zipped([('badXtail.json', BODY)]).replace(b'badXtail.json', b'bad\0tail.json')]
        info = zipfile.ZipInfo('link.json'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        invalid.append(zipped([(info, b'/elsewhere')]))
        stored = io.BytesIO()
        with zipfile.ZipFile(stored, 'w', compression=zipfile.ZIP_STORED) as target:
            target.writestr('forecasts.json', BODY)
        corrupted = bytearray(stored.getvalue())
        corrupted[30+len('forecasts.json')] ^= 1
        invalid.extend((bytes(corrupted), b'prefix'+stored.getvalue(), stored.getvalue()+b'trailing'))
        for bad in invalid:
            with self.subTest(digest=hashlib.sha256(bad).hexdigest()), self.assertRaises(ValueError):
                self.seal(bad)
        for raw in (zipped([('private-original.enc', self.seal()), ('extra.json', BODY)]),
                    zipped([('private-original.enc', self.seal()), ('private-original.enc', self.seal())])):
            with self.assertRaises(ValueError):
                with archive.open_original_zip(raw, metadata(raw), key=KEY):
                    pass
        plain = zipped([('forecasts.json', BODY)])
        raw = outer(self.seal(plain))
        with self.assertRaises(ValueError):
            with archive.open_original_zip(raw, metadata(raw), key=KEY, max_plain_zip_bytes=len(plain)-1):
                pass
        with patch.object(archive, 'MAX_EXPANDED', len(BODY)-1), self.assertRaises(ValueError):
            self.seal(plain)
        with patch.object(archive, 'MAX_ENTRIES', 1), self.assertRaises(ValueError):
            self.seal(zipped([('one.json', BODY), ('two.json', BODY)]))

    def test_authenticated_plain_hash_and_inner_zip_validation_cannot_be_bypassed(self):
        good = self.seal()
        header, _, nonce, _ = archive._split(good)
        domain = b'RACE_AI_BOAT_PRIVATE_ORIGINAL_ARCHIVE_V1'
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=b'1416489937', info=domain).derive(KEY)
        for plain, wrong_hash in ((zipped([('../escape.json', BODY)]), False),
                                  (zipped([('forecasts.json', BODY)]), True)):
            current = dict(header, plain_zip_size=len(plain),
                           plain_zip_sha256='0'*64 if wrong_hash else hashlib.sha256(plain).hexdigest())
            encoded = json.dumps(current, sort_keys=True, separators=(',', ':')).encode()
            cipher = archive.MAGIC+struct.pack('>I', len(encoded))+encoded+nonce+AESGCM(derived).encrypt(
                nonce, plain, domain+b'\0'+encoded+nonce)
            raw = outer(cipher)
            with self.subTest(wrong_hash=wrong_hash), self.assertRaises(ValueError):
                with archive.open_original_zip(raw, metadata(raw), key=KEY):
                    pass

    def test_legacy_private_zip_bound_and_missing_owner_fail_closed(self):
        plain = zipped([('forecasts.json', BODY)])
        with self.assertRaises(ValueError):
            with archive.open_original_zip(plain, metadata(plain, legacy=True), max_plain_zip_bytes=len(plain)-1):
                pass
        raw = outer(self.seal())
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            with archive.open_original_zip(raw, metadata(raw)):
                pass

    def test_legacy_reader_remains_stdlib_when_optional_crypto_is_unavailable(self):
        body = b'{ "model_id": "synthetic-original", "full_120": [{"ticket":"1-3-6","score":0.25}] }\n'
        plain = zipped([('forecasts.json', body)])
        encrypted = outer(self.seal(plain))
        payload = dict(body=base64.b64encode(body).decode(), plain=base64.b64encode(plain).decode(),
                       encrypted=base64.b64encode(encrypted).decode(), key=KEY.hex(),
                       legacy_receipt=metadata(plain, legacy=True), encrypted_receipt=metadata(encrypted))
        code = textwrap.dedent('''
            import base64, hashlib, importlib.abc, json, sys
            class NoOptionalCrypto(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'cryptography' or fullname.startswith('cryptography.'):
                        raise ModuleNotFoundError('optional crypto blocked by fixture', name=fullname)
            sys.meta_path.insert(0, NoOptionalCrypto())
            from race_ai.frozen_day_cycle import archive_json
            from race_ai.boat_private_original_archive import open_original_zip, seal_original_zip
            fixture = json.load(sys.stdin)
            body = base64.b64decode(fixture['body'])
            plain = base64.b64decode(fixture['plain'])
            encrypted = base64.b64decode(fixture['encrypted'])
            parsed, digest = archive_json(plain, fixture['legacy_receipt'], 'forecasts.json', 'boat-p0-existing-42')
            assert parsed['model_id'] == 'synthetic-original'
            assert digest == hashlib.sha256(body).hexdigest()
            with open_original_zip(plain, fixture['legacy_receipt'], expected_kind='P0') as source:
                assert source.read('forecasts.json') == body
            assert not any(name == 'cryptography' or name.startswith('cryptography.') for name in sys.modules)
            key = bytes.fromhex(fixture['key'])
            def decrypt():
                with open_original_zip(encrypted, fixture['encrypted_receipt'], key=key):
                    raise AssertionError('encrypted input unexpectedly opened')
            for action in (lambda: seal_original_zip(plain, run_id='42', head_sha='a'*40, kind='P0', key=key), decrypt):
                try:
                    action()
                except ValueError as exc:
                    assert str(exc) == 'PRIVATE_ORIGINAL_CRYPTO_RUNTIME_UNAVAILABLE', str(exc)
                else:
                    raise AssertionError('missing cryptography must reject encryption')
            print('STDLIB_LEGACY_AND_CRYPTO_REJECTION_VERIFIED')
        ''')
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                                capture_output=True, cwd=Path(__file__).resolve().parents[1],
                                env={'PATH': os.defpath}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'STDLIB_LEGACY_AND_CRYPTO_REJECTION_VERIFIED')


class PrivateOriginalProducerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(producer, 'private original producer CLI is required')

    def environment(self, temp):
        return dict(RUNNER_TEMP=str(temp), GITHUB_RUN_ID='42', GITHUB_SHA=HEAD,
                    RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())

    def test_pack_is_private_deterministic_byte_preserving_and_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'input'; source.mkdir()
            (source/'forecasts.json').write_bytes(BODY)
            (source/'nested').mkdir(); (source/'nested'/'raw.bin').write_bytes(b'\0\xff')
            runner = root/'runner'; runner.mkdir(); out = runner/'packed'
            with patch.dict(os.environ, self.environment(runner), clear=True):
                summary = producer.pack(kind='P0', input_path=source, output_dir=out)
                cipher = (out/'private-original.enc').read_bytes()
                os.utime(source/'forecasts.json', (1, 1))
                again = producer.pack(kind='P0', input_path=source, output_dir=out)
                self.assertEqual(cipher, (out/'private-original.enc').read_bytes())
                self.assertTrue(again['reused'])
                (source/'forecasts.json').write_bytes(BODY+b' ')
                with self.assertRaises(ValueError):
                    producer.pack(kind='P0', input_path=source, output_dir=out)
                with self.assertRaises(ValueError):
                    producer.pack(kind='P1', input_path=source, output_dir=out)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['private-original.enc'])
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((out/'private-original.enc').stat().st_mode), 0o600)
            self.assertEqual(summary['file_count'], 2)
            self.assertNotIn('forecasts.json', json.dumps(summary))
            self.assertNotIn('合成専用', json.dumps(summary, ensure_ascii=False))
            raw = outer(cipher)
            with archive.open_original_zip(raw, metadata(raw), key=KEY) as restored:
                self.assertEqual(restored.read('forecasts.json'), BODY)
                self.assertEqual(restored.read('nested/raw.bin'), b'\0\xff')

    def test_pack_requires_runner_temp_outside_git_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'native.json'; source.write_bytes(BODY)
            runner = root/'runner'; runner.mkdir()
            repo = runner/'repo'; repo.mkdir(); (repo/'.git').mkdir()
            with patch.dict(os.environ, self.environment(runner), clear=True):
                for out in (root/'outside-runner', repo/'encrypted', runner/'..'/'lexical-escape'):
                    with self.subTest(output=out.name), self.assertRaises(ValueError):
                        producer.pack(kind='P0', input_path=source, output_dir=out)
                linked = root/'linked.json'; linked.symlink_to(source)
                with self.assertRaises(ValueError):
                    producer.pack(kind='P0', input_path=linked, output_dir=runner/'one')
                folder = root/'folder'; folder.mkdir(); (folder/'link.json').symlink_to(source)
                with self.assertRaises(ValueError):
                    producer.pack(kind='P0', input_path=folder, output_dir=runner/'two')
                linkout = runner/'link'; linkout.symlink_to(root, target_is_directory=True)
                with self.assertRaises(ValueError):
                    producer.pack(kind='P0', input_path=source, output_dir=linkout/'three')

    def test_single_file_cli_outputs_only_safe_summary_and_requires_existing_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runner = root/'runner'; runner.mkdir()
            source = root/'national.json'; source.write_bytes(BODY)
            output = runner/'encrypted'; printed = io.StringIO()
            argv = ['pack', '--kind', 'P1', '--input', str(source), '--output-dir', str(output)]
            with patch.dict(os.environ, self.environment(runner), clear=True), redirect_stdout(printed):
                result = producer.main(argv)
            self.assertEqual(result, 0)
            summary = json.loads(printed.getvalue())
            self.assertEqual(summary['status'], 'PRIVATE_ORIGINAL_ARCHIVE_PACKED')
            self.assertEqual(summary['file_count'], 1)
            self.assertNotIn('national.json', printed.getvalue())
            self.assertNotIn('合成専用', printed.getvalue())
            self.assertNotIn(base64.b64encode(KEY).decode(), printed.getvalue())
            raw = outer((output/'private-original.enc').read_bytes())
            with archive.open_original_zip(raw, metadata(raw, 'P1'), key=KEY) as original:
                self.assertEqual(original.read('national.json'), BODY)
            env = self.environment(runner); env.pop('RACE_AI_STATE_KEY')
            printed = io.StringIO()
            with patch.dict(os.environ, env, clear=True), redirect_stdout(printed):
                result = producer.main(['pack', '--kind', 'P1', '--input', str(source),
                                        '--output-dir', str(runner/'missing-secret')])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(printed.getvalue()), {'status': 'PRIVATE_ORIGINAL_ARCHIVE_REJECTED'})
            self.assertFalse((runner/'missing-secret'/'private-original.enc').exists())


if __name__ == '__main__':
    unittest.main()
