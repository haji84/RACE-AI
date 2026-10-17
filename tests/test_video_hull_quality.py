"""Exhaustive geometric labels, rather than detector-selected successes."""
import copy
import unittest

from race_ai.core import SourceError


def labels():
    return dict(schema_version='hull-number-labels/v1', race_id='20261017-24-01',
                media_sha256='a'*64, program_identity_sha256='b'*64,
                split='DEVELOPMENT', observer_id='reviewer_a',
                frozen_at='2026-10-17T00:00:00+00:00', frames=[dict(
                    frame_id=1, frame_sha256='c'*64, width=200, height=100,
                    scene_id='camera_a', kind='MOVING_EXHIBITION', exhaustive=True,
                    overlays=[[0, 80, 200, 20]], hulls=[dict(
                        hull_id='hull_1', box=[20, 20, 60, 30], number=1,
                        number_box=[40, 30, 8, 12])])])


def candidates(ref):
    return dict(schema_version='hull-number-candidates/v1', race_id=ref['race_id'],
                media_sha256=ref['media_sha256'], program_identity_sha256=ref['program_identity_sha256'],
                split=ref['split'], model_sha256='d'*64,
                revealed_at='2026-10-17T00:00:02+00:00', frames=[dict(
                    frame_id=1, frame_sha256='c'*64, candidates=[dict(
                        candidate_id='candidate_1', box=[20, 20, 60, 30],
                        number=1, number_box=[40, 30, 8, 12])])])


class HullQualityTests(unittest.TestCase):
    def evaluate(self, ref=None, pred=None, independent=None):
        try:
            from race_ai.video_hull_quality import evaluate_hull_labels
        except ModuleNotFoundError:
            self.fail('exhaustive hull/digit quality contract is missing')
        ref = labels() if ref is None else ref
        independent = copy.deepcopy(ref) if independent is None else independent
        if independent['observer_id'] == ref['observer_id']:
            independent['observer_id'] = 'reviewer_b'
        return evaluate_hull_labels(ref, independent, candidates(ref) if pred is None else pred)

    def test_one_correct_hull_and_foreground_digit_never_authorizes_forecast(self):
        result = self.evaluate()
        self.assertEqual(result['hulls'], {'tp': 1, 'fp': 0, 'fn': 0})
        self.assertEqual(result['numbers'], {'correct': 1, 'incorrect': 0, 'missed': 0, 'unverifiable': 0})
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['automated_verified_hull_ids'], 0)
        self.assertEqual(result['boat_features'], [])

    def test_overlay_digit_cannot_pass_by_matching_the_boat_number(self):
        ref = labels(); pred = candidates(ref)
        pred['frames'][0]['candidates'][0]['number_box'] = [40, 82, 8, 12]
        result = self.evaluate(ref, pred)
        self.assertEqual(result['numbers']['correct'], 0)
        self.assertEqual(result['numbers']['incorrect'], 1)
        self.assertEqual(result['numbers']['missed'], 1)

    def test_missed_hull_and_extra_false_box_are_both_counted(self):
        ref = labels(); pred = candidates(ref)
        pred['frames'][0]['candidates'] = [dict(candidate_id='false', box=[100, 60, 20, 10], number=None, number_box=None)]
        self.assertEqual(self.evaluate(ref, pred)['hulls'], {'tp': 0, 'fp': 1, 'fn': 1})

    def test_matching_maximizes_count_instead_of_greedy_highest_iou(self):
        ref = labels(); f = ref['frames'][0]
        f['overlays'] = []
        f['hulls'] = [dict(hull_id='a', box=[10, 10, 40, 20], number=None, number_box=None),
                      dict(hull_id='b', box=[30, 10, 40, 20], number=None, number_box=None)]
        pred = candidates(ref)
        pred['frames'][0]['candidates'] = [
            dict(candidate_id='flexible', box=[20, 10, 40, 20], number=None, number_box=None),
            dict(candidate_id='only_a', box=[0, 10, 40, 20], number=None, number_box=None)]
        result = self.evaluate(ref, pred)
        self.assertEqual(result['hulls'], {'tp': 2, 'fp': 0, 'fn': 0})
        self.assertEqual({(r['candidate_id'], r['hull_id']) for r in result['frames'][0]['matches']},
                         {('flexible', 'b'), ('only_a', 'a')})

    def test_duplicate_digit_is_not_two_authenticated_boats(self):
        ref = labels(); f = ref['frames'][0]
        f['hulls'].append(dict(hull_id='hull_2', box=[100, 20, 60, 30], number=2, number_box=[120, 30, 8, 12]))
        pred = candidates(ref)
        pred['frames'][0]['candidates'].append(dict(candidate_id='candidate_2', box=[100, 20, 60, 30], number=1, number_box=[120, 30, 8, 12]))
        result = self.evaluate(ref, pred)
        self.assertEqual(result['numbers'], {'correct': 0, 'incorrect': 2, 'missed': 2, 'unverifiable': 0})

    def test_unreadable_reference_number_is_not_guessed_from_overlay(self):
        ref = labels(); ref['frames'][0]['hulls'][0].update(number=None, number_box=None)
        result = self.evaluate(ref)
        self.assertEqual(result['numbers']['unverifiable'], 1)
        self.assertEqual(result['numbers']['correct'], 0)

    def test_incomplete_labels_or_missing_prediction_frame_stop(self):
        for change in ('incomplete', 'missing'):
            ref = labels(); pred = candidates(ref)
            if change == 'incomplete': ref['frames'][0]['exhaustive'] = False
            else: pred['frames'] = []
            with self.subTest(change=change), self.assertRaises(SourceError): self.evaluate(ref, pred)

    def test_independent_disagreement_and_post_disclosure_labels_stop(self):
        ref = labels(); independent = copy.deepcopy(ref); independent['observer_id'] = 'reviewer_b'
        independent['frames'][0]['hulls'][0]['box'][0] += 1
        with self.assertRaises(SourceError): self.evaluate(ref, independent=independent)
        ref['frozen_at'] = '2026-10-17T00:00:03+00:00'
        with self.assertRaises(SourceError): self.evaluate(ref)

    def test_cross_race_media_program_frame_and_split_are_rejected(self):
        ref = labels()
        for key, value in [('race_id','20261017-24-02'),('media_sha256','e'*64),
                           ('program_identity_sha256','f'*64),('split','HELD_OUT')]:
            pred = candidates(ref); pred[key] = value
            with self.subTest(key=key), self.assertRaises(SourceError): self.evaluate(ref, pred)
        pred = candidates(ref); pred['frames'][0]['frame_sha256'] = 'e'*64
        with self.assertRaises(SourceError): self.evaluate(ref, pred)

    def test_bad_types_unknown_keys_or_nonfinite_geometry_stop(self):
        ref = labels()
        for value in (True, float('nan'), 10**1000, -1):
            pred = candidates(ref); pred['frames'][0]['candidates'][0]['box'][0] = value
            with self.subTest(value=repr(value)[:30]), self.assertRaises(SourceError): self.evaluate(ref, pred)
        pred = candidates(ref); pred['unexpected'] = True
        with self.assertRaises(SourceError): self.evaluate(ref, pred)

    def test_race_identifier_is_ascii_only(self):
        ref=labels();ref['race_id']='20261017-２４-０１'
        with self.assertRaises(SourceError):self.evaluate(ref)

    def test_subpixel_underflow_box_and_non_json_tuple_are_explicitly_rejected(self):
        for box in ([0,0,1e-200,1e-200],(20,20,60,30)):
            ref=labels();ref['frames'][0]['hulls'][0].update(box=box,number=None,number_box=None)
            pred=candidates(ref);pred['frames'][0]['candidates'][0].update(box=box,number=None,number_box=None)
            try:self.evaluate(ref,pred)
            except SourceError:pass
            except Exception as exc:self.fail('contract rejection leaked '+type(exc).__name__)
            else:self.fail('invalid geometric representation accepted')

    def test_nonmeasurement_graphic_is_not_a_moving_hull(self):
        ref = labels(); ref['frames'][0].update(kind='NON_MEASUREMENT', hulls=[])
        result = self.evaluate(ref)
        self.assertEqual(result['hulls'], {'tp':0,'fp':1,'fn':0})
        self.assertEqual(result['numbers']['correct'], 0)

    def test_inputs_and_output_are_detached_and_order_is_deterministic(self):
        ref=labels(); pred=candidates(ref); before=copy.deepcopy((ref,pred))
        first=self.evaluate(ref,pred); second=self.evaluate(ref,pred)
        self.assertEqual(first,second); self.assertEqual((ref,pred),before)
        first['frames'][0]['matches'][0]['hull_id']='changed'
        self.assertEqual(self.evaluate(ref,pred),second)


if __name__ == '__main__': unittest.main()
