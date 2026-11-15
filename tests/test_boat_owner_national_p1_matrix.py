"""National BOAT P1 audit from already authenticated count-only evidence.

No source traffic, AES secrets, model inference, or private race identities.
"""
from copy import deepcopy
import json
import unittest

from scripts.boat_owner_national_p1_matrix import calculate

IDS=['boat-A','boat-B','boat-C']
DAY='2030-04-01'


def fixture():
    return dict(schema='RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1',
        day_jst=DAY, owner_run_id=987654321, owner_conclusion='success',
        official_program_verified=True,scheduled_races=4,retained_schedule_rows=4,
        baseline_p0_races=4,baseline_p1_races=4,
        baseline_p1_unique_model_slots=12,p1_schedule_cutoff_conflict_races=0,
        p0_models={'boat-A':4},p1_models={m:4 for m in IDS},
        verified_video_prediction_rows=0,
        official_source_requests=0,originals_changed=False,successor_dispatch_allowed=False,
        source_control=dict(completed_round=24,prepared_round=None))


class ActualReaderMatrixTests(unittest.TestCase):
    def test_all_4_races_3_models_counts_complete_only_after_original_reader(self):
        doc=fixture()
        no=calculate(doc,IDS)
        self.assertEqual(no['status'],'HOLD_SOURCE_OR_INDEPENDENT_READBACK')
        self.assertFalse(no['all_expected_models_p1_readback_proven'])
        yes=calculate(doc,IDS,independent_original_reader=True)
        self.assertEqual(yes['status'],'INDEPENDENT_P1_MODEL_MATRIX_PRESENT')
        self.assertEqual(yes['expected_p1_model_slots'],12)
        self.assertEqual(yes['p1_saved_expected_slots'],12)
        self.assertEqual(yes['missing_p1_model_slots'],0)
        self.assertFalse(yes['full_e2e_website_proven'])

    def test_one_missing_model_slot_is_not_hidden_by_other_successful_models(self):
        doc=fixture();doc['p1_models']['boat-C']=3
        doc['baseline_p1_unique_model_slots']=11
        yes=calculate(doc,IDS,independent_original_reader=True)
        self.assertEqual(yes['missing_p1_model_slots'],1)
        self.assertFalse(yes['all_expected_models_p1_readback_proven'])
        self.assertEqual([x for x in yes['by_model'] if x['model_id']=='boat-C'][0]['missing_races'],1)

    def test_existing_p1_in_some_races_never_counts_as_full_coverage(self):
        doc=fixture();doc['baseline_p1_races']=3
        doc['p1_models']={'boat-A':3,'boat-B':3,'boat-C':3}
        doc['baseline_p1_unique_model_slots']=9
        value=calculate(doc,IDS,independent_original_reader=True)
        self.assertEqual(value['missing_p1_model_slots'],3)
        self.assertFalse(value['all_expected_models_p1_readback_proven'])

    def test_incomplete_official_schedule_stays_hold_with_real_receipts(self):
        doc=fixture();doc['official_program_verified']=False;doc['scheduled_races']=None
        value=calculate(doc,IDS,independent_original_reader=True)
        self.assertIsNone(value['scheduled_races'])
        self.assertFalse(value['all_expected_models_p1_readback_proven'])

    def test_failed_worker_and_source_cutoff_conflict_stay_hold(self):
        for change in (dict(owner_conclusion='failure'),
                       dict(p1_schedule_cutoff_conflict_races=1)):
            with self.subTest(change=change):
                doc=dict(fixture(),**change)
                value=calculate(doc,IDS,independent_original_reader=True)
                self.assertFalse(value['all_expected_models_p1_readback_proven'])

    def test_unknown_model_never_spoofs_a_required_model(self):
        doc=fixture()
        doc['p1_models']['unknown-X']=4
        doc['baseline_p1_unique_model_slots']=16
        result=calculate(doc,IDS,independent_original_reader=True)
        self.assertEqual(result['unrecognized_p1_model_count'],1)
        self.assertFalse(result['all_expected_models_p1_readback_proven'])

    def test_duplicate_unverified_slot_counts_and_control_conflicts_refuse(self):
        for change in (
            lambda doc:doc.update(baseline_p1_unique_model_slots=100),
            lambda doc:doc['p1_models'].update({'boat-A':5}),
            lambda doc:doc['source_control'].update(prepared_round=25),
            lambda doc:doc.update(official_source_requests=10),
            lambda doc:doc.update(originals_changed=True),
        ):
            doc=fixture();change(doc)
            with self.subTest(change=change),self.assertRaises(ValueError):
                calculate(doc,IDS,independent_original_reader=True)

    def test_private_original_never_becomes_report_or_public_video(self):
        doc=fixture();doc['private_athlete_name']='NOT_FOR_LOG';doc['raw_video']='NOT_FOR_LOG'
        result=calculate(doc,IDS,independent_original_reader=True)
        dumped=json.dumps(result,sort_keys=True)
        self.assertNotIn('NOT_FOR_LOG',dumped)
        self.assertEqual(result['racing_provider_gets'],0)
        self.assertTrue(result['original_forecasts_unchanged'])
        self.assertFalse(result['public_video_usable'])


if __name__=='__main__':
    unittest.main()
