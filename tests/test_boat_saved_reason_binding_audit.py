"""Synthetic, read-only AES-base reason-sidecar counts against the pinned guard."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from scripts import boat_saved_reason_binding_audit as A


ROOT = Path(__file__).resolve().parents[1]
GUARD_BLOB = 'e6db8d720aa151940e01f377831a5884eb4b2ba9'
SCHEMA = 'RACE_AI_SAVED_REASON_BINDING_COUNTS_V1'
CLEAR = 'NO_BINDING_INCONSISTENCY_IN_THIS_VIEW'
FOUND = 'BINDING_INCONSISTENCY_FOUND'
BINDING = 'SAVED_MODEL_VIEW_RESULT_REASON_VARIANT_BINDING'
CLOCK = '2030-04-01T11:00:00+09:00'
EQUIVALENT_CLOCK = '2030-04-01T02:00:00Z'
RACE_ID = '20300401-01-01'
SOURCE = 'f' * 64
FIELDS = {
    'observation': ('result_observations', 'saved_result_observation_reason_variants'),
    'rejection': ('result_observation_rejections', 'saved_result_rejection_reason_variants'),
}
COUNTERS = (
    'active_count', 'history_count', 'missing_active_anchor',
    'invalid_active_reason_metadata', 'invalid_history_reason_metadata',
    'source_sha_absent_active', 'source_sha_absent_history', 'source_sha_different',
    'non_reason_body_mismatch', 'clock_text_mismatch',
    'compared_active_history_pairs', 'other_guard_failures',
)
EFFECTS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    publication_performed=False, forecast_generated=False, broader_goals_proven=False)


def load_guard():
    path = ROOT / 'reason-binding-source/race_ai/boat_saved_model_view.py'
    raw = path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual != GUARD_BLOB:
        raise AssertionError('PINNED_OWNER_SOURCE_GUARD_REQUIRED')
    spec = importlib.util.spec_from_file_location('race_ai._saved_reason_binding_audit_guard', path)
    if spec is None or spec.loader is None:
        raise AssertionError('PINNED_OWNER_SOURCE_GUARD_REQUIRED')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def side_counts(**changes):
    output = {key: 0 for key in COUNTERS}
    output.update(changes)
    return output


def empty_view():
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', dataset_status='SYNTHETIC_ONLY',
        event_date_jst='2030-04-01', records=[])


def fixture(*kinds):
    output = empty_view()
    row = dict(race_id=RACE_ID, result_observations=[], result_observation_rejections=[])
    for kind in kinds:
        field, history = FIELDS[kind]
        first = dict(captured_at=CLOCK, source_sha256=SOURCE, reason='RESULT_METADATA_FIRST')
        if kind == 'observation':
            first.update(race_id=RACE_ID, closed_at='2030-04-01T10:00:00+09:00',
                         status='PENDING', data=None)
        second = dict(first, reason='RESULT_METADATA_SECOND')
        row[field] = [deepcopy(first)]
        row[history] = [deepcopy(first), deepcopy(second)]
    output['records'] = [row]
    return output


class SavedReasonBindingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_guard()

    def diagnose(self, value, *, origin='AES_BASE'):
        before = deepcopy(value)
        original_wire = wire(value)
        report = A.diagnose_view(value, guard=self.guard, origin=origin)
        self.assertEqual(value, before)
        self.assertEqual(wire(value), original_wire)
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], SCHEMA)
        self.assertEqual(report['origin'], 'AES_BASE')
        self.assertIn(report['status'], (CLEAR, FOUND, 'HOLD'))
        self.assertEqual({key: report[key] for key in EFFECTS}, EFFECTS)
        self.assertIs(report['originals_changed'], False)
        self.assertIs(type(report['observations_reconciled']), int)
        self.assertIs(type(report['source_requests']), int)
        for flag in ('publication_performed', 'forecast_generated', 'broader_goals_proven'):
            self.assertIs(report[flag], False)
        expected_keys = {'schema', 'origin', 'status', 'counts', *EFFECTS}
        if report['status'] == 'HOLD':
            expected_keys.add('reason')
            self.assertEqual(report['reason'], 'INPUT_OR_GUARD_INVALID')
            self.assertIsNone(report['counts'])
        else:
            self.assertEqual(set(report['counts']), {'observation', 'rejection'})
            for counts in report['counts'].values():
                self.assertEqual(set(counts), set(COUNTERS))
                for count in counts.values():
                    self.assertIs(type(count), int)
                    self.assertGreaterEqual(count, 0)
                self.assertEqual(counts['other_guard_failures'], 0)
        self.assertEqual(set(report), expected_keys)
        self.assertEqual(json.loads(wire(report)), report)
        return report

    def assert_guard_binding(self, value, kind):
        field, _ = FIELDS[kind]
        row = value['records'][0]
        before = deepcopy(row)
        with self.assertRaises(self.guard.SavedModelViewError) as caught:
            self.guard._observations([row], field, rejection=kind == 'rejection')
        self.assertEqual(caught.exception.reason_code, BINDING)
        self.assertEqual(row, before)

    def assert_side(self, report, kind, **changes):
        self.assertEqual(report['counts'][kind], side_counts(**changes))
        other = 'rejection' if kind == 'observation' else 'observation'
        self.assertEqual(report['counts'][other], side_counts())

    def test_valid_histories_count_observations_and_rejections_independently(self):
        value = fixture('observation', 'rejection')
        before = deepcopy(value)
        for kind, (field, _) in FIELDS.items():
            active, history = self.guard._observations([value['records'][0]], field,
                                                       rejection=kind == 'rejection')
            self.assertEqual(len(active), 1)
            self.assertEqual(len(history), 2)
        report = self.diagnose(value)
        self.assertEqual(report['status'], CLEAR)
        expected = side_counts(active_count=1, history_count=2, compared_active_history_pairs=2)
        self.assertEqual(report['counts'], dict(observation=expected, rejection=expected))
        self.assertEqual(value, before)

    def test_no_sidecar_and_empty_view_do_not_invent_inconsistencies(self):
        report = self.diagnose(empty_view())
        self.assertEqual(report['status'], CLEAR)
        self.assertEqual(report['counts'], dict(observation=side_counts(), rejection=side_counts()))
        value = fixture('observation')
        value['records'][0].pop(FIELDS['observation'][1])
        report = self.diagnose(value)
        self.assertEqual(report['status'], CLEAR)
        self.assert_side(report, 'observation', active_count=1)

    def test_missing_active_anchors_are_findings_without_reconstructing_originals(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                value = fixture(kind)
                value['records'][0][FIELDS[kind][0]] = []
                self.assert_guard_binding(value, kind)
                report = self.diagnose(value)
                self.assertEqual(report['status'], FOUND)
                self.assert_side(report, kind, history_count=2, missing_active_anchor=2)
                self.assert_guard_binding(value, kind)

    def test_source_mismatch_respects_each_guards_identity_without_guessing_a_body(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                value = fixture(kind)
                value['records'][0][FIELDS[kind][1]][1]['source_sha256'] = 'e' * 64
                self.assert_guard_binding(value, kind)
                report = self.diagnose(value)
                self.assertEqual(report['status'], FOUND)
                if kind == 'observation':
                    self.assert_side(report, kind, active_count=1, history_count=2,
                        source_sha_different=1, non_reason_body_mismatch=1,
                        compared_active_history_pairs=2)
                else:
                    self.assert_side(report, kind, active_count=1, history_count=2,
                        source_sha_different=1, missing_active_anchor=1,
                        compared_active_history_pairs=1)
                self.assert_guard_binding(value, kind)

    def test_missing_source_hashes_are_counted_without_inventing_source_values(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                value = fixture(kind)
                row = value['records'][0]
                field, history = FIELDS[kind]
                for item in [*row[field], *row[history]]:
                    item.pop('source_sha256')
                self.assert_guard_binding(value, kind)
                report = self.diagnose(value)
                self.assertEqual(report['status'], FOUND)
                self.assert_side(report, kind, active_count=1, history_count=2,
                    source_sha_absent_active=1, source_sha_absent_history=2,
                    compared_active_history_pairs=2)

    def test_unknown_non_reason_fields_remain_exact_and_never_become_output_names(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                value = fixture(kind)
                value['records'][0][FIELDS[kind][1]][1]['private-sentinel-unknown-name'] = {
                    'private-sentinel-inner': 'private-sentinel-body'}
                self.assert_guard_binding(value, kind)
                report = self.diagnose(value)
                self.assertEqual(report['status'], FOUND)
                self.assert_side(report, kind, active_count=1, history_count=2,
                    non_reason_body_mismatch=1, compared_active_history_pairs=2)
                self.assertNotIn('sentinel', wire(report))
                self.assert_guard_binding(value, kind)

    def test_invalid_active_and_history_reason_metadata_are_counted_separately(self):
        for kind in FIELDS:
            for target in ('active', 'history'):
                with self.subTest(kind=kind, target=target):
                    value = fixture(kind)
                    row = value['records'][0]
                    field, history = FIELDS[kind]
                    if target == 'active':
                        row[field][0]['reason'] = None if kind == 'rejection' else 'private-sentinel-lower'
                    else:
                        row[history][1]['reason'] = None if kind == 'rejection' else 'private-sentinel-lower'
                    self.assert_guard_binding(value, kind)
                    report = self.diagnose(value)
                    self.assertEqual(report['status'], FOUND)
                    changes = dict(active_count=1, history_count=2, compared_active_history_pairs=2)
                    changes['invalid_' + target + '_reason_metadata'] = 1
                    self.assert_side(report, kind, **changes)
                    self.assertNotIn('sentinel', wire(report))
                    self.assert_guard_binding(value, kind)

    def test_equivalent_instants_keep_their_exact_clock_text_binding(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                value = fixture(kind)
                value['records'][0][FIELDS[kind][1]][1]['captured_at'] = EQUIVALENT_CLOCK
                self.assertEqual(self.guard._clock(CLOCK), self.guard._clock(EQUIVALENT_CLOCK))
                self.assert_guard_binding(value, kind)
                report = self.diagnose(value)
                self.assertEqual(report['status'], FOUND)
                self.assert_side(report, kind, active_count=1, history_count=2,
                    clock_text_mismatch=1, non_reason_body_mismatch=1,
                    compared_active_history_pairs=2)
                self.assert_guard_binding(value, kind)

    def test_other_guard_failures_hold_the_whole_report_with_null_counts(self):
        for change in ('single_history', 'duplicate_history', 'invalid_clock', 'invalid_active_list'):
            value = fixture('observation')
            row = value['records'][0]
            field, history = FIELDS['observation']
            if change == 'single_history':
                row[history] = row[history][:1]
            elif change == 'duplicate_history':
                row[history][1] = deepcopy(row[history][0])
            elif change == 'invalid_clock':
                row[history][1]['captured_at'] = 'private-sentinel-invalid-clock'
            else:
                row[field] = {'private-sentinel-not-list': True}
            with self.subTest(change=change):
                report = self.diagnose(value)
                self.assertEqual(report['status'], 'HOLD')
                self.assertIsNone(report['counts'])
                self.assertNotIn('sentinel', wire(report))
        # A later structural failure must invalidate earlier partial findings.
        value = fixture('observation', 'rejection')
        row = value['records'][0]
        row[FIELDS['observation'][0]] = []
        row[FIELDS['rejection'][1]][1] = deepcopy(row[FIELDS['rejection'][1]][0])
        report = self.diagnose(value)
        self.assertEqual(report['status'], 'HOLD')
        self.assertIsNone(report['counts'])

    def test_invalid_view_shapes_and_unapproved_origins_hold_without_echoing_input(self):
        for value in (None, [], {}, dict(schema='private-sentinel', records=[]),
                      dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', records=None),
                      dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', records=[None])):
            with self.subTest(value_type=type(value).__name__):
                report = self.diagnose(value)
                self.assertEqual(report['status'], 'HOLD')
                self.assertIsNone(report['counts'])
                self.assertNotIn('sentinel', wire(report))
        for origin in ('private-sentinel-origin', 'ADDITION', '', None, 1, True):
            with self.subTest(origin_type=type(origin).__name__):
                report = self.diagnose(fixture('observation'), origin=origin)
                self.assertEqual(report['status'], 'HOLD')
                self.assertEqual(report['origin'], 'AES_BASE')
                self.assertIsNone(report['counts'])
                self.assertNotIn('sentinel', wire(report))

    def test_serialization_roundtrip_keeps_results_and_inputs_byte_equivalent(self):
        for kind in FIELDS:
            for invalid in (False, True):
                with self.subTest(kind=kind, invalid=invalid):
                    original = fixture(kind)
                    if invalid:
                        original['records'][0][FIELDS[kind][1]][1]['unknown'] = {'value': [1, True, None]}
                    decoded = json.loads(wire(original))
                    before = wire(decoded)
                    first = self.diagnose(original)
                    second = self.diagnose(decoded)
                    self.assertEqual(second, first)
                    self.assertEqual(wire(decoded), before)
                    self.assertEqual(json.loads(wire(second)), second)

    def test_reports_only_fixed_metadata_counts_and_false_broader_goal_flags(self):
        value = fixture('observation', 'rejection')
        row = value['records'][0]
        row['private-sentinel-row-name'] = 'private-sentinel-row-body'
        value['private-sentinel-top-name'] = 'private-sentinel-top-body'
        for kind in FIELDS:
            field, history = FIELDS[kind]
            for item in [*row[field], *row[history]]:
                item['source_url'] = 'https://private-sentinel.invalid/protected'
                item['private-sentinel-unknown-name'] = {'private-sentinel-key': 'private-sentinel-secret'}
        report = self.diagnose(value)
        self.assertEqual(report['status'], CLEAR)
        serialized = wire(report)
        for forbidden in ('sentinel', RACE_ID, CLOCK, EQUIVALENT_CLOCK, SOURCE,
                          'https:', 'RESULT_METADATA_FIRST', 'RESULT_METADATA_SECOND'):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual({key: report[key] for key in EFFECTS}, EFFECTS)
        self.assertEqual(report['counts']['observation'],
            side_counts(active_count=1, history_count=2, compared_active_history_pairs=2))
        self.assertEqual(report['counts']['rejection'],
            side_counts(active_count=1, history_count=2, compared_active_history_pairs=2))


if __name__ == '__main__':
    unittest.main()
