"""Real PR71 algorithm invoked on *invented* data, never provider material.

The PR72 repository doesn't contain PR71 modules. This test is enabled only
when the pinned PR71 model sources have been checked out by the dedicated CI.
"""
import copy
from datetime import datetime
from hashlib import sha256
import unittest

from race_ai.keirin_result_delivery import canonical
from race_ai.keirin_pr71_model_adapter import (
    Pr71AdapterError, run_pr71_for_next_race
)
from race_ai.keirin_next_forecast_worker import consume_next_intent

try:
    from race_ai.comprehensive_four_sport_models import feature_inventory
    from race_ai.four_sport_model_suite import run_suite, verify_suite
except ImportError:
    feature_inventory = run_suite = verify_suite = None

DAY = '2030-01-15'
RID = 'keirin:2030-01-15:fictional-venue:1'
ASOF = '2030-01-15T09:10:00+09:00'
CUTOFF = '2030-01-15T10:00:00+09:00'
ISSUED = '2030-01-15T09:21:00+09:00'


def make_sources():
    inv=feature_inventory('keirin')
    def obs(value):
        return {'value':value,'published_at':'2030-01-15T08:00:00+09:00',
                'captured_at':'2030-01-15T08:01:00+09:00',
                'source_ref':'synthetic://fiction','source_rights_ref':'synthetic-fiction',
                'sample_n':10,'transform_id':'fictional-favorability-0-1'}
    participants=[]
    for i in range(7):
        features={key:obs(round(0.2+((i*17+j*13)%65)/100,2))
            for j,key in enumerate(inv['common_required']+inv['sport_required'])}
        participants.append({
            'number':i+1,'identity':f'fictional-rider-{i+1}',
            'draw':i+1,'style':('front','stalker','closer','allround')[i%4],
            'group_id':f'line-{i//3}',
            'features':features,
        })
    required=inv['environment_required']
    defaults={'wind_mps':4,'rain_mm_h':0,'humidity_pct':60,'air_temp_c':18,
              'surface_wetness':0.1}
    env={key:obs(defaults.get(key,0.3)) for key in required}
    evidence={
        'schema':'RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1',
        'scope':'SYNTHETIC_ONLY',
        'race':{'race_id':RID,'sport':'keirin','venue':'fictional-venue',
                'event_date_jst':DAY,'sales_cutoff_at':CUTOFF,
                'as_of':ASOF,'distance_m':2000,'surface':'velodrome',
                'race_kind':'fictional-test','race_revision':1},
        'participants':participants,'environment':env,
    }
    snapshot={
        'schema':'RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1',
        'race_id':RID,'as_of':ASOF,'starters':[1,2,3,4,5,6,7],
        'facts':{'pr71_evidenced_snapshot':evidence},
        'permission_ref':'SYNTHETIC_ONLY_NOT_RIGHTSHOLDER_PERMISSION',
        'official_cutoff_at':CUTOFF,
    }
    sha=sha256(canonical(snapshot)).hexdigest()
    key=sha256(canonical({'race_id':RID,'official_cutoff_at':CUTOFF,
                          'job_kind':'KEIRIN_NEXT_FORECAST_V1'})).hexdigest()
    intent={
        'schema':'RACE_AI_KEIRIN_NEXT_FORECAST_INTENT_V1',
        'idempotency_key':key,'trigger_source_event_sha256':'b'*64,
        'race_id':RID,'official_cutoff_at':CUTOFF,
        'pre_race_snapshot_sha256':sha,'pre_race_snapshot_at':ASOF,
        'permission_ref':snapshot['permission_ref'],
        'max_trifecta_picks':8,'prediction_generated':False,
    }
    cert={
        'race_id':RID,'source_sha256':sha,'permission_ref':snapshot['permission_ref'],
        'official_cutoff_at':CUTOFF,
        'verified_purposes':['schedule','pre_race','private_retention','model_inference'],
        'valid_until':'2030-01-15T11:00:00+09:00',
    }
    return snapshot,intent,cert


@unittest.skipIf(run_suite is None, 'PR71 pinned model not checked out by host')
class ActualPR71AlgorithmIntegration(unittest.TestCase):
    def test_run_actual_pr71_suite_and_save_eight_private_research_picks(self):
        snap,intent,cert=make_sources()
        original=copy.deepcopy(snap)
        forecast=run_pr71_for_next_race(
            snap,run_suite=run_suite,verify_suite=verify_suite,
            source_admission=None,
            model_id='multisport-scenario-ensemble-v1',
            issued_at=ISSUED)
        self.assertIs(forecast['trained'],False)
        self.assertIsNone(forecast['trained_until'])
        self.assertEqual(forecast['top8'],run_suite(
            snap['facts']['pr71_evidenced_snapshot']
        )['models']['multisport-scenario-ensemble-v1']['ordered_top8'])
        self.assertEqual(snap,original)
        private={}
        times=iter(['2030-01-15T09:20:00+09:00',
                    '2030-01-15T09:22:00+09:00'])
        def freeze(record, fingerprint):
            private[RID]=copy.deepcopy(record)
            return {'race_id':RID,'forecast_sha256':fingerprint,
                    'state':'CREATED_ONCE'}
        summary=consume_next_intent(
            intent,clock=lambda:next(times),
            read_queued_intent=lambda key:intent,
            read_snapshot=lambda _i:copy.deepcopy(snap),
            attest_source=lambda _s,_i:cert,
            frozen_status=lambda rid:{
                'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            model_forecast=lambda _:forecast,
            atomic_freeze=freeze,
            freeze_readback=lambda race,fingerprint:private.get(race),
            independent_receipt_check=lambda r,d:{
                'race_id':RID,'forecast_sha256':d,
                'trusted_persisted_at':'2030-01-15T09:22:01+09:00',
                'external_witness':'SYNTHETIC_CALLBACK_NOT_A_REMOTE_WITNESS'},
        )
        self.assertTrue(summary['forecast_durably_saved'])
        self.assertFalse(summary['live_autorun_enabled'])
        self.assertIsNone(summary['formal_hit_at_8_all'])
        self.assertIs(private[RID]['trained'],False)
        self.assertIsNone(private[RID]['trained_until'])
        self.assertEqual(private[RID]['top8'],forecast['top8'])
        self.assertFalse(private[RID]['officially_frozen'])

    def test_missing_required_evidence_refuses_to_invent_input(self):
        snap,_,_=make_sources()
        del snap['facts']['pr71_evidenced_snapshot']['participants'][0]['features']['ability']
        with self.assertRaises(ValueError):
            run_pr71_for_next_race(snap,run_suite=run_suite,verify_suite=verify_suite,
              source_admission=None,model_id='multisport-scenario-ensemble-v1',
              issued_at=ISSUED)

    def test_real_scope_without_source_grant_denied(self):
        snap,_,_=make_sources()
        snap['facts']['pr71_evidenced_snapshot']['scope']='OPERATOR_SUPPLIED_RESEARCH'
        with self.assertRaisesRegex(Pr71AdapterError,'REAL_SOURCE_ADMISSION_REQUIRED'):
            run_pr71_for_next_race(snap,run_suite=run_suite,verify_suite=verify_suite,
              source_admission=None,model_id='multisport-scenario-ensemble-v1',
              issued_at=ISSUED)

    def test_wrong_cutoff_does_not_run_model(self):
        snap,_,_=make_sources()
        snap['facts']['pr71_evidenced_snapshot']['race']['sales_cutoff_at']=(
             '2030-01-15T09:30:00+09:00')
        with self.assertRaisesRegex(Pr71AdapterError,'RACE_TIME_OR_SCOPE_MISMATCH'):
            run_pr71_for_next_race(snap,run_suite=run_suite,verify_suite=verify_suite,
              source_admission=None,model_id='multisport-scenario-ensemble-v1',
              issued_at=ISSUED)

    def test_no_result_or_odds_in_prediction_input(self):
        snap,_,_=make_sources()
        snap['facts']['pr71_evidenced_snapshot']['participants'][0]['features']['odds']=2.0
        with self.assertRaises(ValueError):
            run_pr71_for_next_race(snap,run_suite=run_suite,verify_suite=verify_suite,
              source_admission=None,model_id='multisport-scenario-ensemble-v1',
              issued_at=ISSUED)


if __name__=='__main__':
    unittest.main()
