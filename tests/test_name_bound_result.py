"""Synthetic independently bound result labels; no live evidence or network."""
import copy
from datetime import timedelta
import hashlib
import importlib
from pathlib import Path
import sys
import unittest

from tests.test_name_bound_evaluation import fixture
from tests.test_live_evaluation_contract import rehash as rehash_record
from web import race_contract as facts
from web.name_bound_prediction import digest

TOP = set('schema_version kind race_id date_jst closed_at program_identity_sha256 validation_program_identity_sha256 forecast_link parents_read_at generated_at result_storage_scope result_record snapshot_id'.split())
LINK = set('request_id snapshot_id envelope_sha256 baseline_request_id name_binding_request_id receipt_confirmed_at'.split())
RECEIPT = set('schema_version request_id forecast_request_id snapshot runner_saved_at cloud_saved_at cloud_eligible_pre_race'.split())
MARKER = set('schema_version race_id request_id forecast_request_id snapshot_id receipt_sha256 receipt_confirmed_at'.split())


def rehash(packet):
    packet['snapshot_id'] = hashlib.sha256(facts.canonical({k:v for k,v in packet.items() if k != 'snapshot_id'})).hexdigest()


def label_fixture(module):
    race, forecast, bundle, now = fixture()
    record = bundle['records'][0]['record']
    captured = facts._time(record['captured_at'])
    packet = module.build_name_bound_result(record, race, forecast,
        parents_read_at=captured-timedelta(seconds=1), generated_at=captured+timedelta(seconds=2), now=now)
    receipt = dict(schema_version=1, request_id='123500-1', forecast_request_id='123499-1', snapshot=packet,
        runner_saved_at=facts.stamp(captured+timedelta(seconds=3)), cloud_saved_at=facts.stamp(captured+timedelta(seconds=4)), cloud_eligible_pre_race=False)
    marker = dict(schema_version=1, race_id=race['race_id'], request_id='123500-1', forecast_request_id='123499-1',
        snapshot_id=packet['snapshot_id'], receipt_sha256=digest(receipt), receipt_confirmed_at=facts.stamp(captured+timedelta(seconds=5)))
    return race, forecast, dict(receipt=receipt, finalization=marker), now


class NameBoundResultTests(unittest.TestCase):
    def setUp(self):
        try: self.c = importlib.import_module('web.name_bound_result')
        except ModuleNotFoundError: self.c = None
        self.assertIsNotNone(self.c, 'independent result label contract required')
        self.race, self.forecast, self.bundle, self.now = fixture()
        self.record = self.bundle['records'][0]['record']
        self.capture = facts._time(self.record['captured_at'])

    def build(self, **kw):
        return self.c.build_name_bound_result(self.record, self.race, self.forecast,
            parents_read_at=kw.get('parents_read_at', self.capture-timedelta(seconds=1)),
            generated_at=kw.get('generated_at', self.capture+timedelta(seconds=2)), now=kw.get('now', self.now))

    def validate(self, packet):
        return self.c.validate_name_bound_result(packet, self.race, self.forecast, now=self.now)

    def test_full_name_label_preserves_abbreviated_b_and_every_parent_and_hash(self):
        before = copy.deepcopy((self.race, self.forecast, self.record))
        with self.assertRaises(ValueError): facts.validate_record(self.record, self.race, self.now, require_same_day=True)
        packet = self.build()
        self.assertEqual((self.race, self.forecast, self.record), before)
        self.assertEqual(set(packet), TOP)
        self.assertEqual(set(packet['forecast_link']), LINK)
        self.assertEqual((packet['schema_version'],packet['kind'],packet['result_storage_scope']),
            (1,'NAME_BOUND_OFFICIAL_RESULT_LABEL','SQLITE_MEMORY_NOT_DURABLE'))
        self.assertEqual(packet['forecast_link'], dict(request_id='123499-1', snapshot_id=self.forecast['receipt']['snapshot']['snapshot_id'],
            envelope_sha256=hashlib.sha256(facts.canonical(self.forecast)).hexdigest(), baseline_request_id='123455-1',
            name_binding_request_id='123456-1', receipt_confirmed_at=self.forecast['finalization']['receipt_confirmed_at']))
        self.assertEqual(packet['program_identity_sha256'], facts.program_digest(self.race))
        self.assertNotEqual(packet['program_identity_sha256'], packet['validation_program_identity_sha256'])
        self.assertEqual(packet['result_record'], self.record)
        unsigned = copy.deepcopy(packet); del unsigned['snapshot_id']
        self.assertEqual(packet['snapshot_id'],hashlib.sha256(facts.canonical(unsigned)).hexdigest())
        validated = self.validate(packet)
        validated['result_record']['data']['results'][0]['name']='changed'
        packet['forecast_link']['request_id']='changed'
        self.assertEqual((self.race, self.forecast, self.record), before)

    def test_context_replays_the_fully_finalized_forecast_and_detaches_projection(self):
        clock, day, close, projected, link = self.c.result_context(self.race,self.forecast,self.now)
        self.assertEqual((clock,day.isoformat(),close),(self.now,'2026-10-15',facts._time(self.race['closed_at'])))
        self.assertEqual(projected['boats'][0]['name'],'松田 大志郎')
        self.assertEqual(link['request_id'],'123499-1')
        projected['boats'][0]['name']='changed';link['request_id']='changed'
        self.assertEqual(self.race['boats'][0]['name'],'松田大志')
        self.assertEqual(self.forecast['receipt']['request_id'],'123499-1')

    def test_packet_fields_and_link_schema_cannot_be_rehashed_to_new_identity(self):
        packet = self.build()
        changes = [('schema_version', True),('schema_version',1.0),('kind','OTHER'),('race_id','20261015-18-02'),
            ('date_jst','2026-10-14'),('closed_at',self.record['captured_at']),('program_identity_sha256','0'*64),
            ('validation_program_identity_sha256','0'*64),('result_storage_scope','CLOUD'),('snapshot_id','0'*64)]
        for field,value in changes:
            bad=copy.deepcopy(packet);bad[field]=value
            if field!='snapshot_id':rehash(bad)
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.validate(bad)
        for field in LINK:
            for value in ('123498-1',None,True):
                bad=copy.deepcopy(packet);bad['forecast_link'][field]=value;rehash(bad)
                with self.subTest(link=field,value=value),self.assertRaises(ValueError):self.validate(bad)
        for field in TOP:
            bad=copy.deepcopy(packet);del bad[field]
            with self.subTest(missing=field),self.assertRaises(ValueError):self.validate(bad)
        bad=copy.deepcopy(packet);bad['extra']=1;rehash(bad)
        with self.assertRaises(ValueError):self.validate(bad)

    def test_strict_record_rejects_prefix_registration_finish_money_flags_and_status(self):
        original=copy.deepcopy(self.record)
        mutations=[lambda r:r['data']['results'][0].update(name='松田大志'),
            lambda r:r['data']['results'][0].update(name='松田大志朗'),
            lambda r:r['data']['results'][0].update(racer_registration_id='4999'),
            lambda r:r['data']['results'][0].update(finish=True),
            lambda r:r['data']['results'][0].update(verified_official=1),
            lambda r:r['data']['payouts'][0].update(payout_per_100_yen=-1),
            lambda r:r['data']['payouts'][0].update(payout_per_100_yen=True),
            lambda r:r['data'].update(top3=[2,1,3]),lambda r:r['data'].update(finish_confirmed=False),
            lambda r:r.update(status='PARTIAL'),lambda r:r.update(body_identity_verified=1),
            lambda r:r.update(eligible_pre_race=True),lambda r:r.update(storage_eligible_pre_race=True),
            lambda r:r.update(rights_review='another-review'),lambda r:r.update(source_sha256='INVALID'),
            lambda r:r.update(source_url=r['source_url']+'&other=1'),lambda r:r.update(schema_version=True)]
        for mutate in mutations:
            self.record=copy.deepcopy(original);mutate(self.record);rehash_record(self.record)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):self.build()

    def test_forecast_own_parents_race_and_finalization_are_revalidated(self):
        original=copy.deepcopy(self.forecast)
        mutations=[lambda f:f['finalization'].update(receipt_sha256='0'*64),
            lambda f:f['receipt'].update(request_id='0-1'),lambda f:f['receipt'].update(cloud_eligible_pre_race=False),
            lambda f:f['receipt']['snapshot']['models'][0]['triples'][0].update(probability=.5),
            lambda f:f['baseline'].update(request_id='123498-1'),
            lambda f:f['baseline'].update(cloud_eligible_pre_race=False),
            lambda f:f['name_binding']['finalization'].update(receipt_sha256='0'*64),
            lambda f:f['inputs']['name_binding_link'].update(request_id='123498-1')]
        for mutate in mutations:
            self.forecast=copy.deepcopy(original);mutate(self.forecast)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):self.build()
        self.forecast=original;self.race['boats'][0]['racer_registration_id']='4999'
        with self.assertRaises(ValueError):self.build()

    def test_clocks_cannot_precede_close_parent_capture_save_or_leave_race_day(self):
        close=facts._time(self.race['closed_at'])
        for kw in [dict(now=close-timedelta(microseconds=1)),dict(now=self.now+timedelta(days=1)),
            dict(now=self.now.replace(tzinfo=None)),dict(parents_read_at=close-timedelta(microseconds=1)),
            dict(parents_read_at=self.capture+timedelta(microseconds=1)),dict(parents_read_at=self.capture.replace(tzinfo=None)),
            dict(generated_at=self.capture),dict(generated_at=self.now+timedelta(microseconds=1)),
            dict(generated_at=self.now+timedelta(days=1))]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.build(**kw)
        for field in ('parents_read_at','generated_at'):
            packet=self.build();packet[field]=packet[field].replace('+00:00','Z');rehash(packet)
            with self.assertRaises(ValueError):self.validate(packet)
        original=copy.deepcopy(self.record)
        for saved in (self.capture-timedelta(seconds=1),self.now+timedelta(seconds=1),self.now+timedelta(days=1)):
            self.record=copy.deepcopy(original);self.record['saved_at']=facts.stamp(saved)
            with self.assertRaises(ValueError):self.build()

    def test_full_envelope_converts_to_existing_three_score_cloud_contract(self):
        race,forecast,envelope,now=label_fixture(self.c);before=copy.deepcopy((race,forecast,envelope))
        checked=self.c.validate_name_bound_result_envelope(envelope,race,forecast,now=now)
        self.assertEqual(set(checked),{'receipt','finalization'})
        self.assertEqual(set(checked['receipt']),RECEIPT);self.assertEqual(set(checked['finalization']),MARKER)
        bundle=self.c.result_bundle(envelope,race,forecast,now=now)
        self.assertEqual(set(bundle),{'schema_version','race_id','date_jst','closed_at','program_sha256','published_at','latest','records'})
        self.assertEqual(bundle['published_at'],envelope['finalization']['receipt_confirmed_at'])
        self.assertEqual(bundle['records'][0]['cloud_saved_at'],envelope['receipt']['cloud_saved_at'])
        self.assertEqual(bundle['records'][0]['record'],envelope['receipt']['snapshot']['result_record'])
        from web.name_bound_evaluation import build_name_bound_evaluation
        report=build_name_bound_evaluation(forecast,bundle,race,now)
        self.assertEqual((report['status'],len(report['models']),report['purchase_decision']),('EVALUATED',3,'skip'))
        self.assertEqual([m['phase'] for m in report['models']],['B_ONLY_BASELINE','DISPLAY_V2','ORIGINAL_V2'])
        self.assertFalse(report['result_proof']['financial_confirmed'])
        self.assertEqual((race,forecast,envelope),before)
        checked['receipt']['snapshot']['result_record']['data']['top3'][0]=6
        bundle['records'][0]['record']['data']['top3'][0]=6
        self.assertEqual((race,forecast,envelope),before)

    def test_envelope_exact_ids_hashes_types_and_all_io_clock_order_are_required(self):
        race,forecast,envelope,now=label_fixture(self.c)
        changes=[('receipt','schema_version',True),('receipt','request_id','01-1'),('receipt','request_id','1-0'),
            ('receipt','forecast_request_id','123498-1'),('receipt','cloud_eligible_pre_race',0),
            ('finalization','schema_version',True),('finalization','request_id','123501-1'),
            ('finalization','race_id','20261015-18-02'),('finalization','forecast_request_id','123498-1'),
            ('finalization','snapshot_id','0'*64),('finalization','receipt_sha256','0'*64)]
        for section,field,value in changes:
            bad=copy.deepcopy(envelope);bad[section][field]=value
            if section=='receipt':bad['finalization']['receipt_sha256']=digest(bad['receipt'])
            with self.subTest(section=section,field=field),self.assertRaises(ValueError):
                self.c.validate_name_bound_result_envelope(bad,race,forecast,now=now)
        for section,field in [('receipt','runner_saved_at'),('receipt','cloud_saved_at'),('finalization','receipt_confirmed_at')]:
            for value in (facts.stamp(self.capture),facts.stamp(now+timedelta(seconds=1)),facts.stamp(now+timedelta(days=1)),None,
                    envelope[section][field].replace('+00:00','Z')):
                bad=copy.deepcopy(envelope);bad[section][field]=value;bad['finalization']['receipt_sha256']=digest(bad['receipt'])
                with self.subTest(clock=field,value=value),self.assertRaises(ValueError):self.c.result_bundle(bad,race,forecast,now=now)
        for section,fields in [('receipt',RECEIPT),('finalization',MARKER)]:
            for field in fields:
                bad=copy.deepcopy(envelope);del bad[section][field]
                with self.assertRaises(ValueError):self.c.validate_name_bound_result_envelope(bad,race,forecast,now=now)
        bad=copy.deepcopy(envelope);bad['extra']=True
        with self.assertRaises(ValueError):self.c.result_bundle(bad,race,forecast,now=now)

    def test_pending_empty_and_cancelled_results_do_not_become_labels(self):
        for body in ('<p>結果はまだありません。</p>','<span class="heading1_mainLabel">レース中止</span>','<p>データがありません。</p>'):
            self.race,self.forecast,self.bundle,self.now=fixture(body)
            self.record=self.bundle['records'][0]['record']
            with self.subTest(body=body),self.assertRaises(ValueError):self.build()

    def test_standard_library_contract_imports_in_standalone_api_mode(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
        try:
            standalone=importlib.import_module('name_bound_result')
            self.assertEqual(standalone.result_context(self.race,self.forecast,self.now)[4]['request_id'],'123499-1')
        finally:sys.path.pop(0)


if __name__=='__main__':unittest.main()
