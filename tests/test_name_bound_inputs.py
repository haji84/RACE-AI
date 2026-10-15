"""Offline full-name source packets preserve the frozen abbreviated B."""
import copy
from datetime import timedelta
import hashlib
import importlib
import sqlite3
import unittest
from unittest.mock import patch
from tests.test_live_research_contract import fixture as base_fixture, NOW
from tests.test_official_racelist_adapter import fixture as racelist, DAY
from tests.test_official_race_updates import page, preview
from tests.test_boatcast_original import original, companion
from race_ai.official_racelist_adapter import parse_official_racelist
from race_ai.official_race_updates import parse_update, endpoint
from race_ai import official_observation_store as memory
from web import race_contract as facts, research_contract, name_binding_contract as names
from web.original_exhibition_contract import parse_original, endpoint as original_endpoint


def sha(value):return hashlib.sha256(facts.canonical(value)).hexdigest()
def rehash(value):value['snapshot_id']=sha({k:v for k,v in value.items() if k!='snapshot_id'})

def fixture():
    feed,race=base_fixture()
    race.update(race_id='20261015-18-01',closed_at='2026-10-15T08:43:00+09:00')
    feed['venues'][0]['venue']='18'
    for b in race['boats']:b['name']='松田大志' if b['lane']==1 else '選手'+str(b['lane'])
    early=NOW-timedelta(minutes=5)
    snapshot=research_contract.build_research_bundle(feed,race,early)
    baseline=dict(schema_version=1,request_id='123455-1',snapshot=snapshot,cloud_saved_at=facts.stamp(early),cloud_eligible_pre_race=True,program_sha256=snapshot['program_sha256'])
    raw=racelist().replace('08:03','08:43').replace('選手 1','松田 大志郎').encode()
    detail=parse_official_racelist(raw,day=DAY,venue='18',race_no=1,source_url=facts._endpoint(race['race_id'],'racelist'),captured_at=facts.stamp(NOW-timedelta(minutes=3)))
    proof=names.build_name_binding(detail,race,baseline_snapshot_id=snapshot['snapshot_id'],b_program_sha256=baseline['program_sha256'],generated_at=NOW-timedelta(minutes=2),now=NOW)
    receipt=dict(schema_version=1,request_id='123456-1',baseline_request_id=baseline['request_id'],snapshot=proof,runner_saved_at=facts.stamp(NOW-timedelta(seconds=90)),cloud_saved_at=facts.stamp(NOW-timedelta(seconds=80)),cloud_eligible_pre_race=True,baseline_snapshot_id=snapshot['snapshot_id'],b_program_sha256=baseline['program_sha256'],program_identity_sha256=facts.program_digest(race))
    marker=dict(schema_version=1,race_id=race['race_id'],request_id=receipt['request_id'],baseline_request_id=baseline['request_id'],snapshot_id=proof['snapshot_id'],**{k:receipt[k] for k in ('baseline_snapshot_id','b_program_sha256','program_identity_sha256')},receipt_sha256=sha(receipt),receipt_confirmed_at=facts.stamp(NOW-timedelta(seconds=70)))
    return race,baseline,dict(receipt=receipt,finalization=marker)

def bodies():
    return (page('beforeinfo',preview().replace('選手1','松田 大志郎')),
        original().replace('選手1'.encode(),'松田 大志郎'.encode()),
        companion().replace(b'6.81',b'6.92').replace('選手1'.encode(),'松田 大志郎'.encode()))

def sources(race,binding):
    projected=names.project_name_bound_program(binding['receipt']['snapshot'],race,baseline_snapshot_id=binding['receipt']['baseline_snapshot_id'],b_program_sha256=binding['receipt']['b_program_sha256'],now=NOW)
    raw,first,second=bodies()
    observation=parse_update(raw,kind='beforeinfo',day=DAY,venue='18',race_no=1,source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at=facts.stamp(NOW-timedelta(seconds=30)),entries=projected['boats'])
    observation['rights_review']='user-confirmation-2026-10-15-official-facts'
    with sqlite3.connect(':memory:') as db,patch.object(memory,'utc_now',return_value=NOW-timedelta(seconds=29)):
        memory.setup_store(db);memory.save_observation(db,observation)
        record=memory.latest_observation(db,race['race_id'],'beforeinfo',as_of=NOW,pre_race_only=True)
    original_observation=parse_original(first,second,race=projected,source_url=original_endpoint(race['race_id'],'original'),captured_at=NOW-timedelta(seconds=20),companion_source_url=original_endpoint(race['race_id'],'standard'),companion_captured_at=NOW-timedelta(seconds=10),now=NOW)
    return record,original_observation

class InputsTests(unittest.TestCase):
    def setUp(self):
        try:self.c=importlib.import_module('web.name_bound_inputs')
        except ModuleNotFoundError:self.c=None
        self.assertIsNotNone(self.c,'separate name-bound input contract required')
        self.race,self.base,self.binding=fixture();self.record,self.original=sources(self.race,self.binding)
    def build(self,**kw):
        return self.c.build_name_bound_inputs(self.record,self.original,self.race,self.base,self.binding,parents_read_at=kw.get('parents_read_at',NOW-timedelta(seconds=60)),generated_at=kw.get('generated_at',NOW-timedelta(seconds=1)),now=kw.get('now',NOW))
    def test_full_name_projection_preserves_original_baseline_and_b(self):
        old=copy.deepcopy((self.race,self.base,self.binding));packet=self.build()
        self.assertEqual((self.race,self.base,self.binding),old)
        self.assertNotEqual(packet['program_identity_sha256'],packet['validation_program_identity_sha256'])
        self.assertEqual(packet['beforeinfo_storage_scope'],'SQLITE_MEMORY_NOT_DURABLE')
        self.assertEqual(packet['beforeinfo_record']['data']['boats'][0]['name'],'松田 大志郎')
        self.assertEqual(packet['baseline_link']['receipt_sha256'],sha(self.base))
        self.assertEqual(packet['name_binding_link']['envelope_sha256'],sha(self.binding))
        self.assertEqual(self.c.validate_name_bound_inputs(packet,self.race,self.base,self.binding,now=NOW),packet)
    def test_parent_and_generation_clocks_must_bracket_actual_sources_and_memory_save(self):
        for kw in [dict(parents_read_at=NOW-timedelta(seconds=71)),dict(parents_read_at=NOW-timedelta(seconds=29)),dict(generated_at=NOW-timedelta(seconds=11)),dict(generated_at=NOW+timedelta(seconds=1)),dict(now=NOW+timedelta(days=1))]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.build(**kw)
        self.record['saved_at']=self.race['closed_at']
        with self.assertRaises(ValueError):self.build()
    def test_tampered_pins_sha_missing_fields_and_raw_b_names_reject(self):
        packet=self.build()
        for field,value in [('snapshot_id','0'*64),('program_identity_sha256','0'*64),('validation_program_identity_sha256','0'*64),('beforeinfo_storage_scope','CLOUD')]:
            bad=copy.deepcopy(packet);bad[field]=value;rehash(bad) if field!='snapshot_id' else None
            with self.subTest(field=field),self.assertRaises(ValueError):self.c.validate_name_bound_inputs(bad,self.race,self.base,self.binding,now=NOW)
        bad=copy.deepcopy(packet);del bad['parents_read_at'];rehash(bad)
        with self.assertRaises(ValueError):self.c.validate_name_bound_inputs(bad,self.race,self.base,self.binding,now=NOW)
        self.original['boats'][0]['name']='松田大志';rehash(self.original)
        with self.assertRaises(ValueError):self.build()
    def test_display_and_original_incomplete_or_conflicting_metrics_reject(self):
        for kind in ('missing','conflict','registration','source'):
            old=copy.deepcopy(self.original)
            if kind=='missing':self.original['boats'][0]['original_times']['lap_s']=None;self.original['boats'][0]['missing_reasons']['lap_s']='SOURCE_NOT_PUBLISHED';self.original['status']='PARTIAL'
            elif kind=='conflict':self.original['boats'][0]['display_time_s']=6.91
            elif kind=='registration':self.original['boats'][0]['racer_registration_id']='4999'
            else:self.original['sources'][0]['source_url']+='?other'
            rehash(self.original)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.build()
            self.original=old
    def test_finalization_and_frozen_baseline_are_validated_before_projection(self):
        for target,field,value in [(self.binding['finalization'],'receipt_sha256','0'*64),(self.base,'cloud_eligible_pre_race',False)]:
            old=target[field];target[field]=value
            with self.assertRaises(ValueError):self.build()
            target[field]=old

if __name__=='__main__':unittest.main()
