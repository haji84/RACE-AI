"""Scheduled display feed boundaries with invented pages and a local Git remote."""
from datetime import datetime,timezone
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from race_ai import keirin_note_feed as feed
from tests.test_keirin_note_browser import packet


class FeedCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.repo=self.root/'repo';self.remote=self.root/'origin.git'
        def git(*args,cwd=None):return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL)
        git('init','--bare',str(self.remote));git('init',str(self.repo))
        git('remote','add','origin',str(self.remote),cwd=self.repo)
        class LocalFeedGit(feed.NoteFeedGit):
            def _remote(self):return 'origin'
        self.store=LocalFeedGit(self.repo)
        self.recipient=feed.create_recipient(self.root/'owner')['public']
        self.calls=[]

    def cycle(self,**kwargs):
        return importlib.import_module('scripts.keirin_note_feed_cycle').cycle(
            self.repo,recipient=self.recipient,store=self.store,collector=self.collect,
            clock=lambda:datetime(2030,1,15,0,0,tzinfo=timezone.utc),
            source_commit='a'*40,**kwargs)

    def seed(self):
        return feed.publish_snapshot(self.store,self.recipient,
            feed.seal_snapshot(packet(),self.recipient,kind='import'),expected_parent=None)

    def collect(self,**kwargs):
        self.calls.append(kwargs)
        root=Path(kwargs['private_root']);day=root/'data/2030-01-15';day.mkdir(parents=True)
        for name,entry in packet()['files'].items():
            (root/name).write_text(entry['text'])
        (root/'raw').mkdir();(root/'raw/original.html').write_text('invented raw source')
        return dict(site_root=str(root),safe_report=dict(captured_races=1,
            captured_race_ids=['203001159801'],priority_window_race_ids=[],
            selected_races=1,provider_denied=False,public_page_requests=2,
            research_references_generated=1))

    def test_missing_seed_stops_without_provider_get_or_branch_genesis(self):
        r=self.cycle();self.assertEqual(r['state'],'HOLD_NOTE_OWNER_SEED_REQUIRED')
        self.assertEqual(self.calls,[]);self.assertIsNone(self.store.head())

    def test_research_snapshot_preserves_import_and_updates_id_coverage(self):
        seed=self.seed();r=self.cycle()
        self.assertEqual(r['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
        self.assertEqual(r['entries'],2)
        self.assertEqual(len(self.calls),1)
        index=feed.load_index(self.store,self.recipient,r['source_commit'])
        self.assertEqual(index['covered_race_ids'],['203001159801'])
        self.assertEqual(index['entries'][0]['kind'],'import')
        self.assertEqual(index['entries'][1]['kind'],'research')

    def test_persistent_provider_stop_blocks_future_cycles_without_network(self):
        seed=self.seed();feed.publish_snapshot(self.store,self.recipient,
            expected_parent=seed['source_commit'],denied=True)
        r=self.cycle();self.assertEqual(r['state'],'HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
        self.assertEqual(self.calls,[])

    def test_fresh_denial_survives_a_source_archive_failure(self):
        from unittest.mock import patch
        self.seed();original=self.collect
        def denied(**kwargs):
            result=original(**kwargs);result['safe_report']['provider_denied']=True
            return result
        self.collect=denied
        with patch('scripts.keirin_note_feed_cycle.source_archive',side_effect=ValueError('BOUND')):
            with self.assertRaises(ValueError):self.cycle()
        self.assertTrue(feed.load_index(self.store,self.recipient,self.store.head())['provider_denied'])
        self.assertEqual(self.cycle()['state'],'HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
        self.assertEqual(len(self.calls),1)


if __name__=='__main__':unittest.main()
