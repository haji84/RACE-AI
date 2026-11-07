"""Authored immutable rejected-wire proof; no real key, source or network."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import base64
import importlib
import importlib.util
import json
from unittest.mock import patch
import unittest
from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_continuation as continuation
from scripts import all_existing_model_official_result_collect as collector
from tests import test_official_result_browser_refund_404 as source
from tests import test_all_existing_model_prior_static_cache as statics


def fixture():
    f=source.BrowserRefund404Tests();f.setUp()
    try:
        collector._write(f.root/'capture-index.json',json.dumps(f.index,indent=2).encode())
        q=collector._browser_quarantine(f.index,f.root,maximum_json=12*1024*1024)
        body=dict(epoch_started_at=(source.START-timedelta(seconds=1)).isoformat(),maximum_requests=16,attempts=[],captures=[],
            cases=[dict(sport='autorace',race_id=source.RACE,state='HOLD_BROWSER_SOURCE_VALIDATION')],
            browser_attempt=dict(state='REJECTED',actual_request_count=3,started_at=source.START.isoformat(),completed_at=f.finish.isoformat()),
            browser_index=collector._index_diagnostic(f.index,f.planned),browser_quarantine=q,
            browser_failure=dict(stage='SOURCE_VALIDATION',error_code='ALL_MODEL_OFFICIAL_COLLECT_BROWSER_SOURCE_BYTES',exception_type='ValueError'))
        return body,dict(created_at=(f.finish+timedelta(seconds=1)).isoformat()),f.finish+timedelta(hours=2)
    finally:f.doCleanups()


def api(test):
    test.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_known_rejected_wire'))
    return importlib.import_module('race_ai.all_existing_model_known_rejected_wire')


class KnownRejectedWireTests(unittest.TestCase):
    def test_complete_rejected_wire_counts_without_changing_state_or_creating_data_authority(self):
        module=api(self);body,meta,now=fixture();before=deepcopy(body)
        proof=module.known_data_rejected_wire(body,meta,now=now)
        self.assertEqual(proof['state'],'WIRE_KNOWN_DATA_REJECTED');self.assertEqual(proof['actual_request_count'],3)
        self.assertFalse(proof['source_data_admitted']);self.assertFalse(proof['reusable_static_cache_granted'])
        self.assertEqual(body,before);self.assertEqual(body['browser_attempt']['state'],'REJECTED');self.assertEqual(body['captures'],[])
    def test_optional_accounting_accepts_but_required_normal_probe_stays_complete_only(self):
        api(self);body,meta,now=fixture();before=digest(body)
        self.assertEqual(continuation._complete(body,meta,now,required=False),3)
        with self.assertRaises(ValueError):continuation._complete(body,meta,now,required=True,expected_limit=16)
        self.assertEqual(digest(body),before)
    def test_other_states_stages_missing_outcomes_and_future_saved_clock_reject(self):
        module=api(self)
        for kind in ('RESERVED','INTERRUPTED','INDEX_RECEIVED','QUARANTINE','INDEX_VALIDATION','missing_response','missing_file','bad_hash','index','inventory','future','unknown_count'):
            body,meta,now=fixture()
            if kind in ('RESERVED','INTERRUPTED','INDEX_RECEIVED'):body['browser_attempt']['state']=kind
            elif kind in ('QUARANTINE','INDEX_VALIDATION'):body['browser_failure']['stage']=kind
            elif kind=='missing_response':body['browser_index']['responses'].pop()
            elif kind=='missing_file':body['browser_quarantine']['files'].pop()
            elif kind=='bad_hash':body['browser_quarantine']['files'][0]['source_sha256']='f'*64
            elif kind=='index':body['browser_quarantine']['returned_index_sha256']='f'*64
            elif kind=='inventory':body['browser_quarantine']['inventory_sha256']='f'*64
            elif kind=='future':meta['created_at']=(source.START-timedelta(seconds=2)).isoformat()
            else:body['browser_attempt']['actual_request_count']=None
            with self.subTest(kind=kind),self.assertRaises(ValueError):module.known_data_rejected_wire(body,meta,now=now)
    def test_all_denials_remain_fail_closed_even_inside_rehashed_metadata(self):
        module=api(self)
        for kind in ('ledger','metadata','flag'):
            for status in (401,403,429):
                body,meta,now=fixture()
                if kind=='ledger':body['browser_index']['ledger'][0]['status']=status
                elif kind=='flag':body['http_access_denied']=True
                else:
                    file=next(f for f in body['browser_quarantine']['files'] if f['kind']=='HTTP_METADATA')
                    value=json.loads(base64.b64decode(file['raw_base64']));value['status']=status
                    statics.update_file(body,file['file'],collector.future.wire(value))
                with self.subTest(kind=kind,status=status),self.assertRaises(ValueError):module.known_data_rejected_wire(body,meta,now=now)
    def test_normal_prior_guard_and_nonold_probe_false_branch_accept_only_accounting(self):
        api(self);from race_ai import all_existing_model_official_probe16 as sixteen
        body,meta,now=fixture();pin=dict(id=9100,digest='sha256:'+'c'*64,run_id=91,head_sha='d'*40)
        actual=dict(meta,expires_at=(now+timedelta(days=1)).isoformat());manifest=dict(schema=collector.SCHEMA_V2,prior_journal_artifacts=[pin]);cipher=b'authored admitted cipher boundary'
        scope=dict(request={'manifest':manifest},not_before=(now-timedelta(seconds=1)).isoformat(),issued_at=(now-timedelta(seconds=1)).isoformat(),
            expires_at=(now+timedelta(minutes=1)).isoformat(),prior_journal_receipts=[dict(pin=pin,artifact_metadata=actual,cipher_sha256=sha256(cipher).hexdigest(),payload_sha256=digest(body))])
        auth=sixteen.ValidatedProbe16(scope,sixteen._CAPABILITY)
        self.assertFalse(auth.validate_prior(manifest,pin,body,cipher,actual,now))
        for authority in (None,auth):
            with patch.object(collector,'_journal_artifact',return_value=(body,cipher,actual)):
                cache={};summary=collector.prior_journals(manifest,now=now,key=bytes(range(32)),recovery_authorization=authority,private_static_cache_out=cache)
                self.assertEqual(summary['prior_journal_artifact_count'],1);self.assertEqual(cache,{})
        with patch.object(collector,'_journal_artifact',return_value=(body,cipher,actual)),self.assertRaisesRegex(ValueError,'PRIOR_EPOCH_TOO_RECENT'):
            collector.prior_journals(manifest,now=source.START+timedelta(minutes=1),key=bytes(range(32)))
    def test_rejected_wire_never_supplies_static_cache_even_when_originals_include_scripts(self):
        api(self);body,meta,_=statics.fixture();body['browser_attempt']['state']='REJECTED'
        body['browser_failure']=dict(stage='SOURCE_VALIDATION',error_code='ALL_MODEL_OFFICIAL_COLLECT_BROWSER_CASE_RESPONSES')
        now=statics.NOW;actual=dict(meta,expires_at=(now+timedelta(days=1)).isoformat());pin=dict(id=9200,digest='sha256:'+'c'*64,run_id=92,head_sha='d'*40)
        with patch.object(collector,'_journal_artifact',return_value=(body,b'fixture cipher',actual)),patch('race_ai.all_existing_model_prior_static_cache.extract_static_cache',side_effect=AssertionError('REJECTED cannot grant cache')):
            cache={};collector.prior_journals(dict(schema=collector.SCHEMA_V2,prior_journal_artifacts=[pin]),now=now,key=bytes(range(32)),private_static_cache_out=cache)
            self.assertEqual(cache,{})
