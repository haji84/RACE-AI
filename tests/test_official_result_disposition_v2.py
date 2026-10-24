"""Synthetic six-boat results for an explicitly selected literal disposition contract."""
import copy
from datetime import date, timedelta
import hashlib
import sqlite3
import unittest
from unittest.mock import patch

from race_ai import official_race_updates as updates
from race_ai import official_observation_store as memory
from race_ai import name_bound_result_source as source
from race_ai.core import SourceError
from race_ai.tokuyama_day_worker import FetchResponse
from tests.test_official_race_updates import page,results
from tests.test_name_bound_evaluation import fixture
from web import race_contract as facts
from web.name_bound_result import validate_name_bound_result,result_context

CONTRACT='official-result-dispositions/v2'

class ResultDispositionV2Tests(unittest.TestCase):
    def setUp(self):
        self.parse=getattr(updates,'parse_result_v2',None)
        self.assertTrue(callable(self.parse),'separate opt-in v2 parser required')
        self.race,self.forecast,_,self.now=fixture()
        self.projected=result_context(self.race,self.forecast,self.now)[3]
        self.kw=dict(day=date(2026,10,15),venue='18',race_no=1,
            source_url=updates.endpoint(date(2026,10,15),'18',1,'raceresult'),captured_at=facts.stamp(self.now))
    def body(self,token='エ'):
        return page('raceresult',results().replace('<td>6</td><td class="is-boatColor6">',
            '<td>'+token+'</td><td class="is-boatColor6">').replace('選手1','松田 大志郎'))
    def stored(self,observation):
        with sqlite3.connect(':memory:') as db,patch.object(memory,'utc_now',return_value=self.now):
            memory.setup_store(db);memory.save_observation(db,observation)
            return memory.latest_observation(db,self.race['race_id'],'raceresult',as_of=self.now)
    def test_explicit_v2_preserves_literal_without_inventing_finish_or_refund(self):
        record=self.stored(self.parse(self.body(),**self.kw))
        self.assertEqual(record['result_disposition_contract'],CONTRACT)
        row=record['data']['results'][5]
        self.assertIsNone(row['finish']);self.assertEqual(row['finish_status'],'エ')
        self.assertEqual(record['data']['top3'],[1,2,3])
        self.assertEqual(record['data']['refund_boats'],[])
        self.assertFalse(record['eligible_pre_race']);self.assertFalse(record['storage_eligible_pre_race'])
        facts.validate_record(record,self.projected,self.now,require_same_day=True)
    def test_legacy_parser_still_rejects_new_literal(self):
        with self.assertRaisesRegex(SourceError,'unsupported finish disposition'):
            updates.parse_update(self.body(),kind='raceresult',**self.kw)
    def test_v2_unknown_or_compound_dispositions_still_reject(self):
        for token in ('X','エF','エンスト','?','', 'エ/失','ｴ'):
            with self.subTest(token=token),self.assertRaises(SourceError):self.parse(self.body(token),**self.kw)
    def test_normal_legacy_body_is_unchanged_except_explicit_version_field(self):
        raw=self.body('6')
        old=updates.parse_update(raw,kind='raceresult',**self.kw)
        new=self.parse(raw,**self.kw);new.pop('result_disposition_contract')
        self.assertEqual(facts.canonical(old),facts.canonical(new))
    def test_missing_wrong_or_wrong_kind_version_cannot_admit_new_literal(self):
        good=self.stored(self.parse(self.body(),**self.kw))
        for version in (None,False,'other','official-result-dispositions/v1'):
            bad=copy.deepcopy(good)
            if version is None:bad.pop('result_disposition_contract')
            else:bad['result_disposition_contract']=version
            bad['snapshot_id']=hashlib.sha256(facts.canonical({k:v for k,v in bad.items() if k not in facts.STORE_FIELDS})).hexdigest()
            with self.subTest(version=version),self.assertRaises(ValueError):facts.validate_record(bad,self.projected,self.now)
        for kind in ('beforeinfo','odds3t'):
            with self.subTest(kind=kind),self.assertRaises(SourceError):
                updates.parse_update(self.body(),kind=kind,result_disposition_contract=CONTRACT,**self.kw)
    def test_v2_rejects_name_registration_cutoff_and_source_day_conflicts(self):
        projected=[{**b,'race_id':self.race['race_id']} for b in self.projected['boats']]
        for old,new in [('4006','4999'),('選手6','別選手'),('20261015','20261014'),('08:43','08:44')]:
            raw=self.body().replace(old.encode(),new.encode())
            with self.subTest(old=old):
                try:record=self.stored(self.parse(raw,entries=projected,**self.kw));facts.validate_record(record,self.projected,self.now)
                except ValueError:pass
                else:self.fail('unbound result accepted')
    def test_separate_worker_uses_one_get_and_old_worker_remains_strict(self):
        collect=getattr(source,'collect_name_bound_result_v2',None)
        self.assertTrue(callable(collect),'separate v2 source worker required')
        from pathlib import Path
        import json
        review=json.loads(Path('config/operator-official-facts.json').read_bytes())
        review['reviewed_at']=facts.stamp(self.now-timedelta(hours=1))
        calls=[]
        def transport(url,**kw):calls.append((url,kw));return FetchResponse(self.body(),url,200,'text/html')
        arguments=dict(parents_read_at=self.race['closed_at'],facts_review=review,execute=True,transport=transport,clock=lambda:self.now)
        with patch.object(memory,'utc_now',return_value=self.now):
            old=source.collect_name_bound_result(self.race,self.forecast,**arguments)
            new=collect(self.race,self.forecast,**arguments)
        self.assertEqual(old,dict(status='SOURCE_INVALID',official_source_requests=1))
        self.assertEqual((new['status'],new['official_source_requests']),('COLLECTED',1))
        packet=validate_name_bound_result(new['snapshot'],self.race,self.forecast,now=self.now)
        self.assertEqual(packet['result_record']['result_disposition_contract'],CONTRACT)
        self.assertEqual(calls,[(self.kw['source_url'],dict(timeout=10,max_bytes=1000000))]*2)

if __name__=='__main__':unittest.main()
