"""Forecast-scoped immutable result publication, with synthetic private Blob I/O."""
import copy
from datetime import timedelta
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_name_bound_evaluation_api import seed
from tests.test_name_bound_result import label_fixture
from tests.test_race_cloud_store import Blob
from web import name_bound_result as contract
from web import race_contract as facts


def store_fixture(client=None):
    race, forecast, envelope, now = label_fixture(contract)
    client = client or Blob()
    seed(client, forecast, None)
    request = dict(publication_review='user-confirmation-2026-10-15-official-facts',
        race_id=race['race_id'], request_id='123500-1', forecast_request_id='123499-1',
        snapshot=envelope['receipt']['snapshot'], runner_saved_at=envelope['receipt']['runner_saved_at'])
    return race, forecast, request, client, now


def seed_label(client, race, envelope):
    r = envelope['receipt']; f = r['forecast_request_id']; n = r['request_id']; rid = race['race_id']
    client.data[f'race-ai/name-bound-result-packets/{rid}/{r["snapshot"]["snapshot_id"]}.json'] = facts.canonical(r['snapshot'])
    client.data[f'race-ai/name-bound-result-receipts/{rid}/{f}/{n}.json'] = facts.canonical(r)
    client.data[f'race-ai/name-bound-result-finalizations/{rid}/{f}/{n}.json'] = facts.canonical(envelope['finalization'])
    client.data[f'race-ai/name-bound-result-latest/{rid}/{f}.json'] = facts.canonical(dict(schema_version=1,
        race_id=rid, forecast_request_id=f, request_id=n, snapshot_id=r['snapshot']['snapshot_id'],
        published_at=envelope['finalization']['receipt_confirmed_at']))


class NameBoundResultStoreTests(unittest.TestCase):
    def setUp(self):
        with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]/'web')]+sys.path):
            try: self.s = importlib.import_module('api.name_bound_result_store')
            except ModuleNotFoundError: self.s = None
        self.assertIsNotNone(self.s, 'forecast-scoped result store required')
        self.race, self.forecast, self.request, self.client, self.now = store_fixture()

    def publish(self, request=None, now=None, clock=None):
        now = self.now if now is None else now
        return self.s.publish_name_bound_result(self.request if request is None else request, self.race,
            client=self.client, now=now, clock=clock or (lambda:now))

    def read(self, request_id=None, now=None, forecast=None):
        return self.s.read_name_bound_result(self.race, self.forecast if forecast is None else forecast,
            client=self.client, now=self.now if now is None else now, request_id=request_id)

    def test_exclusive_canonical_publication_full_readback_and_identical_zero_write_retry(self):
        old = copy.deepcopy(self.client.data)
        meta = self.publish(); envelope = self.read(); receipt = envelope['receipt']
        self.assertEqual(set(envelope), {'receipt','finalization'})
        self.assertEqual(receipt['snapshot'], self.request['snapshot'])
        self.assertEqual(receipt['runner_saved_at'], self.request['runner_saved_at'])
        self.assertEqual(set(meta), set('status race_id request_id forecast_request_id snapshot_id cloud_saved_at receipt_confirmed_at sha256 research_only validation_status purchase_decision purchase_recommendations'.split()))
        self.assertEqual((meta['status'],meta['request_id'],meta['forecast_request_id']), ('verified','123500-1','123499-1'))
        self.assertEqual((meta['research_only'],meta['validation_status'],meta['purchase_decision'],meta['purchase_recommendations']), (True,'UNVALIDATED','skip',[]))
        self.assertEqual(meta['sha256'], contract.digest(envelope))
        self.assertEqual(len(self.client.puts),4)
        for key,options in self.client.puts:
            self.assertTrue(key.startswith('race-ai/name-bound-result-'))
            self.assertEqual(options['access'],'private')
            self.assertEqual(options['overwrite'], '/name-bound-result-latest/' in key)
            self.assertEqual(self.client.data[key],facts.canonical(self.s.decode(self.client.data[key])))
        for key,raw in old.items(): self.assertEqual(self.client.data[key],raw)
        puts = copy.deepcopy(self.client.puts)
        self.assertEqual(self.publish(now=self.now+timedelta(seconds=1)),meta)
        self.assertEqual(self.client.puts,puts)
        self.assertEqual(self.read(request_id='123500-1'),envelope)

    def test_truly_absent_before_close_is_none_but_supplied_label_rejects(self):
        preclose = facts._time(self.race['closed_at'])-timedelta(seconds=1)
        self.assertIsNone(self.read(now=preclose))
        self.assertIsNone(self.read(now=preclose,request_id='123500-1'))
        self.publish()
        for nonce in (None,'123500-1'):
            with self.subTest(nonce=nonce), self.assertRaises(ValueError): self.read(now=preclose,request_id=nonce)

    def test_exact_own_pinned_forecast_is_required_before_any_write(self):
        for mutation in ('missing','tampered','wrong_link','different_forecast'):
            self.setUp()
            if mutation == 'missing':
                del self.client.data[f'race-ai/name-bound-receipts/{self.race["race_id"]}/123499-1.json']
            elif mutation == 'tampered':
                key=f'race-ai/name-bound-finalizations/{self.race["race_id"]}/123499-1.json'
                self.client.data[key]=b'{}'
            elif mutation == 'wrong_link':
                self.request['snapshot']['forecast_link']['envelope_sha256']='0'*64
            else: self.request['forecast_request_id']='123498-1'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): self.publish()
            self.assertEqual(self.client.puts,[])

    def test_conflicting_request_or_orphan_nonce_never_writes_or_overwrites(self):
        self.publish(); original=copy.deepcopy(self.client.data); puts=len(self.client.puts)
        for field,value in [('runner_saved_at',facts.stamp(self.now)),('snapshot',{}),('publication_review','other'),('request_id','../escape'),('forecast_request_id','0-1')]:
            request=copy.deepcopy(self.request);request[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.publish(request)
            self.assertEqual(self.client.data,original);self.assertEqual(len(self.client.puts),puts)
        for missing in ('name-bound-result-receipts','name-bound-result-finalizations','name-bound-result-packets'):
            self.client.data=copy.deepcopy(original)
            key=next(k for k in self.client.data if '/'+missing+'/' in k);del self.client.data[key]
            before=copy.deepcopy(self.client.data)
            with self.subTest(missing=missing),self.assertRaises(ValueError):self.publish()
            self.assertEqual(self.client.data,before);self.assertEqual(len(self.client.puts),puts)

    def test_orphan_finalization_pinned_read_is_invalid_instead_of_absent(self):
        _,_,envelope,_=label_fixture(contract);seed_label(self.client,self.race,envelope)
        del self.client.data[f'race-ai/name-bound-result-receipts/{self.race["race_id"]}/123499-1/123500-1.json']
        with self.assertRaises(ValueError):self.read(request_id='123500-1')

    def test_packet_only_orphan_and_packet_reuse_under_new_nonce_are_rejected(self):
        packet=self.request['snapshot'];rid=self.race['race_id']
        self.client.data[f'race-ai/name-bound-result-packets/{rid}/{packet["snapshot_id"]}.json']=facts.canonical(packet)
        before=copy.deepcopy(self.client.data)
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.client.data,before);self.assertEqual(self.client.puts,[])
        self.setUp();self.publish();before=copy.deepcopy(self.client.data);puts=len(self.client.puts)
        request=copy.deepcopy(self.request);request['request_id']='123501-1'
        with self.assertRaises(ValueError):self.publish(request)
        self.assertEqual(self.client.data,before);self.assertEqual(len(self.client.puts),puts)

    def test_retry_requires_valid_latest_but_pinned_recovery_can_read_without_it(self):
        self.publish();envelope=self.read();original=copy.deepcopy(self.client.data);puts=len(self.client.puts)
        key=f'race-ai/name-bound-result-latest/{self.race["race_id"]}/123499-1.json'
        for raw in (None,b'{}',b'null'):
            self.client.data=copy.deepcopy(original)
            if raw is None:del self.client.data[key]
            else:self.client.data[key]=raw
            before=copy.deepcopy(self.client.data)
            self.assertEqual(self.read(request_id='123500-1'),envelope)
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.publish()
            self.assertEqual(self.client.data,before);self.assertEqual(len(self.client.puts),puts)

    def test_manifest_exact_fields_links_canonical_time_and_packet_bytes_are_required(self):
        self.publish(); original=copy.deepcopy(self.client.data)
        key=f'race-ai/name-bound-result-latest/{self.race["race_id"]}/123499-1.json'
        for field,value in [('schema_version',True),('race_id','20261015-18-02'),('forecast_request_id','123498-1'),
                ('request_id','123501-1'),('snapshot_id','0'*64),('published_at',facts.stamp(self.now+timedelta(seconds=1))),
                ('published_at',self.request['snapshot']['generated_at']),('extra',1)]:
            self.client.data=copy.deepcopy(original);manifest=self.s.decode(self.client.data[key]);manifest[field]=value
            self.client.data[key]=facts.canonical(manifest)
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.read()
        for namespace in ('packets','receipts','finalizations','latest'):
            self.client.data=copy.deepcopy(original);target=next(k for k in self.client.data if '/name-bound-result-'+namespace+'/' in k)
            self.client.data[target]=b' '+self.client.data[target]
            with self.subTest(namespace=namespace),self.assertRaises(ValueError):self.read()

    def test_pinned_read_ignores_other_forecasts_and_invalid_unrelated_latest(self):
        self.publish(); value=self.read();rid=self.race['race_id']
        self.client.data[f'race-ai/name-bound-result-latest/{rid}/123498-1.json']=b'{invalid'
        self.client.data[f'race-ai/name-bound-result-latest/{rid}/123499-1.json']=b'{invalid'
        self.assertEqual(self.read(request_id='123500-1'),value)
        other=copy.deepcopy(self.forecast);other['receipt']['request_id']='123498-1'
        other['finalization'].update(request_id='123498-1',receipt_sha256=contract.digest(other['receipt']))
        del self.client.data[f'race-ai/name-bound-result-latest/{rid}/123498-1.json']
        self.assertIsNone(self.read(forecast=other))
        self.assertIsNone(self.read(request_id='123500-1',forecast=other))

    def test_newer_latest_is_monotonic_and_forecast_scoped(self):
        self.publish();first=self.read();request=copy.deepcopy(self.request)
        request['request_id']='123501-1'
        request['snapshot']['generated_at']=facts.stamp(facts._time(request['snapshot']['generated_at'])+timedelta(microseconds=1))
        request['snapshot']['snapshot_id']=contract.digest({k:v for k,v in request['snapshot'].items() if k!='snapshot_id'})
        later=self.now+timedelta(seconds=1)
        self.publish(request,now=later)
        self.assertEqual(self.read(now=later)['receipt']['request_id'],'123501-1')
        self.assertEqual(self.read(request_id='123500-1',now=later),first)
        self.publish(now=later+timedelta(seconds=1))
        self.assertEqual(self.read(now=later+timedelta(seconds=1))['receipt']['request_id'],'123501-1')
        # A new nonce with older capture cannot replace the latest even with a later cloud clock.
        request['request_id']='123502-1'
        from tests.test_name_bound_evaluation import fixture
        earlier=facts._time(request['snapshot']['result_record']['captured_at'])-timedelta(microseconds=1)
        request['snapshot']['result_record']=fixture(capture=earlier)[2]['records'][0]['record']
        request['snapshot']['snapshot_id']=contract.digest({k:v for k,v in request['snapshot'].items() if k!='snapshot_id'})
        self.publish(request,now=later+timedelta(seconds=2))
        self.assertEqual(self.read(now=later+timedelta(seconds=2))['receipt']['request_id'],'123501-1')

    def test_postclose_day_and_monotonic_actual_clocks_across_every_io_and_final_read(self):
        midnight=(self.now.astimezone(facts.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))
        for namespace in ('name-bound-receipts','name-bound-result-packets','name-bound-result-receipts','name-bound-result-finalizations','name-bound-result-latest'):
            for late in (self.now-timedelta(microseconds=1),midnight):
                self.setUp();trigger=[False];original_get=self.client.get
                def get(key,**kw):
                    result=original_get(key,**kw)
                    if '/'+namespace+'/' in key and result is not None:trigger[0]=True
                    return result
                self.client.get=get
                with self.subTest(namespace=namespace,late=late),self.assertRaises(ValueError):
                    self.publish(clock=lambda:late if trigger[0] else self.now)
                if namespace in ('name-bound-receipts','name-bound-result-packets','name-bound-result-receipts'):
                    self.assertFalse(any('/name-bound-result-finalizations/' in k for k in self.client.data))
        self.setUp();self.publish();trigger=[False];original_get=self.client.get
        def final_get(key,**kw):
            result=original_get(key,**kw)
            if '/name-bound-result-packets/' in key:trigger[0]=True
            return result
        self.client.get=final_get;puts=len(self.client.puts)
        with self.assertRaises(ValueError):self.publish(clock=lambda:midnight if trigger[0] else self.now)
        self.assertEqual(len(self.client.puts),puts)
        for now in (facts._time(self.race['closed_at'])-timedelta(microseconds=1),midnight):
            self.setUp()
            with self.assertRaises(ValueError):self.publish(now=now)
            self.assertEqual(self.client.puts,[])

    def test_cloud_and_confirmation_clocks_are_measured_after_actual_readbacks(self):
        time=[self.now];original_get=self.client.get
        def get(key,**kw):
            result=original_get(key,**kw)
            if '/name-bound-result-' in key and result is not None:time[0]+=timedelta(microseconds=1)
            return result
        self.client.get=get;meta=self.publish(clock=lambda:time[0]);envelope=self.read(now=time[0])
        self.assertGreater(facts._time(meta['cloud_saved_at']),self.now)
        self.assertGreater(facts._time(meta['receipt_confirmed_at']),facts._time(meta['cloud_saved_at']))
        self.assertEqual(envelope['receipt']['snapshot'],self.request['snapshot'])

    def test_corrupt_blob_path_origin_size_and_write_readback_fail_closed(self):
        self.publish();old_get=self.client.get
        for field,value in [('pathname','other'),('url','https://attacker.invalid/x'),('size',True),('content_type','text/html')]:
            def get(key,**kw):
                result=old_get(key,**kw)
                if result is not None and '/name-bound-result-' in key:setattr(result,field,value)
                return result
            self.client.get=get
            with self.subTest(field=field),self.assertRaises(ValueError):self.read()
        self.setUp();old_get=self.client.get
        def corrupt(key,**kw):
            result=old_get(key,**kw)
            if result is not None and '/name-bound-result-packets/' in key:result.content=b'{}'
            return result
        self.client.get=corrupt
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any('/name-bound-result-receipts/' in k for k in self.client.data))

    def test_aggregate_bound_rejects_before_finalization(self):
        self.publish();envelope=self.read();bound=len(facts.canonical(envelope))-1
        self.setUp()
        with patch.dict(self.s.validate_name_bound_result_envelope.__globals__,MAX_BYTES=bound):
            with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any('/name-bound-result-finalizations/' in k for k in self.client.data))


if __name__=='__main__':unittest.main()
