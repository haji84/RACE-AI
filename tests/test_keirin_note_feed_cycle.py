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
        self.calls=[];self.result_calls=[]

    def cycle(self,**kwargs):
        return importlib.import_module('scripts.keirin_note_feed_cycle').cycle(
            self.repo,recipient=self.recipient,store=self.store,collector=self.collect,
            result_collector=self.collect_results,
            clock=kwargs.pop('clock',lambda:datetime(2030,1,15,0,0,tzinfo=timezone.utc)),
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

    def collect_results(self,**kwargs):
        self.result_calls.append(kwargs)
        return dict(site_root=str(kwargs['private_root']),result_checks={},safe_report=dict(
            provider_denied=False,changed_observations=0,public_page_requests=0,checked_races=0))

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

    def test_no_new_forecast_tick_still_checks_results_for_every_imported_day(self):
        self.seed()
        self.collect=lambda **kwargs:dict(safe_report=dict(selected_races=0,provider_denied=False,public_page_requests=1))
        result=self.cycle()
        self.assertEqual(len(self.result_calls),1)
        self.assertEqual(self.result_calls[0]['days'],['2030-01-15'])
        self.assertIn('results',result)
        self.assertEqual(result['results']['checked_races'],0)

    def test_new_prediction_is_physically_published_before_result_collector(self):
        self.seed();old_collect=self.collect_results
        def results(**kwargs):
            index=feed.load_index(self.store,self.recipient,self.store.head())
            self.assertEqual(index['covered_race_ids'],['203001159801'])
            self.assertEqual(index['entries'][-1]['kind'],'research')
            return old_collect(**kwargs)
        self.collect_results=results;self.cycle()

    def test_midnight_includes_all_imported_dates_without_decrypting_past_forecasts(self):
        first=self.seed();extra=packet();extra['dates']=['2028-01-01']
        feed.publish_snapshot(self.store,self.recipient,feed.seal_snapshot(extra,self.recipient,kind='import'),
            expected_parent=first['source_commit'])
        self.collect=lambda **kwargs:dict(safe_report=dict(selected_races=0,provider_denied=False,public_page_requests=0))
        self.cycle(clock=lambda:datetime(2030,1,16,0,tzinfo=timezone.utc))
        self.assertEqual(self.result_calls[0]['days'],['2028-01-01','2030-01-15'])

    def test_results_are_separate_encrypted_deltas_and_unchanged_ticks_only_update_progress(self):
        self.seed()
        from scripts.keirin_note_collect_results import _held,fact_digest,SCHEMA
        checks={}
        def results(**kwargs):
            root=Path(kwargs['private_root']);folder=root/'data/2030-01-15';folder.mkdir(parents=True)
            (root/'raw').mkdir();(root/'raw/result.html').write_bytes(b'private invented result source')
            obs=_held('203001159801','PENDING_RESULT_NOT_PUBLISHED')
            digest=fact_digest(obs);obs.update(captured_at='2030-01-15T00:00:00+00:00',
                observation_sha256=digest,previous_observation_sha256=None)
            (folder/'research_results.json').write_text(json.dumps(dict(schema=SCHEMA,day_jst='2030-01-15',observations=[obs])))
            checks['203001159801']=dict(checked_at=obs['captured_at'],digest=digest,status='PENDING')
            return dict(site_root=str(root),result_checks=checks,safe_report=dict(
                provider_denied=False,changed_observations=1,public_page_requests=2,checked_races=1))
        self.collect_results=results
        result=self.cycle();index=feed.load_index(self.store,self.recipient,result['source_commit'])
        self.assertEqual([e['kind'] for e in index['entries']],['import','research','results'])
        self.assertEqual(index['covered_race_ids'],['203001159801'])
        # The exact raw result bytes are inside only the owner's ECDH/AES
        # envelope. Neither the public index nor cycle output contains them.
        self.assertNotIn('private invented result source',json.dumps(result))
        self.assertNotIn('winning_triple',json.dumps(result))
        import base64,io,tarfile
        from cryptography.hazmat.primitives import serialization,hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key=serialization.load_der_private_key(feed.unb64((self.root/'owner/display-key.txt').read_text().strip()),None)
        entry=index['entries'][-1];wire=self.store.read(result['source_commit'],'views/'+entry['cipher_sha256']+'.json')
        peer=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),feed.unb64(entry['ephemeral_public_key']))
        aes=HKDF(algorithm=hashes.SHA256(),length=32,salt=feed.unb64(entry['salt']),
            info=feed.INFO+self.recipient['recipient_id'].encode()).derive(key.exchange(ec.ECDH(),peer))
        envelope=json.loads(wire)
        note=json.loads(AESGCM(aes).decrypt(base64.b64decode(envelope['nonce']),
            base64.b64decode(envelope['ciphertext']),feed.canonical(envelope['header'])))
        archive=base64.b64decode(note['preserved_archives']['result-sources.tar.gz']['base64'])
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as saved:
            self.assertEqual(saved.extractfile('raw/result.html').read(),b'private invented result source')
        before={e['cipher_sha256'] for e in index['entries']}
        self.collect=lambda **kwargs:dict(safe_report=dict(selected_races=0,provider_denied=False,public_page_requests=1))
        def unchanged(**kwargs):
            return dict(site_root=str(kwargs['private_root']),result_checks={
                rid:{**row,'checked_at':'2030-01-15T00:10:00+00:00'} for rid,row in checks.items()},
                safe_report=dict(provider_denied=False,changed_observations=0,public_page_requests=2,checked_races=1))
        self.collect_results=unchanged
        later=self.cycle();after=feed.load_index(self.store,self.recipient,later['source_commit'])
        self.assertEqual({e['cipher_sha256'] for e in after['entries']},before)
        self.assertEqual(len(after['entries']),3)

    def test_result_denial_survives_packaging_failure(self):
        from unittest.mock import patch
        self.seed()
        self.collect=lambda **kwargs:dict(safe_report=dict(selected_races=0,provider_denied=False,public_page_requests=0))
        def denied(**kwargs):
            root=Path(kwargs['private_root']);day=root/'data/2030-01-15';day.mkdir(parents=True)
            (day/'research_results.json').write_text('{}')
            return dict(site_root=str(root),result_checks={},safe_report=dict(
                provider_denied=True,changed_observations=1,public_page_requests=1,checked_races=1))
        self.collect_results=denied
        with patch('scripts.keirin_note_feed_cycle.import_site',side_effect=ValueError('INVENTED_PACKAGING_FAILURE')):
            with self.assertRaises(ValueError):self.cycle()
        self.assertTrue(feed.load_index(self.store,self.recipient,self.store.head())['provider_denied'])

    def test_later_result_failure_preserves_the_just_published_pre_cutoff_original(self):
        self.seed()
        def failed(**kwargs):raise ValueError('INVENTED_RESULT_LAYOUT_HOLD')
        self.collect_results=failed
        with self.assertRaises(ValueError):self.cycle()
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual(index['covered_race_ids'],['203001159801'])
        self.assertEqual([e['kind'] for e in index['entries']],['import','research'])

    def test_inconsistent_progress_cannot_publish_a_result_without_its_private_facts(self):
        self.seed()
        self.collect=lambda **kwargs:dict(safe_report=dict(selected_races=0,provider_denied=False,public_page_requests=0))
        def broken(**kwargs):
            return dict(site_root=str(kwargs['private_root']),result_checks={
                '203001159801':dict(checked_at='2030-01-15T00:00:00Z',digest='a'*64,status='MATCHED')},
                safe_report=dict(provider_denied=False,changed_observations=0,public_page_requests=0))
        self.collect_results=broken;before=self.store.head()
        with self.assertRaises(ValueError):self.cycle()
        self.assertEqual(self.store.head(),before)

    def test_real_input_collector_denial_survives_failure_writing_dated_outputs(self):
        from unittest.mock import patch
        from scripts.keirin_note_collect_inputs import collect_day
        from scripts.keirin_capture_public_two_sources import SourceCaptureError
        self.seed();requests=[]
        def denied(url):
            requests.append(url)
            raise SourceCaptureError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')
        self.collect=lambda **kwargs:collect_day(fetch=denied,**kwargs)
        with patch('scripts.keirin_note_collect_inputs._write_snapshot',
                side_effect=ValueError('SNAPSHOT_FAILED_AFTER_DENIAL')):
            with self.assertRaises(ValueError):self.cycle()
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertTrue(index['provider_denied'])
        self.assertEqual(len(requests),1)
        self.assertEqual(self.cycle()['state'],'HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
        self.assertEqual(len(requests),1)
        self.assertEqual(self.result_calls,[])

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
