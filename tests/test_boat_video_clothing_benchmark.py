"""Controlled rider-part references, never real six-boat or calibration proof."""
from copy import deepcopy
import unittest

from race_ai.actions_contract import digest
from race_ai import boat_video_benchmark


MEDIA = 'a' * 64


def rider(lane, x=10):
    return dict(box=[x, 10, 10, 10], lane=lane,
                readability='UNREADABLE' if lane is None else 'READABLE')


def reference(count=1, *, riders=None):
    return dict(schema_version='RACE_AI_RIDER_PART_REFERENCE_V1', semantic_type='RIDER_PART_TYPED',
        media_sha256=MEDIA, width=160, height=90, media_class='SYNTHETIC',
        reference_class='CONTROLLED_FIXTURE', human_verified=False, blind_to_predictions=True,
        split_scope='WHOLE_MEDIA', split_frozen_before_predictions=True,
        frames=[dict(frame_index=i, t=9. + i / 10, decoded_frame_sha256='%064x' % (i + 1),
            continuity_group='shot-a', exhaustive=True, partition='DEVELOPMENT',
            riders=deepcopy(riders if riders is not None else [rider(1)])) for i in range(count)])


def proposal(number, x=10, *, track='R000001', carried=False):
    return dict(track_id=track, semantic_type='RIDER_PART_TYPED', rider_box=[x, 10, 10, 10],
        hull_box=None, number=number, identity_source='CLOTHING_COLOR', printed_number_observed=False,
        number_status=('UNKNOWN_CLOTHING_COLOR' if number is None else
            'PRIOR_CLOTHING_TRACK_CANDIDATE' if carried else 'CLOTHING_COLOR_CANDIDATE'),
        number_evidence_status=(None if number is None else
            'CURRENT_PIXEL_TRACK_PRIOR_CLOTHING_COLOR' if carried else 'CURRENT_CLOTHING_COLOR'))


def journal(ref, predictions=None):
    rows = []
    for i, frame in enumerate(ref['frames']):
        packet = dict(schema_version='RACE_AI_RIDER_PART_TRACKS_V1', frame_index=frame['frame_index'],
            t=frame['t'] - 9., scene=0, frame_sha256=frame['decoded_frame_sha256'],
            coordinate_space='IMAGE_PX', semantic_type='RIDER_PART_TYPED', identity_validated=False, model_eligible=False,
            tracks=deepcopy(predictions[i] if predictions is not None else [proposal(1)]), quality_flags=[])
        pipeline = dict(frame_index=packet['frame_index'], t=packet['t'], scene=0,
            frame_sha256=packet['frame_sha256'], identity_validated=False, model_eligible=False,
            rider_part_tracking=packet)
        rows.append(dict(schema_version='RACE_AI_BOAT_MARKER_FRAME_JOURNAL_V1', media_sha256=MEDIA,
            frame_index=packet['frame_index'], source_pts=frame['t'], t=packet['t'],
            decoded_bgr_sha256=packet['frame_sha256'], pipeline_result=pipeline))
    return rows


class ClothingBenchmarkTests(unittest.TestCase):
    def score(self, rows, ref, **config):
        score = getattr(boat_video_benchmark, 'benchmark_clothing_identity', None)
        self.assertTrue(callable(score), 'the existing benchmark cannot consume clothing-only CLI journals')
        return score(rows, ref, configuration=config or None)

    def test_unknown_rider_parts_remain_identity_misses_with_separate_geometry_counts(self):
        ref = reference(riders=[rider(1), rider(2, 40)])
        rows = journal(ref, [[proposal(1), proposal(None, 40, track='R000002'),
                              proposal(None, 80, track='R000003')]])
        report = self.score(rows, ref)
        metrics = report['partitions']['DEVELOPMENT']
        self.assertEqual((metrics['reference_visible_rider_parts'], metrics['matched_regions'],
            metrics['missed_reference_identities']), (2, 1, 1))
        self.assertEqual((metrics['matched_rider_parts'], metrics['false_positive_rider_parts'],
            metrics['missed_reference_rider_parts'], metrics['unknown_clothing_matches']), (2, 1, 0, 1))
        self.assertEqual(metrics['rider_part_precision'], 2 / 3)
        self.assertEqual(metrics['rider_part_coverage'], 1.)
        self.assertEqual(metrics['lanes']['2']['coverage'], 0.)
        self.assertEqual(report['prediction_scope'], 'CLOTHING_IDENTITIES_ON_RIDER_PARTS_NOT_HULLS')
        self.assertFalse(report['identity_validated'])
        self.assertFalse(report['physical_calibration_established'])
        self.assertFalse(report['production_eligible'])

    def test_swapped_clothing_numbers_are_scored_after_geometry_matching(self):
        ref = reference(riders=[rider(1), rider(2, 40)])
        metrics = self.score(journal(ref, [[proposal(2), proposal(1, 40, track='R000002')]]),
                             ref)['partitions']['DEVELOPMENT']
        self.assertEqual(metrics['wrong_id_matches'], 2)
        self.assertEqual(metrics['confusion']['1']['2'], 1)
        self.assertEqual(metrics['confusion']['2']['1'], 1)

    def test_current_and_carried_six_identity_matches_have_distinct_counts(self):
        targets = [rider(n, n * 20) for n in range(1, 7)]
        ref = reference(2, riders=targets)
        rows = journal(ref, [[proposal(n, n * 20, track='R%06d' % n,
                    carried=(i == 1 and n == 6)) for n in range(1, 7)] for i in range(2)])
        report = self.score(rows, ref)
        metrics = report['partitions']['DEVELOPMENT']
        self.assertEqual(metrics['whole_six_eligible_frames'], 2)
        self.assertEqual(metrics['whole_six_correct_frames'], 2)
        self.assertEqual(metrics['current_color_correct_matches'], 11)
        self.assertEqual(metrics['carried_color_correct_matches'], 1)
        self.assertEqual(metrics['whole_six_current_color_correct_frames'], 1)
        self.assertFalse(report['independent_human_heldout_verified'])
        self.assertFalse(report['strength_established'])

    def test_extra_unknown_part_cannot_be_removed_from_whole_six_frame_acceptance(self):
        ref = reference(riders=[rider(n, n * 20) for n in range(1, 7)])
        parts = [proposal(n, n * 20, track='R%06d' % n) for n in range(1, 7)]
        parts.append(proposal(None, 145, track='EQUIPMENT'))
        metrics = self.score(journal(ref, [parts]), ref)['partitions']['DEVELOPMENT']
        self.assertEqual(metrics['whole_six_eligible_frames'], 1)
        self.assertEqual(metrics['whole_six_correct_frames'], 0)
        self.assertEqual(metrics['false_positive_rider_parts'], 1)

    def test_switches_and_unknown_identity_fragmentation_have_observed_denominators(self):
        ref = reference(5)
        predictions = [[proposal(1)], [proposal(1, track='CHANGED')], [proposal(None)],
                       [proposal(1, track='RETURNED')], [proposal(2, track='RETURNED')]]
        metrics = self.score(journal(ref, predictions), ref)['partitions']['DEVELOPMENT']
        self.assertEqual(metrics['anonymous_id_switches'], 1)
        self.assertEqual(metrics['number_id_switches'], 1)
        self.assertEqual(metrics['fragmentations'], 1)
        self.assertEqual(metrics['matched_identity_transitions'], 2)

    def test_sparse_unknown_references_and_failure_flags_keep_coverage_honest(self):
        ref = reference(2, riders=[rider(None)])
        ref['frames'][0]['exhaustive'] = False
        rows = journal(ref, [[proposal(1), proposal(None, 80, track='EXTRA')], []])
        rows[1]['pipeline_result']['rider_part_tracking']['quality_flags'] = ['DETECTOR_FAILED']
        report = self.score(rows, ref)
        metrics = report['partitions']['DEVELOPMENT']
        self.assertEqual(report['quality_flag_counts'], {'DETECTOR_FAILED': 1})
        self.assertEqual(metrics['identity_unknown_matches'], 1)
        self.assertIsNone(metrics['lanes']['1']['precision'])
        self.assertEqual(metrics['rider_part_coverage'], .5)
        self.assertEqual(metrics['rider_part_precision'], 1.)
        self.assertEqual(metrics['false_positive_rider_parts'], 0)

    def test_scene_partition_and_time_boundaries_reset_transitions(self):
        ref = reference(2)
        for boundary in ('scene', 'partition', 'group', 'gap'):
            with self.subTest(boundary=boundary):
                labels = deepcopy(ref)
                rows = journal(labels, [[proposal(1)], [proposal(1, track='CHANGED')]])
                if boundary == 'scene':
                    rows[1]['pipeline_result']['scene'] = 1
                    rows[1]['pipeline_result']['rider_part_tracking']['scene'] = 1
                elif boundary == 'partition':
                    labels['split_scope'] = 'WITHIN_CLIP'
                    labels['frames'][1]['partition'] = 'HELDOUT'
                elif boundary == 'group':
                    labels['frames'][1]['continuity_group'] = 'shot-b'
                else:
                    labels['frames'][1]['t'] = 10.
                    rows[1]['source_pts'] = 10.
                    rows[1]['t'] = 1.
                    rows[1]['pipeline_result']['t'] = 1.
                    rows[1]['pipeline_result']['rider_part_tracking']['t'] = 1.
                report = self.score(rows, labels)
                self.assertEqual(sum(m['matched_identity_transitions'] for m in report['partitions'].values()), 0)

    def test_missing_clothing_mode_is_unavailable_without_inventing_empty_observations(self):
        ref = reference()
        rows = journal(ref)
        rows[0]['pipeline_result'].pop('rider_part_tracking')
        report = self.score(rows, ref)
        self.assertEqual(report['status'], 'UNAVAILABLE')
        self.assertIsNone(report['partitions'])

    def test_relative_clock_drift_and_duplicate_track_ids_are_rejected(self):
        ref = reference(2)
        for mutation in ('relative_drift', 'duplicate_id', 'forced_eligibility', 'box', 'reference_semantics',
                         'boolean_packet_frame', 'boolean_pipeline_time'):
            with self.subTest(mutation=mutation):
                labels = deepcopy(ref)
                rows = journal(labels)
                if mutation == 'relative_drift':
                    rows[1]['t'] += .01
                    rows[1]['pipeline_result']['t'] = rows[1]['t']
                    rows[1]['pipeline_result']['rider_part_tracking']['t'] = rows[1]['t']
                elif mutation == 'duplicate_id':
                    rows[0]['pipeline_result']['rider_part_tracking']['tracks'].append(proposal(2, 80))
                elif mutation == 'forced_eligibility':
                    rows[0]['pipeline_result']['rider_part_tracking']['model_eligible'] = True
                elif mutation == 'box':
                    rows[0]['pipeline_result']['rider_part_tracking']['tracks'][0]['rider_box'][0] = 200
                elif mutation == 'boolean_packet_frame':
                    rows[0]['pipeline_result']['rider_part_tracking']['frame_index'] = False
                elif mutation == 'boolean_pipeline_time':
                    rows[0]['pipeline_result']['t'] = False
                else:
                    labels['semantic_type'] = 'HULL'
                with self.assertRaisesRegex(ValueError, '^BOAT_CLOTHING_BENCHMARK_REJECTED$'):
                    self.score(rows, labels)

    def test_missing_output_and_unlabeled_frames_never_extend_identity_continuity(self):
        ref = reference(3)
        rows = journal(ref)
        rows[2]['pipeline_result']['rider_part_tracking']['tracks'][0]['track_id'] = 'CHANGED'
        partial = self.score([rows[0], rows[2]], ref)
        self.assertEqual(partial['status'], 'PARTIAL')
        self.assertEqual(partial['reference_frames_without_predictions'], 1)
        self.assertEqual(partial['partitions']['DEVELOPMENT']['matched_identity_transitions'], 0)
        sparse = deepcopy(ref)
        sparse['frames'].pop(1)
        report = self.score(rows, sparse)
        self.assertEqual(report['unlabeled_prediction_frames'], 1)
        self.assertEqual(report['partitions']['DEVELOPMENT']['anonymous_id_switches'], 0)
        self.assertEqual(self.score([], ref)['status'], 'UNAVAILABLE')

    def test_original_media_pts_pixels_and_rider_semantics_are_required(self):
        ref = reference()
        mutations = [lambda r: r[0].update(media_sha256='b' * 64),
            lambda r: r[0].update(source_pts=9.01),
            lambda r: r[0]['pipeline_result']['rider_part_tracking'].update(frame_sha256='b' * 64),
            lambda r: r[0]['pipeline_result']['rider_part_tracking']['tracks'][0].update(hull_box=[1, 1, 2, 2]),
            lambda r: r[0]['pipeline_result']['rider_part_tracking']['tracks'][0].update(number=True),
            lambda r: r[0]['pipeline_result']['rider_part_tracking']['tracks'][0].update(
                printed_number_observed=True)]
        self.score(journal(ref), ref)
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                rows = journal(ref)
                mutate(rows)
                with self.assertRaisesRegex(ValueError, '^BOAT_CLOTHING_BENCHMARK_REJECTED$'):
                    self.score(rows, ref)
        wrong_reference = deepcopy(ref)
        wrong_reference['schema_version'] = 'RACE_AI_BOAT_VIDEO_REFERENCE_V1'
        with self.assertRaises(ValueError):
            self.score(journal(ref), wrong_reference)

    def test_geometry_matches_unknown_parts_before_numbered_duplicates(self):
        ref = reference()
        # The exact unknown part owns the best geometric match. A shifted
        # numbered duplicate cannot rescue identity by dropping the unknown.
        metrics = self.score(journal(ref, [[proposal(None), proposal(1, 11, track='EXTRA')]]),
                             ref)['partitions']['DEVELOPMENT']
        self.assertEqual(metrics['unknown_clothing_matches'], 1)
        self.assertEqual(metrics['lanes']['1']['correct'], 0)
        self.assertEqual(metrics['false_positive_regions'], 1)
        self.assertEqual(metrics['false_positive_rider_parts'], 1)

    def test_inputs_and_source_hashes_are_preserved(self):
        ref = reference()
        rows = journal(ref)
        before = deepcopy((rows, ref))
        report = self.score(rows, ref)
        self.assertEqual((rows, ref), before)
        self.assertEqual(report['reference_sha256'], digest(ref))
        self.assertEqual(report['journal_rows_sha256'], digest(rows))
        self.assertEqual(report['benchmark_sha256'], digest({k: v for k, v in report.items()
                                                           if k != 'benchmark_sha256'}))
        self.assertEqual(report, self.score(rows, ref))


if __name__ == '__main__':
    unittest.main()
