"""Result-only production entrypoint reaches actual local Git feed and Pages."""
from pathlib import Path
from datetime import timedelta
import base64,json,os,subprocess,tempfile,unittest
from unittest.mock import patch
from tests.test_racer_intraday_handoff import FixtureGit
from tests.test_racer_intraday_refresh import LocalPages
from tests.test_racer_result_bridge import FixtureFeed,saved_view
from tests.test_boat_sp_settlement import document
from tests.intraday_fixture import packet,day_index
from tests.test_racer_daily import NOW,ROSTER
from tests.test_boat_venue_history import archive
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai import saved_view_feed as F
from race_ai.racer_daily import sha,wire
from race_ai.racer_daily_handoff import load_daily,save_daily
from race_ai.racer_result_bridge import SavedResultBridge
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.saved_pages import build_site
from race_ai.boat_pdca_state import PdcaState
from scripts.racer_intraday_refresh import refresh

class RuntimeResultTests(unittest.TestCase):
    def test_shared_source_results_feed_and_small_public_status_without_forecast_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir();remote=root/'remote.git'
            for c in (['git','init','--bare',str(remote)],['git','-C',str(remote),'config','uploadpack.allowFilter','true'],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',remote.as_uri()]):subprocess.run(c,check=True,capture_output=True)
            state=FixtureGit(repo,ref=TRANSFER_REF);commit=state.commit({'state/other.enc':b'UNCHANGED'},None);state.push(commit,None);key=bytes(range(32))
            base=load_daily(repo,initialize=True,key=key,transport=state,now=NOW);base['store'].record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');save_daily(base,base['store'].catalogue(ROSTER,as_of=NOW.isoformat()),key=key);base['store'].close()
            path,_=invented_research_state(root);private=PdcaState(path)
            try:content=private.content_sha256()
            finally:private.close()
            build_site(path,root/'public',root/'owner',expected_source_sha256=content);manifest=json.loads((root/'public/site-build.json').read_text());pages=LocalPages(repo);files={name:(root/'public'/name).read_bytes() for name in manifest['files']};files['site-build.json']=(root/'public/site-build.json').read_bytes();first=pages.commit(files,None);pages.push(first,None)
            feed=FixtureFeed(repo);view=saved_view();boot=dict(key=b'x'*32,view_id='a'*64,cipher_sha256='c'*64,forecast_sha256=F.originals_sha(view),pages_commit='d'*40);raw=F.encrypt_view(view,boot['key'],view_id=boot['view_id'],source_sha='c'*64,generation=1,previous='d'*64);digest=sha(raw);h=json.loads(raw)['header'];fc=feed.commit({'latest.json':(wire(dict(header=h,cipher_sha256=digest))+'\n').encode(),'views/'+digest+'.json':raw},None);feed.push(fc,None)
            calls=[]
            def source(url):
                calls.append(url)
                if '/race/index?' in url:return day_index(),NOW.isoformat()
                from race_ai.racer_intraday_source import identity
                d,v,n=identity(url);doc=document(day=d.replace('-',''),venue=v,number=n);return packet(doc)[0],NOW.isoformat()
            with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(key).decode()}):
                bridge=SavedResultBridge(repo,now=NOW,transport=feed,bootstrap=boot)
                out=refresh(repo,root/'run1',initialize=True,now=NOW,fetch=source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER,sync_results=True,result_bridge=bridge)
                self.assertEqual(out['result_sync']['confirmed'],1);self.assertLessEqual(len(calls),12)
                pointer=json.loads(pages.read(out['public']['pages_commit'],'data/racer-live-status.json',16384));self.assertEqual(pointer['result_sync']['confirmed'],1);self.assertEqual(F.forecast_inventory(F.current_view(feed,boot)[3]),F.forecast_inventory(view))
                count=len(calls);out=refresh(repo,root/'run2',now=NOW+timedelta(minutes=5),fetch=source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER,sync_results=True,result_bridge=SavedResultBridge(repo,now=NOW+timedelta(minutes=5),transport=feed,bootstrap=boot))
                self.assertEqual(out['result_sync']['changed_races'],0);self.assertEqual(out['public']['changed_paths'],['data/racer-live-status.json']);self.assertLessEqual(len(calls)-count,12)
