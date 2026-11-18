"""Synthetic linked reader receipts; no key, decryption, repair or publication."""
from copy import deepcopy
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts import boat_saved_rejection_anchor_audit as A
from tests.test_boat_saved_reason_binding_audit import load_guard


SCHEMA = 'RACE_AI_SAVED_REJECTION_ANCHOR_PROOF_V1'
READY = 'ALL_ORPHAN_ANCHORS_PROVEN'
UNCHANGED = 'NO_ORPHAN_ANCHORS'
BINDING = 'SAVED_MODEL_VIEW_RESULT_REASON_VARIANT_BINDING'
RID = '20300401-01-01'
HISTORY = 'saved_result_rejection_reason_variants'
ACTIVE = 'result_observation_rejections'
COUNT_FIELDS = (
    'snapshots_checked', 'current_active_rejections', 'retained_history_originals',
    'orphan_groups', 'proved_groups', 'older_active_bodies_checked', 'planned_active_originals',
)
EFFECTS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    publication_performed=False, forecast_generated=False, broader_goals_proven=False)
HOLD_REASONS = {
    'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED', 'CURRENT_HISTORY_INVALID',
    'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING',
}


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def original(hour, source, reason):
    return dict(captured_at='2030-04-01T%02d:00:00+09:00' % hour,
        source_sha256=source * 64, reason=reason,
        **{'private-sentinel-unknown-field': {'exact': ['private-sentinel-original', True, None]}})


def views():
    first = original(11, 'a', 'RESULT_METADATA_FIRST')
    first_other = dict(first, reason='RESULT_METADATA_SECOND')
    second = original(12, 'b', 'RESULT_METADATA_FIRST')
    second_other = dict(second, reason='RESULT_METADATA_SECOND')
    live = original(13, 'c', 'RESULT_CURRENT_CAPTURE')
    row = dict(race_id=RID, sport='boat', event_date_jst='2030-04-01', race_no=1,
        prediction={'private-sentinel-forecast': [1, 2, 3]},
        comparison_predictions=[{'private-sentinel-comparison': 'unchanged'}],
        result=dict(status='unsupported', **{'private-sentinel-result': 'unchanged'}),
        result_observations=[dict(race_id=RID, captured_at='2030-04-01T13:00:00+09:00',
            closed_at='2030-04-01T10:00:00+09:00', source_sha256='c'*64,
            status='PENDING', data=None)],
        result_observation_rejections=[deepcopy(live)],
        saved_result_rejection_reason_variants=[
            deepcopy(first), deepcopy(first_other), deepcopy(second), deepcopy(second_other)])
    current = dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', dataset_status='SYNTHETIC_ONLY',
                   event_date_jst='2030-04-01', records=[row])
    older = deepcopy(current)
    # The authoritative first body is intentionally not the first sidecar body.
    older['records'][0][ACTIVE] = [deepcopy(first_other), deepcopy(second)]
    return current, older


def mint(view, *, generation, previous, tag, view_id='d'*64):
    header = dict(schema='RACE_AI_SAVED_WEB_VIEW_V4', source_content_sha256='e'*64,
        view_id=view_id, forecast_sha256='f'*64, forecast_inventory_sha256='9'*64,
        generation=generation, previous_cipher_sha256=previous)
    # Factory fixtures bind bytes and metadata only. This synthetic envelope is
    # deliberately not an AEAD authentication claim; the real reader owns that.
    raw = (wire(dict(header=header, nonce=base64.b64encode(b'n'*12).decode(),
        ciphertext=base64.b64encode(('synthetic-reader-fixture-' + tag).encode()).decode())) + '\n').encode()
    cipher_sha = hashlib.sha256(raw).hexdigest()
    snapshot_sha = hashlib.sha1(('synthetic-snapshot-' + tag).encode()).hexdigest()
    source_view, source_header = deepcopy(view), deepcopy(header)
    receipt = A._verified_snapshot(source_view, header=source_header,
        manifest_cipher_sha256=cipher_sha, snapshot_sha=snapshot_sha, ciphertext=raw)
    return dict(receipt=receipt, hashes=dict(snapshot_sha=snapshot_sha, cipher_sha256=cipher_sha),
                source_view=source_view, source_header=source_header, raw=raw, header=header)


def chain(current, older):
    documents = [current, *older]
    items = [None] * len(documents)
    previous = '0' * 64
    for index in range(len(documents) - 1, -1, -1):
        item = mint(documents[index], generation=424-index, previous=previous,
                    tag='chain-%d' % index)
        items[index] = item
        previous = item['hashes']['cipher_sha256']
    return dict(current=items[0]['receipt'], older=tuple(item['receipt'] for item in items[1:]),
                items=items, hashes=[item['hashes'] for item in items])


class RejectionAnchorProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_guard()

    def match(self, case, *, current=None, older=None):
        receipts = [case['current'], *case['older']]
        before = [(wire(item._view), wire(item._header)) for item in receipts]
        inputs = [(wire(item['source_view']), wire(item['source_header'])) for item in case['items']]
        decision = A.match_rejection_anchor_proofs(
            case['current'] if current is None else current,
            case['older'] if older is None else older, guard=self.guard)
        self.assertEqual([(wire(item._view), wire(item._header)) for item in receipts], before)
        self.assertEqual([(wire(item['source_view']), wire(item['source_header']))
                          for item in case['items']], inputs)
        summary = decision.public_summary()
        self.assertIs(type(summary), dict)
        self.assertEqual(summary['schema'], SCHEMA)
        self.assertIn(summary['status'], (READY, UNCHANGED, 'HOLD'))
        self.assertEqual({key: summary[key] for key in EFFECTS}, EFFECTS)
        for key in ('originals_changed', 'publication_performed', 'forecast_generated', 'broader_goals_proven'):
            self.assertIs(summary[key], False)
        for key in ('observations_reconciled', 'source_requests'):
            self.assertIs(type(summary[key]), int)
        expected = {'schema', 'status', 'counts', 'snapshots', *EFFECTS}
        if summary['status'] == 'HOLD':
            expected.add('reason')
            self.assertIn(summary['reason'], HOLD_REASONS)
            self.assertIsNone(summary['counts'])
            self.assertEqual(summary['snapshots'], [])
            self.assertIsNone(decision._plan)
        else:
            self.assertEqual(set(summary['counts']), set(COUNT_FIELDS))
            for count in summary['counts'].values():
                self.assertIs(type(count), int)
                self.assertGreaterEqual(count, 0)
            self.assertIs(type(decision._plan), tuple)
            for item in summary['snapshots']:
                self.assertEqual(set(item), {'snapshot_sha', 'cipher_sha256'})
                self.assertRegex(item['snapshot_sha'], r'^[a-f0-9]{40}$')
                self.assertRegex(item['cipher_sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(set(summary), expected)
        self.assertEqual(json.loads(wire(summary)), summary)
        return decision, summary

    def assert_hold(self, case, reason, **overrides):
        decision, report = self.match(case, **overrides)
        self.assertEqual(report['status'], 'HOLD')
        self.assertEqual(report['reason'], reason)
        self.assertIsNone(decision._plan)
        return report

    def assert_current_still_rejected(self, current):
        row = current['records'][0]
        with self.assertRaises(self.guard.SavedModelViewError) as caught:
            self.guard._observations([row], ACTIVE, rejection=True)
        self.assertEqual(caught.exception.reason_code, BINDING)

    def test_all_groups_need_exact_older_active_originals_without_changing_current_data(self):
        current, older = views()
        before = deepcopy((current, older))
        self.assert_current_still_rejected(current)
        case = chain(current, [older])
        decision, report = self.match(case)
        self.assertEqual(report['status'], READY)
        self.assertEqual(report['snapshots'], case['hashes'])
        self.assertEqual(report['counts'], dict(
            snapshots_checked=2, current_active_rejections=1, retained_history_originals=4,
            orphan_groups=2, proved_groups=2, older_active_bodies_checked=2, planned_active_originals=2))
        self.assertEqual(len(decision._plan), 2)
        for index, (race_id, body) in enumerate(decision._plan):
            self.assertEqual(race_id, RID)
            self.assertEqual(wire(body), wire(older['records'][0][ACTIVE][index]))
            self.assertIsNot(body, case['older'][0]._view['records'][0][ACTIVE][index])
        # Only a disposable synthetic copy is changed, using the proven bodies.
        disposable = deepcopy(current)
        for race_id, body in decision._plan:
            self.assertEqual(race_id, disposable['records'][0]['race_id'])
            disposable['records'][0][ACTIVE].append(deepcopy(body))
        active, history = self.guard._observations([disposable['records'][0]], ACTIVE, rejection=True)
        self.assertEqual(len(active), 3)
        self.assertEqual(len(history), 4)
        self.assertEqual(disposable['records'][0][HISTORY], current['records'][0][HISTORY])
        for field in ('prediction', 'comparison_predictions', 'result', 'result_observations'):
            self.assertEqual(disposable['records'][0][field], current['records'][0][field])
        self.assertEqual((current, older), before)
        self.assert_current_still_rejected(current)

    def test_other_parent_race_and_sidecars_alone_never_supply_active_authority(self):
        for mode in ('other_race', 'sidecar_only'):
            with self.subTest(mode=mode):
                current, older = views()
                if mode == 'other_race':
                    older['records'][0]['race_id'] = '20300401-01-02'
                    for observation in older['records'][0]['result_observations']:
                        observation['race_id'] = '20300401-01-02'
                else:
                    older['records'][0][ACTIVE] = []
                self.assert_hold(chain(current, [older]), 'ACTIVE_PROOF_MISSING')
                self.assert_current_still_rejected(current)

    def test_any_conflicting_older_body_holds_even_when_a_nearer_original_matches(self):
        for mode in ('not_a_history_member', 'duplicate_active_key', 'deeper_conflict'):
            with self.subTest(mode=mode):
                current, older = views()
                if mode == 'not_a_history_member':
                    older['records'][0][ACTIVE][0]['private-sentinel-extra'] = 'private-sentinel-conflict'
                    previous = [older]
                elif mode == 'duplicate_active_key':
                    older['records'][0][ACTIVE].append(deepcopy(current['records'][0][HISTORY][0]))
                    previous = [older]
                else:
                    deeper = deepcopy(older)
                    deeper['records'][0][ACTIVE][0] = deepcopy(current['records'][0][HISTORY][0])
                    previous = [older, deeper]
                report = self.assert_hold(chain(current, previous), 'ACTIVE_PROOF_CONFLICT')
                self.assertNotIn('sentinel', wire(report))

    def test_one_missing_group_discards_every_partial_plan(self):
        current, older = views()
        older['records'][0][ACTIVE] = older['records'][0][ACTIVE][:1]
        self.assert_hold(chain(current, [older]), 'ACTIVE_PROOF_MISSING')
        self.assert_current_still_rejected(current)

    def test_current_history_groups_keep_reason_only_full_body_and_original_rules(self):
        for mode in ('duplicate', 'single_group_original', 'bad_reason', 'missing_source',
                     'changed_unknown_body', 'equivalent_clock_text'):
            with self.subTest(mode=mode):
                current, older = views()
                history = current['records'][0][HISTORY]
                if mode == 'duplicate':
                    history[1] = deepcopy(history[0])
                elif mode == 'single_group_original':
                    history.pop(1)
                elif mode == 'bad_reason':
                    history[1]['reason'] = None
                elif mode == 'missing_source':
                    history[1].pop('source_sha256')
                elif mode == 'changed_unknown_body':
                    history[1]['private-sentinel-extra'] = True
                else:
                    history[1]['captured_at'] = '2030-04-01T02:00:00Z'
                self.assert_hold(chain(current, [older]), 'CURRENT_HISTORY_INVALID')

    def test_already_bound_current_groups_are_preserved_without_recovery(self):
        current, older = views()
        current['records'][0][ACTIVE].extend(deepcopy(older['records'][0][ACTIVE]))
        case = chain(current, [])
        decision, report = self.match(case)
        self.assertEqual(report['status'], UNCHANGED)
        self.assertEqual(decision._plan, ())
        self.assertEqual(report['snapshots'], case['hashes'])
        self.assertEqual(report['counts'], dict(
            snapshots_checked=1, current_active_rejections=3, retained_history_originals=4,
            orphan_groups=0, proved_groups=0, older_active_bodies_checked=0, planned_active_originals=0))
        bad = deepcopy(current)
        bad['records'][0][ACTIVE][1]['reason'] = 'RESULT_UNRETAINED_ACTIVE_REASON'
        self.assert_hold(chain(bad, [older]), 'CURRENT_HISTORY_INVALID')

    def test_receipts_reject_authentication_flags_and_detect_bound_body_tampering(self):
        current, older = views()
        case = chain(current, [older])
        for fake in (True, {'authenticated': True, 'view': current}, object()):
            with self.subTest(fake_type=type(fake).__name__):
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID', current=fake)
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID', older=(fake,))
        for target in ('view', 'header', 'ciphertext'):
            with self.subTest(target=target):
                case = chain(current, [older])
                receipt = case['older'][0]
                if target == 'view':
                    receipt._view['records'][0]['private-sentinel-mutated'] = True
                elif target == 'header':
                    receipt._header['generation'] += 1
                else:
                    object.__setattr__(receipt, '_ciphertext', receipt._ciphertext + b'private-sentinel')
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID')
        case = chain(current, [older])
        item = case['items'][0]
        with self.assertRaises(ValueError) as caught:
            A._verified_snapshot(current, header=item['header'], snapshot_sha=item['hashes']['snapshot_sha'],
                manifest_cipher_sha256='0'*64, ciphertext=item['raw'])
        self.assertNotIn('sentinel', str(caught.exception))

    def test_header_cipher_links_generations_and_view_identity_must_be_contiguous(self):
        current, older = views()
        for mode in ('wrong_cipher', 'skipped_generation', 'duplicate_generation', 'different_view'):
            with self.subTest(mode=mode):
                old = mint(older, generation=423, previous='0'*64, tag='older')
                generation = 426 if mode == 'skipped_generation' else 423 if mode == 'duplicate_generation' else 424
                previous = '0'*64 if mode == 'wrong_cipher' else old['hashes']['cipher_sha256']
                latest = mint(current, generation=generation, previous=previous, tag='current',
                              view_id='8'*64 if mode == 'different_view' else 'd'*64)
                case = dict(current=latest['receipt'], older=(old['receipt'],),
                            items=[latest, old], hashes=[latest['hashes'], old['hashes']])
                self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID')
        case = chain(current, [older, deepcopy(older)])
        self.assert_hold(case, 'INPUT_OR_CHAIN_INVALID', older=tuple(reversed(case['older'])))

    def test_snapshot_and_ciphertext_bounds_hold_without_claiming_proof_absence(self):
        current, older = views()
        case = chain(current, [deepcopy(older) for _ in range(31)])
        decision, report = self.match(case)
        self.assertEqual(report['status'], READY)
        self.assertEqual(report['counts']['snapshots_checked'], 32)
        self.assertEqual(len(decision._plan), 2)
        over = chain(current, [deepcopy(older) for _ in range(32)])
        self.assert_hold(over, 'BOUND_EXCEEDED')
        self.assertEqual(A.MAX_CIPHERTEXT_BYTES, 256 * 1024 * 1024)
        case = chain(current, [older])
        exact_bytes = sum(len(item['raw']) for item in case['items'])
        with patch.object(A, 'MAX_CIPHERTEXT_BYTES', exact_bytes - 1):
            self.assert_hold(case, 'BOUND_EXCEEDED')
        with patch.object(A, 'MAX_CIPHERTEXT_BYTES', exact_bytes):
            _, report = self.match(case)
            self.assertEqual(report['status'], READY)

    def test_public_summaries_and_opaque_plans_never_leak_or_serialize_private_bodies(self):
        current, older = views()
        case = chain(current, [older])
        decision, report = self.match(case)
        self.assertEqual(report['status'], READY)
        for value in (decision, case['current'], case['older'][0]):
            with self.assertRaises(TypeError):
                json.dumps(value)
        public = wire(report)
        representation = repr(decision) + repr(case['current']) + repr(case['older'][0])
        for forbidden in ('sentinel', RID, '2030-04-01T', 'RESULT_METADATA_FIRST',
                          'RESULT_METADATA_SECOND', 'a'*64, 'b'*64, 'c'*64, 'e'*64, 'f'*64,
                          'prediction', 'result_observations', 'source_sha256'):
            self.assertNotIn(forbidden, public)
            self.assertNotIn(forbidden, representation)
        original = deepcopy(report)
        planned = wire(decision._plan)
        report['counts']['proved_groups'] = 999
        report['snapshots'][0]['snapshot_sha'] = '0'*40
        self.assertEqual(decision.public_summary(), original)
        self.assertEqual(wire(decision._plan), planned)
        self.assert_current_still_rejected(current)


if __name__ == '__main__':
    unittest.main()
