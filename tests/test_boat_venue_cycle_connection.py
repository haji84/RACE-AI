"""Invented orchestration: private venue research never enters national.json."""
from copy import deepcopy
from datetime import timedelta
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.test_video_existing_hooks import target_bundle
from tests.test_observed_weight_learning import NOW


class PrivateVenueCycleTests(unittest.TestCase):
    def run_cycle(self, *, preload_error=None,generation_failure=False,setup_failure=False):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        _, _, bundle = target_bundle()
        original = deepcopy(bundle)
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'cycle_recovery_output').mkdir()
            index = root/'index.json'; index.write_text('{"entries":[]}')
            out = root/'boat_nationwide_output'; out.mkdir()
            runtime = dict(context={'training':{'private_weights':'NEVER_PUBLIC'}},
                dataset_folder=root/'dataset', dataset_pointer={'dataset_sha256':'a'*64,
                    'source_commit':'a'*40,'dataset_path':'state/fixture/dataset.json'},
                dataset_verified_at=NOW.isoformat(), output_folder=root/'cipher',preload_folder=root/'private-preload')
            if setup_failure:runtime['output_folder'].write_bytes(b'fixture-blocked-path')
            def preload(**kwargs):
                events.append('private-preload')
                self.assertEqual(kwargs['round_no'], 2)
                return (None, preload_error) if preload_error else (runtime, None)
            def baseline(**kwargs):
                events.append('fresh-baseline')
                return {'observed_pairwise_p1_bundles':[deepcopy(bundle)]}
            def private_forecast(*args, **kwargs):
                events.append('private-inference')
                self.assertEqual(args[0], json.loads(json.dumps(bundle)))
                self.assertEqual(args[1], runtime['context'])
                self.assertEqual(kwargs['dataset_verified_at'], NOW.isoformat())
                # The actual crypto, same-input replay and cutoff behavior are
                # tested by the private forecaster's separate contract tests.
                folder=Path(args[4]);folder.mkdir(mode=0o700,parents=True)
                for name in ('learning.json','learning.enc','summary.json'):(folder/name).write_bytes(b'fixture-cipher')
                if generation_failure:raise ValueError('fixture sealing crossed cutoff')
                return {'learned_shadow_count':2, 'plaintext_published':False}
            with patch.object(runner,'ROOT',root), \
                 patch.object(runner,'load_state',return_value={'index_entries':[]}), \
                 patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',out), \
                 patch.object(pilot,'run',side_effect=baseline), \
                 patch.object(runner,'_venue_research_preload',side_effect=preload,create=True), \
                 patch('race_ai.boat_venue_research_forecast.forecast_private_venue_p1',side_effect=private_forecast), \
                 patch.dict(os.environ,RUNNER_TEMP=str(root)), \
                 patch.object(runner,'datetime') as clock:
                clock.now.return_value=NOW+timedelta(minutes=10)
                runner.forecast('2030-04-01')
                with contextlib.redirect_stdout(io.StringIO()):
                    private_summary=runner.venue_research_forecast('2030-04-01',2)
            body=(out/'national.json').read_text(); result=json.loads(body)
            if generation_failure:
                self.assertEqual(list(runtime['output_folder'].iterdir()),[])
                retained=list((root/'boat-venue-research-quarantine').glob('*/cipher/learning.enc'))
                self.assertEqual(len(retained),1)
                self.assertEqual(retained[0].read_bytes(),b'fixture-cipher')
        self.assertEqual(bundle, original)
        self.assertNotIn('NEVER_PUBLIC',body)
        self.assertNotIn('training_receipt',body)
        self.assertNotIn('venue_evidence',body)
        self.assertNotIn('venue_research_summary',body)
        result['venue_research_summary']=private_summary
        self.assertEqual(result['observed_pairwise_p1_bundles'],json.loads(json.dumps([bundle])))
        return events,result

    def test_original_baseline_is_frozen_before_private_preload_and_inference(self):
        events,result=self.run_cycle()
        self.assertEqual(events,['fresh-baseline','private-preload','private-inference'])
        self.assertEqual(result['venue_research_summary']['generated_races'],1)
        self.assertEqual(result['venue_research_summary']['learned_shadow_count'],2)
        self.assertFalse(result['venue_research_summary']['production_promoted'])
        self.assertFalse(result['venue_research_summary']['independent_pre_cutoff_receipt_verified'])

    def test_optional_private_failure_preserves_original_baseline(self):
        events,result=self.run_cycle(preload_error='VENUE_RESEARCH_PRELOAD_REJECTED')
        self.assertEqual(events,['fresh-baseline','private-preload'])
        self.assertEqual(result['venue_research_summary']['generated_races'],0)
        self.assertEqual(result['venue_research_summary']['reason'],'VENUE_RESEARCH_PRELOAD_REJECTED')

    def test_late_partial_ciphertext_is_preserved_but_excluded_from_upload(self):
        events,result=self.run_cycle(generation_failure=True)
        self.assertEqual(events,['fresh-baseline','private-preload','private-inference'])
        self.assertEqual(result['venue_research_summary']['generated_races'],0)
        self.assertEqual(result['venue_research_summary']['rejected_races'],1)

    def test_private_output_setup_failure_does_not_abort_saved_baseline(self):
        events,result=self.run_cycle(setup_failure=True)
        self.assertEqual(events,['fresh-baseline','private-preload'])
        self.assertEqual(result['venue_research_summary']['reason'],'VENUE_RESEARCH_GENERATION_REJECTED')

    def test_missing_public_config_does_not_read_sources_or_make_private_output(self):
        from scripts import github_existing_cycle as runner
        with tempfile.TemporaryDirectory() as temporary,patch.object(runner,'ROOT',Path(temporary)), \
             patch.object(runner,'gh',side_effect=AssertionError('unexpected private GET')):
            runtime,error=runner._venue_research_preload(round_no=1)
            self.assertIsNone(runtime);self.assertIsNone(error)

    def test_empty_p1_does_not_restore_or_download_optional_candidates(self):
        from scripts import github_existing_cycle as runner
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'boat_nationwide_output').mkdir()
            (root/'boat_nationwide_output/national.json').write_text('{"observed_pairwise_p1_bundles":[]}')
            with patch.object(runner,'ROOT',root), \
                 patch.object(runner,'_venue_research_preload',side_effect=AssertionError('unnecessary private I/O')), \
                 contextlib.redirect_stdout(io.StringIO()):
                summary=runner.venue_research_forecast('2030-04-01',2)
            self.assertEqual(summary['state'],'NO_PRIVATE_P1_INPUT')
            self.assertEqual(summary['generated_races'],0)

    def test_failed_private_receipt_is_explicit_hold_without_blocking_baselines(self):
        from scripts import github_existing_cycle as runner
        stream=io.StringIO()
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode()), \
             patch.object(runner,'gh',side_effect=ValueError('/private/secret-source')), \
             contextlib.redirect_stdout(stream):
            report=runner.venue_research_readback(123)
        self.assertEqual(report['status'],'HOLD_PRIVATE_VENUE_P1_READBACK')
        self.assertFalse(report['independent_pre_cutoff_receipt_verified'])
        self.assertNotIn('/private',stream.getvalue())

    def test_verified_receipt_carries_handle_to_later_official_result_round(self):
        from scripts import github_existing_cycle as runner
        from race_ai.cycle_recovery import load_state
        meta={'workflow_run':{'id':99,'head_sha':'a'*40},'digest':'sha256:'+'b'*64}
        state={'schema':'RACE_AI_RECOVERED_FIRST_RECEIPTS_V1','day_jst':'2030-04-01','complete':True}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'cycle_recovery_output').mkdir()
            with patch.object(runner,'ROOT',root),patch.object(runner,'event_day',return_value='2030-04-01'), \
                 patch.object(runner,'load_state',return_value=state), \
                 patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode()), \
                 patch.object(runner,'gh',side_effect=[json.dumps(meta).encode(),b'cipher-fixture']), \
                 patch.dict(os.environ,GITHUB_RUN_ID='99',GITHUB_SHA='a'*40), \
                 patch('race_ai.boat_venue_research_receipt.verify_private_p1_artifact',return_value={
                     'status':'PRIVATE_VENUE_P1_ARTIFACT_PRE_CUTOFF_VERIFIED',
                     'independent_pre_cutoff_receipt_verified':True}),contextlib.redirect_stdout(io.StringIO()):
                runner.venue_research_readback(123)
            retained=load_state(root/'cycle_recovery_output/continuity.json','2030-04-01')
        self.assertEqual(retained['venue_research_artifact_refs'],[dict(
            artifact_id=123,run_id=99,head_sha='a'*40,digest='sha256:'+'b'*64)])

    def test_official_result_revisit_prepares_private_archive_for_retention(self):
        from scripts import github_existing_cycle as runner
        ref=dict(artifact_id=123,run_id=99,head_sha='a'*40,digest='sha256:'+'b'*64)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'existing_cycle_output').mkdir()
            (root/'existing_cycle_output/official-result-observations.json').write_text('[]')
            with patch.object(runner,'ROOT',root), \
                 patch.object(runner,'load_state',return_value={'venue_research_artifact_refs':[ref]}), \
                 patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode(),
                            RUNNER_TEMP=str(root)), \
                 patch.object(runner,'gh',side_effect=[json.dumps({'digest':ref['digest']}).encode(),b'fixture-cipher-zip']), \
                 patch('race_ai.boat_venue_research_pdca.score_private_p1_artifact',return_value={'paired_forecasts':0}), \
                 contextlib.redirect_stdout(io.StringIO()):
                summary=runner.venue_research_pdca('2030-04-01',2)
            self.assertEqual(summary['archives_processed'],1)
            self.assertEqual(summary['paired_forecasts'],0)
            archive=root/'boat-venue-research-archives'
            self.assertEqual(archive.stat().st_mode&0o077,0)
            self.assertEqual((archive/'123').stat().st_mode&0o077,0)
            self.assertEqual((archive/'123/archive.zip').read_bytes(),b'fixture-cipher-zip')


class PrivateVenueWorkerRecoveryTests(unittest.TestCase):
    def saved_private_metadata(self, artifact_id=800):
        return dict(id=artifact_id, name='boat-venue-research-p1-99-1', expired=False,
            created_at='2030-04-01T03:00:00Z', size_in_bytes=64*1024*1024,
            digest='sha256:'+'d'*64, workflow_run=dict(id=99, repository_id=1416489937,
                head_repository_id=1416489937, head_sha='a'*40))

    def recover_private_listing(self, metadata, *, listed=None, unavailable=False):
        from race_ai import cycle_recovery as recovery
        from race_ai.frozen_day_cycle import read_p0
        from tests.test_frozen_day_cycle import sample
        _, raw, baseline = sample()
        baseline = deepcopy(baseline)
        baseline['name'] = 'boat-p0-existing-99'
        baseline['workflow_run']['id'] = 99
        _, expected = read_p0(raw, baseline, expected_day='2030-04-01')
        listed = listed if listed is not None else {'id':800, 'name':'boat-venue-research-p1-99-1'}
        calls = []
        def get(route):
            calls.append(route)
            if route == f'actions/artifacts/{baseline["id"]}':
                return json.dumps(baseline).encode()
            if route == f'actions/artifacts/{baseline["id"]}/zip':
                return raw
            if route == 'actions/artifacts/800':
                if unavailable:
                    raise ValueError('synthetic private metadata unavailable')
                return metadata if type(metadata) is bytes else json.dumps(metadata).encode()
            raise AssertionError('private ZIP or unexpected request: '+route)
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(recovery, 'day_runs', return_value=[{'id':99, 'head_sha':'a'*40}]), \
             patch.object(recovery, 'artifact_pages', return_value=[baseline, listed]), \
             patch.object(recovery, 'previous_source_control', return_value=None):
            state = recovery.recover(get, '2030-04-01', current_run=100,
                out=Path(temporary), clock=lambda:NOW+timedelta(hours=4))
        self.assertEqual({r['model_sha256'] for r in state['rows']},
                         {r['model_sha256'] for r in expected})
        self.assertEqual(state['observations'], [])
        self.assertTrue(state['complete'])
        self.assertNotIn('actions/artifacts/800/zip', calls)
        self.assertEqual(state['receipts'], [baseline])
        return state, calls

    def test_recovers_saved_private_artifact_without_result_report_or_owner_key(self):
        metadata = self.saved_private_metadata()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            state, calls = self.recover_private_listing(metadata)
        self.assertEqual(state.get('venue_research_artifact_refs', []), [dict(
            artifact_id=800, run_id=99, head_sha='a'*40, digest='sha256:'+'d'*64)])
        self.assertIn('actions/artifacts/800', calls)
        self.assertEqual(state.get('venue_research_ref_rejections', 0), 0)
        self.assertNotIn('independent_pre_cutoff_receipt_verified', state)

    def test_malformed_private_metadata_never_blocks_authenticated_baselines(self):
        good = self.saved_private_metadata()
        variants = [dict(good, id=True), dict(good, id=801), dict(good, expired=True),
            dict(good, size_in_bytes=0), dict(good, size_in_bytes=True),
            dict(good, size_in_bytes=64*1024*1024+1), dict(good, digest='sha256:'+'D'*64),
            dict(good, name='boat-venue-research-p1-99-1-extra'),
            dict(good, created_at='2030-04-01T08:00:00'),
            dict(good, created_at=(NOW+timedelta(hours=5)).isoformat()), b'{invalid']
        for name, value in (('id', 98), ('id', True), ('repository_id', 1),
                            ('head_repository_id', 1), ('head_sha', 'main'), ('head_sha', 'b'*40)):
            variants.append(dict(good, workflow_run=dict(good['workflow_run'], **{name:value})))
        for metadata in variants:
            with self.subTest(metadata=metadata):
                state, _ = self.recover_private_listing(metadata)
                self.assertEqual(state.get('venue_research_artifact_refs', []), [])
                self.assertEqual(state.get('venue_research_ref_rejections', 0), 1)
        state, _ = self.recover_private_listing(good, unavailable=True)
        self.assertEqual(state.get('venue_research_ref_rejections', 0), 1)
        for name in ('boat-venue-research-p1-99-0', 'boat-venue-research-p1-98-1',
                     'boat-venue-research-p1-99-01', 'boat-venue-research-p1-99-1-extra'):
            with self.subTest(name=name):
                state, _ = self.recover_private_listing(good, listed={'id':800, 'name':name})
                self.assertEqual(state.get('venue_research_artifact_refs', []), [])
                self.assertEqual(state.get('venue_research_ref_rejections', 0), 1)

    def test_saved_private_artifact_from_previous_jst_day_is_excluded_without_relabeling(self):
        metadata = self.saved_private_metadata()
        metadata['created_at'] = '2030-03-31T10:00:00Z'
        state, _ = self.recover_private_listing(metadata)
        self.assertEqual(state.get('venue_research_artifact_refs', []), [])
        self.assertEqual(state.get('venue_research_ref_rejections', 0), 0)

    def test_next_worker_recovers_handles_from_authenticated_result_zip(self):
        from race_ai import cycle_recovery as recovery
        from race_ai.frozen_day_cycle import read_p0
        from tests.test_frozen_day_cycle import sample,observation
        _,raw,metadata=sample();_,rows=read_p0(raw,metadata,expected_day='2030-04-01')
        outcome=observation(rows[0])
        ref=dict(artifact_id=123,run_id=88,head_sha='a'*40,digest='sha256:'+'b'*64)
        for handles,expected,rejected in (([ref],[ref],0),([{'artifact_id':True}],[],1)):
            with self.subTest(valid=not rejected),tempfile.TemporaryDirectory() as temporary:
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w') as saved:
                    saved.writestr('official-result-observations.json',json.dumps([outcome]))
                    saved.writestr('status.json',json.dumps({'day_jst':'2030-04-01',
                        'venue_research_artifact_refs':handles}))
                original=stream.getvalue()
                meta=dict(id=77,name='race-existing-cycle-99',expired=False,
                    created_at='2030-04-01T03:00:00Z',digest='sha256:'+hashlib.sha256(original).hexdigest(),
                    workflow_run={'id':99,'head_repository_id':1416489937})
                routes={'actions/artifacts/77':json.dumps(meta).encode(),'actions/artifacts/77/zip':original}
                with patch.object(recovery,'day_runs',return_value=[{'id':99}]), \
                     patch.object(recovery,'artifact_pages',return_value=[meta]), \
                     patch.object(recovery,'previous_source_control',return_value=None), \
                     patch('race_ai.observed_weight_learning.context_from_result_archive',return_value=None), \
                     patch('race_ai.observed_result_history.context_from_result_archive',return_value={
                         'receipt':{'created_at':meta['created_at']}}), \
                     patch('race_ai.observed_result_history.history_proof',return_value={}):
                    state=recovery.recover(routes.__getitem__,'2030-04-01',current_run=100,
                        out=Path(temporary),clock=lambda:NOW+timedelta(hours=4))
                self.assertEqual(state.get('venue_research_artifact_refs',[]),expected)
                self.assertEqual(state.get('venue_research_ref_rejections',0),rejected)
                self.assertEqual(state['observations'],[outcome])


if __name__=='__main__':unittest.main()
