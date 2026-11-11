"""Separate-reader verification of invented native AES originals in local Git."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha1, sha256
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_private_original_vault as V
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.boat_source_control import build_summary
from tests.test_boat_private_original_vault import (
    BASE_NATIVE, HEAD, KEY, NOW, LocalGit, original, packed, wire,
)
from tests.test_continuity_checkpoint import session

try:
    readback = importlib.import_module('scripts.boat_first_p0_readback')
except ModuleNotFoundError:
    readback = None


def companion_pair(*, ident=801, run=7, head=HEAD):
    cipher = seal_original_zip(packed({'repeat-session.json': session(run_id=run)}),
        run_id=str(run), head_sha=head, kind='CONTINUITY', key=KEY)
    raw = packed({'private-original.enc': cipher})
    metadata = dict(id=ident, name=f'race-cycle-continuity-{run}', expired=False,
        created_at='2030-04-01T02:00:00Z', expires_at='2030-04-08T02:00:00Z',
        digest='sha256:'+sha256(raw).hexdigest(), size_in_bytes=len(raw),
        workflow_run=dict(id=run, repository_id=1416489937,
                          head_repository_id=1416489937, head_sha=head))
    return raw, wire(metadata), cipher


def retain_bundle(writer, reader, parent, *, p0_pair=None, companion_run=7,
                  companion_head=HEAD):
    """Reusable real vault fixture; no live network, production key, or scorer."""
    raw, metadata_raw = p0_pair or original(ident=101, run=7, encrypted=True)
    metadata = json.loads(metadata_raw)
    continuity, continuity_meta, cipher = companion_pair(run=companion_run, head=companion_head)
    summary = build_summary(cipher, run_id=companion_run, head_sha=companion_head, key=KEY)
    control = packed({'source-control.json': wire(summary)})
    control_meta = json.loads(continuity_meta)
    control_meta.update(id=802, name=f'race-source-control-{companion_run}',
                        digest='sha256:'+sha256(control).hexdigest(), size_in_bytes=len(control))
    retained = V.retain_originals([
        (raw, metadata_raw), (continuity, continuity_meta),
        dict(raw_zip=control, metadata_raw=wire(control_meta),
             companion=(continuity, continuity_meta)),
    ], writer.repo, expected_parent=parent, key=KEY, transport=writer,
       readback_transport=reader, now=NOW)
    with zipfile.ZipFile(io.BytesIO(BASE_NATIVE)) as archive:
        body_sha = sha256(archive.read('forecasts.json')).hexdigest()
    index = dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1', day_jst='2030-04-01',
        artifact_id=101, run_id=7, server_created_at='2030-04-01T01:43:00Z',
        zip_sha256=sha256(raw).hexdigest(), json_sha256=body_sha,
        race_count=1, model_forecast_count=2, no_regeneration=True,
        retention_days=7, permanent_private_storage_proven=False)
    body = wire(index)+b'\n'
    receipt_file = dict(path='docs/evidence/2030-04-01/p0-first-receipt.json',
        type='file', encoding='base64', size=len(body),
        sha=sha1(f'blob {len(body)}\0'.encode()+body).hexdigest(),
        content=base64.encodebytes(body).decode())
    return dict(vault_commit=retained['source_commit'], receipt_commit='c'*40,
        day='2030-04-01', p0_artifact=101, companion_artifacts=[801, 802],
        receipt_file=receipt_file, p0_raw=raw, p0_meta=metadata,
        continuity_raw=continuity, continuity_meta=json.loads(continuity_meta))


class FirstP0ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(readback, 'separate-runner first-P0 verifier is absent')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root/'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', '--git-dir', str(self.remote), 'config',
                        'uploadpack.allowFilter', 'true'], check=True, capture_output=True)
        self.writer = self.git('writer')
        self.retention_reader = self.git('retention-reader')
        self.reader = self.git('separate-verification-reader')
        self.parent = self.writer.commit({'unrelated.enc': b'unchanged ciphertext'}, None)
        self.writer.push(self.parent, None)
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_RUN_ID='99', GITHUB_SHA='d'*40, GH_TOKEN='fixture-token-only-not-a-credential',
            RUNNER_TEMP=str(self.root), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        auth = patch('scripts.boat_saved_view_feed.git_auth')
        auth.start(); self.addCleanup(auth.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('provider GET forbidden'))
        network.start(); self.addCleanup(network.stop)
        self.receipt_calls = []

    def git(self, name):
        repo = self.root/name
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', str(self.remote)],
                       check=True, capture_output=True)
        return LocalGit(repo, ref=V.VAULT_REF)

    def prepare(self, **kwargs):
        self.bundle = retain_bundle(self.writer, self.retention_reader, self.parent, **kwargs)

    def receipt_get(self, path, *, ref):
        self.receipt_calls.append((path, ref))
        self.assertEqual(path, 'docs/evidence/2030-04-01/p0-first-receipt.json')
        self.assertEqual(ref, self.bundle['receipt_commit'])
        return deepcopy(self.bundle['receipt_file'])

    def verify(self, **changes):
        args = {key: self.bundle[key] for key in (
            'vault_commit', 'receipt_commit', 'day', 'p0_artifact', 'companion_artifacts')}
        args.update(changes)
        return readback.verify(self.reader.repo, transport=self.reader,
                               receipt_get=self.receipt_get, **args)

    def test_native_objects_verify_at_pinned_commit_after_vault_head_moves(self):
        self.prepare()
        later = self.writer.commit({'unrelated.enc': b'later unchanged receipt history'},
                                   self.bundle['vault_commit'])
        self.writer.push(later, self.bundle['vault_commit'])
        report, document, rows, metadata = self.verify()
        self.assertEqual(metadata, self.bundle['p0_meta'])
        self.assertEqual(document['race_count'], 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(report['original_id'], 101)
        self.assertEqual(report['source_run_id'], 7)
        self.assertEqual(report['verification_run_id'], 99)
        self.assertEqual(report['source_sha'], HEAD)
        self.assertEqual(report['vault_commit'], self.bundle['vault_commit'])
        self.assertEqual(report['zip_sha256'], sha256(self.bundle['p0_raw']).hexdigest())
        with zipfile.ZipFile(io.BytesIO(self.bundle['p0_raw'])) as archive:
            cipher = archive.read('private-original.enc')
        self.assertEqual(report['cipher_sha256'], sha256(cipher).hexdigest())
        self.assertEqual(report['inner_zip_sha256'], sha256(BASE_NATIVE).hexdigest())
        for name, value in (('race_count', 1), ('model_forecast_count', 2),
                            ('distinct_model_count', 2), ('before_cutoff_race_count', 1),
                            ('before_cutoff_model_forecast_count', 2), ('artifacts_verified', 3),
                            ('companions_verified', 2), ('new_forecasts_created', 0),
                            ('provider_requests', 0)):
            self.assertEqual(report[name], value, name)
        self.assertTrue(report['independent_readback_verified'])
        self.assertFalse(report['plaintext_published'])
        self.assertFalse(report['scoring_performed'])
        self.assertEqual(self.writer.head(), later)
        self.assertEqual([path.name for path in self.reader.repo.iterdir()], ['.git'])
        self.assertEqual(len(self.receipt_calls), 1)

    def test_missing_and_duplicate_companions_cannot_be_certified(self):
        self.prepare()
        for ids in ([801], [801, 801], [101, 801], [801, 999]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_'):
                self.verify(companion_artifacts=ids)
        self.assertEqual(self.receipt_calls, [])

    def test_foreign_companion_run_is_rejected_even_with_valid_vault_encryption(self):
        self.prepare(companion_run=8)
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_COMPANION_IDENTITY'):
            self.verify()

    def test_foreign_companion_head_is_rejected_even_with_valid_vault_encryption(self):
        self.prepare(companion_head='b'*40)
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_COMPANION_IDENTITY'):
            self.verify()

    def test_source_control_must_bind_the_explicit_continuity_companion(self):
        self.prepare()
        raw, metadata, _ = companion_pair(ident=803)
        locator = V.retain_original(raw, metadata, self.writer.repo,
            expected_parent=self.bundle['vault_commit'], key=KEY, transport=self.writer,
            readback_transport=self.retention_reader, now=NOW)
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_COMPANION_BINDING'):
            self.verify(vault_commit=locator['source_commit'], companion_artifacts=[803, 802])

    def test_receipt_bytes_and_path_are_authenticated_without_rewriting_index(self):
        self.prepare()
        original_file = deepcopy(self.bundle['receipt_file'])
        for field, value in (('path', 'docs/foreign.json'), ('sha', 'f'*40),
                             ('content', base64.b64encode(b'altered receipt').decode())):
            self.bundle['receipt_file'] = dict(original_file, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_RECEIPT_MISMATCH'):
                self.verify()
        self.assertEqual(self.writer.head(), self.bundle['vault_commit'])
        self.assertEqual([path.name for path in self.reader.repo.iterdir()], ['.git'])

    def test_wrong_event_day_fails_native_p0_validation(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_P0_REJECTED'):
            self.verify(day='2030-04-02')
        self.assertEqual(self.receipt_calls, [])

    def test_tampered_retained_ciphertext_fails_before_receipt_or_plaintext_output(self):
        self.prepare()
        paths = self.writer._run(['ls-tree', '-r', '--name-only',
                                  self.bundle['vault_commit']]).decode().splitlines()
        chunk = next(path for path in paths if '/chunks/' in path)
        changed = self.writer.commit({chunk: b'tampered ciphertext'}, self.bundle['vault_commit'])
        self.writer.push(changed, self.bundle['vault_commit'])
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_VAULT_REJECTED'):
            self.verify(vault_commit=changed)
        self.assertEqual(self.receipt_calls, [])
        self.assertEqual([path.name for path in self.reader.repo.iterdir()], ['.git'])

    def test_same_source_run_and_non_owner_context_cannot_claim_independence(self):
        self.prepare()
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '7'}):
            with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_SEPARATE_RUN_REQUIRED'):
                self.verify()
        for update in ({'GITHUB_ACTIONS': 'false'}, {'RACE_AI_STATE_KEY': ''}):
            with self.subTest(update=list(update)), patch.dict(os.environ, update), \
                    patch.object(self.reader, 'fetch', side_effect=AssertionError('premature Git read')):
                with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_'):
                    self.verify()
        self.assertEqual(self.receipt_calls, [])

    def cli(self, output, *, receipt_get=None):
        stdout = io.StringIO()
        args = ['--repo-root', str(self.reader.repo), '--vault-commit', self.bundle['vault_commit'],
            '--receipt-commit', self.bundle['receipt_commit'], '--day', self.bundle['day'],
            '--p0-artifact', '101', '--companion-artifact', '801', '--companion-artifact', '802',
            '--output', str(output)]
        with redirect_stdout(stdout):
            code = readback.main(args, transport=self.reader, receipt_get=receipt_get or self.receipt_get)
        return code, stdout.getvalue()

    def test_cli_emits_only_count_report_and_never_extracts_native_plaintext(self):
        self.prepare()
        output = self.root/'count-report.json'
        code, stdout = self.cli(output)
        self.assertEqual(code, 0)
        report = json.loads(stdout)
        self.assertEqual(json.loads(output.read_text()), report)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        for forbidden in ('predictions', 'observations', 'top8', 'ranked', 'roster',
                          'RACE_AI_EXISTING_P0_DAY_V1', self.env['RACE_AI_STATE_KEY']):
            self.assertNotIn(forbidden, stdout)
        self.assertEqual([path.name for path in self.reader.repo.iterdir()], ['.git'])

    def test_cli_failure_diagnostics_never_echo_private_exception_text(self):
        self.prepare()
        secret = 'private payload and token must never appear'
        def denied(path, *, ref):
            raise RuntimeError(secret)
        output = self.root/'rejected-report.json'
        code, stdout = self.cli(output, receipt_get=denied)
        self.assertEqual(code, 2)
        self.assertNotIn(secret, stdout)
        self.assertEqual(json.loads(stdout)['status'], 'FIRST_P0_READBACK_REJECTED')
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
