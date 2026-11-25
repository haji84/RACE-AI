from copy import deepcopy
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_research_cohort_score as cohort
from tests.test_keirin_forward_score import fixtures


class ResearchCohortTests(unittest.TestCase):
    day = '2026-11-25'
    baseline_commit = 'a' * 40
    challenger_commit = 'b' * 40
    more_commit = 'c' * 40

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.git = {}
        _, _, self.roster, self.results = fixtures()
        # Results cannot precede an official deadline, which could differ from the programme.
        for r in self.roster['races']:
            r['observed_riders'].append({'number': 4})
        old = [list(t) for t in permutations((1,2,3,4), 3)][:8]
        new = [[3,1,2],[2,1,3]] + old[:-2]
        self.initial = dict(date=self.day, schema=cohort.BASELINE, frozen_at=self.day+'T04:50:00Z', races=[
            dict(race_id=r['race_id'], cutoff_at=self.day+'T15:58:00+09:00',
                 official_cutoff_at=r['published_cutoff_at'], starter_cars=[1,2,3,4], source_as_of=self.day+'T04:45:00Z',
                 eligible_points=[1,4,8], ranked_3t=old)
            for r in self.roster['races'][:5]
        ])
        self.challenge = dict(date=self.day, schema=cohort.CHALLENGER, frozen_at=self.day+'T05:02:30Z',
            caps=[1,4,8], comparators={'published':'early_existing_static','trial':'existing_published_line'},
            races=[dict(race_id=r['race_id'], cutoff_at=r['cutoff_at'], starter_cars=r['starter_cars'],
                        published=old, trial=new) for r in self.initial['races']])
        self.manifest = dict(schema=cohort.SCHEMA, challengers=[])

    def save(self, name, doc):
        data = json.dumps(doc, sort_keys=True).encode()
        (self.path / name).write_bytes(data)
        return sha256(data).hexdigest()

    def arm(self, name, pred, rev, when, extra):
        native = name+'.owner.json'
        receipt = name+'-receipt.json'
        path = 'docs/evidence/cohort/'+receipt
        digest = self.save(native, pred)
        if 'driver_sha256' not in extra:
            extra['implementation_sha256'] = '0'*64
        body = dict(date=pred['date'], frozen_at=pred['frozen_at'], forecast_sha256=digest, **extra)
        self.save(receipt, body)
        self.git[rev,path] = (self.day+'T'+when+'Z', (self.path / receipt).read_bytes())
        return dict(original=native, receipt=receipt, git_commit=rev, git_path=path), digest

    def inputs(self, registration_only=False, with_third=False):
        obj, digest = self.arm('baseline', self.initial, self.baseline_commit, '05:01:00',
            dict(fixed_point_caps=[1,4,8], predictions_frozen=len(self.initial['races']),
                 registered_known_races=len(self.initial['races']), readback_at=self.initial['frozen_at']))
        self.manifest['baseline'] = obj
        arms = [(self.challenge, self.challenger_commit)]
        if with_third:
            third = deepcopy(self.challenge)
            third['comparators']['trial'] = 'stage-and-B'
            arms.append((third, self.more_commit))
        for pred, rev in arms:
            obj, _ = self.arm(pred['comparators']['trial'], pred, rev, '05:03:00',
                dict(races=len(pred['races']), original_baseline_sha256=digest, readback=pred['frozen_at']))
            self.manifest['challengers'].append(obj)
        if not registration_only:
            self.manifest.update(roster='roster.json',results='results.json')
            for key, d in (('roster',self.roster),('results',self.results)):
                self.save(self.manifest[key],d)

    def collect(self):
        return cohort.collect(self.manifest,self.path,lambda rev, path: self.git[rev,path])

    def test_registration_needs_no_tomorrows_results(self):
        self.inputs(True)
        value = self.collect()
        self.assertEqual(value['original_registered'],5)
        self.assertEqual(value['registered_without_publication'],5)
        self.assertEqual(value['status'],'AWAITING_PUBLIC_ROSTER_AND_RESULTS')

    def test_freezes_may_be_witnessed_in_one_later_commit(self):
        self.challenge['frozen_at'] = self.day + 'T04:55:00Z'
        self.inputs(True)
        self.assertEqual(self.collect()['registered_without_publication'], 5)

    def test_challenger_cannot_freeze_before_earlier_comparator(self):
        self.challenge['frozen_at'] = self.day + 'T04:49:59Z'
        self.inputs(True)
        with self.assertRaisesRegex(ValueError,'COHORT_BASELINE_LINK_MISMATCH'):
            self.collect()

    def test_all_caps_and_arms_use_identical_validated_results(self):
        self.inputs(with_third=True)
        value = self.collect()
        self.assertEqual(value['eligible_result_states'],{'matched':3, 'held':1, 'pending':1})
        self.assertEqual(value['eligible_hold_reasons'],{'source_disagreement':1})
        self.assertEqual(value['public_roster_not_registered'],1)
        self.assertEqual(value['starter_evidence'],'car_numbers_only')
        before, after = value['comparisons'].values()
        self.assertEqual(before,after)
        self.assertEqual((before[1]['baseline_hits'],before[1]['challenger_hits'],before[1]['gained'],before[1]['lost']),
                         (1,1,1,1))
        self.assertEqual([before[cap]['tickets_per_arm'] for cap in (1,4,8)],[3,12,24])
        self.assertEqual(before[1]['gap_to_95_hits_on_matched'],2)
        self.assertEqual(value['eligible_matched_pct'],60.0)
        self.assertEqual(value['public_roster_scored_pct'],50.0)
        self.assertEqual(before[1]['baseline_wilson_95_pct'],[6.1492,79.234])
        self.assertEqual(before[1]['paired_delta_pp'],0)
        for arm in ('baseline', 'challenger'):
            self.assertEqual(sum(before[1]['misses_by_first_failed_position'][arm].values()),2)

    def test_phase_original_binds_its_own_prior_static_rows(self):
        self.inputs()
        earlier = self.manifest['baseline']['original']
        digest = sha256((self.path / earlier).read_bytes()).hexdigest()
        phase = deepcopy(self.initial)
        phase['frozen_at'] = self.day + 'T05:05:00Z'
        for row, target in zip(phase['races'], self.challenge['races'], strict=True):
            row['prior_static'] = row['ranked_3t']
            row['ranked_3t'] = target['trial']
        original, _ = self.arm('phase', phase, self.more_commit, '05:06:00', dict(base_static_sha256=digest,
            driver_sha256='0'*64, predictions_frozen=len(phase['races']), eligible_fixed_points=[1,4,8],
            readback=phase['frozen_at']))
        self.manifest['challengers'].append(original)
        value = self.collect()
        self.assertEqual(value['comparisons']['existing_published_line'],
                         value['comparisons']['existing_phase_h_unavailable'])

    def test_exclude_revised_starter_set_or_earlier_deadline(self):
        self.roster['races'][0]['observed_riders'][-1]['number'] = 5
        self.roster['races'][1]['published_cutoff_at'] = self.day+'T05:03:00Z'
        self.inputs()
        value = self.collect()
        self.assertEqual(value['exclusions'],{'starter_numbers_changed':1,'witness_at_or_after_public_cutoff':1})
        self.assertEqual(value['public_confirmed_not_in_comparison'],2)
        self.assertEqual(value['eligible_result_states'],{'matched':1,'held':1,'pending':1})

    def test_cannot_use_own_later_cutoff_if_the_earlier_arm_did_not_allow_it(self):
        self.initial['races'][0]['cutoff_at'] = self.day+'T05:02:59Z'
        self.inputs()
        value = self.collect()
        self.assertEqual(value['registered_without_publication'],4)
        self.assertEqual(value['exclusions'],{'witness_at_or_after_earliest_registered_cutoff':1})

    def test_later_arm_must_bind_literally_same_earlier_prediction(self):
        self.challenge['races'][0]['published'] = list(reversed(self.challenge['races'][0]['published']))
        self.inputs(True)
        with self.assertRaisesRegex(ValueError,'COHORT_CHALLENGER_BASELINE_ROW_MISMATCH'):
            self.collect()

    def test_forged_original_and_forged_local_receipt_both_fail(self):
        self.inputs(True)
        for k in ('original','receipt'):
            with self.subTest(k=k):
                target = self.path / self.manifest['baseline'][k]
                before = target.read_bytes()
                target.write_bytes(before+b'\n')
                with self.assertRaisesRegex(ValueError,'COHORT_GIT_RECEIPT_MISMATCH'):
                    self.collect()
                target.write_bytes(before)

    def test_a_match_with_only_one_result_source_fails(self):
        self.results['races'][0]['comparison']['sources'].pop()
        self.inputs()
        with self.assertRaisesRegex(ValueError,'DISTINCT_RESULT_SOURCES_REQUIRED'):
            self.collect()

    def test_empty_results_report_missing_coverage_without_a_hit_rate(self):
        self.results['races'].clear()
        self.inputs()
        value = self.collect()
        self.assertEqual(value['eligible_result_states'], {'missing': 5})
        self.assertEqual(value['public_roster_scored_pct'], 0)
        eight = value['comparisons']['existing_published_line'][8]
        self.assertIsNone(eight['challenger_hit_pct'])
        self.assertIsNone(eight['target_95_hits_on_matched'])


if __name__ == '__main__':
    unittest.main()
