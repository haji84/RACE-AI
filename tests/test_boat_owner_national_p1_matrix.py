"""National BOAT P1 audit from already authenticated count-only evidence.

No source traffic, AES secrets, model inference, or private race identities.
"""
from copy import deepcopy
import json
import unittest
from datetime import datetime,timezone

from scripts.boat_owner_national_p1_matrix import calculate, saved_view_coverage

IDS=['boat-A','boat-B','boat-C']
DAY='2030-04-01'
NOW=datetime(2030,4,2,tzinfo=timezone.utc)


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
    def test_partial_failed_round_retains_actual_control_without_granting_completion(self):
        doc=fixture();doc['owner_conclusion']='failure'
        doc['source_control'].update(completed_round=6,prepared_round=7,
            lifetime_requests=11812,previous_session_requests=70,
            day_start_lifetime_requests=11524,lifetime_completed_rounds=638)
        before=deepcopy(doc)
        report=calculate(doc,IDS,independent_original_reader=True,allow_pending_audit=True)
        self.assertEqual(report['status'],'HOLD_INTERRUPTED_ROUND_PARTIAL_AUDIT')
        self.assertEqual(report['observed_source_control'],doc['source_control'])
        self.assertFalse(report['all_expected_models_p1_readback_proven'])
        self.assertFalse(report['successor_dispatch_allowed'])
        self.assertEqual(doc,before)
        with self.assertRaises(ValueError):calculate(doc,IDS,independent_original_reader=True)
        for change in (dict(prepared_round=8),dict(prepared_round=True),dict(completed_round=-1)):
            bad=deepcopy(doc);bad['source_control'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                calculate(bad,IDS,independent_original_reader=True,allow_pending_audit=True)

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



class SealedViewCoverageTests(unittest.TestCase):
    def test_actual_completion_proof_counts_without_inventing_generated_at(self):
        view,source=self.example()
        source['generated_at']=None
        view['records'][0]['saved_prediction_coverage']={'authenticated-native-fixture':{}}
        original=deepcopy(view)
        # The pure calculator receives an already authenticated reader result.
        proof=dict(status='QUALIFIED_PRE_CUTOFF',as_of=source['as_of'],generated_at=None,
            computation_completed_at='2030-04-01T11:40:03+09:00',
            clock_proof_kind='ACTUAL_NATIVE_CALL_COMPLETION',
            server_saved_at=source['server_saved_at'],cutoff_at=source['cutoff_at'])
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,now=NOW,
                                  native_coverage_reader=lambda *a,**k:proof)
        self.assertEqual(result['p1_qualified_unique_slots'],1)
        self.assertEqual(view,original)
        view['records'][0].pop('saved_prediction_coverage')
        source.update(computation_completed_at=proof['computation_completed_at'],
                      clock_proof_kind=proof['clock_proof_kind'])
        unproven=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,now=NOW)
        self.assertEqual(unproven['p1_qualified_unique_slots'],0)
        source.update(computation_completed_at=proof['computation_completed_at'],
                      clock_proof_kind=proof['clock_proof_kind'])
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,now=NOW)
        self.assertEqual(result['p1_qualified_unique_slots'],0,'unattested clock fields became proof')

    def test_legacy_reused_asof_is_not_generation_proof(self):
        for mid in ('boat-local-start-course-shadow-v0.1-UNTRAINED',
                    'boat-observed-pairwise-factor-v1','boat-observed-pairwise-start-v1'):
            with self.subTest(model=mid):
                view,source=self.example()
                source.update(model_id=mid,dispatch_status='ORIGINAL_REUSED',generated_at=source['as_of'])
                original=deepcopy(view)
                result=saved_view_coverage(view,day=DAY,model_ids=[mid],scheduled_races=1,now=NOW)
                self.assertEqual(result['p1_qualified_unique_slots'],0)
                self.assertEqual(view,original)

    def example(self):
        cutoff='2030-04-01T12:00:00+09:00'
        original=dict(stage='P1',model_id='boat-A',cutoff_at=cutoff,
                      as_of='2030-04-01T11:40:00+09:00',
                      generated_at='2030-04-01T11:40:03+09:00',
                      server_saved_at='2030-04-01T11:41:00+09:00',
                      external_receipt_verified=True,eligible_pre_cutoff=True,
                      artifact_id=123,original_json_sha256='a'*64)
        row=dict(sport='boat',event_date_jst='2030-04-01',
                 race_id='20300401-01-01',cutoff_at=cutoff,
                 prediction=None,comparison_predictions=[original])
        return dict(records=[row]),original

    def test_only_physically_pre_cutoff_owner_originals_count(self):
        view,_=self.example()
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A','boat-B'],
                                   scheduled_races=2,now=NOW)
        self.assertEqual(result['expected_model_slots'],4)
        self.assertEqual(result['p1_qualified_unique_slots'],1)
        self.assertEqual(result['missing_p1_model_slots'],3)
        self.assertEqual(result['saved_view_race_rows'],1)
        self.assertFalse(result['independently_authenticated_source_zip_claim'])

    def test_a_saved_after_cutoff_and_unattested_receipt_do_not_count(self):
        for changes in ({'server_saved_at':'2030-04-01T13:00:00+09:00'},
                        {'external_receipt_verified':False},
                        {'eligible_pre_cutoff':False},
                        {'original_json_sha256':'wrong'}):
            view,source=self.example()
            view['records'][0]['comparison_predictions']=[dict(source,**changes)]
            result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                       scheduled_races=1,now=NOW)
            self.assertEqual(result['p1_qualified_unique_slots'],0)
            self.assertEqual(result['missing_p1_model_slots'],1)

    def test_duplicate_immutable_race_or_changed_day_is_rejected(self):
        view,_=self.example()
        view['records'].append(deepcopy(view['records'][0]))
        with self.assertRaises(ValueError):
            saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                scheduled_races=2,now=NOW)
        view['records'].pop()
        view['records'][0]['race_id']='20300402-01-01'
        with self.assertRaises(ValueError):
            saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                scheduled_races=1,now=NOW)


    def test_missing_official_top_level_cutoff_is_counted_as_hold_not_a_fake_success(self):
        view,_=self.example()
        second=deepcopy(view['records'][0])
        second['race_id']='20300401-01-02'
        second['cutoff_at']=None
        view['records'].append(second)
        report=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                   scheduled_races=2,now=NOW)
        self.assertEqual(report['saved_view_race_rows'],2)
        self.assertEqual(report['p1_qualified_unique_slots'],1)
        self.assertEqual(report['missing_p1_model_slots'],1)
        self.assertEqual(report['excluded_reasons'],
                         {'ROW_OFFICIAL_CUTOFF_MISSING_OR_INVALID':1})
        self.assertNotIn('20300401-01-02',json.dumps(report))

    def test_invalid_or_cross_day_cutoff_never_causes_provisional_readback_success(self):
        for value,reason in ((42,'ROW_OFFICIAL_CUTOFF_MISSING_OR_INVALID'),
                             ('not-a-timestamp','ROW_OFFICIAL_CUTOFF_MISSING_OR_INVALID'),
                             ('2030-04-02T11:00:00+09:00','ROW_OFFICIAL_CUTOFF_OUTSIDE_DAY')):
            with self.subTest(value=value):
                view,_=self.example()
                view['records'][0]['cutoff_at']=value
                counts=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                           scheduled_races=1,now=NOW)
                self.assertEqual(counts['p1_qualified_unique_slots'],0)
                self.assertEqual(counts['missing_p1_model_slots'],1)
                self.assertEqual(counts['excluded_reasons'][reason],1)

    def test_unknown_model_not_promoted_to_coverage(self):
        view,source=self.example()
        view['records'][0]['comparison_predictions'].append(dict(source,model_id='alien-X'))
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],
                                   scheduled_races=1,now=NOW)
        self.assertEqual(result['unsupported_or_extra_models'],1)
        self.assertEqual(result['p1_qualified_unique_slots'],1)
        self.assertNotIn('20300401-01-01',json.dumps(result))

    def test_native_sidecar_counts_are_audit_local_and_legacy_clock_stays_hold(self):
        view, source=self.example()
        source.pop('generated_at');source.pop('eligible_pre_cutoff')
        view['records'][0]['saved_prediction_coverage']={'native-proof':{}}
        original=deepcopy(view)
        proof=dict(status='QUALIFIED_PRE_CUTOFF',as_of=source['as_of'],
                   generated_at='2030-04-01T11:40:03+09:00',
                   server_saved_at=source['server_saved_at'],cutoff_at=source['cutoff_at'])
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,now=NOW,
                                  native_coverage_reader=lambda *_args,**_kw:proof)
        self.assertEqual(result['p1_qualified_unique_slots'],1)
        self.assertEqual(view,original)
        proof.update(status='HOLD',reason='NATIVE_GENERATED_AT_MISSING',generated_at=None)
        result=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,now=NOW,
                                  native_coverage_reader=lambda *_args,**_kw:proof)
        self.assertEqual(result['p1_qualified_unique_slots'],0)
        self.assertEqual(result['excluded_reasons'],{'NATIVE_NATIVE_GENERATED_AT_MISSING':1})
        self.assertEqual(view,original)

    def test_missing_slots_separate_future_pending_and_past_without_changing_denominator(self):
        view,source=self.example()
        now=datetime.fromisoformat('2030-04-01T11:50:00+09:00')
        ledger=[dict(race_id=f'20300401-01-{n:02}',cutoff_at=at,
                     schedule_captured_at='2030-04-01T08:00:00+09:00',source_sha256='c'*64)
                for n,at in ((1,'2030-04-01T12:00:00+09:00'),
                             (2,'2030-04-01T12:30:00+09:00'),
                             (3,'2030-04-01T11:49:00+09:00'))]
        ledger[2]['schedule_captured_at']='2030-04-01T11:50:00+09:00'
        before=deepcopy((view,ledger))
        report=saved_view_coverage(view,day=DAY,model_ids=['boat-A','boat-B'],scheduled_races=3,
                                   now=now,official_schedule=ledger)
        self.assertEqual(report['expected_model_slots'],6)
        self.assertEqual(report['p1_qualified_unique_slots'],1)
        self.assertEqual(report['missing_p1_model_slots'],5)
        self.assertEqual(report['missing_by_time'],{'NOT_DUE':2,'PRE_CUTOFF_PENDING':1,'DEADLINE_MISSED':2})
        self.assertEqual((view,ledger),before)
        self.assertNotIn('20300401-01-03',json.dumps(report))

    def test_official_ledger_disagreement_cannot_promote_a_native_claim(self):
        view,source=self.example()
        ledger=[dict(race_id='20300401-01-01',cutoff_at='2030-04-01T11:59:00+09:00',
                     schedule_captured_at='2030-04-01T08:00:00+09:00',source_sha256='c'*64)]
        report=saved_view_coverage(view,day=DAY,model_ids=['boat-A'],scheduled_races=1,
                                   now=NOW,official_schedule=ledger)
        self.assertEqual(report['p1_qualified_unique_slots'],0)
        self.assertEqual(report['missing_by_time'],{'NOT_DUE':0,'PRE_CUTOFF_PENDING':0,'DEADLINE_MISSED':1})
        self.assertEqual(report['cutoff_conflicts'],1)


if __name__=='__main__':
    unittest.main()
