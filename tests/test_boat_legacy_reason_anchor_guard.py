"""Synthetic legacy publication-boundary contracts; no source, key or network I/O.

The two hash-bound fixtures contain verbatim public legacy functions. The
existing reason-binding test loader supplies the unchanged pinned e6db guard.
These tests do not add an updater adapter or modify a legacy guard API.
"""
import ast
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import io
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.test_boat_saved_reason_binding_audit import load_guard, fixture, wire

try:
    adapter = importlib.import_module('scripts.boat_legacy_reason_anchor_guard')
except ModuleNotFoundError as error:
    if error.name != 'scripts.boat_legacy_reason_anchor_guard':
        raise
    adapter = None

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "ffb": ("tests/fixtures/legacy_saved_view_feed_ffb_update.py", "2062fc2f5e1648bb0fc4b5b199045713e5de3b9b"),
    "3295": ("tests/fixtures/legacy_saved_view_feed_3295_update.py", "95956bfb870c11229f9e216b1b4dc8e15b551bdd"),
}
SIDES = (
    ('result_observations', 'saved_result_observation_reason_variants', False),
    ('result_observation_rejections', 'saved_result_rejection_reason_variants', True),
)
MUTABLE = {'result', 'result_revisions', 'result_observations',
    'result_observation_rejections', 'missing_reasons', 'live_boat_observation'}
PARENT = 'a' * 40
PREVIOUS = 'b' * 64
NEW_CLOCK = '2030-04-01T12:00:00+09:00'
SYNC_CLOCK = '2030-04-01T13:00:00+09:00'


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(wire(value).encode('utf-8')).hexdigest()


def strict_merge(items):
    """Synthetic strict duplicate handling; never creates reason exceptions."""
    output = {}
    for item in items:
        key = (item['race_id'], instant(item['captured_at']))
        need(key not in output or wire(output[key]) == wire(item), 'RESULT_CAPTURE_CONFLICT')
        output[key] = deepcopy(item)
    return sorted(output.values(), key=lambda item: instant(item['captured_at']))


def view_with(*kinds):
    value = fixture(*kinds)
    value['forecast_base_sha256'] = 'c' * 64
    row = value['records'][0]
    row.update(sport='boat', event_date_jst='2030-04-01',
        cutoff_at='2030-04-01T10:00:00+09:00', missing_reasons=[],
        prediction=dict(model_id='SYNTHETIC_MODEL', persisted_at='2030-04-01T09:00:00+09:00'),
        comparison_predictions=[], result=None)
    return value


def new_observation():
    return dict(race_id='20300401-01-01', captured_at=NEW_CLOCK,
        source_sha256='e' * 64, source_url='synthetic://result',
        closed_at='2030-04-01T10:00:00+09:00', body_identity_verified=False,
        status='UNSUPPORTED', data=None)


def forecast_inventory(value):
    return {row['race_id']: deepcopy([row.get('prediction'),
        *row.get('comparison_predictions', [])]) for row in value['records']}


@contextmanager
def legacy_feed(version, before):
    path, expected_blob = FIXTURES[version]
    raw = (ROOT / path).read_bytes()
    actual_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual_blob != expected_blob:
        raise AssertionError('PINNED_LEGACY_FUNCTION_FIXTURE_REQUIRED')
    tree = ast.parse(raw, filename=path)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if [node.name for node in functions] != ['originals_sha', 'update_view']:
        raise AssertionError('PINNED_LEGACY_FUNCTION_FIXTURE_REQUIRED')
    package = ModuleType('_synthetic_legacy_anchor_contract')
    package.__path__ = []
    official = ModuleType(package.__name__ + '.official_race_updates')
    intraday = ModuleType(package.__name__ + '.racer_intraday_source')
    official.endpoint = lambda day, venue, number, kind: 'synthetic://result'
    intraday.result_url = lambda day, venue, number: 'synthetic://result'
    feed = ModuleType(package.__name__ + '.saved_view_feed')
    feed.__package__ = package.__name__
    feed.__dict__.update(deepcopy=deepcopy, instant=instant, digest=digest, need=need,
        MUTABLE=MUTABLE, _merge=strict_merge, re=re)
    feed.parse_capture = Mock(side_effect=AssertionError('NO_CAPTURE_PARSER_EXPECTED'))
    feed.project_observation = Mock(side_effect=ValueError('RESULT_NEW_CAPTURE_UNSUPPORTED'))
    modules = {package.__name__: package, official.__name__: official,
        intraday.__name__: intraday, feed.__name__: feed}
    with patch.dict(sys.modules, modules):
        exec(compile(ast.Module(body=functions, type_ignores=[]), path, 'exec'), feed.__dict__)
        feed.ref = 'state/boat-saved-view'
        feed.collector = Mock(side_effect=AssertionError('NO_SOURCE_REQUEST_EXPECTED'))
        feed.scorer = Mock(side_effect=AssertionError('NO_MODEL_SCORE_EXPECTED'))
        feed.current_view = Mock(side_effect=AssertionError('NO_EXTRA_AES_READ_EXPECTED'))
        feed.fetch = Mock(side_effect=AssertionError('NO_EXTRA_FETCH_EXPECTED'))
        feed.transport = SimpleNamespace(commit=Mock(), push=Mock(), fetch=Mock())
        feed.ensure_calls = Mock()
        feed.publish_calls = Mock()
        feed.inventory = {'synthetic_inventory': object()}
        feed.report = {'status': 'SYNTHETIC_ENCRYPTED_VIEW_PUBLISHED'}
        feed.new_v5_day = False

        def ensure_append_only(previous, current):
            feed.ensure_calls(previous, current)
            need(previous['forecast_base_sha256'] == current['forecast_base_sha256']
                and forecast_inventory(previous) == forecast_inventory(current),
                'FEED_ORIGINAL_REMOVED_OR_CHANGED')
            return feed.inventory

        def publish_view(git, bootstrap, view, *, parent, previous, generation, history=False):
            feed.publish_calls(git, bootstrap, view, parent=parent, previous=previous,
                generation=generation, history=history)
            # Existing V5 publication compares old days before staging. A newly
            # added day has no previous descriptor and skips that comparison.
            if not feed.new_v5_day:
                feed.ensure_append_only(before, view)
            git.commit(view)
            git.push(parent)
            return feed.report

        feed.ensure_append_only = ensure_append_only
        feed.publish_view = publish_view
        yield feed


class LegacyLossControlTests(unittest.TestCase):
    def reproduce(self, version):
        guard = load_guard()
        before = view_with('rejection')
        frozen = wire(before)
        with legacy_feed(version, before) as feed:
            updated = feed.update_view(before, [new_observation()],
                synced_at=SYNC_CLOCK, captures=())
            self.assertEqual(wire(before), frozen)
            self.assertEqual(updated['records'][0]['saved_result_rejection_reason_variants'],
                before['records'][0]['saved_result_rejection_reason_variants'])
            self.assertEqual(len(updated['records'][0]['result_observation_rejections']), 1)
            self.assertEqual(updated['records'][0]['result_observation_rejections'][0]['captured_at'],
                NEW_CLOCK)
            with self.assertRaises(guard.SavedModelViewError) as raised:
                guard._observations(updated['records'], 'result_observation_rejections',
                    rejection=True)
            self.assertEqual(raised.exception.reason_code,
                'SAVED_MODEL_VIEW_RESULT_REASON_VARIANT_BINDING')
            feed.project_observation.assert_called_once()
            feed.parse_capture.assert_not_called()
            feed.transport.commit.assert_not_called()
            feed.transport.push.assert_not_called()

    def test_b9a_bfcb_6327_original_loss_is_reproduced(self):
        self.reproduce('ffb')

    def test_0da3_0796_original_loss_is_reproduced(self):
        self.reproduce('3295')


class LegacyReasonAnchorGuardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(adapter, 'legacy reason-anchor publication guard module is missing')
        self.guard = load_guard()
        self.bootstrap = {'synthetic_bootstrap': True}

    def install(self, feed, guard=None):
        self.assertIs(adapter.install_guard(feed, guard=self.guard if guard is None else guard), feed)
        return feed

    def publish(self, feed, view, **changes):
        values = dict(parent=PARENT, previous=PREVIOUS, generation=7, history=True)
        values.update(changes)
        return feed.publish_view(feed.transport, self.bootstrap, view, **values)

    def no_effects(self, feed):
        feed.transport.commit.assert_not_called()
        feed.transport.push.assert_not_called()
        feed.transport.fetch.assert_not_called()
        feed.collector.assert_not_called()
        feed.scorer.assert_not_called()
        feed.current_view.assert_not_called()
        feed.fetch.assert_not_called()

    def blocked(self, feed, action):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(ValueError) as raised:
                action()
        error = raised.exception
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')
        self.assertLessEqual(len(str(error)), 240)
        self.assertRegex(str(error), r'\A[A-Za-z0-9_: .-]{1,240}\Z')
        self.assertNotIn('private-anchor-contract', str(error))
        self.assertNotIn('private.invalid', str(error))
        self.assertIsNone(error.__cause__)
        if error.__context__ is not None:
            self.assertTrue(error.__suppress_context__)
        self.no_effects(feed)
        return str(error)

    def check_sides(self, value):
        for row in value['records']:
            for field, history, rejection in SIDES:
                if history in row:
                    self.guard._observations([row], field, rejection=rejection)

    def test_install_returns_same_feed_is_idempotent_and_changes_only_two_existing_hooks(self):
        before = view_with('observation', 'rejection')
        with legacy_feed('ffb', before) as feed:
            original = dict(feed.__dict__)
            guard_state = dict(self.guard.__dict__)
            self.install(feed)
            ensure, publish = feed.ensure_append_only, feed.publish_view
            self.assertIsNot(ensure, original['ensure_append_only'])
            self.assertIsNot(publish, original['publish_view'])
            self.install(feed)
            self.assertIs(feed.ensure_append_only, ensure)
            self.assertIs(feed.publish_view, publish)
            for name, value in original.items():
                if name not in ('ensure_append_only', 'publish_view'):
                    self.assertIs(feed.__dict__[name], value, name)
            for name, value in guard_state.items():
                self.assertIs(self.guard.__dict__[name], value, name)
            self.no_effects(feed)

    def test_healthy_sidecar_free_publish_preserves_arguments_result_and_inputs(self):
        before = view_with()
        candidate = deepcopy(before)
        frozen = wire(candidate)
        with legacy_feed('ffb', before) as feed:
            self.install(feed)
            result = feed.publish_view(git=feed.transport, bootstrap=self.bootstrap,
                view=candidate, parent=PARENT, previous=PREVIOUS, generation=7, history=True)
            self.assertIs(result, feed.report)
            feed.publish_calls.assert_called_once_with(feed.transport, self.bootstrap, candidate,
                parent=PARENT, previous=PREVIOUS, generation=7, history=True)
            feed.ensure_calls.assert_called_once_with(before, candidate)
            feed.transport.commit.assert_called_once_with(candidate)
            feed.transport.push.assert_called_once_with(PARENT)
            self.assertEqual(wire(candidate), frozen)
            feed.collector.assert_not_called()
            feed.scorer.assert_not_called()
            feed.current_view.assert_not_called()
            feed.fetch.assert_not_called()

    def test_ensure_preserves_forecast_inventory_return_identity_and_inputs(self):
        before = view_with('observation', 'rejection')
        candidate = deepcopy(before)
        frozen = wire([before, candidate])
        with legacy_feed('3295', before) as feed:
            self.install(feed)
            self.assertIs(feed.ensure_append_only(previous=before, current=candidate), feed.inventory)
            feed.ensure_calls.assert_called_once_with(before, candidate)
            self.assertEqual(wire([before, candidate]), frozen)
            self.no_effects(feed)

    def test_valid_observation_and_rejection_histories_publish_without_rewriting_evidence(self):
        before = view_with('observation', 'rejection')
        candidate = deepcopy(before)
        frozen = wire([before, candidate])
        with legacy_feed('3295', before) as feed:
            self.install(feed)
            self.assertIs(self.publish(feed, candidate), feed.report)
            self.assertEqual(wire([before, candidate]), frozen)
            feed.transport.commit.assert_called_once()
            feed.transport.push.assert_called_once()

    def reject_legacy_loss(self, version):
        before = view_with('rejection')
        frozen = wire(before)
        with legacy_feed(version, before) as feed:
            updater, parser, projector = feed.update_view, feed.parse_capture, feed.project_observation
            self.install(feed)
            self.assertIs(feed.update_view, updater)
            self.assertIs(feed.parse_capture, parser)
            self.assertIs(feed.project_observation, projector)
            updated = feed.update_view(before, [new_observation()],
                synced_at=SYNC_CLOCK, captures=())
            self.assertEqual(updated['records'][0]['result_observation_rejections'][0]['captured_at'],
                NEW_CLOCK)
            updated_wire = wire(updated)
            self.blocked(feed, lambda: self.publish(feed, updated))
            feed.publish_calls.assert_not_called()
            self.assertEqual(wire(updated), updated_wire)
            self.assertEqual(wire(before), frozen)
            projector.assert_called_once()
            parser.assert_not_called()

    def test_b9a_bfcb_6327_loss_is_blocked_without_wrapping_updater(self):
        self.reject_legacy_loss('ffb')

    def test_0da3_0796_loss_is_blocked_without_wrapping_updater(self):
        self.reject_legacy_loss('3295')

    def test_already_bad_base_holds_even_if_candidate_supplies_a_history_body_as_anchor(self):
        healthy = view_with('observation', 'rejection')
        for field, history, rejection in SIDES:
            with self.subTest(field=field):
                before, candidate = deepcopy(healthy), deepcopy(healthy)
                before['records'][0][field] = []
                frozen = wire([before, candidate])
                with legacy_feed('ffb', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))
                    self.assertEqual(wire([before, candidate]), frozen)

    def test_malformed_history_holds_on_noop_before_original_publish(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            for bad in (None, [], [dict(captured_at='2030-04-01T11:00:00+09:00')]):
                with self.subTest(kind=kind, bad_type=type(bad).__name__):
                    before = view_with(kind)
                    before['records'][0][history] = deepcopy(bad)
                    candidate = deepcopy(before)
                    frozen = wire([before, candidate])
                    with legacy_feed('ffb', before) as feed:
                        self.install(feed)
                        self.blocked(feed, lambda: self.publish(feed, candidate))
                        feed.publish_calls.assert_not_called()
                        self.assertEqual(wire([before, candidate]), frozen)

    def test_removing_both_history_and_active_anchor_fails_transition_guard(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = view_with(kind)
                candidate = deepcopy(before)
                candidate['records'][0].pop(history)
                candidate['records'][0][field] = []
                with legacy_feed('ffb', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))
                    feed.publish_calls.assert_called_once()

    def test_removing_history_alone_fails_transition_guard(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = view_with(kind)
                candidate = deepcopy(before)
                candidate['records'][0].pop(history)
                with legacy_feed('3295', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: feed.ensure_append_only(before, candidate))

    def test_changing_a_history_original_fails_even_when_new_binding_is_valid(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = view_with(kind)
                candidate = deepcopy(before)
                candidate['records'][0][history][1]['reason'] = 'RESULT_METADATA_THIRD'
                self.check_sides(candidate)
                with legacy_feed('ffb', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: feed.ensure_append_only(before, candidate))

    def test_replacing_active_anchor_with_retained_alternate_reason_fails(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = view_with(kind)
                candidate = deepcopy(before)
                candidate['records'][0][field] = [deepcopy(candidate['records'][0][history][1])]
                self.check_sides(candidate)
                with legacy_feed('3295', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: feed.ensure_append_only(before, candidate))

    def test_consistent_non_reason_body_changes_cannot_replace_originals(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = view_with(kind)
                for item in before['records'][0][field] + before['records'][0][history]:
                    item['opaque_original'] = {'value': 'private-anchor-contract-original'}
                candidate = deepcopy(before)
                for item in candidate['records'][0][field] + candidate['records'][0][history]:
                    item['opaque_original'] = {'value': 'private-anchor-contract-replacement'}
                self.check_sides(before)
                self.check_sides(candidate)
                with legacy_feed('ffb', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))

    def test_observation_and_rejection_sidecars_are_checked_independently(self):
        for field, history, rejection in SIDES:
            with self.subTest(field=field):
                before = view_with('observation', 'rejection')
                candidate = deepcopy(before)
                candidate['records'][0][field] = []
                with legacy_feed('ffb', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))
                    feed.publish_calls.assert_not_called()

    def test_new_v5_day_with_bad_sidecar_is_blocked_at_publish_entry(self):
        for field, history, rejection in SIDES:
            with self.subTest(field=field):
                before = view_with()
                candidate = view_with('observation', 'rejection')
                candidate['records'][0][field] = []
                with legacy_feed('ffb', before) as feed:
                    feed.new_v5_day = True
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))
                    feed.publish_calls.assert_not_called()
                    feed.ensure_calls.assert_not_called()

    def test_valid_new_v5_day_does_not_require_a_previous_day_descriptor(self):
        before = view_with()
        candidate = view_with('observation', 'rejection')
        frozen = wire(candidate)
        with legacy_feed('ffb', before) as feed:
            feed.new_v5_day = True
            self.install(feed)
            self.assertIs(self.publish(feed, candidate), feed.report)
            feed.ensure_calls.assert_not_called()
            feed.transport.commit.assert_called_once()
            feed.transport.push.assert_called_once()
            self.assertEqual(wire(candidate), frozen)

    def test_valid_additive_history_and_later_active_captures_preserve_prior_originals(self):
        before = view_with('observation', 'rejection')
        candidate = deepcopy(before)
        for field, history, rejection in SIDES:
            row = candidate['records'][0]
            row[history].append(dict(row[history][0], reason='RESULT_METADATA_THIRD'))
            newest = dict(row[field][0], captured_at=NEW_CLOCK, source_sha256='e' * 64)
            row[field].append(newest)
        self.check_sides(candidate)
        frozen = wire(candidate)
        with legacy_feed('3295', before) as feed:
            self.install(feed)
            self.assertIs(self.publish(feed, candidate), feed.report)
            self.assertEqual(wire(candidate), frozen)

    def two_rows(self, kind):
        before = view_with(kind)
        before['records'].append(deepcopy(before['records'][0]))
        for index, row in enumerate(before['records']):
            row['race_id'] = '20300401-01-0' + str(index + 1)
            for field, history, rejection in SIDES:
                for item in row[field] + row.get(history, []):
                    item['opaque_original'] = 'synthetic-row-' + str(index)
                    if not rejection:
                        item['race_id'] = row['race_id']
        return before

    def test_reordering_rows_does_not_replace_their_originals(self):
        before = self.two_rows('rejection')
        candidate = deepcopy(before)
        candidate['records'].reverse()
        with legacy_feed('ffb', before) as feed:
            self.install(feed)
            self.assertIs(self.publish(feed, candidate), feed.report)

    def test_matching_capture_and_source_cannot_move_originals_between_races(self):
        for kind, field, history, rejection in (
                ('observation', *SIDES[0]), ('rejection', *SIDES[1])):
            with self.subTest(kind=kind):
                before = self.two_rows(kind)
                candidate = deepcopy(before)
                left, right = candidate['records']
                left[field], right[field] = right[field], left[field]
                left[history], right[history] = right[history], left[history]
                if not rejection:
                    for row in candidate['records']:
                        for item in row[field] + row[history]:
                            item['race_id'] = row['race_id']
                self.check_sides(candidate)
                with legacy_feed('3295', before) as feed:
                    self.install(feed)
                    self.blocked(feed, lambda: self.publish(feed, candidate))

    def test_guard_exception_payloads_are_sanitized_without_printing_or_visible_chaining(self):
        messages = []
        for secret in ('private-anchor-contract-first', 'private-anchor-contract-second'):
            before = view_with('rejection')
            with legacy_feed('ffb', before) as feed:
                self.install(feed)
                with patch.object(self.guard, '_observations',
                        side_effect=ValueError(secret + ' https://private.invalid/body')):
                    messages.append(self.blocked(feed, lambda: self.publish(feed, deepcopy(before))))
                feed.publish_calls.assert_not_called()
        self.assertEqual(messages[0], messages[1])

    def test_existing_forecast_failure_is_preserved_and_never_reaches_commit(self):
        before = view_with('observation', 'rejection')
        candidate = deepcopy(before)
        candidate['records'][0]['prediction']['model_id'] = 'SYNTHETIC_CHANGED_MODEL'
        with legacy_feed('ffb', before) as feed:
            self.install(feed)
            with self.assertRaisesRegex(ValueError, r'\AFEED_ORIGINAL_REMOVED_OR_CHANGED\Z'):
                self.publish(feed, candidate)
            self.no_effects(feed)


if __name__ == '__main__':
    unittest.main()
