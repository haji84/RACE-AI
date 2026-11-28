"""Synthetic server metadata only; no real forecast timing attestation."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module, util
from io import BytesIO
import json
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from race_ai.keirin_github_evidence_client import API, GitHubEvidenceClient
from tests.test_keirin_github_origin_evidence import evidence_fixture, report_bytes


def zip_bytes(members):
    stream = BytesIO()
    with ZipFile(stream, 'w', compression=ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return stream.getvalue()


def packet(run_id='123456', *, report=None, name=None, minute=1, head='a' * 40):
    value = deepcopy(evidence_fixture()[0])
    run = value['run']
    run.update(id=int(run_id), url=API + '/actions/runs/' + run_id,
        path='.github/workflows/keirin-result-live.yml', event='workflow_dispatch',
        created_at='2030-01-15T02:00:00Z', run_started_at='2030-01-15T02:00:00Z', head_sha=head)
    value['job'].update(id=int(run_id) + 1000, run_id=int(run_id), run_url=run['url'],
        url=API + '/actions/jobs/' + str(int(run_id) + 1000), name='observe-results',
        runner_id=int(run_id) + 100000, head_sha=head,
        started_at=f'2030-01-15T02:{minute:02d}:00Z',
        completed_at=f'2030-01-15T02:{minute+1:02d}:00Z')
    raw = zip_bytes({'summary.json': report_bytes(report or {'schema': 'fixture'})})
    ident = int(run_id) + 2000
    value['artifact'].update(id=ident, url=API + '/actions/artifacts/' + str(ident),
        archive_download_url=API + '/actions/artifacts/' + str(ident) + '/zip',
        name=name or 'keirin-result-live-receipt-' + run_id,
        created_at=f'2030-01-15T02:{minute:02d}:30Z', expired=False,
        workflow_run=dict(id=int(run_id), repository_id=1416489937, head_repository_id=1416489937,
            head_branch='main', head_sha=run['head_sha']),
        digest='sha256:' + sha256(raw).hexdigest(), size_in_bytes=len(raw))
    value['archive_bytes'] = raw
    return value


class APIResponse(BytesIO):
    status = 200
    def __init__(self, raw, url):
        super().__init__(raw); self.url = url


class FixtureAPI:
    def __init__(self, packets):
        self.packets = packets; self.calls = []
        self.client = GitHubEvidenceClient(token='', open_request=self.open)

    def open(self, request, timeout):
        url = request.full_url; self.calls.append(url)
        for value in self.packets:
            run = value['run']; same = [p for p in self.packets if p['run']['id'] == run['id']]
            if url == run['url']:
                raw = report_bytes(run); break
            if url == run['url'] + '/jobs?per_page=100&filter=all':
                jobs = {p['job']['id']: p['job'] for p in same}
                raw = report_bytes({'total_count': len(jobs), 'jobs': list(jobs.values())}); break
            if url == run['url'] + '/artifacts?per_page=100':
                raw = report_bytes({'total_count': len(same), 'artifacts': [p['artifact'] for p in same]}); break
            if url == value['artifact']['archive_download_url']:
                raw = value['archive_bytes']; break
        else:
            raise AssertionError('Unexpected synthetic request')
        return APIResponse(raw, url)


class FutureReadbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('scripts.keirin_dt_r1_future_readback'),
                             'Independent future readback is not implemented')
        self.api = import_module('scripts.keirin_dt_r1_future_readback')

    def test_report_uses_existing_server_artifact_verifier_and_canonical_main(self):
        fixture = FixtureAPI([packet()])
        verified = self.api.fetch_report(fixture.client, '123456')
        self.assertEqual(verified['run_id'], 123456)
        self.assertEqual(verified['report'], {'schema': 'fixture'})
        self.assertEqual(verified['completed_at'].isoformat(), '2030-01-15T02:02:00+00:00')
        self.assertEqual(len(fixture.calls), 4)

    def test_fork_event_branch_failed_job_and_expired_artifact_are_refused(self):
        changes = [('run', 'head_branch', 'research'), ('run', 'event', 'schedule'),
                   ('run', 'repository', {'id': 1, 'full_name': 'fork/RACE-AI'}),
                   ('job', 'conclusion', 'failure'), ('artifact', 'expired', True)]
        for section, field, value in changes:
            changed = packet(); changed[section][field] = value
            fixture = FixtureAPI([changed])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.api.fetch_report(fixture.client, '123456')

    def test_ambiguous_receipt_and_mutated_zip_digest_are_refused(self):
        value = packet(); duplicate = deepcopy(value); duplicate['artifact']['id'] += 1
        fixture = FixtureAPI([value, duplicate])
        with self.assertRaises(ValueError):
            self.api.fetch_report(fixture.client, '123456')
        value = packet(); value['archive_bytes'] += b'changed'
        with self.assertRaises(ValueError):
            self.api.fetch_report(FixtureAPI([value]).client, '123456')

    def test_run_id_is_numeric_and_never_an_arbitrary_api_path(self):
        for run_id in ('0', '01', '1/../../', '123?secret', '1' * 19, 123):
            fixture = FixtureAPI([packet()])
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.api.fetch_report(fixture.client, run_id)
            self.assertEqual(fixture.calls, [])

    def produced(self):
        case = import_module('tests.test_keirin_dt_r1_future_shadow').FutureShadowTests
        if not hasattr(case, 'private'):
            case.setUpClass()
        producer = case(); producer.setUp(); self.addCleanup(producer.doCleanups)
        report = producer.produce()
        first = packet('456', report=report, head='c' * 40)
        cipher = deepcopy(first)
        cipher['artifact'].update(id=2457, name='keirin-dt-r1-future-cipher-456',
            url=API + '/actions/artifacts/2457', archive_download_url=API + '/actions/artifacts/2457/zip')
        raw = zip_bytes({path.name: path.read_bytes() for path in producer.output.iterdir()})
        cipher['archive_bytes'] = raw
        cipher['artifact'].update(digest='sha256:' + sha256(raw).hexdigest(), size_in_bytes=len(raw))
        return producer, first, cipher

    def test_verified_producer_opens_only_exact_temporary_cipher_inventory(self):
        producer, first, cipher = self.produced()
        client = FixtureAPI([first, cipher]).client
        with self.api.verified_producer('456', client=client) as verified:
            folder = verified['directory']
            self.assertEqual(verified['manifest'], producer.manifest())
            self.assertEqual({p.name for p in folder.iterdir()}, {p.name for p in producer.output.iterdir()})
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in folder.iterdir()))
        self.assertFalse(folder.exists())

    def test_cipher_artifact_extra_member_and_wrong_manifest_are_refused(self):
        producer, first, cipher = self.produced()
        original = deepcopy(cipher)
        for kind in ('extra', 'manifest'):
            cipher = deepcopy(original)
            members = {p.name: p.read_bytes() for p in producer.output.iterdir()}
            if kind == 'extra': members['private-source.txt'] = b'PRIVATE_SECRET'
            else: members['manifest.json'] += b'changed'
            raw = zip_bytes(members); cipher['archive_bytes'] = raw
            cipher['artifact'].update(digest='sha256:' + sha256(raw).hexdigest(), size_in_bytes=len(raw))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                with self.api.verified_producer('456', client=FixtureAPI([first, cipher]).client):
                    self.fail('Invalid inventory was admitted')

    def test_readback_is_safe_cipher_only_and_does_not_self_certify_server_timing(self):
        producer, first, cipher = self.produced()
        report = self.api.readback('456', reader_run_id='789', reader_code_commit='d' * 40,
            client=FixtureAPI([first, cipher]).client,
            clock=lambda: datetime.fromisoformat('2030-01-15T02:03:30+00:00'))
        self.assertEqual(report['registered_races'], 78)
        self.assertEqual(report['verified_cipher_files'], 1)
        self.assertFalse(report['independent_server_timing_verified'])
        self.assertFalse(report['owner_decryption_verified'])
        self.assertFalse(report['source_authenticated'])
        self.assertFalse(report['production_promoted'])
        self.assertEqual(report['provider_source_requests'], 0)
        self.assertEqual(report['confidence'], 'HOLD')
        self.assertNotIn(producer.rid, json.dumps(report))
        self.assertNotIn('trifectas', json.dumps(report))
        with self.assertRaises(ValueError):
            self.api.readback('456', reader_run_id='456', reader_code_commit='d' * 40,
                client=FixtureAPI([first, cipher]).client)

    def test_independent_server_proof_binds_both_runs_and_actual_completion_margin(self):
        producer, first, cipher = self.produced()
        report = self.api.readback('456', reader_run_id='789', reader_code_commit='d' * 40,
            client=FixtureAPI([first, cipher]).client,
            clock=lambda: datetime.fromisoformat('2030-01-15T02:03:30+00:00'))
        reader = packet('789', report=report, head='d' * 40, minute=3)
        client = FixtureAPI([first, cipher, reader]).client
        with self.api.verified_producer('456', client=client) as verified:
            proof = self.api.verify_readback(verified, '789', client=client)
            self.assertEqual(proof['latest_server_evidence_at'], '2030-01-15T02:04:00+00:00')
            self.assertEqual(len(proof['eligible_slots']), 1)
        reader['job']['completed_at'] = '2030-01-15T03:33:00Z'
        client = FixtureAPI([first, cipher, reader]).client
        with self.api.verified_producer('456', client=client) as verified:
            proof = self.api.verify_readback(verified, '789', client=client)
            self.assertEqual(proof['eligible_slots'], [])
            self.assertEqual(proof['held_slots'], {report['records'][0]['slot_sha256']: 'SERVER_READBACK_AFTER_T15'})

    def test_archived_batch_does_not_override_current_github_witness(self):
        _, first, cipher = self.produced()
        receipt = self.api.readback('456', reader_run_id='789', reader_code_commit='d' * 40,
            client=FixtureAPI([first, cipher]).client,
            clock=lambda: datetime.fromisoformat('2030-01-15T02:03:30+00:00'))
        readback = packet('789', report=receipt, head='d' * 40, minute=3)
        client = FixtureAPI([first, cipher, readback]).client
        with self.api.verified_producer('456', client=client) as verified:
            manifest, digest = verified['manifest'], verified['manifest_sha256']
            proof = self.api.verify_readback(verified, '789', client=client)
        self.api.verify_saved_batch(manifest, proof, digest, client=client)
        altered = dict(proof, latest_server_evidence_at='2030-01-15T02:03:31+00:00')
        with self.assertRaisesRegex(ValueError, 'ARCHIVED_READBACK_CHANGED'):
            self.api.verify_saved_batch(manifest, altered, digest, client=client)

    def test_swapped_readback_identity_cannot_certify_a_saved_candidate(self):
        _, first, cipher = self.produced()
        report = self.api.readback('456', reader_run_id='789', reader_code_commit='d' * 40,
            client=FixtureAPI([first, cipher]).client,
            clock=lambda: datetime.fromisoformat('2030-01-15T02:03:30+00:00'))
        report['manifest_sha256'] = '0' * 64
        reader = packet('789', report=report, head='d' * 40, minute=3)
        client = FixtureAPI([first, cipher, reader]).client
        with self.api.verified_producer('456', client=client) as verified:
            with self.assertRaises(ValueError):
                self.api.verify_readback(verified, '789', client=client)

    def test_zip_traversal_symlink_and_expanded_budget_fail_before_extraction(self):
        for name in ('../manifest.json', '/manifest.json', 'a\\manifest.json'):
            with TemporaryDirectory() as folder, self.subTest(name=name), self.assertRaises(ValueError):
                self.api._extract(zip_bytes({'manifest.json': b'{}', name: b'PRIVATE'}), Path(folder))
        stream = BytesIO()
        with ZipFile(stream, 'w') as zipped:
            member = ZipInfo('manifest.json'); member.external_attr = 0o120777 << 16
            zipped.writestr(member, b'private-link')
        with TemporaryDirectory() as folder, self.assertRaises(ValueError):
            self.api._extract(stream.getvalue(), Path(folder))
        with TemporaryDirectory() as folder, patch.object(self.api, 'MAX_EXPANDED_BYTES', 1), self.assertRaises(ValueError):
            self.api._extract(zip_bytes({'manifest.json': b'{}'}), Path(folder))

    def test_cli_requires_existing_main_manual_job_and_never_echoes_key_or_exception(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/research',
                'RACE_AI_KEIRIN_PRIVATE_RSA_PEM': 'PRIVATE_SENTINEL'}, clear=True), \
                patch.object(self.api, 'readback') as readback, redirect_stdout(output):
            code = self.api.main(['--repo', '.', '--producer-run', '123456'])
            self.assertNotIn('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', os.environ)
        self.assertEqual(code, 2); readback.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertFalse(report['independent_server_timing_verified'])
        self.assertNotIn('PRIVATE_SENTINEL', output.getvalue())


if __name__ == '__main__':
    unittest.main()
