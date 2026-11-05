import copy, io, json, tempfile, unittest, zipfile, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
try:
    from race_ai import repeated_cycle as r
except ImportError:
    r = None
from race_ai import frozen_day_cycle as frozen
from race_ai import cycle_recovery as recovery
from tests.test_frozen_day_cycle import sample, observation

def stamp(s='2030-04-01T03:35:00+00:00'):
    return datetime.fromisoformat(s)

class RepeatedControllerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(r, 'bounded repeated controller not connected')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'session.json'
    def test_first_then_second_round_requires_ack_and_wait(self):
        now=stamp(); state=r.start(self.path, day='2030-04-01', run_id=99, now=now)
        first=r.prepare(self.path,1,now=now)
        self.assertTrue(first['active'])
        self.assertEqual(first['p0_name'],'boat-p0-existing-99-cycle-01')
        with self.assertRaisesRegex(ValueError,'UNCOMMITTED'):
            r.prepare(self.path, 2, now=now+timedelta(seconds=181))
        r.complete(self.path,1,now=now+timedelta(seconds=20),forecast_artifact=101,result_artifact=102)
        next_round=r.prepare(self.path,2,now=now+timedelta(seconds=30))
        self.assertFalse(next_round['active']); self.assertEqual(next_round['wait_seconds'],150)
        self.assertTrue(r.prepare(self.path,2,now=now+timedelta(seconds=180))['active'])
    def test_continuous_rounds_beyond_24_and_65minutes_then_day_handoff(self):
        now=stamp(); state=r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.assertIsNone(state['stop_at']);self.assertIsNone(state['max_rounds'])
        for number in range(1,28):
            at=now+timedelta(seconds=(number-1)*180)
            self.assertTrue(r.prepare(self.path,number,now=at)['active'])
            r.complete(self.path,number,now=at,forecast_artifact=number*2,result_artifact=number*2+1)
        self.assertEqual(r.load(self.path)['completed_round'],27)
        next_day=now+timedelta(days=1)
        self.assertEqual(r.prepare(self.path,28,now=next_day)['reason'],'DAY_HANDOFF')
        self.assertIsNone(r.load(self.path)['halted_reason'])
        with self.assertRaises(ValueError):r.start(self.path,day='2030-04-02',run_id=99,now=now)
    def test_unlimited_source_count_preserves_hash_tamper_detection(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        guard=r.SourceGuard(self.path,clock=lambda:now)
        for _ in range(257):guard.charge('forecast')
        guard.charge('result')
        current=r.load(self.path)
        self.assertEqual(current['requests_used'],258)
        self.assertEqual(current['requests_by_kind'],{'forecast':257,'result':1})
        self.assertIsNone(current['source_limit'])
        self.assertTrue(r.prepare(self.path,1,now=now)['active'])
        data=json.loads(self.path.read_text());data['requests_used']=0;self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'hash'):r.load(self.path)

    def test_over_240_count_survives_round_completion_and_restart(self):
        now=stamp();original=r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.assertIsNone(original['source_limit'])
        guard=r.SourceGuard(self.path,clock=lambda:now)
        for _ in range(241):guard.charge('forecast')
        self.assertTrue(r.prepare(self.path,1,now=now)['active'])
        r.complete(self.path,1,now=now+timedelta(seconds=20),forecast_artifact=101,result_artifact=102)
        restarted=r.start(self.path,day='2030-04-01',run_id=99,now=now+timedelta(seconds=30))
        self.assertEqual(restarted['requests_used'],241)
        self.assertEqual(restarted['started_at'],original['started_at'])
        self.assertEqual(restarted['stop_at'],original['stop_at'])
        self.assertEqual(restarted['completed_round'],1)
        self.assertEqual(len(restarted['receipts']),1)
        self.assertEqual(r.prepare(self.path,2,now=now+timedelta(seconds=30))['reason'],'POLL_INTERVAL')
        self.assertTrue(r.prepare(self.path,2,now=now+timedelta(seconds=180))['active'])

    def legacy_session(self, **changes):
        data=json.loads(self.path.read_text());data.pop('session_sha256')
        data['source_limit']=240;data.update(changes)
        raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        data['session_sha256']=hashlib.sha256(raw).hexdigest()
        self.path.write_text(json.dumps(data))

    def test_legacy_policy_metadata_and_counts_above_240_are_accepted(self):
        now=stamp();original=r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.legacy_session(requests_used=280,requests_by_kind={'forecast':280})
        self.assertEqual(r.load(self.path)['requests_used'],280)
        r.SourceGuard(self.path,clock=lambda:now).charge('result')
        after=r.load(self.path)
        self.assertEqual(after['requests_used'],281)
        self.assertIsNone(after['source_limit'])
        for field in ('started_at','stop_at','completed_round','prepared_round'):
            self.assertEqual(after[field],original[field])

    def test_authorized_numeric_policy_migration_preserves_counter_and_halt_evidence(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.legacy_session(requests_used=240,requests_by_kind={'forecast':240},
                            halted_reason='SESSION_SOURCE_BUDGET_EXHAUSTED')
        stopped=r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.assertIsNone(stopped['halted_reason'])
        self.assertEqual(stopped['policy_migration']['previous_halted_reason'],'SESSION_SOURCE_BUDGET_EXHAUSTED')
        self.assertTrue(r.prepare(self.path,1,now=now)['active'])
        r.SourceGuard(self.path,clock=lambda:now).charge('forecast')
        self.assertEqual(r.load(self.path)['requests_used'],241)

    def test_session_counter_cannot_decrease_or_become_boolean(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        r.SourceGuard(self.path,clock=lambda:now).charge('forecast')
        for invalid in (0,True,-1):
            value=r.load(self.path);value['requests_used']=invalid
            with self.assertRaises(ValueError):r.write_state(self.path,value)
        self.assertEqual(r.load(self.path)['requests_used'],1)

    def test_authorized_policy_migration_preserves_old_state_digest_and_counts(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        self.legacy_session(requests_used=241,requests_by_kind={'forecast':241},max_rounds=24,
                            stop_at=(now+timedelta(minutes=65)).isoformat(),halted_reason='BOUNDED_SESSION_END')
        old=r.load(self.path)
        out=r.start(self.path,day='2030-04-01',run_id=99,now=now+timedelta(minutes=70))
        self.assertIsNone(out['stop_at']);self.assertIsNone(out['max_rounds'])
        self.assertIsNone(out['halted_reason']);self.assertEqual(out['requests_used'],241)
        self.assertEqual(out['policy_migration']['from_session_sha256'],r._digest(old))
        self.assertEqual(out['policy_migration']['previous_halted_reason'],'BOUNDED_SESSION_END')

    def test_inherited_source_wait_and_lifetime_totals_survive_restart(self):
        now=stamp();wait=r.plan_http_wait(429,{'Retry-After':'7200'},now)
        control=dict(source_wait=wait,lifetime_requests=500,lifetime_completed_rounds=38,
                     previous_halted_reason='SOURCE_HTTP_429_NO_RETRY')
        r.start(self.path,day='2030-04-01',run_id=99,now=now,source_control=control)
        self.assertEqual(r.prepare(self.path,1,now=now)['reason'],'RATE_LIMIT_WAIT')
        guard=r.SourceGuard(self.path,clock=lambda:now)
        with self.assertRaises(r.SourceWait):guard.charge('forecast')
        self.assertEqual(r.load(self.path)['lifetime_requests'],500)
        guard=r.SourceGuard(self.path,clock=lambda:now+timedelta(seconds=7200));guard.charge('forecast')
        guard.http_success()
        r.prepare(self.path,1,now=now+timedelta(seconds=7200))
        r.complete(self.path,1,now=now+timedelta(seconds=7200),forecast_artifact=1,result_artifact=2)
        restarted=r.start(self.path,day='2030-04-01',run_id=99,now=now+timedelta(seconds=7250))
        self.assertEqual(restarted['lifetime_requests'],501)
        self.assertEqual(restarted['lifetime_completed_rounds'],39)

    def test_deadline_hint_advances_round_but_global_retry_after_wins(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        r.prepare(self.path,1,now=now)
        r.complete(self.path,1,now=now,forecast_artifact=1,result_artifact=2)
        due=now+timedelta(seconds=40)
        self.assertTrue(r.prepare(self.path,2,now=due,next_action_at=due)['active'])
        r.complete(self.path,2,now=due,forecast_artifact=3,result_artifact=4)
        r.SourceGuard(self.path,clock=lambda:due).http_failure(429,{'Retry-After':'7200'})
        out=r.prepare(self.path,3,now=due+timedelta(seconds=1),next_action_at=due)
        self.assertEqual(out['reason'],'RATE_LIMIT_WAIT')
        self.assertEqual(out['wait_seconds'],7199)

    def test_success_cannot_clear_auth_wait_or_legacy_halt(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        guard=r.SourceGuard(self.path,clock=lambda:now);guard.http_failure(403)
        guard.http_success()
        with self.assertRaises(r.SourceWait):guard.charge('result')
        state=r.load(self.path);state['halted_reason']='SOURCE_IDENTITY_OR_PARSE_STOP';r.write_state(self.path,state)
        guard.http_success()
        self.assertEqual(r.load(self.path)['halted_reason'],'SOURCE_IDENTITY_OR_PARSE_STOP')

    def test_success_never_clears_review_wait_even_with_stale_retry_timestamp(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        state=r.load(self.path);state['source_wait']=r.plan_http_wait(403,{},now)
        state['source_wait']['retry_at']=(now-timedelta(seconds=1)).isoformat()
        r.write_state(self.path,state)
        r.SourceGuard(self.path,clock=lambda:now).http_success()
        self.assertEqual(r.load(self.path)['source_wait']['state'],'AUTHORIZATION_WAIT')

    def test_hard_inherited_identity_halt_overrides_stale_timed_wait(self):
        now=stamp();wait=r.plan_http_wait(429,{},now)
        r.start(self.path,day='2030-04-01',run_id=99,now=now,source_control=dict(
            source_wait=wait,previous_halted_reason='SOURCE_IDENTITY_OR_PARSE_STOP'))
        guard=r.SourceGuard(self.path,clock=lambda:now+timedelta(hours=2))
        with self.assertRaises(r.SourceWait):guard.charge('forecast')
        self.assertIsNone(r.load(self.path)['source_wait']['retry_at'])
        self.assertIsNone(r.load(self.path)['source_wait']['http_status'])
        self.assertEqual(r.load(self.path)['requests_used'],0)

    def test_successor_normal_policy_halt_without_wait_is_not_review_blocked(self):
        now=stamp()
        r.start(self.path,day='2030-04-01',run_id=99,now=now,source_control=dict(
            previous_halted_reason='SESSION_SOURCE_BUDGET_EXHAUSTED',lifetime_requests=240))
        self.assertTrue(r.prepare(self.path,1,now=now)['active'])
        self.assertEqual(r.load(self.path)['lifetime_requests'],240)

    def test_lifetime_bases_cannot_decrease_and_complete_returns_current_totals(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now,
            source_control=dict(lifetime_requests=500,lifetime_completed_rounds=38))
        state=r.load(self.path);state['lifetime_requests_base']=499
        with self.assertRaises(ValueError):r.write_state(self.path,state)
        r.prepare(self.path,1,now=now)
        done=r.complete(self.path,1,now=now,forecast_artifact=1,result_artifact=2)
        self.assertEqual(done['lifetime_completed_rounds'],39)
    def test_http_429_waits_for_retry_after_without_charging_early(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        current=[now];guard=r.SourceGuard(self.path,clock=lambda:current[0])
        guard.charge('forecast');guard.http_failure(429,{'Retry-After':'600'})
        with self.assertRaisesRegex(ValueError,'RATE_LIMIT'):guard.charge('forecast')
        self.assertEqual(r.load(self.path)['requests_used'],1)
        self.assertEqual(r.prepare(self.path,1,now=now)['reason'],'RATE_LIMIT_WAIT')
        current[0]+=timedelta(seconds=600);guard.charge('forecast');guard.http_success()
        self.assertEqual(r.load(self.path)['requests_used'],2)
        self.assertIsNone(r.load(self.path)['source_wait'])
    def test_round_names_unbounded_no_foreign_run_or_overwrite(self):
        self.assertEqual(r.artifact_name('boat-national-cutoff',99,1),'boat-national-cutoff-99')
        self.assertEqual(r.artifact_name('boat-national-cutoff',99,2),'boat-national-cutoff-99-cycle-02')
        self.assertEqual(r.artifact_name('boat-national-cutoff',99,125),'boat-national-cutoff-99-cycle-125')
        self.assertEqual(r.artifact_name('boat-p0-existing',99,1),'boat-p0-existing-99-cycle-01')
        self.assertTrue(r.matches('boat-p0-existing-99','boat-p0-existing-99'))
        self.assertTrue(r.matches('boat-p0-existing-99-cycle-01','boat-p0-existing-99'))
        self.assertFalse(r.matches('boat-p0-existing-99-cycle-001','boat-p0-existing-99'))
        self.assertFalse(r.matches('race-existing-cycle-99-cycle-01','race-existing-cycle-99'))
        for bad in (0,-1,True):
            with self.assertRaises(ValueError):r.artifact_name('boat-national-cutoff',99,bad)
        self.assertTrue(r.matches('boat-national-cutoff-99-cycle-02','boat-national-cutoff-99'))
        self.assertTrue(r.matches('boat-national-cutoff-99-cycle-125','boat-national-cutoff-99'))
        for bad in ('boat-national-cutoff-98-cycle-02','boat-national-cutoff-99-cycle-01','boat-national-cutoff-99-cycle-002','boat-national-cutoff-99-extra'):
            self.assertFalse(r.matches(bad,'boat-national-cutoff-99'))
    def test_completion_requires_both_distinct_remote_receipts(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now);r.prepare(self.path,1,now=now)
        with self.assertRaises(ValueError):r.complete(self.path,1,now=now,forecast_artifact=10,result_artifact=10)
        self.assertEqual(r.load(self.path)['completed_round'],0)
    def test_snapshot_cache_age_day_and_original_timestamps(self):
        now=stamp();doc={'official_day_source':{'captured_at':now.isoformat(),'source_sha256':'a'*64,'url':'https://www.boatrace.jp/owpc/pc/race/index?hd=20300401', 'active_venues':['01']},'verified_active_venues':['01'],'official_race_registry':[{'race_id':'20300401-01-01','cutoff_at':'2030-04-01T15:00:00+09:00','schedule_captured_at':now.isoformat(),'source_sha256':'b'*64}]}
        original=copy.deepcopy(doc)
        self.assertTrue(r.usable_schedule(doc,day='2030-04-01',now=now+timedelta(seconds=179)))
        self.assertFalse(r.usable_schedule(doc,day='2030-04-01',now=now+timedelta(seconds=181)))
        self.assertFalse(r.usable_schedule(doc,day='2030-04-02',now=now))
        self.assertEqual(doc,original)

    def test_worker_handoff_checks_each_get_without_charge_or_persistent_halt(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        deadline=now+timedelta(seconds=1)
        state=r.load(self.path);state['worker_handoff_at']=deadline.isoformat();r.write_state(self.path,state)
        current=[now];guard=r.SourceGuard(self.path,clock=lambda:current[0])
        guard.charge('forecast')
        prior=self.path.read_bytes();current[0]=deadline
        with self.assertRaisesRegex(ValueError,'^WORKER_HANDOFF$'):guard.charge('result')
        self.assertEqual(self.path.read_bytes(),prior)
        self.assertEqual(r.load(self.path)['requests_used'],1)
        self.assertIsNone(r.load(self.path)['halted_reason'])
        self.assertIsNone(r.load(self.path)['source_wait'])

    def test_verification_failure_is_persistent_review_without_invented_http_status(self):
        now=stamp();r.start(self.path,day='2030-04-01',run_id=99,now=now)
        guard=r.SourceGuard(self.path,clock=lambda:now)
        first=guard.verification_failure()
        self.assertEqual(first,dict(state='SOURCE_REVIEW_WAIT',reason='SOURCE_VERIFICATION_REQUIRED',
            retry_at=None,http_status=None,attempts=1))
        again=guard.verification_failure('OFFICIAL_SOURCE_IDENTITY_REJECTED')
        self.assertEqual(again['attempts'],2)
        with self.assertRaises(r.SourceWait):guard.charge('forecast')
        guard.http_success()
        self.assertEqual(r.load(self.path)['source_wait'],again)
        self.assertEqual(r.load(self.path)['requests_used'],0)
        prior=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'SOURCE_VERIFICATION_REASON_INVALID'):
            guard.verification_failure('private source /tmp/raw.json')
        self.assertEqual(self.path.read_bytes(),prior)
    def test_checkpoint_keeps_first_receipt_and_results_without_duplicates(self):
        _,raw,meta=sample();_,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01')
        previous=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst='2030-04-01',rows=rows,receipts=[meta],observations=[],excluded_repeats=[],scanned_runs=[],index_entries=[],complete=True)
        target=Path(self.tmp.name)/'continuity.json';obs=observation(rows[0])
        r.checkpoint(target,previous,rows+rows,[obs,obs],[meta,meta],p1_doc=None,p1_receipt=None)
        state=recovery.load_state(target,'2030-04-01')
        self.assertEqual(len(state['rows']),2);self.assertEqual(len(state['observations']),1);self.assertEqual(len(state['receipts']),1)
        self.assertEqual(rows,state['rows'])

class RepeatedArchiveTests(unittest.TestCase):
    def test_first_round_supplement_archive_is_distinct_from_legacy_bootstrap(self):
        _,raw,meta=sample();meta['name']='boat-p0-existing-2-cycle-01'
        _,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01')
        self.assertEqual(len(rows),2)

    def test_later_round_forecast_archive_is_authenticated(self):
        d,raw,meta=sample();meta['name']='boat-p0-existing-2-cycle-02'
        parsed,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01')
        self.assertEqual(len(rows),2)
        with self.assertRaises(ValueError):frozen.read_p0(raw+b'bad',meta,expected_day='2030-04-01')
    def test_later_round_result_journal_is_recoverable(self):
        _,raw,meta=sample();_,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01');o=observation(rows[0]);b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('official-result-observations.json',json.dumps([o]))
        body=b.getvalue();receipt=dict(id=30,name='race-existing-cycle-99-cycle-02',expired=False,digest='sha256:'+hashlib.sha256(body).hexdigest(),workflow_run={'id':99,'head_repository_id':1416489937})
        self.assertEqual(recovery.result_archive(body,receipt,'2030-04-01'),[o])
    def test_new_rejected_outcome_keeps_original_forecast_provenance(self):
        _,raw,meta=sample();_,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01');o=observation(rows[0]);o['closed_at']='2030-04-01T02:01:00Z'
        verdict=frozen.evaluate(rows,[o])['per_forecast'][0]
        self.assertEqual(verdict['state'],'RESULT_REJECTED');self.assertEqual(verdict['top8'],rows[0]['top8'])

if __name__=='__main__':unittest.main()

class RepeatedWiringTests(unittest.TestCase):
    def test_schedule_cache_reuses_only_schedule_not_candidate_inputs(self):
        import race_ai
        location=str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
        if location not in race_ai.__path__: race_ai.__path__.append(location)
        from scripts import boat_nationwide_ab_pilot as pilot
        now=datetime.now(timezone.utc);day=now.astimezone(r.JST).date().isoformat()
        doc={'official_day_source':{'captured_at':now.isoformat(),'source_sha256':'a'*64,'url':'https://www.boatrace.jp/owpc/pc/race/index?hd='+day.replace('-',''),'active_venues':['01']},'verified_active_venues':['01'],'official_race_registry':[{'race_id':day.replace('-','')+'-01-01','cutoff_at':(now+timedelta(minutes=15)).astimezone(r.JST).isoformat(),'schedule_captured_at':now.isoformat(),'source_sha256':'b'*64}]}
        with tempfile.TemporaryDirectory() as temp, patch.object(pilot,'OUTPUT',Path(temp)), patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}), patch.object(pilot,'official_schedule') as discovery, patch.object(pilot,'load_original_race_ids',return_value=frozenset()), patch.object(pilot,'make_pair',return_value=({'state':'NOT_READY'},None,None,None,None)) as candidate:
            result=pilot.run(schedule_snapshot=doc)
            discovery.assert_not_called();candidate.assert_called_once()
            self.assertEqual(result['official_day_source']['captured_at'],now.isoformat())
            self.assertEqual(result['paired_forecast_count'],0)
    def test_budget_guard_is_checked_before_network(self):
        import race_ai
        location=str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
        if location not in race_ai.__path__: race_ai.__path__.append(location)
        from scripts import boat_nationwide_ab_pilot as pilot
        from unittest.mock import Mock
        guard=Mock();guard.charge.side_effect=ValueError('SESSION_SOURCE_BUDGET_EXHAUSTED')
        with patch.object(pilot,'SOURCE_GUARD',guard,create=True),patch.object(pilot.request,'build_opener') as network:
            network.side_effect=AssertionError('NETWORK_BEFORE_GUARD')
            with self.assertRaisesRegex(ValueError,'BUDGET'):pilot.get('https://www.boatrace.jp/')
            network.assert_not_called()

class RepeatedRecoveryTests(unittest.TestCase):
    def test_recover_all_round_receipts_after_job_ends(self):
        from tests.test_observed_p1_connection import inputs,archive,AT,bridge
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        records={};listed=[]
        for number in (1,2):
            b,e,p=inputs();rid=f'20300401-01-{number:02d}';b['race_id']=rid;e['race_id']=rid
            p={k:(v.replace('rno=1',f'rno={number}') if k.endswith('_url') else v) for k,v in p.items()}
            doc=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[build_pair(b,AT)],additional_official_feature_shadows=[build_live_feature_shadow(b,e,AT)],observed_pairwise_p1_bundles=[bridge.build_bundle(b,e,AT,**p,owner_reviewed=True)])
            raw,meta=archive(doc);meta['id']=1000+number;meta['name']=r.artifact_name('boat-national-cutoff',99,number)
            records[f'actions/artifacts/{meta["id"]}']=json.dumps(meta).encode();records[f'actions/artifacts/{meta["id"]}/zip']=raw;listed.append(meta)
        records[f'actions/workflows/{recovery.WORKFLOW}/runs?per_page=100&page=1']=json.dumps({'workflow_runs':[dict(id=99,status='completed',event='push',head_branch=recovery.BRANCH,created_at='2030-04-01T01:40:00Z')]}).encode()
        records['actions/runs/99/artifacts?per_page=100']=json.dumps({'total_count':2,'artifacts':listed}).encode()
        with tempfile.TemporaryDirectory() as temp:
            state=recovery.recover(lambda path:records[path],'2030-04-01',current_run=100,out=Path(temp))
            self.assertEqual(len(state['rows']),10);self.assertEqual(len(state['index_entries']),2)
            self.assertEqual(len(state['receipts']),2);self.assertEqual(state['excluded_repeats'],[])
    def test_day_handoff_stops_http_before_charging_without_poisoning_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'session.json';now=stamp()
            state=r.start(path,day='2030-04-01',run_id=99,now=now)
            guard=r.SourceGuard(path,clock=lambda:now+timedelta(days=1))
            with self.assertRaisesRegex(ValueError,'DAY_HANDOFF'):guard.charge('result')
            self.assertEqual(r.load(path)['requests_used'],0)
            self.assertIsNone(r.load(path)['halted_reason'])

def instant(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
