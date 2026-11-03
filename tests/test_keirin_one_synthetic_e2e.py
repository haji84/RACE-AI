"""One complete *synthetic* result -> compare -> queue -> model -> private save cycle.

No provider HTTP, source grant, real model or independent timestamp witness is
used. Never interpret this as successful real-race or official KPI execution.
"""
from __future__ import annotations

from copy import deepcopy
import unittest

from race_ai.keirin_result_reactor import react_to_result_delivery
from race_ai.keirin_next_forecast_worker import consume_next_intent
from tests.test_keirin_result_reactor import case, auth_result
from tests.test_keirin_next_forecast_worker import fixture, NOW, AFTER, RID, CUTOFF


class KeirinSyntheticOneCycleTests(unittest.TestCase):
    def test_complete_one_cycle_uses_existing_contracts_without_replacing_original(self):
        batch,reference,_old_future = case()
        original_batch=deepcopy(batch)
        original_reference=deepcopy(reference)
        source_intent, snapshot, model_result, worker_cert = fixture()
        future=[{'race_id':RID,'official_cutoff_at':CUTOFF}]
        queue={}

        def next_certificate(row):
            return {
                'race_id':RID,
                'official_cutoff_at':CUTOFF,
                'pre_race_snapshot_sha256':source_intent['pre_race_snapshot_sha256'],
                'snapshot_captured_at':snapshot['as_of'],
                'permission_ref':snapshot['permission_ref'],
                'verified_purposes':['schedule','pre_race','private_retention'],
            }

        def enqueue_once(intent):
            queue.setdefault(intent['idempotency_key'],deepcopy(intent))
            return {'idempotency_key':intent['idempotency_key'],
                    'state':'CREATED_OR_EXISTS'}

        reactor_report=react_to_result_delivery(
            batch,future,now=NOW,forecast_reference=reference,
            authenticate_result=auth_result,
            verify_next=next_certificate,
            frozen_readback=lambda rid: {
                'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            enqueue_once=enqueue_once,
            enqueue_readback=lambda key:queue.get(key),
        )
        self.assertEqual(reactor_report['queued_count'],1)
        self.assertEqual(reactor_report['reference_hit8']['rows'][0]['research_hit8'],True)

        intent=next(iter(queue.values()))
        self.assertEqual(intent['race_id'],RID)
        self.assertFalse(intent['prediction_generated'])
        events=[NOW,AFTER]
        saved={}
        called={'model':0,'write':0}

        def clock():
            return events.pop(0)

        def model(snapshot_arg):
            called['model']+=1
            self.assertEqual(snapshot_arg,snapshot)
            return deepcopy(model_result)

        def freeze(record, digest):
            called['write']+=1
            self.assertEqual(record['top8'],model_result['top8'])
            saved.setdefault(record['race_id'],deepcopy(record))
            return {'race_id':RID,'forecast_sha256':digest,'state':'CREATED_ONCE'}

        worker_report=consume_next_intent(
            intent,clock=clock,
            read_queued_intent=lambda k:deepcopy(queue.get(k)),
            read_snapshot=lambda i:deepcopy(snapshot),
            attest_source=lambda s,i:deepcopy(worker_cert),
            frozen_status=lambda rid:{
                'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            model_forecast=model,atomic_freeze=freeze,
            freeze_readback=lambda rid,digest:deepcopy(saved.get(rid)),
            independent_receipt_check=lambda record,digest:{
                'race_id':RID,'forecast_sha256':digest,
                'trusted_persisted_at':'2026-11-03T10:51:01+09:00',
                'external_witness':'SYNTHETIC_FIXTURE_NOT_ACTUAL_WITNESS'},
        )
        self.assertTrue(worker_report['forecast_durably_saved'])
        self.assertTrue(worker_report['independent_receipt_accepted_by_callback'])
        self.assertFalse(worker_report['live_autorun_enabled'])
        self.assertIsNone(worker_report['formal_hit_at_8_all'])
        self.assertEqual(called,{'model':1,'write':1})
        self.assertEqual(batch,original_batch)
        self.assertEqual(reference,original_reference)
        self.assertFalse(saved[RID]['officially_frozen'])

    def test_no_result_attestation_never_queues_or_runs_model(self):
        batch,reference,_ = case()
        intent,snapshot,model,cert=fixture()
        stored=[]
        out=react_to_result_delivery(
            batch,[{'race_id':RID,'official_cutoff_at':CUTOFF}],
            now=NOW,forecast_reference=reference,
            authenticate_result=lambda obs,sha:None,
            verify_next=lambda row:None,
            frozen_readback=lambda rid:None,
            enqueue_once=lambda i:stored.append(i),
            enqueue_readback=lambda k:None)
        self.assertEqual(out['dispatch_state'],'NO_VERIFIED_FINAL_RESULT_EVENT')
        self.assertEqual(stored,[])


if __name__=='__main__':
    unittest.main()
