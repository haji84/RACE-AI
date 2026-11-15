"""Controlled coordinate/clock contracts, not field calibration or accuracy."""
from copy import deepcopy
import math
import unittest

try:
    import numpy
except ImportError:
    numpy = None

from race_ai.actions_contract import digest


def seal(value):
    value = deepcopy(value)
    value['calibration_sha256'] = digest({k: v for k, v in value.items() if k != 'calibration_sha256'})
    return value


def frame_hash(index):
    return digest({'controlled_frame': index})


def fixture():
    tracks = []
    for lane in range(1, 7):
        rows = []
        if lane <= 2:
            for i in range(3):
                index = (lane - 1) * 10 + i + 1
                rows.append({'frame_index': index, 't': (lane - 1) + (i + 1) / 10,
                    'x': 10. + 10 * i, 'y': 40. + lane,
                    'scene': lane + 2, 'camera_scene': 0, 'valid': True,
                    'position_error': .01, 'frame_sha256': frame_hash(index)})
        tracks.append({'lane': lane, 'identity_status': 'NUMBER_TEMPORAL_CANDIDATE', 'samples': rows})
    tracking = {'schema_version': 'RACE_AI_BOAT_VIDEO_TRACKS_V1', 'media_sha256': 'd' * 64,
        'width': 201, 'height': 201, 'duration_seconds': 2., 'timeline_source': 'MEDIA_PTS',
        'coordinate_space': 'REFERENCE_IMAGE_PX', 'validation_status': 'UNVALIDATED',
        'model_eligible': False, 'tracks': tracks, 'quality': {
            'camera_estimates':[dict({'frame_index':i,'t':i/10,
                'status':'REFERENCE_INITIALIZATION' if i==0 else 'ACCEPTED'},
                **({} if i==0 else {'homography_previous_to_current':[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]}))
                for i in range(14)],
            'identity_observations':[{'frame_index':i,'t':i/10,'scene':0,
                'decoded_frame_sha256':frame_hash(i)} for i in range(14)]}}
    anchors = [{'id': 'anchor' + str(i), 'reference_xy': list(point),
                'world_xy': [point[0] / 10, point[1] / 10]}
               for i, point in enumerate([(0, 0), (100, 0), (100, 100), (0, 100)])]
    checks = [{'id': 'check' + str(i), 'reference_xy': list(point),
               'world_xy': [point[0] / 10, point[1] / 10]}
              for i, point in enumerate([(25, 25), (75, 75)])]
    frames = [{'frame_index': row['frame_index'], 'camera_scene': 0,
               'decoded_frame_sha256': row['frame_sha256'], 'reference_frame_sha256': frame_hash(0),
               'fit_source_sha256': 'a' * 64, 'check_source_sha256': 'b' * 64,
               'anchors': deepcopy(anchors), 'checks': deepcopy(checks)}
              for track in tracks for row in track['samples']]
    manifest = seal({'schema_version': 'RACE_AI_BOAT_VIDEO_CALIBRATION_V1',
        'media_sha256': tracking['media_sha256'], 'source_tracking_sha256': digest(tracking),
        'report_sha256': None, 'dataset_status': 'SYNTHETIC_ONLY',
        'world_frame_id':'controlled-water-plane','world_frame_source_sha256':'f'*64,
        'anchor_coordinate_space': 'RAW_DECODED_FRAME_PX', 'world_units': 'm', 'ground_plane': True,
        'clock_reference': {'source_sha256': 'c' * 64,
            'points': [{'media_t': t, 'reference_elapsed_seconds': 50. + t,
                        'uncertainty_seconds': .0001} for t in [0., 1., 2.]]},
        'frames': frames})
    return tracking, manifest


@unittest.skipIf(numpy is None, 'optional NumPy is required for projective calibration')
class BoatVideoCalibrationTests(unittest.TestCase):
    def engine(self):
        try:
            from race_ai import boat_video_calibration
        except ImportError:
            self.fail('calibration import/projection implementation is missing')
        return boat_video_calibration

    def calibrate(self, tracking, manifest):
        return self.engine().calibrate_tracks(tracking, manifest)

    def test_projects_actual_points_and_propagates_supplied_error_without_relabeling(self):
        tracking, manifest = fixture()
        before = deepcopy((tracking, manifest))
        out = self.calibrate(tracking, manifest)
        point = out['tracks'][0]['samples'][0]
        self.assertAlmostEqual(point['x'], 1., places=10)
        self.assertAlmostEqual(point['y'], 4.1, places=10)
        self.assertGreaterEqual(point['position_error'], .001 - 1e-12)
        self.assertEqual(point['scene'], 3)  # lane continuity != global camera scene0
        self.assertEqual(point['camera_scene'], 0)
        self.assertEqual(point['frame_sha256'], frame_hash(1))
        self.assertEqual(out['coordinate_space'], 'WATER_PLANE_METRES')
        self.assertEqual(out['source_tracking_sha256'], digest(tracking))
        self.assertEqual(out['calibration_sha256'], manifest['calibration_sha256'])
        self.assertEqual(out['validation_status'], 'UNVALIDATED')
        self.assertFalse(out['identity_validated'])
        self.assertFalse(out['prediction_eligible'])
        self.assertFalse(out['production_eligible'])
        self.assertEqual(out['dataset_status'], 'SYNTHETIC_ONLY')
        self.assertEqual(out['point_scope'], 'SUPPLIED_TRACK_POINT_NOT_VERIFIED_WATER_CONTACT')
        self.assertIn('BOAT_GROUND_PLANE_CONTACT_UNVERIFIED', out['validation_gaps'])
        self.assertEqual(out['clock_evidence']['status'], 'REFERENCE_DIFFERENCES_AGREE_NOT_AUTHENTICATED')
        self.assertEqual((tracking, manifest), before)
        self.assertEqual(out['envelope_sha256'], digest({k:v for k,v in out.items() if k!='envelope_sha256'}))

    def test_measures_sequential_per_boat_windows_in_metres_without_forcing_common_frames(self):
        tracking, manifest = fixture()
        out = self.engine().measure_calibrated_tracks(tracking, manifest,
            phase_windows={'1': {'straight': [.1, .3]}, '2': {'straight': [1.1, 1.3]}})
        self.assertEqual(out['schema_version'], 'RACE_AI_BOAT_VIDEO_CALIBRATED_MEASUREMENTS_V1')
        for lane in out['measurements']['lanes'][:2]:
            phase = lane['phases']['straight']
            self.assertEqual(phase['status'], 'MEASURED')
            metric = next(m for m in phase['metrics'] if m['name']=='mean_interval_speed')
            self.assertEqual(metric['unit'], 'm/s')
            self.assertAlmostEqual(metric['value'], 10., places=9)
        self.assertEqual(out['measurements']['time_basis'], 'MEDIA_TIMELINE_SECONDS')
        self.assertEqual(out['measurements']['physical_velocity'], 'NOT_ESTABLISHED')
        self.assertFalse(out['production_eligible'])
        self.assertFalse(out['independent_human_heldout_verified'])
        self.assertEqual(out['measurements_sha256'], digest(out['measurements']))

    def test_import_rejects_media_tracking_hash_tampering_and_wrong_frame_pixels(self):
        tracking, manifest = fixture()
        for mutate in [lambda x:x.update(media_sha256='f'*64),
                       lambda x:x.update(source_tracking_sha256='f'*64),
                       lambda x:x['frames'][0].update(decoded_frame_sha256='f'*64),
                       lambda x:x['frames'][0].update(camera_scene=8)]:
            bad=deepcopy(manifest);mutate(bad)
            with self.assertRaises(ValueError):self.calibrate(tracking, seal(bad))
        manifest['frames'][0]['anchors'][0]['world_xy'][0]=.2
        with self.assertRaises(ValueError):self.calibrate(tracking,manifest)

    def test_rejects_fitted_landmarks_reused_as_independent_checks_even_renamed(self):
        tracking, manifest=fixture()
        for key in ['id','reference_xy','world_xy']:
            bad=deepcopy(manifest)
            bad['frames'][0]['checks'][0][key]=deepcopy(bad['frames'][0]['anchors'][0][key])
            with self.assertRaises(ValueError, msg=key):self.calibrate(tracking,seal(bad))

    def test_independent_check_error_is_measured_and_rejected_not_anchor_residual(self):
        tracking, manifest=fixture()
        bad=deepcopy(manifest);bad['frames'][0]['checks'][0]['world_xy'][0]+=.3
        with self.assertRaises(ValueError):self.calibrate(tracking,seal(bad))
        good=deepcopy(manifest)
        for row in good['frames']:row['checks'][0]['world_xy'][0]+=.1
        out=self.calibrate(tracking,seal(good))
        self.assertAlmostEqual(out['per_frame_validation'][0]['max_check_error_m'],.1,places=9)
        self.assertGreaterEqual(out['tracks'][0]['samples'][0]['position_error'],.101-1e-10)

    def test_degenerate_nonfinite_and_excessive_fit_error_are_rejected(self):
        tracking, manifest=fixture()
        for mutation in ['collinear','nonfinite','too_large','bool_point','too_few_checks']:
            bad=deepcopy(manifest);row=bad['frames'][0]
            if mutation=='collinear':
                for i,p in enumerate(row['anchors']):p['reference_xy']=[i*10.,0.]
            elif mutation=='nonfinite':row['anchors'][0]['reference_xy'][0]=float('inf')
            elif mutation=='too_large':row['anchors'][0]['world_xy'][0]=1e200
            elif mutation=='bool_point':row['checks'][0]['world_xy'][0]=True
            else:row['checks'].pop()
            with self.assertRaises(ValueError,msg=mutation):self.calibrate(tracking,seal(bad))

    def test_clock_references_check_playback_rate_direction_and_uncertainty(self):
        tracking, manifest=fixture()
        for mutation in ['double_speed','reverse','huge_uncertainty','duplicate_media','duplicate_elapsed']:
            bad=deepcopy(manifest);points=bad['clock_reference']['points']
            if mutation=='double_speed':points[-1]['reference_elapsed_seconds']=54.
            elif mutation=='reverse':points[-1]['reference_elapsed_seconds']=49.
            elif mutation=='huge_uncertainty':points[0]['uncertainty_seconds']=1.
            elif mutation=='duplicate_media':points[1]['media_t']=0.
            else:points[1]['reference_elapsed_seconds']=50.
            with self.assertRaises(ValueError,msg=mutation):self.calibrate(tracking,seal(bad))

    def test_missing_frame_or_clock_coverage_remains_missing_without_interpolation(self):
        tracking, manifest=fixture()
        manifest['frames']=[r for r in manifest['frames'] if r['frame_index']!=2]
        manifest['clock_reference']['points']=[{'media_t':0.,'reference_elapsed_seconds':50.,'uncertainty_seconds':0.},
                                               {'media_t':.3,'reference_elapsed_seconds':50.3,'uncertainty_seconds':0.}]
        out=self.calibrate(tracking,seal(manifest))
        rows=out['tracks'][0]['samples']
        self.assertFalse(rows[1]['valid']);self.assertIsNone(rows[1]['x'])
        self.assertEqual(rows[1]['reason'],'FRAME_CALIBRATION_MISSING')
        for row in out['tracks'][1]['samples']:
            self.assertFalse(row['valid']);self.assertEqual(row['reason'],'CLOCK_REFERENCE_COVERAGE_MISSING')
        self.assertEqual([r['t'] for r in rows],[.1,.2,.3])

    def test_invalid_original_points_are_preserved_and_unknown_identity_is_not_promoted(self):
        tracking,manifest=fixture()
        tracking['tracks'][0]['samples'][1].update(valid=False,x=None,y=None,position_error=None,reason='OCCLUDED')
        tracking['tracks'][1]['identity_status']='UNRESOLVED'
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.engine().measure_calibrated_tracks(tracking,seal(manifest))
        row=out['calibrated_tracking']['tracks'][0]['samples'][1]
        self.assertEqual(row['reason'],'OCCLUDED');self.assertFalse(row['valid']);self.assertIsNone(row['x'])
        self.assertEqual(out['calibrated_tracking']['tracks'][1]['identity_status'],'UNRESOLVED')
        self.assertEqual(out['measurements']['lanes'][1]['phases']['straight']['reason'],'IDENTITY_UNRESOLVED')

    def test_projection_outside_anchor_support_is_missing_and_not_extrapolated(self):
        tracking,manifest=fixture();tracking['tracks'][0]['samples'][0]['x']=150.
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        row=out['tracks'][0]['samples'][0]
        self.assertFalse(row['valid']);self.assertEqual(row['reason'],'OUTSIDE_CALIBRATION_SUPPORT')

    def test_source_position_uncertainty_is_required_for_numeric_projection(self):
        tracking,manifest=fixture();tracking['tracks'][0]['samples'][0].pop('position_error')
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        row=out['tracks'][0]['samples'][0]
        self.assertFalse(row['valid']);self.assertEqual(row['reason'],'SOURCE_POSITION_ERROR_MISSING')


    def test_raw_frame_anchors_are_not_applied_to_stabilized_boat_coordinates(self):
        tracking,manifest=fixture()
        for index in [2,3]:
            tracking['quality']['camera_estimates'][index]['homography_previous_to_current'][0][2]=10.
        for row in manifest['frames']:
            shift=10. if row['frame_index']==2 else 20. if row['frame_index']>=3 else 0.
            for point in row['anchors']+row['checks']:point['reference_xy'][0]+=shift
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        for track in out['tracks'][:2]:
            self.assertEqual(len(track['samples']),3)
            for index,row in enumerate(track['samples']):self.assertAlmostEqual(row['x'],1.+index,places=9)
        self.assertEqual(out['per_frame_validation'][1]['source_pts_seconds'],.2)
        self.assertAlmostEqual(out['per_frame_validation'][1]['raw_to_reference'][0][2],-10.)

    def test_camera_reset_changes_reference_without_mixing_lane_continuity_scenes(self):
        tracking,manifest=fixture()
        estimates=tracking['quality']['camera_estimates'];estimates[10].pop('homography_previous_to_current')
        estimates[10]['status']='CAMERA_FIT_REJECTED'
        for row in tracking['quality']['identity_observations'][10:]:row['scene']=1
        for row in tracking['tracks'][1]['samples']:row['camera_scene']=1
        for row in manifest['frames']:
            if row['frame_index']>=10:row.update(camera_scene=1,reference_frame_sha256=frame_hash(10))
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        self.assertEqual(out['tracks'][1]['samples'][0]['scene'],4)
        self.assertEqual(out['tracks'][1]['samples'][0]['camera_scene'],1)
        self.assertAlmostEqual(out['tracks'][1]['samples'][0]['x'],1.)

    def test_missing_camera_chain_or_mismatched_pts_cannot_use_identity_transform_fallback(self):
        tracking,manifest=fixture()
        for mutation in ['missing_matrix','nonfinite_matrix','missing_observation','wrong_pts','wrong_reference']:
            source=deepcopy(tracking);bound=deepcopy(manifest)
            if mutation=='missing_matrix':source['quality']['camera_estimates'][1].pop('homography_previous_to_current')
            elif mutation=='nonfinite_matrix':source['quality']['camera_estimates'][1]['homography_previous_to_current'][0][0]=float('nan')
            elif mutation=='missing_observation':source['quality']['identity_observations'].pop(1)
            elif mutation=='wrong_pts':source['quality']['camera_estimates'][1]['t']=.11
            else:bound['frames'][0]['reference_frame_sha256']='e'*64
            with self.assertRaises(ValueError,msg=mutation):
                bound['source_tracking_sha256']=digest(source)
                self.calibrate(source,seal(bound))

    def test_world_landmark_identity_and_survey_frame_cannot_drift_between_frames(self):
        tracking,manifest=fixture()
        for mutation in ['world_drift','missing_frame_id','heldout_becomes_fit']:
            bad=deepcopy(manifest)
            if mutation=='world_drift':bad['frames'][1]['anchors'][0]['world_xy'][0]=.01
            elif mutation=='missing_frame_id':bad['world_frame_id']=''
            else:bad['frames'][1]['anchors'][0]['id']=bad['frames'][0]['checks'][0]['id']
            with self.assertRaises(ValueError,msg=mutation):self.calibrate(tracking,seal(bad))


    def test_projective_geometry_propagates_the_supplied_error_disk_conservatively(self):
        tracking,manifest=fixture()
        h=[[.12,.01,2.],[.02,.08,-1.],[.001,.002,1.]]
        def project(point):
            x,y=point;w=h[2][0]*x+h[2][1]*y+h[2][2]
            return [(h[i][0]*x+h[i][1]*y+h[i][2])/w for i in range(2)]
        for row in manifest['frames']:
            for point in row['anchors']+row['checks']:point['world_xy']=project(point['reference_xy'])
        out=self.calibrate(tracking,seal(manifest))
        row=out['tracks'][0]['samples'][0];expected=project([10.,41.])
        self.assertAlmostEqual(row['x'],expected[0],places=10)
        self.assertAlmostEqual(row['y'],expected[1],places=10)
        for i in range(128):
            theta=2*math.pi*i/128
            moved=project([10.+.01*math.cos(theta),41.+.01*math.sin(theta)])
            self.assertLessEqual(math.dist(moved,expected),row['position_error']+1e-12)

    def test_calibration_horizon_crossing_and_large_supplied_error_are_not_numeric_positions(self):
        tracking,manifest=fixture()
        def remap(value,h):
            for row in value['frames']:
                for point in row['anchors']+row['checks']:
                    x,y=point['reference_xy'];w=h[2][0]*x+h[2][1]*y+h[2][2]
                    point['world_xy']=[(h[i][0]*x+h[i][1]*y+h[i][2])/w for i in range(2)]
        bad=deepcopy(manifest);remap(bad,[[1.,0.,0.],[0.,1.,0.],[.02,0.,-1.]])
        with self.assertRaises(ValueError):self.calibrate(tracking,seal(bad))
        remap(manifest,[[.1,0.,0.],[0.,.1,0.],[.001,0.,1.]])
        tracking['tracks'][0]['samples'][0]['position_error']=2000.
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        row=out['tracks'][0]['samples'][0]
        self.assertFalse(row['valid']);self.assertEqual(row['reason'],'POSITION_UNCERTAINTY_CROSSES_HORIZON')

    def test_excessive_fit_error_and_raw_points_outside_the_bound_frame_are_rejected(self):
        tracking,manifest=fixture()
        bad=deepcopy(manifest)
        bad['frames'][0]['anchors'].append({'id':'bad-extra','reference_xy':[50.,50.],'world_xy':[8.,5.]})
        with self.assertRaises(ValueError):self.calibrate(tracking,seal(bad))
        bad=deepcopy(manifest);bad['frames'][0]['anchors'][0]['reference_xy'][0]=-1.
        with self.assertRaises(ValueError):self.calibrate(tracking,seal(bad))

    def test_image_coordinate_manifest_or_missing_world_plane_cannot_be_read_as_raw_calibration(self):
        tracking,manifest=fixture()
        for mutate in [lambda x:x.update(anchor_coordinate_space='REFERENCE_IMAGE_PX'),
                       lambda x:x.update(world_units='px'),lambda x:x.update(ground_plane=False),
                       lambda x:x.update(report_sha256='not-a-report-hash')]:
            bad=deepcopy(manifest);mutate(bad)
            with self.assertRaises(ValueError):self.calibrate(tracking,seal(bad))

    def test_invalid_finite_image_coordinates_do_not_become_metre_values(self):
        tracking,manifest=fixture()
        tracking['tracks'][0]['samples'][0].update(valid=False,reason='OCCLUDED')
        manifest['source_tracking_sha256']=digest(tracking)
        out=self.calibrate(tracking,seal(manifest))
        row=out['tracks'][0]['samples'][0]
        self.assertFalse(row['valid']);self.assertEqual(row['reason'],'OCCLUDED')
        self.assertIsNone(row['x']);self.assertIsNone(row['y']);self.assertIsNone(row['position_error'])


if __name__=='__main__':unittest.main()
