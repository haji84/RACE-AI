"""Invented frozen P0 originals; no real sources, keys, Actions or accuracy claim."""
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
import importlib
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.boat_observed_pairwise_models import predict_pair, MODEL_IDS as OBSERVED
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_boat_all_model_cycle import fitted_ranker, receipt
from tests.test_frozen_day_cycle import sample


NOW=datetime.fromisoformat('2030-04-01T01:44:00+00:00')


@lru_cache(maxsize=1)
def fitted_nine_training():
    """Fit invented eight-race originals through the actual nine native cells."""
    from race_ai.all_existing_model_derivation import derive_records
    from race_ai.all_existing_model_learning import fit
    from tests.test_all_existing_model_learning import observed_records
    from tests.test_observed_weight_learning import NOW as CREATED
    original=observed_records(synthetic=False)
    derived=derive_records(original,now=CREATED,include_groups=('shared','boat_full','shared_learned'))
    return fit(original+derived,now=CREATED,allow_source=lambda *a:True,allow_training=lambda *a:True)


class FutureP0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline=fitted_ranker()

    def helper(self):
        return importlib.import_module('race_ai.all_existing_model_future_p0').build_future_p0_requests

    def source(self):
        document,_,_=sample()
        return document,receipt(document,artifact=99,saved='2030-04-01T01:43:00Z')

    def test_nine_p0_requests_use_new_clock_and_keep_original_observation_hashes_and_clocks(self):
        document,proof=self.source();original=deepcopy((document,proof,self.baseline))
        out=self.helper()(document,proof,now=NOW,baseline_ranker=self.baseline)
        self.assertEqual(len(out['requests']),9)
        self.assertEqual(out['race_id'],'20300401-01-01')
        self.assertEqual(out['cutoff_at'],'2030-04-01T10:59:00+09:00')
        for request in out['requests']:
            mid=request['cell_key'][5:];native=request['native_payload']
            info=registry.identity(mid,'boat',native)
            self.assertEqual(info['stage'],'P0')
            self.assertEqual(datetime.fromisoformat(info['as_of']),NOW)
            forecast=registry.predict(mid,'boat',native,at=NOW,allow_source=lambda *a:True)
            self.assertEqual(len(registry.normalize(mid,'boat',native,forecast)['ranked']),120)
            if mid in OBSERVED:
                self.assertEqual(native['snapshot']['sources'],document['predictions'][0]['source_evidence'])
                self.assertTrue(all('exhibition_time_seconds' not in p['features'] for p in native['snapshot']['participants']))
        self.assertEqual((document,proof,self.baseline),original)
        self.assertIs(out['source_audit']['new_payload_saved_by_original_receipt'],False)
        self.assertEqual(out['source_audit']['new_payload_as_of'],NOW.isoformat())
        self.assertEqual(out['source_audit']['original_receipt'],proof)
        self.assertIs(out['summary']['independent_pre_cutoff_receipt_verified'],False)

    def test_earliest_race_with_ten_minutes_remaining_is_selected_and_late_races_hold(self):
        document,proof=self.source()
        later=fixture(research=True);later['race_id']='boat:2030-04-01:boatrace-jcd-01:2'
        later['sales_cutoff_at']='2030-04-01T11:15:00+09:00'
        document['predictions'].insert(0,predict_pair(later,allow_source=lambda *a:True))
        document.update(race_count=2,model_forecast_count=4)
        proof=receipt(document,artifact=99,saved='2030-04-01T01:43:00Z')
        out=self.helper()(document,proof,now=NOW,baseline_ranker=self.baseline)
        self.assertEqual(out['race_id'],'20300401-01-01')
        out=self.helper()(document,proof,now=NOW+timedelta(minutes=6),baseline_ranker=self.baseline)
        self.assertEqual(out['race_id'],'20300401-01-02')
        out=self.helper()(document,proof,now=NOW+timedelta(hours=1),baseline_ranker=self.baseline)
        self.assertEqual(out['requests'],[])
        self.assertIn('HOLD',out['state'])

    def test_unverified_or_tampered_original_and_wrong_event_day_are_rejected(self):
        for mutate in (lambda d,r:r.update(independently_verified=False),
                       lambda d,r:d['predictions'][0].update(snapshot_sha256='f'*64),
                       lambda d,r:r.update(payload_sha256='f'*64)):
            document,proof=self.source();mutate(document,proof)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):
                self.helper()(document,proof,now=NOW,baseline_ranker=self.baseline)
        document,proof=self.source()
        out=self.helper()(document,proof,now=NOW+timedelta(days=1),baseline_ranker=self.baseline)
        self.assertEqual(out['requests'],[])

    def test_missing_future_or_wrong_schema_baseline_ranker_cannot_silently_replace_the_baseline(self):
        document,proof=self.source()
        for index,model in enumerate((None,dict(self.baseline,created_at='2031-01-01T00:00:00Z'),
                      dict(self.baseline,input_schema='RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1'))):
            with self.subTest(index=index),self.assertRaises(ValueError):
                self.helper()(document,proof,now=NOW,baseline_ranker=model)

    def test_partial_venue_inputs_or_unadmitted_source_callback_do_not_issue_requests(self):
        document,proof=self.source()
        with self.assertRaises(ValueError):
            self.helper()(document,proof,now=NOW,baseline_ranker=self.baseline,dataset_pointer={})
        with self.assertRaises(ValueError):
            self.helper()(document,proof,now=NOW,baseline_ranker=self.baseline,allow_source=lambda *a:False)

    def test_actual_nine_cell_candidate_generates_all_native_future_pairs(self):
        from race_ai.all_existing_model_learning import forecast_pair
        import json
        snapshot=json.loads(json.dumps(fixture(research=True)).replace('2030-04-01','2030-04-02'))
        document,_,_=sample();document.update(day_jst='2030-04-02',predictions=[predict_pair(snapshot,allow_source=lambda *a:True)],
            schedule=[dict(race_id='20300402-01-01',cutoff_at=snapshot['sales_cutoff_at'])])
        proof=receipt(document,artifact=100,saved='2030-04-02T01:43:00Z')
        now=NOW+timedelta(days=1);training=fitted_nine_training()
        self.assertEqual(len(training['models']),9)
        out=self.helper()(document,proof,now=now,baseline_ranker=self.baseline,training=training)
        for request in out['requests']:
            pair=forecast_pair(training,request['cell_key'],request['native_payload'],now=now,allow_source=lambda *a:True)
            self.assertEqual(pair['stage'],'P0')
            self.assertEqual(pair['as_of'],now.isoformat())
            self.assertEqual(len(pair['baseline_normalized']['ranked']),120)
            self.assertEqual(len(pair['learned_normalized']['ranked']),120)
            self.assertFalse(pair['production_promoted'])


if __name__=='__main__':unittest.main()
