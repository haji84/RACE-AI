"""Scheduled display feed boundaries with invented pages and a local Git remote."""
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
import importlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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

    def collect_empty(self,**kwargs):
        self.calls.append(kwargs)
        root=Path(kwargs['private_root']);day=kwargs['day_jst']
        folder=root/'data'/day;folder.mkdir(parents=True)
        report=dict(selected_races=0,provider_denied=False,public_page_requests=1,
            captured_races=0,captured_race_ids=[],priority_window_race_ids=[],
            research_references_generated=0,observed_races=0)
        (folder/'races.json').write_text(json.dumps(dict(date=day,races=[])))
        (folder/'reference_AB.json').write_text('[]')
        (folder/'manifest.json').write_text(json.dumps(dict(day_jst=day,safe_report=report)))
        return dict(site_root=str(root),safe_report=report)

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

    def test_public_projection_gets_the_in_memory_forecast_only_after_encrypted_readback(self):
        self.seed()
        published=[]
        def publish(repo,note,entry,*,published_at):
            index=feed.load_index(self.store,self.recipient,self.store.head())
            self.assertIn(entry,index['entries'])
            self.assertEqual(note['scope'],'OWNER_MATCHED_SOURCE_RESEARCH_REFRESH')
            self.assertEqual(entry['captured_race_ids'],['203001159801'])
            self.assertEqual(published_at.tzinfo,timezone.utc)
            published.append(entry['cipher_sha256'])
            return {'state':'PUBLIC_REFERENCES_UPDATED','published_races':1}
        result=self.cycle(reference_publisher=publish)
        self.assertEqual(len(published),1)
        self.assertEqual(result['public_reference']['published_races'],1)
        self.assertEqual(len(self.result_calls),1)

    def test_reference_publisher_is_off_by_default_and_after_a_failed_encrypted_write(self):
        self.seed()
        result=self.cycle()
        self.assertNotIn('public_reference',result)
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=ValueError('GIT_OPERATION_FAILED')):
            with self.assertRaisesRegex(ValueError,'GIT_OPERATION_FAILED'):
                self.cycle(reference_publisher=lambda *args,**kwargs:self.fail('pre-readback public release'))

    def test_failed_odds_handoff_cannot_interfere_with_forecast_or_history(self):
        self.seed()
        callbacks=[]

        def stage(source, note, entry):
            self.assertTrue((source/'raw/original.html').is_file())
            self.assertIn(entry, feed.load_index(self.store,self.recipient,self.store.head())['entries'])
            callbacks.append(entry['captured_race_ids'])
            raise OSError('private detail deliberately excluded from receipt')

        result=self.cycle(odds_stager=stage)
        self.assertEqual(callbacks,[['203001159801']])
        self.assertEqual(result['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
        self.assertEqual(result['public_odds_handoff'],{'state':'HOLD_PUBLIC_ODDS_HANDOFF'})
        self.assertEqual(len(self.result_calls),1)

    def test_secondary_context_follows_public_reference_and_receives_verified_private_capture(self):
        self.seed()
        order=[]
        private_roots=[]

        def reference(repo,note,entry,*,published_at):
            order.append('reference')
            return {'state':'PUBLIC_REFERENCES_UPDATED'}

        def context(repo,root,note,entry,*,published_at):
            index=feed.load_index(self.store,self.recipient,self.store.head())
            self.assertIn(entry,index['entries'])
            self.assertTrue((root/'raw/original.html').is_file())
            self.assertEqual(note['scope'],'OWNER_MATCHED_SOURCE_RESEARCH_REFRESH')
            self.assertEqual(published_at.tzinfo,timezone.utc)
            order.append('context')
            private_roots.append(root)
            raise OSError('private detail deliberately excluded from receipt')

        result=self.cycle(reference_publisher=reference,secondary_context_publisher=context)
        self.assertEqual(order,['reference','context'])
        self.assertEqual(result['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
        self.assertEqual(result['public_rider_context_secondary'],
                         {'state':'HOLD_PUBLIC_RIDER_CONTEXT_SECONDARY'})
        self.assertFalse(private_roots[0].exists())
        self.assertEqual(len(self.result_calls),1)

    def test_secondary_context_is_skipped_without_verified_capture_or_after_denial(self):
        self.seed()
        result=self.cycle()
        self.assertNotIn('public_rider_context_secondary',result)

        def unexpected(*args,**kwargs):
            self.fail('secondary release without an admitted capture')

        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=ValueError('GIT_OPERATION_FAILED')):
            with self.assertRaisesRegex(ValueError,'GIT_OPERATION_FAILED'):
                self.cycle(secondary_context_publisher=unexpected)

        feed.publish_snapshot(self.store,self.recipient,expected_parent=self.store.head(),denied=True)
        result=self.cycle(secondary_context_publisher=unexpected)
        self.assertEqual(result['state'],'HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
        self.assertEqual(result['provider_requests'],0)

    def test_secondary_context_only_reports_named_coverage_counters(self):
        self.seed()

        def context(*args,**kwargs):
            return dict(state='PUBLIC_RIDER_CONTEXT_SECONDARY_UPDATED',commit='b'*40,
                        coverage=dict(verified_riders=7,comments_missing=2,comments_held=True,
                                      coverage_detail='invented private value'),provider_requests=0,
                        private_comment='invented private comment')

        result=self.cycle(secondary_context_publisher=context)
        self.assertEqual(result['public_rider_context_secondary'],
                         dict(state='PUBLIC_RIDER_CONTEXT_SECONDARY_UPDATED',commit='b'*40,
                              coverage=dict(verified_riders=7,comments_missing=2),provider_requests=0))

    def test_publication_is_opt_in_only_in_the_existing_main_actions_job(self):
        from scripts import keirin_note_feed_cycle as cycle
        env={
            'GITHUB_REPOSITORY':'haji84/RACE-AI', 'GITHUB_REPOSITORY_ID':'1416489937',
            'GITHUB_REF':'refs/heads/main','GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'schedule',
            'GITHUB_WORKFLOW_REF':'haji84/RACE-AI/.github/workflows/keirin-pr71-owner-autonomous.yml@refs/heads/main',
            'GITHUB_JOB':'other-job',
        }
        with patch.dict(os.environ,env,clear=True),patch.object(cycle,'cycle') as roll:
            with self.assertRaisesRegex(ValueError,'PUBLIC_REFERENCE_TRUSTED_MAIN_RUN'):
                cycle.main(['--repo',str(self.repo),'--publish-reference'])
        roll.assert_not_called()

    def append_archive(self):
        incoming=feed.seal_snapshot(packet(),self.recipient,kind='archive')
        return feed.publish_snapshot(self.store,self.recipient,incoming,expected_parent=self.store.head())

    def test_stale_forecast_append_reuses_exact_cipher_and_retains_other_writer(self):
        seed=self.seed()
        collect=self.collect
        def interleaved(**kwargs):
            got=collect(**kwargs)
            self.append_archive()
            return got
        self.collect=interleaved
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',wraps=feed.publish_snapshot) as publish:
            outcome=self.cycle()
        self.assertEqual(outcome['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.result_calls),1)
        self.assertEqual(publish.call_count,2)
        first,retry=[call.args[2] for call in publish.call_args_list]
        self.assertEqual(first,retry)
        head=self.store.head()
        index=feed.load_index(self.store,self.recipient,head)
        self.assertEqual([entry['kind'] for entry in index['entries']],['import','archive','research'])
        old=feed.load_index(self.store,self.recipient,seed['source_commit'])['entries'][0]
        self.assertEqual(index['entries'][0],old)
        self.assertEqual(
            self.store.read(head,'views/'+first['entry']['cipher_sha256']+'.json'),
            first['cipher'])

    def test_two_disjoint_concurrent_writes_retry_the_same_result_without_new_gets(self):
        self.seed()
        self.cycle()
        self.collect=self.collect_empty
        from scripts.keirin_note_collect_results import SCHEMA, _held, _status, fact_digest
        rid='203001159801'
        checked_at='2030-01-15T00:02:00+00:00'

        def collect_results(**kwargs):
            self.result_calls.append(kwargs)
            root=Path(kwargs['private_root'])
            folder=root/'data/2030-01-15';folder.mkdir(parents=True)
            row=_held(rid,'PENDING_RESULT_NOT_PUBLISHED')
            digest=fact_digest(row)
            row.update(captured_at=checked_at,observation_sha256=digest,previous_observation_sha256=None)
            (folder/'research_results.json').write_text(json.dumps(
                dict(schema=SCHEMA,day_jst='2030-01-15',observations=[row])))
            return dict(site_root=str(root),result_checks={rid:dict(
                checked_at=checked_at,digest=digest,status=_status(row))},safe_report=dict(
                provider_denied=False,changed_observations=1,public_page_requests=1))

        self.collect_results=collect_results
        self.result_calls.clear()
        attempts=[]
        def interleaved(*args,**kwargs):
            attempts.append(args[2])
            if len(attempts)<=2:
                self.append_archive()
            return feed.publish_snapshot(*args,**kwargs)

        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=interleaved):
            outcome=self.cycle()
        self.assertEqual(len(self.result_calls),1)
        self.assertEqual(len(attempts),3)
        self.assertTrue(all(attempt is attempts[0] for attempt in attempts))
        index=feed.load_index(self.store,self.recipient,outcome['source_commit'])
        self.assertEqual([entry['kind'] for entry in index['entries']],
            ['import','research','archive','archive','results'])
        self.assertEqual(index['result_checks'][rid]['checked_at'],checked_at)

    def test_concurrent_writes_stop_after_the_retry_budget(self):
        self.seed()
        attempts=[]
        def interleaved(*args,**kwargs):
            attempts.append(kwargs['expected_parent'])
            self.append_archive()
            return feed.publish_snapshot(*args,**kwargs)
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=interleaved):
            with self.assertRaisesRegex(ValueError,'CONCURRENT_UPDATE'):
                self.cycle()
        self.assertEqual(len(attempts),3)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.result_calls,[])
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual([entry['kind'] for entry in index['entries']],['import','archive','archive','archive'])

    def test_non_fast_forward_change_cannot_rebase_a_cipher(self):
        self.seed()
        collect=self.collect
        rewritten=[]
        def interleaved(**kwargs):
            got=collect(**kwargs)
            changed=feed.seal_snapshot(packet(),self.recipient,kind='archive')
            index=feed.append_index(None,self.recipient,entry=changed['entry'])
            unrelated=self.store.commit({
                'index.json':feed.canonical(index)+b'\n',
                'views/'+changed['entry']['cipher_sha256']+'.json':changed['cipher'],
            },None)
            self.store.run(['push','--force','origin',unrelated+':refs/heads/'+self.store.ref])
            rewritten.append(unrelated)
            return got
        self.collect=interleaved
        with self.assertRaisesRegex(ValueError,'PARENT_NOT_FAST_FORWARD'):
            self.cycle()
        self.assertEqual(self.store.head(),rewritten[0])
        self.assertEqual(self.result_calls,[])

    def test_concurrent_denial_is_kept_and_prevents_result_collection(self):
        self.seed()
        collect=self.collect
        def interleaved(**kwargs):
            got=collect(**kwargs)
            feed.publish_snapshot(self.store,self.recipient,expected_parent=self.store.head(),denied=True)
            return got
        self.collect=interleaved
        with self.assertRaisesRegex(ValueError,'PREVIOUS_PROVIDER_DENIAL_NO_RETRY'):
            self.cycle()
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertTrue(index['provider_denied'])
        self.assertEqual(len(index['entries']),1)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.result_calls,[])

    def test_concurrent_forecast_for_the_same_race_preserves_existing_reference(self):
        self.seed()
        collect=self.collect
        def interleaved(**kwargs):
            got=collect(**kwargs)
            competing=feed.seal_snapshot(packet(),self.recipient,kind='research',
                                          captured_ids=['203001159801'])
            feed.publish_snapshot(self.store,self.recipient,competing,
                                  expected_parent=self.store.head())
            return got
        self.collect=interleaved
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',wraps=feed.publish_snapshot) as publish:
            with self.assertRaisesRegex(ValueError,'FORECAST_COVERAGE_CHANGED'):
                self.cycle()
        self.assertEqual(publish.call_count,1)
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual([entry['kind'] for entry in index['entries']],['import','research'])
        self.assertEqual(index['covered_race_ids'],['203001159801'])
        self.assertEqual(self.result_calls,[])

    def test_moved_readback_accepts_only_the_already_published_cipher(self):
        self.seed()
        def moved(*args,**kwargs):
            feed.publish_snapshot(*args,**kwargs)
            self.append_archive()
            raise ValueError('KEIRIN_NOTE_FEED_REMOTE_READBACK')
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=moved) as publish:
            outcome=self.cycle()
        self.assertEqual(publish.call_count,1)
        self.assertEqual(outcome['source_commit'],self.store.head())
        self.assertEqual(len(self.calls),1)
        index=feed.load_index(self.store,self.recipient,outcome['source_commit'])
        self.assertEqual([entry['kind'] for entry in index['entries']],['import','research','archive'])

    def test_unclassified_git_failure_never_retries_just_because_the_head_moved(self):
        self.seed()
        def failed(*args,**kwargs):
            self.append_archive()
            raise ValueError('KEIRIN_NOTE_FEED_GIT_OPERATION_FAILED')
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',side_effect=failed) as publish:
            with self.assertRaisesRegex(ValueError,'GIT_OPERATION_FAILED'):
                self.cycle()
        self.assertEqual(publish.call_count,1)
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual([entry['kind'] for entry in index['entries']],['import','archive'])
        self.assertEqual(self.result_calls,[])

    def test_stale_result_delta_is_held_when_its_predecessor_changes(self):
        from scripts.keirin_note_collect_results import _held, _status, fact_digest, SCHEMA
        self.seed()
        self.cycle()
        self.collect=self.collect_empty
        rid='203001159801'

        def write_result(root,reason,at):
            folder=root/'data/2030-01-15';folder.mkdir(parents=True)
            obs=_held(rid,reason)
            digest=fact_digest(obs)
            obs.update(captured_at=at,observation_sha256=digest,previous_observation_sha256=None)
            (folder/'research_results.json').write_text(json.dumps(
                dict(schema=SCHEMA,day_jst='2030-01-15',observations=[obs])))
            return {rid:dict(checked_at=at,digest=digest,status=_status(obs))}

        # A different writer binds the first result for this race while the
        # original collector is still creating a delta without a predecessor.
        other=self.root/'other-result';other.mkdir(mode=0o700)
        competing=write_result(other,'HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL','2030-01-15T00:01:00+00:00')
        from race_ai.keirin_note_view import import_site
        snapshot=feed.seal_snapshot(import_site(other,source_commit='b'*40),self.recipient,kind='results')

        def collect_results(**kwargs):
            root=Path(kwargs['private_root'])
            local=write_result(root,'PENDING_RESULT_NOT_PUBLISHED','2030-01-15T00:02:00+00:00')
            feed.publish_snapshot(self.store,self.recipient,snapshot,
                                  expected_parent=self.store.head(),result_checks=competing)
            return dict(site_root=str(root),result_checks=local,safe_report=dict(
                provider_denied=False,changed_observations=1,public_page_requests=1))
        self.collect_results=collect_results
        with patch('scripts.keirin_note_feed_cycle.publish_snapshot',wraps=feed.publish_snapshot) as publish:
            with self.assertRaisesRegex(ValueError,'RESULT_PREDECESSOR_CHANGED'):
                self.cycle()
        self.assertEqual(publish.call_count,1)
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual(index['result_checks'],competing)
        self.assertEqual(index['entries'][-1],snapshot['entry'])

    def test_cli_reports_collection_stage_without_exception_text(self):
        seed=self.seed()
        self.store.run(['update-ref','HEAD',seed['source_commit']])
        config=self.repo/'config';config.mkdir()
        (config/'keirin-note-recipient.json').write_text(json.dumps(self.recipient))
        runtime=dict(GITHUB_REPOSITORY=feed.REPO,GITHUB_REF='refs/heads/main',
                     GITHUB_EVENT_NAME='schedule')
        output=StringIO()
        from scripts import keirin_note_feed_cycle as cli
        with patch.dict(os.environ,runtime), patch.object(cli,'NoteFeedGit',return_value=self.store), \
                patch('scripts.keirin_note_collect_inputs.collect_day',
                      side_effect=ValueError('https://fixture.invalid/private-invented-value')), \
                redirect_stdout(output):
            self.assertEqual(cli.main(['--repo',str(self.repo)]),2)
        self.assertEqual(json.loads(output.getvalue()),{
            'state':'HOLD_NOTE_SOURCE_OR_ENCRYPTED_PUBLICATION',
            'failure_stage':'FORECAST_COLLECTION',
            'failure_reason':'INVALID_DATA',
        })

    def test_no_new_forecast_tick_still_checks_results_for_every_imported_day(self):
        self.seed()
        self.collect=self.collect_empty
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
        self.collect=self.collect_empty
        self.cycle(clock=lambda:datetime(2030,1,16,0,tzinfo=timezone.utc))
        self.assertEqual(self.result_calls[0]['days'],['2028-01-01','2030-01-15','2030-01-16'])

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
        self.collect=self.collect_empty
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
        self.seed();self.cycle()
        self.collect=self.collect_empty
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
        self.seed();self.cycle()
        self.collect=self.collect_empty
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

    def test_first_empty_day_is_retained_without_repeating_empty_ticks(self):
        self.seed();self.collect=self.collect_empty
        now=datetime(2030,1,15,0,0,tzinfo=timezone.utc)
        first=self.cycle(clock=lambda:now)
        self.assertEqual(first['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',
            'A day without forecasts must have its own encrypted observation, not disappear.')
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual(len(index['entries']),2)
        self.assertEqual(index['entries'][-1]['days'],['2030-01-15'])
        self.assertEqual(index['entries'][-1]['captured_race_ids'],[])
        first_head=self.store.head()
        now+=timedelta(minutes=5)
        second=self.cycle(clock=lambda:now)
        self.assertEqual(second['state'],'NOTE_NO_NEW_ELIGIBLE_RESEARCH_INPUTS')
        self.assertEqual(self.store.head(),first_head)
        now+=timedelta(days=1)
        third=self.cycle(clock=lambda:now)
        self.assertEqual(third['state'],'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
        index=feed.load_index(self.store,self.recipient,self.store.head())
        self.assertEqual(len(index['entries']),3)
        self.assertEqual(index['entries'][-1]['days'],['2030-01-16'])
        self.assertEqual(index['covered_race_ids'],[])
        self.assertEqual(len(self.result_calls),3,'Empty observations must not disable result updates.')

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
