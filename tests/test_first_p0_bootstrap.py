"""Create-only first-P0 bootstrap contract tests; no external GET or repository writes."""
import copy
import base64
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_frozen_day_cycle import sample
from scripts import first_p0_bootstrap as boot
from scripts import github_existing_cycle as cycle


class FirstP0RegistryTests(unittest.TestCase):
    """Exercise the actual register/readback path with only GitHub I/O replaced."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.day = '2030-04-01'
        self.rel = 'docs/evidence/2030-04-01/p0-first-receipt.json'
        self.path = self.root / self.rel
        _, self.raw, self.meta = sample()
        with zipfile.ZipFile(io.BytesIO(self.raw)) as archive:
            source_sha = hashlib.sha256(archive.read('forecasts.json')).hexdigest()
        self.expected = dict(
            schema='RACE_AI_P0_FIRST_RECEIPT_V1', day_jst=self.day,
            artifact_id=1, run_id=2, server_created_at='2030-04-01T01:43:00Z',
            zip_sha256=self.meta['digest'][7:], json_sha256=source_sha,
            race_count=1, model_forecast_count=2, no_regeneration=True,
            retention_days=7, permanent_private_storage_proven=False)
        self.body = (json.dumps(self.expected, sort_keys=True,
                               separators=(',', ':')) + '\n').encode()
        self.blob_sha = hashlib.sha1(
            f'blob {len(self.body)}\0'.encode() + self.body).hexdigest()
        self.file = dict(path=self.rel, type='file', size=len(self.body),
                         sha=self.blob_sha, encoding='base64',
                         content=base64.encodebytes(self.body).decode())
        self.commit = 'a' * 40
        self.created = dict(commit={'sha': self.commit}, content={
            key: self.file[key] for key in ('path', 'type', 'size', 'sha')})
        self.put_stdout = json.dumps(self.created).encode()
        self.existing = None
        self.branch_after_create = None
        self.pinned_file = self.file
        self.puts = []
        self.reads = []
        self.artifact_reads = []
        for target, name, value in (
            (boot, 'ROOT', self.root), (cycle, 'ROOT', self.root),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        clock = patch.object(boot, 'datetime')
        clock.start().now.return_value = datetime(2030, 4, 1, 1, 44, tzinfo=timezone.utc)
        self.addCleanup(clock.stop)
        api = patch.object(boot.subprocess, 'run', side_effect=self.api)
        api.start()
        self.addCleanup(api.stop)
        artifacts = patch.object(cycle, 'gh', side_effect=self.artifact)
        artifacts.start()
        self.addCleanup(artifacts.stop)

    def artifact(self, endpoint):
        self.artifact_reads.append(endpoint)
        if endpoint == 'actions/artifacts/1':
            return json.dumps(self.meta).encode()
        if endpoint == 'actions/artifacts/1/zip':
            return self.raw
        raise AssertionError(endpoint)

    def api(self, command, **kwargs):
        base = f'repos/{boot.REPO}/contents/{self.rel}'
        if '--method' in command:
            self.assertEqual(command, ['gh', 'api', '--method', 'PUT', base, '--input', '-'])
            self.puts.append(json.loads(kwargs['input']))
            return subprocess.CompletedProcess(command, 0, self.put_stdout, b'')
        self.assertEqual(command[:2], ['gh', 'api'])
        endpoint = command[2]
        self.reads.append(endpoint)
        if endpoint == f'{base}?ref={boot.BRANCH}':
            value = self.branch_after_create if self.puts else self.existing
        elif endpoint == f'{base}?ref={self.commit}':
            value = self.pinned_file
        else:
            raise AssertionError(endpoint)
        if value is None:
            return subprocess.CompletedProcess(command, 1, b'', b'gh: Not Found (HTTP 404)')
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b'')

    def assert_no_local_original(self):
        self.assertFalse(self.path.exists())
        self.assertFalse((self.root / 'boat_all_day_output').exists())
        self.assertEqual(self.artifact_reads, [])

    def test_create_reads_exact_commit_even_when_branch_still_reports_absent(self):
        result = boot.register(self.day, self.raw, self.meta)
        self.assertEqual(result, self.expected)
        self.assertEqual(self.path.read_bytes(), self.body)
        self.assertEqual(len(self.puts), 1)
        self.assertNotIn('sha', self.puts[0])  # Missing sha keeps the write create-only.
        self.assertEqual(self.puts[0]['branch'], boot.BRANCH)
        self.assertEqual(base64.b64decode(self.puts[0]['content']), self.body)
        self.assertTrue(self.reads[-1].endswith('?ref=' + self.commit))
        self.assertEqual(self.artifact_reads,
                         ['actions/artifacts/1', 'actions/artifacts/1/zip'])

    def test_existing_matching_index_is_reused_without_a_write(self):
        self.existing = self.file
        self.assertEqual(boot.register(self.day, self.raw, self.meta), self.expected)
        self.assertEqual(self.path.read_bytes(), self.body)
        self.assertEqual(self.puts, [])

    def test_conflicting_existing_index_never_writes_or_reads_original(self):
        self.existing = dict(self.file, content=base64.b64encode(b'other original').decode())
        with self.assertRaisesRegex(ValueError, 'FIRST_RECEIPT_EXISTS_WITH_OTHER_ORIGINAL'):
            boot.register(self.day, self.raw, self.meta)
        self.assertEqual(self.puts, [])
        self.assert_no_local_original()

    def test_existing_path_blob_and_size_must_match_the_original(self):
        for field, changed in (('path', 'docs/other.json'), ('sha', 'b' * 40),
                               ('size', len(self.body) + 1), ('type', 'symlink')):
            with self.subTest(field=field):
                self.existing = dict(self.file, **{field: changed})
                with self.assertRaisesRegex(ValueError, 'FIRST_RECEIPT_EXISTS_WITH_OTHER_ORIGINAL'):
                    boot.register(self.day, self.raw, self.meta)
                self.assertEqual(self.puts, [])
                self.assert_no_local_original()

    def test_missing_or_malformed_create_receipt_cannot_authorize_readback(self):
        receipts = [b'not json', b'{}', b'{"commit":null,"content":null}']
        for field, changed in (('sha', 'b' * 40), ('path', 'docs/other.json'),
                               ('type', 'symlink'), ('size', len(self.body) + 1)):
            receipt = copy.deepcopy(self.created)
            receipt['content'][field] = changed
            receipts.append(json.dumps(receipt).encode())
        receipt = copy.deepcopy(self.created)
        receipt['commit']['sha'] = 'not-a-commit'
        receipts.append(json.dumps(receipt).encode())
        for response in receipts:
            with self.subTest(response=response):
                self.puts.clear()
                self.reads.clear()
                self.put_stdout = response
                self.branch_after_create = self.file
                with self.assertRaisesRegex(ValueError, 'FIRST_RECEIPT_INDEX_CREATE_RECEIPT_INVALID'):
                    boot.register(self.day, self.raw, self.meta)
                self.assertEqual(len(self.puts), 1)
                self.assertEqual(len(self.reads), 1)
                self.assert_no_local_original()

    def test_pinned_readback_mismatch_never_falls_back_to_matching_branch(self):
        invalid = [None, dict(self.file, content=base64.b64encode(b'changed').decode()),
                   dict(self.file, sha='b' * 40), dict(self.file, path='docs/other.json'),
                   dict(self.file, encoding='none'), dict(self.file, content='not-base64!')]
        for response in invalid:
            with self.subTest(response=response):
                self.puts.clear()
                self.reads.clear()
                self.pinned_file = response
                self.branch_after_create = self.file
                with self.assertRaisesRegex(ValueError, 'FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH'):
                    boot.register(self.day, self.raw, self.meta)
                self.assertEqual(len(self.puts), 1)
                self.assertEqual(len(self.reads), 2)
                self.assert_no_local_original()


class FirstP0BootstrapTests(unittest.TestCase):
    def test_same_day_prior_owner_without_final_checkpoint_is_rejected_before_get(self):
        prior=dict(id=73,event='workflow_dispatch',
                   created_at='2030-04-01T01:00:00Z')
        with tempfile.TemporaryDirectory() as tmp,patch.object(boot,'ROOT',Path(tmp)),\
             patch.object(boot,'day_runs',return_value=[prior]),\
             patch.object(boot,'previous_source_control',return_value=None),\
             patch.object(boot,'previous_first_receipt') as receipt:
            with self.assertRaisesRegex(ValueError,'SAME_DAY_OWNER_SOURCE_CONTROL_REQUIRED'):
                boot.preflight('2030-04-01',119)
            receipt.assert_not_called()
            self.assertFalse((Path(tmp)/'cycle_recovery_output'/'bootstrap-source-control.json').exists())

    def test_same_day_prior_owner_admits_exact_authenticated_day_baseline(self):
        prior=dict(id=73,event='workflow_dispatch',
                   created_at='2030-04-01T01:00:00Z')
        control=dict(day_jst='2030-04-01',lifetime_requests=140,
                     day_start_lifetime_requests=100,lifetime_completed_rounds=2)
        with tempfile.TemporaryDirectory() as tmp,patch.object(boot,'ROOT',Path(tmp)),\
             patch.object(boot,'day_runs',return_value=[prior]),\
             patch.object(boot,'previous_source_control',return_value=control),\
             patch.object(boot,'previous_first_receipt',return_value=None):
            result=boot.preflight('2030-04-01',119)
            self.assertEqual(result,'NO_SAME_WORKFLOW_FIRST_P0_FOUND_CAPTURE_REQUIRED')
            checked=boot.bootstrap_control('2030-04-01',119)
            self.assertEqual(checked['day_start_lifetime_requests'],100)

    def test_first_p0_source_budget_inherits_same_day_baseline(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(boot,'ROOT',Path(tmp)):
            old=dict(day_jst='2030-04-01',lifetime_requests=339,
                     day_start_lifetime_requests=100,lifetime_completed_rounds=3)
            result=boot.bootstrap_control('2030-04-01',116,inherited=old)
            self.assertEqual(result['day_start_lifetime_requests'],100)
            self.assertEqual(result['lifetime_requests'],339)
            self.assertEqual(boot.bootstrap_control('2030-04-01',116),result)

    def test_first_p0_new_day_does_not_reuse_yesterday_budget(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(boot,'ROOT',Path(tmp)):
            old=dict(day_jst='2030-03-31',lifetime_requests=339,
                     day_start_lifetime_requests=100,lifetime_completed_rounds=3)
            result=boot.bootstrap_control('2030-04-01',117,inherited=old)
            self.assertEqual(result['day_start_lifetime_requests'],339)
            self.assertEqual(result['lifetime_requests'],339)

    def test_first_p0_240_day_budget_denies_before_provider_get(self):
        now=datetime.fromisoformat('2030-04-01T09:00:00+09:00')
        with tempfile.TemporaryDirectory() as tmp, patch.object(boot,'ROOT',Path(tmp)):
            old=dict(day_jst='2030-04-01',lifetime_requests=240,
                     day_start_lifetime_requests=0,lifetime_completed_rounds=3)
            boot.bootstrap_control('2030-04-01',119,inherited=old)
            with patch.object(boot,'previous_first_receipt',return_value=None),\
                 patch('scripts.existing_day_program.collect') as collect:
                collect.side_effect=lambda **kwargs:kwargs['source_guard'].charge('forecast')
                with self.assertRaisesRegex(ValueError,'BOOTSTRAP_DAY_SOURCE_BUDGET_EXCEEDED'):
                    boot.capture('2030-04-01',119,clock=lambda:now)
                self.assertEqual(collect.call_count,1)
            state=boot.bootstrap_control('2030-04-01',119)
            self.assertEqual(state['lifetime_requests'],240)
            self.assertEqual(state['requests_used'],0)

    def test_first_p0_unknown_same_day_budget_holds(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(boot,'ROOT',Path(tmp)):
            old=dict(day_jst='2030-04-01',lifetime_requests=239)
            with self.assertRaisesRegex(ValueError,'BOOTSTRAP_DAY_SOURCE_BUDGET_UNVERIFIED'):
                boot.bootstrap_control('2030-04-01',118,inherited=old)
            self.assertFalse((Path(tmp)/'cycle_recovery_output'/'bootstrap-source-control.json').exists())

    def test_direct_cli_import_works_in_actions(self):
        # Unit-test imports run under -m, whereas Actions runs scripts directly.
        import subprocess
        import sys
        from pathlib import Path
        repository = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, 'scripts/first_p0_bootstrap.py', '--help'],
            cwd=repository, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('preflight', result.stdout)

    def test_original_index_is_derived_from_independent_receipt(self):
        doc, raw, meta = sample()
        value = boot.receipt_index(raw, meta, '2030-04-01')
        self.assertEqual(value['artifact_id'], meta['id'])
        self.assertEqual(value['run_id'], meta['workflow_run']['id'])
        self.assertEqual(value['race_count'], 1)
        self.assertEqual(value['model_forecast_count'], 2)
        self.assertFalse(value['permanent_private_storage_proven'])
        self.assertTrue(value['no_regeneration'])

    def test_archive_or_metadata_tampering_never_becomes_first_index(self):
        _, raw, meta = sample()
        with self.assertRaises(ValueError):
            boot.receipt_index(raw + b'altered', meta, '2030-04-01')
        changed = copy.deepcopy(meta)
        changed['created_at'] = '2030-04-01T02:00:00Z'
        with self.assertRaises(ValueError):
            boot.receipt_index(raw, changed, '2030-04-01')
        with self.assertRaises(ValueError):
            boot.receipt_index(raw, meta, '2030-04-02')

    def test_discover_prior_original_and_never_generate_new_one(self):
        _, raw, meta = sample()
        run = {'id': 2}
        listing = {'total_count': 1, 'artifacts': [
            {'id': meta['id'], 'name': 'boat-p0-existing-2'}]}
        def fake_get(endpoint):
            if endpoint.startswith('actions/runs/2/artifacts'):
                return json.dumps(listing).encode()
            if endpoint == 'actions/artifacts/1':
                return json.dumps(meta).encode()
            if endpoint == 'actions/artifacts/1/zip':
                return raw
            raise AssertionError(endpoint)
        with patch.object(boot, 'day_runs', return_value=[run]), \
             patch.object(boot, 'gh', side_effect=fake_get):
            found = boot.previous_first_receipt('2030-04-01', 3)
        self.assertEqual(found[1]['id'], meta['id'])
        self.assertEqual(found[0], raw)

    def test_restore_preserves_just_captured_first_p0_bytes(self):
        # A new first receipt is captured before restore in the same job.
        # Restore must not overwrite it, and a byte conflict must stop.
        import io
        import os
        import tempfile
        import zipfile
        from pathlib import Path
        from scripts import github_existing_cycle as cycle

        doc, raw, meta = sample()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            body = archive.read('forecasts.json')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'boat_all_day_output' / 'forecasts.json'
            target.parent.mkdir()
            target.write_bytes(body)
            with patch.object(cycle, 'ROOT', root), \
                 patch.object(cycle, 'original', return_value=(doc, [], meta, raw)), \
                 patch.object(cycle, 'recover', return_value={}), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': '3'}):
                cycle.restore('2030-04-01')
                self.assertEqual(target.read_bytes(), body)
                target.write_bytes(b'altered')
                with self.assertRaisesRegex(ValueError, 'FIRST_P0_RESTORE_LOCAL_BYTES_CONFLICT'):
                    cycle.restore('2030-04-01')

    def test_github_artifact_reader_is_fail_closed_for_4xx_and_unknown(self):
        from scripts import github_existing_cycle as cycle
        import subprocess
        for stderr,expected in (
            (b'gh: HTTP 429: rate limited', 'GITHUB_API_READ_HTTP_429_HALT'),
            (b'gh: HTTP 403: forbidden', 'GITHUB_API_READ_HTTP_403_HALT'),
            (b'gh: some unexpected failure', 'GITHUB_API_READ_UNCLASSIFIED_CLI_ERROR_HALT'),
        ):
            failed=subprocess.CompletedProcess(['gh'],1,b'',stderr)
            with self.subTest(stderr=stderr):
                with patch.object(cycle.subprocess,'run',return_value=failed) as call:
                    with patch.object(cycle.time,'sleep') as sleeper:
                        with self.assertRaisesRegex(RuntimeError,expected):
                            cycle.gh('actions/artifacts/42/zip')
                        self.assertEqual(call.call_count,1)
                        sleeper.assert_not_called()

    def test_github_artifact_reader_retries_only_bounded_5xx_and_timeouts(self):
        from scripts import github_existing_cycle as cycle
        import subprocess
        failure=subprocess.CompletedProcess(['gh'],1,b'',b'gh: HTTP 503: temporarily unavailable')
        success=subprocess.CompletedProcess(['gh'],0,b'unchanged-zip-bytes',b'')
        with patch.object(cycle.subprocess,'run',side_effect=[failure,success]) as call:
            with patch.object(cycle.time,'sleep') as sleeper:
                self.assertEqual(cycle.gh('actions/artifacts/42/zip'),b'unchanged-zip-bytes')
                self.assertEqual(call.call_count,2)
                sleeper.assert_called_once_with(1)
        with patch.object(cycle.subprocess,'run',side_effect=[subprocess.TimeoutExpired(['gh'],50),success]) as call:
            with patch.object(cycle.time,'sleep') as sleeper:
                self.assertEqual(cycle.gh('actions/artifacts/42/zip'),b'unchanged-zip-bytes')
                self.assertEqual(call.call_count,2)
        with patch.object(cycle.subprocess,'run',return_value=failure) as call:
            with patch.object(cycle.time,'sleep'):
                with self.assertRaisesRegex(RuntimeError,'GITHUB_API_READ_HTTP_503_HALT'):
                    cycle.gh('actions/artifacts/42/zip')
                self.assertEqual(call.call_count,3)

    def test_incomplete_artifact_listing_blocks_blind_regeneration(self):
        incomplete = {'total_count': 2, 'artifacts': []}
        with patch.object(boot, 'day_runs', return_value=[{'id': 2}]), \
             patch.object(boot, 'gh', return_value=json.dumps(incomplete).encode()):
            with self.assertRaisesRegex(ValueError, 'ARTIFACT_PAGINATION_INCOMPLETE'):
                boot.previous_first_receipt('2030-04-01', 3)


if __name__ == '__main__':
    unittest.main()
