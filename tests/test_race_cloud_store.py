"""Synthetic cloud ingress timing, version recovery and program identity checks."""
import copy
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from tests import test_race_update_merge as merge_fixtures

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-10-15T07:02:00+09:00')


class Blob:
    def __init__(self): self.data = {}; self.puts = []
    def get(self, key, **kwargs):
        if key not in self.data: return None
        return types.SimpleNamespace(pathname=key, url='https://test.private.blob.vercel-storage.com/'+key,
            status_code=200, content=self.data[key], content_type='application/json', size=len(self.data[key]))
    def put(self, key, raw, **kwargs):
        if key in self.data and not kwargs.get('overwrite'): raise RuntimeError('immutable collision')
        self.data[key] = raw; self.puts.append((key, kwargs))
        return types.SimpleNamespace(pathname=key)


class RaceCloudTests(unittest.TestCase):
    def setUp(self):
        with patch.object(sys, 'path', [str(ROOT/'web')] + sys.path):
            self.store = importlib.import_module('api.race_store')
        helper = merge_fixtures.RaceUpdateMergeTests()
        self.program = helper.feed()['venues'][0]['races'][0]
        self.record = helper.observation()
        self.record['rights_review'] = 'user-confirmation-2026-10-15-official-facts'
        helper.rehash(self.record)
        self.bundle = {'schema_version':1, 'race_id':self.program['race_id'],
            'records':[self.record], 'latest':{'beforeinfo':self.record['snapshot_id']}}
        self.request = {'publication_review':'user-confirmation-2026-10-15-official-facts', 'bundle':self.bundle}
        self.client = Blob()

    def publish(self, request=None, now=NOW, clock=None):
        return self.store.publish_bundle(request or self.request, self.program, client=self.client,
            now=now, clock=clock or (lambda:now))

    def read(self, now=NOW):
        return self.store.read_current_race(self.program, client=self.client, now=now)

    def test_real_cloud_time_is_after_durable_record_not_runner_save(self):
        receipt_time = NOW + timedelta(seconds=2)
        report = self.publish(clock=lambda:receipt_time)
        served = self.read(receipt_time)
        receipt = served['records'][0]
        self.assertEqual(datetime.fromisoformat(receipt['cloud_saved_at']), receipt_time)
        self.assertTrue(receipt['cloud_eligible_pre_race'])
        self.assertEqual(receipt['record'], self.record)
        self.assertEqual(report['race_id'], self.program['race_id'])
        self.assertEqual(len(self.client.puts), 3)  # observation, actual-save receipt, current manifest
        self.assertTrue(all(options['access']=='private' for _,options in self.client.puts))

    def test_ingress_crossing_close_is_never_pre_race(self):
        closed = datetime.fromisoformat(self.program['closed_at'])
        self.publish(now=closed-timedelta(seconds=1), clock=lambda:closed+timedelta(seconds=1))
        self.assertFalse(self.read(closed+timedelta(seconds=2))['records'][0]['cloud_eligible_pre_race'])

    def test_idempotent_retry_preserves_first_cloud_receipt(self):
        self.publish()
        first = self.read()
        self.publish(now=NOW+timedelta(minutes=5))
        self.assertEqual(self.read(NOW+timedelta(minutes=5)), first)
        self.assertEqual(len(self.client.puts),3)

    def test_retry_recovers_manifest_without_retiming_stored_observation(self):
        report = self.publish()
        original = self.read()['records'][0]
        del self.client.data[report['pathname']]
        self.publish(now=NOW+timedelta(minutes=5))
        self.assertEqual(self.read(NOW+timedelta(minutes=5))['records'][0],original)

    def test_older_revision_is_retained_but_cannot_replace_newer_current(self):
        helper = merge_fixtures.RaceUpdateMergeTests()
        later = helper.observation(capture='2026-10-15T07:03:00+09:00',saved='2026-10-15T07:04:00+09:00')
        later['rights_review']=self.record['rights_review'];helper.rehash(later)
        request=copy.deepcopy(self.request);request['bundle']['records']=[later];request['bundle']['latest']={'beforeinfo':later['snapshot_id']}
        self.publish(request,now=NOW+timedelta(minutes=3))
        self.publish(now=NOW+timedelta(minutes=4))
        self.assertEqual(self.read(NOW+timedelta(minutes=4))['latest']['beforeinfo'],later['snapshot_id'])
        self.assertEqual(len(self.client.data),5)

    def test_malformed_cross_race_future_unapproved_requests_write_nothing(self):
        cases=[]
        for field,value in [('publication_review','unknown')]:
            value_request=copy.deepcopy(self.request);value_request[field]=value;cases.append(value_request)
        for field,value in [('race_id','20261015-17-01'),('latest',{}),('schema_version',True)]:
            value_request=copy.deepcopy(self.request);value_request['bundle'][field]=value;cases.append(value_request)
        for field,value in [('saved_at','2026-10-15T08:00:00+09:00'),('cloud_saved_at',NOW.isoformat()),('rights_review','unknown')]:
            value_request=copy.deepcopy(self.request);value_request['bundle']['records'][0][field]=value;cases.append(value_request)
        for request in cases:
            with self.subTest(request=request),self.assertRaises(ValueError):self.publish(request)
            self.assertEqual(self.client.puts,[])

    def test_program_revision_and_corrupt_manifest_or_receipt_fail_closed(self):
        report=self.publish()
        revised=copy.deepcopy(self.program);revised['boats'][0]['racer_registration_id']='4999'
        with self.assertRaises(ValueError):self.store.read_current_race(revised,client=self.client,now=NOW)
        manifest=json.loads(self.client.data[report['pathname']]);manifest['latest']['odds3t']='a'*64
        self.client.data[report['pathname']]=json.dumps(manifest).encode()
        with self.assertRaises(ValueError):self.read()

    def test_receipt_hash_tampering_and_wrong_blob_origin_are_rejected(self):
        self.publish()
        key=next(key for key in self.client.data if '/receipts/' in key)
        original=self.client.data[key];receipt=json.loads(original);receipt['cloud_eligible_pre_race']=False
        self.client.data[key]=json.dumps(receipt).encode()
        with self.assertRaises(ValueError):self.read()
        self.client.data[key]=original
        original_get=self.client.get
        def malicious(key,**kwargs):
            result=original_get(key,**kwargs)
            if result is not None:result.url='https://attacker.example/'+key
            return result
        self.client.get=malicious
        with self.assertRaises(ValueError):self.read()

    def test_pinned_sdk_cache_bypass_query_is_accepted_but_other_queries_are_not(self):
        original_get=self.client.get
        def sdk_response(key,**kwargs):
            result=original_get(key,**kwargs)
            if result is not None:result.url+='?cache=0'
            return result
        self.client.get=sdk_response
        self.publish()
        self.assertEqual(self.read()['race_id'],self.program['race_id'])
        for query in ['cache=1','cache=0&token=unknown','cache=0&cache=0','download=1']:
            def wrong_query(key,**kwargs):
                result=original_get(key,**kwargs)
                if result is not None:result.url+='?'+query
                return result
            self.client.get=wrong_query
            with self.subTest(query=query),self.assertRaises(ValueError):self.read()


if __name__=='__main__':unittest.main()
