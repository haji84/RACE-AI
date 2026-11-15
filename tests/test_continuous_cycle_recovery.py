"""Offline continuous-worker recovery: no source requests or remote writes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from datetime import datetime,timedelta,timezone

from race_ai import cycle_recovery as recovery
from scripts import first_p0_bootstrap as bootstrap
from scripts import github_existing_cycle as runner
from tests.test_frozen_day_cycle import sample
from unittest.mock import patch


def sealed_session(**changes):
    state = dict(schema='RACE_AI_BOUNDED_REPEAT_V1', day_jst='2030-04-01', run_id=7,
                 started_at='2030-04-01T00:00:00Z', stop_at=None,
                 requests_used=300, completed_round=25, prepared_round=None,
                 halted_reason=None, source_limit=None, source_wait=None)
    state.update(changes)
    state['session_sha256'] = hashlib.sha256(json.dumps(
        state, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return state


def continuity_archive(session):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('repeat-session.json', json.dumps(session))
    raw = stream.getvalue()
    meta = dict(id=70, name='race-cycle-continuity-7', expired=False,
                created_at='2030-04-01T02:00:00Z',
                digest='sha256:' + hashlib.sha256(raw).hexdigest(),
                workflow_run=dict(id=7, head_repository_id=1416489937))
    return raw, meta


class ContinuousRecoveryTests(unittest.TestCase):
    def test_all_due_results_are_selected_without_a_default_round_count_limit(self):
        rows=[dict(race_id=f'20300401-{v:02d}-{n:02d}',cutoff_at='2030-04-01T01:00:00+00:00')
              for v in range(1,4) for n in range(1,13)]
        now=datetime(2030,4,1,3,tzinfo=timezone.utc)
        self.assertEqual(len(recovery.due_rows(rows,[],now)),len(rows))
        self.assertEqual(len(recovery.due_rows(rows,[],now,limit=1)),1)
    def test_recovery_and_bootstrap_use_second_artifact_page(self):
        _,raw,meta=sample();run=dict(id=2,created_at='2030-04-01T00:00:00Z',
            head_branch=recovery.BRANCH,event='push',status='completed')
        dummy=[dict(id=1000+n,name=f'other-{n}') for n in range(100)]
        def get(path):
            if path.startswith('actions/workflows/'):
                return json.dumps({'workflow_runs':[run]}).encode()
            if path.startswith('actions/runs/2/artifacts'):
                return json.dumps(dict(total_count=101,artifacts=[meta] if 'page=2' in path else dummy)).encode()
            if path=='actions/artifacts/1':return json.dumps(meta).encode()
            if path=='actions/artifacts/1/zip':return raw
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            restored=recovery.recover(get,'2030-04-01',current_run=3,out=Path(tmp))
        self.assertEqual(len(restored['rows']),2)
        self.assertEqual(restored['receipts'][0]['id'],1)
        with patch.object(bootstrap,'gh',side_effect=get):
            found=bootstrap.previous_first_receipt('2030-04-01',3)
        self.assertEqual(found[0],raw)

    def test_older_payloads_are_authenticated_then_kept_out_of_current_day(self):
        _,current,meta=sample()
        doc=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst='2030-03-31',predictions=[],
                 race_count=0,model_forecast_count=0,actual_purchases=False)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('forecasts.json',json.dumps(doc))
        old=stream.getvalue();oldmeta=copy.deepcopy(meta)
        oldmeta.update(id=10,name='boat-p0-existing-1',digest='sha256:'+hashlib.sha256(old).hexdigest())
        oldmeta['workflow_run']['id']=1
        runs=[dict(id=2,created_at='2030-04-01T00:00:00Z',head_branch=recovery.BRANCH,event='push',status='completed'),
              dict(id=1,created_at='2030-03-31T14:59:00Z',head_branch=recovery.BRANCH,event='push',status='completed')]
        def get(path):
            if path.startswith('actions/workflows/'):return json.dumps({'workflow_runs':runs}).encode()
            if path=='actions/runs/1/artifacts?per_page=100':return json.dumps(dict(total_count=1,artifacts=[oldmeta])).encode()
            if path=='actions/runs/2/artifacts?per_page=100':return json.dumps(dict(total_count=1,artifacts=[meta])).encode()
            if path=='actions/artifacts/1':return json.dumps(meta).encode()
            if path=='actions/artifacts/1/zip':return current
            if path=='actions/artifacts/10':return json.dumps(oldmeta).encode()
            if path=='actions/artifacts/10/zip':return old
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            restored=recovery.recover(get,'2030-04-01',current_run=3,out=Path(tmp))
        self.assertEqual(len(restored['rows']),2)
        self.assertEqual([r['id'] for r in restored['receipts']],[1])

    def test_local_original_conflict_is_retained_instead_of_silently_overwritten(self):
        _,raw,meta=sample()
        run=dict(id=2,created_at='2030-04-01T00:00:00Z',head_branch=recovery.BRANCH,
                 event='push',status='completed')
        def get(path):
            if path.startswith('actions/workflows/'):return json.dumps(dict(workflow_runs=[run])).encode()
            if path.startswith('actions/runs/2/artifacts'):return json.dumps(dict(total_count=1,artifacts=[meta])).encode()
            if path=='actions/artifacts/1':return json.dumps(meta).encode()
            if path=='actions/artifacts/1/zip':return raw
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'original-1.zip';original.write_bytes(b'conflicting retained original')
            with self.assertRaisesRegex(ValueError,'ORIGINAL_ARCHIVE_LOCAL_BYTES_CONFLICT'):
                recovery.recover(get,'2030-04-01',current_run=3,out=Path(tmp))
            self.assertEqual(original.read_bytes(),b'conflicting retained original')
    def test_artifacts_are_paginated_past_one_hundred_without_losing_receipts(self):
        first = [dict(id=n, name=f'other-{n}') for n in range(1, 101)]
        last = dict(id=101, name='boat-p0-existing-7')
        calls = []
        def get(path):
            calls.append(path)
            return json.dumps(dict(total_count=101, artifacts=[last] if 'page=2' in path else first)).encode()
        result = recovery.artifact_pages(get, 7)
        self.assertEqual([row['id'] for row in result], list(range(1, 102)))
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1].endswith('&page=2'))

    def test_empty_duplicate_and_changing_artifact_pages_fail_closed(self):
        for response in [dict(total_count=2, artifacts=[]),
                         dict(total_count=2, artifacts=[dict(id=1), dict(id=1)])]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                recovery.artifact_pages(lambda _: json.dumps(response).encode(), 7)

    def test_previous_evening_run_can_hold_next_day_artifacts(self):
        response = dict(workflow_runs=[dict(id=7, created_at='2030-03-31T14:59:00Z',
            head_branch=recovery.BRANCH, event='push', status='completed')])
        self.assertEqual([r['id'] for r in recovery.day_runs(
            lambda _: json.dumps(response).encode(), '2030-04-01', current_run=8)], [7])

    def test_final_continuity_restores_wait_and_lifetime_counters(self):
        wait = dict(state='RATE_LIMIT_WAIT', reason='SOURCE_HTTP_429',
                    retry_at='2030-04-02T01:00:00Z', http_status=429, attempts=2)
        raw, meta = continuity_archive(sealed_session(source_wait=wait,
            lifetime_requests=700, lifetime_completed_rounds=80))
        result = recovery.authenticated_source_control(raw, meta, expected_run=7)
        self.assertEqual(result['source_wait'], wait)
        self.assertEqual(result['lifetime_requests'], 700)
        self.assertEqual(result['lifetime_completed_rounds'], 80)
        self.assertEqual(result['previous_session_requests'], 300)
        self.assertEqual(result['receipt']['id'], 70)
        self.assertIsNone(result['previous_halted_reason'])

    def test_legacy_rate_wait_uses_fixed_receipt_time_and_exposes_unfinished_round(self):
        raw,meta=continuity_archive(sealed_session(halted_reason='SOURCE_HTTP_429_NO_RETRY',prepared_round=26))
        first=recovery.authenticated_source_control(raw,meta,now=datetime(2030,4,2,tzinfo=timezone.utc))
        later=recovery.authenticated_source_control(raw,meta,now=datetime(2030,4,3,tzinfo=timezone.utc))
        self.assertEqual(first['source_wait'],later['source_wait'])
        self.assertLess(datetime.fromisoformat(first['source_wait']['retry_at']),datetime(2030,4,2,tzinfo=timezone.utc))
        self.assertEqual(first['prepared_round'],26)
        self.assertEqual(first['completed_round'],25)
        self.assertIsNone(first['previous_halted_reason'])
        raw,meta=continuity_archive(sealed_session(halted_reason='SOURCE_BUDGET_EXHAUSTED'))
        self.assertIsNone(recovery.authenticated_source_control(raw,meta)['previous_halted_reason'])

    def test_source_wait_lookup_is_not_lost_after_a_long_host_outage(self):
        wait=dict(state='AUTHORIZATION_WAIT',reason='SOURCE_AUTHORIZATION_REQUIRED',
                  retry_at=None,http_status=403,attempts=1)
        raw,meta=continuity_archive(sealed_session(source_wait=wait,
            halted_reason='SOURCE_HTTP_403_NO_RETRY'))
        run=dict(id=7,created_at='2030-04-01T00:00:00Z',head_branch=recovery.BRANCH,
                 event='push',status='completed')
        def get(path):
            if path.startswith('actions/workflows/'):return json.dumps(dict(workflow_runs=[run])).encode()
            if path.startswith('actions/runs/7/artifacts'):return json.dumps(dict(total_count=1,artifacts=[meta])).encode()
            if path=='actions/artifacts/70':return json.dumps(meta).encode()
            if path=='actions/artifacts/70/zip':return raw
            raise AssertionError(path)
        control=recovery.previous_source_control(get,'2030-04-03',current_run=8)
        self.assertEqual(control['source_wait']['state'],'AUTHORIZATION_WAIT')
        self.assertIsNone(control['source_wait']['retry_at'])
        self.assertEqual(recovery.day_runs(get,'2030-04-03',current_run=8),[])

    def test_final_bootstrap_wait_is_authenticated_without_a_forecast_session(self):
        wait=dict(state='RATE_LIMIT_WAIT',reason='HTTP_RATE_LIMIT',
                  retry_at='2030-04-02T01:00:00Z',http_status=429,attempts=1)
        state=dict(schema='RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1',day_jst='2030-04-01',
                   run_id=7,requests_used=1,completed_round=0,lifetime_requests=901,
                   lifetime_completed_rounds=80,source_wait=wait,halted_reason=None)
        state['source_control_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True,
            separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('bootstrap-source-control.json',json.dumps(state))
        raw=stream.getvalue();_,meta=continuity_archive(sealed_session())
        meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
        control=recovery.authenticated_source_control(raw,meta,expected_run=7)
        self.assertEqual(control['lifetime_requests'],901)
        self.assertEqual(control['source_wait'],wait)

    def test_source_control_rejects_changed_archive_or_internal_seal(self):
        raw, meta = continuity_archive(sealed_session())
        with self.assertRaises(ValueError):
            recovery.authenticated_source_control(raw + b'changed', meta, expected_run=7)
        state = sealed_session(); state['requests_used'] = 301
        changed, changed_meta = continuity_archive(state)
        with self.assertRaises(ValueError):
            recovery.authenticated_source_control(changed, changed_meta, expected_run=7)
        for changes in (dict(lifetime_requests_base=900,lifetime_requests=1199),
                        dict(lifetime_completed_rounds_base=80,lifetime_completed_rounds=104)):
            raw,meta=continuity_archive(sealed_session(**changes))
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'source lifetime count'):
                recovery.authenticated_source_control(raw,meta,expected_run=7)

    def test_hard_denial_cannot_be_released_by_an_older_transient_wait(self):
        stale=dict(state='RATE_LIMIT_WAIT',reason='HTTP_RATE_LIMIT',
                   retry_at='2030-04-02T01:00:00Z',http_status=429,attempts=1)
        raw,meta=continuity_archive(sealed_session(
            halted_reason='SOURCE_HTTP_403_NO_RETRY',source_wait=stale))
        control=recovery.authenticated_source_control(raw,meta,expected_run=7)
        self.assertEqual(control['previous_halted_reason'],'SOURCE_HTTP_403_NO_RETRY')
        self.assertEqual(control['source_wait']['state'],'AUTHORIZATION_WAIT')
        self.assertIsNone(control['source_wait']['retry_at'])

    def test_normal_old_limit_can_handoff_but_source_review_is_not_cleared(self):
        for reason in ['BOUNDED_SESSION_END', 'SESSION_SOURCE_BUDGET_EXHAUSTED']:
            raw, meta = continuity_archive(sealed_session(halted_reason=reason))
            result = recovery.authenticated_source_control(raw, meta, expected_run=7)
            self.assertIsNone(result['previous_halted_reason'])
            self.assertEqual(result['previous_stop_reason'], reason)
        raw, meta = continuity_archive(sealed_session(halted_reason='SOURCE_HTTP_403_NO_RETRY'))
        result = recovery.authenticated_source_control(raw, meta, expected_run=7)
        self.assertEqual(result['previous_halted_reason'], 'SOURCE_HTTP_403_NO_RETRY')
        self.assertEqual(result['source_wait']['state'], 'AUTHORIZATION_WAIT')
        self.assertIsNone(result['source_wait']['retry_at'])

    def test_event_day_is_pinned_and_never_accepts_a_future_day(self):
        from datetime import datetime
        now = datetime.fromisoformat('2030-04-02T00:01:00+09:00')
        with patch.dict('os.environ', {'RACE_AI_EVENT_DAY': '2030-04-01'}):
            self.assertEqual(runner.event_day(now=now), '2030-04-01')
        with patch.dict('os.environ', {'RACE_AI_EVENT_DAY': '2030-04-03'}):
            with self.assertRaises(ValueError): runner.event_day(now=now)

    def test_capture_wait_is_not_written_as_an_original_forecast(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp, patch.object(bootstrap, 'ROOT', Path(tmp)), \
             patch.object(bootstrap, 'previous_first_receipt', return_value=None), \
             patch('scripts.existing_day_program.collect', return_value=dict(
                 day_jst='2030-04-01', failure_class='HTTPError', http_status=404,
                 source_requests=1, predictions=[], race_count=0, model_forecast_count=0)):
            result = bootstrap.capture('2030-04-01', 8,
                now=datetime(2030, 4, 1, 0, tzinfo=timezone.utc))
            self.assertEqual(result['state'], 'WAITING_PUBLICATION')
            self.assertIsNotNone(result['retry_at'])
            self.assertFalse((Path(tmp)/'boat_all_day_output/forecasts.json').exists())
            wait_path = Path(tmp)/'cycle_recovery_output/bootstrap-source-control.json'
            self.assertTrue(wait_path.is_file())

    def test_capture_wait_respects_retry_after_and_keeps_live_clock(self):
        from scripts import existing_day_program
        from tests.test_existing_day_program import program
        now=[datetime(2030,4,1,0,tzinfo=timezone.utc)];attempts=[];sleeps=[]
        def collect(*,clock,source_guard):
            source_guard.charge('forecast')
            attempts.append(clock())
            if len(attempts)==1:
                return dict(day_jst='2030-04-01',failure_class='HTTPError',http_status=404,
                            source_response_headers={'Retry-After':'300'},source_requests=1,
                            race_count=0,model_forecast_count=0,predictions=[])
            result=existing_day_program.forecast_program(program(),clock=clock)
            result['source_requests']=1
            return result
        def sleep(seconds):sleeps.append(seconds);now[0]+=timedelta(seconds=seconds)
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',return_value=None), \
             patch.object(existing_day_program,'collect',side_effect=collect):
            result=bootstrap.capture_wait('2030-04-01',8,clock=lambda:now[0],sleep=sleep,
                                           handoff_at=now[0]+timedelta(hours=1))
            control=bootstrap.bootstrap_control('2030-04-01',8)
            doc=json.loads((Path(tmp)/'boat_all_day_output/forecasts.json').read_text())
        self.assertTrue(result['capture_complete'])
        self.assertEqual(len(attempts),2)
        self.assertGreaterEqual((attempts[1]-attempts[0]).total_seconds(),300)
        self.assertEqual(control['requests_used'],2)
        self.assertIsNone(control['source_wait'])
        self.assertLessEqual(max(sleeps),30)
        self.assertEqual(doc['predictions'][0]['as_of'],attempts[1].isoformat())

    def test_bootstrap_lookup_crossing_worker_deadline_never_charges_or_fetches_b(self):
        from scripts import existing_day_program
        now=[datetime(2030,4,1,0,tzinfo=timezone.utc)]
        deadline=now[0]+timedelta(seconds=10)
        def slow_lookup(*args):
            now[0]+=timedelta(seconds=20);return None
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',side_effect=slow_lookup), \
             patch.object(existing_day_program,'collect') as collect, \
             patch.dict('os.environ',{'RACE_AI_WORKER_HANDOFF_AT':deadline.isoformat()}):
            result=bootstrap.capture('2030-04-01',8,clock=lambda:now[0])
            control=bootstrap.bootstrap_control('2030-04-01',8)
            self.assertFalse((Path(tmp)/'boat_all_day_output/forecasts.json').exists())
        collect.assert_not_called();self.assertEqual(result['state'],'WORKER_HANDOFF')
        self.assertEqual(control['requests_used'],0);self.assertEqual(control['control_reason'],'WORKER_HANDOFF')

    def test_midnight_denial_keeps_retry_after_in_bootstrap_checkpoint(self):
        from urllib.error import HTTPError
        from scripts import existing_day_program
        now=[datetime(2030,4,1,14,59,55,tzinfo=timezone.utc)]
        class Opener:
            def open(self,*args,**kwargs):
                now[0]+=timedelta(seconds=10)
                raise HTTPError('https://www1.mbrace.or.jp/',429,'wait',{'Retry-After':'3600'},None)
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',return_value=None), \
             patch.object(existing_day_program.request,'build_opener',return_value=Opener()):
            result=bootstrap.capture('2030-04-01',8,clock=lambda:now[0])
            control=bootstrap.bootstrap_control('2030-04-01',8)
        self.assertEqual(result['state'],'DAY_HANDOFF')
        self.assertEqual(control['requests_used'],1)
        self.assertEqual(control['source_wait']['state'],'RATE_LIMIT_WAIT')
        retry=datetime.fromisoformat(control['source_wait']['retry_at'])
        self.assertGreaterEqual(retry,now[0]+timedelta(hours=1))

    def test_worker_boundary_denial_keeps_retry_after_and_the_actual_attempt_count(self):
        from urllib.error import HTTPError
        from scripts import existing_day_program
        now=[datetime(2030,4,1,0,tzinfo=timezone.utc)]
        deadline=now[0]+timedelta(seconds=5)
        class Opener:
            def open(self,*args,**kwargs):
                now[0]+=timedelta(seconds=10)
                raise HTTPError('https://www1.mbrace.or.jp/',429,'wait',{'Retry-After':'3600'},None)
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',return_value=None), \
             patch.object(existing_day_program.request,'build_opener',return_value=Opener()), \
             patch.dict('os.environ',{'RACE_AI_WORKER_HANDOFF_AT':deadline.isoformat()}):
            result=bootstrap.capture('2030-04-01',8,clock=lambda:now[0])
            control=bootstrap.bootstrap_control('2030-04-01',8)
        self.assertEqual(result['state'],'WORKER_HANDOFF');self.assertEqual(control['requests_used'],1)
        self.assertEqual(control['source_wait']['state'],'RATE_LIMIT_WAIT')
        self.assertGreaterEqual(datetime.fromisoformat(control['source_wait']['retry_at']),now[0]+timedelta(hours=1))

    def test_repeat_start_imports_wait_before_any_supplement_source(self):
        from race_ai import repeated_cycle
        now=datetime(2030,4,1,0,tzinfo=timezone.utc)
        wait=dict(state='RATE_LIMIT_WAIT',reason='HTTP_RATE_LIMIT',retry_at=(now+timedelta(hours=1)).isoformat(),
                  http_status=429,attempts=1)
        control=dict(source_wait=wait,lifetime_requests=900,lifetime_completed_rounds=80,
                     previous_halted_reason=None)
        class Clock:
            @staticmethod
            def now(tz):return now
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'ROOT',Path(tmp)),patch.object(runner,'datetime',Clock), \
             patch.dict('os.environ',{'GITHUB_RUN_ID':'8','RACE_AI_FIRST_P0_CAPTURED':'false'}):
            recovered=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst='2030-04-01',
                           complete=True,source_control=control)
            repeated_cycle.write_state(Path(tmp)/'cycle_recovery_output/continuity.json',recovered,key='state_sha256')
            bootstrap.bootstrap_control('2030-04-01',8,inherited=control)
            runner.repeat_start('2030-04-01')
            path=Path(tmp)/'cycle_recovery_output/repeat-session.json'
            state=repeated_cycle.load(path)
            decision=repeated_cycle.prepare(path,1,now=now)
        self.assertEqual(state['source_wait'],wait)
        self.assertEqual(state['lifetime_requests'],900)
        self.assertEqual(state['lifetime_completed_rounds'],80)
        self.assertFalse(decision['active'])
        self.assertGreater(decision['wait_seconds'],0)

    def test_repeat_start_accounts_failed_bootstrap_gets_once(self):
        from race_ai import repeated_cycle
        now=datetime(2030,4,1,0,tzinfo=timezone.utc)
        control=dict(source_wait=None,lifetime_requests=900,lifetime_completed_rounds=80,
                     previous_halted_reason=None)
        class Clock:
            @staticmethod
            def now(tz):return now
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'ROOT',Path(tmp)),patch.object(runner,'datetime',Clock), \
             patch.dict('os.environ',{'GITHUB_RUN_ID':'8','RACE_AI_FIRST_P0_CAPTURED':'true'}):
            repeated_cycle.write_state(Path(tmp)/'cycle_recovery_output/continuity.json',
                dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst='2030-04-01',complete=True,
                     source_control=control),key='state_sha256')
            boot=bootstrap.bootstrap_control('2030-04-01',8,inherited=control)
            boot.update(requests_used=3,lifetime_requests=903);bootstrap._save_control(boot)
            first=Path(tmp)/'boat_all_day_output/forecasts.json';first.parent.mkdir()
            first.write_text(json.dumps(dict(day_jst='2030-04-01',source_requests=1,race_count=1)))
            runner.repeat_start('2030-04-01');runner.repeat_start('2030-04-01')
            state=repeated_cycle.load(Path(tmp)/'cycle_recovery_output/repeat-session.json')
        self.assertEqual(state['requests_used'],3)
        self.assertEqual(state['requests_by_kind'],{'forecast':3})
        self.assertEqual(state['lifetime_requests'],903)

    def test_repeat_start_pins_only_a_sane_future_worker_deadline(self):
        from race_ai import repeated_cycle
        now=datetime(2030,4,1,0,tzinfo=timezone.utc)
        class Clock:
            @staticmethod
            def now(tz):return now
        deadline=(now+timedelta(minutes=330)).isoformat()
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'datetime',Clock), \
             patch.dict('os.environ',{'GITHUB_RUN_ID':'8','RACE_AI_FIRST_P0_CAPTURED':'false',
                                      'RACE_AI_WORKER_HANDOFF_AT':deadline}):
            runner.repeat_start('2030-04-01')
            state=repeated_cycle.load(Path(tmp)/'cycle_recovery_output/repeat-session.json')
        self.assertEqual(state['worker_handoff_at'],deadline)
        for value in ('2030-04-01T02:00:00',(now+timedelta(hours=7)).isoformat(),now.isoformat()):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp, \
                 patch.object(runner,'ROOT',Path(tmp)),patch.object(runner,'datetime',Clock), \
                 patch.dict('os.environ',{'GITHUB_RUN_ID':'8','RACE_AI_FIRST_P0_CAPTURED':'false',
                                          'RACE_AI_WORKER_HANDOFF_AT':value}),self.assertRaises(ValueError):
                runner.repeat_start('2030-04-01')

    def test_physical_handoff_does_not_sleep_forever_on_source_wait(self):
        now=datetime(2030,4,1,0,tzinfo=timezone.utc)
        class Clock:
            @staticmethod
            def now(tz):return now
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'datetime',Clock),patch.object(runner.time,'sleep') as sleep, \
             patch.dict('os.environ',{'RACE_AI_WORKER_HANDOFF_AT':now.isoformat(),
                                     'GITHUB_OUTPUT':str(Path(tmp)/'outputs')}):
            runner.repeat_prepare('2030-04-01',1)
            outputs=(Path(tmp)/'outputs').read_text()
        self.assertIn('active=false',outputs)
        self.assertIn('reason=WORKER_HANDOFF',outputs)
        sleep.assert_not_called()

    def test_midnight_during_restore_skips_source_session_and_retains_control(self):
        now=datetime(2030,4,1,15,0,1,tzinfo=timezone.utc)
        class Clock:
            @staticmethod
            def now(tz):return now
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'ROOT',Path(tmp)),patch.object(runner,'datetime',Clock), \
             patch.dict('os.environ',{'GITHUB_RUN_ID':'8','GITHUB_OUTPUT':str(Path(tmp)/'out'),
                                     'RACE_AI_FIRST_P0_CAPTURED':'false'}):
            result=runner.repeat_start('2030-04-01')
            outputs=(Path(tmp)/'out').read_text()
            control=bootstrap.bootstrap_control('2030-04-01',8)
            self.assertFalse((Path(tmp)/'cycle_recovery_output/repeat-session.json').exists())
        self.assertEqual(result,dict(state='DAY_HANDOFF',session_ready=False))
        self.assertIn('session_ready=false',outputs)
        self.assertEqual(control['control_reason'],'DAY_HANDOFF')
        self.assertEqual(control['requests_used'],0)

    def test_each_round_discovers_new_p0_without_rewriting_previous_round(self):
        from race_ai import repeated_cycle
        from scripts import existing_day_program
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        rid=day.replace('-','')+'-01-01'
        frozen=dict(race_id=rid,stage='P0',model_id=existing_day_program.EXISTING_IDS[0])
        result=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst=day,predictions=[{'fictional':'test'}],
                    race_count=1,model_forecast_count=1,source_requests=1)
        def discover(**kwargs):
            kwargs['source_guard'].charge('forecast');return result
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'original',return_value=({},[frozen],{},b'')), \
             patch.object(runner,'load_state',return_value={'rows':[]}), \
             patch.object(existing_day_program,'collect',side_effect=discover) as collect, \
             patch.dict('os.environ',{'GITHUB_OUTPUT':str(Path(tmp)/'out')}):
            path=Path(tmp)/'cycle_recovery_output/repeat-session.json'
            repeated_cycle.start(path,day=day,run_id=8,now=now)
            runner.supplement(day,1)
            first=Path(tmp)/'p0_supplement_output/cycle-1/forecasts.json';saved=first.read_bytes()
            with self.assertRaisesRegex(ValueError,'P0_SUPPLEMENT_ALREADY_EXISTS_NO_REGENERATION'):
                runner.supplement(day,1)
            self.assertEqual(collect.call_count,1)
            runner.supplement(day,2)
            self.assertEqual(first.read_bytes(),saved)
            self.assertTrue((Path(tmp)/'p0_supplement_output/cycle-2/forecasts.json').is_file())
            self.assertEqual(collect.call_args.kwargs['already_frozen_models'],{(rid,frozen['model_id'])})
            self.assertEqual(repeated_cycle.load(path)['requests_used'],2)
            self.assertEqual((Path(tmp)/'out').read_text().count('supplement_ready=true'),2)

    def test_supplement_rate_wait_and_empty_discovery_never_upload_empty_forecast(self):
        from race_ai import repeated_cycle
        from scripts import existing_day_program
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        denied=dict(predictions=[],race_count=0,model_forecast_count=0,source_requests=1,
                    failure_class='HTTPError',http_status=429,source_response_headers={'Retry-After':'900'})
        attempts=[]
        def discover(**kwargs):
            kwargs['source_guard'].charge('forecast');attempts.append('fictional GET');return denied
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'original',return_value=({},[],{},b'')), \
             patch.object(runner,'load_state',return_value={'rows':[]}), \
             patch.object(existing_day_program,'collect',side_effect=discover), \
             patch.dict('os.environ',{'GITHUB_OUTPUT':str(Path(tmp)/'out')}):
            path=Path(tmp)/'cycle_recovery_output/repeat-session.json'
            repeated_cycle.start(path,day=day,run_id=8,now=now)
            runner.supplement(day,1);runner.supplement(day,2)
            self.assertFalse((Path(tmp)/'p0_supplement_output').exists())
            self.assertEqual(len(attempts),1)
            session=repeated_cycle.load(path)
            self.assertEqual(session['requests_used'],1)
            self.assertEqual(session['source_wait']['state'],'RATE_LIMIT_WAIT')
            self.assertEqual((Path(tmp)/'out').read_text().count('supplement_ready=false'),2)
        empty=dict(predictions=[],race_count=0,model_forecast_count=0,source_requests=1)
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'original',return_value=({},[],{},b'')), \
             patch.object(runner,'load_state',return_value={'rows':[]}), \
             patch.object(existing_day_program,'collect',return_value=empty), \
             patch.dict('os.environ',{'GITHUB_OUTPUT':str(Path(tmp)/'out')}):
            repeated_cycle.start(Path(tmp)/'cycle_recovery_output/repeat-session.json',day=day,run_id=8,now=now)
            runner.supplement(day,1)
            self.assertFalse((Path(tmp)/'p0_supplement_output').exists())
            self.assertIn('supplement_ready=false',(Path(tmp)/'out').read_text())

    def test_invalid_b_data_keeps_a_review_wait_without_inventing_an_http_status(self):
        from scripts import existing_day_program
        from race_ai import repeated_cycle
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        invalid=dict(day_jst=day,predictions=[],race_count=0,model_forecast_count=0,
                     source_requests=1,failure_class='ValueError',source_error_kind='VALIDATION',
                     reason='B_SOURCE_IDENTITY')
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',return_value=None), \
             patch.object(existing_day_program,'collect',return_value=invalid):
            bootstrap.capture(day,8,now=now)
            wait=bootstrap.bootstrap_control(day,8)['source_wait']
        self.assertEqual(wait['state'],'SOURCE_REVIEW_WAIT')
        self.assertIsNone(wait['http_status']);self.assertIsNone(wait['retry_at'])
        def discover(**kwargs):
            kwargs['source_guard'].charge('forecast');return invalid
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'original',return_value=({},[],{},b'')), \
             patch.object(runner,'load_state',return_value={'rows':[]}), \
             patch.object(existing_day_program,'collect',side_effect=discover):
            path=Path(tmp)/'cycle_recovery_output/repeat-session.json'
            repeated_cycle.start(path,day=day,run_id=8,now=now)
            runner.supplement(day,1)
            wait=repeated_cycle.load(path)['source_wait']
            self.assertFalse((Path(tmp)/'p0_supplement_output').exists())
        self.assertEqual(wait['state'],'SOURCE_REVIEW_WAIT')
        self.assertIsNone(wait['http_status']);self.assertIsNone(wait['retry_at'])

    def test_unsupported_result_format_remains_pending_and_all_other_due_races_continue(self):
        from race_ai import repeated_cycle,official_race_updates as updates
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        due=[dict(race_id=day.replace('-','')+f'-{v:02d}-{n:02d}')
             for v in range(1,4) for n in range(1,13)]
        class Response:
            status=200
            def __init__(self,url):self.url=url
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'fictional result bytes'
            def geturl(self):return self.url
        class Opener:
            def open(self,req,timeout):return Response(req.full_url)
        attempts=[]
        def parse(raw,**kwargs):
            attempts.append(kwargs['race_no'])
            if len(attempts)==1:raise ValueError('payout-only auxiliary facts unsupported')
            return dict(race_id=day.replace('-','')+f'-{kwargs["venue"]}-{kwargs["race_no"]:02d}',
                        state='FICTIONAL_TEST_OBSERVATION')
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner.request,'build_opener',return_value=Opener()), \
             patch.object(updates,'parse_update',side_effect=parse),patch.object(runner.time,'sleep'):
            path=Path(tmp)/'repeat-session.json';repeated_cycle.start(path,day=day,run_id=8,now=now)
            observations,failures,count=runner.observe_due_results(due,[],day,repeated_cycle.SourceGuard(path))
            session=repeated_cycle.load(path)
        self.assertEqual(count,len(due));self.assertEqual(len(observations),len(due)-1)
        self.assertEqual(len(failures),1);self.assertEqual(failures[0]['state'],'SOURCE_OR_PARSE_UNAVAILABLE')
        self.assertIsNone(session['source_wait']);self.assertEqual(session['requests_used'],len(due))

    def test_definite_result_source_identity_conflict_quarantines_before_next_race(self):
        from race_ai import repeated_cycle,official_race_updates as updates
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        due=[dict(race_id=day.replace('-','')+f'-01-{n:02d}') for n in (1,2)]
        class Response:
            status=200
            def __init__(self,url):self.url=url
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'fictional result bytes'
            def geturl(self):return 'https://example.test/wrong-source' if wrong_url else self.url
        class Opener:
            def open(self,req,timeout):return Response(req.full_url)
        for wrong_url in (True,False):
            with self.subTest(wrong_url=wrong_url),tempfile.TemporaryDirectory() as tmp, \
                 patch.object(runner.request,'build_opener',return_value=Opener()), \
                 patch.object(updates,'parse_update',side_effect=ValueError('update body day or venue mismatch')) as parser:
                path=Path(tmp)/'repeat-session.json';repeated_cycle.start(path,day=day,run_id=8,now=now)
                observations,failures,count=runner.observe_due_results(due,[],day,repeated_cycle.SourceGuard(path))
                session=repeated_cycle.load(path)
                self.assertEqual(parser.call_count,0 if wrong_url else 1)
                self.assertEqual(count,1);self.assertEqual(observations,[])
                self.assertEqual(len(failures),1);self.assertEqual(session['source_wait']['state'],'SOURCE_REVIEW_WAIT')
                self.assertIsNone(session['source_wait']['http_status'])

    def test_unsupported_b_format_is_data_pending_without_quarantining_other_races(self):
        from scripts import existing_day_program
        from race_ai import repeated_cycle
        now=datetime.now(timezone.utc);day=now.astimezone(runner.JST).date().isoformat()
        pending=dict(day_jst=day,predictions=[],race_count=0,model_forecast_count=0,source_requests=1,
                     failure_class='SourceError',source_error_kind='VALIDATION',reason='unsupported B layout')
        def discover(**kwargs):
            kwargs['source_guard'].charge('forecast');return pending
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)), \
             patch.object(runner,'original',return_value=({},[],{},b'')), \
             patch.object(runner,'load_state',return_value={'rows':[]}), \
             patch.object(existing_day_program,'collect',side_effect=discover):
            path=Path(tmp)/'cycle_recovery_output/repeat-session.json'
            repeated_cycle.start(path,day=day,run_id=8,now=now)
            result=runner.supplement(day,1)
            guard=repeated_cycle.SourceGuard(path);guard.charge('forecast')
            self.assertIsNone(repeated_cycle.load(path)['source_wait'])
            self.assertFalse((Path(tmp)/'p0_supplement_output').exists())
        self.assertEqual(result['state'],'SOURCE_DATA_PENDING')
        with tempfile.TemporaryDirectory() as tmp,patch.object(bootstrap,'ROOT',Path(tmp)), \
             patch.object(bootstrap,'previous_first_receipt',return_value=None), \
             patch.object(existing_day_program,'collect',return_value=pending):
            result=bootstrap.capture(day,8,now=now)
            wait=bootstrap.bootstrap_control(day,8)['source_wait']
        self.assertEqual(result['state'],'WAITING_PUBLICATION')
        self.assertIsNotNone(wait['retry_at']);self.assertIsNone(wait['http_status'])


if __name__ == '__main__': unittest.main()
