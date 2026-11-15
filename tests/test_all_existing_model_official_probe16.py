"""Fixed sixteen-profile synthetic grants; no live key/source/Git operation."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import importlib
import unittest
from unittest.mock import patch

from race_ai import all_existing_model_official_recovery as legacy
from race_ai.boat_all_model_store import open_forecasts,forecast_header,seal_forecasts
from tests import test_all_existing_model_official_recovery as old


def fixture():
    data,body,cipher=old.fixture();data=deepcopy(data)
    data['request'].update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4',
        mode='FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE_16')
    data['new_plan']['maximum_requests']=16
    data.update(prior_runs=[],prior_journal_archives=[dict(raw=data['old_journal_raw'],metadata=data['old_journal_metadata'])])
    return data,body,cipher


def with_known_prior(change=None):
    from tests.test_all_existing_model_official_continuation import zipped,metadata,pin
    data,body,_=fixture();body=deepcopy(body);body.pop('browser_attempt')
    body.update(workflow_run_id=91,code_sha='c'*40)
    if change=='denied':body['attempts'][0].update(state='DENIED',http_status=403)
    if change=='unknown':body['browser_attempt']=dict(state='RESERVED',reserved_request_limit=24,
        started_at=body['attempts'][-1]['finished_at'])
    if change=='missing_outcome':body['attempts'][0]['http_status']=None
    raw=zipped(seal_forecasts(body,run_id='91',round_no=900006,key=old.KEY),'collection.enc')
    saved=old.NOW-timedelta(hours=2)+timedelta(seconds=9)
    meta=metadata(raw,9100,'official-result-collection-journal-91',91,'c'*40,saved)
    prior=dict(data['old_run'],id=91,head_sha='c'*40,run_attempt=2,updated_at=saved.isoformat())
    data['request']['manifest']['prior_journal_artifacts'].append(pin(meta))
    data['prior_journal_archives'].append(dict(raw=raw,metadata=meta));data['prior_runs']=[prior]
    return data


class SixteenProbeTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_official_probe16'),
                             'explicit sixteen-profile grant is absent')
        return importlib.import_module('race_ai.all_existing_model_official_probe16')
    def test_distinct_mac_codec_real_synthetic_issue_and_fixed_attempt_validation(self):
        api=self.module();data,_,_=fixture();before=deepcopy(data)
        raw=api.issue_consume_capsule(data,old.KEY)
        active=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(raw,data=data,current_run=active,now=old.NOW,key=old.KEY)
        self.assertEqual(auth.audit()['maximum_new_requests'],16)
        self.assertIsNone(auth.audit()['old_source_requests_actual'])
        self.assertEqual(auth.audit()['old_source_requests_upper_bound'],32)
        self.assertNotEqual(api.SCHEMA,legacy.SCHEMA);self.assertNotEqual(api.DOMAIN,legacy.DOMAIN)
        self.assertNotEqual(api.ROUND,legacy.ROUND);self.assertEqual(forecast_header(raw)['round_no'],api.ROUND)
        self.assertEqual(open_forecasts(raw,key=old.KEY)['body']['new_plan']['maximum_requests'],16)
        self.assertEqual(data,before)
    def test_new_profile_is_fixed_sixteen_and_legacy_eight_stays_eight(self):
        api=self.module();data,_,_=fixture()
        for cap in (8,12,15,17,32,True,16.0):
            changed=deepcopy(data);changed['new_plan']['maximum_requests']=cap
            with self.subTest(cap=cap),self.assertRaises(ValueError):api.issue_consume_capsule(changed,old.KEY)
        with self.assertRaises(ValueError):legacy.issue_consume_capsule(data,old.KEY)
        unchanged,_,_=old.fixture();raw=legacy.issue_consume_capsule(unchanged,old.KEY)
        self.assertEqual(open_forecasts(raw,key=old.KEY)['body']['maximum_new_requests'],8)
    def test_exact_all_prior_archive_coverage_and_non_overridable_denials(self):
        api=self.module()
        for change in ('missing','duplicate','metadata','extra'):
            data,_,_=fixture()
            if change=='missing':data['prior_journal_archives']=[]
            elif change=='duplicate':data['prior_journal_archives']*=2
            elif change=='metadata':data['prior_journal_archives'][0]['metadata']=dict(data['old_journal_metadata'],digest='sha256:'+'f'*64)
            else:data['prior_journal_archives'].append(dict(raw=b'not-an-archive',metadata={'id':90000}))
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_consume_capsule(data,old.KEY)
    def test_case_url_terms_native_and_clock_changes_still_hold(self):
        api=self.module()
        for change in ('case_count','url','terms','native','clock','expiry','first','attempt'):
            data,_,_=fixture()
            if change=='case_count':data['new_plan']['cases']*=2
            elif change=='url':data['new_plan']['cases'][0]['route']['ui_entry_url']+='?changed=1'
            elif change=='terms':data['new_plan']['terms_manifest']['changed']=True
            elif change=='native':data['request']['manifest']['native_artifacts'].pop()
            elif change=='clock':data['old_run']['updated_at']=(old.NOW-timedelta(minutes=20)).isoformat()
            elif change=='expiry':data['expires_at']=(old.NOW+timedelta(hours=2)).isoformat()
            elif change=='first':data['first_attempt']['conclusion']='failure'
            else:data['target']['run_attempt']=3
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_consume_capsule(data,old.KEY)
    def test_expired_wrong_attempt_or_tampered_capsule_cannot_dispatch(self):
        api=self.module();data,_,_=fixture();raw=api.issue_consume_capsule(data,old.KEY)
        active=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        for change in ('expired','attempt','head','cipher','plan'):
            current=deepcopy(active);actual=deepcopy(data);at=old.NOW;encoded=raw
            if change=='expired':at=old.NOW+timedelta(hours=2)
            elif change=='attempt':current['run_attempt']=3
            elif change=='head':current['head_sha']='f'*40
            elif change=='cipher':encoded=raw[:-1]+bytes([raw[-1]^1])
            else:actual['new_plan']['maximum_requests']=32
            with self.subTest(change=change),self.assertRaises(ValueError):
                api.validate_capsule(encoded,data=actual,current_run=current,now=at,key=old.KEY)

    def test_actions_wrapper_admits_real_synthetic_profile_and_all_original_journals(self):
        api=self.module();data,_,_=fixture();raw=api.issue_consume_capsule(data,old.KEY)
        from scripts import all_existing_model_official_result_recovery as wrapper
        from scripts import all_existing_model_official_result_collect as collector
        active=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        def run(path):
            if path.endswith('/attempts/1'):return data['first_attempt']
            if path=='actions/runs/'+str(legacy.OLD_RUN):return data['old_run']
            raise AssertionError('unexpected metadata endpoint')
        with patch.object(wrapper,'_capsule',return_value=raw),patch.object(wrapper,'_api',side_effect=run),\
             patch.object(collector.future,'metadata',return_value=data['old_journal_metadata']),\
             patch.object(collector.future,'gh',return_value=data['old_journal_raw']),\
             patch.object(collector,'load_plan',side_effect=[data['old_plan'],data['new_plan']]):
            auth=wrapper._admit(data['request'],data['target'],active,old.NOW,old.KEY)
        self.assertEqual(auth.audit()['maximum_new_requests'],16)

    def test_current_day_profile_cannot_authorize_a_wire_after_jst_midnight(self):
        api=self.module();data,_,_=fixture();issued=datetime(2026,11,7,14,59,tzinfo=timezone.utc)
        data.update(issued_at=issued.isoformat(),not_before=issued.isoformat(),
                    expires_at=(issued+timedelta(minutes=30)).isoformat())
        with self.assertRaisesRegex(ValueError,'HISTORICAL_CAPTURE_DAY_WINDOW'):
            api.issue_consume_capsule(data,old.KEY)

    def test_new_issue_requires_ten_minutes_of_initial_authorization(self):
        api=self.module();data,_,_=fixture()
        data['expires_at']=(old.NOW+timedelta(seconds=599)).isoformat()
        with self.assertRaisesRegex(ValueError,'SIXTEEN_CLOCK'):
            api.issue_consume_capsule(data,old.KEY)

    def test_every_nonfixed_prior_requires_known_outcomes_and_exact_terminal_receipt(self):
        api=self.module();data=with_known_prior();raw=api.issue_consume_capsule(data,old.KEY)
        body=open_forecasts(raw,key=old.KEY)['body']
        self.assertEqual(len(body['prior_journal_receipts']),2)
        for change in ('denied','unknown','missing_outcome','missing_run','recent_terminal','future_save'):
            wrong=with_known_prior(change)
            if change=='missing_run':wrong['prior_runs']=[]
            elif change=='recent_terminal':wrong['prior_runs'][0]['updated_at']=(old.NOW-timedelta(minutes=20)).isoformat()
            elif change=='future_save':wrong['prior_journal_archives'][-1]['metadata']['created_at']=(old.NOW+timedelta(seconds=1)).isoformat()
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_consume_capsule(wrong,old.KEY)

    def test_explicit_historical_sixteen_preserves_event_day_and_actual_capture_day(self):
        api=self.module();data,_,_=fixture();issued=old.NOW+timedelta(days=1)
        data['request']['mode']=api.HISTORICAL_MODE
        manifest=data['request']['manifest'];manifest.update(schema='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V3',
            execution_day='2026-11-08',target_event_day='2026-11-07')
        data.update(issued_at=issued.isoformat(),not_before=issued.isoformat(),expires_at=(issued+timedelta(minutes=30)).isoformat())
        raw=api.issue_consume_capsule(data,old.KEY);body=open_forecasts(raw,key=old.KEY)['body']
        self.assertEqual(body['new_plan']['execution_day'],'2026-11-07')
        self.assertEqual(body['request']['manifest']['execution_day'],'2026-11-08')
        for change in ('same_day','eight_days','wrong_mode'):
            wrong=deepcopy(data)
            if change=='same_day':wrong['request']['manifest']['target_event_day']='2026-11-08'
            elif change=='eight_days':wrong['request']['manifest']['target_event_day']='2026-10-31'
            else:wrong['request']['mode']=api.MODE
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_consume_capsule(wrong,old.KEY)


if __name__=='__main__':unittest.main()
