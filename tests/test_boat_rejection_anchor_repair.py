"""Offline V5 repair orchestration boundaries; synthetic receipts are not AEAD proof.

The real proof/candidate/guard are exercised. Publisher and selected-reader
callbacks are fakes, with no key, Git writer, provider, source or live operation.
"""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib
import inspect
import io
import json
import os
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests import test_boat_saved_rejection_anchor_proof as F
from scripts import boat_rejection_anchor_restoration as C

A = F.A
try:
    R = importlib.import_module('scripts.boat_rejection_anchor_repair')
except ModuleNotFoundError as error:
    if error.name != 'scripts.boat_rejection_anchor_repair':
        raise
    R = None

SCHEMA = 'RACE_AI_REJECTION_ANCHOR_REPAIR_V1'
V5 = 'RACE_AI_SAVED_WEB_HISTORY_V5'
PREFIX = 'boat-owner-release: single-real-session-20261111'
HEAD = '1' * 40
PUBLISHED = '7' * 40
DAY = '2030-04-01'
COUNTS = ('snapshots_checked', 'orphan_groups', 'current_active_rejections',
    'candidate_active_rejections', 'retained_history_originals',
    'restored_active_originals', 'rows_changed')
EFFECTS = dict(originals_changed=False, observations_reconciled=0,
    source_requests=0, forecast_generated=False, broader_goals_proven=False)
HASH_FIELDS = ('current_view_sha256', 'candidate_view_sha256',
    'published_snapshot_sha', 'published_cipher_sha256', 'published_generation')


def wire(value):
    return F.wire(value).encode('utf-8')


def mint(value, generation, previous, tag, *, snapshot=None, schema=V5):
    header = dict(schema=schema, source_content_sha256='e' * 64,
        view_id='d' * 64, forecast_sha256='f' * 64,
        generation=generation, previous_cipher_sha256=previous)
    if schema == V5:
        header['history_index_sha256'] = '9' * 64
    else:
        header['forecast_inventory_sha256'] = '9' * 64
    # Explicit synthetic factory bytes, never an authentication assertion.
    raw = wire(dict(header=header, synthetic_ciphertext='private-sentinel-' + tag))
    commit = snapshot or hashlib.sha1(('synthetic-' + tag).encode()).hexdigest()
    return A._verified_snapshot(value, header=header,
        manifest_cipher_sha256=hashlib.sha256(raw).hexdigest(),
        snapshot_sha=commit, ciphertext=raw)


class ObservedEnvironment(dict):
    allowed = frozenset(('GITHUB_ACTIONS', 'GITHUB_EVENT_NAME', 'GITHUB_REF',
        'GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_REPOSITORY_ID',
        'GITHUB_WORKFLOW_REF', 'GITHUB_JOB', 'GITHUB_RUN_ATTEMPT'))

    def get(self, name, default=None):
        if name not in self.allowed:
            raise AssertionError('NO_KEY_OR_OTHER_ENVIRONMENT_ACCESS')
        return super().get(name, default)

    def __getitem__(self, name):
        if name not in self.allowed:
            raise AssertionError('NO_KEY_OR_OTHER_ENVIRONMENT_ACCESS')
        return super().__getitem__(name)

    def __iter__(self):
        raise AssertionError('NO_ENVIRONMENT_ENUMERATION')

    def keys(self):
        raise AssertionError('NO_ENVIRONMENT_ENUMERATION')

    def items(self):
        raise AssertionError('NO_ENVIRONMENT_ENUMERATION')

    def values(self):
        raise AssertionError('NO_ENVIRONMENT_ENUMERATION')

    def copy(self):
        raise AssertionError('NO_ENVIRONMENT_COPY')


def environment():
    return ObservedEnvironment(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
        GITHUB_REF='refs/heads/main', GITHUB_SHA=HEAD,
        GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
        GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main',
        GITHUB_JOB='owner_p0_p1_dispatch', GITHUB_RUN_ATTEMPT='1',
        RACE_AI_STATE_KEY='private-sentinel-owner-key',
        GH_TOKEN='private-sentinel-token', PRIVATE_EXTRA='private-sentinel-extra')


def event():
    return dict(ref='refs/heads/main', after=HEAD, deleted=False,
        head_commit=dict(id=HEAD, message=PREFIX + ': reviewed repair candidate'),
        repository=dict(full_name='haji84/RACE-AI', id=1416489937,
            private=False, fork=False),
        private_extra=dict(url='https://private-sentinel.invalid',
            owner_key='private-sentinel-never-export'))


def case(guard, *, current_view=None, older_view=None, no_older=False, schema=V5):
    current_value, older_value = F.views()
    if current_view is not None:
        current_value = deepcopy(current_view)
    if older_view is not None:
        older_value = deepcopy(older_view)
    older = mint(older_value, 423, '0' * 64, 'older', schema=schema)
    current = mint(current_value, 424, older._cipher_sha256, 'current', schema=schema)
    chain = () if no_older else (older,)
    expected = deepcopy(current_value)
    if not no_older:
        expected['records'][0][F.ACTIVE].extend(deepcopy(older_value['records'][0][F.ACTIVE]))
    readback = mint(expected, 425, current._cipher_sha256, 'readback', snapshot=PUBLISHED)
    ack = dict(status='ENCRYPTED_HISTORY_VIEW_PUBLISHED', generation=425,
        commit=PUBLISHED, cipher_sha256=readback._cipher_sha256,
        updated_dates=1, head_files=2)
    repository = SimpleNamespace(ref='state/boat-saved-view',
        head=Mock(return_value=current._snapshot_sha))
    for name in ('commit', 'commit_snapshot', 'push', '_run', 'read', 'fetch'):
        setattr(repository, name, Mock(side_effect=AssertionError('NO_RAW_REPOSITORY_OPERATION')))
    feed = ModuleType('synthetic_existing_feed')
    feed.REF = 'state/boat-saved-view'
    feed.publish_view = Mock(return_value=deepcopy(ack))
    bootstrap = dict(view_id='d' * 64, forecast_sha256='f' * 64,
        cipher_sha256='e' * 64, key=b'k' * 32)
    context = dict(proof=A, candidate=C, guard=guard, feed=feed,
        repository=repository, bootstrap=bootstrap, current=current, older_chain=chain)
    return dict(context=context, current=current, older=chain, repository=repository,
        feed=feed, bootstrap=bootstrap, expected=expected, readback=readback, ack=ack)


class RejectionAnchorRepairBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(R, 'Actions rejection-anchor repair module is missing')
        self.guard = F.load_guard()

    def receipts(self, value):
        return [(wire(item._view), wire(item._header), item._ciphertext,
                 item._snapshot_sha, item._binding_sha256)
                for item in (value['current'], *value['older'])]

    def safe(self, report):
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], SCHEMA)
        self.assertIn(report['status'], ('HOLD', 'NO_CHANGE', 'PUBLISHED_VERIFIED'))
        fields = {'schema', 'status', 'counts', *HASH_FIELDS, *EFFECTS,
            'publication_attempted', 'publication_performed', 'readback_verified'}
        for name, expected in EFFECTS.items():
            self.assertIs(type(report[name]), type(expected))
            self.assertEqual(report[name], expected)
        self.assertIs(type(report['publication_attempted']), bool)
        self.assertTrue(report['publication_performed'] is None
            or type(report['publication_performed']) is bool)
        self.assertIs(type(report['readback_verified']), bool)
        if report['status'] == 'HOLD':
            fields.add('reason')
            self.assertRegex(report['reason'], r'^[A-Z][A-Z0-9_]{0,79}$')
            self.assertIsNone(report['counts'])
            for name in HASH_FIELDS:
                self.assertIsNone(report[name])
        else:
            self.assertEqual(set(report['counts']), set(COUNTS))
            for number in report['counts'].values():
                self.assertIs(type(number), int)
                self.assertGreaterEqual(number, 0)
            self.assertRegex(report['current_view_sha256'], r'^[a-f0-9]{64}$')
        if report['status'] == 'PUBLISHED_VERIFIED':
            self.assertIs(report['publication_attempted'], True)
            self.assertIs(report['publication_performed'], True)
            self.assertIs(report['readback_verified'], True)
            self.assertRegex(report['candidate_view_sha256'], r'^[a-f0-9]{64}$')
            self.assertRegex(report['published_snapshot_sha'], r'^[a-f0-9]{40}$')
            self.assertRegex(report['published_cipher_sha256'], r'^[a-f0-9]{64}$')
            self.assertIs(type(report['published_generation']), int)
        self.assertEqual(set(report), fields)
        encoded = json.dumps(report, sort_keys=True, allow_nan=False)
        for forbidden in ('sentinel', F.RID, '2030-04-01T', 'RESULT_METADATA',
                'prediction', 'result_observations', 'owner_key', 'Traceback', 'https:'):
            self.assertNotIn(forbidden, encoded)

    def invoke(self, value, *, env=None, payload=None, loader=None, reopened=None):
        before = self.receipts(value)
        load = loader or Mock(return_value=value['context'])
        read = reopened or Mock(return_value=value['readback'])
        stdout, stderr = io.StringIO(), io.StringIO()
        trusted_env = environment() if env is None else env
        with patch.object(A, '_read_verified_snapshot', read), \
                patch.object(os, 'environ', trusted_env), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            report = R.run_repair(trusted_env,
                event() if payload is None else payload, load_context=load)
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))
        self.assertEqual(self.receipts(value), before)
        self.safe(report)
        for name in ('commit', 'commit_snapshot', 'push', '_run', 'read', 'fetch'):
            getattr(value['repository'], name).assert_not_called()
        return report, load, read

    def hold(self, value, reason, *, attempted=False, performed=False, **options):
        report, load, read = self.invoke(value, **options)
        self.assertEqual((report['status'], report['reason']), ('HOLD', reason))
        self.assertIs(report['publication_attempted'], attempted)
        self.assertIs(report['publication_performed'], performed)
        self.assertIs(report['readback_verified'], False)
        if not attempted:
            value['feed'].publish_view.assert_not_called()
            read.assert_not_called()
        return report, load, read

    def test_trusted_v5_recomputes_real_candidate_and_publishes_once_then_reopens_exact_commit(self):
        value = case(self.guard)
        with patch.object(C, 'build_rejection_anchor_restoration',
                wraps=C.build_rejection_anchor_restoration) as built, \
                patch.object(A, 'match_rejection_anchor_proofs',
                wraps=A.match_rejection_anchor_proofs) as matched:
            report, loaded, read = self.invoke(value)
        self.assertEqual(report['status'], 'PUBLISHED_VERIFIED')
        loaded.assert_called_once_with()
        built.assert_called_once_with(value['current'], value['older'], guard=self.guard, proof=A)
        matched.assert_called_once_with(value['current'], value['older'], guard=self.guard)
        value['repository'].head.assert_called_once_with()
        value['feed'].publish_view.assert_called_once()
        args, kwargs = value['feed'].publish_view.call_args
        self.assertIs(args[0], value['repository'])
        self.assertIs(args[1], value['bootstrap'])
        self.assertEqual(wire(args[2]), wire(value['expected']))
        self.assertEqual(kwargs, dict(parent=value['current']._snapshot_sha,
            previous=value['current']._cipher_sha256, generation=424))
        read.assert_called_once()
        args, kwargs = read.call_args
        self.assertEqual(args, (value['repository'], value['bootstrap'], PUBLISHED))
        self.assertIs(kwargs['feed'], value['feed'])
        self.assertIs(kwargs['guard'], self.guard)
        self.assertIs(type(kwargs['budget']), A.ReadBudget)
        self.assertEqual(kwargs['day'], DAY)
        self.assertEqual(report['counts'], dict(snapshots_checked=2, orphan_groups=2,
            current_active_rejections=1, candidate_active_rejections=3,
            retained_history_originals=4, restored_active_originals=2, rows_changed=1))
        self.assertEqual(report['current_view_sha256'], hashlib.sha256(wire(value['current']._view)).hexdigest())
        self.assertEqual(report['candidate_view_sha256'], hashlib.sha256(wire(value['expected'])).hexdigest())
        self.assertEqual(report['published_snapshot_sha'], PUBLISHED)
        self.assertEqual(report['published_cipher_sha256'], value['ack']['cipher_sha256'])
        self.assertEqual(report['published_generation'], 425)
        for row in value['expected']['records']:
            self.guard._observations([row], 'result_observations')
            self.guard._observations([row], F.ACTIVE, rejection=True)
        with self.assertRaises(self.guard.SavedModelViewError):
            self.guard._observations([value['current']._view['records'][0]], F.ACTIVE, rejection=True)

    def test_untrusted_context_and_every_later_attempt_refuse_before_loading_private_context(self):
        changes = [('env', key, replacement) for key, replacement in (
            ('GITHUB_ACTIONS', 'True'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
            ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_SHA', 'A' * 40),
            ('GITHUB_REPOSITORY', 'other/RACE-AI'), ('GITHUB_REPOSITORY_ID', '1'),
            ('GITHUB_JOB', 'other_job'), ('GITHUB_RUN_ATTEMPT', '2'),
            ('GITHUB_RUN_ATTEMPT', '01'), ('GITHUB_RUN_ATTEMPT', 1),
            ('GITHUB_WORKFLOW_REF', 'haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/other'))]
        changes += [('event', key, replacement) for key, replacement in (
            ('after', '2' * 40), ('ref', 'refs/heads/other'), ('deleted', True),
            ('head_commit', dict(id='2' * 40, message=PREFIX)),
            ('head_commit', dict(id=HEAD, message='unreviewed message')),
            ('repository', dict(full_name='haji84/RACE-AI', id=1416489937, private=True, fork=False)),
            ('repository', dict(full_name='other/RACE-AI', id=1416489937, private=False, fork=False)),
            ('repository', dict(full_name='haji84/RACE-AI', id=True, private=False, fork=False)))]
        for location, key, replacement in changes:
            with self.subTest(location=location, key=key, replacement=replacement):
                env, payload, value = environment(), event(), case(self.guard)
                (env if location == 'env' else payload)[key] = replacement
                _, loaded, _ = self.hold(value, 'TRUSTED_MAIN_REQUIRED', env=env, payload=payload)
                loaded.assert_not_called()

    def test_context_errors_flags_or_wrong_module_receipt_and_bootstrap_shapes_never_authorize_write(self):
        modes = ('raise', 'boolean', 'auth_flags', 'proof', 'candidate', 'guard',
            'feed', 'current', 'older', 'ref', 'bootstrap',
            'key_type', 'key_short', 'key_long')
        for mode in modes:
            with self.subTest(mode=mode):
                value = case(self.guard)
                context = value['context'].copy()
                loader = Mock(return_value=context)
                if mode == 'raise':
                    loader.side_effect = RuntimeError('private-sentinel-context https://private.invalid')
                elif mode == 'boolean':
                    loader.return_value = True
                elif mode == 'auth_flags':
                    loader.return_value = dict(authenticated=True, ready=True, proof=True)
                elif mode in ('proof', 'candidate', 'guard', 'feed'):
                    context[mode] = SimpleNamespace(authenticated=True)
                elif mode == 'current':
                    context['current'] = dict(authenticated=True, header=value['current']._header)
                elif mode == 'older':
                    context['older_chain'] = list(value['older'])
                elif mode == 'ref':
                    value['repository'].ref = 'state/other'
                elif mode == 'bootstrap':
                    context['bootstrap'] = dict(value['bootstrap'], view_id='0' * 64)
                else:
                    invalid_key = {'key_type': 'k' * 32,
                        'key_short': b'k' * 31, 'key_long': b'k' * 33}[mode]
                    context['bootstrap'] = dict(value['bootstrap'], key=invalid_key)
                self.hold(value, 'AUTHENTICATED_CONTEXT_UNAVAILABLE', loader=loader)

    def test_v5_current_receipt_digest_cipher_header_and_chain_bindings_are_rechecked(self):
        for mode in ('v4', 'view', 'header', 'cipher', 'source'):
            with self.subTest(mode=mode):
                value = case(self.guard, schema='RACE_AI_SAVED_WEB_VIEW_V4' if mode == 'v4' else V5)
                reason = 'V5_CURRENT_REQUIRED' if mode == 'v4' else 'INPUT_OR_CHAIN_INVALID'
                if mode == 'view':
                    value['current']._view['private-sentinel-tamper'] = True
                elif mode == 'header':
                    value['current']._header['generation'] += 1
                elif mode == 'cipher':
                    value['current']._ciphertext += b'private-sentinel-tamper'
                elif mode == 'source':
                    old = value['older'][0]
                    changed = deepcopy(old._header)
                    changed['source_content_sha256'] = '0' * 64
                    replacement = A._verified_snapshot(old._view, header=changed,
                        manifest_cipher_sha256=old._cipher_sha256,
                        snapshot_sha=old._snapshot_sha, ciphertext=old._ciphertext)
                    value['context']['older_chain'] = (replacement,)
                self.hold(value, reason)

    def test_incomplete_sidecar_only_and_conflicting_old_active_proof_never_create_partial_write(self):
        for mode in ('partial', 'sidecar', 'conflict'):
            with self.subTest(mode=mode):
                current, older = F.views()
                if mode == 'partial':
                    older['records'][0][F.ACTIVE].pop()
                elif mode == 'sidecar':
                    older['records'][0][F.ACTIVE] = []
                else:
                    older['records'][0][F.ACTIVE][0]['private-sentinel-unknown-field']['exact'].append('changed')
                value = case(self.guard, current_view=current, older_view=older)
                self.hold(value, 'ACTIVE_PROOF_CONFLICT' if mode == 'conflict' else 'ACTIVE_PROOF_MISSING')

    def test_healthy_v5_is_no_change_with_verified_zero_restore_counts_and_no_publication(self):
        current, older = F.views()
        current['records'][0][F.ACTIVE].extend(deepcopy(older['records'][0][F.ACTIVE]))
        value = case(self.guard, current_view=current, no_older=True)
        report, _, read = self.invoke(value)
        self.assertEqual(report['status'], 'NO_CHANGE')
        self.assertEqual(report['counts'], dict(snapshots_checked=1, orphan_groups=0,
            current_active_rejections=3, candidate_active_rejections=3,
            retained_history_originals=4, restored_active_originals=0, rows_changed=0))
        self.assertIs(report['publication_attempted'], False)
        self.assertIs(report['publication_performed'], False)
        self.assertIs(report['readback_verified'], False)
        for name in HASH_FIELDS[1:]:
            self.assertIsNone(report[name])
        value['feed'].publish_view.assert_not_called()
        value['repository'].head.assert_not_called()
        read.assert_not_called()

    def test_stale_predecessor_or_head_failure_is_a_prepublication_hold(self):
        for mode in ('changed', 'error'):
            with self.subTest(mode=mode):
                value = case(self.guard)
                if mode == 'changed':
                    value['repository'].head.return_value = '8' * 40
                else:
                    value['repository'].head.side_effect = RuntimeError('private-sentinel-head')
                self.hold(value, 'PREDECESSOR_CHANGED')
                value['repository'].head.assert_called_once_with()

    def test_cas_race_or_ambiguous_publisher_exception_is_attempted_once_without_retry(self):
        for message in ('FEED_CONCURRENT_UPDATE', 'private-sentinel-push https://private.invalid'):
            with self.subTest(message=message):
                value = case(self.guard)
                value['feed'].publish_view.side_effect = RuntimeError(message)
                _, _, read = self.hold(value, 'PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None)
                value['feed'].publish_view.assert_called_once()
                read.assert_not_called()

    def test_only_exact_existing_six_field_v5_ack_with_strict_types_is_accepted(self):
        changes = [('status', 'ENCRYPTED_VIEW_PUBLISHED'), ('generation', True),
            ('generation', 424), ('generation', '425'), ('commit', 'A' * 40),
            ('cipher_sha256', '0' * 63), ('updated_dates', True),
            ('updated_dates', 0), ('head_files', True), ('head_files', 3),
            ('extra', 'private-sentinel-ack'), ('missing', None)]
        for key, replacement in changes:
            with self.subTest(key=key, replacement=replacement):
                value = case(self.guard)
                ack = deepcopy(value['ack'])
                if key == 'missing':
                    ack.pop('updated_dates')
                else:
                    ack[key] = replacement
                value['feed'].publish_view.return_value = ack
                _, _, read = self.hold(value, 'PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None)
                value['feed'].publish_view.assert_called_once()
                read.assert_not_called()

    def test_valid_ack_then_failed_or_inexact_readback_stays_performed_true_without_retry(self):
        modes = ('error', 'forecast', 'result', 'observation', 'history', 'unknown', 'clock',
            'snapshot', 'cipher', 'generation', 'previous', 'view_id', 'source', 'schema', 'binding')
        for mode in modes:
            with self.subTest(mode=mode):
                value = case(self.guard)
                reopened = Mock(return_value=value['readback'])
                reason = 'READBACK_MISMATCH'
                if mode == 'error':
                    reopened.side_effect = RuntimeError('private-sentinel-reopen https://private.invalid')
                    reason = 'AUTHENTICATED_READBACK_UNAVAILABLE'
                elif mode in ('forecast', 'result', 'observation', 'history', 'unknown', 'clock'):
                    changed = deepcopy(value['expected'])
                    row = changed['records'][0]
                    if mode == 'forecast':
                        row['prediction']['private-sentinel-forecast'].append(6)
                    elif mode == 'result':
                        row['result']['status'] = 'final'
                    elif mode == 'observation':
                        row['result_observations'][0]['status'] = 'AVAILABLE'
                    elif mode == 'history':
                        row[F.HISTORY][0]['reason'] = 'RESULT_OTHER_REASON'
                    elif mode == 'unknown':
                        changed['private-sentinel-new-field'] = True
                    else:
                        row[F.ACTIVE][0]['captured_at'] = '2030-04-01T04:00:00Z'
                    reopened.return_value = mint(changed, 425, value['current']._cipher_sha256,
                        'changed-' + mode, snapshot=PUBLISHED)
                    # ACK must match the altered authenticated envelope; exact body still refuses.
                    value['feed'].publish_view.return_value['cipher_sha256'] = reopened.return_value._cipher_sha256
                else:
                    target = value['readback']
                    if mode == 'snapshot':
                        target._snapshot_sha = '8' * 40
                    elif mode == 'cipher':
                        target._cipher_sha256 = '0' * 64
                    elif mode == 'binding':
                        target._view['private-sentinel-after-mint'] = True
                    else:
                        name, replacement = {
                            'generation': ('generation', 426),
                            'previous': ('previous_cipher_sha256', '0' * 64),
                            'view_id': ('view_id', '0' * 64),
                            'source': ('source_content_sha256', '0' * 64),
                            'schema': ('schema', 'RACE_AI_SAVED_WEB_VIEW_V4'),
                        }[mode]
                        changed = deepcopy(target._header)
                        changed[name] = replacement
                        if mode == 'schema':
                            changed.pop('history_index_sha256')
                            changed['forecast_inventory_sha256'] = '9' * 64
                        reopened.return_value = A._verified_snapshot(target._view, header=changed,
                            manifest_cipher_sha256=target._cipher_sha256,
                            snapshot_sha=target._snapshot_sha, ciphertext=target._ciphertext)
                self.hold(value, reason, attempted=True, performed=True, reopened=reopened)
                value['feed'].publish_view.assert_called_once()
                reopened.assert_called_once()

    def test_private_context_publisher_reader_noise_and_unknown_fields_are_never_exported(self):
        value = case(self.guard)
        def noisy_load():
            print('private-sentinel-loader')
            print('private-sentinel-stderr', file=__import__('sys').stderr)
            return value['context']
        def noisy_publish(*args, **kwargs):
            print('private-sentinel-publisher')
            return deepcopy(value['ack'])
        def noisy_read(*args, **kwargs):
            print('private-sentinel-reader', file=__import__('sys').stderr)
            return value['readback']
        original_builder = C.build_rejection_anchor_restoration
        def noisy_builder(*args, **kwargs):
            print('private-sentinel-builder')
            return original_builder(*args, **kwargs)
        value['feed'].publish_view.side_effect = noisy_publish
        with patch.object(C, 'build_rejection_anchor_restoration', side_effect=noisy_builder):
            report, _, _ = self.invoke(value, loader=Mock(side_effect=noisy_load),
                reopened=Mock(side_effect=noisy_read))
        self.assertEqual(report['status'], 'PUBLISHED_VERIFIED')
        self.assertNotIn('private_extra', report)
        self.assertNotIn('key', report)

    def test_fixed_api_and_invalid_candidate_object_summary_or_counts_cannot_authorize_write(self):
        parameters = inspect.signature(R.run_repair).parameters
        self.assertEqual(tuple(parameters), ('environment', 'event', 'load_context'))
        self.assertEqual(parameters['load_context'].kind, inspect.Parameter.KEYWORD_ONLY)
        for mode in ('object', 'summary', 'count', 'hash'):
            with self.subTest(mode=mode):
                value = case(self.guard)
                candidate, report = C.build_rejection_anchor_restoration(
                    value['current'], value['older'], guard=self.guard, proof=A)
                self.assertEqual(report['status'], 'READY')
                if mode == 'object':
                    candidate = SimpleNamespace(_copy_view=lambda: deepcopy(value['expected']))
                elif mode == 'summary':
                    report['private_extra'] = 'private-sentinel-summary'
                elif mode == 'count':
                    report['counts']['restored_active_originals'] = True
                else:
                    report['candidate_view_sha256'] = '0' * 64
                with patch.object(C, 'build_rejection_anchor_restoration',
                        return_value=(candidate, report)):
                    self.hold(value, 'PUBLIC_CANDIDATE_INVALID')


if __name__ == '__main__':
    unittest.main()
