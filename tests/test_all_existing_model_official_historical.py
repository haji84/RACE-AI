"""Explicit target-day result capture; authored fixtures, no live source/key."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import base64
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch
from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts
from tests import test_all_existing_model_official_recovery as fixtures

class HistoricalManifestTests(unittest.TestCase):
    def module(self):return importlib.import_module('race_ai.all_existing_model_official_historical')
    def test_explicit_historical_manifest_separates_current_capture_day_and_recent_target_day(self):
        api=self.module();from scripts import all_existing_model_official_result_collect as collector
        data,_,_=fixtures.fixture();now=fixtures.NOW+timedelta(days=1);manifest=deepcopy(data['request']['manifest'])
        manifest.update(schema=api.MANIFEST,execution_day='2026-11-08',target_event_day='2026-11-07')
        self.assertEqual(collector._manifest(manifest,now),manifest)
        self.assertEqual(collector.target_event_day(manifest),'2026-11-07')
        boundary=datetime(2026,11,7,15,tzinfo=timezone.utc)
        self.assertEqual(collector._manifest(manifest,boundary),manifest)
        with self.assertRaises(ValueError):collector._manifest(manifest,boundary-timedelta(microseconds=1))
        self.assertEqual(collector._manifest(dict(manifest,target_event_day='2026-11-01'),now)['target_event_day'],'2026-11-01')
        for target in ('2026-11-08','2026-11-09','2026-10-31','bad'):
            with self.subTest(target=target),self.assertRaises(ValueError):collector._manifest(dict(manifest,target_event_day=target),now)
        legacy=deepcopy(data['request']['manifest']);legacy['target_event_day']='2026-11-07'
        with self.assertRaises(ValueError):collector._manifest(legacy,fixtures.NOW)
    def test_historical_request_mode_is_explicit_and_preserves_initial_today_probe(self):
        api=self.module();from race_ai import all_existing_model_official_recovery as recovery
        data,_,_=fixtures.fixture();original=deepcopy(data['request'])
        self.assertEqual(recovery.validate_request(original,fixtures.NOW),original)
        request=deepcopy(original);request.update(schema=api.REQUEST,mode=api.PROBE_MODE)
        request['manifest'].update(schema=api.MANIFEST,execution_day='2026-11-08',target_event_day='2026-11-07')
        self.assertEqual(recovery.validate_request(request,fixtures.NOW+timedelta(days=1)),request)
        with self.assertRaises(ValueError):recovery.validate_request(dict(request,mode=original['mode']),fixtures.NOW+timedelta(days=1))

    def test_historical_authority_stops_at_actual_capture_day_midnight(self):
        api=self.module();data,_,_=fixtures.fixture();request=deepcopy(data['request'])
        request.update(schema=api.REQUEST,mode=api.PROBE_MODE)
        request['manifest'].update(schema=api.MANIFEST,execution_day='2026-11-08',target_event_day='2026-11-07')
        api.validate_window(request,'2026-11-08T23:40:00+09:00','2026-11-09T00:00:00+09:00')
        with self.assertRaises(ValueError):api.validate_window(request,'2026-11-08T23:40:00+09:00','2026-11-09T00:00:01+09:00')

class HistoricalEncryptedCollectionTests(unittest.TestCase):
    def test_historical_collection_requires_reviewed_capability_before_any_source_dispatch(self):
        from race_ai import all_existing_model_official_historical as historical
        from scripts import all_existing_model_official_result_collect as collector
        from tests import test_all_existing_model_official_result_collect as collectors
        browser=collectors.BrowserCollectorIntegrationTests(methodName='runTest');browser.setUp();f=browser.fixture
        try:
            f.clock.value+=timedelta(days=1);manifest=deepcopy(f.manifest)
            manifest.update(schema=historical.MANIFEST,execution_day='2030-01-16',target_event_day='2030-01-15',prior_journal_artifacts=[])
            calls=[]
            with patch.object(collector,'ROOT',f.repo),patch.object(collector.freeze,'frozen_inputs',return_value=[f.native]):
                with self.assertRaisesRegex(ValueError,'HISTORICAL_REVIEWED_AUTHORITY_REQUIRED'):
                    collector.collect(f.root/'unreviewed',f.env,manifest,clock=f.clock.now,sleeper=f.clock.sleep,
                        browser=lambda *_:calls.append('BROWSER'))
            self.assertEqual(calls,[])
        finally:browser.doCleanups()

    def test_actual_next_day_source_clocks_preserve_old_native_event_and_result_day(self):
        from race_ai import all_existing_model_official_historical as historical
        from race_ai import all_existing_model_official_recovery as recovery
        from scripts import all_existing_model_official_result_collect as collector
        from tests import test_all_existing_model_official_continuation as prior
        from tests import test_all_existing_model_official_result_collect as collectors
        from tests import test_all_existing_model_order_only_pdca as natives
        previous,_=prior.complete_fixture();browser=collectors.BrowserCollectorIntegrationTests(methodName='runTest');browser.setUp()
        f=browser.fixture
        try:
            old=next(item for item in previous['journal_archives'] if item['metadata']['id']==recovery.OLD_ARTIFACT)
            old_cipher=collector._journal_cipher(old['raw']);old_body=open_forecasts(old_cipher,key=fixtures.KEY)
            target='2030-01-15';start=datetime(2030,1,16,3,tzinfo=timezone.utc)
            f.day=target;f.native=deepcopy(natives.templates()['autorace'][2]);f.case=deepcopy(previous['old_plan']['cases'][0])
            plan=dict(deepcopy(previous['old_plan']),maximum_requests=8);manifest=f.sealed(plan)
            manifest.update(schema=historical.MANIFEST,execution_day='2030-01-16',target_event_day=target,
                native_artifacts=deepcopy(old_body['manifest']['native_artifacts']),checkpoint_artifacts=[],
                prior_journal_artifacts=[prior.pin(old['metadata'])],allow_order_only=True)
            request=dict(schema=historical.REQUEST,repository_id=1416489937,pull_request=71,mode=historical.PROBE_MODE,
                probe_sport='autorace',old_journal_artifact_id=recovery.OLD_ARTIFACT,manifest=manifest)
            first=deepcopy(previous['first_attempt']);first.update(id=10077,head_sha='f'*40,
                updated_at=(start-timedelta(seconds=1)).isoformat(),run_started_at=(start-timedelta(minutes=30)).isoformat())
            data=dict(request=request,target=dict(run_id=10077,head_sha='f'*40,run_attempt=2),issued_at=start.isoformat(),
                not_before=start.isoformat(),expires_at=(start+timedelta(minutes=30)).isoformat(),old_journal_raw=old['raw'],
                old_journal_metadata=old['metadata'],old_run=previous['old_run'],first_attempt=first,
                old_plan=previous['old_plan'],new_plan=plan)
            capsule=historical.issue_consume_capsule(data,fixtures.KEY)
            active=dict(first,run_attempt=2,status='in_progress',conclusion=None)
            auth=recovery.validate_capsule(capsule,request=request,current_run=active,first_attempt=first,
                old_run=previous['old_run'],now=start,key=fixtures.KEY)
            before=deepcopy(f.native);f.clock.value=start;out=f.root/'historical'
            with patch.object(collector,'ROOT',f.repo),patch.object(collector.freeze,'frozen_inputs',return_value=[f.native]), \
                patch.object(collector,'_journal_artifact',return_value=(old_body,old_cipher,old['metadata'])):
                report=collector.collect(out,dict(run_id=10077,head_sha='f'*40),manifest,clock=f.clock.now,
                    sleeper=f.clock.sleep,browser=browser.browser,recovery_authorization=auth)
            self.assertTrue(report['ready']);self.assertEqual(report['execution_day'],'2030-01-16')
            self.assertEqual(report['target_event_day'],target);self.assertEqual(f.native,before)
            payload=open_forecasts((out/'results.enc').read_bytes(),key=fixtures.KEY)
            self.assertEqual(payload['day_jst'],target);self.assertEqual(datetime.fromisoformat(payload['generated_at']).date().isoformat(),'2030-01-16')
            result=payload['observations'][0];self.assertIn(target,result['race_id']);self.assertIsNone(result['published_at'])
            self.assertEqual(datetime.fromisoformat(result['captured_at']).date().isoformat(),'2030-01-16')
            self.assertEqual(result['closed_at'],before['snapshot']['race']['sales_cutoff_at'])
            journal_raw=out.with_name(out.name+'.collection.enc').read_bytes()
            journal=collector._journal_origin(journal_raw,key=fixtures.KEY,run_id=10077,head_sha='f'*40,
                now=f.clock.now()+timedelta(seconds=3),saved_at=f.clock.now()+timedelta(seconds=2))
            self.assertEqual(journal['schema'],collector.JOURNAL_V3);self.assertEqual(journal['execution_day'],'2030-01-16')
            self.assertEqual(journal['target_event_day'],target)
            self.assertEqual(browser.seen[0]['cases'][0]['expected_date'],target)
            self.assertEqual(browser.seen[0]['not_after'],data['expires_at'])
        finally:browser.doCleanups()

    def test_next_day_continuation_replays_original_probe_without_refreshing_its_clocks(self):
        from race_ai import all_existing_model_official_historical as historical
        from race_ai import all_existing_model_official_continuation as continuation
        from tests import test_all_existing_model_official_continuation as prior
        data,old_now=prior.complete_fixture();data=deepcopy(data);before_archives=deepcopy(data['checkpoint_archives'])
        now=old_now+timedelta(days=1)
        data['request'].update(schema=historical.REQUEST,mode=historical.CONTINUATION_MODE)
        data['request']['manifest'].update(schema=historical.MANIFEST,execution_day='2030-01-16',target_event_day='2030-01-15')
        data.update(issued_at=now.isoformat(),not_before=now.isoformat(),expires_at=(now+timedelta(minutes=30)).isoformat())
        for key in ('updated_at','run_started_at'):
            data['first_attempt'][key]=(datetime.fromisoformat(data['first_attempt'][key])+timedelta(days=1)).isoformat()
        capsule=historical.issue_consume_capsule(data,fixtures.KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=continuation.validate_capsule(capsule,data=data,current_run=current,now=now,key=fixtures.KEY)
        self.assertEqual(auth.audit()['maximum_new_requests'],32)
        self.assertEqual(data['checkpoint_archives'],before_archives)

if __name__=='__main__':unittest.main()
