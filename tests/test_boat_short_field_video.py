"""Reduced BOAT fields: only official ACTIVE lane identities enter video/P1 research.

All examples are fictional. A missing lane, including hull 1/2, is not a
zero-valued boat; no 3-way bet may contain a withdrawn boat.
"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_video_measurements import measure_tracks
from tests.test_boat_video_model_context import fixture,seal_evidence,AS_OF
from tests.test_boat_video_evaluation import reseal
from race_ai.boat_video_evaluation import _report,_roster,enrich_view
from race_ai.boat_video_model_context import prepare_video_context,validate_video_context
from race_ai.boat_ab_shadow import build_pair

RACE='20300401-01-01'
CUTOFF='2030-04-01T12:00:00+09:00'
ACTIVE_CASES=((1,2,4,5,6),(1,3,5,6),(2,4,6))


def shrink(active):
    report,evidence=fixture()
    selected=set(active)
    report['roster']=[p for p in report['roster'] if p['lane'] in selected]
    report['tracking']['tracks']=[t for t in report['tracking']['tracks'] if t['lane'] in selected]
    parameters=report['analysis_parameters']
    parameters['phase_windows']={str(lane): window for lane,window in parameters['phase_windows'].items()
                                  if int(lane) in selected}
    report['measurements']=measure_tracks(report['tracking']['tracks'],
        coordinate_space='REFERENCE_IMAGE_PX',
        phase_windows=parameters.get('phase_windows'),start_gate=parameters.get('start_gate'),
        max_gap_seconds=parameters.get('max_gap_seconds',.3))
    report=reseal(report)
    evidence['roster']=deepcopy(report['roster'])
    evidence['identities']=[item for item in evidence['identities'] if item['lane'] in selected]
    evidence['report_sha256']=report['report_sha256']
    for phase in evidence['comparisons'].values():
        phase['uncertainty_by_lane']={n:v for n,v in phase['uncertainty_by_lane'].items()
                                    if int(n) in selected}
    return report,seal_evidence(evidence)


class ReducedFieldVideoTests(unittest.TestCase):
    def test_actual_measurement_report_and_sealed_context_support_3_4_5_active_lanes(self):
        for active in ACTIVE_CASES:
            with self.subTest(active=active):
                report,evidence=shrink(active)
                valid=_report(report)
                self.assertEqual(len(valid['roster']),len(active))
                self.assertEqual([x['lane'] for x in valid['tracking']['tracks']],list(active))
                self.assertEqual([x['lane'] for x in valid['measurements']['lanes']],list(active))
                result=prepare_video_context(valid,evidence,race_id=RACE,cutoff_at=CUTOFF,
                    roster=report['roster'],as_of=AS_OF)
                self.assertEqual([x['lane'] for x in result['participants']],list(active))
                self.assertEqual(validate_video_context(result,race_id=RACE,cutoff_at=CUTOFF,
                    roster=report['roster'],as_of=AS_OF),result)
                self.assertTrue(result['eligible_for_research'])
                self.assertFalse(result['prediction_eligible'])
                self.assertFalse(result['production_eligible'])
                self.assertEqual(len(result['participants']),len(active))
                self.assertEqual(len(result['participants'][0]['feature_cells']),4)

    def test_no_evidence_has_active_only_missing_cells_not_fabricated_boats(self):
        report,_=shrink((1,2,4,5,6))
        result=prepare_video_context(report,None,race_id=RACE,cutoff_at=CUTOFF,
                                    roster=report['roster'],as_of=AS_OF)
        self.assertEqual({p['lane'] for p in result['participants']},{1,2,4,5,6})
        self.assertFalse(result['eligible_for_research'])
        for p in result['participants']:
            self.assertTrue(all(cell['value'] is None for cell in p['feature_cells'].values()))
            self.assertTrue(all(cell['missing_reason']=='INDEPENDENT_NUMBER_EVIDENCE_MISSING'
                                for cell in p['feature_cells'].values()))

    def test_withdrawn_lane_in_evidence_or_unmatched_report_is_rejected(self):
        report,evidence=shrink((1,2,4,5,6))
        fake=deepcopy(evidence)
        fake['identities'].append(dict(evidence['identities'][0],lane=3,number=3,registration_number='4203'))
        with self.assertRaises(ValueError):
            prepare_video_context(report,seal_evidence(fake),race_id=RACE,cutoff_at=CUTOFF,
                                  roster=report['roster'],as_of=AS_OF)
        phantom=deepcopy(report)
        phantom['tracking']['tracks'].append(dict(phantom['tracking']['tracks'][0],lane=3))
        with self.assertRaises(ValueError):_report(reseal(phantom))
        duplicate=deepcopy(report)
        duplicate['roster'].append(deepcopy(duplicate['roster'][0]))
        with self.assertRaises(ValueError):_report(reseal(duplicate))
        mismatch=deepcopy(report)
        mismatch['roster'][0]['registration_number']='9999'
        with self.assertRaises(ValueError):
            prepare_video_context(report,evidence,race_id=RACE,cutoff_at=CUTOFF,
                                  roster=mismatch['roster'],as_of=AS_OF)

    def test_insufficient_entrants_and_missing_lane_identification_fail_closed(self):
        report,evidence=shrink((2,4,6))
        tiny=deepcopy(report)
        tiny['roster']=tiny['roster'][:2]
        with self.assertRaises(ValueError):_report(reseal(tiny))
        missing=deepcopy(evidence)
        missing['identities']=missing['identities'][:2]
        with self.assertRaises(ValueError):
            prepare_video_context(report,seal_evidence(missing),race_id=RACE,cutoff_at=CUTOFF,
                                  roster=report['roster'],as_of=AS_OF)

    def test_result_view_only_links_exact_5_boat_registration_list_not_stale_6(self):
        report,_=shrink((1,2,4,5,6))
        base={'event_date_jst':'2030-04-01','records':[{'sport':'boat','race_id':RACE,
            'cutoff_at':CUTOFF,'participants':[{'number':x['lane'],'registration_no':x['registration_number']}
                for x in report['roster']], 'prediction':{'model_id':'unchanged'},
            'saved_cutoff_variants':[CUTOFF],'saved_schedule_cutoff_variants':[CUTOFF]}]}
        joined=enrich_view(base,[report])
        self.assertEqual(len(joined['records'][0]['boat_video_evaluations']),1)
        stale=deepcopy(base);stale['records'][0]['participants'].append(dict(number=3,registration_no='4203'))
        self.assertNotIn('boat_video_evaluations',enrich_view(stale,[report])['records'][0])

    def test_sequential_image_motion_features_follow_short_roster(self):
        from tests.test_boat_video_sequential_context import fixture as sequential_fixture,rebind
        from race_ai.boat_video_sequential_context import (
            prepare_sequential_video_context,validate_sequential_video_context)
        for active in ACTIVE_CASES:
            if not {1,2}<=set(active):
                continue
            with self.subTest(active=active):
                report,evidence,args=sequential_fixture()
                report['roster']=[r for r in report['roster'] if r['lane'] in active]
                report['tracking']['tracks']=[r for r in report['tracking']['tracks'] if r['lane'] in active]
                report['analysis_parameters']['phase_windows']={
                    k:w for k,w in report['analysis_parameters']['phase_windows'].items() if int(k) in active}
                evidence['roster']=deepcopy(report['roster'])
                report,evidence=rebind(report,evidence)
                args['roster']=deepcopy(report['roster'])
                result=prepare_sequential_video_context(report,evidence,**args)
                self.assertEqual([r['lane'] for r in result['participants']],list(active))
                self.assertEqual(validate_sequential_video_context(result,**args),result)
                self.assertFalse(result['production_eligible'])

    def test_physical_geometry_features_follow_short_roster(self):
        from tests.test_boat_video_physical_context import (
            physical_fixture,seal_evidence as seal_physical_evidence)
        from tests.test_boat_video_calibration import seal as seal_calibration
        from race_ai.boat_video_evaluation import _media
        from race_ai.boat_video_physical_context import (
            prepare_physical_video_context,validate_physical_video_context)
        for active in ((1,2,4,5,6),(1,2,4,6),(1,2,6)):
            with self.subTest(active=active):
                report,evidence,manifest,args=physical_fixture()
                report['roster']=[r for r in report['roster'] if r['lane'] in active]
                report['tracking']['tracks']=[r for r in report['tracking']['tracks'] if r['lane'] in active]
                report['media']=_media(report['tracking'])
                report['analysis_parameters']['phase_windows']={
                    k:w for k,w in report['analysis_parameters']['phase_windows'].items() if int(k) in active}
                report['measurements']=measure_tracks(report['tracking']['tracks'],
                    coordinate_space='REFERENCE_IMAGE_PX',
                    phase_windows=report['analysis_parameters']['phase_windows'])
                report=reseal(report)
                manifest.update(report_sha256=report['report_sha256'],
                                source_tracking_sha256=digest(report['tracking']))
                manifest=seal_calibration(manifest)
                evidence['report_sha256']=report['report_sha256']
                evidence['roster']=deepcopy(report['roster'])
                for comparison in evidence['comparisons'].values():
                    comparison['calibration_evidence_sha256']=manifest['calibration_sha256']
                evidence=seal_physical_evidence(evidence)
                args['roster']=deepcopy(report['roster'])
                result=prepare_physical_video_context(report,evidence,manifest,**args)
                self.assertEqual([r['lane'] for r in result['participants']],list(active))
                self.assertEqual(validate_physical_video_context(result,**args),result)
                self.assertFalse(result['production_eligible'])

    def test_existing_video_model_vectors_use_active_3_4_5_only(self):
        from tests.test_boat_observed_pairwise_models import fixture as observed_fixture
        from tests.test_boat_video_learning import as_p1
        from race_ai.boat_video_learning import video_vectors, _supports
        from race_ai.observed_weight_learning import FEATURES as baseline_features
        from race_ai.boat_video_model_context import FEATURE_IDS
        for active in ACTIVE_CASES:
            with self.subTest(active=active):
                snapshot=as_p1(observed_fixture(research=True))
                snapshot['participants']=[p for p in snapshot['participants'] if p['lane'] in active]
                values=video_vectors(snapshot,None)
                self.assertEqual(set(values),set(active))
                self.assertEqual({len(v) for v in values.values()},
                                 {len(baseline_features)+len(FEATURE_IDS)})
                support=_supports([{'vectors':values}])
                self.assertEqual(len(support),len(baseline_features)+len(FEATURE_IDS))
                self.assertEqual(support[-len(FEATURE_IDS):],[0]*len(FEATURE_IDS))
                self.assertTrue(all(v[-4:]==[0.,0.,0.,0.] for v in values.values()))

    def test_actual_experimental_video_models_generate_3_4_5_active_roster_predictions(self):
        from tests.test_boat_video_connection import VideoConnectionTests,controlled_connection
        from race_ai.boat_video_connection import connect_report
        from race_ai.boat_observed_pairwise_models import predict_pair,MODEL_IDS
        VideoConnectionTests.setUpClass()
        for active in ACTIVE_CASES:
            with self.subTest(active=active):
                report,evidence,inputs,old_verifier,instant=controlled_connection(VideoConnectionTests.training)
                active_set=set(active)
                report['roster']=[r for r in report['roster'] if r['lane'] in active_set]
                report['tracking']['tracks']=[r for r in report['tracking']['tracks'] if r['lane'] in active_set]
                params=report['analysis_parameters']
                params['phase_windows']={n:w for n,w in params['phase_windows'].items() if int(n) in active_set}
                report['measurements']=measure_tracks(report['tracking']['tracks'],
                    coordinate_space='REFERENCE_IMAGE_PX',
                    phase_windows=params.get('phase_windows'),start_gate=params.get('start_gate'),
                    max_gap_seconds=params.get('max_gap_seconds',.3))
                report=reseal(report)
                evidence['roster']=deepcopy(report['roster'])
                evidence['identities']=[v for v in evidence['identities'] if v['lane'] in active_set]
                evidence['report_sha256']=report['report_sha256']
                for comparison in evidence['comparisons'].values():
                    comparison['uncertainty_by_lane']={
                        str(n):value for n,value in comparison['uncertainty_by_lane'].items()
                        if int(n) in active_set}
                evidence=seal_evidence(evidence)
                snapshot=inputs['snapshot']
                snapshot['participants']=[p for p in snapshot['participants'] if p['lane'] in active_set]
                inputs['baseline_suite']=predict_pair(snapshot,allow_source=lambda *_:True)
                context=prepare_video_context(report,evidence,race_id=report['race_id'],
                    cutoff_at=report['cutoff_at'],roster=report['roster'],
                    as_of=inputs['video_context']['as_of'])
                self.assertTrue(context['eligible_for_research'])
                inputs['video_context']=context
                receipt=inputs['video_receipt']
                proof=dict(context_sha256=context['context_sha256'],id=receipt['id'],
                           digest=receipt['digest'],created_at=receipt['created_at'])
                def verifier(value,context_sha256,as_of):
                    return deepcopy(proof) if value==receipt and context_sha256==context['context_sha256'] else None
                result=connect_report(report,identity_evidence=evidence,
                    model_inputs=inputs,receipt_verifier=verifier,clock=lambda:instant)
                self.assertEqual(result['status'],'CONNECTED_EXPERIMENTAL')
                self.assertEqual(len(result['shadows']),len(MODEL_IDS))
                from math import perm,isclose,fsum
                for shadow in result['shadows']:
                    self.assertFalse(shadow['production_eligible'])
                    self.assertEqual(shadow['candidate_count'],perm(len(active),3))
                    self.assertEqual(len(shadow['candidates']),perm(len(active),3))
                    self.assertEqual(len(shadow['ordered_top8']),min(8,perm(len(active),3)))
                    self.assertTrue(isclose(fsum(c['score'] for c in shadow['candidates']),1.0,
                                            abs_tol=1e-8))
                    self.assertTrue(all(set(x['combination'])<=active_set for x in shadow['candidates']))

    def test_original_ab_probability_supports_active_3_4_5_without_phantom_permutations(self):
        for active in ACTIVE_CASES:
            with self.subTest(active=active):
                data=dict(race_id=RACE,cutoff_at=CUTOFF,
                    captured_at='2030-04-01T11:45:00+09:00',program_source_sha256='a'*64,
                    beforeinfo_source_sha256='b'*64,
                    boats=[dict(lane=n,racer_id=str(4200+n),national_win_rate=6.5,
                        exhibition_time_seconds=6.7, motor_two_place_rate_percent=39.0)
                           for n in active])
                output=build_pair(data,'2030-04-01T11:47:00+09:00')
                self.assertIsNotNone(output)
                from math import perm,isclose,fsum
                for model in output['models']:
                    self.assertEqual(len(model['full_120']),perm(len(active),3))
                    self.assertEqual(len(model['top8']),min(8,perm(len(active),3)))
                    self.assertTrue(isclose(fsum(r['score'] for r in model['full_120']),1.0,
                                            abs_tol=1e-8))
                    for row in model['full_120']:
                        indices=[int(x) for x in row['ticket'].split('-')]
                        self.assertEqual(len(indices),3)
                        self.assertEqual(len(set(indices)),3)
                        self.assertTrue(set(indices)<=set(active))
                self.assertEqual(output['actual_result_at_forecast_time'],None)


if __name__=='__main__':unittest.main()
