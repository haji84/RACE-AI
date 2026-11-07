"""Fictional sequential passages; no actual footage or strength certification."""
from copy import deepcopy
from datetime import timedelta
import importlib
import math
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_video_evaluation import _media
from race_ai.boat_video_measurements import measure_tracks
from tests.test_boat_video_calibration import fixture as camera_fixture, frame_hash, numpy
from tests.test_boat_video_evaluation import reseal
from tests.test_boat_video_model_context import fixture as pixel_fixture, AS_OF, CREATED


EVIDENCE_SCHEMA = 'RACE_AI_BOAT_VIDEO_SEQUENTIAL_COMPARISON_EVIDENCE_V1'
SCHEMA = 'RACE_AI_BOAT_VIDEO_SEQUENTIAL_MODEL_CONTEXT_V1'


def seal(value, key='evidence_sha256'):
    value = deepcopy(value)
    value.pop(key, None)
    value[key] = digest(value)
    return value


def rebind(report, evidence):
    report = deepcopy(report)
    parameters = report['analysis_parameters']
    report['media'] = _media(report['tracking'])
    report['measurements'] = measure_tracks(report['tracking']['tracks'], coordinate_space='REFERENCE_IMAGE_PX',
        phase_windows=parameters.get('phase_windows'), start_gate=parameters.get('start_gate'),
        max_gap_seconds=parameters.get('max_gap_seconds', .3))
    report = reseal(report)
    evidence = deepcopy(evidence)
    evidence.update(report_sha256=report['report_sha256'], source_tracking_sha256=digest(report['tracking']))
    tracks = {row['lane']: row for row in report['tracking']['tracks']}
    for identity in evidence['identities']:
        identity['track_sha256'] = digest(tracks[identity['lane']])
    for comparison in evidence['comparisons'].values():
        comparison['camera_evidence_sha256'] = digest(report['tracking']['quality'])
    return report, seal(evidence)


def fixture(snapshot=None):
    report, _ = pixel_fixture()
    tracking, _ = camera_fixture()
    tracking['media_sha256'] = report['source']['media_sha256']
    # Same image passage at different observed times: 100 versus 200 px/media-s.
    for row, t in zip(tracking['tracks'][1]['samples'], (1.1, 1.15, 1.2)):
        row['t'] = t
        index = row['frame_index']
        tracking['quality']['camera_estimates'][index]['t'] = t
        tracking['quality']['identity_observations'][index]['t'] = t
    report['tracking'] = tracking
    report['analysis_parameters'] = {'phase_windows': {'1': {'straight': [.1, .3]}, '2': {'straight': [1.1, 1.2]}}}
    as_of, created = AS_OF, CREATED
    if snapshot is not None:
        from race_ai.observed_weight_learning import ts
        from race_ai.frozen_day_cycle import official_id
        instant = ts(snapshot['as_of'])
        as_of = (instant-timedelta(minutes=1)).isoformat()
        created = (instant-timedelta(minutes=2)).isoformat()
        report.update(race_id=official_id(snapshot['race_id']), cutoff_at=snapshot['sales_cutoff_at'],
            roster=[dict(lane=p['lane'], registration_number=p['registration_no']) for p in snapshot['participants']],
            analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
            analysis_completed_at=(instant-timedelta(minutes=3)).isoformat())
        report['source']['captured_at'] = (instant-timedelta(minutes=5)).isoformat()
    roster = {r['lane']: r['registration_number'] for r in report['roster']}
    identities = [dict(lane=lane, number=lane, registration_number=roster[lane], reviewer_kind='AGENT',
        reviewer_id='fictional-independent-reader', method='INDEPENDENT_HULL_NUMBER_READ',
        track_sha256=digest(tracking['tracks'][lane-1]), frames=[dict(frame_index=row['frame_index'],
            frame_sha256=row['frame_sha256']) for row in tracking['tracks'][lane-1]['samples']]) for lane in (1, 2)]
    comparison = dict(comparison_id='fictional-fixed-image-passage', reference_frame_sha256=frame_hash(0),
        camera_scene=0, camera_evidence_sha256=digest(tracking['quality']),
        corridor=[[0., 0.], [60., 0.], [60., 100.], [0., 100.]],
        entry_gate=dict(a=[15., 0.], b=[15., 100.], normal=[1., 0.]),
        exit_gate=dict(a=[25., 0.], b=[25., 100.], normal=[1., 0.]),
        lanes={str(lane): dict(frame_indices=[r['frame_index'] for r in tracking['tracks'][lane-1]['samples']],
                              uncertainty=.02) for lane in (1, 2)})
    evidence = dict(schema_version=EVIDENCE_SCHEMA, report_sha256=report['report_sha256'],
        source_tracking_sha256=digest(tracking), media_sha256=tracking['media_sha256'],
        race_id=report['race_id'], cutoff_at=report['cutoff_at'], roster=deepcopy(report['roster']),
        created_at=created, identities=identities, comparisons={'straight': comparison}, heldout_evidence_sha256=None)
    report, evidence = rebind(report, evidence)
    return report, evidence, dict(race_id=report['race_id'], cutoff_at=report['cutoff_at'], roster=report['roster'], as_of=as_of)


@unittest.skipIf(numpy is None, 'optional NumPy is required for camera-reference replay')
class SequentialVideoContextTests(unittest.TestCase):
    def engine(self):
        try:
            return importlib.import_module('race_ai.boat_video_sequential_context')
        except ModuleNotFoundError:
            self.fail('sequential image-relative passage context is missing')

    def prepare(self, report, evidence, arguments):
        return self.engine().prepare_sequential_video_context(report, evidence, **arguments)

    def test_two_sequential_image_passages_produce_unsigned_proxies_and_keep_other_lanes_missing(self):
        report, evidence, arguments = fixture()
        before = deepcopy((report, evidence))
        context = self.prepare(report, evidence, arguments)
        self.assertTrue(context['eligible_for_research'])
        self.assertEqual(context['schema_version'], SCHEMA)
        cells = [r['feature_cells']['straight_mean_speed'] for r in context['participants']]
        self.assertAlmostEqual(cells[0]['value'], 100.)
        self.assertAlmostEqual(cells[1]['value'], 200.)
        self.assertEqual([c['unit'] for c in cells], ['px/s']*6)
        self.assertNotEqual(cells[0]['t_start'], cells[1]['t_start'])
        self.assertTrue(all(c['value'] is None for c in cells[2:]))
        self.assertEqual(context['identity_supported_lanes'], [1, 2])
        self.assertFalse(context['prediction_eligible']); self.assertFalse(context['production_eligible'])
        self.assertFalse(context['independent_human_heldout_verified'])
        self.assertEqual(context['performance_rating'], 'NOT_COMPUTED')
        self.assertEqual(context['time_basis'], 'MEDIA_TIMELINE_SECONDS')
        self.assertEqual(context['learned_direction'], 'UNTRAINED')
        self.assertEqual(set(context['default_coefficients'].values()), {0.})
        self.assertEqual(context['point_scope'], 'SUPPLIED_TRACK_POINT_REFERENCE_IMAGE_PROXY_NOT_WATER_CONTACT')
        self.assertEqual((report, evidence), before)
        self.assertEqual(self.engine().validate_sequential_video_context(context, **arguments), context)

    def test_missing_identity_evidence_keeps_all_twenty_four_cells_missing(self):
        report, _, arguments = fixture()
        context = self.prepare(report, None, arguments)
        self.assertFalse(context['eligible_for_research'])
        self.assertTrue(all(c['value'] is None for r in context['participants'] for c in r['feature_cells'].values()))

    def test_forged_source_target_or_direct_number_binding_is_rejected(self):
        report, evidence, arguments = fixture()
        mutations = [lambda e:e.update(report_sha256='f'*64), lambda e:e.update(media_sha256='f'*64),
            lambda e:e.update(source_tracking_sha256='f'*64),
            lambda e:e['identities'][0].update(number=2),
            lambda e:e['identities'][0].update(method='COLOR_INFERENCE'),
            lambda e:e['identities'][0]['frames'][0].update(frame_sha256='f'*64)]
        for mutate in mutations:
            bad = deepcopy(evidence); mutate(bad)
            with self.subTest(mutation=mutate):
                with self.assertRaises(ValueError): self.prepare(report, seal(bad), arguments)
        bad = deepcopy(evidence); bad['comparisons']['straight']['lanes']['1']['uncertainty'] = 0.
        with self.assertRaises(ValueError): self.prepare(report, bad, arguments)

    def test_wrong_reference_camera_evidence_or_scene_cannot_compare_sequential_lanes(self):
        report, evidence, arguments = fixture()
        for field, value in [('reference_frame_sha256', 'f'*64), ('camera_scene', 1), ('camera_evidence_sha256', 'f'*64)]:
            bad = deepcopy(evidence); bad['comparisons']['straight'][field] = value
            with self.subTest(field=field):
                context = self.prepare(report, seal(bad), arguments)
                self.assertFalse(context['eligible_for_research'])
                self.assertTrue(all(r['feature_cells']['straight_mean_speed']['value'] is None for r in context['participants']))

    def test_real_camera_reset_cannot_be_hidden_by_declared_shared_reference(self):
        report, evidence, arguments = fixture()
        cameras = report['tracking']['quality']['camera_estimates']
        cameras[10].update(status='INSUFFICIENT_BACKGROUND'); cameras[10].pop('homography_previous_to_current')
        for row in report['tracking']['quality']['identity_observations'][10:]: row['scene'] = 1
        for row in report['tracking']['tracks'][1]['samples']: row['camera_scene'] = 1
        report, evidence = rebind(report, evidence)
        context = self.prepare(report, evidence, arguments)
        self.assertFalse(context['eligible_for_research'])

    def test_invalid_sample_frame_pixels_and_clock_mismatches_never_gain_values(self):
        report, evidence, arguments = fixture()
        for kind in ('invalid', 'pixels', 'pts'):
            changed = deepcopy(report)
            row = changed['tracking']['tracks'][0]['samples'][1]
            if kind == 'invalid': row.update(valid=False, x=None, y=None, position_error=None)
            elif kind == 'pixels': row['frame_sha256'] = 'f'*64
            else: row['t'] = .21
            changed, proof = rebind(changed, evidence)
            # Keep the independent direct-number list on valid observed frames.
            if kind == 'invalid':
                proof['identities'][0]['frames'] = [f for f in proof['identities'][0]['frames'] if f['frame_index'] != 2]
                proof = seal(proof)
            with self.subTest(kind=kind):
                if kind == 'pixels':
                    with self.assertRaises(ValueError): self.prepare(changed, proof, arguments)
                    continue
                context = self.prepare(changed, proof, arguments)
                self.assertFalse(context['eligible_for_research'])

    def test_omitted_interior_sample_cannot_hide_an_observation_or_gap(self):
        report, evidence, arguments = fixture()
        row = deepcopy(report['tracking']['tracks'][0]['samples'][-1]); row.update(frame_index=4,t=.4,x=40.,frame_sha256=frame_hash(4))
        report['tracking']['tracks'][0]['samples'].append(row)
        evidence['comparisons']['straight']['lanes']['1']['frame_indices'] = [1, 3, 4]
        report, evidence = rebind(report, evidence)
        context = self.prepare(report, evidence, arguments)
        self.assertFalse(context['eligible_for_research'])

    def test_common_gates_require_real_ordered_crossings_inside_the_shared_corridor(self):
        report, evidence, arguments = fixture()
        for kind in ('no_crossing', 'reverse_order', 'outside_corridor'):
            bad = deepcopy(evidence); passage = bad['comparisons']['straight']
            if kind == 'no_crossing': passage['exit_gate'].update(a=[50.,0.], b=[50.,100.])
            elif kind == 'reverse_order': passage['entry_gate'],passage['exit_gate'] = passage['exit_gate'],passage['entry_gate']
            else: passage['corridor'] = [[0.,0.],[60.,0.],[60.,20.],[0.,20.]]
            with self.subTest(kind=kind):
                context = self.prepare(report, seal(bad), arguments)
                self.assertFalse(context['eligible_for_research'])

    def test_malformed_gate_polygon_and_single_lane_do_not_create_comparisons(self):
        report, evidence, arguments = fixture()
        for mutate in [lambda c:c.update(corridor=[[0.,0.],[1.,1.],[2.,2.]]),
                       lambda c:c['entry_gate'].update(normal=[0.,0.]),
                       lambda c:c['lanes']['1'].update(frame_indices=[True,2,3])]:
            bad=deepcopy(evidence); mutate(bad['comparisons']['straight'])
            with self.assertRaises(ValueError): self.prepare(report,seal(bad),arguments)
        evidence['comparisons']['straight']['lanes'].pop('2')
        context=self.prepare(report,seal(evidence),arguments)
        self.assertFalse(context['eligible_for_research'])

    def test_pre_cutoff_and_evidence_availability_are_not_relabelled(self):
        report,evidence,arguments=fixture()
        for created in ('2030-04-01T11:49:00+09:00','2030-04-01T11:56:00+09:00'):
            bad=deepcopy(evidence);bad['created_at']=created
            self.assertFalse(self.prepare(report,seal(bad),arguments)['eligible_for_research'])
        later=dict(arguments,as_of=report['cutoff_at'])
        self.assertFalse(self.prepare(report,evidence,later)['eligible_for_research'])

    def test_validator_recomputes_cells_and_rejects_resealed_strength_or_physical_claims(self):
        report,evidence,arguments=fixture();context=self.prepare(report,evidence,arguments)
        for mutate in [lambda c:c.update(production_eligible=True),lambda c:c.update(coordinate_space='WATER_PLANE_METRES'),
                       lambda c:c['participants'][0]['feature_cells']['straight_mean_speed'].update(value=999.)]:
            bad=deepcopy(context);mutate(bad)
            with self.assertRaises(ValueError):self.engine().validate_sequential_video_context(seal(bad,'context_sha256'),**arguments)

    def test_resealed_impossible_camera_transforms_cannot_validate_numeric_proxies(self):
        report,evidence,arguments=fixture();context=self.prepare(report,evidence,arguments)
        matrices = (
            [[0.,0.,0.],[0.,0.,0.],[0.,0.,0.]],
            [[1.,0.,0.],[1.,0.,0.],[0.,0.,1.]],
            [[1e-12,0.,0.],[0.,1.,0.],[0.,0.,1.]],
            [[2.,0.,0.],[0.,2.,0.],[0.,0.,2.]],
            [[1.,0.,0.],[0.,1.,0.],[0.,0.,0.]],
            [[1e6,3e6,7e6],[1e6,3e6,7e6],[11e6,13e6,1.]],
            [[1e6,3e6,7e6],[2e6,6e6,14e6],[11e6,13e6,1.]],
        )
        for matrix in matrices:
            bad=deepcopy(context)
            bad['comparisons']['straight']['lanes']['1']['camera_bindings'][0]['raw_to_reference']=matrix
            with self.subTest(matrix=matrix):
                with self.assertRaises(ValueError):
                    self.engine().validate_sequential_video_context(seal(bad,'context_sha256'),**arguments)

    def test_normalized_nonidentity_camera_binding_is_structural_not_an_accuracy_certificate(self):
        report,evidence,arguments=fixture();context=self.prepare(report,evidence,arguments)
        # A normalized, nonsingular translation is structurally possible.
        # Authenticity still requires replay against the external original.
        context['comparisons']['straight']['lanes']['1']['camera_bindings'][0]['raw_to_reference']=[
            [1.,0.,2.],[0.,1.,-3.],[0.,0.,1.]]
        checked=self.engine().validate_sequential_video_context(seal(context,'context_sha256'),**arguments)
        self.assertAlmostEqual(checked['participants'][0]['feature_cells']['straight_mean_speed']['value'],100.)
        self.assertFalse(checked['prediction_eligible'])

    def test_existing_validator_and_model_vectors_accept_sealed_pixel_proxies_without_promoting_them(self):
        from tests.test_boat_video_learning import controlled_inputs
        from race_ai.boat_video_model_context import prepare_video_context,validate_video_context
        from race_ai.boat_video_learning import video_vectors
        rows,_,_,_=controlled_inputs();snapshot=rows[0]['learning_snapshot']
        report,evidence,arguments=fixture(snapshot);context=self.prepare(report,evidence,arguments)
        self.assertEqual(prepare_video_context(report,evidence,**arguments),context)
        self.assertEqual(validate_video_context(context,**arguments),context)
        vectors=video_vectors(snapshot,context)
        self.assertEqual(len(vectors[1]),12)
        self.assertAlmostEqual(vectors[1][-1],-1/6)
        self.assertAlmostEqual(vectors[2][-1],1/6)
        self.assertEqual(vectors[3][-4:],[0.,0.,0.,0.])
        self.assertFalse(context['production_eligible'])

    def test_existing_connection_builds_the_sequential_context_without_creating_predictions(self):
        from datetime import datetime
        from race_ai.boat_video_connection import connect_report
        report,evidence,arguments=fixture()
        result=connect_report(report,identity_evidence=evidence,
            clock=lambda:datetime.fromisoformat(arguments['as_of']))
        self.assertEqual(result['video_context']['schema_version'],SCHEMA)
        self.assertTrue(result['video_context']['eligible_for_research'])
        self.assertEqual(result['shadows'],[])
        self.assertFalse(result['forecast_originals_modified'])
        self.assertFalse(result['training_performed'])

    def test_turn_exit_and_runup_use_observed_passages_without_inventing_strength_direction(self):
        expected={'turn':(30/math.pi,30/math.pi),'exit':(400.,1600.),'runup':(400.,1600.)}
        features={'turn':'turn_sampled_radius','exit':'exit_speed_trend','runup':'runup_speed_trend'}
        for phase in ('turn','exit','runup'):
            report,evidence,arguments=fixture()
            points=[(10.,40.),(20.,40.),(20.,50.),(10.,50.)] if phase=='turn' else [(10.,40.),(12.,40.),(18.,40.),(28.,40.)]
            tracking=report['tracking']
            for lane,times in ((1,(.1,.2,.3,.4)),(2,(1.1,1.15,1.2,1.25))):
                rows=tracking['tracks'][lane-1]['samples']
                rows.append(deepcopy(rows[-1]))
                for offset,(row,point,t) in enumerate(zip(rows,points,times),1):
                    index=(lane-1)*10+offset
                    row.update(frame_index=index,t=t,x=point[0],y=point[1],frame_sha256=frame_hash(index))
                if lane==2:
                    camera=deepcopy(tracking['quality']['camera_estimates'][-1]);camera.update(frame_index=14,t=1.25)
                    tracking['quality']['camera_estimates'].append(camera)
                    observation=deepcopy(tracking['quality']['identity_observations'][-1])
                    observation.update(frame_index=14,t=1.25,decoded_frame_sha256=frame_hash(14))
                    tracking['quality']['identity_observations'].append(observation)
            passage=evidence['comparisons'].pop('straight')
            passage['lanes']['1']['frame_indices']=[1,2,3,4]
            passage['lanes']['2']['frame_indices']=[11,12,13,14]
            if phase=='turn':
                passage['entry_gate']=dict(a=[15.,35.],b=[15.,45.],normal=[1.,0.])
                passage['exit_gate']=dict(a=[15.,45.],b=[15.,55.],normal=[-1.,0.])
            else:
                passage['entry_gate']=dict(a=[11.,0.],b=[11.,100.],normal=[1.,0.])
                passage['exit_gate']=dict(a=[23.,0.],b=[23.,100.],normal=[1.,0.])
            evidence['comparisons'][phase]=passage
            report,evidence=rebind(report,evidence)
            with self.subTest(phase=phase):
                context=self.prepare(report,evidence,arguments)
                self.assertTrue(context['eligible_for_research'])
                cells=[r['feature_cells'][features[phase]] for r in context['participants'][:2]]
                self.assertAlmostEqual(cells[0]['value'],expected[phase][0])
                self.assertAlmostEqual(cells[1]['value'],expected[phase][1])
                if phase=='runup':
                    self.assertEqual(cells[0]['t_end'],.3)
                    self.assertEqual(cells[1]['t_end'],1.2)
                    later=deepcopy(evidence)
                    for identity in later['identities']:
                        row=report['tracking']['tracks'][identity['lane']-1]['samples'][-1]
                        identity['frames']=[dict(frame_index=row['frame_index'],frame_sha256=row['frame_sha256'])]
                    self.assertFalse(self.prepare(report,seal(later),arguments)['eligible_for_research'])
                self.assertEqual(context['performance_rating'],'NOT_COMPUTED')
                self.assertEqual(context['learned_direction'],'UNTRAINED')



# Frozen fictional producer output made with NumPy before the data-only fix.
# The compressed JSON contains only the context, model snapshot and target;
# decoding it requires the standard library and no media or optional runtime.
_DATA_ONLY_PAYLOAD = (
    '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'
    '9Ps2svTURJaz5TbOw8N/AHxagyM='
)


class DataOnlySequentialContextTests(unittest.TestCase):
    def run_without_optional_runtime(self, *, corrupt=False):
        import base64
        import json
        import subprocess
        import sys
        import zlib
        payload = json.loads(zlib.decompress(base64.b64decode(_DATA_ONLY_PAYLOAD)))
        program = """
import importlib.abc, json, sys
class NoVideoRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('numpy', 'cv2'):
            raise ModuleNotFoundError('OPTIONAL_VIDEO_RUNTIME_FORBIDDEN')
sys.meta_path.insert(0, NoVideoRuntime())
from copy import deepcopy
from race_ai.actions_contract import digest
from race_ai.boat_video_model_context import validate_video_context
from race_ai.boat_video_learning import video_vectors
payload = json.load(sys.stdin)
context, arguments = payload['context'], payload['arguments']
if payload['corrupt']:
    rejected = 0
    for matrix in (
        [[0.,0.,0.],[0.,0.,0.],[0.,0.,0.]],
        [[1.,0.,0.],[1.,0.,0.],[0.,0.,1.]],
        [[1e-12,0.,0.],[0.,1.,0.],[0.,0.,1.]],
        [[2.,0.,0.],[0.,2.,0.],[0.,0.,2.]],
        [[1e200,0.,0.],[0.,1e200,0.],[0.,0.,1.]],
        [[1e6,3e6,7e6],[1e6,3e6,7e6],[11e6,13e6,1.]],
        [[1e6,3e6,7e6],[2e6,6e6,14e6],[11e6,13e6,1.]],
    ):
        changed = deepcopy(context)
        changed['comparisons']['straight']['lanes']['1']['camera_bindings'][0]['raw_to_reference'] = matrix
        changed.pop('context_sha256')
        changed['context_sha256'] = digest(changed)
        try:
            validate_video_context(changed, **arguments)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError('impossible saved transform accepted')
    print(json.dumps(dict(rejected=rejected)))
else:
    checked = validate_video_context(context, **arguments)
    vectors = video_vectors(payload['snapshot'], checked)
    print(json.dumps(dict(unchanged=checked == context, first=vectors[1][-4:],
        second=vectors[2][-4:], eligible=checked['eligible_for_research'],
        production=checked['production_eligible'])))
"""
        payload['corrupt'] = corrupt
        result = subprocess.run([sys.executable, '-S', '-c', program], input=json.dumps(payload),
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_saved_context_and_existing_vectors_work_without_video_runtime(self):
        result = self.run_without_optional_runtime()
        self.assertTrue(result['unchanged']); self.assertTrue(result['eligible'])
        self.assertFalse(result['production'])
        self.assertEqual(result['first'][:3], [0.,0.,0.])
        self.assertAlmostEqual(result['first'][-1], -1/6)
        self.assertAlmostEqual(result['second'][-1], 1/6)

    def test_saved_impossible_transforms_are_rejected_without_video_runtime(self):
        self.assertEqual(self.run_without_optional_runtime(corrupt=True)['rejected'], 7)
