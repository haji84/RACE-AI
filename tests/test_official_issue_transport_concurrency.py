"""Synthetic Git data API only: no gh, provider, owner key or real state."""
from copy import deepcopy
from hashlib import sha1
import importlib
import unittest

from tests.test_official_issue_transport import FakeGitHub, PATH, PARENT, wire


class RacingGitHub(FakeGitHub):
    def __init__(self):
        self.counter = 0
        self.before_patch = None
        self.after_patch = None
        self.lose_ack = False
        super().__init__()

    def _commit(self, ident, files, parents=()):
        super()._commit(ident, files)
        self.commits[ident]['parents'] = [dict(sha=p) for p in parents]

    def append(self, additions):
        parent = self.ref
        self.counter += 1
        files = dict(self.snapshots[parent], **additions)
        ident = sha1(wire(dict(parent=parent, files=sorted(files), n=self.counter))).hexdigest()
        self.snapshots[ident] = files
        self._commit(ident, files, [parent])
        self.ref = ident
        return ident

    def __call__(self, method, path, body=None):
        if method == 'POST' and path == 'git/commits':
            raw = super().__call__(method, path, body)
            ident = sha1(wire(body)).hexdigest()
            self.commits[ident]['parents'] = [dict(sha=p) for p in body['parents']]
            return wire(self.commits[ident])
        if method == 'PATCH':
            self.calls.append((method, path, deepcopy(body)))
            if self.before_patch is not None:
                callback, self.before_patch = self.before_patch, None
                callback(self)
            commit = self.commits[body['sha']]
            if commit['parents'] != [dict(sha=self.ref)]:
                raise ValueError('non-fast-forward conflict')
            self.ref = body['sha']
            if self.after_patch is not None:
                callback, self.after_patch = self.after_patch, None
                callback(self)
            if self.lose_ack:
                raise ValueError('response lost after the real update')
            return wire(dict(ref='refs/heads/state/boat-pdca-transfer',
                             object=dict(type='commit', sha=body['sha'])))
        return super().__call__(method, path, body)


class ConcurrentTransportTests(unittest.TestCase):
    def module(self):
        return importlib.import_module('race_ai.all_existing_model_official_issue_transport')

    def publish(self, transport, **kwargs):
        try:
            return transport.publish_capsule(PATH, b'exact-opaque-cipher', PARENT, **kwargs)
        except (ValueError, TypeError) as error:
            self.fail('safe append must retain the one original ciphertext: ' + str(error))

    def test_append_after_success_does_not_turn_an_issued_capsule_into_a_false_hold(self):
        api = RacingGitHub()
        api.after_patch = lambda store: store.append({'other/new.enc': b'another-original'})
        transport = self.module().GithubIssueTransport(api)
        commit = self.publish(transport)
        self.assertEqual(api.commits[api.ref]['parents'], [dict(sha=commit)])
        self.assertEqual(api.snapshots[api.ref], {
            'keep/original.enc': b'unchanged', PATH: b'exact-opaque-cipher',
            'other/new.enc': b'another-original'})
        self.assertEqual(transport.read_file(commit, PATH, 1024), b'exact-opaque-cipher')
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)

    def test_append_during_context_preparation_rebases_the_same_bytes(self):
        api = RacingGitHub()
        api.append({'other/new.enc': b'another-original'})
        checks = []
        transport = self.module().GithubIssueTransport(api)
        commit = self.publish(transport, before_publish=lambda: checks.append('admitted'))
        self.assertEqual(api.snapshots[commit], {
            'keep/original.enc': b'unchanged', 'other/new.enc': b'another-original',
            PATH: b'exact-opaque-cipher'})
        self.assertEqual(checks, ['admitted'])
        self.assertEqual(sum(m == 'POST' and p == 'git/blobs' for m, p, _ in api.calls), 1)

    def test_cas_conflict_rechecks_admission_without_regenerating_the_blob(self):
        api = RacingGitHub()
        api.before_patch = lambda store: store.append({'other/new.enc': b'new'})
        checks = []
        commit = self.publish(self.module().GithubIssueTransport(api),
                              before_publish=lambda: checks.append('admitted'))
        self.assertEqual(api.snapshots[commit][PATH], b'exact-opaque-cipher')
        self.assertEqual(api.snapshots[commit]['other/new.enc'], b'new')
        self.assertEqual(checks, ['admitted', 'admitted'])
        self.assertEqual(sum(m == 'POST' and p == 'git/blobs' for m, p, _ in api.calls), 1)
        self.assertEqual([body['force'] for m, _, body in api.calls if m == 'PATCH'], [False, False])

    def test_rejected_candidate_search_does_not_walk_below_a_deep_known_parent(self):
        api = RacingGitHub()
        # Real transfer refs already have far more than64 historic commits.
        # Those older ancestors cannot contain the new unpublished candidate.
        child = PARENT
        for n in range(70):
            older = sha1(('historic-' + str(n)).encode()).hexdigest()
            api.commits[child]['parents'] = [dict(sha=older)]
            api.snapshots[older] = dict(api.snapshots[PARENT])
            api._commit(older, api.snapshots[older])
            child = older
        api.before_patch = lambda store: store.append({'other/new.enc': b'new'})
        checks = []
        commit = self.publish(self.module().GithubIssueTransport(api),
                              before_publish=lambda: checks.append(True))
        self.assertEqual(checks, [True, True])
        self.assertEqual(api.snapshots[commit][PATH], b'exact-opaque-cipher')
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 2)
        older_reads = [p for m, p, _ in api.calls if m == 'GET' and
                       p.startswith('git/commits/') and p.rsplit('/', 1)[1] not in
                       (PARENT, commit, api.commits[commit]['parents'][0]['sha'])]
        self.assertEqual(older_reads, [])

    def test_lost_ack_of_success_is_read_back_without_a_second_publication(self):
        for append_after in (False, True):
            with self.subTest(append_after=append_after):
                api = RacingGitHub(); api.lose_ack = True
                if append_after:
                    api.after_patch = lambda store: store.append({'other/new.json': b'index'})
                commit = self.publish(self.module().GithubIssueTransport(api), before_publish=lambda: None)
                self.assertEqual(api.snapshots[api.ref][PATH], b'exact-opaque-cipher')
                self.assertEqual(self.module().GithubIssueTransport(api).read_file(commit, PATH, 1024),
                                 b'exact-opaque-cipher')
                self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)

    def test_no_ack_and_unchanged_ref_holds_without_retry(self):
        class Uncertain(RacingGitHub):
            def __call__(self, method, path, body=None):
                if method == 'PATCH':
                    self.calls.append((method, path, deepcopy(body)))
                    raise ValueError('request outcome unknown')
                return super().__call__(method, path, body)
        api = Uncertain()
        with self.assertRaisesRegex(self.module().PublicationUnconfirmed, 'PUBLICATION_UNCONFIRMED') as caught:
            self.module().GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)
        self.assertNotIn(PATH, api.snapshots[api.ref])
        evidence = caught.exception.publication_attempt
        self.assertEqual(evidence['expected_parent'], PARENT)
        self.assertEqual(evidence['observed_head'], PARENT)
        self.assertEqual(evidence['capsule_path'], PATH)
        self.assertEqual(evidence['state'], 'UNCONFIRMED_DO_NOT_REISSUE')
        self.assertEqual(evidence['source_requests'], 0)

    def test_known_github_denial_is_never_retried_even_with_another_append(self):
        module = self.module()
        class Denied(RacingGitHub):
            def __call__(self, method, path, body=None):
                if method == 'PATCH':
                    self.calls.append((method, path, deepcopy(body)))
                    self.append({'other/new.enc': b'new'})
                    raise module._GitHubDenied()
                return super().__call__(method, path, body)
        api = Denied()
        with self.assertRaisesRegex(ValueError, 'GITHUB_DENIED'):
            module.GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)
        self.assertNotIn(PATH, api.snapshots[api.ref])

    def test_post_publication_read_failure_preserves_safe_recovery_hashes(self):
        module = self.module()
        class LostRead(RacingGitHub):
            unreadable = False
            def __call__(self, method, path, body=None):
                if self.unreadable and method == 'GET':
                    raise ValueError('private server failure')
                result = super().__call__(method, path, body)
                if method == 'PATCH':
                    self.unreadable = True
                return result
        api = LostRead()
        with self.assertRaises(module.PublicationUnconfirmed) as caught:
            module.GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
        evidence = caught.exception.publication_attempt
        self.assertEqual(evidence['commit_sha'], api.ref)
        self.assertEqual(evidence['capsule_path'], PATH)
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)
        api.unreadable = False
        self.assertEqual(module.GithubIssueTransport(api).read_file(api.ref, PATH, 1024),
                         b'exact-opaque-cipher')

    def test_original_deletion_and_pointer_mode_change_are_rejected(self):
        for variant in ('delete', 'mode'):
            with self.subTest(variant=variant):
                api = RacingGitHub()
                pointer = 'state/boat-racer-daily/v1/latest.json'
                api.snapshots[PARENT][pointer] = b'old'; api._commit(PARENT, api.snapshots[PARENT])
                later = api.append({'other/new.json': b'new'})
                if variant == 'delete':
                    del api.snapshots[later]['keep/original.enc']
                    api._commit(later, api.snapshots[later], [PARENT])
                else:
                    def changed_mode(tree, parts):
                        rows = deepcopy(api.trees[tree])
                        row = next(row for row in rows if row['path'] == parts[0])
                        if len(parts) == 1:
                            row['mode'] = '120000'
                        else:
                            row['sha'] = changed_mode(row['sha'], parts[1:])
                        ident = sha1(wire(rows)).hexdigest(); api.trees[ident] = rows
                        return ident
                    api.commits[later]['tree']['sha'] = changed_mode(
                        api.commits[later]['tree']['sha'], pointer.split('/'))
                with self.assertRaisesRegex(ValueError, 'ORIGINAL_REMOVED_OR_MODE_CHANGED'):
                    module = self.module()
                    module.GithubIssueTransport(api).publish_capsule(
                        PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
                self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_deep_ancestry_has_a_fixed_read_bound_before_any_mutation(self):
        module = self.module(); api = RacingGitHub()
        for n in range(module.MAX_ANCESTRY_COMMITS + 1):
            api.append({'other/' + str(n) + '.json': b'new'})
        with self.assertRaisesRegex(ValueError, 'REF_ANCESTRY_BOUND'):
            module.GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
        self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_fresh_admission_failure_never_moves_the_ref(self):
        for reason in ('expired', 'PR advanced', 'first attempt changed'):
            with self.subTest(reason=reason):
                api = RacingGitHub()
                def reject():
                    raise ValueError(reason)
                with self.assertRaisesRegex(ValueError, reason):
                    self.module().GithubIssueTransport(api).publish_capsule(
                        PATH, b'exact-opaque-cipher', PARENT, before_publish=reject)
                self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))
                self.assertEqual(api.ref, PARENT)

    def test_only_exact_known_mutable_pointer_changes_can_be_carried(self):
        pointer = 'state/boat-racer-intraday/v1/latest.json'
        for path in (pointer, 'unknown/latest.json', 'state/boat-private-originals/v1/2026-11/batches/' +
                     '1' * 64 + '.json', 'keep/original.enc', 'raw/metadata.json'):
            with self.subTest(path=path):
                api = RacingGitHub()
                api.snapshots[PARENT][path] = b'old'; api._commit(PARENT, api.snapshots[PARENT])
                api.append({path: b'new'})
                transport = self.module().GithubIssueTransport(api)
                if path == pointer:
                    commit = self.publish(transport, before_publish=lambda: None)
                    self.assertEqual(api.snapshots[commit][pointer], b'new')
                else:
                    with self.assertRaisesRegex(ValueError, 'IMMUTABLE_ORIGINAL_CHANGED'):
                        transport.publish_capsule(PATH, b'exact-opaque-cipher', PARENT,
                                                  before_publish=lambda: None)
                    self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_ref_rewind_and_divergence_with_equal_tree_cannot_publish(self):
        for variant in ('rewind', 'divergence'):
            with self.subTest(variant=variant):
                api = RacingGitHub()
                if variant == 'rewind':
                    expected = api.append({'later/one.json': b'new'}); api.ref = PARENT
                else:
                    expected = PARENT; api.ref = 'e' * 40
                    api.snapshots[api.ref] = dict(api.snapshots[PARENT])
                    api._commit(api.ref, api.snapshots[api.ref])
                with self.assertRaisesRegex(ValueError, 'REF_NOT_DESCENDANT'):
                    self.module().GithubIssueTransport(api).publish_capsule(
                        PATH, b'exact-opaque-cipher', expected, before_publish=lambda: None)
                self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_conflicting_canonical_path_is_never_overwritten(self):
        api = RacingGitHub(); api.append({PATH: b'another-cipher'})
        with self.assertRaisesRegex(ValueError, 'CAPSULE_ALREADY_EXISTS'):
            self.module().GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: None)
        self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_persistent_contention_is_bounded_and_keeps_every_other_original(self):
        class AlwaysRacing(RacingGitHub):
            def __call__(self, method, path, body=None):
                if method == 'PATCH':
                    self.before_patch = lambda store: store.append({
                        'other/' + str(store.counter) + '.enc': b'another-original'})
                return super().__call__(method, path, body)
        api = AlwaysRacing(); checks = []
        with self.assertRaisesRegex(ValueError, 'CONCURRENT_REF_BOUND'):
            self.module().GithubIssueTransport(api).publish_capsule(
                PATH, b'exact-opaque-cipher', PARENT, before_publish=lambda: checks.append(True))
        self.assertEqual(len(checks), 3)
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 3)
        self.assertEqual(sum(m == 'POST' and p == 'git/blobs' for m, p, _ in api.calls), 1)
        self.assertNotIn(PATH, api.snapshots[api.ref])
        self.assertEqual(len(api.snapshots[api.ref]), 4)


if __name__ == '__main__':
    unittest.main()
