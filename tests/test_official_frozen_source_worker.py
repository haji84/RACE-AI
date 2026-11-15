"""Injected public Git admission seams and real legacy source authority.

No provider, owner key or remote writes; Git graph proof lives in shared tests.
"""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import inspect
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_recovery as legacy
from scripts import all_existing_model_official_result_recovery as worker
from tests.test_all_existing_model_official_recovery import fixture,KEY,HEAD,NOW
from tests.test_official_frozen_capsule import binding
from tests.test_official_recovery_preflight import jobs


class FrozenSourceWorkerTests(unittest.TestCase):
    def test_missing_frozen_output_provenance_cannot_leave_reuse_true(self):
        from tests.test_official_recovery_preflight import RecoveryPreflightTests
        from race_ai import all_existing_model_official_frozen_capsule as frozen
        from types import SimpleNamespace
        base=RecoveryPreflightTests('runTest');base.setUp();self.addCleanup(base.doCleanups)
        scope=binding(base.data['target']);base.raw=frozen.wrap_capsule(base.raw,scope,key=KEY)
        context=dict(binding=scope,snapshot=SimpleNamespace(facts={}))
        with patch.object(worker,'_trusted_environment',return_value=(base.env,base.current)),\
             patch.object(worker,'_frozen_source_context',return_value=context),\
             patch.object(worker,'_refresh_frozen'):
            status=worker.preflight(base.input,frozen_source=True)
        self.assertFalse(status['reuse_prior_verification'])

    def test_slow_fresh_intent_check_cannot_reuse_stale_three_minute_window(self):
        from tests.test_official_recovery_preflight import RecoveryPreflightTests
        from race_ai import all_existing_model_official_frozen_capsule as frozen
        base=RecoveryPreflightTests('runTest');base.setUp();self.addCleanup(base.doCleanups)
        scope=binding(base.data['target']);base.raw=frozen.wrap_capsule(base.raw,scope,key=KEY)
        base.now=legacy.clock(base.data['expires_at'])-timedelta(seconds=180)
        def delayed(*_):base.now+=timedelta(seconds=1)
        with patch.object(worker,'_trusted_environment',return_value=(base.env,base.current)),\
             patch.object(worker,'_frozen_source_context',return_value={'binding':scope}),\
             patch.object(worker,'_refresh_frozen',side_effect=delayed):
            status=worker.preflight(base.input,frozen_source=True)
        self.assertFalse(status['reuse_prior_verification'])

    def test_explicit_frozen_preflight_rejects_public_revocation_before_key(self):
        self.assertIn('check_owner_key',inspect.signature(worker._trusted_environment).parameters)
        self.assertTrue(callable(getattr(worker,'_frozen_source_context',None)))
        data,_,_=fixture();current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);request=root/'request.json';request.write_text(json.dumps(data['request']))
            env=dict(run_id=77,head_sha=HEAD,temp=root)
            with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='2'),\
                 patch.object(worker,'_trusted_environment',return_value=(env,current)) as trusted,\
                 patch.object(worker,'_frozen_source_context',side_effect=ValueError('OFFICIAL_FROZEN_SOURCE_REVOKED')),\
                 patch.object(worker,'state_key',side_effect=AssertionError('owner key before public gate')) as key,\
                 patch.object(worker.collector,'utc_now',return_value=NOW):
                status=worker.preflight(request,frozen_source=True)
            trusted.assert_called_once_with(check_owner_key=False)
            key.assert_not_called();self.assertFalse(status['reuse_prior_verification'])
            self.assertEqual(status['error_code'],'OFFICIAL_FROZEN_SOURCE_REVOKED')

    def test_typed_outer_is_unwrapped_only_for_exact_active_binding(self):
        from race_ai import all_existing_model_official_frozen_capsule as frozen
        data,body,old_cipher=fixture();inner=legacy.issue_consume_capsule(data,KEY);scope=binding(data['target'])
        outer=frozen.wrap_capsule(inner,scope,key=KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        env=dict(run_id=77,head_sha=HEAD)
        def api(path):
            if '/attempts/1' in path:return data['first_attempt']
            if path=='actions/runs/'+str(legacy.OLD_RUN):return data['old_run']
            raise AssertionError(path)
        def plan(manifest,**_):return data['old_plan'] if manifest['plan_sha256']=='f'*64 else data['new_plan']
        with patch.object(worker,'_capsule',return_value=outer),patch.object(worker,'_api',side_effect=api),\
             patch.object(worker.collector,'_journal_artifact',return_value=(body,old_cipher,data['old_journal_metadata'])),\
             patch.object(worker.collector,'load_plan',side_effect=plan):
            auth=worker._admit(data['request'],env,current,NOW,KEY,expected_binding=scope)
            self.assertEqual(auth.audit()['request_sha256'],digest(data['request']))
            wrong=dict(scope,intent_head_sha='9'*40)
            with self.assertRaises(ValueError):worker._admit(data['request'],env,current,NOW,KEY,expected_binding=wrong)
            with self.assertRaises(ValueError):worker._admit(data['request'],env,current,NOW,KEY)


class FrozenCollectorDispatchTests(unittest.TestCase):
    def test_revocation_after_native_reads_prevents_actual_browser_dispatch(self):
        from scripts import all_existing_model_official_result_collect as collector
        data,old_body,old_cipher=fixture();wire=legacy.issue_consume_capsule(data,KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=legacy.validate_capsule(wire,request=data['request'],current_run=current,first_attempt=data['first_attempt'],
            old_run=data['old_run'],now=NOW,key=KEY)
        case=data['new_plan']['cases'][0]
        native=dict(snapshot=dict(race=dict(sport='autorace',race_id=case['race_id'],event_date_jst='2026-11-07',
            sales_cutoff_at=(NOW-timedelta(hours=1)).isoformat(),venue='isesaki')))
        callbacks=[];requests=[]
        def revoked():
            callbacks.append('fresh current intent')
            raise ValueError('OFFICIAL_FROZEN_SOURCE_REVOKED')
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()),\
             patch.object(collector,'load_plan',return_value=data['new_plan']),\
             patch.object(collector,'_journal_artifact',return_value=(old_body,old_cipher,data['old_journal_metadata'])),\
             patch.object(collector.freeze,'frozen_inputs',return_value=[native]),\
             patch.object(collector.results,'_frozen',return_value=({('autorace',case['race_id']):native},'a'*64)),\
             patch.object(collector,'checkpoints',return_value={}):
            status=collector.collect(Path(temporary)/'out',dict(run_id=77,head_sha=HEAD),data['request']['manifest'],
                clock=lambda:NOW,recovery_authorization=auth,before_source=revoked,
                opener=lambda *_:requests.append('GET'),browser=lambda *_:requests.append('BROWSER'))
        self.assertEqual(callbacks,['fresh current intent']);self.assertEqual(requests,[])
        self.assertFalse(status['ready']);self.assertIsNone(status['source_requests'])

    def test_after_checkpoint_revocation_prevents_direct_http_and_preserves_unknown(self):
        from scripts import all_existing_model_official_result_collect as collector
        self.assertIn('before_source',inspect.signature(collector.Budget).parameters)
        attempts=[];writes=[];requests=[]
        journal=dict(epoch_started_at=NOW.isoformat(),execution_day=NOW.astimezone(collector.JST).date().isoformat(),
                     attempts=attempts,captures=[])
        def guard():
            if writes:raise ValueError('OFFICIAL_FROZEN_SOURCE_REVOKED')
        budget=collector.Budget(8,journal,lambda:writes.append('checkpoint'),lambda:NOW,lambda _:None,
            lambda *_:requests.append('HTTP'),before_source=guard)
        with self.assertRaisesRegex(ValueError,'REVOKED'):budget.get('https://www.jra.go.jp/JRADB/accessD.html')
        self.assertEqual(requests,[]);self.assertEqual(len(attempts),1)
        self.assertEqual(attempts[0]['state'],'RESERVED')


if __name__=='__main__':unittest.main()
