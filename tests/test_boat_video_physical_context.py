"""Fictional raw-pixel/clock/identity inputs; never field calibration claims."""
from copy import deepcopy
from datetime import timedelta
import importlib
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_video_calibration import calibrate_tracks
from race_ai.boat_video_evaluation import _media
from race_ai.boat_video_measurements import measure_tracks
from tests.test_boat_video_calibration import fixture as calibration_fixture, seal as seal_calibration, numpy
from tests.test_boat_video_model_context import fixture as pixel_fixture, AS_OF, CREATED
from tests.test_boat_video_evaluation import reseal, roster, RACE, CUTOFF


PHYSICAL_SCHEMA='RACE_AI_BOAT_VIDEO_PHYSICAL_MODEL_CONTEXT_V2'
EVIDENCE_SCHEMA='RACE_AI_BOAT_VIDEO_PHYSICAL_COMPARISON_EVIDENCE_V1'
WINDOWS={'1':{'straight':[.1,.3]},'2':{'straight':[1.1,1.3]}}


def seal_evidence(value):
    value=deepcopy(value);value.pop('evidence_sha256',None);value['evidence_sha256']=digest(value)
    return value


def seal_context(value):
    value=deepcopy(value);value.pop('context_sha256',None);value['context_sha256']=digest(value)
    return value


def physical_fixture(snapshot=None):
    report,_=pixel_fixture();tracking,manifest=calibration_fixture()
    for i,row in enumerate(tracking['tracks'][1]['samples']):row['x']=10.+20*i
    tracking['media_sha256']=report['source']['media_sha256']
    report['tracking']=tracking;report['media']=_media(tracking)
    report['analysis_parameters']={'phase_windows':deepcopy(WINDOWS)}
    report['measurements']=measure_tracks(tracking['tracks'],coordinate_space='REFERENCE_IMAGE_PX',phase_windows=WINDOWS)
    as_of,created=AS_OF,CREATED
    if snapshot is not None:
        from race_ai import observed_weight_learning as existing
        from race_ai.frozen_day_cycle import official_id
        instant=existing.ts(snapshot['as_of']);as_of=(instant-timedelta(minutes=1)).isoformat()
        created=(instant-timedelta(minutes=2)).isoformat()
        report.update(race_id=official_id(snapshot['race_id']),cutoff_at=snapshot['sales_cutoff_at'],
            roster=[{'lane':p['lane'],'registration_number':p['registration_no']} for p in snapshot['participants']],
            analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
            analysis_completed_at=(instant-timedelta(minutes=3)).isoformat())
        report['source']['captured_at']=(instant-timedelta(minutes=5)).isoformat()
    report=reseal(report)
    manifest.update(media_sha256=tracking['media_sha256'],source_tracking_sha256=digest(tracking),
                    report_sha256=report['report_sha256'],dataset_status=report['dataset_status'])
    manifest=seal_calibration(manifest);calibrated=calibrate_tracks(tracking,manifest)
    by_lane={r['lane']:r for r in report['roster']}
    identities=[{'lane':lane,'registration_number':by_lane[lane]['registration_number'],'number':lane,
        'reviewer_kind':'AGENT','reviewer_id':'fictional-independent-reader',
        'method':'INDEPENDENT_HULL_NUMBER_READ','track_sha256':digest(tracking['tracks'][lane-1]),
        'frames':[{'frame_index':tracking['tracks'][lane-1]['samples'][0]['frame_index'],
                   'frame_sha256':tracking['tracks'][lane-1]['samples'][0]['frame_sha256']}]} for lane in [1,2]]
    comparison={'comparison_id':'fictional-sequential-straight',
        'world_frame_id':calibrated['world_frame_id'],'world_frame_source_sha256':calibrated['world_frame_source_sha256'],
        'calibration_evidence_sha256':manifest['calibration_sha256'],
        'clock_evidence_sha256':digest(calibrated['clock_evidence']),
        'lanes':{str(lane):{'frame_indices':[r['frame_index'] for r in tracking['tracks'][lane-1]['samples']],
                    'phase_evidence_sha256':'1'*64,'uncertainty':.02} for lane in [1,2]}}
    evidence=seal_evidence({'schema_version':EVIDENCE_SCHEMA,'report_sha256':report['report_sha256'],
        'media_sha256':tracking['media_sha256'],'race_id':report['race_id'],'cutoff_at':report['cutoff_at'],
        'roster':deepcopy(report['roster']),'created_at':created,'identities':identities,
        'comparisons':{'straight':comparison},'heldout_evidence_sha256':None})
    arguments=dict(race_id=report['race_id'],cutoff_at=report['cutoff_at'],roster=report['roster'],
                   as_of=as_of,phase_windows=deepcopy(WINDOWS))
    return report,evidence,manifest,arguments


def controlled_physical_inputs(count=12):
    from tests.test_boat_video_learning import controlled_inputs
    from race_ai.boat_video_physical_context import prepare_physical_video_context
    from race_ai import observed_weight_learning as existing
    rows,observations,_,_=controlled_inputs(count)
    contexts,proofs={},{}
    for index,row in enumerate(rows[::2]):
        snapshot=row['learning_snapshot'];report,evidence,manifest,args=physical_fixture(snapshot)
        context=prepare_physical_video_context(report,evidence,manifest,**args)
        instant=existing.ts(snapshot['as_of'])
        receipt=dict(id=4000+index,created_at=(instant-timedelta(seconds=30)).isoformat(),
            digest='sha256:'+digest({'controlled_context':context}),expired=False,
            workflow_run={'head_repository_id':1416489937})
        contexts[row['race_id']]=dict(video_context=context,receipt=receipt)
        proofs[context['context_sha256']]=dict(context_sha256=context['context_sha256'],
            id=receipt['id'],digest=receipt['digest'],created_at=receipt['created_at'])
    def verifier(receipt,context_sha256,as_of):
        proof=proofs.get(context_sha256)
        if proof is not None and proof['id']==receipt['id'] and proof['digest']==receipt['digest']:
            return deepcopy(proof)
        return None
    return rows,observations,contexts,verifier


@unittest.skipIf(numpy is None,'optional NumPy is required for physical-context projection')
class BoatVideoPhysicalContextTests(unittest.TestCase):
    def engine(self):
        try:return importlib.import_module('race_ai.boat_video_physical_context')
        except ImportError:self.fail('physical-coordinate context adapter is missing')

    def prepare(self,report,evidence,manifest,arguments):
        return self.engine().prepare_physical_video_context(report,evidence,manifest,**arguments)

    def test_sequential_physical_windows_keep_missing_lanes_and_explicit_physical_limits(self):
        report,evidence,manifest,args=physical_fixture();before=deepcopy((report,evidence,manifest))
        out=self.prepare(report,evidence,manifest,args)
        self.assertEqual(out['schema_version'],PHYSICAL_SCHEMA);self.assertTrue(out['eligible_for_research'])
        self.assertEqual(out['coordinate_space'],'WATER_PLANE_METRES')
        self.assertEqual(out['identity_supported_lanes'],[1,2])
        first,second=[r['feature_cells']['straight_mean_speed'] for r in out['participants'][:2]]
        self.assertAlmostEqual(first['value'],10.);self.assertAlmostEqual(second['value'],20.)
        self.assertEqual(first['unit'],'m/s');self.assertNotEqual(first['t_start'],second['t_start'])
        for row in out['participants'][2:]:
            self.assertIsNone(row['feature_cells']['straight_mean_speed']['value'])
            self.assertEqual(row['feature_cells']['straight_mean_speed']['missing_reason'],'INDEPENDENT_NUMBER_EVIDENCE_MISSING')
        self.assertFalse(out['prediction_eligible']);self.assertFalse(out['production_eligible'])
        self.assertFalse(out['independent_human_heldout_verified'])
        self.assertIn('BOAT_GROUND_PLANE_CONTACT_UNVERIFIED',out['validation_gaps'])
        self.assertEqual(out['performance_rating'],'NOT_COMPUTED')
        self.assertEqual((report,evidence,manifest),before)
        from race_ai.boat_video_model_context import validate_video_context
        target={k:args[k] for k in ['race_id','cutoff_at','roster','as_of']}
        self.assertEqual(validate_video_context(out,**target),out)

    def test_missing_evidence_does_not_create_unobserved_identities_or_values(self):
        report,evidence,manifest,args=physical_fixture()
        out=self.prepare(report,None,manifest,args)
        self.assertFalse(out['eligible_for_research']);self.assertEqual(out['identity_supported_lanes'],[])
        self.assertTrue(all(c['value'] is None for r in out['participants'] for c in r['feature_cells'].values()))

    def test_direct_number_reference_must_overlap_each_boat_phase_and_two_numeric_lanes_are_required(self):
        report,evidence,manifest,args=physical_fixture()
        # A genuine observed number frame exists later, outside the selected
        # phase. It must not authenticate an earlier, disjoint phase window.
        from tests.test_boat_video_calibration import frame_hash
        later=deepcopy(report['tracking']['tracks'][1]['samples'][-1])
        later.update(frame_index=14,t=1.4,x=70.,frame_sha256=frame_hash(14))
        report['tracking']['tracks'][1]['samples'].append(later)
        camera=deepcopy(report['tracking']['quality']['camera_estimates'][-1]);camera.update(frame_index=14,t=1.4)
        report['tracking']['quality']['camera_estimates'].append(camera)
        report['tracking']['quality']['identity_observations'].append(
            {'frame_index':14,'t':1.4,'scene':0,'decoded_frame_sha256':frame_hash(14)})
        report=reseal(report)
        manifest.update(source_tracking_sha256=digest(report['tracking']),report_sha256=report['report_sha256'])
        manifest=seal_calibration(manifest)
        evidence['report_sha256']=report['report_sha256']
        evidence['comparisons']['straight']['calibration_evidence_sha256']=manifest['calibration_sha256']
        evidence['identities'][1]['track_sha256']=digest(report['tracking']['tracks'][1])
        evidence['identities'][1]['frames']=[{'frame_index':14,'frame_sha256':frame_hash(14)}]
        out=self.prepare(report,seal_evidence(evidence),manifest,args)
        self.assertFalse(out['eligible_for_research'])
        self.assertTrue(all(r['feature_cells']['straight_mean_speed']['value'] is None for r in out['participants']))
        evidence['identities'].pop()
        out=self.prepare(report,seal_evidence(evidence),manifest,args)
        self.assertFalse(out['eligible_for_research'])

    def test_foreign_report_calibration_survey_clock_and_frame_evidence_are_rejected(self):
        report,evidence,manifest,args=physical_fixture()
        for mutate in [lambda x:x.update(report_sha256='f'*64),lambda x:x.update(report_sha256=None)]:
            bad=deepcopy(manifest);mutate(bad)
            with self.assertRaises(ValueError):self.prepare(report,evidence,seal_calibration(bad),args)
        for mutate in [lambda x:x.update(report_sha256='f'*64),
            lambda x:x['comparisons']['straight'].update(world_frame_id='other-plane'),
            lambda x:x['comparisons']['straight'].update(clock_evidence_sha256='f'*64),
            lambda x:x['identities'][0]['frames'][0].update(frame_sha256='f'*64)]:
            bad=deepcopy(evidence);mutate(bad)
            with self.assertRaises(ValueError):self.prepare(report,seal_evidence(bad),manifest,args)

    def test_post_cutoff_future_and_synthetic_data_keep_all_cells_missing(self):
        report,evidence,manifest,args=physical_fixture()
        badargs=dict(args,as_of=report['cutoff_at'])
        out=self.prepare(report,evidence,manifest,badargs)
        self.assertFalse(out['eligible_for_research']);self.assertIn('POST_CUTOFF_ONLY',out['missing_reasons'])
        evidence['created_at']='2030-04-01T11:59:00+09:00'
        out=self.prepare(report,seal_evidence(evidence),manifest,args)
        self.assertFalse(out['eligible_for_research']);self.assertIn('EVIDENCE_NOT_AVAILABLE_AS_OF',out['missing_reasons'])

    def test_resealed_units_certification_and_comparison_window_tampering_are_rejected(self):
        report,evidence,manifest,args=physical_fixture();context=self.prepare(report,evidence,manifest,args)
        from race_ai.boat_video_model_context import validate_video_context
        target={k:args[k] for k in ['race_id','cutoff_at','roster','as_of']}
        for mutate in [lambda x:x.update(coordinate_space='REFERENCE_IMAGE_PX'),
            lambda x:x.update(production_eligible=True),lambda x:x.update(validation_gaps=[]),
            lambda x:x['participants'][0]['feature_cells']['straight_mean_speed'].update(unit='px/s'),
            lambda x:x['comparisons']['straight']['lanes']['1'].update(t_end=.25)]:
            bad=deepcopy(context);mutate(bad)
            with self.assertRaises(ValueError):validate_video_context(seal_context(bad),**target)

    def test_legacy_pixel_preparation_and_validation_still_use_identical_bytes(self):
        from race_ai.boat_video_model_context import prepare_video_context,validate_video_context
        report,evidence=pixel_fixture();args=dict(race_id=RACE,cutoff_at=CUTOFF,roster=roster(),as_of=AS_OF)
        context=prepare_video_context(report,evidence,**args);before=deepcopy(context)
        self.assertEqual(validate_video_context(context,**args),context)
        self.assertEqual(context,before);self.assertEqual(context['coordinate_space'],'REFERENCE_IMAGE_PX')

    def test_physical_vectors_are_within_race_unitless_contrasts_for_the_existing_twelve_dimensions(self):
        from tests.test_boat_video_learning import controlled_inputs
        from race_ai.boat_video_learning import video_vectors,FEATURES
        rows,_,_,_=controlled_inputs();snapshot=rows[0]['learning_snapshot']
        report,evidence,manifest,args=physical_fixture(snapshot)
        context=self.prepare(report,evidence,manifest,args);vectors=video_vectors(snapshot,context)
        self.assertEqual(len(FEATURES),12)
        self.assertAlmostEqual(vectors[1][-1],-1/6);self.assertAlmostEqual(vectors[2][-1],1/6)
        for lane in range(3,7):self.assertEqual(vectors[lane][-4:],[0.,0.,0.,0.])


    def test_physical_training_records_dimensionless_contrasts_and_explicit_input_schemas(self):
        from race_ai.boat_video_learning import fit_with_video,verify_video_training,FEATURES
        from tests.test_boat_video_learning import NOW
        rows,observations,contexts,verifier=controlled_physical_inputs()
        out=fit_with_video(rows,observations,contexts,now=NOW,receipt_verifier=verifier)
        self.assertEqual(out['state'],'FITTED_VIDEO_EXPERIMENTAL')
        self.assertEqual(out['video_context_coordinate_spaces'],['WATER_PLANE_METRES'])
        self.assertEqual({r['unit'] for r in out['video_feature_schema']},{'dimensionless'})
        self.assertEqual(out['video_input_feature_schemas']['WATER_PLANE_METRES'][-1]['unit'],'m/s')
        self.assertEqual(len(out['feature_schema']),12);verify_video_training(out)
        self.assertEqual(out['feature_support_train']['turn_sampled_radius'],0)
        for mid in out['source_family_ids']:
            self.assertEqual(out['models'][mid]['video_weights'][:3],[0.,0.,0.])
        bad=deepcopy(out);bad['video_input_feature_schemas']['WATER_PLANE_METRES'][-1]['unit']='px/s'
        bad['training_sha256']=digest({k:v for k,v in bad.items() if k!='training_sha256'})
        with self.assertRaises(ValueError):verify_video_training(bad)

    def test_no_independent_verifier_admits_no_physical_video_training_support(self):
        from race_ai.boat_video_learning import fit_with_video
        from tests.test_boat_video_learning import NOW
        rows,observations,contexts,_=controlled_physical_inputs()
        out=fit_with_video(rows,observations,contexts,now=NOW)
        self.assertEqual(out['video_admitted_races'],0)
        self.assertEqual(out['state'],'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(out['video_feature_schema'][-1]['unit'],'px/s')
        self.assertNotIn('video_context_coordinate_spaces',out)

    def test_replayed_physical_report_reaches_only_the_same_two_existing_model_shadows(self):
        from race_ai.boat_video_learning import fit_with_video
        from race_ai.boat_video_connection import connect_report
        from race_ai.boat_observed_pairwise_models import MODEL_IDS
        from tests.test_boat_video_learning import NOW
        from tests.test_boat_video_connection import controlled_connection
        rows,observations,contexts,verifier=controlled_physical_inputs()
        training=fit_with_video(rows,observations,contexts,now=NOW,receipt_verifier=verifier)
        _,_,inputs,_,instant=controlled_connection(training)
        report,evidence,manifest,args=physical_fixture(inputs['snapshot'])
        physical=self.prepare(report,evidence,manifest,args)
        inputs.update(video_context=physical,calibration_manifest=manifest)
        receipt=inputs['video_receipt'];proof=dict(context_sha256=physical['context_sha256'],
            id=receipt['id'],digest=receipt['digest'],created_at=receipt['created_at'])
        def reader(candidate,context_sha256,as_of):
            if candidate==receipt and context_sha256==physical['context_sha256']:return deepcopy(proof)
        out=connect_report(report,identity_evidence=evidence,model_inputs=inputs,receipt_verifier=reader,clock=lambda:instant)
        self.assertEqual(out['status'],'CONNECTED_EXPERIMENTAL')
        self.assertEqual({r['model_id'] for r in out['shadows']},set(MODEL_IDS))
        self.assertEqual(out['video_context'],physical)
        self.assertTrue(all(not r['production_eligible'] for r in out['shadows']))
        self.assertEqual(len(out['shadows'][0]['ordered_top8']),8)
        inputs.pop('calibration_manifest')
        blocked=connect_report(report,identity_evidence=evidence,model_inputs=inputs,receipt_verifier=reader,clock=lambda:instant)
        self.assertNotEqual(blocked['status'],'CONNECTED_EXPERIMENTAL');self.assertEqual(blocked['shadows'],[])

    def test_legacy_pixel_training_cannot_silently_accept_a_physical_target(self):
        from race_ai.boat_video_learning import fit_with_video,make_video_shadows
        from tests.test_boat_video_learning import controlled_inputs,NOW
        from tests.test_boat_video_connection import controlled_connection
        rows,observations,contexts,verifier=controlled_inputs()
        training=fit_with_video(rows,observations,contexts,now=NOW,receipt_verifier=verifier)
        _,_,inputs,_,_=controlled_connection(training)
        report,evidence,manifest,args=physical_fixture(inputs['snapshot']);context=self.prepare(report,evidence,manifest,args)
        receipt=inputs['video_receipt'];proof=dict(context_sha256=context['context_sha256'],id=receipt['id'],
            digest=receipt['digest'],created_at=receipt['created_at'])
        with self.assertRaises(ValueError):make_video_shadows(inputs['snapshot'],inputs['baseline_suite'],
            inputs['training_context'],dict(video_context=context,receipt=receipt),receipt_verifier=lambda *_:deepcopy(proof))


    def test_mixed_input_units_are_declared_separately_and_never_pooled_as_raw_values(self):
        from tests.test_boat_video_learning import controlled_inputs,NOW
        from race_ai.boat_video_learning import fit_with_video,verify_video_training
        rows,observations,pixel,verify_pixel=controlled_inputs()
        _,_,physical,verify_physical=controlled_physical_inputs()
        combined={rid:(physical[rid] if i%2 else pixel[rid]) for i,rid in enumerate(pixel)}
        def reader(receipt,context_sha256,as_of):
            return verify_physical(receipt,context_sha256,as_of) or verify_pixel(receipt,context_sha256,as_of)
        out=fit_with_video(rows,observations,combined,now=NOW,receipt_verifier=reader)
        self.assertEqual(out['video_context_coordinate_spaces'],['REFERENCE_IMAGE_PX','WATER_PLANE_METRES'])
        self.assertEqual(out['video_input_feature_schemas']['REFERENCE_IMAGE_PX'][-1]['unit'],'px/s')
        self.assertEqual(out['video_input_feature_schemas']['WATER_PLANE_METRES'][-1]['unit'],'m/s')
        self.assertEqual(out['video_feature_schema'][-1]['unit'],'dimensionless');verify_video_training(out)

    def test_empty_observed_identity_subset_is_explicit_missing_not_six_fabricated_reads(self):
        report,evidence,manifest,args=physical_fixture();evidence['identities']=[]
        out=self.prepare(report,seal_evidence(evidence),manifest,args)
        self.assertEqual(out['identity_supported_lanes'],[]);self.assertFalse(out['eligible_for_research'])

    def test_resealed_numeric_context_cannot_reuse_an_original_independent_receipt(self):
        from race_ai.boat_video_learning import fit_with_video
        from tests.test_boat_video_learning import NOW
        rows,observations,contexts,reader=controlled_physical_inputs()
        changed=deepcopy(contexts);rid=next(iter(changed));context=changed[rid]['video_context']
        context['participants'][0]['feature_cells']['straight_mean_speed']['value']+=1.
        changed[rid]['video_context']=seal_context(context)
        with self.assertRaises(ValueError):fit_with_video(rows,observations,changed,now=NOW,receipt_verifier=reader)


    def test_physical_start_gate_requires_explicit_metre_coordinate_label(self):
        report,evidence,manifest,args=physical_fixture()
        gate={'a':[2.5,0.],'b':[2.5,10.],'normal':[1.,0.]}
        with self.assertRaises(ValueError):self.prepare(report,evidence,manifest,dict(args,start_gate=gate))
        gate['coordinate_space']='WATER_PLANE_METRES'
        context=self.prepare(report,evidence,manifest,dict(args,start_gate=gate))
        self.assertEqual(context['measurement_parameters']['start_gate']['coordinate_space'],'WATER_PLANE_METRES')

    def test_synthetic_reports_never_gain_live_eligibility_from_supplied_calibration(self):
        report,evidence,manifest,args=physical_fixture()
        report['source'].update(kind='SYNTHETIC_TEST',identity_status='SYNTHETIC');report['dataset_status']='SYNTHETIC_ONLY'
        report=reseal(report);manifest.update(report_sha256=report['report_sha256'],dataset_status='SYNTHETIC_ONLY')
        manifest=seal_calibration(manifest);evidence['report_sha256']=report['report_sha256']
        evidence['comparisons']['straight']['calibration_evidence_sha256']=manifest['calibration_sha256']
        context=self.prepare(report,seal_evidence(evidence),manifest,args)
        self.assertFalse(context['eligible_for_research']);self.assertEqual(context['missing_reasons'],['SYNTHETIC_ONLY'])


    def test_comparison_cannot_omit_high_error_interior_samples_used_by_measurement(self):
        from tests.test_boat_video_calibration import frame_hash
        report,evidence,manifest,args=physical_fixture()
        tracking=report['tracking']
        for track in tracking['tracks'][:2]:
            for row in track['samples']:
                row['frame_index']*=2;row['frame_sha256']=frame_hash(row['frame_index'])
            original=deepcopy(track['samples']);expanded=[]
            for first,second in zip(original,original[1:]):
                expanded.append(first)
                middle=deepcopy(first);middle.update(frame_index=first['frame_index']+1,
                    frame_sha256=frame_hash(first['frame_index']+1),t=(first['frame_index']+1)/20,
                    x=(first['x']+second['x'])/2,position_error=3.4)
                expanded.append(middle)
            expanded.append(original[-1]);track['samples']=expanded
        tracking['quality']['camera_estimates']=[dict({'frame_index':i,'t':i/20,
            'status':'REFERENCE_INITIALIZATION' if i==0 else 'ACCEPTED'},
            **({} if i==0 else {'homography_previous_to_current':[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]}))
            for i in range(27)]
        tracking['quality']['identity_observations']=[{'frame_index':i,'t':i/20,'scene':0,
            'decoded_frame_sha256':frame_hash(i)} for i in range(27)]
        frames=[]
        for track in tracking['tracks'][:2]:
            for sample in track['samples']:
                row=deepcopy(manifest['frames'][0]);row.update(frame_index=sample['frame_index'],
                    decoded_frame_sha256=sample['frame_sha256']);frames.append(row)
        manifest['frames']=frames
        report['measurements']=measure_tracks(tracking['tracks'],coordinate_space='REFERENCE_IMAGE_PX',phase_windows=WINDOWS)
        report=reseal(report);manifest.update(source_tracking_sha256=digest(tracking),report_sha256=report['report_sha256'])
        manifest=seal_calibration(manifest);evidence['report_sha256']=report['report_sha256']
        evidence['comparisons']['straight']['calibration_evidence_sha256']=manifest['calibration_sha256']
        for lane in [1,2]:
            identity=evidence['identities'][lane-1];identity['track_sha256']=digest(tracking['tracks'][lane-1])
            identity['frames'][0]['frame_index']*=2
            identity['frames'][0]['frame_sha256']=frame_hash(identity['frames'][0]['frame_index'])
            window=evidence['comparisons']['straight']['lanes'][str(lane)]
            window['frame_indices']=[i*2 for i in window['frame_indices']]
        # All five rows support a measured phase. The comparison names only
        # three low-error rows, while those endpoints still exactly match.
        from race_ai.boat_video_calibration import measure_calibrated_tracks
        actual=measure_calibrated_tracks(tracking,manifest,phase_windows=WINDOWS)
        for lane in actual['measurements']['lanes'][:2]:
            self.assertEqual(lane['phases']['straight']['status'],'MEASURED')
            self.assertEqual(lane['phases']['straight']['sample_count'],5)
        context=self.prepare(report,seal_evidence(evidence),manifest,args)
        for participant in context['participants'][:2]:
            cell=participant['feature_cells']['straight_mean_speed']
            self.assertIsNone(cell['value'])
            self.assertEqual(cell['missing_reason'],'PER_BOAT_PHASE_WINDOW_MISMATCH')
        self.assertFalse(context['eligible_for_research'])
        # Naming every used row admits the genuine large supplied error bound;
        # the difference between lanes is then unresolved by video_vectors.
        for lane in [1,2]:
            evidence['comparisons']['straight']['lanes'][str(lane)]['frame_indices']=[
                row['frame_index'] for row in tracking['tracks'][lane-1]['samples']]
        complete=self.prepare(report,seal_evidence(evidence),manifest,args)
        first,second=[r['feature_cells']['straight_mean_speed'] for r in complete['participants'][:2]]
        self.assertGreater(first['uncertainty'],9.6);self.assertGreater(second['uncertainty'],9.6)
        self.assertLess(second['value']-first['value'],first['uncertainty']+second['uncertainty'])


    def turn_fixture(self,near_straight):
        report,evidence,manifest,args=physical_fixture()
        windows={'1':{'turn':[.1,.3]},'2':{'turn':[1.1,1.3]}}
        for lane in [1,2]:
            samples=report['tracking']['tracks'][lane-1]['samples']
            for i,row in enumerate(samples):
                row['y']=40.+lane+(.001*lane*i*i if near_straight else (10. if i==1 else 0.))
        report['analysis_parameters']={'phase_windows':deepcopy(windows)}
        report['measurements']=measure_tracks(report['tracking']['tracks'],coordinate_space='REFERENCE_IMAGE_PX',phase_windows=windows)
        report=reseal(report);manifest.update(source_tracking_sha256=digest(report['tracking']),report_sha256=report['report_sha256'])
        manifest=seal_calibration(manifest);evidence['report_sha256']=report['report_sha256']
        comparison=evidence['comparisons'].pop('straight');evidence['comparisons']['turn']=comparison
        comparison['comparison_id']='fictional-sequential-turn';comparison['calibration_evidence_sha256']=manifest['calibration_sha256']
        for lane in [1,2]:
            comparison['lanes'][str(lane)]['uncertainty']=0.
            evidence['identities'][lane-1]['track_sha256']=digest(report['tracking']['tracks'][lane-1])
        args['phase_windows']=windows
        return report,seal_evidence(evidence),manifest,args

    def test_near_straight_turn_radius_cannot_erase_known_position_uncertainty(self):
        report,evidence,manifest,args=self.turn_fixture(True)
        from race_ai.boat_video_calibration import measure_calibrated_tracks
        actual=measure_calibrated_tracks(report['tracking'],manifest,phase_windows=args['phase_windows'])
        for lane in actual['measurements']['lanes'][:2]:self.assertEqual(lane['phases']['turn']['status'],'MEASURED')
        # Perturbing the middle pixel by .001/.002, inside supplied .01px,
        # makes either curve straight; its nonzero heading is unresolved.
        for track in report['tracking']['tracks'][:2]:
            points=track['samples'];offset=(points[0]['y']+points[2]['y'])/2-points[1]['y']
            self.assertLess(abs(offset),points[1]['position_error'])
        context=self.prepare(report,evidence,manifest,args)
        for participant in context['participants'][:2]:
            cell=participant['feature_cells']['turn_sampled_radius']
            self.assertIsNone(cell['value']);self.assertEqual(cell['missing_reason'],'TURN_HEADING_UNCERTAINTY_UNRESOLVED')
        self.assertFalse(context['eligible_for_research'])

    def test_resolved_turn_radius_has_nonzero_conservative_supplied_error_bound(self):
        from itertools import product
        report,evidence,manifest,args=self.turn_fixture(False)
        context=self.prepare(report,evidence,manifest,args)
        from race_ai.boat_video_calibration import calibrate_tracks
        calibrated=calibrate_tracks(report['tracking'],manifest)
        for lane in [1,2]:
            cell=context['participants'][lane-1]['feature_cells']['turn_sampled_radius']
            self.assertIsNotNone(cell['value']);self.assertGreater(cell['uncertainty'],0.)
            track=calibrated['tracks'][lane-1]
            for angles in product([0.,1.5707963267948966,3.141592653589793,4.71238898038469],repeat=3):
                moved=deepcopy(track)
                import math
                for row,angle in zip(moved['samples'],angles):
                    error=row['position_error'];row['x']+=error*math.cos(angle);row['y']+=error*math.sin(angle)
                result=measure_tracks([moved],coordinate_space='WATER_PLANE_METRES',
                    phase_windows={str(lane):args['phase_windows'][str(lane)]},
                    calibration_evidence=calibrated['calibration_evidence'])
                turn=result['lanes'][0]['phases']['turn']
                self.assertEqual(turn['status'],'MEASURED')
                radius=next(m['value'] for m in turn['metrics'] if m['name']=='equivalent_sampled_radius')
                self.assertLessEqual(abs(radius-cell['value']),cell['uncertainty']+1e-12)


if __name__=='__main__':unittest.main()
