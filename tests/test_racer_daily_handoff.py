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
