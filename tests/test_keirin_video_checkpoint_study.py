import copy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_video_checkpoint_study as study


class VideoCheckpointStudyTests(unittest.TestCase):
    def setUp(self):
        key = '202611214204'
        url = 'https://keirin.kdreams.jp/yenjoy/keirin-kaisai/race-card/result/4220261120/42202611200200/4/'
        self.key = key
        self.review = dict(race_id=key, phase='4C_nearby_visual_sample', ambiguity=False,
                           ordered_4C=[1, 2, 3], source_url=url, time_from_digest_start_seconds=55,
                           observation_frame_sha256='a'*64, visual_sha256=['a'*64],
                           capture_receipt_sha256='b'*64)
        self.sources = [
            dict(provider='Kdreams', source_bytes_sha256='c'*64, observed_at='2026-11-21T20:00:00+09:00',
                 source_url='https://keirin.kdreams.jp/nagoya/racedetail/4220261120020004/?pageType=result'),
            dict(provider='netkeirin', source_bytes_sha256='d'*64, observed_at='2026-11-21T20:00:30+09:00',
                 source_url='https://keirin.netkeiba.com/race/result/?race_id='+key)]
        self.result = dict(race_id=key, state='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',
                           winning_triple=[1, 2, 4], provider_receipts=self.sources)
        self.bound = dict(self.review, ordered_goal=[1, 2, 4], provider_receipts=self.sources,
                          ordered_4C_registration=['010001', '010002', '010003'],
                          ordered_goal_registration=['010001', '010002', '010004'])
        self.back = dict(race_id=key, order=[1, 2, 4], seconds=48, sha256='e'*64, proof='f'*64,
                         source=url, obs_at_utc='2026-11-23T12:30:00Z')
        self.witness = dict(race_id='20261121-42-04', B_car=1, B_second=2, published_B_car=1,
                            checkpoints=[dict(phase='back', first_car=1, second_car=2,
                                              seconds_in_digest=48.2),
                                         dict(phase='corner', first_car=1, second_car=2,
                                              seconds_in_digest=55.2)])

    def history(self, day='2026-11-22'):
        return study.for_history([self.review], [self.bound], {self.key:self.result}, before=day,
                                 back=[self.back], witnesses=[self.witness])

    def test_counts_third_change_when_same_ordered_front_two(self):
        rows, skipped = self.history()
        self.assertEqual(skipped, {})
        self.assertEqual(rows, [{'race_id':self.key, 'corner':(1,2,3), 'goal':(1,2,4), 'back':(1,2,4)}])
        actual = study.summarize(rows)
        self.assertEqual(actual['same_ordered_back_corner_pair_changed_third'], 1)
        self.assertEqual(actual['same_corner_goal_pair'], 1)
        self.assertEqual(actual['same_corner_goal_order'], 0)

    def test_target_date_ambiguous_and_held_never_return_a_label(self):
        self.assertEqual(self.history('2026-11-21'), ([], {'at_or_after_boundary':1}))
        self.review['ambiguity'] = True
        self.assertEqual(self.history(), ([], {'ambiguous_corner':1}))
        self.review['ambiguity'] = False
        self.result['state'] = 'HOLD_SECONDARY_RESULT_DISAGREEMENT'
        self.assertEqual(self.history(), ([], {'no_matched_outcome':1}))

    def test_reject_inconsistent_registration_phase_and_sources(self):
        state = copy.deepcopy((self.review,self.bound,self.result,self.back,self.witness))
        for which, field, value, match in (
            (1,'ordered_goal_registration',['010099','010002','010004'],'different riders'),
            (0,'ordered_4C',[True,2,3],'Malformed corner trio'),
            (1,'ordered_4C',[1,3,2],'does not match visual review'),
            (2,'provider_receipts',[self.sources[0],self.sources[0]],'two distinct matching result sources'),
            (3,'seconds',49,'does not match checkpoint time'),
            (4,'published_B_car',4,'does not match race witness'),
        ):
            with self.subTest(field=field):
                var = [self.review,self.bound,self.result,self.back,self.witness][which]
                var[field] = value
                with self.assertRaisesRegex(ValueError,match):
                    self.history()
                var[field] = copy.deepcopy(state[which][field])

    def test_as_of_filter_requires_labels_and_both_results_to_be_available(self):
        self.bound['labelled_at_4C'] = '2026-11-22T19:00:00+09:00'
        data = ([self.review], [self.bound], {self.key:self.result})
        future, skipped = study.for_history(*data, before='2026-11-24', available_before='2026-11-22T08:00:00Z')
        self.assertEqual((future, skipped), ([], {'not_available_before':1}))
        before, skipped = study.for_history(*data, before='2026-11-24', available_before='2026-11-22T12:00:00Z')
        self.assertEqual(len(before), 1)
        self.assertEqual(skipped, {})
        self.bound['labelled_at_4C'] = True
        unknown, skipped = study.for_history(*data, before='2026-11-24', available_before='2026-11-22T12:00:00Z')
        self.assertEqual((unknown, skipped), ([], {'not_available_before':1}))
        known, skipped = study.for_history(*data, before='2026-11-24', available_before='2026-11-22T12:00:00Z',
                                           review_frozen_at='2026-11-22T11:00:00Z')
        self.assertEqual(len(known), 1)
        self.sources[1]['observed_at'] = '2026-11-23T22:01:00+09:00'
        late, skipped = study.for_history(*data, before='2026-11-24', available_before='2026-11-22T12:00:00Z')
        self.assertEqual((late, skipped), ([], {'not_available_before':1}))

    def test_early_back_image_without_a_timed_label_is_held_for_as_of_training(self):
        self.bound['labelled_at_4C'] = '2026-11-22T10:00:00Z'
        rows, skipped = study.for_history(
            [self.review], [self.bound], {self.key: self.result}, before='2026-11-24',
            back=[self.back], witnesses=[self.witness], available_before='2026-11-24T00:00:00Z',
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn('back', rows[0])
        self.assertEqual(skipped, {'back_not_available_before':1})

    def test_reads_only_digest_bound_bytes_and_disallows_duplicate_rows(self):
        with TemporaryDirectory() as folder:
            ref = Path(folder)/'review.json'
            ref.write_bytes(b'{}\n')
            digest = sha256(ref.read_bytes()).hexdigest()
            self.assertEqual(study.checked_json(ref,digest), {})
            ref.write_bytes(b'{ }')
            with self.assertRaisesRegex(ValueError,'digest mismatch'):
                study.checked_json(ref,digest)
        with self.assertRaisesRegex(ValueError,'Duplicate race ID'):
            study.for_history([self.review,self.review], [], {}, before='2026-11-22')


if __name__ == '__main__':
    unittest.main()
