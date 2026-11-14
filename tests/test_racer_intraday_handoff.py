"""Real temporary Git and ephemeral fixture key; original namespaces stay intact."""
from pathlib import Path
from datetime import timedelta
import json,subprocess,tempfile,unittest
from race_ai.racer_daily_handoff import DailyStateRepository
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.racer_intraday import IntradayState,decode_packet
from tests.test_racer_daily import NOW
from tests.intraday_fixture import packet,result_document
try:
    from race_ai.racer_intraday_handoff import load_intraday,save_intraday,LATEST
except ImportError:load_intraday=save_intraday=None;LATEST=''

class FixtureGit(DailyStateRepository):
    def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);p=Path(self.t.name);self.repo=p/'repo';self.repo.mkdir();remote=p/'remote.git'
        for a in (['git','init','--bare',str(remote)],['git','-C',str(remote),'config','uploadpack.allowFilter','true'],['git','init',str(self.repo)],['git','-C',str(self.repo),'remote','add','origin',remote.as_uri()]):subprocess.run(a,check=True,capture_output=True)
        self.git=FixtureGit(self.repo,ref=TRANSFER_REF);self.root=self.git.commit({'state/other/previous.enc':b'ORIGINAL_OTHER_CIPHER'},None);self.git.push(self.root,None);self.key=bytes(range(32))
    def load(self,initialize=False):
        self.assertIsNotNone(load_intraday,'per-race updates require authenticated delta retention')
        return load_intraday(self.repo,initialize=initialize,key=self.key,transport=self.git,now=NOW+timedelta(hours=1))
    def seed(self):
        loaded=self.load(True);raw,receipt=packet();p=loaded['state'].remember('RESULT',raw,receipt)
        from race_ai.racer_intraday_source import parse_result
        out=parse_result(raw,receipt,now=NOW);p.update(fact_sha256=out['fact_sha256'],statistics_sha256=out['statistics_sha256']);loaded['state'].control['results'][out['race_id']]=p
        return loaded
    def test_fresh_receiver_authenticates_and_replays_only_delta_packets(self):
        loaded=self.seed();a=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW,key=self.key)
        self.assertEqual(a['generation'],1);self.assertEqual(self.git.read(a['source_commit'],'state/other/previous.enc',100),b'ORIGINAL_OTHER_CIPHER')
        again=self.load();p=next(iter(again['state'].control['results'].values()));raw,r=again['state'].capture(p)
        self.assertEqual(r['source_sha256'],p['source_sha256']);self.assertNotIn('架空'.encode(),self.git.read(a['source_commit'],a['cipher_path'],1000000))
        again['state'].control['last_checked_at']=(NOW+timedelta(minutes=5)).isoformat()
        b=save_intraday(again,catalogue_sha256='a'*64,now=NOW+timedelta(minutes=5),key=self.key)
        self.assertEqual(b['generation'],2)
        from race_ai.racer_daily import unseal
        doc=json.loads(self.git.read(b['source_commit'],LATEST,16000));packet=decode_packet(unseal(self.git.read(b['source_commit'],b['cipher_path'],1000000),doc['head'],key=self.key))
        self.assertEqual(packet['captures'],[],'a no-new-result checkpoint must not copy old captures or the ninety-day database')
        last=self.load();self.assertEqual(last['state'].capture(next(iter(last['state'].control['results'].values())))[0],raw)
        receiver=Path(self.t.name)/'receiver';receiver.mkdir()
        subprocess.run(['git','init',str(receiver)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(receiver),'remote','add','origin',self.git.fetch_url],check=True,capture_output=True)
        fresh=FixtureGit(receiver,ref=TRANSFER_REF);loaded=load_intraday(receiver,key=self.key,transport=fresh,now=NOW+timedelta(hours=1))
        self.assertEqual(loaded['state'].capture(next(iter(loaded['state'].control['results'].values())))[0],raw)
        c=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW+timedelta(minutes=10),key=self.key)
        self.assertEqual(c['generation'],3)
        unrelated=self.git._run(['rev-parse',self.root+':state/other/previous.enc']).decode().strip()
        self.assertNotIn(unrelated,fresh._run(['cat-file','--batch-all-objects','--batch-check=%(objectname)']).decode().splitlines())
    def test_missing_or_corrupt_state_never_silently_reinitializes(self):
        with self.assertRaises(ValueError):self.load()
        loaded=self.seed();saved=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW,key=self.key)
        doc=json.loads(self.git.read(saved['source_commit'],LATEST,16000));doc['as_of']='2030-01-01T00:00:00Z'
        wrong=self.git.commit({LATEST:json.dumps(doc).encode()},saved['source_commit']);self.git.push(wrong,saved['source_commit'])
        with self.assertRaises(ValueError):self.load(True)
    def test_save_refuses_a_clock_regression_before_publishing(self):
        saved=save_intraday(self.seed(),catalogue_sha256='a'*64,now=NOW,key=self.key)
        with self.assertRaisesRegex(ValueError,'INTRADAY_CLOCK_REGRESSION'):
            save_intraday(self.load(),catalogue_sha256='a'*64,now=NOW-timedelta(seconds=1),key=self.key)
        self.assertEqual(self.git.head(),saved['source_commit'])
    def test_revert_and_concurrent_other_namespace_updates_preserve_the_originals(self):
        loaded=self.seed();a=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW,key=self.key);again=self.load()
        other=self.git.commit({'state/other/new.enc':b'CONCURRENT_OTHER_CIPHER'},a['source_commit']);self.git.push(other,a['source_commit'])
        b=save_intraday(again,catalogue_sha256='a'*64,now=NOW+timedelta(minutes=5),key=self.key)
        self.assertEqual(self.git.read(b['source_commit'],'state/other/new.enc',100),b'CONCURRENT_OTHER_CIPHER')
        self.git._run(['switch','-C','fixture-revert',b['source_commit']]);self.git._run(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','revert','--no-edit',b['source_commit']])
        reverted=self.git._run(['rev-parse','HEAD']).decode().strip();self.git.push(reverted,b['source_commit'])
        with self.assertRaises(ValueError):self.load(True)
    def test_only_reverting_the_head_cannot_hide_a_later_cipher_generation(self):
        loaded=self.seed();a=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW,key=self.key);old=self.git.read(a['source_commit'],LATEST,16000)
        b=save_intraday(self.load(),catalogue_sha256='a'*64,now=NOW+timedelta(minutes=5),key=self.key)
        reverted=self.git.commit({LATEST:old},b['source_commit']);self.git.push(reverted,b['source_commit'])
        with self.assertRaises(ValueError):self.load()
    def test_unrelated_merge_that_keeps_the_latest_cipher_can_restore(self):
        loaded=self.seed();a=save_intraday(loaded,catalogue_sha256='a'*64,now=NOW,key=self.key)
        side=self.git.commit({'state/other/branch.enc':b'OTHER_BRANCH'},a['source_commit'])
        b=save_intraday(self.load(),catalogue_sha256='a'*64,now=NOW+timedelta(minutes=5),key=self.key)
        self.git._run(['switch','-C','fixture-merge',b['source_commit']]);self.git._run(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','merge','--no-edit',side])
        merged=self.git._run(['rev-parse','HEAD']).decode().strip();self.git.push(merged,b['source_commit'])
        self.assertEqual(self.load()['previous']['head']['generation'],2)
