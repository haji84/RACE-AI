"""Retained-run verification uses invented encrypted records and local Git only."""
import importlib
import io
import json
import os
from contextlib import redirect_stdout
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from race_ai import boat_private_original_vault as V, boat_original_recovery as R
from race_ai import boat_source_control_mirror as M
from tests import test_boat_source_control_mirror as F

try:
    cli = importlib.import_module('scripts.boat_retained_run_verify')
except ModuleNotFoundError:
    cli = None


class RetainedRunTests(TestCase):
    def setUp(self):
        self.assertIsNotNone(cli, 'read-only retained-run verifier is absent')
        self.fixture = F.MirrorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        mirror = self.fixture.publish()
        rows = [deepcopy(self.fixture.continuity_meta), deepcopy(self.fixture.control_meta)]
        # Archived listing expiry remains true; original captured receipts stay unchanged.
        for row in rows:
            row['expired'] = True
        self.closed = R.retain_closed_run_responses(V._wire(self.fixture.run), [
            ('actions/runs/7/artifacts?per_page=100', V._wire(dict(total_count=2, artifacts=rows)))],
            self.f.writer.repo, expected_parent=mirror['source_commit'], key=F.KEY,
            transport=self.f.writer, readback_transport=self.f.reader, now=F.NOW)
        self.parent = self.f.writer.head()

    def verify(self, **kwargs):
        return cli.verify(self.f.reader, run=7, day='2030-04-01', head=F.HEAD,
                          key=F.KEY, **kwargs)

    def rewrite(self, files):
        parent = self.f.writer.head()
        commit = self.f.writer.commit(files, parent)
        self.f.writer.push(commit, parent)
        return commit

    def test_expired_archives_restore_without_http_writes_or_private_output(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')), \
                patch.object(self.f.reader, 'commit', side_effect=AssertionError('write forbidden')), \
                patch.object(self.f.reader, 'push', side_effect=AssertionError('push forbidden')):
            report = self.verify()
        self.assertEqual(report['status'], 'RETAINED_RUN_PARTIALLY_VERIFIED')
        self.assertFalse(report['raw_capture_completeness_verified'])
        self.assertEqual(report['capture_records_by_type']['OFFICIAL_RACE_RESULT'], 0)
        self.assertEqual(report['capture_records_by_type']['GITHUB_METADATA'], 2)
        self.assertEqual(report['originals_by_kind']['CONTINUITY'], 1)
        self.assertEqual(report['originals_by_kind']['SOURCE_CONTROL'], 1)
        self.assertEqual(report['originals_restored'], 2)
        self.assertEqual(report['listed_native_originals'], 2)
        self.assertEqual(report['capture_bundles_restored'], 1)
        self.assertEqual(report['captures_restored'], 2)
        self.assertTrue(report['mirror_cipher_binding_verified'])
        self.assertEqual(report['official_source_requests'], 0)
        self.assertEqual(self.f.writer.head(), self.parent)
        text = json.dumps(report)
        for secret in ('DO_NOT_PUBLISH_NATIVE', 'private.invalid', 'source_url', 'source_wait'):
            self.assertNotIn(secret, text)

    def test_authenticated_partial_inventory_is_not_success(self):
        path = V.PREFIX+'2030-04/runs/7.json'
        _, mac = V._keys(F.KEY)
        index = V._unsigned(self.f.writer.read(self.parent, path, V.MAX_INDEX), mac)
        index['entries'].pop('70')
        self.rewrite({path: V._signed(index, mac)})
        # Re-sign the month index as a genuine partial inventory, not a hash corruption.
        parent = self.f.writer.head()
        month_path = V.PREFIX+'2030-04/month.json'
        month = V._unsigned(self.f.writer.read(parent, month_path, V.MAX_INDEX), mac)
        month['runs']['7'] = V._sha(V._signed(index, mac))
        self.rewrite({month_path: V._signed(month, mac)})
        with self.assertRaisesRegex(ValueError, 'INVENTORY_COVERAGE_MISMATCH'):
            self.verify()

    def test_tampered_cipher_is_rejected_without_live_fallback(self):
        locator = V.lookup_original(70, self.f.writer.repo, key=F.KEY, transport=self.f.writer)
        _, mac = V._keys(F.KEY)
        ref = {k: locator[k] for k in ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
        entry = V._batch_entry(self.f.writer, locator['source_commit'], ref, mac)
        path = entry['chunks'][0]['path']
        # Corrupt the transport bytes even for the immutable pinned commit.
        read = self.f.reader.read
        def corrupt(commit, name, limit):
            body = read(commit, name, limit)
            return body[:-1]+bytes([body[-1]^1]) if name == path else body
        with patch.object(self.f.reader, 'read', side_effect=corrupt), self.assertRaises(ValueError):
            self.verify()

    def test_stale_mirror_is_rejected_even_when_originals_restore(self):
        latest = M._decode(self.f.writer.read(self.parent, M.LATEST, M.MAX_RECORD), F.KEY)
        latest['run_id'] = 8
        latest['record_path'] = M._path('2030-04-01', 8)
        self.rewrite({M.LATEST: M._encode(latest, F.KEY)})
        with self.assertRaisesRegex(ValueError, 'LATEST_MIRROR_SCOPE_MISMATCH'):
            self.verify()

    def test_missing_catalogue_stops_before_any_live_request(self):
        exists = self.f.reader.exists
        def hide(commit, path):
            return False if path.startswith(R.PREFIX) else exists(commit, path)
        with patch.object(self.f.reader, 'exists', side_effect=hide), \
                self.assertRaisesRegex(ValueError, 'CLOSED_RUN_CATALOGUE_REQUIRED'):
            self.verify()

    def test_read_budget_stops_before_decrypting_originals(self):
        with self.assertRaises(ValueError), patch.object(V, 'restore_original',
                side_effect=AssertionError('unbudgeted private restore')):
            self.verify(max_bytes=1)

    def test_missing_owner_key_blocks_before_git_or_output(self):
        output = self.f.root/'counts.json'
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(V, '_transport', side_effect=AssertionError('Git before owner guard')), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,'--output',str(output)])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(stream.getvalue())['reason'], 'OWNER_CONTEXT_REQUIRED')

    def test_verify_requires_owner_key_before_any_git_read(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(self.f.reader, 'head', side_effect=AssertionError('Git before key')), \
                self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
            cli.verify(self.f.reader, run=7, day='2030-04-01', head=F.HEAD)

    def test_archive_bound_precedes_private_bundle_restore(self):
        path = V.PREFIX+'2030-04/runs/7.json'
        _, mac = V._keys(F.KEY)
        index = V._unsigned(self.f.writer.read(self.parent, path, V.MAX_INDEX), mac)
        capture = next(value for value in index['entries'].values() if value['kind'] == 'SOURCE_CAPTURES')
        for number in range(129):
            index['entries']['captures-'+format(number, '064x')] = capture
        month_path = V.PREFIX+'2030-04/month.json'
        month = V._unsigned(self.f.writer.read(self.parent, month_path, V.MAX_INDEX), mac)
        month['runs']['7'] = V._sha(V._signed(index, mac))
        self.rewrite({path: V._signed(index, mac), month_path: V._signed(month, mac)})
        with patch.object(V, 'restore_capture_bundle', side_effect=AssertionError('private read before bound')), \
                self.assertRaisesRegex(ValueError, 'INVENTORY_BOUND_EXCEEDED'):
            self.verify()

    def test_cli_uses_fresh_bare_git_and_only_writes_private_count_report(self):
        output = self.f.root/'verified-counts.json'
        before = set(self.f.root.iterdir())
        # Only the remote allowlist is replaced: real fresh Git, AES/HMAC, and CLI guards run.
        def local_git(repo, *, ref=V.VAULT_REF):
            return F.fixtures.LocalGit(repo, ref=self.f.writer.ref)
        with patch.dict(os.environ, self.fixture.env, clear=True), \
                patch.object(cli, 'ROOT', self.f.writer.repo), \
                patch.object(V, 'VaultGitRepository', side_effect=local_git), \
                patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,'--output',str(output)])
        self.assertEqual(code, 0, stream.getvalue())
        self.assertEqual(json.loads(output.read_bytes()), json.loads(stream.getvalue()))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(self.f.root.iterdir())-before, {output})
        self.assertEqual(self.f.writer.head(), self.parent)

    def test_untrusted_error_is_not_echoed_and_failure_never_reports_verified(self):
        output = self.f.root/'hold-counts.json'
        with patch.dict(os.environ, self.fixture.env, clear=True), \
                patch.object(cli, 'ROOT', self.f.writer.repo), \
                patch.object(cli, '_fresh_reader', side_effect=ValueError('https://secret.invalid/PRIVATE')), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,'--output',str(output)])
        self.assertEqual(code, 2)
        value = json.loads(stream.getvalue())
        self.assertEqual(value['status'], 'RETAINED_RUN_VERIFICATION_HOLD')
        self.assertEqual(value['reason'], 'AUTHENTICATED_READ_FAILED')
        self.assertNotIn('PRIVATE', output.read_text())
        self.assertIsNone(value['diagnostics']['error_code'])
        self.assertEqual(value['diagnostics']['exception_type'], 'ValueError')
        self.assertEqual(value['diagnostics']['stage'], 'FRESH_REPOSITORY')

    def test_real_read_failure_reports_safe_stage_cause_and_bounded_code_sites(self):
        output = self.f.root/'read-failure-counts.json'
        def local_git(repo, *, ref=V.VAULT_REF):
            git = F.fixtures.LocalGit(repo, ref=self.f.writer.ref)
            def fail_read(commit, path, limit):
                raise ValueError('STATE_GIT_BLOB_BOUND_EXCEEDED')
            git.read = fail_read
            return git
        with patch.dict(os.environ, self.fixture.env, clear=True), \
                patch.object(cli, 'ROOT', self.f.writer.repo), \
                patch.object(V, 'VaultGitRepository', side_effect=local_git), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,'--output',str(output)])
        self.assertEqual(code, 2)
        report = json.loads(stream.getvalue())
        self.assertEqual(report['status'], 'RETAINED_RUN_VERIFICATION_HOLD')
        diagnostics = report['diagnostics']
        self.assertEqual(diagnostics['stage'], 'INVENTORY')
        self.assertEqual(diagnostics['error_code'], 'VAULT_RETAINED_BYTES_MISSING_OR_INVALID')
        self.assertIn('STATE_GIT_BLOB_BOUND_EXCEEDED', diagnostics['cause_codes'])
        self.assertEqual(diagnostics['originals_restored'], 0)
        self.assertEqual(diagnostics['blob_bytes_read'], 0)
        self.assertGreater(len(diagnostics['code_sites']), 0)
        self.assertLessEqual(len(diagnostics['code_sites']), 3)
        for site in diagnostics['code_sites']:
            self.assertRegex(site, r'^[A-Za-z_][A-Za-z0-9_]*\.py:[1-9][0-9]*:[A-Za-z_][A-Za-z0-9_]*$')
        self.assertNotIn(str(self.f.root), json.dumps(report))

    def test_mirror_failure_reports_completed_original_counts_without_success(self):
        output = self.f.root/'mirror-failure-counts.json'
        latest = M._decode(self.f.writer.read(self.parent, M.LATEST, M.MAX_RECORD), F.KEY)
        latest['run_id'] = 8
        latest['record_path'] = M._path('2030-04-01', 8)
        self.rewrite({M.LATEST: M._encode(latest, F.KEY)})
        def local_git(repo, *, ref=V.VAULT_REF):
            return F.fixtures.LocalGit(repo, ref=self.f.writer.ref)
        with patch.dict(os.environ, self.fixture.env, clear=True), \
                patch.object(cli, 'ROOT', self.f.writer.repo), \
                patch.object(V, 'VaultGitRepository', side_effect=local_git), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,'--output',str(output)])
        self.assertEqual(code, 2)
        report = json.loads(stream.getvalue())
        self.assertEqual(report['reason'], 'LATEST_MIRROR_SCOPE_MISMATCH')
        diagnostics = report['diagnostics']
        self.assertEqual(diagnostics['stage'], 'MIRROR')
        self.assertEqual(diagnostics['originals_restored'], 2)
        self.assertEqual(diagnostics['capture_bundles_restored'], 1)
        self.assertGreater(diagnostics['blob_bytes_read'], 0)
        self.assertEqual(report['status'], 'RETAINED_RUN_VERIFICATION_HOLD')

    def test_diagnostic_whitelist_drops_private_messages_and_external_code_paths(self):
        # Neither an approved-looking prefix nor an exception chain permits arbitrary text.
        for secret in ('VAULT_PRIVATE https://secret.invalid/key', 'VAULT_PRIVATE\nKEY',
                       'UNAPPROVED_SECRET', 'a'*500):
            with self.subTest(secret=secret):
                try:
                    try:
                        raise RuntimeError(secret)
                    except RuntimeError:
                        raise ValueError(secret)
                except ValueError as exc:
                    report = cli._failure_diagnostics(exc, {})
                self.assertIsNone(report['error_code'])
                self.assertEqual(report['cause_codes'], [])
                self.assertNotIn(secret, json.dumps(report))
                self.assertEqual(report['code_sites'], [])

    def official_requirement(self):
        raw = b'<html>invented private result, unchanged bytes</html>'
        receipt = V._wire(dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z', source_sha256=V._sha(raw), http_status=200))
        locator = V.retain_capture_bundle([(raw, receipt)], self.f.writer.repo,
            run_id=7, head_sha=F.HEAD, expected_parent=self.f.writer.head(), key=F.KEY,
            transport=self.f.writer, readback_transport=self.f.reader, now=F.NOW)
        return dict(schema='RACE_AI_BOAT_REQUIRED_CAPTURE_V1', locator=locator, expected_capture_count=1)

    def test_exact_required_official_bundle_proves_raw_completeness(self):
        required = self.official_requirement()
        # Advance the snapshot: current inventory locators legitimately use a later source_commit.
        self.rewrite({'unrelated/public.json': b'{}'})
        report = self.verify(required_capture=required)
        self.assertEqual(report['status'], 'RETAINED_RUN_VERIFIED')
        self.assertTrue(report['raw_capture_completeness_verified'])
        self.assertEqual(report['required_official_result_captures'], 1)
        self.assertEqual(report['capture_records_by_type']['OFFICIAL_RACE_RESULT'], 1)
        self.assertEqual(report['capture_records_by_type']['GITHUB_METADATA'], 2)

    def test_metadata_only_inventory_cannot_mask_missing_required_official_bundle(self):
        required = self.official_requirement()
        parent = self.f.writer.head()
        path = V.PREFIX+'2030-04/runs/7.json'
        month_path = V.PREFIX+'2030-04/month.json'
        _, mac = V._keys(F.KEY)
        index = V._unsigned(self.f.writer.read(parent, path, V.MAX_INDEX), mac)
        index['entries'] = {name: value for name, value in index['entries'].items()
                            if value['entry_sha256'] != required['locator']['entry_sha256']}
        month = V._unsigned(self.f.writer.read(parent, month_path, V.MAX_INDEX), mac)
        month['runs']['7'] = V._sha(V._signed(index, mac))
        self.rewrite({path: V._signed(index, mac), month_path: V._signed(month, mac)})
        with self.assertRaisesRegex(ValueError, 'REQUIRED_CAPTURE_NOT_IN_INVENTORY'):
            self.verify(required_capture=required)

    def test_github_metadata_bundle_is_not_an_official_result_bundle(self):
        locator = next(value for value in V.list_originals('2030-04', self.f.writer.repo,
            run_id=7, key=F.KEY, transport=self.f.writer) if value['kind'] == 'SOURCE_CAPTURES')
        required = dict(schema='RACE_AI_BOAT_REQUIRED_CAPTURE_V1', locator=locator, expected_capture_count=2)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_CAPTURE_TYPE_MISMATCH'):
            self.verify(required_capture=required)

    def test_required_bundle_count_and_identity_must_match(self):
        required = self.official_requirement()
        for wrong in (dict(required, expected_capture_count=2),
                      dict(required, locator=dict(required['locator'], entry_sha256='f'*64))):
            with self.subTest(wrong=wrong['expected_capture_count']), self.assertRaises(ValueError):
                self.verify(required_capture=wrong)

    def test_cli_reads_only_public_requirement_and_emits_full_count_proof(self):
        required = self.official_requirement()
        config = self.f.writer.repo/'audit'/'state'/'retained-captures.json'
        config.parent.mkdir(parents=True)
        config.write_bytes(V._wire(required))
        output = self.f.root/'full-counts.json'
        def local_git(repo, *, ref=V.VAULT_REF):
            return F.fixtures.LocalGit(repo, ref=self.f.writer.ref)
        with patch.dict(os.environ, self.fixture.env, clear=True), \
                patch.object(cli, 'ROOT', self.f.writer.repo), \
                patch.object(V, 'VaultGitRepository', side_effect=local_git), \
                redirect_stdout(io.StringIO()) as stream:
            code = cli.main(['--run','7','--day','2030-04-01','--head',F.HEAD,
                '--required-capture-locator',str(config),'--output',str(output)])
        self.assertEqual(code, 0, stream.getvalue())
        report = json.loads(output.read_bytes())
        self.assertEqual(report['status'], 'RETAINED_RUN_VERIFIED')
        self.assertEqual(report['required_official_result_captures'], 1)
