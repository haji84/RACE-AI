"""Real temporary Git refs, invented data, ephemeral non-production test key."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,subprocess,tempfile,unittest
from race_ai.boat_pdca_github_handoff import GitStateRepository,TRANSFER_REF
from race_ai.racer_daily import DailyStore
from tests.test_boat_venue_history import archive
from tests.test_racer_daily import ROSTER,NOW
try:
    from race_ai.racer_daily_handoff import load_daily,save_daily,collect_recent,PREFIX,LATEST
except ModuleNotFoundError:
    load_daily=save_daily=collect_recent=None

class LocalGit(GitStateRepository):
    def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);p=Path(self.t.name);self.repo=p/'repo';self.repo.mkdir();remote=p/'remote.git'
        for args in (['git','init','--bare',str(remote)],['git','init',str(self.repo)],['git','-C',str(self.repo),'remote','add','origin',str(remote)]):subprocess.run(args,check=True,capture_output=True)
        self.git=LocalGit(self.repo,ref=TRANSFER_REF);self.parent=self.git.commit({'state/unrelated.enc':b'PREVIOUS_UNRELATED_CIPHER'},None);self.git.push(self.parent,None)
        self.key=bytes(range(32))
    def require(self):self.assertIsNotNone(load_daily,'daily collection must connect to durable authenticated Git state')
    def test_initialize_persist_restore_and_preserve_unrelated_namespaces(self):
        self.require();loaded=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        loaded['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        catalogue=loaded['store'].catalogue(ROSTER,as_of=NOW.isoformat())
        receipt=save_daily(loaded,catalogue,key=self.key);loaded['store'].close()
        self.assertEqual(self.git.read(receipt['source_commit'],'state/unrelated.enc',100),b'PREVIOUS_UNRELATED_CIPHER')
        again=load_daily(self.repo,key=self.key,transport=self.git,now=NOW);self.addCleanup(again['store'].close)
        self.assertEqual(again['store'].catalogue(ROSTER,as_of=NOW.isoformat()),catalogue)
        self.assertEqual(again['previous']['generation'],1)
        self.assertNotIn(b'SQLite format',self.git.read(receipt['source_commit'],receipt['cipher_path'],1000000))
        self.assertNotIn(b'4001',self.git.read(receipt['source_commit'],LATEST,10000))
    def test_absent_state_requires_explicit_initialization_and_corrupt_head_never_resets(self):
        self.require()
        with self.assertRaises(ValueError):load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
        loaded=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        loaded['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        receipt=save_daily(loaded,loaded['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);loaded['store'].close()
        head=json.loads(self.git.read(receipt['source_commit'],LATEST,10000));head['as_of']='2030-01-01T00:00:00Z'
        wrong=self.git.commit({LATEST:json.dumps(head).encode()},receipt['source_commit']);self.git.push(wrong,receipt['source_commit'])
        with self.assertRaises(ValueError):load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
    def test_requests_are_bounded_and_same_day_revisions_do_not_double_count(self):
        self.require();s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close);calls=[]
        def fetch(day):calls.append(day);return archive(day=day),NOW.isoformat()
        receipt=collect_recent(s,now=NOW,fetch=fetch,max_requests=7)
        self.assertEqual(len(calls),7);self.assertEqual(receipt['requests'],7);self.assertEqual(len(set(calls)),7)
        self.assertEqual(calls[:3],['2026-11-06','2026-11-05','2026-11-04'])
        self.assertEqual(s.catalogue(ROSTER,as_of=NOW.isoformat())['people'][0]['summary']['starts'],21)
    def test_429_stops_remaining_calls_and_persists_retry_wait(self):
        self.require();from race_ai.source_retry_policy import SourceWait
        s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close);calls=[]
        def fetch(day):
            calls.append(day);raise SourceWait('SOURCE_RATE_LIMITED',(NOW+timedelta(days=2)).isoformat(),state='WAIT')
        r=collect_recent(s,now=NOW,fetch=fetch,max_requests=7)
        self.assertEqual(len(calls),1);self.assertEqual(r['status'],'SOURCE_WAIT')
        collect_recent(s,now=NOW,fetch=fetch,max_requests=7);self.assertEqual(len(calls),1)
        raw=s.serialize();copy=DailyStore.restore(raw,expected_sha256=__import__('hashlib').sha256(raw).hexdigest(),clock=lambda:NOW);self.addCleanup(copy.close)
        collect_recent(copy,now=NOW,fetch=fetch,max_requests=7);self.assertEqual(len(calls),1)
    def test_refresh_accepts_sources_captured_after_job_start_and_dates_at_finish(self):
        self.require();import base64,os
        from unittest.mock import patch
        from scripts import racer_daily_refresh as cli
        loaded=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        loaded['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        save_daily(loaded,loaded['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);loaded['store'].close()
        moment=[NOW]
        class Advancing(datetime):
            @classmethod
            def now(cls,tz=None):return moment[0]
        def local_load(repo,**kwargs):return load_daily(repo,transport=self.git,**kwargs)
        def source(day):moment[0]+=timedelta(seconds=2);return archive(day=day),moment[0].isoformat()
        def collect(store,**kwargs):return collect_recent(store,fetch=source,**kwargs)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(self.key).decode()}),patch.object(cli,'datetime',Advancing),patch.object(cli,'load_daily',local_load),patch.object(cli,'collect_recent',collect),patch.object(cli,'publish_daily_catalogue',return_value={'status':'LOCAL_ONLY'}):
            report=cli.refresh(self.repo,Path(self.t.name)/'private')
        self.assertEqual(report['status'],'DAILY_REFRESHED')
        self.assertGreater(datetime.fromisoformat(report['as_of']),NOW)
        self.assertGreater(report['new_source_files'],0)
    def test_source_review_wait_without_retry_time_is_retained_without_new_gets(self):
        self.require();from race_ai.source_retry_policy import SourceWait
        s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close);calls=[]
        def denied(day):calls.append(day);raise SourceWait('SOURCE_REVIEW_WAIT',None,state='SOURCE_REVIEW_WAIT')
        self.assertEqual(collect_recent(s,now=NOW,fetch=denied)['status'],'SOURCE_WAIT')
        collect_recent(s,now=NOW+timedelta(days=2),fetch=denied);self.assertEqual(len(calls),1)
    def test_recent_unpublished_archive_can_retry_before_next_morning_schedule(self):
        self.require();from race_ai.source_retry_policy import SourceWait
        s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close)
        def unpublished(day):
            exc=SourceWait('NOT_PUBLISHED',(NOW+timedelta(minutes=15)).isoformat(),state='WAIT');exc.plan={'http_status':404};raise exc
        collect_recent(s,now=NOW,fetch=unpublished,max_requests=1)
        self.assertFalse(s.waiting('2026-11-06',NOW+timedelta(hours=2)))
    def test_persisted_review_wait_does_not_create_daily_duplicate_checkpoints(self):
        self.require();import os,base64
        from unittest.mock import patch
        from scripts import racer_daily_refresh as cli
        loaded=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        loaded['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');loaded['store'].wait_until('*','9999-12-31T23:59:59+00:00')
        save_daily(loaded,loaded['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);loaded['store'].close();before=self.git.head()
        def local_load(repo,**kwargs):return load_daily(repo,transport=self.git,**kwargs)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(self.key).decode()}),patch.object(cli,'load_daily',local_load):
            report=cli.refresh(self.repo,Path(self.t.name)/'review-wait',now=NOW)
        self.assertEqual(report['status'],'SOURCE_WAIT');self.assertEqual(report['source_requests'],0);self.assertEqual(self.git.head(),before)
    def test_real_404_retry_policy_without_timestamp_records_a_publication_wait(self):
        self.require();from race_ai.source_retry_policy import SourceWait,plan_http_wait
        s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close)
        def actual_policy(day):
            plan=plan_http_wait(404,{},NOW);exc=SourceWait(plan['reason'],plan['retry_at'],state=plan['state']);exc.plan=plan;raise exc
        report=collect_recent(s,now=NOW,fetch=actual_policy,max_requests=1)
        self.assertEqual(report['unavailable_days'],1);self.assertTrue(s.waiting('2026-11-06',NOW))
    def test_normal_git_revert_of_daily_generation_is_rejected(self):
        self.require();first=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        first['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        a=save_daily(first,first['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);first['store'].close()
        second=load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
        second['store'].record('2026-11-05',archive(day='2026-11-05'),captured_at='2026-11-06T00:00:00Z')
        b=save_daily(second,second['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);second['store'].close()
        self.git._run(['switch','-C','revert-test',b['source_commit']])
        self.git._run(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','revert','--no-edit',b['source_commit']])
        reverted=self.git._run(['rev-parse','HEAD']).decode().strip();self.git.push(reverted,b['source_commit'])
        self.assertFalse(self.git.exists(reverted,b['cipher_path']))
        with self.assertRaisesRegex(ValueError,'DAILY_STATE_HISTORY'):
            load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
    def test_merge_cannot_hide_a_later_generation_from_reachable_history(self):
        self.require();one=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        one['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');a=save_daily(one,one['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);one['store'].close()
        two=load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
        two['store'].record('2026-11-05',archive(day='2026-11-05'),captured_at='2026-11-06T00:00:00Z');b=save_daily(two,two['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);two['store'].close()
        side=self.git.commit({'state/other-namespace.enc':b'UNRELATED_UPDATE'},a['source_commit'])
        self.git._run(['switch','-C','merge-test',side])
        self.git._run(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','merge','-s','ours','--no-edit',b['source_commit']])
        merged=self.git._run(['rev-parse','HEAD']).decode().strip();self.git.push(merged,b['source_commit'])
        with self.assertRaisesRegex(ValueError,'DAILY_STATE_HISTORY'):
            load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
    def test_unrelated_merge_preserving_the_latest_generation_can_restore(self):
        self.require();one=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        one['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');a=save_daily(one,one['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);one['store'].close()
        side=self.git.commit({'state/other-namespace.enc':b'UNRELATED_UPDATE'},a['source_commit'])
        two=load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
        two['store'].record('2026-11-05',archive(day='2026-11-05'),captured_at='2026-11-06T00:00:00Z');b=save_daily(two,two['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);two['store'].close()
        self.git._run(['switch','-C','valid-merge-test',b['source_commit']])
        self.git._run(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','merge','--no-edit',side])
        merged=self.git._run(['rev-parse','HEAD']).decode().strip();self.git.push(merged,b['source_commit'])
        restored=load_daily(self.repo,key=self.key,transport=self.git,now=NOW);self.addCleanup(restored['store'].close)
        self.assertEqual(restored['previous']['generation'],2)
    def test_fresh_runner_restores_daily_state_without_downloading_unrelated_cipher_history(self):
        from race_ai.racer_daily_handoff import DailyStateRepository
        import os
        unrelated=os.urandom(1024*1024)
        commit=self.git.commit({'state/unrelated-large-history.enc':unrelated},self.parent);self.git.push(commit,self.parent)
        large=self.git._run(['rev-parse',commit+':state/unrelated-large-history.enc']).decode().strip()
        one=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        one['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');saved=save_daily(one,one['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);one['store'].close()
        old_cipher=self.git._run(['rev-parse',saved['source_commit']+':'+saved['cipher_path']]).decode().strip()
        two=load_daily(self.repo,key=self.key,transport=self.git,now=NOW)
        two['store'].record('2026-11-05',archive(day='2026-11-05'),captured_at='2026-11-06T00:00:00Z');saved=save_daily(two,two['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);two['store'].close()
        remote=Path(self.git.fetch_url);subprocess.run(['git','-C',str(remote),'config','uploadpack.allowFilter','true'],check=True)
        receiver=Path(self.t.name)/'fresh-runner';receiver.mkdir()
        subprocess.run(['git','init',str(receiver)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(receiver),'remote','add','origin',remote.as_uri()],check=True,capture_output=True)
        class FixtureDaily(DailyStateRepository):
            def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()
        filtered=FixtureDaily(receiver,ref=TRANSFER_REF)
        restored=load_daily(receiver,key=self.key,transport=filtered,now=NOW);self.addCleanup(restored['store'].close)
        self.assertEqual(restored['previous']['generation'],2)
        self.assertEqual(filtered._run(['rev-list','--count',saved['source_commit']]).strip(),b'4')
        restored['store'].record('2026-11-06',archive(day='2026-11-06'),captured_at=NOW.isoformat())
        next_saved=save_daily(restored,restored['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key)
        self.assertEqual(next_saved['generation'],3)
        self.assertEqual(filtered._run(['rev-parse',next_saved['source_commit']+':state/unrelated-large-history.enc']).decode().strip(),large)
        present=filtered._run(['cat-file','--batch-all-objects','--batch-check=%(objectname)']).decode().splitlines()
        self.assertNotIn(large,present,'full ancestry must remain available without fetching unrelated encrypted blobs')
        self.assertNotIn(old_cipher,present,'old daily ciphertext is retained and audited through its tree identity without downloading it')
        config=subprocess.run(['git','-C',str(receiver),'config','--local','--get','remote.origin.promisor'],capture_output=True)
        self.assertEqual(config.returncode,1,'fetch settings must remain command-scoped')
    def test_runner_failure_reports_code_locations_without_command_or_source_contents(self):
        import io,sys
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from scripts import racer_daily_refresh as cli
        output=io.StringIO();error=subprocess.TimeoutExpired(['git','cat-file','PRIVATE_ARGUMENT'],60,output=b'PRIVATE_SOURCE')
        with patch.object(sys,'argv',['racer_daily_refresh','--private-dir',self.t.name]),patch.object(cli,'refresh',side_effect=error),redirect_stdout(output):
            result=cli.main()
        report=json.loads(output.getvalue());self.assertEqual(result,1)
        self.assertEqual(report['exception_type'],'TimeoutExpired');self.assertTrue(report['code_trace'])
        self.assertNotIn('PRIVATE_',output.getvalue());self.assertNotIn(self.t.name,output.getvalue())
    def test_daily_reconciliation_can_retain_without_publishing_a_k_only_catalogue(self):
        import os,base64
        from unittest.mock import patch
        from scripts import racer_daily_refresh as cli
        loaded=load_daily(self.repo,initialize=True,key=self.key,transport=self.git,now=NOW)
        loaded['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');save_daily(loaded,loaded['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=self.key);loaded['store'].close()
        def local_load(repo,**kwargs):return load_daily(repo,transport=self.git,**kwargs)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(self.key).decode()}),patch.object(cli,'load_daily',local_load),patch.object(cli,'collect_recent',return_value={'status':'NO_CHANGES','requests':0,'new_files':0}),patch.object(cli,'publish_daily_catalogue',side_effect=AssertionError('K_ONLY_MUST_NOT_BE_PUBLISHED')):
            try:report=cli.refresh(self.repo,Path(self.t.name)/'retain-only',now=NOW,publish=False)
            except TypeError as e:self.fail('morning reconciliation needs a retain-only stage: '+str(e))
        self.assertEqual(report['status'],'DAILY_RETAINED');self.assertIsNone(report['public']);self.assertEqual(report['retained']['generation'],2)
