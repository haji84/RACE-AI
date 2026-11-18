"""Synthetic receipt-bound restoration candidates; no keys, I/O, repair or publication."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
from hashlib import sha256
import importlib
import inspect
import io
import json
import unittest
from unittest.mock import patch

from tests import test_boat_saved_rejection_anchor_proof as F

# Keep the exact receipt class used by the frozen proof fixtures. The pure
# candidate receives this module; it must not reload another proof namespace.
A = F.A
try:
    restoration = importlib.import_module('scripts.boat_rejection_anchor_restoration')
except ModuleNotFoundError as error:
    if error.name != 'scripts.boat_rejection_anchor_restoration':
        raise
    restoration = None


class RejectionAnchorRestorationTests(unittest.TestCase):
    SCHEMA = 'RACE_AI_REJECTION_ANCHOR_RESTORATION_V1'
    COUNTS = ('snapshots_checked', 'orphan_groups', 'current_active_rejections',
              'candidate_active_rejections', 'retained_history_originals',
              'restored_active_originals', 'rows_changed')
    EFFECTS = dict(originals_changed=False, observations_reconciled=0,
        source_requests=0, publication_performed=False, forecast_generated=False,
        broader_goals_proven=False)

    def setUp(self):
        self.assertIsNotNone(restoration, 'pure rejection-anchor restoration module is missing')
        self.guard = F.load_guard()

    def receipt_bytes(self, case):
        return [(F.wire(item._view), F.wire(item._header), item._ciphertext,
                 item._snapshot_sha, item._cipher_sha256, item._binding_sha256)
                for item in (case['current'], *case['older'])]

    def safe_summary(self, report):
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], self.SCHEMA)
        self.assertIn(report['status'], ('READY', 'NO_CHANGE', 'HOLD'))
        expected={'schema', 'status', 'counts', 'current_view_sha256',
                  'candidate_view_sha256', *self.EFFECTS}
        for key, value in self.EFFECTS.items():
            self.assertIs(type(report[key]), type(value))
            self.assertEqual(report[key], value)
        if report['status']=='HOLD':
            expected.add('reason')
            self.assertRegex(report['reason'], r'^[A-Z][A-Z0-9_]{0,79}$')
            self.assertIsNone(report['counts'])
            self.assertIsNone(report['current_view_sha256'])
            self.assertIsNone(report['candidate_view_sha256'])
        else:
            self.assertEqual(set(report['counts']), set(self.COUNTS))
            for value in report['counts'].values():
                self.assertIs(type(value), int)
                self.assertGreaterEqual(value, 0)
            self.assertRegex(report['current_view_sha256'], r'^[a-f0-9]{64}$')
            if report['status']=='READY':
                self.assertRegex(report['candidate_view_sha256'], r'^[a-f0-9]{64}$')
            else:
                self.assertIsNone(report['candidate_view_sha256'])
        self.assertEqual(set(report), expected)
        public=json.dumps(report, sort_keys=True, allow_nan=False)
        for forbidden in ('sentinel', F.RID, '2030-04-01T', 'RESULT_METADATA_FIRST',
                          'RESULT_METADATA_SECOND', 'source_sha256', 'prediction',
                          'result_observations', 'private_url', 'owner_key', 'Traceback'):
            self.assertNotIn(forbidden, public)

    def build(self, case, *, guard=None, current=None, older=None, proof=A):
        before=self.receipt_bytes(case)
        output, errors=io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            candidate, report=restoration.build_rejection_anchor_restoration(
                case['current'] if current is None else current,
                case['older'] if older is None else older,
                guard=self.guard if guard is None else guard, proof=proof)
        self.assertEqual(output.getvalue()+errors.getvalue(), '')
        self.assertEqual(self.receipt_bytes(case), before)
        self.safe_summary(report)
        return candidate, report

    def assert_hold(self, case, reason, **options):
        candidate, report=self.build(case, **options)
        self.assertIsNone(candidate)
        self.assertEqual(report['status'], 'HOLD')
        self.assertEqual(report['reason'], reason)
        return report

    def assert_original_rejected(self, case):
        for row in case['current']._view['records']:
            if row.get(F.HISTORY):
                with self.assertRaises(self.guard.SavedModelViewError) as caught:
                    self.guard._observations([row], F.ACTIVE, rejection=True)
                self.assertEqual(caught.exception.reason_code, F.BINDING)

    def validate_rows(self, view):
        for row in view['records']:
            self.guard._observations([row], 'result_observations')
            self.guard._observations([row], F.ACTIVE, rejection=True)

    def test_full_proof_appends_exact_older_active_bodies_and_preserves_every_other_byte(self):
        current, older=F.views()
        current['private-sentinel-top-level']={'clock':'2030-04-01T00:00:00Z'}
        untouched=deepcopy(current['records'][0])
        untouched.update(race_id='20300401-01-02', race_no=2,
                         result_observations=[])
        untouched[F.ACTIVE]=[]; untouched.pop(F.HISTORY, None)
        current['records'].append(untouched)
        case=F.chain(current, [older])
        original=deepcopy(current); expected=deepcopy(current)
        expected['records'][0][F.ACTIVE].extend(deepcopy(older['records'][0][F.ACTIVE]))
        self.assert_original_rejected(case)
        matcher=A.match_rejection_anchor_proofs
        with patch.object(A, 'match_rejection_anchor_proofs', wraps=matcher) as matched:
            candidate, report=self.build(case)
        matched.assert_called_once_with(case['current'], case['older'], guard=self.guard)
        self.assertEqual(report['status'], 'READY')
        self.assertIsNotNone(candidate)
        self.assertNotIsInstance(candidate, A.VerifiedSnapshot)
        private=candidate._copy_view()
        self.assertEqual(F.wire(private), F.wire(expected))
        self.assertEqual(F.wire(current), F.wire(original))
        self.validate_rows(private)
        self.assert_original_rejected(case)
        self.assertEqual(report['counts'], dict(snapshots_checked=2, orphan_groups=2,
            current_active_rejections=1, candidate_active_rejections=3,
            retained_history_originals=4, restored_active_originals=2, rows_changed=1))
        self.assertEqual(report['current_view_sha256'], sha256(F.wire(current).encode()).hexdigest())
        self.assertEqual(report['candidate_view_sha256'], sha256(F.wire(expected).encode()).hexdigest())
        self.assertEqual(private['records'][0]['result']['status'], 'unsupported')
        self.assertEqual(private['records'][0]['result_observations'][0]['status'], 'PENDING')

    def test_complete_older_chain_restores_each_race_without_cross_race_authority(self):
        current, older=F.views()
        second=deepcopy(current['records'][0]); second.update(race_id='20300401-01-02', race_no=2)
        second['result_observations'][0]['race_id']=second['race_id']
        current['records'].append(second)
        near=deepcopy(current); deeper=deepcopy(current)
        for row in near['records']+deeper['records']:row[F.ACTIVE]=[]
        near['records'][0][F.ACTIVE]=deepcopy(older['records'][0][F.ACTIVE])
        deeper['records'][1][F.ACTIVE]=deepcopy(older['records'][0][F.ACTIVE])
        case=F.chain(current, [near, deeper])
        candidate, report=self.build(case)
        self.assertEqual(report['status'], 'READY')
        expected=deepcopy(current)
        for row in expected['records']:row[F.ACTIVE].extend(deepcopy(older['records'][0][F.ACTIVE]))
        self.assertEqual(F.wire(candidate._copy_view()), F.wire(expected))
        self.validate_rows(candidate._copy_view())
        self.assert_original_rejected(case)
        self.assertEqual(report['counts'], dict(snapshots_checked=3, orphan_groups=4,
            current_active_rejections=2, candidate_active_rejections=6,
            retained_history_originals=8, restored_active_originals=4, rows_changed=2))

    def test_missing_partial_sidecar_only_or_wrong_race_proof_never_yields_partial_candidate(self):
        for mode in ('missing_one', 'sidecars_only', 'other_race'):
            with self.subTest(mode=mode):
                current, older=F.views()
                if mode=='missing_one':older['records'][0][F.ACTIVE]=older['records'][0][F.ACTIVE][:1]
                elif mode=='sidecars_only':older['records'][0][F.ACTIVE]=[]
                else:older['records'][0]['race_id']='20300401-01-02'
                case=F.chain(current, [older])
                self.assert_hold(case, 'ACTIVE_PROOF_MISSING')
                self.assert_original_rejected(case)

    def test_conflicts_unknown_body_changes_and_clock_text_are_not_repaired_or_normalized(self):
        for mode in ('older_conflict', 'deeper_conflict', 'current_body', 'clock_text'):
            with self.subTest(mode=mode):
                current, older=F.views(); previous=[older]
                expected='ACTIVE_PROOF_CONFLICT'
                if mode=='older_conflict':
                    older['records'][0][F.ACTIVE][0]['private-sentinel-extra']=True
                elif mode=='deeper_conflict':
                    deeper=deepcopy(older)
                    deeper['records'][0][F.ACTIVE][0]=deepcopy(current['records'][0][F.HISTORY][0])
                    previous.append(deeper)
                elif mode=='current_body':
                    current['records'][0][F.HISTORY][1]['private-sentinel-extra']=True
                    expected='CURRENT_HISTORY_INVALID'
                else:
                    current['records'][0][F.HISTORY][1]['captured_at']='2030-04-01T02:00:00Z'
                    expected='CURRENT_HISTORY_INVALID'
                self.assert_hold(F.chain(current, previous), expected)

    def test_recomputes_receipt_proof_and_never_accepts_cached_decision_or_authentication_flags(self):
        current, older=F.views(); case=F.chain(current, [older])
        cached=A.match_rejection_anchor_proofs(case['current'], case['older'], guard=self.guard)
        self.assertEqual(cached.public_summary()['status'], 'ALL_ORPHAN_ANCHORS_PROVEN')
        for target in ('current_body', 'older_body', 'older_header', 'older_cipher'):
            with self.subTest(target=target):
                case=F.chain(current, [older])
                A.match_rejection_anchor_proofs(case['current'], case['older'], guard=self.guard)
                if target=='current_body':case['current']._view['private-sentinel-tamper']=True
                elif target=='older_body':case['older'][0]._view['private-sentinel-tamper']=True
                elif target=='older_header':case['older'][0]._header['generation']+=1
                else:object.__setattr__(case['older'][0], '_ciphertext',
                                       case['older'][0]._ciphertext+b'private-sentinel-tamper')
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID')
        case=F.chain(current, [older])
        for fake in (cached, True, {'authenticated':True, 'plan':cached._plan}):
            with self.subTest(fake=type(fake).__name__):
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID', current=fake)
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID', proof=fake)
        parameters=inspect.signature(restoration.build_rejection_anchor_restoration).parameters
        self.assertEqual(tuple(parameters), ('current', 'older_chain', 'guard', 'proof'))
        self.assertIs(parameters['guard'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameters['proof'].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_candidate_must_pass_unchanged_observation_and_rejection_guard_on_every_row(self):
        real=self.guard
        for mode in ('observations', 'rejections', 'unrelated_row'):
            with self.subTest(mode=mode):
                current, older=F.views()
                if mode=='unrelated_row':
                    row=deepcopy(current['records'][0])
                    row.update(race_id='20300401-01-02', race_no=2, result_observations=[])
                    row[F.ACTIVE]=[]; row.pop(F.HISTORY, None); current['records'].append(row)
                class RejectingGuard:
                    def __getattr__(self, name):return getattr(real, name)
                    def _observations(self, rows, field, *, rejection=False):
                        # Keep all unchanged native checks before injecting the
                        # final candidate-validation failure.
                        result=real._observations(rows, field, rejection=rejection)
                        fail=(mode=='observations' and field=='result_observations' or
                              mode=='rejections' and field==F.ACTIVE and len(rows[0][F.ACTIVE])==3 or
                              mode=='unrelated_row' and field=='result_observations' and
                              rows[0]['race_id']=='20300401-01-02')
                        if fail:raise RuntimeError('private-sentinel-guard https://private.invalid/')
                        return result
                case=F.chain(current, [older])
                self.assert_hold(case, 'CANDIDATE_GUARD_REJECTED', guard=RejectingGuard())
                self.assert_original_rejected(case)

    def test_healthy_and_empty_views_return_no_change_and_no_candidate(self):
        current, older=F.views()
        current['records'][0][F.ACTIVE].extend(deepcopy(older['records'][0][F.ACTIVE]))
        empty=dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', records=[])
        for name, view, active, history in (('healthy', current, 3, 4), ('empty', empty, 0, 0)):
            with self.subTest(view=name):
                case=F.chain(view, [])
                candidate, report=self.build(case)
                self.assertIsNone(candidate)
                self.assertEqual(report['status'], 'NO_CHANGE')
                self.validate_rows(view)
                self.assertEqual(report['counts'], dict(snapshots_checked=1, orphan_groups=0,
                    current_active_rejections=active, candidate_active_rejections=active,
                    retained_history_originals=history, restored_active_originals=0, rows_changed=0))
                self.assertEqual(report['current_view_sha256'], sha256(F.wire(view).encode()).hexdigest())

    def test_candidate_is_opaque_non_serializable_and_each_private_copy_is_detached(self):
        current, older=F.views(); case=F.chain(current, [older])
        candidate, report=self.build(case)
        self.assertEqual(report['status'], 'READY')
        for value in (candidate, (candidate, report)):
            with self.assertRaises(TypeError):json.dumps(value)
        for forbidden in ('sentinel', F.RID, '2030-04-01T', 'RESULT_METADATA_FIRST',
                          'RESULT_METADATA_SECOND', 'prediction', 'source_sha256'):
            self.assertNotIn(forbidden, repr(candidate))
        first=candidate._copy_view(); second=candidate._copy_view()
        expected=F.wire(second)
        self.assertIsNot(first, second)
        self.assertIsNot(first['records'][0], second['records'][0])
        first['records'][0][F.ACTIVE][-1]['reason']='private-sentinel-mutated-copy'
        report['counts']['restored_active_originals']=999
        self.assertEqual(F.wire(candidate._copy_view()), expected)
        self.assertEqual(F.wire(second), expected)
        self.assert_original_rejected(case)


if __name__ == '__main__':
    unittest.main()
