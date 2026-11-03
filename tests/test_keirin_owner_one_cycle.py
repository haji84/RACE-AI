"""One full fictional race loop, actual PR71 algorithm, no provider I/O.

PR71 code is included only in the separately pinned checkout of dedicated CI.
Results and rights receipts are invented, intentionally proving NO real E2E.
"""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_result_delivery import canonical, digest
from race_ai.keirin_owner_one_cycle import execute_one_owner_cycle
from race_ai.keirin_pr71_model_adapter import run_pr71_for_next_race
from tests.test_keirin_pr71_model_adapter import (
    make_sources, RID, CUTOFF, ISSUED, run_suite, verify_suite
)

PAST = 'keirin:2029-12-30:fictional-venue:7'


def build():
    future_snapshot,intent,cert=make_sources()
    raw_record={
        'schema':'RACE_AI_KEIRIN_NORMALIZED_RESULT_DELIVERY_V1',
        'event_date_jst':'2029-12-30',
        'source_url':'https://keirin.jp/example',
        'source_published_at':'2029-12-30T16:00:00+09:00',
        'captured_at':'2029-12-30T16:01:00+09:00',
        'results':[{
            'race_id':PAST,'starters':[1,2,3,4,5,6,7],
            'status':'FINAL_NORMAL','winning_triples':[[1,2,3]],
            'payouts_100yen':[{'triple':[1,2,3],'yen':2230}],
            'refund_status':'NONE','provider_revision_ref':'fictional-1',
            'official_cutoff_at':'2029-12-30T15:00:00+09:00',
        }],
    }
    raw=canonical(raw_record)
    admission={
        'source_id':'synthetic','source_url':raw_record['source_url'],
        'source_sha256':sha256(raw).hexdigest(),'rights_ref':'SYNTHETIC-NOT-A-GRANT',
        'verified_purposes':['result_collection','private_retention','result_analysis'],
        'checked_at':'2029-12-30T15:45:00+09:00',
        'expires_at':'2030-01-16T10:00:00+09:00',
    }
    bridge={
        'schema':'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
        'mode':'OFFLINE_RESEARCH_COVERAGE_LINK',
        'event_date_jst':'2029-12-30',
        'official_completeness_verified':False,
        'source_rights_verified':False,
        'external_pre_cutoff_receipts_verified':False,
        'formal_hit_at_8_all':None,
        'records':[{
            'race_id':PAST,'sport':'keirin','event_date_jst':'2029-12-30',
            'venue':'fictional-venue','race_no':7,
        }],
    }
    past_ref={PAST:{
        'top8':[[1,2,3],[1,3,2],[2,1,3],[2,3,1],
                [3,1,2],[3,2,1],[4,5,6],[5,4,6]],
        'original_generated_at':'2029-12-30T14:00:00+09:00',
        'original_cutoff_at':'2029-12-30T15:00:00+09:00',
        'model_version':'fixture-research',
    }}
    return bridge,raw,admission,past_ref,future_snapshot,intent,cert


@unittest.skipIf(run_suite is None,'pinned PR71 source not available')
class FullOneCycleActualResearchModel(unittest.TestCase):
    def _go(self,deny_source=False):
        bridge,raw,admission,reference,snapshot,expected_intent,cert=build()
        previous=copy.deepcopy(reference)
        store={}
        queue={}
        ticks=iter(['2030-01-15T09:20:00+09:00',
                    '2030-01-15T09:20:01+09:00',
                    '2030-01-15T09:22:00+09:00'])
        called={'model':0,'freeze':0}
        def model(actual):
            called['model']+=1
            return run_pr71_for_next_race(
                actual,run_suite=run_suite,verify_suite=verify_suite,
                source_admission=None,
                model_id='multisport-scenario-ensemble-v1',
                issued_at=ISSUED)
        def freeze(record,sha):
            called['freeze']+=1
            store.setdefault(record['race_id'],copy.deepcopy(record))
            return {'race_id':record['race_id'],'forecast_sha256':sha,
                    'state':'CREATED_ONCE'}
        def outcome_attest(obs,sha):
            return {
                'race_id':obs['race_id'],'observation_sha256':sha,
                'provider_receipt_sha256':'a'*64,
                'verified_purposes':['result_collection','result_analysis'],
            }
        def future_attest(row):
            return {
                'race_id':RID,'official_cutoff_at':CUTOFF,
                'pre_race_snapshot_sha256':expected_intent['pre_race_snapshot_sha256'],
                'snapshot_captured_at':snapshot['as_of'],
                'permission_ref':snapshot['permission_ref'],
                'verified_purposes':['schedule','pre_race','private_retention'],
            }
        def enqueue(intent):
            queue.setdefault(intent['idempotency_key'],copy.deepcopy(intent))
            return {'idempotency_key':intent['idempotency_key'],
                    'state':'CREATED_OR_EXISTS'}
        cbs={
            'clock':lambda:next(ticks),
            'attest_raw_result_feed':(
                (lambda *args:None) if deny_source else
                (lambda fingerprint, receipt:{
                    'source_sha256':fingerprint,'rights_ref':receipt['rights_ref'],
                    'verified_purposes':receipt['verified_purposes']})
            ),
            'authenticate_result':outcome_attest,
            'verify_next':future_attest,
            'frozen_readback':lambda rid:{
                'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            'enqueue_once':enqueue,
            'enqueue_readback':lambda k:queue.get(k),
            'read_queued_intent':lambda k:queue.get(k),
            'read_snapshot':lambda i:copy.deepcopy(snapshot),
            'attest_source':lambda s,i:copy.deepcopy(cert),
            'frozen_status':lambda rid:{
                'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            'model_forecast':model,
            'atomic_freeze':freeze,
            'freeze_readback':lambda rid,sha:copy.deepcopy(store.get(rid)),
            'independent_receipt_check':lambda rec,sha:{
                'race_id':RID,'forecast_sha256':sha,
                'trusted_persisted_at':'2030-01-15T09:22:01+09:00',
                'external_witness':'SYNTHETIC_NOT_REAL_WITNESS',
            },
        }
        report=execute_one_owner_cycle(
            bridge=bridge,raw_feed=raw,admission=admission,
            forecast_reference=reference,
            future_races=[{'race_id':RID,'official_cutoff_at':CUTOFF}],
            callbacks=cbs)
        self.assertEqual(reference,previous)
        return report,store,queue,called

    def test_full_result_to_real_pr71_algorithm_mock_private_save(self):
        summary,store,queue,calls=self._go()
        self.assertTrue(summary['research_hit8']['rows'][0]['research_hit8'])
        self.assertEqual(summary['research_queued'],1)
        self.assertTrue(summary['model_called'])
        self.assertTrue(summary['private_forecast_saved'])
        self.assertFalse(summary['real_e2e_verified'])
        self.assertIsNone(summary['formal_hit_at_8_all'])
        self.assertEqual(calls,{'model':1,'freeze':1})
        self.assertEqual(len(store[RID]['top8']),8)
        self.assertIsNone(store[RID]['trained_until'])
        self.assertFalse(store[RID]['officially_frozen'])

    def test_unverified_real_feed_stops_before_model(self):
        summary,store,queue,calls=self._go(deny_source=True)
        self.assertEqual(summary['state'],'REAL_SOURCE_ATTESTATION_UNAVAILABLE')
        self.assertFalse(summary['real_e2e_verified'])
        self.assertFalse(summary['model_called'])
        self.assertEqual(queue,{})
        self.assertEqual(store,{})
        self.assertEqual(calls,{'model':0,'freeze':0})


if __name__=='__main__':
    unittest.main()
