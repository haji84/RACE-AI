"""Encrypted state → per-race collection → Pages, all on invented local Git."""
from datetime import timedelta
from pathlib import Path
import base64,json,os,subprocess,tempfile,unittest
from unittest.mock import patch
from tests.test_racer_intraday_handoff import FixtureGit
from tests.test_racer_daily import NOW,ROSTER
from tests.test_boat_venue_history import archive
from tests.intraday_fixture import packet,day_index
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai.boat_pdca_state import PdcaState
from race_ai.saved_pages import build_site,PagesRepository
from race_ai.racer_daily_handoff import load_daily,save_daily,_DailyFilteredFetch
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
try:
    from scripts.racer_intraday_refresh import refresh
except ImportError:refresh=None

class LocalPages(_DailyFilteredFetch,PagesRepository):
    def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()

class RefreshTests(unittest.TestCase):
    def test_same_day_then_unchanged_restart_and_morning_reconcile_preserve_uncovered_results(self):
        self.assertIsNotNone(refresh,'live source/state/publication must be connected end to end')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir();remote=root/'remote.git'
            for a in (['git','init','--bare',str(remote)],['git','-C',str(remote),'config','uploadpack.allowFilter','true'],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',remote.as_uri()]):subprocess.run(a,check=True,capture_output=True)
            state=FixtureGit(repo,ref=TRANSFER_REF);parent=state.commit({'state/unrelated.enc':b'UNCHANGED_CIPHER'},None);state.push(parent,None)
            key=bytes(range(32));loaded=load_daily(repo,initialize=True,key=key,transport=state,now=NOW);base=loaded['store']
            base.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');save_daily(loaded,base.catalogue(ROSTER,as_of=NOW.isoformat()),key=key);base.close()
            path,_=invented_research_state(root);private=PdcaState(path)
            try:content=private.content_sha256()
            finally:private.close()
            bundle=build_site(path,root/'public',root/'owner',expected_source_sha256=content);pages=LocalPages(repo);manifest=json.loads((root/'public/site-build.json').read_text())
            files={n:(root/'public'/n).read_bytes() for n in manifest['files']};files['site-build.json']=(root/'public/site-build.json').read_bytes();first=pages.commit(files,None);pages.push(first,None)
            views=pages._run(['ls-tree','-r',first,'--','views']);calls=[]
            def source(url):calls.append(url);return (day_index() if '/race/index?' in url else packet()[0]),NOW.isoformat()
            with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(key).decode()}):
                a=refresh(repo,root/'run1',initialize=True,now=NOW,fetch=source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER)
                self.assertEqual(a['status'],'INTRADAY_REFRESHED');self.assertEqual(a['today']['confirmed_races'],1)
                data=pages.read(a['public']['pages_commit'],'data/racer-daily.json',4000000);self.assertEqual(json.loads(data)['people'][0]['summary']['starts'],4)
                b=refresh(repo,root/'run2',now=NOW+timedelta(minutes=5),fetch=source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER)
                self.assertEqual(b['retained']['generation'],a['retained']['generation']);self.assertEqual(b['public']['changed_paths'],['data/racer-live-status.json'])
                self.assertEqual(pages.read(b['public']['pages_commit'],'data/racer-daily.json',4000000),data)
                tomorrow=NOW+timedelta(days=1)
                def k_source(url):
                    import re
                    match=re.search(r'/k([0-9]{6})\.lzh$',url);self.assertIsNotNone(match,'06:20 reconciliation must not add unrelated HTTP')
                    from datetime import datetime
                    day=datetime.strptime(match[1],'%y%m%d').date().isoformat();return archive(day=day),tomorrow.isoformat()
                c=refresh(repo,root/'run3',daily_reconcile=True,now=tomorrow,fetch=k_source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER)
                self.assertEqual(c['daily']['status'],'DAILY_RETAINED');self.assertIsNone(c['daily']['public'])
                current=json.loads(pages.read(c['public']['pages_commit'],'data/racer-daily.json',4000000));self.assertEqual(current['people'][0]['summary']['starts'],25)
                self.assertEqual(pages._run(['rev-list','--count',c['public']['pages_commit']]).strip(),b'4','morning stage must publish only the recombined snapshot once')
                self.assertEqual(pages._run(['ls-tree','-r',c['public']['pages_commit'],'--','views']),views)
