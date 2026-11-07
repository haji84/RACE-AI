import copy
import importlib.util
import math
import unittest
from datetime import datetime, timezone

SPEC = importlib.util.find_spec('race_ai.horse_history_features')
if SPEC:
    from race_ai.horse_history_features import derive, fit_reference, build_snapshot, summarize_suite, quote_ev

AT='2030-10-01T12:00:00+09:00'


def row(i=1, **kw):
    out={'race_id':f'past-{i}', 'horse_id':'H1', 'event_date':f'2030-0{i}-01',
         'venue':'Tokyo','surface':'turf','distance_m':1400,'field_size':10,
         'finish_position':i, 'status':'FINISHED', 'elapsed_seconds':80.0+i,
         'last3f_seconds':34.0+i/10,'last3f_rank':i,
         'first_corner_position':i, 'last_corner_position':i+1,
         'start_incident': False, 'jockey_id':'J1',
         'source_ref':f'fixture://past-{i}', 'captured_at':'2030-09-30T12:00:00+09:00',
         'published_at':None, 'source_rights_ref':'fixture-only'}
    out.update(kw)
    return out

def target(**kw):
    t={'horse_id':'H1', 'venue':'Tokyo','surface':'turf','distance_m':1400,'jockey_id':'J1'}
    t.update(kw)
    return t

def refs():
    return [row(1, horse_id='TRAIN1', event_date='2029-01-01', race_id='train-1', captured_at='2029-11-30T00:00:00+09:00'),
            row(2, horse_id='TRAIN2', event_date='2029-02-01', race_id='train-2', captured_at='2029-11-30T00:00:00+09:00')]

class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SPEC, 'The raw-history conversion implementation is absent')

    def test_finished_field_relative_performance_and_recent_weighting(self):
        out=derive([row(1),row(2)],target(),as_of=AT)
        self.assertAlmostEqual(out['features']['ability']['value'],17/18)
        self.assertAlmostEqual(out['features']['recent_form']['value'],(2*(8/9)+1)/3)

    def test_evidence_is_derived_now_not_forged_original_publication(self):
        out=derive([row()],target(),as_of=AT)
        ev=out['features']['ability']
        self.assertEqual(ev['published_at'],AT)
        self.assertEqual(ev['captured_at'],AT)
        self.assertIsNone(out['lineage'][ev['source_ref']][0]['published_at'])
        self.assertEqual(out['method_status'],'UNVALIDATED_RESEARCH_TRANSFORM')

    def test_every_native_required_feature_has_a_formula(self):
        rows=[row(1),row(2, first_corner_position=9)]
        ref=fit_reference(refs(), fitted_at='2029-12-01T00:00:00+09:00',
                          data_captured_at='2029-11-30T00:00:00+09:00',
                          allow_source=lambda *x: True, scope='SYNTHETIC_ONLY')
        out=derive(rows,target(),as_of=AT,reference=ref,scope='SYNTHETIC_ONLY')
        self.assertEqual(len(out['features']),12)
        self.assertEqual(out['missing'],{})
        self.assertTrue(all(0<=v['value']<=1 for v in out['features'].values()))

    def test_single_start_consistency_and_adaptability_stay_missing(self):
        out=derive([row()],target(),as_of=AT)
        self.assertNotIn('consistency',out['features'])
        self.assertNotIn('tactical_adaptability',out['features'])

    def test_unknown_start_and_sections_are_not_zero_or_neutral(self):
        r=row(); [r.pop(k) for k in ['start_incident','last_corner_position','last3f_seconds','last3f_rank']]
        out=derive([r],target(),as_of=AT)
        for f in ['start_reliability','finishing_power','closing_sectional']:
            self.assertNotIn(f,out['features'])
            self.assertIn(f,out['missing'])

    def test_course_and_jockey_without_matching_samples_stay_missing(self):
        out=derive([row()],target(venue='Kyoto',jockey_id=None),as_of=AT)
        self.assertNotIn('course_compatibility',out['features'])
        self.assertNotIn('jockey_fit',out['features'])

    def test_out_of_distance_stamina_is_not_inferred(self):
        out=derive([row(distance_m=1200)],target(distance_m=2500),as_of=AT)
        self.assertNotIn('stamina',out['features'])
        self.assertNotIn('distance_surface_fit',out['features'])

    def test_target_and_future_history_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'future|as_of'):
            derive([row(event_date='2030-10-02')],target(),as_of=AT)

    def test_capture_after_asof_rejected(self):
        with self.assertRaisesRegex(ValueError,'capture'):
            derive([row(captured_at='2031-01-01T00:00:00+09:00')],target(),as_of=AT)

    def test_duplicate_history_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            derive([row(),row()],target(),as_of=AT)

    def test_different_horse_and_result_bounds_rejected(self):
        for r in [row(horse_id='WRONG'),row(finish_position=11),row(field_size=1),row(finish_position=True)]:
            with self.subTest(r=r), self.assertRaises(ValueError):
                derive([r],target(),as_of=AT)

    def test_missing_elapsed_never_uses_index_as_speed(self):
        r=row();r.pop('elapsed_seconds');r['published_external_index']=99
        out=derive([r],target(),as_of=AT)
        self.assertNotIn('speed_figure',out['features'])

    def test_withdrawal_not_counted_as_bad_performance(self):
        rows=[row(),row(2,status='WITHDRAWN',finish_position=None)]
        out=derive(rows,target(),as_of=AT)
        self.assertEqual(out['features']['ability']['value'],1)
        self.assertEqual(out['features']['ability']['sample_n'],1)

    def test_unfinished_record_is_not_coerced_into_a_finish(self):
        out=derive([row(status='DNF',finish_position=None)],target(),as_of=AT)
        self.assertNotIn('ability',out['features'])
        self.assertEqual(out['nonfinish_count'],1)

    def test_reference_fit_cannot_include_future_or_real_without_authority(self):
        with self.assertRaises(ValueError):
            fit_reference(refs(),fitted_at='2028-01-01T00:00:00+09:00',data_captured_at='2027-01-01T00:00:00+09:00',scope='SYNTHETIC_ONLY')
        with self.assertRaisesRegex(ValueError,'author'):
            fit_reference(refs(),fitted_at='2030-01-01T00:00:00+09:00',data_captured_at='2029-12-01T00:00:00+09:00')

    def test_source_observations_must_be_available_when_reference_was_fitted(self):
        bad=refs();bad[0]['captured_at']='2030-01-02T00:00:00+09:00'
        with self.assertRaisesRegex(ValueError,'capture'):
            fit_reference(bad,fitted_at='2029-12-01T00:00:00+09:00',data_captured_at='2029-11-30T00:00:00+09:00',scope='SYNTHETIC_ONLY')

    def test_synthetic_reference_cannot_enter_real_data_derivation(self):
        ref=fit_reference(refs(),fitted_at='2029-12-01T00:00:00+09:00',data_captured_at='2029-11-30T00:00:00+09:00',scope='SYNTHETIC_ONLY')
        with self.assertRaisesRegex(ValueError,'scope'):
            derive([row()],target(),as_of=AT,reference=ref)

    def test_auxiliary_section_source_survives_feature_lineage(self):
        r=row(sectional_source_ref='fixture://separate-official-result')
        out=derive([r],target(),as_of=AT)
        ref=out['features']['finishing_power']['source_ref']
        self.assertIn('fixture://separate-official-result',str(out['lineage'][ref]))

    def test_derive_does_not_mutate_history(self):
        rows=[row()]; before=copy.deepcopy(rows)
        derive(rows,target(),as_of=AT)
        self.assertEqual(rows,before)

    def test_snapshot_refuses_missing_features_draw_and_surface_mismatch(self):
        out=derive([row()],target(),as_of=AT)
        with self.assertRaises(ValueError):
            build_snapshot({},[{'horse_id':'H1','report':out}],{},as_of=AT)

    def test_ev_requires_real_odds_and_calibrated_probability(self):
        with self.assertRaisesRegex(ValueError,'calibr'):
            quote_ev(.1,12,calibrated=False)
        self.assertAlmostEqual(quote_ev(.1,12,calibrated=True)['net_return_per_unit'],.2)
        for q in [None,0,float('nan')]:
            with self.assertRaises(ValueError):quote_ev(.1,q,calibrated=True)

if __name__=='__main__': unittest.main()
