from copy import deepcopy
from base64 import b64decode, b64encode
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import keirin_research_cohort_score as cohort
from scripts import keirin_note_collect_results as note
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

    def use_note_results(self):
        self.inputs(True)
        at = self.day+'T07:18:00Z'
        published = self.results['races'][0]['comparison']
        first = self.initial['races'][0]['race_id']
        receipts = [dict(provider='Kdreams' if row['source_id']=='kdreams' else 'netkeirin',
                         source_bytes_sha256='1'*64, observed_at=at, source_url=row['url'])
                    for row in published['sources']]
        matched = note._held(first, note.MATCHED, receipts)
        matched.update(winning_triple=[3,1,2], payout_per_100yen=250)
        matched.update(captured_at=at, previous_observation_sha256=None,
                       observation_sha256=note.fact_digest(matched))
        checks = {first: dict(checked_at=at, digest=matched['observation_sha256'], status='MATCHED')}
        packet = dict(schema=note.SCHEMA, day_jst=self.day, observations=[matched])
        wire = json.dumps(packet, sort_keys=True)
        bound = {f'data/{self.day}/research_results.json':
                 dict(sha256=sha256(wire.encode()).hexdigest(), bytes=len(wire.encode()), text=wire)}
        source = b64encode(json.dumps({'files':bound}).encode()).decode()
        date_readback = dict(schema='KEIRIN_NOTE_COHORT_RESULT_READBACK_V1', date=self.day,
                             checked_at=at, result_checks=checks, packets=[packet], source_packets=[source])
        self.manifest.update(note_results='owner-note.json', note_index_commit='d'*40)
        self.save('owner-note.json', date_readback)
        self.add_note_index(date_readback)
        return first, date_readback

    def add_note_index(self, readback):
        native_index = dict(schema='RACE_AI_KEIRIN_NOTE_FEED_V1',repository='haji84/RACE-AI',
                            entries=[dict(kind='results', days=[self.day],
                                          source_content_sha256=sha256(b64decode(readback['source_packets'][0])).hexdigest())],
                            result_checks=readback['result_checks'])
        self.git['d'*40,'index.json'] = (self.day+'T07:18:00Z', json.dumps(native_index).encode())

    def test_note_results_without_verified_actual_roster_show_coverage_only(self):
        self.use_note_results()
        value = self.collect()
        self.assertEqual(value['status'], 'OWNER_NOTE_TRIFECTA_CHECKED')
        self.assertEqual(value['eligible_result_states'], {'held':1, 'missing':4})
        self.assertEqual(value['eligible_hold_reasons'], {'independent_roster_or_cutoff_unverified':1})
        self.assertEqual(value['note_matched_races'], 1)
        self.assertEqual(value['comparisons']['existing_published_line'][8]['scored'], 0)

    def test_note_results_use_existing_equal_budget_comparison_with_official_agreement(self):
        first, _ = self.use_note_results()
        self.manifest['official_result_records'] = 'official.json'
        self.save('official.json', {'races':[]})
        actual = {first: dict(cutoff_at=self.day+'T07:00:00Z', starters={1,2,3,4}, winning_triple=[3,1,2])}
        with patch.object(cohort, '_official_note_context', return_value=actual):
            value = self.collect()
        arm = value['comparisons']['existing_published_line']
        self.assertEqual([arm[cap]['tickets_per_arm'] for cap in (1,4,8)], [1,4,8])
        self.assertEqual((arm[1]['baseline_hits'],arm[1]['challenger_hits']), (0,1))
        self.assertNotIn('winning_triple', json.dumps(value))

        actual[first]['winning_triple'] = [1,2,3]
        with patch.object(cohort, '_official_note_context', return_value=actual):
            value = self.collect()
        self.assertEqual(value['eligible_hold_reasons'], {'official_note_order_disagreement':1})
        self.assertEqual(value['comparisons']['existing_published_line'][8]['scored'], 0)

    def test_old_note_index_or_mixed_published_result_files_fail(self):
        _, readback = self.use_note_results()
        self.add_note_index(dict(readback, result_checks={}))
        with self.assertRaisesRegex(ValueError, 'NOTE_COHORT_INDEX_READBACK_MISMATCH'):
            self.collect()
        self.manifest['results'] = 'public-results.json'
        with self.assertRaisesRegex(ValueError, 'COHORT_RESULT_SOURCE_MIXED'):
            self.collect()

    def test_note_receipt_time_cannot_be_edited_without_changing_the_authenticated_packet(self):
        _, readback = self.use_note_results()
        readback['packets'][0]['observations'][0]['provider_receipts'][0]['observed_at'] = self.day+'T07:17:00Z'
        self.save('owner-note.json', readback)
        with self.assertRaisesRegex(ValueError, 'NOTE_COHORT_DECODED_PACKET_MISMATCH'):
            self.collect()

    def test_official_note_context_reparses_saved_response_bytes(self):
        from race_ai import keirin_official_public_source as official
        from scripts.keirin_official_day_pipeline import private_snapshot_json
        from tests.test_keirin_official_public_source import DAY, NOW, RACE, fixtures as official_fixtures, transport

        record = official.fetch_race_result(RACE, fetcher=transport(official_fixtures()), clock=lambda: NOW)

        def context():
            return cohort._official_note_context(json.dumps(private_snapshot_json({'races':[record]})), DAY)

        self.assertEqual(context(), {RACE: dict(cutoff_at=DAY+'T10:47:00+09:00',
                                               starters=set(range(1,8)), winning_triple=[1,2,3])})
        record['result']['winning_triples'] = [[2,1,3]]
        self.assertEqual(context(), {})


if __name__ == '__main__':
    unittest.main()
