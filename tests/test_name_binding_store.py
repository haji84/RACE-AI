"""Synthetic immutable name proof persistence and finalization gates."""
import copy
from datetime import timedelta
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from tests.test_live_research_contract import fixture as program_fixture, NOW
from tests.test_exhibition_store import seed_baseline
from tests.test_race_cloud_store import Blob
from web import race_contract as facts, research_contract, name_binding_contract as contract

ROOT=Path(__file__).resolve().parents[1]

def fixture():
    feed,race=program_fixture()
    early=NOW-timedelta(minutes=2)
    snapshot=research_contract.build_research_bundle(feed,race,early)
    baseline=dict(schema_version=1,request_id='123455-1',snapshot=snapshot,cloud_saved_at=facts.stamp(early),
        cloud_eligible_pre_race=True,program_sha256=snapshot['program_sha256'])
    capture=NOW-timedelta(seconds=3)
    url=facts._endpoint(race['race_id'],'racelist')
    detail=dict(status='OFFICIAL_BODY_IDENTITY_VERIFIED',race_id=race['race_id'],date_jst='2026-10-15',venue='01',
        closed_at=race['closed_at'],source_url=url,source_sha256='f'*64,redistribution_authorized=False,
        first_observed_at=facts.stamp(capture),boats=[dict(**{k:b[k] for k in ('lane','racer_registration_id','name')},
            verified_source=True,race_id=race['race_id'],source_url=url,captured_at=facts.stamp(capture),closed_at=race['closed_at']) for b in race['boats']])
    proof=contract.build_name_binding(detail,race,baseline_snapshot_id=snapshot['snapshot_id'],b_program_sha256=baseline['program_sha256'],
        generated_at=NOW-timedelta(seconds=2),now=NOW)
    request=dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=race['race_id'],request_id='123456-1',
        baseline_request_id=baseline['request_id'],snapshot=proof,runner_saved_at=facts.stamp(NOW-timedelta(seconds=1)))
    return feed,race,baseline,request

class NameBindingStoreTests(unittest.TestCase):
    def setUp(self):
        try:
            with patch.object(sys,'path',[str(ROOT/'web')]+sys.path): self.store=importlib.import_module('api.name_binding_store')
        except ModuleNotFoundError:self.store=None
        self.assertIsNotNone(self.store,'independent immutable name-binding store required')
        self.feed,self.race,self.base,self.request=fixture();self.client=Blob();seed_baseline(self.client,self.base)
        self.old=copy.deepcopy(self.client.data)
    def publish(self,request=None,now=NOW,clock=None):
        return self.store.publish_name_binding(request or self.request,self.race,self.base,client=self.client,now=now,clock=clock or (lambda:now))
    def read(self,request_id=None,now=NOW):
        return self.store.read_name_binding(self.race,self.base,client=self.client,now=now,request_id=request_id)
    def test_finalization_pins_exact_receipt_and_preserves_baselines(self):
        meta=self.publish();value=self.read()
        self.assertEqual(set(value),{'receipt','finalization'})
        self.assertEqual(meta['sha256'],self.store.digest(value))
        self.assertEqual(value['finalization']['receipt_sha256'],self.store.digest(value['receipt']))
        self.assertEqual(self.store.validate_finalized_binding(value,self.race,self.base,now=NOW),value)
        self.assertEqual({k:self.client.data[k] for k in self.old},self.old)
        self.assertEqual(len(self.client.puts),4)
        self.assertTrue(all('/name-binding' in k for k,_ in self.client.puts))
        self.assertTrue(all(not opts['overwrite'] for _,opts in self.client.puts[:3]))
    def test_exact_retry_is_identical_and_changed_request_rejects(self):
        self.publish();old=self.read();puts=len(self.client.puts)
        self.publish(now=NOW+timedelta(seconds=1));self.assertEqual(self.read(now=NOW+timedelta(seconds=1)),old)
        self.assertEqual(len(self.client.puts),puts)
        for changes in [dict(runner_saved_at=facts.stamp(NOW)),dict(baseline_request_id='123454-1')]:
            with self.assertRaises(ValueError):self.publish({**self.request,**changes})
    def test_invalid_fields_pins_source_and_runner_reject_before_write(self):
        for field,value in [('extra',True),('publication_review','bad'),('request_id','../bad'),('runner_saved_at',facts.stamp(NOW+timedelta(seconds=1)))]:
            with self.subTest(field=field),self.assertRaises(ValueError):self.publish({**self.request,field:value})
        for field in ['baseline_snapshot_id','b_program_sha256','program_identity_sha256']:
            bad=copy.deepcopy(self.request);bad['snapshot'][field]='0'*64
            with self.assertRaises(ValueError):self.publish(bad)
        bad=copy.deepcopy(self.request);bad['snapshot']['source']['body_identity_verified']=False
        with self.assertRaises(ValueError):self.publish(bad)
        self.assertEqual(self.client.puts,[])
    def test_baseline_cloud_save_must_precede_source(self):
        self.base['cloud_saved_at']=facts.stamp(NOW)
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.client.puts,[])
    def test_delayed_receipt_readback_close_and_midnight_never_finalizes_or_retries(self):
        for late in [facts._time(self.race['closed_at']),NOW+timedelta(days=1)]:
            with self.subTest(late=late):
                self.client=Blob();seed_baseline(self.client,self.base)
                clocks=iter([NOW,late])
                with self.assertRaises(ValueError):self.publish(clock=lambda:next(clocks))
                self.assertTrue(any('/name-binding-receipts/' in k for k in self.client.data))
                self.assertFalse(any('/name-binding-finalizations/' in k for k in self.client.data))
                with self.assertRaises(ValueError):self.read('123456-1')
                with self.assertRaises(ValueError):self.publish(now=NOW+timedelta(seconds=1))
    def test_delayed_body_clock_leaves_no_receipt(self):
        with self.assertRaises(ValueError):self.publish(clock=lambda:facts._time(self.race['closed_at']))
        self.assertFalse(any('/name-binding-receipts/' in k for k in self.client.data))
    def test_marker_missing_mismatch_and_version_loss_fail_closed(self):
        self.publish();saved=copy.deepcopy(self.client.data)
        keys=[self.store.finalization_key(self.race['race_id'],'123456-1'),self.store.version_key(self.race['race_id'],self.request['snapshot']['snapshot_id'])]
        for key in keys:
            self.client.data=copy.deepcopy(saved);del self.client.data[key]
            with self.assertRaises(ValueError):self.read('123456-1')
        self.client.data=copy.deepcopy(saved);marker=self.store.decode(self.client.data[keys[0]])
        for field,value in [('receipt_sha256','0'*64),('request_id','999-1'),('receipt_confirmed_at',self.race['closed_at']),('schema_version',True)]:
            self.client.data[keys[0]]=facts.canonical({**marker,field:value})
            with self.assertRaises(ValueError):self.read('123456-1')
    def test_pinned_read_ignores_corrupt_latest_and_allows_after_close(self):
        self.publish();old=self.read();self.client.data[self.store.manifest_key(self.race['race_id'])]=b'corrupt'
        self.client.data[f"race-ai/predictions/{self.race['race_id']}.json"]=b'corrupt'
        self.assertEqual(self.read('123456-1',facts._time(self.race['closed_at'])+timedelta(seconds=1)),old)
        with self.assertRaises(ValueError):self.read()
    def test_older_correction_cannot_replace_newer_latest(self):
        newer=copy.deepcopy(self.request);newer['snapshot']['generated_at']=facts.stamp(NOW-timedelta(seconds=1));newer['runner_saved_at']=facts.stamp(NOW)
        unsigned={k:v for k,v in newer['snapshot'].items() if k!='snapshot_id'};newer['snapshot']['snapshot_id']=self.store.digest(unsigned)
        self.publish(newer);latest=self.read();older=copy.deepcopy(self.request);older['request_id']='123457-1'
        self.publish(older,now=NOW+timedelta(seconds=1));self.assertEqual(self.read(now=NOW+timedelta(seconds=1)),latest)
        self.assertEqual(self.read('123457-1',NOW+timedelta(seconds=1))['receipt']['request_id'],'123457-1')
    def test_latest_write_needs_fresh_preclose_check_but_finalization_remains_readable(self):
        clocks=iter([NOW,NOW,facts._time(self.race['closed_at'])])
        with self.assertRaises(ValueError):self.publish(clock=lambda:next(clocks))
        self.assertIsNotNone(self.read('123456-1'))
        self.assertIsNone(self.read())
    def test_noncanonical_receipt_bytes_cannot_replay_canonical_marker(self):
        self.publish();key=self.store.receipt_key(self.race['race_id'],'123456-1');self.client.data[key]+=b' '
        with self.assertRaises(ValueError):self.read('123456-1')
    def test_finalized_exact_retry_after_close_does_not_write_or_backdate(self):
        self.publish();old=self.read();puts=len(self.client.puts)
        after=facts._time(self.race['closed_at'])+timedelta(seconds=1)
        self.publish(now=after)
        self.assertEqual(self.read('123456-1',after),old)
        self.assertEqual(len(self.client.puts),puts)
    def test_forged_baseline_and_oversized_json_reject_before_write(self):
        original=copy.deepcopy(self.base)
        for mutate in [lambda b:b.update(cloud_eligible_pre_race=False),lambda b:b.update(request_id='../bad'),
                       lambda b:b['snapshot']['models'][0].update(probabilities=[1])]:
            self.base=copy.deepcopy(original);mutate(self.base)
            with self.assertRaises(ValueError):self.publish()
        self.base=original
        bad=copy.deepcopy(self.request);bad['snapshot']['source']['parser']='x'*64000
        with self.assertRaises(ValueError):self.publish(bad)
        self.assertEqual(self.client.puts,[])
    def test_successive_baselines_resolve_previous_proofs_own_immutable_nonce(self):
        self.publish();first=self.read();base_a=copy.deepcopy(self.base)
        baseline_bytes={k:v for k,v in self.client.data.items() if '/prediction-' in k}
        base_b=copy.deepcopy(base_a);base_b['request_id']='123458-1'
        base_b['snapshot']=research_contract.build_research_bundle(self.feed,self.race,NOW-timedelta(minutes=1))
        base_b['cloud_saved_at']=facts.stamp(NOW-timedelta(minutes=1));seed_baseline(self.client,base_b)
        self.base=base_b;new=copy.deepcopy(self.request);new['request_id']='123459-1';new['baseline_request_id']=base_b['request_id']
        new['snapshot']['baseline_snapshot_id']=base_b['snapshot']['snapshot_id']
        new['snapshot']['snapshot_id']=self.store.digest({k:v for k,v in new['snapshot'].items() if k!='snapshot_id'})
        self.client.data[f"race-ai/predictions/{self.race['race_id']}.json"]=b'corrupt mutable latest'
        self.publish(new,now=NOW+timedelta(seconds=1))
        self.assertEqual(self.read(now=NOW+timedelta(seconds=1))['receipt']['request_id'],'123459-1')
        self.assertEqual(self.read('123459-1',NOW+timedelta(seconds=1))['receipt']['baseline_request_id'],'123458-1')
        self.base=base_a;self.assertEqual(self.read('123456-1',NOW+timedelta(seconds=1)),first)
        self.assertEqual({k:self.client.data[k] for k in baseline_bytes},baseline_bytes)

if __name__=='__main__':unittest.main()
