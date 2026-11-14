"""Actual local Git roundtrips for dated encrypted display publication."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from race_ai import saved_view_feed as F
from race_ai import saved_view_history as H
from race_ai.boat_pdca_projection import project_pdca
from race_ai.boat_pdca_state import PdcaState, sha
from race_ai.boat_history_store import wire
from tests.test_boat_pdca_github_handoff import invented_research_state


class LocalFeed(F.FeedRepository):
    def _check_remote(self):
        self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()


class HistoryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.remote = self.root/'remote.git'
        self.repo = self.root/'repo'; self.repo.mkdir()
        for args in (['git','init','--bare',str(self.remote)], ['git','init',str(self.repo)],
                     ['git','-C',str(self.repo),'remote','add','origin',str(self.remote)]):
            subprocess.run(args, check=True, capture_output=True)
        path, _ = invented_research_state(self.root)
        state = PdcaState(path)
        try: self.view = project_pdca(state)
        finally: state.close()
        self.key = b'x'*32; self.pin = F.originals_sha(self.view)
        self.bootstrap = dict(key=self.key, view_id='b'*64, cipher_sha256='c'*64,
                              forecast_sha256=self.pin, pages_commit='d'*40)
        raw = F.encrypt_view(self.view, self.key, view_id='b'*64, source_sha='c'*64,
                             generation=1, previous='c'*64)
        header = json.loads(raw)['header']; self.old_cipher = sha(raw)
        self.git = LocalFeed(self.repo)
        self.first = self.git.commit({'views/'+sha(raw)+'.json':raw,
            'latest.json':(wire(dict(header=header,cipher_sha256=sha(raw)))+'\n').encode()}, None)
        self.git.push(self.first, None)

    def dated(self, day):
        source_day = self.view['records'][0]['event_date_jst']
        body = wire(self.view).replace(source_day, day).replace(source_day.replace('-',''),day.replace('-',''))
        value = json.loads(body); value['forecast_base_sha256'] = self.pin
        return value

    def publish(self, view):
        parent, previous, generation, _ = F.current_view(self.git, self.bootstrap)
        return F.publish_view(self.git, self.bootstrap, view, parent=parent, previous=previous,
                              generation=generation, history=True)

    def test_migration_retains_old_originals_and_prunes_only_current_tree(self):
        new = self.dated('2026-11-07')
        self.publish(new)
        head = self.git.head()
        paths = self.git._run(['ls-tree','-r','--name-only',head]).decode().splitlines()
        self.assertEqual(len(paths), 2)
        old = F.current_view(self.git, self.bootstrap, day='2026-11-06')[3]
        current = F.current_view(self.git, self.bootstrap, day='2026-11-07')[3]
        self.assertEqual(F.forecast_inventory(old), F.forecast_inventory(self.view))
        self.assertEqual(F.forecast_inventory(current), F.forecast_inventory(new))
        self.assertTrue(self.git.read(self.first,'views/'+self.old_cipher+'.json',F.MAX_WIRE))
        second = self.root/'fresh'; second.mkdir()
        for args in (['git','init',str(second)],['git','-C',str(second),'remote','add','origin',str(self.remote)]):
            subprocess.run(args,check=True,capture_output=True)
        fresh = LocalFeed(second)
        restored = F.current_view(fresh,self.bootstrap,day='2026-11-06')[3]
        self.assertEqual(F.forecast_inventory(restored),F.forecast_inventory(self.view))

    def test_late_prior_month_update_preserves_current_month_and_old_forecasts(self):
        december = self.dated('2026-12-01'); self.publish(december)
        parent, previous, generation, november = F.current_view(self.git,self.bootstrap,day='2026-11-06')
        november['records'][0]['missing_reasons'].append('LATE_SOURCE_REVIEW')
        F.publish_view(self.git,self.bootstrap,november,parent=parent,previous=previous,
                       generation=generation,history=True)
        latest = F.current_view(self.git,self.bootstrap,day='2026-12-01')[3]
        self.assertEqual(F.forecast_inventory(latest),F.forecast_inventory(december))
        prior = F.current_view(self.git,self.bootstrap,day='2026-11-06')[3]
        self.assertIn('LATE_SOURCE_REVIEW',prior['records'][0]['missing_reasons'])
        self.assertEqual(F.forecast_inventory(prior),F.forecast_inventory(self.view))

    def test_mutated_original_stops_before_publication(self):
        changed = deepcopy(self.view); changed['forecast_base_sha256'] = self.pin
        original=changed['records'][0]['prediction']['ordered_top8'][0]
        changed['records'][0]['prediction']['ordered_top8'][0] = list(reversed(original))
        with self.assertRaises(ValueError): self.publish(changed)
        self.assertEqual(self.git.head(),self.first)

    def test_unanchored_multiday_v3_migrates_without_changing_originals(self):
        before=deepcopy(self.view)
        before['records']+=self.dated('2026-11-07')['records']
        self.pin=F.originals_sha(before);self.bootstrap['forecast_sha256']=self.pin
        raw=F.encrypt_view(before,self.key,view_id='b'*64,source_sha='c'*64,generation=2,previous=self.old_cipher)
        header=json.loads(raw)['header'];ident=sha(raw)
        second=self.git.commit({'views/'+ident+'.json':raw,'latest.json':
            (wire(dict(header=header,cipher_sha256=ident))+'\n').encode()},self.first)
        self.git.push(second,self.first)
        after=deepcopy(before);after['forecast_base_sha256']=self.pin
        self.publish(after)
        for day in ('2026-11-06','2026-11-07'):
            restored=F.current_view(self.git,self.bootstrap,day=day)[3]
            expected=dict(before,records=[r for r in before['records'] if r['event_date_jst']==day])
            self.assertEqual(F.forecast_inventory(restored),F.forecast_inventory(expected))


if __name__ == '__main__': unittest.main()
