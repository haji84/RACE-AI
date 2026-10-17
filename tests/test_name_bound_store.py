import copy
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from datetime import timedelta
from tests.test_name_bound_prediction import packet_fixture, NOW
from tests.test_race_cloud_store import Blob
from tests.test_exhibition_store import seed_baseline
from web import race_contract as facts
from web.name_bound_inputs import build_name_bound_inputs


class StoreTests(unittest.TestCase):
    def setUp(self):
        with patch.object(sys,'path',[str(Path(__file__).resolve().parents[1]/'web')]+sys.path):
            try:self.s=importlib.import_module('api.name_bound_exhibition_store')
            except ModuleNotFoundError:self.s=None
        self.assertIsNotNone(self.s,'finalized name-bound store required')
        self.race,self.base,self.binding,self.inputs=packet_fixture();self.client=Blob()
        seed_baseline(self.client,self.base)
        r=self.race['race_id'];n=self.binding['receipt']['request_id'];b=self.binding
        self.client.data[f'race-ai/name-binding-receipts/{r}/{n}.json']=facts.canonical(b['receipt'])
        self.client.data[f'race-ai/name-binding-finalizations/{r}/{n}.json']=facts.canonical(b['finalization'])
        self.client.data[f"race-ai/name-binding-versions/{r}/{b['receipt']['snapshot']['snapshot_id']}.json"]=facts.canonical(b['receipt']['snapshot'])
        self.request=dict(publication_review='user-confirmation-2026-10-15-official-facts',media_review='user-confirmation-2026-10-15-exhibition-private-analysis',race_id=r,request_id='123499-1',baseline_request_id=self.base['request_id'],name_binding_request_id=n,inputs=self.inputs,runner_saved_at=facts.stamp(NOW))

    def publish(self,now=NOW,clock=None,request=None):
        return self.s.publish_name_bound_exhibition(request or self.request,self.race,client=self.client,now=now,clock=clock or (lambda:now))
    def read(self,now=NOW,request_id=None):
        return self.s.read_name_bound_exhibition(self.race,client=self.client,now=now,request_id=request_id)

    def test_complete_envelope_and_zero_write_retry_after_close(self):
        meta=self.publish();value=self.read();self.assertEqual(set(value),{'receipt','finalization','inputs','baseline','name_binding'})
        self.assertEqual(meta['sha256'],self.s.digest(value));self.assertEqual(len(self.client.puts),5)
        self.assertEqual(value['receipt']['snapshot']['input_link']['sha256'],self.s.digest(self.inputs))
        puts=copy.deepcopy(self.client.puts);after=facts._time(self.race['closed_at'])+timedelta(seconds=1)
        self.assertEqual(self.publish(now=after),meta);self.assertEqual(self.client.puts,puts)
        self.assertEqual(self.read(now=after,request_id=self.request['request_id']),value)
        for field,value in [('runner_saved_at',facts.stamp(NOW+timedelta(seconds=1))),('baseline_request_id','123498-1'),('name_binding_request_id','123498-1')]:
            with self.assertRaises(ValueError):self.publish(request={**self.request,field:value})

    def test_actual_readback_clock_sequence_and_orphan_is_permanent(self):
        values=iter(NOW+timedelta(seconds=i) for i in range(7))
        self.publish(clock=lambda:next(values));e=self.read(now=NOW+timedelta(seconds=7));s=e['receipt']['snapshot']
        self.assertEqual(s['parents_resolved_at'],facts.stamp(NOW))
        self.assertEqual(s['input_link']['input_cloud_saved_at'],facts.stamp(NOW+timedelta(seconds=1)))
        self.assertEqual(s['generated_at'],facts.stamp(NOW+timedelta(seconds=2)))
        self.assertEqual(e['receipt']['cloud_saved_at'],facts.stamp(NOW+timedelta(seconds=3)))
        self.assertEqual(e['finalization']['receipt_confirmed_at'],facts.stamp(NOW+timedelta(seconds=4)))
        del self.client.data[self.s.finalization_key(self.race['race_id'],self.request['request_id'])]
        puts=len(self.client.puts)
        with self.assertRaises(ValueError):self.publish(now=NOW+timedelta(seconds=8))
        self.assertEqual(len(self.client.puts),puts)

    def test_missing_versions_corrupt_marker_and_latest_fail_closed(self):
        self.publish();original=copy.deepcopy(self.client.data)
        keys=[self.s.input_key(self.race['race_id'],self.inputs['snapshot_id']),self.s.prediction_key(self.race['race_id'],self.read()['receipt']['snapshot']['snapshot_id']),self.s.finalization_key(self.race['race_id'],self.request['request_id'])]
        for key in keys:
            self.client.data=copy.deepcopy(original);del self.client.data[key]
            with self.assertRaises(ValueError):self.read(request_id=self.request['request_id'])
        self.client.data=original;self.client.data[self.s.manifest_key(self.race['race_id'])]=b'corrupt'
        self.assertIsNotNone(self.read(request_id=self.request['request_id']))
        with self.assertRaises(ValueError):self.read()

    def test_latest_turnover_uses_each_requests_own_pinned_parents(self):
        self.publish();first=self.read();original=copy.deepcopy(self.client.data)
        base=copy.deepcopy(self.base);base['request_id']='123488-1';seed_baseline(self.client,base)
        binding=copy.deepcopy(self.binding);binding['receipt']['request_id']='123489-1';binding['receipt']['baseline_request_id']=base['request_id']
        binding['finalization'].update(request_id='123489-1',baseline_request_id=base['request_id'],receipt_sha256=self.s.digest(binding['receipt']))
        r=self.race['race_id'];n='123489-1'
        self.client.data[f'race-ai/name-binding-receipts/{r}/{n}.json']=facts.canonical(binding['receipt'])
        self.client.data[f'race-ai/name-binding-finalizations/{r}/{n}.json']=facts.canonical(binding['finalization'])
        inputs=build_name_bound_inputs(self.inputs['beforeinfo_record'],self.inputs['original_observation'],self.race,base,binding,
            parents_read_at=self.inputs['parents_read_at'],generated_at=self.inputs['generated_at'],now=NOW)
        second={**self.request,'request_id':'123490-1','baseline_request_id':base['request_id'],'name_binding_request_id':n,'inputs':inputs}
        self.client.data[f'race-ai/predictions/{r}.json']=b'corrupt mutable baseline'
        self.publish(request=second,now=NOW+timedelta(seconds=1))
        self.assertEqual(self.read(now=NOW+timedelta(seconds=1))['baseline'],base)
        self.assertEqual(self.read(now=NOW+timedelta(seconds=1),request_id=self.request['request_id']),first)
        for key,value in original.items():
            if '/prediction-' in key:self.assertEqual(self.client.data[key],value)
        puts=len(self.client.puts);self.publish(now=NOW+timedelta(seconds=2));self.assertEqual(len(self.client.puts),puts)
        self.assertEqual(self.read(now=NOW+timedelta(seconds=2))['receipt']['request_id'],second['request_id'])

    def test_readback_latency_never_backdates_finalization(self):
        for namespace in ('name-bound-inputs','name-bound-predictions','name-bound-receipts'):
            with self.subTest(namespace=namespace):
                self.setUp();late=[False];original_get=self.client.get
                def get(key,**kw):
                    result=original_get(key,**kw)
                    if namespace in key and key in self.client.data:late[0]=True
                    return result
                self.client.get=get
                with self.assertRaises(ValueError):self.publish(clock=lambda:facts._time(self.race['closed_at']) if late[0] else NOW)
                self.assertFalse(any('/name-bound-finalizations/' in k for k in self.client.data))
                self.assertFalse(any('/name-bound-exhibition/' in k for k in self.client.data))
                if namespace=='name-bound-receipts':
                    writes=len(self.client.puts)
                    with self.assertRaises(ValueError):self.publish()
                    self.assertEqual(len(self.client.puts),writes)

    def test_aggregate_bound_is_checked_before_marker_and_every_read(self):
        self.publish();envelope=self.read();bound=len(facts.canonical(envelope))-1
        # The lowered boundary fits each member individually but not their aggregate.
        self.assertTrue(all(len(facts.canonical(v))<bound for v in envelope.values()))
        with patch.dict(self.s.validate_name_bound_envelope.__globals__,MAX_BYTES=bound):
            with self.assertRaises(ValueError):self.read()
        self.setUp()
        with patch.dict(self.s.validate_name_bound_envelope.__globals__,MAX_BYTES=bound):
            with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any('/name-bound-finalizations/' in k for k in self.client.data))

    def test_latest_preclose_check_uses_clock_after_marker_readback(self):
        times=iter([NOW]*5+[facts._time(self.race['closed_at'])])
        with self.assertRaises(ValueError):self.publish(clock=lambda:next(times))
        self.assertIsNotNone(self.read(request_id=self.request['request_id']))
        self.assertIsNone(self.read())


if __name__=='__main__':unittest.main()
