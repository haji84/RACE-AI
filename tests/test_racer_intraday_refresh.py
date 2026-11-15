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
    def test_live_beforeinfo_shares_twelve_request_budget_and_survives_encrypted_restart(self):
        from copy import deepcopy
        from urllib.parse import urlsplit,parse_qs
        from race_ai import saved_view_feed as F
        from race_ai.racer_result_bridge import SavedResultBridge
        from race_ai.racer_intraday_handoff import load_intraday
        from race_ai.racer_beforeinfo import project_beforeinfo
        from tests.test_racer_result_bridge import FixtureFeed
        from tests.test_racer_beforeinfo import preview_view,html
        from tests.test_boat_sp_settlement import document
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir();remote=root/'remote.git'
            for cmd in (['git','init','--bare',str(remote)],['git','-C',str(remote),'config','uploadpack.allowFilter','true'],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',remote.as_uri()]):subprocess.run(cmd,check=True,capture_output=True)
            state=FixtureGit(repo,ref=TRANSFER_REF);parent=state.commit({'state/unrelated.enc':b'UNCHANGED_CIPHER'},None);state.push(parent,None)
            key=bytes(range(32));loaded=load_daily(repo,initialize=True,key=key,transport=state,now=NOW);base=loaded['store'];base.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');save_daily(loaded,base.catalogue(ROSTER,as_of=NOW.isoformat()),key=key);base.close()
            path,_=invented_research_state(root);private=PdcaState(path)
            try:content=private.content_sha256()
            finally:private.close()
            build_site(path,root/'public',root/'owner',expected_source_sha256=content);pages=LocalPages(repo);manifest=json.loads((root/'public/site-build.json').read_text());files={n:(root/'public'/n).read_bytes() for n in manifest['files']};files['site-build.json']=(root/'public/site-build.json').read_bytes();parent=pages.commit(files,None);pages.push(parent,None)
            view=json.loads(json.dumps(preview_view()).replace('2030-04-01','2026-11-07').replace('20300401','20261107'));template=view['records'][0];rows=[]
            for venue in range(1,7):
                row=deepcopy(template);row.update(race_id=f'20261107-{venue:02d}-12',cutoff_at='2026-11-07T11:30:00+09:00',saved_cutoff_variants=['2026-11-07T11:30:00+09:00']);row['prediction']['cutoff_at']=row['cutoff_at'];rows.append(row)
            view['records']=rows;feed=FixtureFeed(repo);boot=dict(key=b'x'*32,view_id='a'*64,cipher_sha256='c'*64,forecast_sha256=F.originals_sha(view),pages_commit='d'*40)
            raw=F.encrypt_view(view,boot['key'],view_id=boot['view_id'],source_sha='c'*64,generation=1,previous='d'*64);digest=F.sha(raw);header=json.loads(raw)['header'];parent=feed.commit({'latest.json':(json.dumps(dict(header=header,cipher_sha256=digest))+'\n').encode(),'views/'+digest+'.json':raw},None);feed.push(parent,None)
            bridge=SavedResultBridge(repo,now=NOW,transport=feed,bootstrap=boot);calls=[];pin=F.originals_sha(view)
            def source(url):
                calls.append(url);u=urlsplit(url);q=parse_qs(u.query)
                if u.path.endswith('/beforeinfo'):raw=html().replace(b'20300401',b'20261107').replace(b'jcd=12',('jcd='+q['jcd'][0]).encode())
                elif u.path.endswith('/index'):raw=day_index(tuple(f'{n:02d}' for n in range(1,11)))
                else:raw=packet(document(day=q['hd'][0],venue=q['jcd'][0],number=int(q['rno'][0])))[0]
                return raw,NOW.isoformat()
            with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(key).decode()}):
                result=refresh(repo,root/'run',initialize=True,now=NOW,fetch=source,base_transport=state,intraday_transport=state,pages_transport=pages,roster=ROSTER,sync_results=True,sync_beforeinfo=True,result_bridge=bridge)
                self.assertEqual(len(calls),12);self.assertEqual(result['source_requests'],12);self.assertEqual(result['beforeinfo']['parsed'],4);self.assertEqual(result['beforeinfo']['published_races'],4)
                restored=load_intraday(repo,transport=state,now=NOW)['state']
                self.assertEqual(project_beforeinfo(rows[0],restored,now=NOW)['context']['beforeinfo']['participants'][0]['display_time'],6.72)
                _,_,_,readback=F.current_view(feed,boot);self.assertEqual(F.originals_sha(readback),pin)
                self.assertEqual(sum(bool(r.get('live_boat_observation')) for r in readback['records']),4)

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


class StageCredentialScopeTests(unittest.TestCase):
    def test_stage_only_resets_checkout_host_authorization_and_keeps_repo_scope(self):
        from scripts.racer_intraday_refresh import _stage_git_header_scope
        from scripts.boat_saved_view_feed import git_auth
        token='TEST_STAGE_OWNER_GITHUB_TOKEN_1234567890'
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(['git','init','-q',folder],check=True,capture_output=True)
            subprocess.run(['git','-C',folder,'config','http.https://github.com/.extraheader',
                            'AUTHORIZATION: basic checkout-placeholder'],check=True,capture_output=True)
            with patch.dict(os.environ,{'GH_TOKEN':token,'GIT_CONFIG_COUNT':'0'},clear=True):
                _stage_git_header_scope()
                self.assertEqual(os.environ['GIT_CONFIG_VALUE_0'],'')
                git_auth()
                expected='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode()
                def matched(url):
                    result=subprocess.run(['git','-C',folder,'config','--get-urlmatch',
                        'http.extraheader',url],capture_output=True,text=True)
                    return result.stdout.strip()
                self.assertEqual(matched('https://github.com/haji84/RACE-AI'),expected)
                self.assertEqual(matched('https://github.com/unrelated/repository'),'')
                _stage_git_header_scope()
                self.assertEqual(os.environ['GIT_CONFIG_COUNT'],'2')

    def test_stage_rejects_injected_nonempty_host_header_in_environment(self):
        from scripts.racer_intraday_refresh import _stage_git_header_scope
        with patch.dict(os.environ,{'GIT_CONFIG_COUNT':'1',
            'GIT_CONFIG_KEY_0':'http.https://github.com/.extraheader',
            'GIT_CONFIG_VALUE_0':'AUTHORIZATION: basic unexpected'},clear=True):
            with self.assertRaisesRegex(ValueError,'MODEL_PDCA_CHECKOUT_HEADER_CONFLICT'):
                _stage_git_header_scope()
