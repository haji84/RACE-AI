"""Invented identities exercise evidence admission, not race prediction quality."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import unittest

from race_ai import keirin_rider_context as predictor
from tests.test_keirin_rider_context import card


AT = '2098-12-31T16:00:00Z'
CUTOFF = '2099-01-01T02:00:00Z'
NOW = datetime(2098, 12, 31, 16, tzinfo=timezone.utc)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def episode(**changes):
    binding = dict(race_id='209812302101', car=1, registration='012345')
    row = dict(binding, event_id='switch', ability='tactical_switch', source='official_report',
        outcome='success', measurement='relative_position', reviewed_at='2098-12-30T10:00:00Z',
        published_at=None,
        observation_receipt=dict(binding, url='https://keirin.jp/report/one', sha256='a'*64,
                                 available_at='2098-12-30T09:00:00Z'),
        identity_receipt=dict(binding, url='https://keirin.jp/result/one', sha256='b'*64,
                              available_at='2098-12-30T09:30:00Z', finish=2))
    row.update(changes)
    return row


class TacticalContextTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = card()
        self.snapshot['riders'][1]['registration'] = '012345'
        self.bindings = {(self.snapshot['race_id'], 2, '012345')}

    def module(self):
        try:
            return importlib.import_module('race_ai.keirin_tactical_context')
        except ModuleNotFoundError:
            self.fail('The source-bound tactical-to-scenario adapter is missing.')

    def prepare(self, rows, **options):
        raw = encode(dict(schema='KEIRIN_REVIEWED_TACTICAL_EPISODES_V1',
            scope='PRIVATE_RETROSPECTIVE_TACTICAL_OBSERVATIONS',
            prepared_at='2098-12-31T10:00:00Z', episodes=rows))
        args = dict(packet_raw=raw, expected_sha256=sha256(raw).hexdigest(), as_of=AT,
            cutoff_at=CUTOFF, clock=lambda: NOW,
            verify_starter=lambda rid, row: (rid, row['car'], row.get('registration')) in self.bindings)
        args.update(options)
        return self.module().prepare_context(self.snapshot, **args)

    def test_verified_history_reaches_actor_paths_without_changing_predictions(self):
        saved = deepcopy(self.snapshot)
        baseline = predictor.compare(self.snapshot)
        evidence = self.prepare([episode()])
        result = predictor.compare(self.snapshot, tactical_context=evidence)
        self.assertEqual(self.snapshot, saved)
        self.assertEqual(result['baseline'], baseline['baseline'])
        summary = result['candidate'].pop('tactical_context')
        self.assertEqual(summary['riders_with_observations'], 1)
        self.assertEqual(summary['predictive_model_changed'], False)
        for arm in ('A', 'B'):
            for path in result['candidate'][arm]['six_phase_scenarios']:
                notes = path.pop('historical_tactical_context', [])
                if path['branch_kind'] == 'FOLLOWER_SELF_ATTACK' and path['attacking_car'] == 2:
                    self.assertEqual(notes[0]['car'], 2)
                    self.assertEqual(notes[0]['abilities']['tactical_switch']['observed_opportunities'], 1)
                    self.assertIsNone(notes[0]['predictive_rating'])
        for row in result['candidate']['position_evidence'].values():
            row.pop('historical_tactical_context', None)
        self.assertEqual(result, baseline)

    def test_no_eligible_history_preserves_every_scenario_and_market(self):
        evidence = self.prepare([])
        baseline = predictor.compare(self.snapshot)
        result = predictor.compare(self.snapshot, tactical_context=evidence)
        self.assertEqual(result['candidate'].pop('tactical_context')['riders_with_observations'], 0)
        self.assertEqual(result, baseline)

    def test_multi_stage_response_attaches_defender_context_without_numeric_probability(self):
        self.snapshot['riders'][6].update(style='MAKURI', makuri=3)
        evidence = self.prepare([episode(ability='resist_makuri', outcome='unknown')])
        original = predictor.multi_stage_makuri_hypotheses(self.snapshot)
        paths = predictor.multi_stage_makuri_hypotheses(self.snapshot, tactical_context=evidence)
        observed = 0
        for path in paths:
            self.assertIsNone(path['probability'])
            for move in path['moves']:
                notes = move.pop('historical_tactical_context', [])
                observed += len(notes)
        self.assertGreater(observed, 0)
        self.assertEqual(paths, original)

    def test_snapshot_or_target_substitution_is_rejected(self):
        evidence = self.prepare([episode()])
        self.snapshot['riders'][1]['registration'] = '054321'
        with self.assertRaisesRegex(ValueError, 'CONTEXT_SNAPSHOT_CHANGED'):
            predictor.compare(self.snapshot, tactical_context=evidence)

    def test_unverified_or_duplicate_current_identity_is_not_admitted(self):
        self.bindings.clear()
        evidence = self.prepare([episode()])
        self.assertEqual(evidence.receipt['riders_with_observations'], 0)
        self.assertEqual(evidence.receipt['identity_held_by_reason']['STARTER_UNVERIFIED'], 1)
        self.bindings.add((self.snapshot['race_id'], 2, '012345'))
        self.snapshot['riders'][2]['registration'] = '012345'
        evidence = self.prepare([episode()])
        self.assertEqual(evidence.receipt['riders_with_observations'], 0)

    def test_unknown_conflicting_and_unmeasured_outcomes_remain_unrated(self):
        evidence = self.prepare([episode(outcome='unknown'),
            episode(event_id='conflict'), episode(event_id='conflict', outcome='failure'),
            episode(event_id='relative', ability='side_by_side_sustain')])
        notes = evidence.for_car(2)['abilities']
        self.assertEqual(notes['tactical_switch']['known_outcomes'], 0)
        self.assertEqual(notes['tactical_switch']['unknown_outcomes'], 2)
        self.assertEqual(notes['tactical_switch']['conflicts'], 1)
        self.assertIsNone(notes['side_by_side_sustain']['observed_success_rate'])

    def test_same_day_late_review_and_wrong_historical_car_are_held(self):
        same = episode(race_id=self.snapshot['race_id'])
        late = episode(event_id='late', reviewed_at='2098-12-31T15:00:00Z')
        wrong = episode(event_id='wrong', identity_receipt=dict(episode()['identity_receipt'], car=2))
        evidence = self.prepare([same, late, wrong])
        self.assertEqual(evidence.receipt['riders_with_observations'], 0)
        self.assertEqual(evidence.receipt['held_by_reason'],
            {'RACE_NOT_HISTORICAL': 1, 'REVIEW_NOT_AVAILABLE': 1, 'RECEIPT_UNBOUND': 1})

    def test_sha_and_cutoff_clocks_are_not_optional(self):
        with self.assertRaisesRegex(ValueError, 'TACTICAL_SHA_MISMATCH'):
            self.prepare([], expected_sha256='c'*64)
        with self.assertRaisesRegex(ValueError, 'CONTEXT_CLOCK'):
            self.prepare([], as_of=CUTOFF)
        with self.assertRaisesRegex(ValueError, 'CONTEXT_CLOCK'):
            self.prepare([], cutoff_at='2099-01-02T02:00:00Z')

    def test_bare_unadmitted_profiles_cannot_be_attached(self):
        with self.assertRaisesRegex(ValueError, 'CONTEXT_NOT_ADMITTED'):
            self.module().TacticalContext(self.snapshot, {}, {})
        with self.assertRaisesRegex(ValueError, 'CONTEXT_TYPE'):
            predictor.compare(self.snapshot, tactical_context={})

    def test_receipt_and_returned_notes_cannot_mutate_admitted_context(self):
        evidence = self.prepare([episode()])
        note = evidence.for_car(2)
        note['abilities']['tactical_switch']['observed_opportunities'] = 900
        evidence.receipt['riders_with_observations'] = 900
        self.assertEqual(evidence.for_car(2)['abilities']['tactical_switch']['observed_opportunities'], 1)
        self.assertEqual(evidence.receipt['riders_with_observations'], 1)
        self.assertNotIn('012345', json.dumps(evidence.receipt))
