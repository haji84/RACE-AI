"""Public invented AES candidates and service receipts; no actual ZIP/key reads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha256
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT/'owner-source'
sys.path.insert(0, str(OWNER))
import race_ai, scripts, tests
for folder in ('pr64-reference', 'pr72-reference'):
    race_ai.__path__.append(str(OWNER/folder/'race_ai'))
scripts.__path__.append(str(ROOT/'scripts'))
tests.__path__.append(str(OWNER/'tests'))
from race_ai.actions_contract import digest
from race_ai import boat_venue_learning_handoff as learning
from race_ai.boat_private_original_vault import VaultGitRepository
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.all_existing_model_pdca import _score_verified_private_pairs
from tests import test_boat_current_pair_eligibility_audit as pair_fixture

SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
RUN = 44426169530
JOB = 135231474660
CASES = {18: 14488233127, 23: 14491506398, 24: 14492170715}
KEY = bytes(range(32))
NOW = datetime(2030, 4, 1, 12, 10, tzinfo=timezone.utc)
PATH = ROOT/'scripts/boat_private_venue_retention_audit.py'
if PATH.exists():
    spec = importlib.util.spec_from_file_location('main_private_venue_retention_audit', PATH)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
else:
    audit = None


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def packed(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return stream.getvalue()


def oid(raw):
    return sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


class MemoryReadOnlyGit:
    """Public remote-object oracle using the real selected-OID/size validator."""
    ref = 'state/boat-pdca-transfer'
    fetch_url = push_url = 'https://github.com/haji84/RACE-AI'
    def __init__(self, root, files):
        self.repo = root/'independent.git'
        self.files = dict(files)
        self.head_calls = self.fetch_calls = self.prefetch_calls = 0
        self.publication_calls = 0
        self.current = 'd'*40
        self.stored_commit = self.current
        self.move_after_observation = False
        self.corrupt_read = False
        self.corrupt_size = False
        self.mode = b'100644 blob '
    def head(self):
        self.head_calls += 1
        observed = self.current
        if self.move_after_observation:
            self.current = 'e'*40
        return observed
    def fetch(self, commit):
        assert commit == self.stored_commit
        self.fetch_calls += 1
    def _reject_rewrites(self, *args):
        pass
    def _check_remote(self):
        pass
    def _run(self, args, *, body=None, **options):
        args = list(args)
        if args and args[0] == '--no-lazy-fetch':
            args.pop(0)
        if args[:2] == ['cat-file', '-t']:
            assert args[2] == self.stored_commit
            return b'commit\n'
        if args[:2] == ['ls-tree', '-z']:
            assert args[2] == self.stored_commit and args[3] == '--'
            return b''.join(self.mode+oid(self.files[p]).encode()+b'\t'+p.encode()+b'\0'
                            for p in args[4:] if p in self.files)
        if len(args) > 1 and args[0] == 'cat-file' and args[1].startswith('--batch-check='):
            objects = {oid(raw): raw for raw in self.files.values()}
            return b''.join((ident+' blob '+str(len(objects[ident])+(1 if self.corrupt_size else 0))+'\n').encode()
                            if ident in objects else (ident+' missing\n').encode()
                            for ident in body.decode().splitlines())
        if args[:2] == ['cat-file', '-s']:
            commit, path = args[2].split(':', 1)
            assert commit == self.stored_commit
            return str(len(self.files[path])).encode()
        if args[0] == 'show':
            commit, path = args[1].split(':', 1)
            assert commit == self.stored_commit
            raw = self.files[path]
            return (b'X'+raw[1:]) if self.corrupt_read else raw
        raise AssertionError('UNEXPECTED_PUBLIC_FIXTURE_GIT_COMMAND')
    def prefetch_selected(self, commit, files, *, maximum_bytes):
        self.prefetch_calls += 1
        return VaultGitRepository.prefetch_selected(self, commit, files, maximum_bytes=maximum_bytes)
    def publication(self, *args, **kwargs):
        self.publication_calls += 1
        raise AssertionError('PUBLICATION_FORBIDDEN')
    commit = commit_snapshot = push = _write_tree = publication


class PrivateVenueRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pair_fixture.CurrentPairEligibilityTests.setUpClass()
        seed = pair_fixture.CurrentPairEligibilityTests('runTest')
        seed.setUp()
        cls.addClassCleanup(seed.doCleanups)
        cls.master = seed.root
        cls.main_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        cls.source_run = dict(id=RUN, head_sha=SOURCE, head_branch='production/boat-p0-p1-20261111',
            event='workflow_dispatch', workflow_id=405276784,
            path='.github/workflows/boat-nationwide-ab-one-shot.yml',
            name='BOAT nationwide cutoff-ordered A/B research (no Vercel)',
            status='completed', conclusion='success', run_attempt=1,
            created_at='2030-04-01T08:00:00Z', updated_at='2030-04-01T12:01:00Z',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        cls.job = dict(id=JOB, run_id=RUN, run_attempt=1, head_sha=SOURCE,
            name='Existing frozen P0, exhibition P1, separate official results and PDCA',
            status='completed', conclusion='success', started_at=cls.source_run['created_at'],
            completed_at=cls.source_run['updated_at'], steps=[])
        for number in range(1, 25):
            start = datetime(2030, 4, 1, 8, tzinfo=timezone.utc)+timedelta(minutes=10*(number-1))
            cls.job['steps'].append(dict(number=number+37, name=f'Deadline-ordered five-model round {number:02}',
                status='completed', conclusion='success', started_at=start.isoformat(),
                completed_at=(start+timedelta(minutes=10)).isoformat()))
        cls.raws = {800: seed.raws[800]}
        cls.metas = {800: dict(seed.metas[800], name=f'all-existing-model-pairs-{RUN}-2',
            workflow_run=dict(id=RUN, repository_id=1416489937, head_repository_id=1416489937,
                              head_sha=SOURCE, head_branch=cls.source_run['head_branch']))}
        admission, records = _verified_private_pairs_artifact(cls.raws[800], cls.metas[800], now=NOW,
            expected_run_id=RUN, expected_head_sha=SOURCE)
        cls.members = {}
        cls.remote_files = {}
        for round_no, ident in CASES.items():
            evaluated = datetime.fromisoformat(cls.job['steps'][round_no-1]['started_at'])+timedelta(minutes=1)
            folder = cls.master/f'pdca-{round_no}'/'800'
            _score_verified_private_pairs(admission, records, [], folder, now=evaluated)
            members = {str(path.relative_to(folder.parent)): path.read_bytes()
                       for path in folder.rglob('*') if path.is_file()}
            cls.members[ident] = members
            cls.raws[ident] = packed(members)
            cls.metas[ident] = dict(id=ident, name=f'boat-venue-research-pdca-{RUN}-{round_no}',
                size_in_bytes=len(cls.raws[ident]), digest='sha256:'+sha256(cls.raws[ident]).hexdigest(),
                expired=False, created_at=(evaluated+timedelta(minutes=1)).isoformat(),
                expires_at='2030-04-08T12:00:00Z', workflow_run=deepcopy(cls.metas[800]['workflow_run']))
            for child in (p for p in folder.iterdir() if p.is_dir()):
                identity = sha256((child/'learning.json').read_bytes()).hexdigest()
                prefix = 'state/boat-venue-history/v1/learning/'+identity+'/'
                for name in learning.FILES:
                    cls.remote_files[prefix+name] = (child/name).read_bytes()

    def setUp(self):
        self.assertIsNotNone(audit, 'exact private venue retention read-only auditor is missing')
        temporary = tempfile.TemporaryDirectory(prefix='public-retention-reader-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raws = dict(type(self).raws)
        self.metas = deepcopy(type(self).metas)
        self.source = deepcopy(type(self).source_run)
        self.job = deepcopy(type(self).job)
        self.identity = dict(commit=self.main_sha, run_id=9000, attempt=1, repository='haji84/RACE-AI')
        self.main = dict(id=9000, head_sha=self.main_sha, head_branch='main', event='push',
            name='BOAT nationally authenticated P1 matrix (no racing GET)',
            path='.github/workflows/boat-owner-national-p1-matrix.yml', workflow_id=418875114,
            run_attempt=1, status='in_progress', conclusion=None,
            created_at='2030-04-01T12:05:00Z', updated_at='2030-04-01T12:06:00Z',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        settings = dict(RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(), GITHUB_ACTIONS='true',
            GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_RUN_ID='9000', GITHUB_RUN_ATTEMPT='1',
            GITHUB_SHA=self.main_sha, GITHUB_EVENT_NAME='push', GITHUB_JOB='authenticated_original_matrix',
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-owner-national-p1-matrix.yml@refs/heads/main',
            RUNNER_TEMP=str(self.root), PATH=os.environ.get('PATH', os.defpath))
        environment = patch.dict(os.environ, settings, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.reader = MemoryReadOnlyGit(self.root, type(self).remote_files)
        self.routes = []
        self.attempts = []
        self.noise = io.StringIO()

    def get(self, route):
        self.routes.append(route)
        if route == 'actions/runs/9000':
            return wire(self.main)
        if route == f'actions/runs/{RUN}':
            return wire(self.source)
        if route == f'actions/jobs/{JOB}':
            return wire(self.job)
        if route in (f'actions/runs/{RUN}/artifacts?per_page=100', f'actions/runs/{RUN}/artifacts?per_page=100&page=1'):
            return wire(dict(total_count=len(self.metas), artifacts=list(self.metas.values())))
        if route.startswith('actions/artifacts/'):
            ident = int(route.split('/')[2])
            return self.raws[ident] if route.endswith('/zip') else wire(self.metas[ident])
        raise AssertionError('UNEXPECTED_SERVICE_ROUTE')

    def run_audit(self, **options):
        def forbidden(*args, **kwargs):
            self.attempts.append(1)
            raise AssertionError('NETWORK_FORBIDDEN')
        with patch('race_ai.boat_venue_research_cache.research_readback_transport', return_value=self.reader), \
             patch('socket.socket.connect', forbidden), patch('socket.socket.connect_ex', forbidden), \
             patch('socket.create_connection', forbidden), contextlib.redirect_stdout(self.noise), \
             contextlib.redirect_stderr(self.noise):
            out = audit.audit_private_venue_retention(OWNER, get=self.get, now=NOW,
                main_identity=self.identity, **options)
        self.assertEqual(self.noise.getvalue(), '')
        self.assertEqual(self.attempts, [])
        self.assertEqual(self.reader.publication_calls, 0)
        for sentinel in ('PRIVATE_RESULT_SENTINEL', 'source_url', 'learning.enc', 'ordered_top', 'coefficients', 'http', 'RACE_AI_STATE_KEY'):
            self.assertNotIn(sentinel, json.dumps(out))
        self.assertEqual(len(json.dumps(out)), min(len(json.dumps(out)), 8192))
        return out

    def replace_zip(self, ident, members):
        self.raws[ident] = packed(members)
        self.metas[ident].update(size_in_bytes=len(self.raws[ident]),
            digest='sha256:'+sha256(self.raws[ident]).hexdigest())

    def assert_hold(self, out):
        self.assertEqual(out['status'], 'HOLD_PRIVATE_RESEARCH_RETENTION')
        self.assertIs(out['plaintext_published'], False)
        self.assertIs(out['production_promoted'], False)
        self.assertIs(out['historical_push_completion_time_proven'], False)

    def test_all_three_exact_ciphertexts_verify_at_one_remote_head(self):
        before = deepcopy((self.raws, self.metas, self.reader.files))
        out = self.run_audit()
        self.assertEqual(out['status'], 'EXACT_PRIVATE_RESEARCH_RETENTION_VERIFIED')
        self.assertIsNone(out['failure_code'])
        self.assertEqual(out['artifact_count'], 3)
        self.assertEqual(out['expected_candidate_count'], 3)
        self.assertEqual(out['verified_candidate_count'], 3)
        self.assertEqual((out['missing_candidate_count'], out['conflict_candidate_count']), (0, 0))
        self.assertEqual(out['observed_remote_commit'], 'd'*40)
        self.assertEqual(self.reader.head_calls, 1)
        self.assertEqual(self.reader.fetch_calls, 1)
        self.assertGreater(self.reader.prefetch_calls, 0)
        self.assertEqual(before, (self.raws, self.metas, self.reader.files))

    def test_workflow_hook_uses_direct_metadata_transport_before_key_and_preserves_core(self):
        import textwrap
        from types import SimpleNamespace
        text = (ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertIn('# PRIVATE_VENUE_RETENTION_READBACK_BEGIN', text)
        block = text.split('# PRIVATE_VENUE_RETENTION_READBACK_BEGIN\n', 1)[1].split(
            '# PRIVATE_VENUE_RETENTION_READBACK_END', 1)[0]
        before = dict(current_pair_qualifying_g8_count=0, current_pair_official_raw_verified=None,
                      status='HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
        self.main['event'] = 'pull_request'
        def unsafe_transport(*args):
            raise AssertionError('ARCHIVAL_READER_MUST_NOT_INITIALIZE_BEFORE_MAIN_AUTH')
        namespace = dict(report=deepcopy(before), repo=OWNER, from_exact_file=lambda *_:audit,
            _live_gh=self.get, gh=unsafe_transport, os=os, timezone=timezone,
            datetime=SimpleNamespace(now=lambda *_:NOW))
        with patch('race_ai.boat_pdca_state.state_key') as key, \
             patch.object(audit.subprocess, 'check_output') as git:
            exec(textwrap.dedent(block), namespace)
        key.assert_not_called()
        git.assert_not_called()
        self.assertEqual(self.routes, ['actions/runs/9000'])
        self.assertTrue(all(namespace['report'][k] == value for k, value in before.items()))
        self.assert_hold(namespace['report']['private_venue_retention_readback'])

    def test_workflow_hook_failure_never_exports_private_exception_or_changes_core(self):
        import textwrap
        text = (ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertIn('# PRIVATE_VENUE_RETENTION_READBACK_BEGIN', text)
        block = text.split('# PRIVATE_VENUE_RETENTION_READBACK_BEGIN\n', 1)[1].split(
            '# PRIVATE_VENUE_RETENTION_READBACK_END', 1)[0]
        def fail(*args, **kwargs):
            raise ValueError('PRIVATE_RESULT_SENTINEL https://private.invalid/?key=secret')
        before = dict(current_pair_qualifying_g8_count=0, current_pair_official_raw_verified=None)
        namespace = dict(report=deepcopy(before), repo=OWNER, from_exact_file=fail,
            _live_gh=fail, os=os, datetime=datetime, timezone=timezone)
        exec(textwrap.dedent(block), namespace)
        self.assertTrue(all(namespace['report'][k] == value for k, value in before.items()))
        self.assert_hold(namespace['report']['private_venue_retention_readback'])
        self.assertNotIn('PRIVATE_RESULT_SENTINEL', json.dumps(namespace['report']))
        self.assertNotIn('http', json.dumps(namespace['report']))

    def test_main_service_and_environment_guards_precede_key_and_git(self):
        for field, value in [('event', 'pull_request'), ('status', 'completed'), ('path', 'other.yml'),
                             ('head_branch', 'topic'), ('run_attempt', 2), ('head_sha', 'f'*40)]:
            old = self.main[field]
            self.main[field] = value
            with self.subTest(field=field), patch('race_ai.boat_pdca_state.state_key') as key, \
                 patch.object(audit.subprocess, 'check_output') as git:
                self.assert_hold(self.run_audit())
                key.assert_not_called()
                git.assert_not_called()
            self.main[field] = old
        with patch.dict(os.environ, GITHUB_ACTIONS='false'):
            self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_source_identity_round_step_and_known_artifact_metadata_fail_closed(self):
        cases = [('head', self.source, 'head_sha', 'e'*40),
                 ('attempt', self.source, 'run_attempt', 2),
                 ('job', self.job, 'id', JOB+1),
                 ('step', self.job['steps'][17], 'conclusion', 'failure'),
                 ('expired', self.metas[CASES[18]], 'expired', True),
                 ('name', self.metas[CASES[18]], 'name', 'unknown-private-container'),
                 ('future', self.metas[CASES[18]], 'created_at', '2030-04-01T12:11:00Z')]
        for name, target, field, value in cases:
            old = target[field]
            target[field] = value
            with self.subTest(case=name):
                self.assert_hold(self.run_audit())
                self.assertEqual(self.reader.head_calls, 0)
            target[field] = old

    def test_missing_remote_exact_candidate_is_hold_not_replaced_by_later_nonce(self):
        first = next(iter(self.reader.files)).rsplit('/', 1)[0]+'/'
        for path in list(self.reader.files):
            if path.startswith(first):
                self.reader.files.pop(path)
        out = self.run_audit()
        self.assert_hold(out)
        self.assertEqual(out['expected_candidate_count'], 3)
        self.assertEqual(out['verified_candidate_count'], 2)
        self.assertEqual(out['missing_candidate_count'], 1)
        self.assertEqual(out['conflict_candidate_count'], 0)
        self.assertEqual(self.reader.head_calls, 1)

    def test_remote_cipher_oid_mode_size_and_read_bytes_are_verified(self):
        for case in ('oid', 'mode', 'size', 'bytes'):
            files = dict(self.reader.files)
            if case == 'oid':
                path = next(p for p in self.reader.files if p.endswith('/learning.enc'))
                self.reader.files[path] += b'changed'
            elif case == 'mode':
                self.reader.mode = b'100755 blob '
            elif case == 'size':
                self.reader.corrupt_size = True
            else:
                self.reader.corrupt_read = True
            with self.subTest(case=case):
                self.assert_hold(self.run_audit())
            self.reader.files = files
            self.reader.mode = b'100644 blob '
            self.reader.corrupt_size = self.reader.corrupt_read = False

    def test_pdca_summary_missing_partition_unknown_member_and_cipher_corruption_hold_before_git(self):
        ident = CASES[18]
        original = deepcopy((self.raws, self.metas))
        for case in ('summary', 'partition', 'unknown', 'cipher'):
            members = dict(type(self).members[ident])
            if case == 'summary':
                members['800/summary.json'] = b'{}'
            elif case == 'partition':
                members = {'800/summary.json': members['800/summary.json']}
            elif case == 'unknown':
                members['800/hidden.bin'] = b'PRIVATE_RESULT_SENTINEL'
            else:
                path = next(p for p in members if p.endswith('/learning.enc'))
                members[path] = b'not-authenticated-ciphertext'
            self.replace_zip(ident, members)
            with self.subTest(case=case):
                self.assert_hold(self.run_audit())
                self.assertEqual(self.reader.head_calls, 0)
            self.raws, self.metas = deepcopy(original)

    def test_duplicate_zip_names_oversize_container_and_metadata_digest_mismatch_hold(self):
        ident = CASES[18]
        original = deepcopy((self.raws, self.metas))
        self.metas[ident]['size_in_bytes'] = 128*1024*1024+1
        self.assert_hold(self.run_audit())
        self.assertNotIn(f'actions/artifacts/{ident}/zip', self.routes)
        self.raws, self.metas = deepcopy(original)
        self.routes.clear()
        self.metas[ident]['digest'] = 'sha256:'+'f'*64
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_exact_service_identifiers_reject_float_types_before_key_or_git(self):
        cases = [(self.main, 'id'), (self.source, 'id'), (self.job, 'id'), (self.job, 'run_id'),
                 (self.metas[CASES[18]]['workflow_run'], 'id')]
        for target, field in cases:
            previous = target[field]
            target[field] = float(previous)
            with self.subTest(field=field, value=previous), patch('race_ai.boat_pdca_state.state_key') as key, \
                 patch.object(audit.subprocess, 'check_output') as git:
                self.assert_hold(self.run_audit())
                key.assert_not_called()
                git.assert_not_called()
            target[field] = previous

    def test_unknown_same_run_research_container_cannot_be_silently_ignored(self):
        self.metas[801] = dict(self.metas[CASES[18]], id=801,
            name=f'boat-venue-research-pdca-{RUN}-18-extra')
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_workflow_and_request_identifiers_require_bounded_strict_integers(self):
        for target in (self.main, self.source):
            previous = target['workflow_id']
            target['workflow_id'] = float(previous)
            with self.subTest(workflow=previous), patch('race_ai.boat_pdca_state.state_key') as key, \
                 patch.object(audit.subprocess, 'check_output') as git:
                self.assert_hold(self.run_audit())
                key.assert_not_called()
                git.assert_not_called()
            target['workflow_id'] = previous
        self.identity['run_id'] = 10**40
        with patch.dict(os.environ, GITHUB_RUN_ID=str(self.identity['run_id'])), \
             patch.object(self, 'get', wraps=self.get) as service:
            self.assert_hold(self.run_audit())
            service.assert_not_called()

    def test_duplicate_member_symlink_future_payload_and_authenticated_unknown_field_hold(self):
        from race_ai.boat_venue_learning import read_candidate, seal_candidate
        ident = CASES[18]
        original = deepcopy((self.raws, self.metas))
        for case in ('duplicate', 'symlink', 'future', 'unknown_field'):
            members = dict(type(self).members[ident])
            if case in ('duplicate', 'symlink'):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for name, raw in members.items():
                        if case == 'symlink' and name.endswith('/learning.enc'):
                            info = zipfile.ZipInfo(name)
                            info.create_system = 3
                            info.external_attr = (0o120777 << 16)
                            archive.writestr(info, raw)
                        else:
                            archive.writestr(name, raw)
                    if case == 'duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            name = next(iter(members))
                            archive.writestr(name, members[name])
                self.raws[ident] = stream.getvalue()
                self.metas[ident].update(size_in_bytes=len(self.raws[ident]),
                    digest='sha256:'+sha256(self.raws[ident]).hexdigest())
            else:
                child = next(p for p in (self.master/'pdca-18'/'800').iterdir() if p.is_dir())
                payload = read_candidate(child)
                if case == 'future':
                    payload['evaluated_at'] = (NOW+timedelta(seconds=1)).isoformat()
                else:
                    payload['unknown'] = 'PRIVATE_RESULT_SENTINEL'
                replacement = self.root/case
                seal_candidate(payload, replacement)
                for name in learning.FILES:
                    members['800/'+child.name+'/'+name] = (replacement/name).read_bytes()
                self.replace_zip(ident, members)
            with self.subTest(case=case):
                self.assert_hold(self.run_audit())
                self.assertEqual(self.reader.head_calls, 0)
            self.raws, self.metas = deepcopy(original)

    def test_artifact_expiry_and_source_receipt_conflict_hold_before_remote(self):
        original = deepcopy(self.metas)
        self.metas[CASES[23]]['expires_at'] = NOW.isoformat()
        self.assert_hold(self.run_audit())
        self.metas = deepcopy(original)
        self.metas[800]['created_at'] = '2030-04-01T08:19:00Z'
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_missing_known_artifact_or_added_same_round_carrier_does_not_shrink_scope(self):
        original = deepcopy(self.metas)
        self.metas.pop(CASES[23])
        self.assert_hold(self.run_audit())
        self.metas = deepcopy(original)
        self.metas[801] = dict(self.metas[800], id=801, name=f'all-existing-model-pairs-{RUN}-18')
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_ordinary_exception_with_secret_text_never_escapes(self):
        old = self.get
        def failing(route):
            if route == 'actions/runs/9000':
                raise RuntimeError('PRIVATE_RESULT_SENTINEL https://private.invalid/?key=secret')
            return old(route)
        self.get = failing
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_archive_failure_code_preserves_hold_and_unknown_counts(self):
        failure = audit._Rejected('OBSERVATION_SNAPSHOT_REJECTED')
        with patch.object(audit, '_candidates', side_effect=failure):
            out = self.run_audit()
        self.assert_hold(out)
        self.assertEqual(out['phase'], 'PRIVATE_ARCHIVE')
        self.assertEqual(out['reason'], 'PRIVATE_EVIDENCE_REJECTED')
        self.assertEqual(out['failure_code'], 'OBSERVATION_SNAPSHOT_REJECTED')
        self.assertIsNone(out['expected_candidate_count'])
        self.assertIsNone(out['missing_candidate_count'])
        self.assertEqual(self.reader.head_calls, 0)

    def test_readonly_facade_rejects_publication_and_unpinned_read_commands(self):
        reader = audit._ReadOnly(self.reader)
        for name in ('commit', 'commit_snapshot', 'push', '_write_tree'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                getattr(reader, name)('f'*40, 'e'*40)
        self.assertEqual(self.reader.publication_calls, 0)

    def test_missing_or_wrong_owner_key_stays_hold_without_zip_or_remote_mutation(self):
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            self.assert_hold(self.run_audit())
        self.assertFalse(any(route.endswith('/zip') for route in self.routes))
        self.routes.clear()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(range(32)))).decode()):
            self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_observed_commit_remains_pinned_when_transfer_head_advances(self):
        self.reader.move_after_observation = True
        out = self.run_audit()
        self.assertEqual(out['status'], 'EXACT_PRIVATE_RESEARCH_RETENTION_VERIFIED')
        self.assertEqual(out['observed_remote_commit'], 'd'*40)
        self.assertEqual(self.reader.current, 'e'*40)
        self.assertEqual((self.reader.head_calls, self.reader.fetch_calls), (1, 1))

    def test_duplicate_metadata_json_and_fresh_receipt_drift_are_rejected(self):
        original_get = self.get
        def duplicate(route):
            if route == 'actions/runs/9000':
                return b'{"id":9000,'+wire(self.main)[1:]
            return original_get(route)
        self.get = duplicate
        self.assert_hold(self.run_audit())
        def changed(route):
            if route == f'actions/artifacts/{CASES[18]}':
                return wire(dict(self.metas[CASES[18]], digest='sha256:'+'f'*64))
            return original_get(route)
        self.get = changed
        self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_uncompressed_archive_budget_is_checked_before_cipher_or_git(self):
        with patch.object(audit, 'MAX_EXPANDED', 1):
            self.assert_hold(self.run_audit())
        self.assertEqual(self.reader.head_calls, 0)

    def test_archive_member_order_does_not_change_source_summary_or_candidate_identity(self):
        for ident in CASES.values():
            members = type(self).members[ident]
            self.replace_zip(ident, dict(reversed(list(members.items()))))
        out = self.run_audit()
        self.assertEqual(out['status'], 'EXACT_PRIVATE_RESEARCH_RETENTION_VERIFIED')
        self.assertEqual(out['verified_candidate_count'], 3)


class PrivateVenueObservationSnapshotTests(unittest.TestCase):
    """One producer observation is shared by all cells of its canonical race."""
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        from tests.test_all_existing_model_learning import observed_records
        from tests.test_observed_weight_learning import NOW as TRAIN_NOW
        seed = pair_fixture.CurrentPairEligibilityTests('runTest')
        seed.records = observed_records(synthetic=False)
        seed.training = fit(seed.records, now=TRAIN_NOW, allow_source=lambda *_:True,
                            allow_training=lambda *_:True)
        seed.cell = next(iter(seed.training['models']))
        seed.setUp()
        cls.addClassCleanup(seed.doCleanups)
        seed.pairs(1, both_models=True)
        cls.raw = seed.raws[800]
        cls.meta = dict(seed.metas[800], name=f'all-existing-model-pairs-{RUN}-2',
            workflow_run=dict(id=RUN, repository_id=1416489937, head_repository_id=1416489937,
                              head_sha=SOURCE, head_branch='production/boat-p0-p1-20261111'))
        cls.admission, cls.records = _verified_private_pairs_artifact(cls.raw, cls.meta, now=NOW,
            expected_run_id=RUN, expected_head_sha=SOURCE)
        assert len(cls.records) == 2
        cls.evaluated = datetime(2030, 4, 1, 10, 51, tzinfo=timezone.utc)
        pair = cls.records[0]['pair']
        cls.observation = dict(race_id=pair['race_id'], sport=pair['sport'], status='settled',
            ordered_top3=[1, 2, 3], roster=deepcopy(pair['baseline_normalized']['roster']),
            captured_at='2030-04-01T08:31:00+00:00', source_sha256='c'*64,
            identity_verified=True, payout_per_100_yen=100, refund_numbers=[])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='public-observation-snapshot-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rounds = {2: (datetime(2030, 4, 1, 8, 10, tzinfo=timezone.utc),
                           datetime(2030, 4, 1, 8, 20, tzinfo=timezone.utc)),
                       18: (self.evaluated-timedelta(minutes=1), self.evaluated+timedelta(minutes=9))}

    def members(self, observations, *, ident=800):
        folder = self.root/('producer-'+str(len(list(self.root.iterdir()))))/str(ident)
        _score_verified_private_pairs(self.admission, self.records, observations, folder, now=self.evaluated)
        return {str(path.relative_to(folder.parent)): path.read_bytes()
                for path in folder.rglob('*') if path.is_file()}

    def candidates(self, members, *, additional=None):
        original_metas = {800: (2, self.meta)}
        if additional is not None:
            original_metas.update(additional)
        routes = []
        def get(route):
            routes.append(route)
            for ident, (_, meta) in original_metas.items():
                if route == f'actions/artifacts/{ident}':
                    return wire(meta)
                if route == f'actions/artifacts/{ident}/zip':
                    return self.raw
            self.fail('UNEXPECTED_PUBLIC_FIXTURE_ROUTE')
        reads = audit._Reads(get, 9000)
        reads.artifacts.update(original_metas)
        folder = self.root/('reader-'+str(len(list(self.root.iterdir()))))
        try:
            found = audit._candidates(packed(members), 18,
                dict(created_at=(self.evaluated+timedelta(minutes=1)).isoformat()),
                folder, reads, original_metas, self.rounds, NOW, self.root/'cache', {})
        except audit._Rejected as error:
            return error.args[0], []
        self.assertEqual(routes, [route for ident in original_metas for route in
                                  (f'actions/artifacts/{ident}', f'actions/artifacts/{ident}/zip')])
        return 'ACCEPTED', found

    def change_observation(self, members, observation):
        from race_ai.all_existing_model_pdca import _score, _summary
        from race_ai.boat_venue_learning import read_candidate, seal_candidate
        partition = next(name.split('/')[1] for name in members if name.endswith('/learning.enc'))
        folder = self.root/'change-source'
        folder.mkdir()
        for name in learning.FILES:
            (folder/name).write_bytes(members['800/'+partition+'/'+name])
        payload = read_candidate(folder)
        payload['observation'] = deepcopy(observation)
        pair = payload['private_forecast']['pair']
        payload['score'] = dict(cell_key=pair['cell_key'],
            forecast_record_sha256=digest(payload['private_forecast']), score=_score(pair, observation))
        payload['summary'] = _summary(self.admission, [payload['score']], int(observation is not None))
        replacement = self.root/'changed-candidate'
        seal_candidate(payload, replacement)
        for name in learning.FILES:
            members['800/'+partition+'/'+name] = (replacement/name).read_bytes()
        return payload

    def test_same_race_two_cells_count_one_authenticated_observation(self):
        members = self.members([self.observation])
        self.assertEqual(json.loads(members['800/summary.json'])['observation_count'], 1)
        before = deepcopy(members)
        status, found = self.candidates(members)
        self.assertEqual(status, 'ACCEPTED')
        self.assertEqual(len(found), 2)
        self.assertEqual(members, before)

    def test_pending_observation_is_one_input_not_zero_settled_results(self):
        pending = dict(self.observation, status='pending', ordered_top3=[])
        members = self.members([pending])
        self.assertEqual(json.loads(members['800/summary.json'])['observation_count'], 1)
        self.assertEqual(self.candidates(members)[0], 'ACCEPTED')

    def test_observation_snapshot_scope_is_per_original_artifact(self):
        members = self.members([self.observation])
        meta = dict(self.meta, id=801, name=f'all-existing-model-pairs-{RUN}-3',
                    created_at='2030-04-01T08:20:03Z')
        admission, records = _verified_private_pairs_artifact(self.raw, meta, now=NOW,
            expected_run_id=RUN, expected_head_sha=SOURCE)
        folder = self.root/'different-artifact'/'801'
        revision = dict(self.observation, source_sha256='d'*64)
        _score_verified_private_pairs(admission, records, [revision], folder, now=self.evaluated)
        members.update({str(path.relative_to(folder.parent)): path.read_bytes()
                        for path in folder.rglob('*') if path.is_file()})
        self.rounds[3] = (datetime(2030, 4, 1, 8, 20, tzinfo=timezone.utc),
                          datetime(2030, 4, 1, 8, 30, tzinfo=timezone.utc))
        status, found = self.candidates(members, additional={801: (3, meta)})
        self.assertEqual(status, 'ACCEPTED')
        self.assertEqual(len(found), 4)

    def test_producer_rejects_unmatched_result_before_creating_output(self):
        folder = self.root/'unmatched'
        with self.assertRaisesRegex(ValueError, '^ALL_MODEL_PRIVATE_PDCA_UNRELATED_RESULT$'):
            _score_verified_private_pairs(self.admission, self.records,
                [self.observation, dict(self.observation, race_id='20300401-24-02')],
                folder, now=self.evaluated)
        self.assertFalse(folder.exists())

    def test_producer_rejects_duplicate_canonical_race_revision_before_output(self):
        folder = self.root/'duplicate'
        revision = dict(self.observation, source_sha256='d'*64)
        with self.assertRaisesRegex(ValueError, '^ALL_MODEL_PRIVATE_PDCA_DUPLICATE_RESULT_REVISION$'):
            _score_verified_private_pairs(self.admission, self.records,
                [self.observation, revision], folder, now=self.evaluated)
        self.assertFalse(folder.exists())

    def test_authenticated_cell_revision_disagreement_holds(self):
        members = self.members([self.observation])
        self.change_observation(members, dict(self.observation, source_sha256='d'*64))
        self.assertEqual(self.candidates(members)[0], 'OBSERVATION_SNAPSHOT_REJECTED')

    def test_authenticated_some_cells_none_disagreement_holds(self):
        from race_ai.all_existing_model_pdca import _score, _summary
        members = self.members([self.observation])
        changed = self.change_observation(members, None)
        rows = [changed['score'] if record['pair']['cell_key'] == changed['score']['cell_key'] else
                dict(cell_key=record['pair']['cell_key'], forecast_record_sha256=digest(record),
                     score=_score(record['pair'], self.observation)) for record in self.records]
        members['800/summary.json'] = wire(dict(_summary(self.admission, rows, 1),
                                                encrypted_readback_verified=True))
        self.assertEqual(self.candidates(members)[0], 'OBSERVATION_SNAPSHOT_REJECTED')

    def test_original_aggregate_observation_count_is_compared_not_trusted(self):
        members = self.members([self.observation])
        summary = json.loads(members['800/summary.json'])
        summary['observation_count'] = 2
        members['800/summary.json'] = wire(summary)
        self.assertEqual(self.candidates(members)[0], 'SUMMARY_COVERAGE_REJECTED')

    def test_original_aggregate_scoreboard_is_still_compared_completely(self):
        members = self.members([])
        summary = json.loads(members['800/summary.json'])
        summary['baseline_forecast_count'] += 1
        members['800/summary.json'] = wire(summary)
        self.assertEqual(self.candidates(members)[0], 'SUMMARY_COVERAGE_REJECTED')


class PrivateVenueFailureCodeTests(unittest.TestCase):
    def report(self, error):
        with patch.object(audit, '_service_context', side_effect=error), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            out = audit.audit_private_venue_retention(OWNER, get=lambda _:b'{}', now=NOW,
                                                      main_identity={})
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))
        self.assertEqual(out['status'], 'HOLD_PRIVATE_RESEARCH_RETENTION')
        self.assertEqual(out['phase'], 'MAIN_CONTEXT')
        self.assertEqual(out['reason'], 'CONTEXT_REJECTED')
        self.assertIsNone(out['verified_candidate_count'])
        self.assertIsNone(out['missing_candidate_count'])
        return out

    def test_exact_local_and_frozen_upstream_failure_codes_are_projected(self):
        for error in (audit._Rejected('SUMMARY_COVERAGE_REJECTED'),
                      audit._Rejected('OBSERVATION_SNAPSHOT_REJECTED'),
                      ValueError('ALL_MODEL_PAIR_RECEIPT_PRE_CUTOFF_CLOCK_INVALID'),
                      ValueError('VENUE_LEARNING_AUTHENTICATION_FAILED')):
            with self.subTest(code=error.args[0]):
                self.assertEqual(self.report(error).get('failure_code'), error.args[0])

    def test_unknown_text_type_or_multiple_args_never_escape(self):
        class Hostile(ValueError):
            def __str__(self):
                raise AssertionError('PRIVATE_EXCEPTION_FORMATTED')
        class PrivateString(str):
            pass
        sentinel = 'PRIVATE_RESULT_SENTINEL https://private.invalid/?params=secret'
        errors = (ValueError(sentinel), audit._Rejected(sentinel),
                  ValueError('SUMMARY_COVERAGE_REJECTED '+sentinel),
                  ValueError('SUMMARY_COVERAGE_REJECTED', sentinel),
                  ValueError(PrivateString('SUMMARY_COVERAGE_REJECTED')),
                  RuntimeError('SUMMARY_COVERAGE_REJECTED'), Hostile('SUMMARY_COVERAGE_REJECTED'))
        for error in errors:
            with self.subTest(kind=type(error).__name__):
                out = self.report(error)
                self.assertEqual(out.get('failure_code'), 'UNCLASSIFIED')
                self.assertNotIn('PRIVATE_RESULT_SENTINEL', json.dumps(out))
                self.assertNotIn('http', json.dumps(out))


if __name__ == '__main__':
    unittest.main()
