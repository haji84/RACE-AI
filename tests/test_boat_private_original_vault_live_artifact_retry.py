"""Test classified transient GitHub artifact availability; never provider GET."""
from datetime import datetime, timezone
import json
import os
import unittest
from unittest.mock import patch
from scripts import boat_private_original_vault as cli


class LiveGithubArtifactRetryTests(unittest.TestCase):
    def test_recent_same_artifact_id_can_be_read_after_two_transient_failures(self):
        endpoint="actions/artifacts/14004326635"
        with patch.object(cli,"_gh_once",side_effect=[
                ValueError("VAULT_GITHUB_HTTP_503"),
                ValueError("VAULT_GITHUB_HTTP_502"),
                b"IMMUTABLE_SYNTHETIC_METADATA"]) as get, \
             patch.object(cli.time,"sleep") as pause:
            self.assertEqual(cli._gh(endpoint),b"IMMUTABLE_SYNTHETIC_METADATA")
        self.assertEqual(get.call_count,3)
        self.assertTrue(all(x.args == (endpoint,) for x in get.call_args_list))
        self.assertEqual([x.args[0] for x in pause.call_args_list],[2,4])

    def test_artifact_zip_exhausted_transient_failure_keeps_hold(self):
        endpoint="actions/artifacts/14004326635/zip"
        with patch.object(cli,"_gh_once",side_effect=ValueError(
                "VAULT_GITHUB_HTTP_503")) as get, \
             patch.object(cli.time,"sleep") as pause:
            with self.assertRaisesRegex(ValueError,"VAULT_GITHUB_HTTP_503"):
                cli._gh(endpoint)
        self.assertEqual(get.call_count,3)
        self.assertEqual(pause.call_count,2)

    def test_source_run_unclassified_denial_is_not_retried(self):
        with patch.object(cli,"_gh_once",side_effect=ValueError(
                "VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE")) as get, \
             patch.object(cli.time,"sleep") as pause:
            with self.assertRaisesRegex(ValueError,"VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE"):
                cli._gh("actions/runs/43348227701")
        get.assert_called_once();pause.assert_not_called()

    def test_integrity_size_and_empty_response_failures_never_retry(self):
        endpoint="actions/artifacts/14004326635"
        for reason in ("VAULT_GITHUB_READ_BOUND_INVALID",
                       "VAULT_GITHUB_RESPONSE_EMPTY",
                       "VAULT_LIVE_ARTIFACT_DIGEST_INVALID"):
            with self.subTest(reason=reason),patch.object(cli,"_gh_once",
                    side_effect=ValueError(reason)) as get, \
                 patch.object(cli.time,"sleep") as pause:
                with self.assertRaisesRegex(ValueError,reason):
                    cli._gh(endpoint)
                get.assert_called_once();pause.assert_not_called()


class FreshOwnUploadRetryTests(unittest.TestCase):
    """Only a real current upload receipt may authorize metadata visibility retry."""
    def setUp(self):
        self.now = datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc)
        self.head = 'a' * 40
        self.ident = 123
        self.endpoint = 'actions/artifacts/123'
        self.name = 'boat-national-cutoff-99-cycle-07'
        self.digest = 'sha256:' + 'b' * 64
        self.run = dict(id=99, workflow_id=405276784, head_branch='production/boat-p0-p1-20261111',
                        event='workflow_dispatch', head_sha=self.head, status='in_progress', run_attempt=1,
                        created_at='2030-01-02T01:00:00Z',
                        repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
                        head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        self.metadata = dict(id=123, name=self.name, digest=self.digest, expired=False,
                             size_in_bytes=1024, created_at='2030-01-02T01:59:59Z',
                             expires_at='2030-01-09T01:59:59Z', workflow_run=dict(
                                 id=99, head_sha=self.head, repository_id=1416489937,
                                 head_repository_id=1416489937))
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
                        GITHUB_REF='refs/heads/production/boat-p0-p1-20261111',
                        GITHUB_RUN_ID='99', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA=self.head,
                        RACE_AI_FRESH_UPLOAD_RECEIPTS=json.dumps([
                            dict(artifact_id='123', name=self.name, digest=self.digest)]))

    def context(self, **env):
        with patch.dict(os.environ, dict(self.env, **env), clear=True), \
             patch.object(cli.subprocess, 'check_output', return_value=(self.head+'\n').encode()):
            return cli._fresh_upload_context([123], '/fixture',
                lambda endpoint: json.dumps(self.run).encode(), self.now)

    def test_verified_current_upload_metadata_404_then_exact_metadata_succeeds(self):
        context = self.context()
        body = json.dumps(self.metadata).encode()
        with patch.object(cli, '_gh_once', side_effect=[ValueError('VAULT_GITHUB_HTTP_404'), body]) as get, \
             patch.object(cli.time, 'sleep') as pause:
            self.assertEqual(cli._gh(self.endpoint, fresh_uploads=context), body)
        self.assertEqual([call.args for call in get.call_args_list], [(self.endpoint,), (self.endpoint,)])
        pause.assert_called_once_with(2)

    def test_unknown_artifact_zip_run_auth_and_rate_failures_never_gain_retry(self):
        context = self.context()
        cases = [('actions/artifacts/124', 'VAULT_GITHUB_HTTP_404'),
                 (self.endpoint+'/zip', 'VAULT_GITHUB_HTTP_404'),
                 ('actions/runs/99', 'VAULT_GITHUB_HTTP_404')]
        cases += [(self.endpoint, 'VAULT_GITHUB_HTTP_'+str(status)) for status in (401, 403, 429)]
        for endpoint, reason in cases:
            with self.subTest(endpoint=endpoint, reason=reason), \
                 patch.object(cli, '_gh_once', side_effect=ValueError(reason)) as get, \
                 patch.object(cli.time, 'sleep') as pause:
                with self.assertRaisesRegex(ValueError, reason):
                    cli._gh(endpoint, fresh_uploads=context)
                get.assert_called_once(); pause.assert_not_called()

    def test_expired_context_no_longer_retries_404(self):
        with patch.object(cli.time, 'monotonic', return_value=100):
            context = self.context()
        with patch.object(cli.time, 'monotonic', return_value=161), \
             patch.object(cli, '_gh_once', side_effect=ValueError('VAULT_GITHUB_HTTP_404')) as get, \
             patch.object(cli.time, 'sleep') as pause:
            with self.assertRaisesRegex(ValueError, 'VAULT_GITHUB_HTTP_404'):
                cli._gh(self.endpoint, fresh_uploads=context)
            get.assert_called_once(); pause.assert_not_called()

    def test_recovered_wrong_digest_name_run_head_or_clock_keeps_hold(self):
        context = self.context()
        cases = [dict(digest='sha256:'+'c'*64), dict(name='boat-national-cutoff-100-cycle-07'),
                 dict(workflow_run=dict(self.metadata['workflow_run'], id=100)),
                 dict(workflow_run=dict(self.metadata['workflow_run'], head_sha='c'*40)),
                 dict(created_at='2030-01-02T00:59:59Z'), dict(size_in_bytes=0), dict(expired=True)]
        for change in cases:
            with self.subTest(change=change), patch.object(cli, '_gh_once',
                    return_value=json.dumps(dict(self.metadata, **change)).encode()) as get, \
                 patch.object(cli.time, 'sleep') as pause:
                with self.assertRaisesRegex(ValueError, 'VAULT_FRESH_UPLOAD_'):
                    cli._gh(self.endpoint, fresh_uploads=context)
                get.assert_called_once(); pause.assert_not_called()

    def test_untrusted_context_or_receipt_cannot_enable_404_retry(self):
        for field, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_RUN_ATTEMPT', '2'),
                             ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_SHA', 'c'*40),
                             ('GITHUB_REPOSITORY', 'other/repo'),
                             ('RACE_AI_FRESH_UPLOAD_RECEIPTS', '[]'),
                             ('RACE_AI_FRESH_UPLOAD_RECEIPTS', json.dumps([dict(
                                 artifact_id='124', name=self.name, digest=self.digest)]))]:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, 'VAULT_FRESH_UPLOAD_'):
                    self.context(**{field: value})
        for change in (dict(run_attempt=2), dict(status='completed'),
                       dict(head_sha='c'*40), dict(head_repository=dict(id=1, full_name='other/repo'))):
            with self.subTest(run=change):
                original = self.run
                self.run = dict(original, **change)
                try:
                    with self.assertRaisesRegex(ValueError, 'VAULT_FRESH_UPLOAD_'):
                        self.context()
                finally:
                    self.run = original


if __name__=="__main__":
    unittest.main()
