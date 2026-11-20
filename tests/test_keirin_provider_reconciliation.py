"""Real local Git and invented transport only; no provider or external writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
import json
import subprocess
import unittest

from race_ai import keirin_provider_reconciliation as reconcile
from race_ai import keirin_github_provider_stop as stop


NOW = datetime(2026, 11, 21, 2, 0, tzinfo=timezone(timedelta(hours=9)))
MARKER = dict(schema=stop.SCHEMA, day_jst='2026-11-20', code=stop.DENIED,
              observed_at='2026-11-20T09:24:45.201674+00:00')
MARKER_RAW = (json.dumps(MARKER, sort_keys=True, separators=(',', ':'))+'\n').encode()


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.origin = self.root/'origin.git'
        self.writer = self.root/'writer'; self.other = self.root/'other'
        git(self.root, 'init', '--bare', '-b', reconcile.archive.BRANCH, str(self.origin))
        git(self.root, 'clone', str(self.origin), str(self.writer))
        git(self.writer, 'config', 'user.name', 'Synthetic fixture')
        git(self.writer, 'config', 'user.email', 'fixture@example.invalid')
        path = self.writer/reconcile.MARKER_PATH
        path.parent.mkdir(parents=True); path.write_bytes(MARKER_RAW)
        (self.writer/'original.enc').write_bytes(b'SYNTHETIC ORIGINAL PRESERVE\n')
        git(self.writer, 'add', '.'); git(self.writer, 'commit', '-m', 'synthetic retained state')
        git(self.writer, 'push', 'origin', reconcile.archive.BRANCH)
        git(self.root, 'clone', str(self.origin), str(self.other))
        git(self.other, 'config', 'user.name', 'Synthetic fixture')
        git(self.other, 'config', 'user.email', 'fixture@example.invalid')
        self.source = git(self.writer, 'rev-parse', 'HEAD')
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937', GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA=self.source,
            GITHUB_RUN_ID='123456789', GITHUB_RUN_ATTEMPT='1',
            GITHUB_WORKFLOW_REF=reconcile.WORKFLOW_REF, CANARY_RECONCILE='true',
            RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true')
        p = patch.dict(reconcile.os.environ, env, clear=False); p.start(); self.addCleanup(p.stop)
        remote = reconcile.archive._remote
        p = patch.object(reconcile.archive, '_remote', side_effect=lambda repo, **kw:
            remote(repo, synthetic_local=True)); p.start(); self.addCleanup(p.stop)

    def begin(self, repo=None, now=NOW, **kw):
        return reconcile.begin(repo=repo or self.writer, now=now,
                               source_commit=self.source, **kw)

    def read(self, path):
        return git(self.origin, 'show', reconcile.archive.BRANCH+':'+path)

    def mutate_remote(self, path, raw):
        git(self.other, 'fetch', 'origin', reconcile.archive.BRANCH)
        git(self.other, 'reset', '--hard', 'origin/'+reconcile.archive.BRANCH)
        target = self.other/path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        git(self.other, 'add', '--', path); git(self.other, 'commit', '-m', 'synthetic external append')
        git(self.other, 'push', 'origin', reconcile.archive.BRANCH)

    def request(self, lease, purpose, now=NOW):
        host, path, method = reconcile.ROUTES[purpose]
        lease.before_request(purpose=purpose, method=method, url='https://'+host+path, now=now)

    def test_claim_is_remote_and_read_back_before_request_and_does_not_release_stop(self):
        self.assertEqual(sha1(b'blob '+str(len(MARKER_RAW)).encode()+b'\0'+MARKER_RAW).hexdigest(),
                         reconcile.MARKER_BLOB)
        lease = self.begin()
        claim = json.loads(self.read(reconcile.CLAIM_PATH))
        self.assertEqual(claim['race_id'], '202611208105')
        self.assertEqual(claim['source_commit'], self.source)
        self.assertIs(claim['general_source_release'], False)
        self.assertIs(claim['legacy_incident_resolved'], False)
        self.assertEqual(json.loads(self.read(reconcile.MARKER_PATH)), MARKER)
        self.assertEqual(stop.read_for_observed_day(repo=self.writer, day='2026-11-21'), MARKER)
        self.assertEqual(self.read('original.enc'), 'SYNTHETIC ORIGINAL PRESERVE')
        self.assertEqual(lease.request_count, 0)
        self.request(lease, reconcile.PURPOSES[0])
        self.assertEqual(lease.request_count, 1)

    def test_trusted_dispatch_first_attempt_real_day_and_code_pin_are_required(self):
        changes = [dict(GITHUB_EVENT_NAME='schedule'), dict(GITHUB_RUN_ATTEMPT='2'),
            dict(GITHUB_REF='refs/heads/untrusted'), dict(GITHUB_REPOSITORY_ID='1'),
            dict(GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/unrelated.yml@refs/heads/main'),
            dict(CANARY_RECONCILE='false'),
            dict(GITHUB_SHA='f'*40), dict(RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='false')]
        for change in changes:
            with self.subTest(change=change), patch.dict(reconcile.os.environ, change):
                with self.assertRaises(reconcile.ReconciliationError): self.begin()
        for value in (NOW-timedelta(days=1), NOW+timedelta(days=1), NOW.replace(tzinfo=None)):
            with self.subTest(now=value), self.assertRaises(reconcile.ReconciliationError):
                self.begin(now=value)
        with self.assertRaises(reconcile.ReconciliationError): self.begin(race_id='202611208106')
        with self.assertRaises(subprocess.CalledProcessError): self.read(reconcile.CLAIM_PATH)

    def test_lease_allows_only_exact_order_once_and_closes_on_any_invalid_request(self):
        lease = self.begin()
        self.request(lease, reconcile.PURPOSES[0])
        with self.assertRaises(reconcile.ReconciliationError):
            self.request(lease, reconcile.PURPOSES[0])
        with self.assertRaises(reconcile.ReconciliationError):
            self.request(lease, reconcile.PURPOSES[1])
        self.assertEqual(lease.request_count, 1)
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_off_route_query_and_identity_changes_never_get_transport_permission(self):
        lease = self.begin()
        with self.assertRaises(reconcile.ReconciliationError):
            lease.before_request(purpose='OFFICIAL_CALENDAR', method='GET',
                url='https://keirin.jp/sp/raceschedule?retry=private', now=NOW)
        with self.assertRaises(reconcile.ReconciliationError):
            self.request(lease, 'OFFICIAL_CALENDAR')
        self.assertEqual(lease.request_count, 0)

    def test_expired_or_wrong_repo_context_stays_closed(self):
        lease = self.begin()
        with self.assertRaises(reconcile.ReconciliationError):
            lease.assert_active(repo=self.writer, now=NOW+timedelta(seconds=reconcile.LEASE_SECONDS+1))
        with self.assertRaises(reconcile.ReconciliationError):
            lease.assert_active(repo=self.writer, now=NOW)
        self.assertEqual(lease.request_count, 0)

    def test_elapsed_time_during_git_check_expires_even_with_unchanged_caller_clock(self):
        with patch.object(reconcile.time, 'monotonic', return_value=100.0):
            lease = self.begin()
        with patch.object(reconcile.time, 'monotonic',
                          side_effect=[100.0, 100.0+reconcile.LEASE_SECONDS]):
            with self.assertRaises(reconcile.ReconciliationError):
                self.request(lease, reconcile.PURPOSES[0], now=NOW)
        self.assertEqual(lease.request_count, 0)

    def test_slow_claim_readback_never_grants_an_already_expired_lease(self):
        with patch.object(reconcile.time, 'monotonic',
                          side_effect=[100.0, 100.0+reconcile.LEASE_SECONDS]):
            with self.assertRaises(reconcile.ReconciliationError): self.begin()
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_changed_legacy_marker_is_not_an_admitted_reconciliation(self):
        changed = dict(MARKER, observed_at='2026-11-20T10:00:00+00:00')
        self.mutate_remote(reconcile.MARKER_PATH, json.dumps(changed).encode())
        with self.assertRaises(reconcile.ReconciliationError): self.begin()
        with self.assertRaises(subprocess.CalledProcessError): self.read(reconcile.CLAIM_PATH)

    def test_any_additional_stop_blocks_begin_and_an_existing_lease(self):
        lease = self.begin()
        extra = dict(MARKER, day_jst='2026-11-21', observed_at=NOW.isoformat())
        self.mutate_remote(stop.ROOT+'/2026-11-21.json', json.dumps(extra).encode())
        with self.assertRaises(reconcile.ReconciliationError): self.request(lease, reconcile.PURPOSES[0])
        with self.assertRaises(reconcile.ReconciliationError): self.begin()
        self.assertEqual(lease.request_count, 0)
        # An actual new refusal may still be recorded as a failed attempt.
        lease.finish(state='FAILED', now=NOW)
        self.assertEqual(json.loads(self.read(reconcile.FINISH_PATH))['state'], 'FAILED')

    def test_same_run_concurrent_claimants_grant_exactly_one_lease(self):
        original = reconcile.archive._cmd; gate = Barrier(2)
        def command(repo, *args, **kw):
            if args and args[0] == 'push': gate.wait(timeout=15)
            return original(repo, *args, **kw)
        def begin(repo):
            try: return self.begin(repo=repo)
            except reconcile.ReconciliationError: return None
        with patch.object(reconcile.archive, '_cmd', side_effect=command):
            with ThreadPoolExecutor(max_workers=2) as pool:
                leases = list(pool.map(begin, (self.writer, self.other)))
        self.assertEqual(sum(lease is not None for lease in leases), 1)
        self.assertEqual(sum(lease.request_count for lease in leases if lease), 0)

    def test_lost_push_acknowledgement_consumes_claim_without_granting_a_lease(self):
        original = reconcile.archive._cmd
        def command(repo, *args, **kw):
            value = original(repo, *args, **kw)
            if args and args[0] == 'push':
                raise reconcile.archive.GitCipherArchiveError('SYNTHETIC_LOST_ACK')
            return value
        with patch.object(reconcile.archive, '_cmd', side_effect=command):
            with self.assertRaises(reconcile.ReconciliationError): self.begin()
        self.assertEqual(json.loads(self.read(reconcile.CLAIM_PATH))['race_id'], reconcile.RACE)
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_readback_failure_never_grants_lease_and_rerun_stays_closed(self):
        original = reconcile.archive._refresh; calls = 0
        def refresh(repo):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise reconcile.archive.GitCipherArchiveError('SYNTHETIC_READBACK_FAILED')
            return original(repo)
        with patch.object(reconcile.archive, '_refresh', side_effect=refresh):
            with self.assertRaises(reconcile.ReconciliationError): self.begin()
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_complete_sequence_finish_is_safe_append_only_and_never_general_release(self):
        lease = self.begin()
        for purpose in reconcile.PURPOSES: self.request(lease, purpose)
        lease.finish(state='FOUR_ARMS_ARCHIVED', now=NOW)
        finish = json.loads(self.read(reconcile.FINISH_PATH))
        self.assertEqual(finish['requests_consumed'], 8)
        self.assertEqual(finish['state'], 'FOUR_ARMS_ARCHIVED')
        self.assertIs(finish['general_source_release'], False)
        self.assertIs(finish['legacy_incident_resolved'], False)
        self.assertEqual(json.loads(self.read(reconcile.MARKER_PATH)), MARKER)
        self.assertFalse(any(s in json.dumps(finish).lower() for s in ('encp', 'cookie', 'token', 'private')))
        with self.assertRaises(reconcile.ReconciliationError): self.begin()
        with self.assertRaises(reconcile.ReconciliationError): self.request(lease, reconcile.PURPOSES[0])

    def test_order_only_can_finish_after_seven_steps(self):
        lease = self.begin()
        for purpose in reconcile.PURPOSES[:7]: self.request(lease, purpose)
        lease.finish(state='ORDER_ONLY_ARCHIVED', now=NOW)
        self.assertEqual(json.loads(self.read(reconcile.FINISH_PATH))['requests_consumed'], 7)

    def test_optional_guide_denial_keeps_order_archive_and_new_stop(self):
        lease = self.begin()
        for purpose in reconcile.PURPOSES: self.request(lease, purpose)
        extra = dict(MARKER, day_jst='2026-11-21', observed_at=NOW.isoformat())
        path = stop.ROOT+'/2026-11-21.json'
        self.mutate_remote(path, json.dumps(extra).encode())
        lease.finish(state='ORDER_ONLY_ARCHIVED', now=NOW)
        self.assertEqual(json.loads(self.read(reconcile.FINISH_PATH))['state'], 'ORDER_ONLY_ARCHIVED')
        self.assertEqual(json.loads(self.read(path)), extra)
        self.assertEqual(json.loads(self.read(reconcile.MARKER_PATH)), MARKER)
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_failed_finish_without_requests_never_reopens_attempt(self):
        lease = self.begin()
        lease.finish(state='FAILED', now=NOW)
        self.assertEqual(json.loads(self.read(reconcile.FINISH_PATH))['requests_consumed'], 0)
        with self.assertRaises(reconcile.ReconciliationError): self.begin()

    def test_wrong_method_out_of_order_external_host_and_alternate_endpoint_are_rejected(self):
        lease = self.begin()
        # Each failure must be checked without creating more than one claim.
        # A rejected request permanently consumes the process-local lease.
        attempts = [dict(purpose='OFFICIAL_JSON_CALENDAR', method='GET', url='https://keirin.jp/pc/json'),
            dict(purpose='OFFICIAL_CALENDAR', method='POST', url='https://keirin.jp/sp/raceschedule'),
            dict(purpose='CALENDAR_SCRIPT', method='GET', url='https://keirin.jp/sp/static/js/SJ0201.js'),
            dict(purpose='OFFICIAL_CALENDAR', method='GET', url='https://www.winticket.jp/keirin/racecard')]
        for args in attempts:
            with self.subTest(args=args), self.assertRaises(reconcile.ReconciliationError):
                lease.before_request(**args, now=NOW)
        self.assertEqual(lease.request_count, 0)

    def test_wrong_repository_context_and_changed_run_cannot_use_a_valid_claim(self):
        lease = self.begin()
        with self.assertRaises(reconcile.ReconciliationError):
            lease.assert_active(repo=self.other, now=NOW)
        with patch.dict(reconcile.os.environ, GITHUB_RUN_ID='999999999'):
            with self.assertRaises(reconcile.ReconciliationError): self.request(lease, reconcile.PURPOSES[0])
        self.assertEqual(lease.request_count, 0)


if __name__ == '__main__': unittest.main()
