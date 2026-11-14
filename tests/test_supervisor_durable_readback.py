"""Source-free regression for archived source handoff without age-based expiry."""
from datetime import timedelta
from copy import deepcopy
import os
import unittest
from unittest.mock import patch

from race_ai import boat_original_recovery as R, boat_private_original_vault as V
from race_ai.github_continuous_supervisor import GitHubCLI
from scripts import github_existing_cycle as cycle
from tests import test_boat_source_control_mirror as fixtures

KEY, NOW = fixtures.KEY, fixtures.NOW


class DurableSupervisorReadbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MirrorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        retained = V.retain_originals([
            (f.continuity, V._wire(f.continuity_meta)),
            dict(raw_zip=f.control, metadata_raw=V._wire(f.control_meta),
                 companion=(f.continuity, V._wire(f.continuity_meta))),
        ], f.f.writer.repo, expected_parent=f.f.parent, key=KEY,
            transport=f.f.writer, readback_transport=f.f.reader, now=NOW)
        self.closed = R.retain_closed_run_responses(
            V._wire(f.run), [('actions/runs/7/artifacts?per_page=100',
                f.responses['actions/runs/7/artifacts?per_page=100'])],
            f.f.writer.repo, expected_parent=retained['source_commit'], key=KEY,
            transport=f.f.writer, readback_transport=f.f.reader, now=NOW)
        self.client = GitHubCLI()
        self.calls = []

    def no_live(self, endpoint, **kwargs):
        self.calls.append(endpoint)
        raise AssertionError('EXPIRED_LIVE_API_MUST_NOT_BE_CONTACTED')

    def reader(self, **kwargs):
        f = self.fixture
        return R.ArtifactRecovery(self.no_live, f.f.reader.repo,
                                  key=kwargs.get('key', KEY), transport=f.f.reader)

    def test_handoff_restores_at_four_days_one_year_and_ten_years_from_exact_git(self):
        f = self.fixture
        original_receipts = deepcopy((f.control_meta, f.continuity_meta))
        parent = self.closed['source_commit']
        for age_days in (4, 8, 366, 3653):
            with self.subTest(age_days=age_days):
                report = f.publish(expected_parent=parent, get=self.no_live,
                                   now=NOW + timedelta(days=age_days))
                parent = report['source_commit']
                archive = self.reader()
                with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
                     patch.object(cycle, 'original_reader', return_value=archive), \
                     patch.object(self.client, 'raw', side_effect=self.no_live):
                    control = self.client.final_control(f.run)
                self.assertEqual(control['previous_run_id'], 7)
                self.assertEqual(control['receipt']['created_at'], f.continuity_meta['created_at'])
                self.assertEqual(control['source_control_receipt']['created_at'], f.control_meta['created_at'])
                self.assertEqual(archive('actions/artifacts/70/zip'), f.continuity)
                self.assertEqual(archive('actions/artifacts/71/zip'), f.control)
                self.assertEqual((f.control_meta, f.continuity_meta), original_receipts)
                self.assertEqual(self.calls, [])

    def test_archive_disabled_preserves_existing_transport(self):
        f = self.fixture
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(cycle, 'original_reader', side_effect=AssertionError('unexpected archive')), \
             patch.object(self.client, 'raw', side_effect=lambda endpoint: f.responses[endpoint]):
            result = self.client.final_control(f.run)
        self.assertEqual(result['previous_run_id'], 7)

    def test_explicit_archive_flag_without_reader_never_downgrades_to_live(self):
        with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
             patch.object(cycle, 'original_reader', return_value=None), \
             patch.object(self.client, 'raw', side_effect=self.no_live):
            with self.assertRaisesRegex(ValueError, 'WORKFLOW_ARCHIVE_READER_UNAVAILABLE'):
                self.client.final_control(self.fixture.run)
        self.assertEqual(self.calls, [])

    def test_bad_archive_key_never_downgrades_to_live(self):
        archive = self.reader(key=bytes(range(32, 64)))
        with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
             patch.object(cycle, 'original_reader', return_value=archive), \
             patch.object(self.client, 'raw', side_effect=self.no_live):
            with self.assertRaises(ValueError):
                self.client.final_control(self.fixture.run)
        self.assertEqual(self.calls, [])

    def test_rerun_cannot_reuse_the_archived_attempt_one_checkpoint(self):
        run = dict(self.fixture.run, run_attempt=2)
        with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
             patch.object(cycle, 'original_reader', return_value=self.reader()), \
             patch.object(self.client, 'raw', side_effect=self.no_live):
            with self.assertRaisesRegex(ValueError, 'WORKFLOW_ARCHIVED_ATTEMPT_MISMATCH'):
                self.client.final_control(run)
        self.assertEqual(self.calls, [])

    def test_running_worker_cannot_be_replaced_by_a_closed_archive(self):
        run = dict(self.fixture.run, status='in_progress', conclusion=None)
        with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
             patch.object(cycle, 'original_reader', return_value=self.reader()), \
             patch.object(self.client, 'raw', side_effect=self.no_live):
            with self.assertRaisesRegex(ValueError, 'WORKFLOW_ARCHIVED_ATTEMPT_MISMATCH'):
                self.client.final_control(run)
        self.assertEqual(self.calls, [])

    def test_another_head_cannot_use_a_valid_archived_handoff(self):
        run = dict(self.fixture.run, head_sha='b' * 40)
        with patch.dict(os.environ, {'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true'}, clear=True), \
             patch.object(cycle, 'original_reader', return_value=self.reader()), \
             patch.object(self.client, 'raw', side_effect=self.no_live):
            with self.assertRaises(ValueError):
                self.client.final_control(run)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
