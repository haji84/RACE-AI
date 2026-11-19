"""Read-only GitHub evidence acquisition uses exact API paths and no credential redirects."""
from copy import deepcopy
import json
from io import BytesIO
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from tests.test_keirin_github_origin_evidence import evidence_fixture


class Response(BytesIO):
    def __init__(self, payload, *, url, content_type='application/json'):
        super().__init__(payload)
        self.status = 200
        self.url = url
        self.headers = {'Content-Type': content_type}


class GithubEvidenceTransport(unittest.TestCase):
    def module(self):
        from race_ai import keirin_github_evidence_client
        return keirin_github_evidence_client

    def test_invalid_run_id_never_reaches_transport(self):
        module = self.module()
        calls = []
        client = module.GitHubEvidenceClient(open_request=lambda *a, **kw: calls.append(a))
        with self.assertRaisesRegex(ValueError, 'RUN_ID'):
            client.read_run_bundle('../secrets')
        self.assertEqual(calls, [])

    def test_provider_auth_failure_does_not_retry_or_echo_token(self):
        module = self.module()
        calls = []
        def denied(request, **kwargs):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 403, 'secret-test-token', {}, None)
        client = module.GitHubEvidenceClient(token='secret-test-token', open_request=denied)
        with self.assertRaisesRegex(ValueError, '^GITHUB_EVIDENCE_HTTP_403$'):
            client.read_run_bundle('100')
        self.assertEqual(len(calls), 1)

    def test_denial_is_latched_across_races_and_exposed_without_secrets(self):
        module = self.module()
        for status in (401, 403, 429):
            with self.subTest(status=status):
                calls = []
                def denied(request, **kwargs):
                    calls.append(request.full_url)
                    raise HTTPError(request.full_url, status,
                                    'private-token-value', {}, None)
                client = module.GitHubEvidenceClient(token='private-token-value',
                                                     open_request=denied)
                for run in ('100', '101'):
                    with self.assertRaisesRegex(ValueError,
                            '^GITHUB_EVIDENCE_HTTP_' + str(status) + '$'):
                        client.read_run_bundle(run)
                self.assertEqual(len(calls), 1)
                self.assertEqual(client.stopped_reason,
                                 'GITHUB_EVIDENCE_HTTP_' + str(status))

    def test_invalid_secret_header_is_rejected_without_transport_or_token_text(self):
        module = self.module()
        calls = []
        for token in ('private-token\nsecond-line', 'private-token\rheader', 123):
            with self.subTest(token_type=type(token).__name__):
                with self.assertRaisesRegex(ValueError, '^GITHUB_EVIDENCE_TOKEN_INVALID$'):
                    module.GitHubEvidenceClient(token=token,
                        open_request=lambda *args, **kwargs: calls.append(args))
        self.assertEqual(calls, [])

    def test_redirect_cannot_forward_authorization_or_go_to_arbitrary_host(self):
        module = self.module()
        handler = module.ArtifactRedirect()
        req = Request('https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/1/zip')
        req.add_unredirected_header('Authorization', 'Bearer private-test-token')
        target = 'https://example.blob.core.windows.net/archive.zip?sig=fixture'
        redirected = handler.redirect_request(req, None, 302, 'Found', {}, target)
        self.assertIsNone(redirected.get_header('Authorization'))
        with self.assertRaisesRegex(ValueError, 'REDIRECT'):
            handler.redirect_request(req, None, 302, 'Found', {}, 'https://attacker.invalid/file')
        with self.assertRaisesRegex(ValueError, '^GITHUB_ARTIFACT_REDIRECT_NOT_TRUSTED$'):
            handler.redirect_request(req, None, 302, 'Found', {},
                                     'https://example.blob.core.windows.net:private-token/file')

    def test_duplicate_named_job_or_artifact_never_selects_arbitrarily(self):
        module = self.module()
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            module.only_named([{'name':'producer'},{'name':'producer'}], 'producer')

    def test_duplicate_api_json_fields_do_not_silently_override_identity(self):
        module = self.module()
        def response(request, **kwargs):
            return Response(b'{"id":123,"id":456}', url=request.full_url)
        client = module.GitHubEvidenceClient(open_request=response)
        with self.assertRaisesRegex(ValueError, 'JSON'):
            client.json('/actions/runs/123')

    def test_metadata_final_url_cannot_be_silently_replaced(self):
        module = self.module()
        def response(request, **kwargs):
            return Response(b'{"id":123}', url='https://attacker.invalid/run')
        client = module.GitHubEvidenceClient(open_request=response)
        with self.assertRaisesRegex(ValueError, 'RESPONSE_URL'):
            client.json('/actions/runs/123')

    def run_client(self, *, wrong_lineage=False, corrupt_archive=False, rerun=False,
                   ambiguous_job=False):
        module = self.module()
        producer, readback = evidence_fixture()
        if wrong_lineage:
            readback['artifact']['workflow_run']['id'] = 999
        run_id = producer['run']['id']
        api = module.API
        jobs = [producer['job'], readback['job']]
        latest_jobs = jobs
        if rerun:
            producer['run']['run_attempt'] = 2
            producer['run']['status'] = 'in_progress'
            producer['run']['conclusion'] = None
            later = deepcopy(producer['job'])
            later.update(id=1003, url=f'{api}/actions/jobs/1003', run_attempt=2,
                         started_at='2026-11-18T02:00:00Z',
                         completed_at='2026-11-18T02:01:00Z')
            jobs = jobs + [later]
            latest_jobs = [later]
        if ambiguous_job:
            duplicate = deepcopy(producer['job'])
            duplicate.update(id=1004, url=f'{api}/actions/jobs/1004')
            jobs = jobs + [duplicate]
            latest_jobs = jobs
        payloads = {
            f'{api}/actions/runs/{run_id}': producer['run'],
            f'{api}/actions/runs/{run_id}/jobs?per_page=100': {
                'total_count': len(latest_jobs), 'jobs': latest_jobs},
            f'{api}/actions/runs/{run_id}/jobs?per_page=100&filter=all': {
                'total_count': len(jobs), 'jobs': jobs},
            f'{api}/actions/runs/{run_id}/artifacts?per_page=100': {
                'total_count': 2,
                'artifacts': [producer['artifact'], readback['artifact']]},
        }
        archives = {packet['artifact']['archive_download_url']: packet['archive_bytes']
                    for packet in (producer, readback)}
        if corrupt_archive:
            archives[readback['artifact']['archive_download_url']] += b'corrupt'
        calls = []
        def response(request, **kwargs):
            calls.append(request.full_url)
            if request.full_url in archives:
                return Response(archives[request.full_url],
                                url='https://fixture.blob.core.windows.net/archive.zip',
                                content_type='application/zip')
            return Response(json.dumps(payloads[request.full_url]).encode(),
                            url=request.full_url)
        return module.GitHubEvidenceClient(token='fixture-token', open_request=response), calls

    def test_actual_response_shapes_download_original_bytes_then_cache_without_new_gets(self):
        client, calls = self.run_client()
        bundles = client.read_run_bundle('123456')
        self.assertEqual(set(bundles), {'producer', 'readback'})
        self.assertEqual(bundles['producer']['artifact']['id'], 2001)
        self.assertTrue(bundles['readback']['archive_bytes'].startswith(b'PK'))
        self.assertEqual(len(calls), 5)
        client.read_run_bundle('123456')
        self.assertEqual(len(calls), 5)

    def test_cross_run_artifact_is_rejected_before_any_binary_download(self):
        client, calls = self.run_client(wrong_lineage=True)
        with self.assertRaisesRegex(ValueError, 'LINEAGE'):
            client.read_run_bundle('123456')
        self.assertEqual(len(calls), 3)

    def test_bad_archive_bytes_never_become_a_durable_origin_bundle(self):
        client, calls = self.run_client(corrupt_archive=True)
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_DIGEST'):
            client.read_run_bundle('123456')
        self.assertEqual(len(calls), 5)

    def test_later_rerun_fetches_original_jobs_and_matches_the_artifact_creation(self):
        from race_ai.keirin_github_origin_evidence import verify_origin_evidence
        from tests.test_keirin_github_origin_evidence import CIPHER, DIGEST, HEAD, RID
        client, calls = self.run_client(rerun=True)
        bundles = client.read_run_bundle('123456')
        self.assertEqual(bundles['producer']['job']['id'], 1001)
        self.assertEqual(bundles['readback']['job']['id'], 1002)
        self.assertIn('filter=all', calls[1])
        result = verify_origin_evidence(race_id=RID, raw_cipher=CIPHER,
            expected_cipher_sha256=DIGEST, official_cutoff_at='2026-11-18T01:10:00Z',
            expected_producer_run_id='123456', expected_producer_commit=HEAD, **bundles)
        self.assertEqual(result['state'], 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED')

    def test_two_successful_jobs_covering_one_upload_are_rejected_before_download(self):
        client, calls = self.run_client(ambiguous_job=True)
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            client.read_run_bundle('123456')
        self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
