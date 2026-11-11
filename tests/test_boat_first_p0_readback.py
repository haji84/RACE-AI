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

class RetainedP1ReadbackTests(unittest.TestCase):
    """Real encrypted local-Git originals; no live race or performance claims."""
    setUp = FirstP0ReadbackTests.setUp
    git = FirstP0ReadbackTests.git
    prepare = FirstP0ReadbackTests.prepare
    receipt_get = FirstP0ReadbackTests.receipt_get
    verify = FirstP0ReadbackTests.verify

    def retain_p1(self, *, ident=901, run=7, head=HEAD, empty=False,
                  event_day='2030-04-01', round_no=1, saved='2030-04-01T01:41:00Z'):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        from race_ai.repeated_cycle import artifact_name
        from tests.test_observed_p1_connection import AT, bridge, inputs
        base, extra, proof = inputs()
        document = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1', event_day=event_day,
            paired_forecasts=[] if empty else [build_pair(base, AT)],
            additional_official_feature_shadows=[] if empty else [build_live_feature_shadow(base, extra, AT)],
            observed_pairwise_p1_bundles=[] if empty else [bridge.build_bundle(
                base, extra, AT, **proof, owner_reviewed=True)])
        body = wire(document)
        cipher = seal_original_zip(packed({'national.json': body}), run_id=str(run),
                                   head_sha=head, kind='P1', key=KEY)
        raw = packed({'private-original.enc': cipher})
        metadata = dict(id=ident, name=artifact_name('boat-national-cutoff', run, round_no),
            expired=False, created_at=saved, expires_at='2030-04-08T01:41:00Z',
            size_in_bytes=len(raw), digest='sha256:'+sha256(raw).hexdigest(),
            workflow_run=dict(id=run, repository_id=1416489937,
                              head_repository_id=1416489937, head_sha=head))
        before = self.bundle['vault_commit']
        locator = V.retain_original(raw, wire(metadata), self.writer.repo,
            expected_parent=before, key=KEY, transport=self.writer,
            readback_transport=self.retention_reader, now=NOW)
        self.bundle['vault_commit'] = locator['source_commit']
        return dict(raw=raw, cipher=cipher, body=body, metadata=metadata,
                    before=before, locator=locator)

    def cli_p1(self, output):
        args = ['--repo-root', str(self.reader.repo), '--vault-commit', self.bundle['vault_commit'],
                '--receipt-commit', self.bundle['receipt_commit'], '--day', self.bundle['day'],
                '--p0-artifact', '101', '--companion-artifact', '801', '--companion-artifact', '802',
                '--verify-retained-p1', '--output', str(output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = readback.main(args, transport=self.reader, receipt_get=self.receipt_get)
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_accepts_p1_scope_and_authenticates_nonempty_original(self):
        self.prepare(); original = self.retain_p1()
        before = self.writer.head()
        code, stdout, stderr = self.cli_p1(self.root/'p1-report.json')
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report['model_forecast_count'], 2)
        p1 = report['p1_readback']
        self.assertEqual(p1['status'], 'P1_INDEPENDENT_READBACK_VERIFIED')
        self.assertTrue(p1['generation_storage_proven'])
        self.assertEqual(p1['model_forecast_count'], 5)
        self.assertEqual(p1['race_count'], 1)
        self.assertEqual(p1['artifacts_verified'], 1)
        self.assertEqual(p1['artifacts'][0]['json_sha256'], sha256(original['body']).hexdigest())
        self.assertEqual(p1['artifacts'][0]['zip_sha256'], sha256(original['raw']).hexdigest())
        self.assertEqual(p1['artifacts'][0]['cipher_sha256'], sha256(original['cipher']).hexdigest())
        self.assertEqual(p1['artifacts'][0]['server_created_at'], original['metadata']['created_at'])
        self.assertEqual(self.writer.head(), before)
        self.assertEqual([p.name for p in self.reader.repo.iterdir()], ['.git'])
        for value in ('top8', 'roster', 'ranked', '20300401-01-01', self.env['RACE_AI_STATE_KEY']):
            self.assertNotIn(value, stdout)

    def test_no_p1_preserves_p0_without_claiming_p1_success(self):
        self.prepare()
        report, _, _, _ = self.verify(verify_retained_p1=True)
        self.assertEqual(report['status'], 'FIRST_P0_INDEPENDENT_READBACK_VERIFIED')
        self.assertEqual(report['p1_readback']['status'], 'P1_NOT_RETAINED')
        self.assertFalse(report['p1_readback']['generation_storage_proven'])
        self.assertEqual(report['p1_readback']['model_forecast_count'], 0)

    def test_empty_p1_ciphertext_does_not_count_as_a_forecast(self):
        self.prepare(); self.retain_p1(empty=True)
        report, _, _, _ = self.verify(verify_retained_p1=True)
        p1 = report['p1_readback']
        self.assertEqual(p1['status'], 'P1_EMPTY_ORIGINALS_ONLY')
        self.assertFalse(p1['generation_storage_proven'])
        self.assertEqual(p1['artifacts_verified'], 1)
        self.assertEqual(p1['empty_artifacts'], 1)
        self.assertEqual(p1['model_forecast_count'], 0)

    def test_same_run_wrong_source_head_is_rejected(self):
        self.prepare(); self.retain_p1(head='b'*40)
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_P1_SOURCE_IDENTITY'):
            self.verify(verify_retained_p1=True)

    def test_wrong_document_day_is_rejected(self):
        self.prepare(); self.retain_p1(event_day='2030-04-02')
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_P1_DAY_INVALID'):
            self.verify(verify_retained_p1=True)

    def test_other_run_p1_cannot_fill_missing_source_run_forecasts(self):
        self.prepare(); self.retain_p1(run=8)
        report, _, _, _ = self.verify(verify_retained_p1=True)
        self.assertEqual(report['p1_readback']['status'], 'P1_NOT_RETAINED')
        self.assertFalse(report['p1_readback']['generation_storage_proven'])

    def test_duplicate_race_model_rows_count_once_across_retained_rounds(self):
        self.prepare(); self.retain_p1()
        self.retain_p1(ident=902, round_no=2)
        report, _, _, _ = self.verify(verify_retained_p1=True)
        p1 = report['p1_readback']
        self.assertTrue(p1['generation_storage_proven'])
        self.assertEqual(p1['artifacts_verified'], 2)
        self.assertEqual(p1['model_forecast_count'], 5)
        self.assertEqual(p1['excluded_repeat_forecasts'], 5)

    def test_p1_cipher_tampering_is_not_hidden_by_successful_p0_readback(self):
        self.prepare(); original = self.retain_p1()
        changed_paths = self.writer._run(['diff', '--name-only', original['before'],
                                         self.bundle['vault_commit']]).decode().splitlines()
        chunk = next(path for path in changed_paths if '/chunks/' in path)
        altered = self.writer.commit({chunk: b'changed P1 ciphertext'}, self.bundle['vault_commit'])
        self.writer.push(altered, self.bundle['vault_commit'])
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_READBACK_P1_'):
            self.verify(vault_commit=altered, verify_retained_p1=True)

    def test_reader_does_not_generate_train_or_settle_predictions(self):
        self.prepare(); self.retain_p1()
        with patch('race_ai.boat_observed_pairwise_models.predict_pair', side_effect=AssertionError('inference forbidden')), \
             patch('race_ai.frozen_day_cycle.settle', side_effect=AssertionError('settlement forbidden')), \
             patch('race_ai.observed_weight_learning.fit_from_verified', side_effect=AssertionError('training forbidden')):
            report, _, _, _ = self.verify(verify_retained_p1=True)
        self.assertTrue(report['p1_readback']['generation_storage_proven'])
        self.assertEqual(report['new_forecasts_created'], 0)
        self.assertEqual(report['provider_requests'], 0)

    def test_non_artifact_capture_locators_do_not_break_p1_inventory(self):
        self.prepare(); self.retain_p1()
        raw = b'explicit synthetic official-page capture fixture'
        metadata = wire(dict(http_status=200, source_sha256=sha256(raw).hexdigest(),
            source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z'))
        locator = V.retain_capture_bundle([(raw, metadata)], self.writer.repo,
            run_id=7, head_sha=HEAD, expected_parent=self.bundle['vault_commit'],
            key=KEY, transport=self.writer, readback_transport=self.retention_reader, now=NOW)
        report, _, _, _ = self.verify(vault_commit=locator['source_commit'], verify_retained_p1=True)
        self.assertEqual(report['p1_readback']['model_forecast_count'], 5)
        self.assertEqual(report['p1_readback']['artifacts_verified'], 1)

    def test_existing_native_reader_rejects_post_cutoff_save(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'forecast not independently stored before cutoff'):
            self.retain_p1(saved='2030-04-01T02:00:00Z')
        self.assertEqual(self.writer.head(), self.bundle['vault_commit'])


class SyntheticNovember11P1EndToEndTests(unittest.TestCase):
    """Offline 2026-11-11 clock replay. Inputs are fictional, NOT 11/11 source data."""

    def _prediction(self, minutes_before_cutoff, *, ready=True):
        from datetime import date, datetime, timedelta
        from scripts import boat_nationwide_ab_pilot as pilot
        from tests.test_boat_official_program import page
        from tests.test_boat_observation_context import before_table, starts

        class VirtualClock(datetime):
            moment = None
            @classmethod
            def now(cls, tz=None):
                return cls.moment.astimezone(tz) if tz else cls.moment.replace(tzinfo=None)

        cutoff = datetime.fromisoformat('2026-11-11T10:59:00+09:00')
        VirtualClock.moment = cutoff - timedelta(minutes=minutes_before_cutoff)
        program_at = VirtualClock.moment - timedelta(minutes=2)
        exhibition_at = VirtualClock.moment - timedelta(minutes=1)
        program = page(venue='01', race_no=1, row_options={n: dict(name=f'選手 {n}') for n in range(1, 7)})
        exhibition = page(venue='01', race_no=1,
                          content=before_table(display='6.82' if ready else '&nbsp;')+
                                  starts(populated=ready))
        program = program.replace(b'20300401', b'20261111').replace(b'20:30', b'10:59')
        exhibition = exhibition.replace(b'20300401', b'20261111').replace(
            b'/owpc/pc/race/racelist?rno=', b'/owpc/pc/race/beforeinfo?rno=').replace(b'20:30', b'10:59')
        captures = [(program, program_at, sha256(program).hexdigest()),
                    (exhibition, exhibition_at, sha256(exhibition).hexdigest()),
                    pilot.SourceError('SYNTHETIC_ODDS_NOT_AVAILABLE')]
        with patch.object(pilot, 'get', side_effect=captures), \
             patch.object(pilot, 'datetime', VirtualClock), \
             patch.object(pilot, 'collect_pitreport', return_value=None), \
             patch.object(pilot, 'collect_entry_history', return_value=None), \
             patch.object(pilot, 'observed_timestamp', return_value=VirtualClock.moment.isoformat()), \
             patch.object(pilot, 'requests_used', 0), \
             patch.dict(os.environ, {'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED': 'true'}):
            result = pilot.make_pair(date(2026, 11, 11),
                dict(race_id='20261111-01-01', cutoff_at=cutoff.isoformat()))
        return cutoff, VirtualClock.moment, result

    def test_true_model_generation_pack_and_separate_process_aes_readback_at_t15_t10(self):
        """Use the unchanged P1 model path, actual pack(), native parser and independent process."""
        from datetime import datetime, timedelta
        from scripts import boat_private_original_archive as packer
        from race_ai.frozen_day_cycle import read_p1
        import sys

        for minute in (15, 10):
            with self.subTest(t_minus_minutes=minute), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                cutoff, now, (status, pair, shadow, _, observed) = self._prediction(minute)
                self.assertIsNotNone(pair, status)
                self.assertIsNotNone(observed, status)
                self.assertEqual(pair['race_id'], '20261111-01-01')
                document = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
                    event_day='2026-11-11', paired_forecasts=[pair],
                    additional_official_feature_shadows=[shadow],
                    observed_pairwise_p1_bundles=[observed],
                    research_only=True)
                original = wire(document)
                source = root/'national.json'
                source.write_bytes(original)
                source_env = dict(RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),
                                  GITHUB_RUN_ID='72341', GITHUB_SHA=HEAD, RUNNER_TEMP=str(root))
                with patch.dict(os.environ, source_env):
                    packed_report = packer.pack(kind='P1', input_path=str(source),
                                                output_dir=str(root/'p1-original'))
                self.assertEqual(packed_report['status'], 'PRIVATE_ORIGINAL_ARCHIVE_PACKED')
                cipher = (root/'p1-original'/'private-original.enc').read_bytes()
                self.assertNotIn(original, cipher)
                outer = packed({'private-original.enc': cipher})
                artifact = root/'simulated-github-artifact.zip'
                artifact.write_bytes(outer)
                receipt = dict(id=7234101, name='boat-national-cutoff-72341', expired=False,
                    created_at=(now+timedelta(seconds=10)).isoformat(),
                    digest='sha256:'+sha256(outer).hexdigest(), size_in_bytes=len(outer),
                    workflow_run=dict(id=72341, repository_id=1416489937,
                                      head_repository_id=1416489937, head_sha=HEAD))
                receipt_file = root/'receipt.json'
                receipt_file.write_text(json.dumps(receipt))
                checker = ('import json,sys,hashlib;'
                           'from pathlib import Path;'
                           'from race_ai.frozen_day_cycle import read_p1;'
                           'raw=Path(sys.argv[1]).read_bytes();'
                           'receipt=json.loads(Path(sys.argv[2]).read_text());'
                           'doc,rows=read_p1(raw,receipt);'
                           'assert len(rows)==5 and all(r["stage"]=="P1" for r in rows);'
                           'print(json.dumps({"forecast_count":len(rows),'
                           '"original_sha256":hashlib.sha256(raw).hexdigest()}))')
                env = dict(os.environ, **source_env)
                child = subprocess.run([sys.executable, '-c', checker, str(artifact), str(receipt_file)],
                                       cwd=str(Path(__file__).resolve().parents[1]), env=env,
                                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=20, check=False)
                self.assertEqual(child.returncode, 0, child.stderr)
                authenticated = json.loads(child.stdout)
                self.assertEqual(authenticated['forecast_count'], 5)
                self.assertEqual(authenticated['original_sha256'], sha256(outer).hexdigest())
                self.assertGreater((cutoff-now).total_seconds(), 0)
                self.assertGreater((cutoff-datetime.fromisoformat(receipt['created_at'])).total_seconds(), 0)
                late = deepcopy(receipt)
                late['created_at'] = (cutoff+timedelta(seconds=1)).isoformat()
                with patch.dict(os.environ, source_env):
                    with self.assertRaises(ValueError):
                        read_p1(outer, late)
                corrupt = outer[:-1] + bytes([outer[-1] ^ 1])
                with patch.dict(os.environ, source_env):
                    with self.assertRaises(ValueError):
                        read_p1(corrupt, receipt)

    def test_missing_exhibition_never_becomes_a_fabricated_p1(self):
        for minute in (15, 10):
            with self.subTest(t_minus_minutes=minute):
                cutoff, now, (status, pair, shadow, _, observed) = self._prediction(minute, ready=False)
                self.assertIsNone(pair)
                self.assertIsNone(shadow)
                self.assertIsNone(observed)
                self.assertIn(status['state'], {'EXHIBITION_NOT_FULLY_PUBLISHED',
                                               'EXHIBITION_TIME_INCOMPLETE'})


if __name__ == '__main__':
    unittest.main()
