"""Invented encrypted grids -> unchanged existing model contracts; no live claim."""
from copy import deepcopy
import hashlib,json
import unittest
from unittest.mock import patch
from tests import test_boat_venue_history_handoff as history_fixture
from tests.test_boat_observed_pairwise_models import fixture

class VenueFeatureTests(unittest.TestCase):
    setUp=history_fixture.HandoffTests.setUp
    collection=history_fixture.HandoffTests.collection
    def dataset(self,*,partial=False,raw=None):
        from race_ai.boat_venue_dataset import build_dataset,PREFIX
        root=self.collection(raw=raw,day='2026-11-04' if partial else '2026-11-01');out=self.root/'grid'
        with patch('race_ai.boat_venue_dataset._now',return_value='2030-01-02T00:00:00Z'):
            build_dataset(root,out,roster=['4999'],end='2026-11-04' if partial else '2026-11-01')
        sha=hashlib.sha256((out/'dataset.json').read_bytes()).hexdigest()
        pointer=dict(schema='RACE_AI_BOAT_VENUE_DATASET_INPUT_V1',status='READY',repository_id='1416489937',source_commit='a'*40,
            dataset_sha256=sha,dataset_path=PREFIX+'datasets/'+sha+'/dataset.json')
        snapshot=fixture(all_missing=True,research=True);snapshot.update(venue='boatrace-jcd-17',race_id='boat:2030-04-01:boatrace-jcd-17:1')
        return out,pointer,snapshot

    def test_real_shaped_six_racer_grid_contract_to_both_existing_models(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from race_ai.boat_observed_pairwise_models import predict_pair
        out,pointer,snapshot=self.dataset();before=deepcopy(snapshot)
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        self.assertEqual(snapshot,before)
        self.assertEqual(r['course_st_participants'],6)
        self.assertAlmostEqual(r['snapshot']['participants'][0]['features']['course_mean_st']['value'],.12)
        self.assertEqual(r['snapshot']['participants'][0]['features']['course_mean_st']['sample_n'],2)
        models=predict_pair(r['snapshot'],allow_source=lambda *a:True)
        self.assertEqual(len(models['models']),2);self.assertFalse(r['actual_entry_course_inferred'])
        with self.assertRaises(ValueError):enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z')

    def test_partial_source_withholds_features_and_late_dataset_or_bad_pin_is_rejected(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        out,pointer,snapshot=self.dataset(partial=True)
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        self.assertEqual(r['course_st_participants'],0)
        self.assertTrue(all(p['missing']['course_mean_st']=='SOURCE_UNAVAILABLE' for p in r['snapshot']['participants']))
        for key,value in [('dataset_sha256','f'*64),('source_commit','../invalid')]:
            with self.assertRaises(ValueError):enrich_venue_snapshot(snapshot,out,dict(pointer,**{key:value}),verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        snapshot['as_of']='2029-01-01T00:00:00Z'
        with self.assertRaises(ValueError):enrich_venue_snapshot(snapshot,out,pointer,verified_at='2028-12-31T00:00:00Z',allow_source=lambda *a:True)

    def test_explicit_observed_only_research_retains_incomplete_coverage_and_real_denominators(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from race_ai.boat_observed_pairwise_models import predict_pair
        out,pointer,snapshot=self.dataset(partial=True)
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True,observed_only=True)
        self.assertEqual(r['course_st_participants'],6)
        self.assertFalse(r['source_coverage_complete']);self.assertTrue(r['observed_only'])
        p=r['snapshot']['participants'][0]['features']['course_mean_st']
        self.assertEqual((p['sample_n'],p['history']['total_n']),(2,2))
        self.assertIn('observed-published-files-only',p['history']['window_id'])
        self.assertFalse(r['venue_evidence']['4001']['profile']['history_completeness'])
        self.assertEqual(len(predict_pair(r['snapshot'],allow_source=lambda *a:True)['models']),2)

    def test_unknown_historical_course_is_not_assumed_outside_frame_condition(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from tests.test_official_k_special_blocks import packet
        from tests.test_boat_entry_observations import uncompressed_lzh
        body=packet(late=True).replace(b'2030/01/01',b'2026/11/01').replace(b'01KBGN',b'17KBGN').replace(b'01KEND',b'17KEND')
        out,pointer,snapshot=self.dataset(raw=uncompressed_lzh(body,'K261101.TXT'))
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        p=r['snapshot']['participants'][5]
        self.assertEqual(p['missing']['course_mean_st'],'NO_VERIFIED_COURSE')
        self.assertNotIn('course_mean_st',p['features'])
        observed=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True,observed_only=True)
        self.assertEqual(observed['course_st_participants'],5)
        self.assertNotIn('course_mean_st',observed['snapshot']['participants'][5]['features'])
        self.assertEqual(observed['venue_evidence']['4006']['unknown_course_rows_excluded_without_membership_inference'],1)

    def test_tied_finish_is_not_supplied_as_an_ordinary_finish_mean(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from tests.test_official_k_special_blocks import packet
        from tests.test_boat_entry_observations import uncompressed_lzh
        body=packet().replace(b'2030/01/01',b'2026/11/01').replace(b'01KBGN',b'17KBGN').replace(b'01KEND',b'17KEND').replace(b'02 2 4002',b'01 2 4002')
        out,pointer,snapshot=self.dataset(raw=uncompressed_lzh(body,'K261101.TXT'))
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        self.assertEqual(r['course_st_participants'],6)
        self.assertTrue(all(p['missing']['course_mean_finish']=='UNRESOLVED_DISPOSITION' for p in r['snapshot']['participants']))

    def test_finish_f_does_not_reclassify_missing_st_as_observed_f_timing(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from tests.test_boat_entry_observations import daily_pair,uncompressed_lzh
        _,body=daily_pair()
        body=body.replace(b'2026/11/04',b'2026/11/01').replace(
            b'01 1 4001 TEST 55 33 6.80 1 0.12 1.50.4',
            b'F 1 4001 TEST 55 33 6.80 1 -- 1.50.4')
        out,pointer,snapshot=self.dataset(raw=uncompressed_lzh(body,'K261101.TXT'))
        r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        h=r['snapshot']['participants'][0]['features']['course_mean_st']['history']
        self.assertEqual((h['total_n'],h['ok_n'],h['f_n'],h['l_n'],h['missing_n']),(2,1,0,0,1))

    def test_legacy_grid_without_st_status_counts_withholds_st_feature(self):
        from race_ai.boat_venue_feature_adapter import enrich_venue_snapshot
        from race_ai.boat_venue_dataset import lookup
        out,pointer,snapshot=self.dataset()
        def legacy(*args,**kwargs):
            p=lookup(*args,**kwargs)
            for b in p['by_actual_course'].values():b.pop('st_status_counts',None)
            return p
        with patch('race_ai.boat_venue_feature_adapter.lookup',side_effect=legacy):
            r=enrich_venue_snapshot(snapshot,out,pointer,verified_at='2030-04-01T01:40:00Z',allow_source=lambda *a:True)
        self.assertEqual(r['course_st_participants'],0)
        self.assertTrue(all(p['missing']['course_mean_st']=='UNRESOLVED_DISPOSITION' for p in r['snapshot']['participants']))
