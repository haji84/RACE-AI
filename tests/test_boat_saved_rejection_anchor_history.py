"""Synthetic immediate-ancestry discovery; existing authenticated reader owns AEAD."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from scripts import boat_saved_rejection_anchor_audit as S
from tests.test_boat_saved_rejection_anchor_io import (
    FLAGS, CURRENT, OLDER, header, load_guard, reader_feed, receipt,
    trusted_environment, trusted_event, view, wire,
)

PARENT = '4' * 40
DUPLICATE = '5' * 40
DEEPER = '6' * 40
RACE = '20300401-01-01'
DAY = '2030-04-01'
SOURCE = 'f' * 64


def commit_object(parent, *, message='private-commit-message-sentinel', signed=False):
    lines = ['tree ' + 'a' * 40]
    if parent is not None:
        lines.append('parent ' + parent)
    lines += ['author Invented Test <fixture@example.invalid> 1893456000 +0000',
              'committer Invented Test <fixture@example.invalid> 1893456000 +0000']
    if signed:
        lines += ['gpgsig -----BEGIN PGP SIGNATURE-----',
                  ' private-signature-sentinel',
                  ' parent ' + 'e' * 40,
                  ' -----END PGP SIGNATURE-----']
    return ('\n'.join(lines) + '\n\n' + message + '\n').encode('utf-8')


def manifest(document_header, cipher):
    return wire(dict(header=document_header, cipher_sha256=cipher))


class AncestryRepository:
    def __init__(self, commits, manifests, *, initial=CURRENT):
        self.commits = dict(commits)
        self.manifests = dict(manifests)
        self.initial = initial
        self.fetched = {initial}
        self.calls = []
        self.modes = {}

    def head(self):
        raise AssertionError('mutable-head-must-not-be-read')

    def fetch(self, commit):
        self.calls.append(('fetch', commit))
        if type(commit) is not str or len(commit) != 40:
            raise AssertionError('immutable-parent-required')
        self.fetched.add(commit)

    def read(self, commit, path, maximum):
        self.calls.append(('read', commit, path, maximum))
        if commit not in self.fetched or path != 'latest.json':
            raise AssertionError('only-fetched-selected-manifests-may-be-read')
        raw = self.manifests[commit]
        if len(raw) > maximum:
            raise ValueError('INVENTED_MANIFEST_BOUND')
        return raw

    def _run(self, args, **kwargs):
        self.calls.append(('git', tuple(args)))
        if args[:1] == ['cat-file'] and len(args) == 3:
            operation, commit = args[1:]
            if commit.endswith('^{commit}'):
                commit = commit[:-9]
            if commit not in self.fetched:
                raise AssertionError('commit-must-be-fetched-before-inspection')
            raw = self.commits[commit]
            if operation == '-s':
                return (str(len(raw)) + '\n').encode('ascii')
            if operation == '-t':
                return b'commit\n'
            if operation == '-p':
                return raw
        if args[:1] == ['ls-tree'] and len(args) == 4 and args[2:] == ['--', 'latest.json']:
            commit = args[1]
            if commit not in self.fetched:
                raise AssertionError('parent-must-be-fetched-before-manifest-mode-check')
            mode, kind = self.modes.get(commit, ('100644', 'blob'))
            return (mode + ' ' + kind + ' ' + 'b' * 40 + '\tlatest.json\n').encode('utf-8')
        raise AssertionError('only-cat-file-and-selected-latest-ls-tree-are-allowed')

    def commit(self, *args, **kwargs):
        raise AssertionError('no-private-commit')

    def commit_snapshot(self, *args, **kwargs):
        raise AssertionError('no-private-commit-snapshot')

    def push(self, *args, **kwargs):
        raise AssertionError('no-private-push')


def direct_fixture():
    older_raw = b'invented-older-authenticated-reader-cipher'
    current_raw = b'invented-newer-authenticated-reader-cipher'
    previous = hashlib.sha256(older_raw).hexdigest()
    current = receipt(view(), 424, previous, CURRENT, current_raw)
    repository = AncestryRepository(
        {CURRENT: commit_object(PARENT), PARENT: commit_object(DEEPER)},
        {PARENT: manifest(header(423, '0' * 64), previous)})
    return current, repository


def rejection(reason='RESULT_FIRST_ORIGINAL'):
    return dict(captured_at='2030-04-01T11:00:00+09:00',
        source_sha256=SOURCE, reason=reason, private_payload='private-rejection-body-sentinel')


def rejection_view(*, active=False, orphan=False, invalid=False):
    result = view()
    row = dict(race_id=RACE, sport='boat', event_date_jst=DAY, race_no=1,
        result_observations=[], result_observation_rejections=[])
    if active:
        row['result_observation_rejections'] = [rejection()]
    if orphan:
        row['saved_result_rejection_reason_variants'] = [
            rejection(), rejection('RESULT_SECOND_ORIGINAL')]
    if invalid:
        row['saved_result_rejection_reason_variants'][1]['private_payload'] = 'changed-private-body'
    result['records'] = [row]
    return result


def receipt_chain(older_views, *, current_active=False, invalid_current=False):
    oldest = min(older_views)
    previous = '0' * 64
    receipts = {}
    for generation in range(oldest, 425):
        raw = ('invented-chain-cipher-' + str(generation)).encode('ascii')
        value = (rejection_view(active=current_active, orphan=True, invalid=invalid_current)
                 if generation == 424 else deepcopy(older_views[generation]))
        snapshot = format(generation, '040x')
        receipts[generation] = receipt(value, generation, previous, snapshot, raw)
        previous = hashlib.sha256(raw).hexdigest()
    return receipts


class BoundedAncestryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(S, '_find_predecessor_commit', None)),
            'bounded rejection-anchor ancestry search is missing')
        self.assertTrue(callable(getattr(S, '_extend_authenticated_chain', None)),
            'authenticated rejection-anchor chain extension is missing')
        self.guard = load_guard()

    def find(self, repository, current, *, budget=None, max_hops=128):
        return S._find_predecessor_commit(repository, current,
            feed=reader_feed(), budget=S.ReadBudget() if budget is None else budget,
            max_hops=max_hops)

    def assert_hold(self, callback, reason):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
                self.assertRaises(S.AncestryHold) as caught:
            callback()
        self.assertEqual(caught.exception.reason, reason)
        self.assertNotIn('private-', str(caught.exception))
        self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_immediate_regular_parent_is_selected_using_raw_commit_headers(self):
        current, repository = direct_fixture()
        budget = S.ReadBudget()
        before = budget.remaining
        found = self.find(repository, current, budget=budget)
        self.assertEqual(found, PARENT)
        self.assertIn(('fetch', PARENT), repository.calls)
        self.assertLessEqual(budget.remaining, before -
            len(repository.commits[CURRENT]) - len(repository.manifests[PARENT]))
        self.assertEqual(budget.remaining_hops, 127)
        self.assertTrue(any(call[0] == 'git' and call[1][:2] == ('cat-file', '-p')
            for call in repository.calls))
        self.assertTrue(any(call[0] == 'git' and call[1] == ('ls-tree', PARENT, '--', 'latest.json')
            for call in repository.calls))
        self.assertFalse(any(call[0] == 'read' and call[2] != 'latest.json'
            for call in repository.calls))

    def test_signed_headers_and_parent_words_in_message_never_create_another_parent(self):
        current, repository = direct_fixture()
        repository.commits[CURRENT] = commit_object(PARENT,
            message='parent ' + DEEPER + '\nprivate-message-sentinel', signed=True)
        self.assertEqual(self.find(repository, current), PARENT)
        self.assertNotIn(('fetch', DEEPER), repository.calls)
        self.assertNotIn(('fetch', 'e' * 40), repository.calls)

    def test_only_identical_generation_header_and_cipher_metadata_may_be_skipped(self):
        current, repository = direct_fixture()
        repository.commits[CURRENT] = commit_object(DUPLICATE)
        repository.commits[DUPLICATE] = commit_object(PARENT)
        repository.manifests[DUPLICATE] = manifest(current._header, current._cipher_sha256)
        budget = S.ReadBudget()
        self.assertEqual(self.find(repository, current, budget=budget), PARENT)
        self.assertEqual([call[1] for call in repository.calls
            if call[0] == 'fetch' and call[1] != CURRENT], [DUPLICATE, PARENT])
        self.assertEqual(budget.remaining_hops, 126)

    def test_same_generation_different_header_or_cipher_stops_without_cherry_picking(self):
        for change in ('cipher', 'source', 'view', 'forecast'):
            current, repository = direct_fixture()
            repository.commits[CURRENT] = commit_object(DUPLICATE)
            repository.commits[DUPLICATE] = commit_object(PARENT)
            bad_header = deepcopy(current._header); cipher = current._cipher_sha256
            if change == 'cipher':
                cipher = 'e' * 64
            else:
                field = {'source': 'source_content_sha256', 'view': 'view_id',
                         'forecast': 'forecast_sha256'}[change]
                bad_header[field] = 'e' * 64
            repository.manifests[DUPLICATE] = manifest(bad_header, cipher)
            with self.subTest(change=change):
                self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')
                self.assertNotIn(('fetch', PARENT), repository.calls)

    def test_first_distinct_wrong_generation_or_cipher_never_searches_a_later_valid_ancestor(self):
        for change in ('generation', 'cipher'):
            current, repository = direct_fixture()
            expected = current._header['previous_cipher_sha256']
            bad_header = header(422 if change == 'generation' else 423, '0' * 64)
            repository.manifests[PARENT] = manifest(bad_header,
                'e' * 64 if change == 'cipher' else expected)
            repository.manifests[DEEPER] = manifest(header(423, '0' * 64), expected)
            with self.subTest(change=change):
                self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')
                self.assertNotIn(('fetch', DEEPER), repository.calls)

    def test_missing_merge_malformed_or_message_only_parent_headers_hold(self):
        current, base = direct_fixture()
        valid = commit_object(PARENT)
        bad = [
            commit_object(None),
            valid.replace(('parent ' + PARENT + '\n').encode(),
                ('parent ' + PARENT + '\nparent ' + DEEPER + '\n').encode()),
            valid.replace(('parent ' + PARENT).encode(), b'parent main'),
            valid.replace(('tree ' + 'a' * 40).encode(), b'tree not-a-tree-sha'),
            valid.replace(('tree ' + 'a' * 40 + '\n').encode(),
                ('tree ' + 'a' * 40 + '\ntree ' + 'b' * 40 + '\n').encode()),
            commit_object(None, message='parent ' + PARENT),
            valid.replace(b'\n\n', b'\n', 1),
            valid.replace(b'parent ', b'parent \x00', 1),
            valid.replace(b'\n', b'\r\n'),
        ]
        for index, raw in enumerate(bad):
            repository = AncestryRepository({CURRENT: raw}, base.manifests)
            with self.subTest(case=index):
                self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')
                self.assertFalse(any(call[0] == 'fetch' for call in repository.calls))

    def test_selected_manifest_mode_or_shape_cannot_supply_parent_authority(self):
        for mode, kind in (('120000', 'blob'), ('100755', 'blob'), ('040000', 'tree')):
            current, repository = direct_fixture()
            repository.modes[PARENT] = (mode, kind)
            with self.subTest(mode=mode):
                self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')
        for value in ({}, [], dict(header=header(423, '0' * 64), cipher_sha256='private-cipher-sentinel'),
                      dict(header=header(423, '0' * 64), cipher_sha256='e' * 64, extra=True)):
            current, repository = direct_fixture()
            repository.manifests[PARENT] = wire(value)
            with self.subTest(shape=type(value).__name__):
                self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')

    def test_parent_cycles_and_invalid_local_hop_overrides_hold_without_fetching_again(self):
        current, repository = direct_fixture()
        repository.commits[CURRENT] = commit_object(CURRENT)
        self.assert_hold(lambda: self.find(repository, current), 'INPUT_OR_CHAIN_INVALID')
        self.assertFalse(any(call[0] == 'fetch' for call in repository.calls))
        for limit in (0, True, -1, 129, '128'):
            current, repository = direct_fixture()
            with self.subTest(limit=limit):
                self.assert_hold(lambda: self.find(repository, current, max_hops=limit),
                    'INPUT_OR_CHAIN_INVALID')
                self.assertEqual(repository.calls, [])

    def test_local_and_shared_hop_exhaustion_are_explicit_bounds_without_fetching_past_them(self):
        current, repository = direct_fixture()
        repository.commits[CURRENT] = commit_object(DUPLICATE)
        repository.commits[DUPLICATE] = commit_object(PARENT)
        repository.manifests[DUPLICATE] = manifest(current._header, current._cipher_sha256)
        self.assert_hold(lambda: self.find(repository, current, max_hops=1), 'BOUND_EXCEEDED')
        self.assertNotIn(('fetch', PARENT), repository.calls)
        budget = S.ReadBudget(hop_limit=1)
        current, first = direct_fixture()
        self.assertEqual(self.find(first, current, budget=budget), PARENT)
        self.assertEqual(budget.remaining_hops, 0)
        current, second = direct_fixture()
        self.assert_hold(lambda: self.find(second, current, budget=budget), 'BOUND_EXCEEDED')
        self.assertFalse(any(call[0] == 'fetch' for call in second.calls))

    def test_commit_size_and_remaining_byte_limits_stop_before_payload_read(self):
        current, repository = direct_fixture()
        raw = repository.commits[CURRENT]
        budget = S.ReadBudget(limit=len(raw) - 1)
        self.assert_hold(lambda: self.find(repository, current, budget=budget), 'BOUND_EXCEEDED')
        self.assertFalse(any(call[0] == 'git' and call[1][:2] == ('cat-file', '-p')
            for call in repository.calls))
        current, repository = direct_fixture()
        repository.commits[CURRENT] = commit_object(PARENT, message='x' * (64 * 1024))
        self.assert_hold(lambda: self.find(repository, current), 'BOUND_EXCEEDED')
        self.assertFalse(any(call[0] == 'git' and call[1][:2] == ('cat-file', '-p')
            for call in repository.calls))

    def test_hop_budget_constructor_and_consumption_keep_the_global_hard_cap(self):
        budget = S.ReadBudget(hop_limit=2)
        self.assertEqual(budget.remaining_hops, 2)
        budget.hop(); self.assertEqual(budget.remaining_hops, 1)
        budget.hop(); self.assertEqual(budget.remaining_hops, 0)
        self.assert_hold(budget.hop, 'BOUND_EXCEEDED')
        for limit in (0, True, -1, 129, '128'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                S.ReadBudget(hop_limit=limit)

    def test_extension_reads_one_more_authenticated_same_day_receipt_then_stops_when_proven(self):
        receipts = receipt_chain({422: rejection_view(active=True), 423: rejection_view()})
        current, first, proof = receipts[424], receipts[423], receipts[422]
        initial = (first,); calls = []
        repository, bootstrap, feed, budget = object(), object(), reader_feed(), S.ReadBudget()
        def find(actual_repository, newer, *, feed, budget, max_hops=128):
            self.assertIs(actual_repository, repository)
            self.assertIs(newer, first)
            calls.append(('find', newer._snapshot_sha))
            return proof._snapshot_sha
        def read(actual_repository, actual_bootstrap, candidate, *, feed, guard, budget, day=None):
            self.assertIs(actual_repository, repository); self.assertIs(actual_bootstrap, bootstrap)
            self.assertIs(guard, self.guard); self.assertEqual(candidate, proof._snapshot_sha)
            self.assertEqual(day, DAY)
            calls.append(('read', candidate, day))
            return proof
        with patch.object(S, '_find_predecessor_commit', side_effect=find), \
                patch.object(S, '_read_verified_snapshot', side_effect=read):
            result = S._extend_authenticated_chain(repository, bootstrap, current, initial,
                feed=feed, guard=self.guard, budget=budget)
        self.assertEqual(result, (first, proof))
        self.assertEqual(initial, (first,))
        self.assertEqual(calls, [('find', first._snapshot_sha), ('read', proof._snapshot_sha, DAY)])
        summary = S.match_rejection_anchor_proofs(current, result, guard=self.guard).public_summary()
        self.assertEqual(summary['status'], 'ALL_ORPHAN_ANCHORS_PROVEN')
        self.assertEqual(summary['counts']['proved_groups'], 1)
        self.assertFalse(summary['originals_changed'])

    def test_extension_rechecks_each_step_and_never_treats_an_intermediate_missing_proof_as_absence(self):
        receipts = receipt_chain({421: rejection_view(active=True),
            422: rejection_view(), 423: rejection_view()})
        current, initial = receipts[424], (receipts[423],)
        searched, read_days = [], []
        def find(repository, newer, *, feed, budget, max_hops=128):
            searched.append(newer._header['generation'])
            return receipts[newer._header['generation'] - 1]._snapshot_sha
        def read(repository, bootstrap, candidate, *, feed, guard, budget, day=None):
            read_days.append(day)
            return next(item for item in receipts.values() if item._snapshot_sha == candidate)
        with patch.object(S, '_find_predecessor_commit', side_effect=find), \
                patch.object(S, '_read_verified_snapshot', side_effect=read):
            result = S._extend_authenticated_chain(object(), object(), current, initial,
                feed=reader_feed(), guard=self.guard, budget=S.ReadBudget())
        self.assertEqual(searched, [423, 422])
        self.assertEqual(read_days, [DAY, DAY])
        self.assertEqual(result, (receipts[423], receipts[422], receipts[421]))
        self.assertEqual(S.match_rejection_anchor_proofs(
            current, result, guard=self.guard).public_summary()['status'],
            'ALL_ORPHAN_ANCHORS_PROVEN')

    def test_bound_current_proven_current_or_other_hold_never_searches_more_ancestors(self):
        cases = [
            receipt_chain({423: rejection_view()}, current_active=True),
            receipt_chain({423: rejection_view(active=True)}),
            receipt_chain({423: rejection_view()}, invalid_current=True),
        ]
        expected = ['NO_ORPHAN_ANCHORS', 'ALL_ORPHAN_ANCHORS_PROVEN', 'HOLD']
        for receipts, status in zip(cases, expected):
            current, initial = receipts[424], (receipts[423],)
            self.assertEqual(S.match_rejection_anchor_proofs(
                current, initial, guard=self.guard).public_summary()['status'], status)
            with self.subTest(status=status), patch.object(S, '_find_predecessor_commit') as find, \
                    patch.object(S, '_read_verified_snapshot') as read:
                result = S._extend_authenticated_chain(object(), object(), current, initial,
                    feed=reader_feed(), guard=self.guard, budget=S.ReadBudget())
            self.assertEqual(result, initial)
            find.assert_not_called(); read.assert_not_called()

    def test_extension_bounds_discard_partial_results_and_run_audit_reports_fixed_null_hold(self):
        receipts = receipt_chain({422: rejection_view(), 423: rejection_view()})
        current, initial = receipts[424], (receipts[423],)
        searched = []
        def bounded(repository, newer, *, feed, budget, max_hops=128):
            searched.append(newer._header['generation'])
            if newer._header['generation'] == 423:
                return receipts[422]._snapshot_sha
            print('private-search-stdout-sentinel')
            print('private-search-stderr-sentinel', file=sys.stderr)
            raise S.AncestryHold('BOUND_EXCEEDED')
        def read(repository, bootstrap, candidate, *, feed, guard, budget, day=None):
            self.assertEqual(candidate, receipts[422]._snapshot_sha)
            self.assertEqual(day, DAY)
            return receipts[422]
        with patch.object(S, '_find_predecessor_commit', side_effect=bounded), \
                patch.object(S, '_read_verified_snapshot', side_effect=read):
            def load():
                older = S._extend_authenticated_chain(object(), object(), current, initial,
                    feed=reader_feed(), guard=self.guard, budget=S.ReadBudget())
                return current, older, self.guard
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                report = S.run_audit(trusted_environment(), trusted_event(), load_pair=load)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertEqual(report['status'], 'HOLD')
        self.assertEqual(report['reason'], 'BOUND_EXCEEDED')
        self.assertEqual(searched, [423, 422])
        self.assertIsNone(report['counts'])
        self.assertEqual(report['snapshots'], [])
        self.assertEqual({name: report[name] for name in FLAGS}, FLAGS)
        self.assertNotIn('private-', json.dumps(report))
        self.assertEqual(initial, (receipts[423],))
        before = S.match_rejection_anchor_proofs(current, initial, guard=self.guard).public_summary()
        self.assertEqual(before['reason'], 'ACTIVE_PROOF_MISSING')


    def test_generic_reader_failure_does_not_become_a_bound_or_absence_claim(self):
        def load():
            raise RuntimeError('private-reader-error-sentinel https://private.invalid/')
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            report = S.run_audit(trusted_environment(), trusted_event(), load_pair=load)
        self.assertEqual(report['status'], 'HOLD')
        self.assertEqual(report['reason'], 'AUTHENTICATED_PAIR_UNAVAILABLE')
        self.assertIsNone(report['counts'])
        self.assertEqual(report['snapshots'], [])
        self.assertNotIn('private-', json.dumps(report))
        self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_ancestry_exception_never_stores_or_echoes_an_unapproved_reason(self):
        try:
            failure = S.AncestryHold('private-reason-sentinel https://private.invalid/')
        except ValueError as failure:
            self.assertNotIn('private-', str(failure))
        else:
            self.assertIn(failure.reason, ('BOUND_EXCEEDED', 'INPUT_OR_CHAIN_INVALID'))
            self.assertNotIn('private-', str(failure))


if __name__ == '__main__':
    unittest.main()
