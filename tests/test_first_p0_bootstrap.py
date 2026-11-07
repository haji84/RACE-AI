"""Create-only first-P0 bootstrap contract tests; no external GET or repository writes."""
import copy
import json
import unittest
from unittest.mock import patch

from tests.test_frozen_day_cycle import sample
from scripts import first_p0_bootstrap as boot


class FirstP0BootstrapTests(unittest.TestCase):
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
