"""Conditional metric arithmetic must reject missing physical evidence."""
import copy
import unittest

from race_ai.core import SourceError


def track():
    landmarks=[dict(anchor_id=str(i),image=list(p),world=[p[0]/10,p[1]/10])
               for i,p in enumerate([(0,0),(200,0),(200,100),(0,100),(50,50),(150,50)])]
    observations=[]
    for i in range(3):
        sha=hex(i+1)[2:]*64
        observations.append(dict(frame_id=i,frame_sha256=sha,scene_id='camera_a',
            physical_time=f'2026-10-17T00:00:00.{i}00000+00:00',clock_evidence_sha256='e'*64,
            time_uncertainty_seconds=.001, image_point=[50+10*i,50],
            total_world_position_error_bound_metres=.01,world_error_bound_evidence_sha256='d'*64,
            calibration=dict(frame_sha256=sha,
                scene_id='camera_a',width=200,height=100,world_reference_sha256='f'*64,
                matrix=[[.1,0,0],[0,.1,0],[0,0,1]],
                training_landmarks=copy.deepcopy(landmarks[:4]),check_landmarks=copy.deepcopy(landmarks[4:]))))
    return dict(schema_version='image-world-track/v1',race_id='20261017-24-01',media_sha256='a'*64,
                program_identity_sha256='b'*64,identity_evidence_sha256='c'*64,
                hull_number=1,track_id='track_1',motion_phase='STRAIGHT',frame_step=1,observations=observations)


class WorldMotionTests(unittest.TestCase):
    def measure(self, value=None):
        try:
            from race_ai.video_world_motion import measure_world_track
        except ModuleNotFoundError:
            self.fail('per-frame world/clock measurement contract is missing')
        return measure_world_track(track() if value is None else value)

    def test_known_sampled_displacement_rate_does_not_authorize_prediction(self):
        result=self.measure()
        self.assertAlmostEqual(result['polyline_length_metres'],2)
        self.assertEqual(len(result['segments']),2)
        for s in result['segments']:
            self.assertAlmostEqual(s['endpoint_displacement_rate_metres_per_second'],10)
            self.assertLess(s['endpoint_displacement_rate_lower_metres_per_second'],10)
            self.assertGreater(s['endpoint_displacement_rate_upper_metres_per_second'],10)
        self.assertAlmostEqual(result['finite_difference_velocity_changes'][0]['magnitude_metres_per_second_squared'],0)
        self.assertFalse(result['prediction_eligible']);self.assertEqual(result['boat_features'],[])
        self.assertEqual(result['field_validation'],'NOT_ESTABLISHED_BY_THIS_CALCULATION')

    def test_per_frame_mapping_compensates_a_moving_zoom_camera(self):
        t=track();o=t['observations'][1];o['image_point']=[120,50]
        o['calibration']['matrix']=[[.05,0,0],[0,.1,0],[0,0,1]]
        for p in o['calibration']['training_landmarks']+o['calibration']['check_landmarks']:
            p['image'][0]*=2
        o['calibration']['width']=400
        self.assertAlmostEqual(self.measure(t)['polyline_length_metres'],2)

    def test_three_point_turn_geometry_is_not_turn_skill(self):
        t=track();t['motion_phase']='TURN'
        for o,p in zip(t['observations'],[(60,50),(50,60),(40,50)]):o['image_point']=list(p)
        result=self.measure(t)
        self.assertAlmostEqual(result['turn_geometry'][0]['circumradius_metres'],1)
        self.assertAlmostEqual(abs(result['turn_geometry'][0]['heading_change_degrees']),90)
        self.assertEqual(result['performance_rating'],'NOT_COMPUTED')

    def test_incorrect_holdout_anchor_rejects_entire_track(self):
        t=track();t['observations'][-1]['calibration']['check_landmarks'][0]['world'][0]+=1
        with self.assertRaises(SourceError):self.measure(t)

    def test_singular_map_collinear_support_and_extrapolation_stop(self):
        for variant in ('singular','collinear','outside'):
            t=track();c=t['observations'][0]['calibration']
            if variant=='singular':c['matrix']=[[0,0,0],[0,0,0],[0,0,1]]
            elif variant=='collinear':
                for i,p in enumerate(c['training_landmarks']):p.update(image=[10*i,10],world=[i,1])
            else:t['observations'][0]['image_point']=[201,50]
            with self.subTest(variant=variant),self.assertRaises(SourceError):self.measure(t)

    def test_cut_world_reference_or_frame_binding_change_stops(self):
        for variant in ('cut','reference','frame'):
            t=track();o=t['observations'][1]
            if variant=='cut':o['scene_id']='camera_b'
            elif variant=='reference':o['calibration']['world_reference_sha256']='a'*64
            else:o['calibration']['frame_sha256']='a'*64
            with self.subTest(variant=variant),self.assertRaises(SourceError):self.measure(t)

    def test_missing_clock_reversal_large_gap_and_uncertain_time_stop(self):
        for variant in ('missing','reverse','gap','uncertain'):
            t=track();o=t['observations'][1]
            if variant=='missing':o.pop('clock_evidence_sha256')
            elif variant=='reverse':o['physical_time']=t['observations'][0]['physical_time']
            elif variant=='gap':o['physical_time']='2026-10-17T00:00:01+00:00'
            else:o['time_uncertainty_seconds']=.1
            with self.subTest(variant=variant),self.assertRaises(SourceError):self.measure(t)

    def test_physical_frame_date_must_be_the_races_jst_date(self):
        t=track()
        for i,o in enumerate(t['observations']):
            o['physical_time']=f'2026-10-16T14:59:59.{i}00000+00:00'
        with self.assertRaises(SourceError):self.measure(t)
        for i,o in enumerate(t['observations']):
            o['physical_time']=f'2026-10-16T16:00:00.{i}00000+00:00'
        self.assertAlmostEqual(self.measure(t)['polyline_length_metres'],2)

    def test_undeclared_skipped_sampled_frame_is_rejected(self):
        t=track()
        for o,index in zip(t['observations'],[0,2,4]):o['frame_id']=index
        with self.assertRaises(SourceError):self.measure(t)

    def test_declared_regular_sampling_stride_is_supported(self):
        t=track();t['frame_step']=2
        for o,index in zip(t['observations'],[0,2,4]):o['frame_id']=index
        try:result=self.measure(t)
        except SourceError:self.fail('declared regular sampling stride is unsupported')
        self.assertEqual(len(result['segments']),2)

    def test_tuple_point_and_extreme_timestamp_reject_without_raw_exception(self):
        for variant in ('tuple','extreme'):
            t=track()
            if variant=='tuple':t['observations'][0]['image_point']=(50,50)
            else:t['observations'][0]['physical_time']='0001-01-01T00:00:00+23:59'
            try:self.measure(t)
            except SourceError:pass
            except Exception as exc:self.fail('contract rejection leaked '+type(exc).__name__)
            else:self.fail('invalid point or timestamp accepted')

    def test_derived_landmark_residual_cannot_supply_a_global_error_bound(self):
        t=track()
        for o in t['observations']:
            c=o['calibration'];c['matrix']=[[10.1,0,0],[0,.1,0],[.5,0,1]]
            pixels=[(0,0),(200,0),(200,2),(0,2),(0,1),(200,1)]
            for row,p in zip(c['training_landmarks']+c['check_landmarks'],pixels):
                row.update(image=list(p),world=[p[0]/10,p[1]/10])
            o['image_point'][1]=1
        with self.assertRaises(SourceError):self.measure(t)

    def test_circle_chord_rate_is_not_a_bound_on_actual_arc_speed(self):
        t=track();t['motion_phase']='TURN'
        for o,p in zip(t['observations'],[(60,50),(50,60),(40,50)]):o['image_point']=list(p)
        result=self.measure(t)
        self.assertIn('polyline_length_metres',result)
        self.assertNotIn('path_length_metres',result)
        self.assertIn('endpoint_displacement_rate_metres_per_second',result['segments'][0])
        self.assertNotIn('speed_upper_metres_per_second',result['segments'][0])
        self.assertEqual(result['instantaneous_physical_speed'],'NOT_ESTIMATED')
        change=result['finite_difference_velocity_changes'][0]
        self.assertAlmostEqual(change['magnitude_metres_per_second_squared'],200)
        self.assertAlmostEqual(change['displacement_rate_change_metres_per_second_squared'],0)
        self.assertEqual(result['instantaneous_physical_acceleration'],'NOT_ESTIMATED')

    def test_changed_landmark_coordinates_or_check_reused_as_training_stop(self):
        t=track();t['observations'][1]['calibration']['training_landmarks'][0]['world'][0]+=.1
        with self.assertRaises(SourceError):self.measure(t)
        t=track();c=t['observations'][0]['calibration'];c['check_landmarks'][0]=copy.deepcopy(c['training_landmarks'][0])
        with self.assertRaises(SourceError):self.measure(t)

    def test_nan_bool_huge_number_unknown_field_or_bad_hull_number_stop(self):
        for variant in ('nan','bool','huge','unknown','number'):
            t=track()
            if variant=='nan':t['observations'][0]['image_point'][0]=float('nan')
            elif variant=='bool':t['observations'][0]['time_uncertainty_seconds']=True
            elif variant=='huge':t['observations'][0]['image_point'][0]=10**1000
            elif variant=='unknown':t['unknown']=True
            else:t['hull_number']=True
            with self.subTest(variant=variant),self.assertRaises(SourceError):self.measure(t)

    def test_result_and_input_are_detached_and_reproducible(self):
        t=track();before=copy.deepcopy(t);first=self.measure(t);second=self.measure(t)
        self.assertEqual(first,second);self.assertEqual(t,before)
        first['segments'][0]['speed_metres_per_second']=1234
        self.assertEqual(self.measure(t),second)


if __name__ == '__main__':unittest.main()
