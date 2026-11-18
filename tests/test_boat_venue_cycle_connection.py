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
        raw=b'fixture-cipher-zip'
        ref=dict(artifact_id=123,run_id=99,head_sha='a'*40,
                 digest='sha256:'+hashlib.sha256(raw).hexdigest())
        metadata=dict(id=123,name='boat-venue-research-p1-99-2',expired=False,
            created_at='2030-04-01T01:00:00Z',expires_at='2030-04-08T01:00:00Z',
            digest=ref['digest'],size_in_bytes=len(raw),workflow_run=dict(id=99,
                head_sha=ref['head_sha'],repository_id=1416489937,head_repository_id=1416489937))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'existing_cycle_output').mkdir()
            (root/'existing_cycle_output/official-result-observations.json').write_text('[]')
            with patch.object(runner,'ROOT',root), \
                 patch.object(runner,'load_state',return_value={'venue_research_artifact_refs':[ref]}), \
                 patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode(),
                            RUNNER_TEMP=str(root)), \
                 patch.object(runner,'gh',side_effect=[json.dumps(metadata).encode(),raw]), \
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



class VenueResearchDiagnosticTests(unittest.TestCase):
    """AST-isolated real orchestration, with invented boundaries and no keys."""
    PHASES=(
        'READBACK_PREFLIGHT','READBACK_METADATA','READBACK_ZIP','READBACK_VERIFY',
        'READBACK_CONTINUITY_LOAD','READBACK_CONTINUITY_REFS','READBACK_CONTINUITY_WRITE',
        'RETAIN_PREFLIGHT','RETAIN_CANDIDATE_SCAN','RETAIN_CANDIDATES',
        'RETAIN_ARCHIVE_SCAN','RETAIN_ARCHIVE_READER','RETAIN_ARCHIVES')

    def isolated(self,root,*,require_helper=False,**boundaries):
        import ast
        from datetime import datetime,timezone
        source=Path(__file__).resolve().parents[1]/'scripts/github_existing_cycle.py'
        tree=ast.parse(source.read_text())
        functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
        names=('venue_research_readback','venue_research_retain')
        for name in names:self.assertIn(name,functions,'Existing venue function is missing')
        if require_helper:
            self.assertIn('_venue_research_diagnostic',functions,
                'The fixed typed venue diagnostic helper is missing')
        selected=([functions['_venue_research_diagnostic']] if '_venue_research_diagnostic' in functions else [])
        selected.extend(functions[name] for name in names)
        def need(ok,reason):
            if not ok:raise ValueError(reason)
        namespace=dict(ROOT=root,Path=Path,json=json,os=os,datetime=datetime,timezone=timezone,need=need)
        namespace.update(boundaries)
        exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),namespace)
        return namespace

    def modules(self,definitions):
        from types import ModuleType
        result={}
        for name,attributes in definitions.items():
            module=ModuleType(name)
            for key,value in attributes.items():setattr(module,key,value)
            result[name]=module
        return result

    def run_readback(self,*,cut=None,error=None,pairs=False,artifact_id=123,outer_import=False):
        import sys
        from types import SimpleNamespace
        events=[];routes=[];writes=[];verified=[]
        raw=b'invented-private-cipher-archive'
        metadata=dict(id=123,name=('all-existing-model-pairs-99-1' if pairs else 'boat-venue-research-p1-99-1'),
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),size_in_bytes=len(raw),expired=False,
            created_at='2030-04-01T01:00:00Z',expires_at='2030-04-08T01:00:00Z',
            workflow_run=dict(id=99,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
        prior=dict(artifact_id=122,run_id=98,head_sha='b'*40,digest='sha256:'+'c'*64)
        continuity=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst='2030-04-01',
                        complete=True,venue_research_artifact_refs=[prior])
        admitted=dict(status='INVENTED_EXISTING_RECEIPT_VERIFIED',
            independent_pre_cutoff_receipt_verified=True,production_promoted=False,plaintext_published=False)
        failure=error if error is not None else ValueError('VENUE_PRIVATE_P1_RECEIPT_ARTIFACT_BYTES_INVALID')
        def stop(stage):
            if cut==stage:raise failure
        def state_key(mode):
            self.assertEqual(mode,'production');events.append('preflight');stop('preflight')
            return None
        def gh(route):
            routes.append(route)
            if route=='actions/artifacts/123':
                events.append('metadata');stop('metadata')
                return json.dumps(metadata).encode()
            if route=='actions/artifacts/123/zip':
                events.append('zip');stop('zip');return raw
            raise AssertionError('Unexpected synthetic readback route')
        def verifier(kind):
            def verify(data,meta,**options):
                events.append('verify_'+kind);stop('verify')
                verified.append((data,deepcopy(meta),options))
                return admitted
            return verify
        def load_state(path,day):
            events.append('continuity_load');stop('continuity_load')
            self.assertEqual(day,'2030-04-01')
            self.assertEqual(path,root/'cycle_recovery_output/continuity.json')
            return deepcopy(continuity)
        def validate(refs):
            events.append('continuity_refs');stop('continuity_refs')
            return deepcopy(refs)
        def write_state(path,state,*,key):
            events.append('continuity_write');stop('continuity_write')
            self.assertEqual(key,'state_sha256')
            writes.append(deepcopy(state))
            if cut=='continuity_write_after_commit':raise failure
        definitions={
            'race_ai.boat_venue_research_receipt':dict(
                verify_private_p1_artifact=verifier('venue'),validate_research_refs=validate),
            'race_ai.boat_pdca_state':dict(state_key=state_key),
            'race_ai.all_existing_model_receipt':dict(verify_private_pairs_artifact=verifier('pairs')),
            'race_ai.repeated_cycle':dict(write_state=write_state)}
        if outer_import:definitions['race_ai.boat_venue_research_receipt'].pop('verify_private_p1_artifact')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            namespace=self.isolated(root,gh=gh,load_state=load_state,event_day=lambda:'2030-04-01',
                datetime=SimpleNamespace(now=lambda tz:NOW))
            stream=io.StringIO()
            with patch.dict(sys.modules,self.modules(definitions)), \
                 patch.dict(os.environ,{'GITHUB_RUN_ID':'99','GITHUB_SHA':'a'*40},clear=True), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Network forbidden')), \
                 patch('subprocess.Popen',side_effect=AssertionError('Processes forbidden')), \
                 contextlib.redirect_stdout(stream):
                report=namespace['venue_research_readback'](artifact_id)
        return dict(report=report,printed=stream.getvalue(),events=events,routes=routes,writes=writes,
                    verified=verified,admitted=admitted,metadata=metadata,raw=raw,prior=prior)

    def run_retention(self,*,cut=None,error=None,candidates=True,archives=True,round_no=2,
                      archive_write_before_error=False,outer_import=False,blocked_output=False):
        import sys
        events=[];writes=[];calls={}
        failure=error if error is not None else ValueError('VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH')
        candidate_result=dict(status='INVENTED_EXISTING_CANDIDATES_RETAINED',retained_candidates=2,
            production_promoted=False,plaintext_published=False,
            pointers=[dict(source_commit='c'*40,artifact_id=123)])
        archive_result=dict(status='INVENTED_EXISTING_SOURCE_ARCHIVES_RETAINED',retained_archives=1)
        reader=object()
        def stop(stage):
            if cut==stage:raise failure
        class Scan:
            def __init__(self,path):self.path=path
            def __truediv__(self,part):return Scan(self.path/part)
            def rglob(self,pattern):
                events.append('candidate_scan');stop('candidate_scan')
                return self.path.rglob(pattern)
            def glob(self,pattern):
                events.append('archive_scan');stop('archive_scan')
                return self.path.glob(pattern)
        def retain_candidates(folders,repo):
            events.append('retain_candidates');calls['candidates']=(list(folders),repo);stop('candidates')
            writes.append('candidate_commit_completed')
            return candidate_result
        def readback_transport(repo,*,cache_root):
            events.append('archive_reader');calls['reader']=(repo,cache_root);stop('reader')
            return reader
        def retain_archives(folders,repo,*,readback_transport):
            events.append('retain_archives');calls['archives']=(list(folders),repo,readback_transport)
            if cut=='archives':
                if archive_write_before_error:writes.append('source_push_completed')
                raise failure
            writes.append('source_commit_completed')
            return archive_result
        definitions={
            'race_ai.boat_venue_research_retention':dict(
                retain_private_research=retain_candidates,retain_private_source_archives=retain_archives),
            'race_ai.boat_venue_research_cache':dict(research_readback_transport=readback_transport)}
        if outer_import:definitions['race_ai.boat_venue_research_retention'].pop('retain_private_research')
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary);root=parent/'repo';root.mkdir(mode=0o700)
            private=parent/'private';private.mkdir(mode=0o700)
            expected_candidates=[]
            if candidates:
                for kind in ('boat-venue-research-p1','boat-venue-research-pdca'):
                    folder=private/kind/'cycle-2'/'one';folder.mkdir(parents=True,mode=0o700)
                    (folder/'learning.json').write_bytes(b'invented-cipher-metadata')
                    expected_candidates.append(folder)
            expected_archives=[]
            if archives:
                folder=private/'boat-venue-research-archives'/'123';folder.mkdir(parents=True,mode=0o700)
                (folder/'archive.zip').write_bytes(b'invented-cipher-archive')
                expected_archives.append(folder)
            if blocked_output:(root/'existing_cycle_output').write_bytes(b'public-fixture-obstruction')
            def path(value):
                self.assertEqual(value,str(private))
                return Scan(private)
            namespace=self.isolated(root,Path=path)
            stream=io.StringIO()
            with patch.dict(sys.modules,self.modules(definitions)), \
                 patch.dict(os.environ,{'RUNNER_TEMP':str(private)},clear=True), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Network forbidden')), \
                 patch('subprocess.Popen',side_effect=AssertionError('Processes forbidden')), \
                 contextlib.redirect_stdout(stream):
                report=namespace['venue_research_retain'](round_no)
            persisted=json.loads((root/'existing_cycle_output/venue-research-retention.json').read_text())
            if 'candidates' in calls:
                self.assertEqual(calls['candidates'],(expected_candidates,root))
            if 'reader' in calls:
                self.assertEqual(calls['reader'],(root,private/'boat-venue-research-source-readback.git'))
            if 'archives' in calls:
                self.assertEqual(calls['archives'],(expected_archives,root,reader))
        return dict(report=report,printed=stream.getvalue(),persisted=persisted,events=events,writes=writes,
                    candidate_result=candidate_result,archive_result=archive_result,calls=calls)

    def assert_hold(self,out,phase,reason,*,retention=False):
        expected=dict(status=('HOLD_PRIVATE_VENUE_RETENTION' if retention else 'HOLD_PRIVATE_VENUE_P1_READBACK'),
                      production_promoted=False,plaintext_published=False)
        expected['retained_candidates' if retention else 'independent_pre_cutoff_receipt_verified']=0 if retention else False
        expected.update(diagnostic_phase=phase,diagnostic_reason=reason)
        self.assertEqual(out['report'],expected)
        self.assertEqual(json.loads(out['printed']),expected)
        if retention:self.assertEqual(out['persisted'],expected)
        self.assertIs(type(out['report']),dict)
        for key in ('diagnostic_phase','diagnostic_reason'):self.assertIs(type(out['report'][key]),str)

    def helper(self):
        namespace=self.isolated(Path('.'),require_helper=True)
        class NoIO:
            def __getattribute__(self,name):raise AssertionError('Diagnostic helper attempted I/O')
        def forbidden(*args,**kwargs):raise AssertionError('Diagnostic helper attempted a side effect')
        namespace.update(os=NoIO(),Path=forbidden,open=forbidden,gh=forbidden,print=forbidden)
        return namespace['_venue_research_diagnostic']

    def test_helper_exact_builtin_codes_and_all_thirteen_phases(self):
        diagnostic=self.helper()
        known=(
            (ValueError,'OWNER_STATE_KEY_REQUIRED'),
            (ValueError,'VENUE_RESEARCH_ARTIFACT_REQUIRED'),
            (ValueError,'VENUE_PRIVATE_P1_RECEIPT_ARTIFACT_BYTES_INVALID'),
            (ValueError,'ALL_MODEL_PAIR_RECEIPT_PAYLOAD_REPLAY_INVALID'),
            (ValueError,'VENUE_LEARNING_REMOTE_READBACK_MISMATCH'),
            (ValueError,'VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH'),
            (ValueError,'RESEARCH_CACHE_ORIGIN_CHANGED'),
            (ValueError,'STATE_GIT_OPERATION_FAILED_FETCH_HTTP_400'),
            (ValueError,'STATE_GIT_OPERATION_FAILED_FETCH_HTTP_599'),
            (RuntimeError,'GITHUB_API_READ_HTTP_400_HALT'),
            (RuntimeError,'GITHUB_API_READ_HTTP_404_HALT'),
            (RuntimeError,'GITHUB_API_READ_HTTP_429_HALT'),
            (RuntimeError,'GITHUB_API_READ_HTTP_500_HALT'),
            (RuntimeError,'GITHUB_API_READ_HTTP_599_HALT'),
            (RuntimeError,'GITHUB_API_TIMEOUT_HALT'))
        for phase in self.PHASES:
            for kind,code in known:
                with self.subTest(phase=phase,code=code):
                    result=diagnostic(kind(code),phase)
                    self.assertEqual(result,dict(diagnostic_phase=phase,diagnostic_reason=code))
                    self.assertIs(type(result),dict)
                    self.assertTrue(all(type(value) is str for value in result.values()))
        first=diagnostic(ValueError('OWNER_STATE_KEY_REQUIRED'),'READBACK_PREFLIGHT')
        second=diagnostic(ValueError('OWNER_STATE_KEY_REQUIRED'),'READBACK_PREFLIGHT')
        self.assertIsNot(first,second)

    def test_helper_refuses_private_lookalikes_and_hostile_inputs_without_inspection(self):
        diagnostic=self.helper()
        class DerivedValueError(ValueError):pass
        class DerivedRuntimeError(RuntimeError):pass
        known='OWNER_STATE_KEY_REQUIRED'
        variants=(Exception(known),KeyError(known),DerivedValueError(known),
            DerivedRuntimeError('GITHUB_API_READ_HTTP_404_HALT'),ValueError(),ValueError(known,'PRIVATE_PAYLOAD'),
            ValueError(b'OWNER_STATE_KEY_REQUIRED'),ValueError(None),ValueError(123),
            ValueError(known+' PRIVATE_KEY https://private.invalid/token'),
            ValueError('PRIVATE_PATH/'+known),ValueError('owner_state_key_required'),
            RuntimeError(known),ValueError('GITHUB_API_READ_HTTP_404_HALT'),
            RuntimeError('GITHUB_API_READ_HTTP_399_HALT'),RuntimeError('GITHUB_API_READ_HTTP_600_HALT'),
            RuntimeError('GITHUB_API_READ_HTTP_0404_HALT'),RuntimeError('GITHUB_API_READ_HTTP_404_HALT_PRIVATE'))
        for index,error in enumerate(variants):
            with self.subTest(case=index):
                self.assertEqual(diagnostic(error,'READBACK_METADATA'),
                    dict(diagnostic_phase='READBACK_METADATA',diagnostic_reason='UNCLASSIFIED_EXCEPTION'))
        diagnostic=self.helper()
        class Hostile:
            def __getattribute__(self,name):raise AssertionError('private property inspected')
            def __str__(self):raise AssertionError('private str inspected')
            def __repr__(self):raise AssertionError('private repr inspected')
        class PRIVATE_HOSTILE_ERROR(ValueError):
            def __getattribute__(self,name):raise AssertionError('private exception property inspected')
            def __str__(self):raise AssertionError('private exception str inspected')
            def __repr__(self):raise AssertionError('private exception repr inspected')
        class HostileString(str):
            def __hash__(self):raise AssertionError('private phase hash inspected')
            def __eq__(self,other):raise AssertionError('private phase equality inspected')
            def __str__(self):raise AssertionError('private phase str inspected')
            def __repr__(self):raise AssertionError('private phase repr inspected')
        known=ValueError('OWNER_STATE_KEY_REQUIRED')
        known.__cause__=PRIVATE_HOSTILE_ERROR('PRIVATE_CAUSE')
        known.__context__=PRIVATE_HOSTILE_ERROR('PRIVATE_CONTEXT')
        known.__notes__=[Hostile()]
        self.assertEqual(diagnostic(known,'READBACK_PREFLIGHT'),
            dict(diagnostic_phase='READBACK_PREFLIGHT',diagnostic_reason='OWNER_STATE_KEY_REQUIRED'))
        for index,error in enumerate((Hostile(),PRIVATE_HOSTILE_ERROR('PRIVATE_ARGS'),
                                      ValueError(Hostile()),ValueError(HostileString('OWNER_STATE_KEY_REQUIRED')))):
            with self.subTest(exception_case=index):
                self.assertEqual(diagnostic(error,'READBACK_VERIFY'),
                    dict(diagnostic_phase='READBACK_VERIFY',diagnostic_reason='UNCLASSIFIED_EXCEPTION'))
        for index,phase in enumerate((None,True,1,float('nan'),float('inf'),b'READBACK_METADATA','READBACK_METADATA PRIVATE_URL',
                                      Hostile(),HostileString('READBACK_METADATA'))):
            with self.subTest(phase_case=index):
                self.assertEqual(diagnostic(RuntimeError('GITHUB_API_READ_HTTP_404_HALT'),phase),
                    dict(diagnostic_phase='UNKNOWN_PHASE',diagnostic_reason='GITHUB_API_READ_HTTP_404_HALT'))


    def test_actual_readback_metadata_404_and_zip_429_stop_without_retry(self):
        for cut,phase,reason,events,routes in (
            ('metadata','READBACK_METADATA','GITHUB_API_READ_HTTP_404_HALT',
             ['preflight','metadata'],['actions/artifacts/123']),
            ('zip','READBACK_ZIP','GITHUB_API_READ_HTTP_429_HALT',
             ['preflight','metadata','zip'],['actions/artifacts/123','actions/artifacts/123/zip'])):
            with self.subTest(cut=cut):
                out=self.run_readback(cut=cut,error=RuntimeError(reason))
                self.assert_hold(out,phase,reason)
                self.assertEqual(out['events'],events)
                self.assertEqual(out['routes'],routes)
                self.assertEqual((out['verified'],out['writes']),([],[]))


    def test_actual_readback_both_verifiers_keep_fatal_hold_without_continuity(self):
        for pairs in (False,True):
            with self.subTest(pairs=pairs):
                out=self.run_readback(cut='verify',pairs=pairs,
                    error=ValueError('VENUE_PRIVATE_P1_RECEIPT_ARTIFACT_BYTES_INVALID'))
                self.assert_hold(out,'READBACK_VERIFY','VENUE_PRIVATE_P1_RECEIPT_ARTIFACT_BYTES_INVALID')
                self.assertEqual(out['events'],['preflight','metadata','zip','verify_'+('pairs' if pairs else 'venue')])
                self.assertEqual(len(out['routes']),2)
                self.assertEqual(out['writes'],[])

    def test_actual_readback_continuity_boundaries_preserve_completed_verification(self):
        prefix=['preflight','metadata','zip','verify_venue','continuity_load','continuity_refs','continuity_write']
        for cut,phase,count in (('continuity_load','READBACK_CONTINUITY_LOAD',5),
                                ('continuity_refs','READBACK_CONTINUITY_REFS',6),
                                ('continuity_write','READBACK_CONTINUITY_WRITE',7),
                                ('continuity_write_after_commit','READBACK_CONTINUITY_WRITE',7)):
            with self.subTest(cut=cut):
                out=self.run_readback(cut=cut,error=ValueError('VENUE_PRIVATE_P1_RECEIPT_REFERENCE_INVALID'))
                self.assert_hold(out,phase,'VENUE_PRIVATE_P1_RECEIPT_REFERENCE_INVALID')
                self.assertEqual(out['events'],prefix[:count])
                self.assertEqual(len(out['verified']),1)
                self.assertTrue(out['admitted']['independent_pre_cutoff_receipt_verified'])
                self.assertEqual(len(out['writes']),int(cut=='continuity_write_after_commit'))
                self.assertEqual(len(out['routes']),2)

    def test_actual_preflight_gates_hold_before_metadata_or_retention_scan(self):
        for argument,error,cut,reason in ((True,None,None,'VENUE_RESEARCH_ARTIFACT_REQUIRED'),
                (0,None,None,'VENUE_RESEARCH_ARTIFACT_REQUIRED'),
                (123,ValueError('OWNER_STATE_KEY_REQUIRED'),'preflight','OWNER_STATE_KEY_REQUIRED')):
            with self.subTest(argument=argument,cut=cut):
                out=self.run_readback(artifact_id=argument,error=error,cut=cut)
                self.assert_hold(out,'READBACK_PREFLIGHT',reason)
                self.assertEqual(out['events'],['preflight'])
                self.assertEqual((out['routes'],out['verified'],out['writes']),([],[],[]))
        for round_no in (True,0,-1):
            with self.subTest(round_no=round_no):
                out=self.run_retention(round_no=round_no)
                self.assert_hold(out,'RETAIN_PREFLIGHT','VENUE_RESEARCH_ROUND_REQUIRED',retention=True)
                self.assertEqual((out['events'],out['writes']),([],[]))

    def test_actual_success_and_not_needed_schemas_arguments_and_continuity_stay_unchanged(self):
        for pairs in (False,True):
            with self.subTest(pairs=pairs):
                out=self.run_readback(pairs=pairs)
                self.assertIs(out['report'],out['admitted'])
                self.assertEqual(json.loads(out['printed']),out['admitted'])
                self.assertNotIn('diagnostic_phase',out['report'])
                self.assertNotIn('diagnostic_reason',out['report'])
                self.assertEqual(out['events'],['preflight','metadata','zip',
                    'verify_'+('pairs' if pairs else 'venue'),'continuity_load','continuity_refs','continuity_write'])
                self.assertEqual(out['routes'],['actions/artifacts/123','actions/artifacts/123/zip'])
                self.assertEqual(out['verified'],[(out['raw'],out['metadata'],
                    dict(now=NOW,expected_run_id=99,expected_head_sha='a'*40))])
                reference=dict(artifact_id=123,run_id=99,head_sha='a'*40,digest=out['metadata']['digest'])
                self.assertEqual(out['writes'][0]['venue_research_artifact_refs'],[out['prior'],reference])
        for candidates,archives in ((False,False),(True,False),(False,True),(True,True)):
            with self.subTest(candidates=candidates,archives=archives):
                out=self.run_retention(candidates=candidates,archives=archives)
                if candidates:
                    self.assertIs(out['report'],out['candidate_result'])
                else:
                    expected=dict(status='PRIVATE_VENUE_RETENTION_NOT_NEEDED',retained_candidates=0,
                                  production_promoted=False,plaintext_published=False)
                    if archives:expected['source_archives']=out['archive_result']
                    self.assertEqual(out['report'],expected)
                if archives:self.assertIs(out['report']['source_archives'],out['archive_result'])
                self.assertNotIn('diagnostic_phase',out['report'])
                self.assertNotIn('diagnostic_reason',out['report'])
                self.assertEqual(out['persisted'],out['report'])
                self.assertEqual(json.loads(out['printed']),{k:v for k,v in out['report'].items() if k!='pointers'})
                self.assertEqual(out['events'].count('retain_candidates'),int(candidates))
                self.assertEqual(out['events'].count('archive_reader'),int(archives))
                self.assertEqual(out['events'].count('retain_archives'),int(archives))

    def test_actual_retention_scan_failures_keep_the_exact_failed_boundary(self):
        for cut,phase,events,writes in (
                ('candidate_scan','RETAIN_CANDIDATE_SCAN',['candidate_scan'],[]),
                ('archive_scan','RETAIN_ARCHIVE_SCAN',
                    ['candidate_scan','candidate_scan','retain_candidates','archive_scan'],['candidate_commit_completed'])):
            with self.subTest(cut=cut):
                out=self.run_retention(cut=cut,error=OSError('PRIVATE_PATH https://private.invalid/key'))
                self.assert_hold(out,phase,'UNCLASSIFIED_EXCEPTION',retention=True)
                self.assertEqual(out['events'],events)
                self.assertEqual(out['writes'],writes)

    def test_actual_retention_publisher_reader_and_archive_failures_do_not_retry(self):
        prefix=['candidate_scan','candidate_scan','retain_candidates','archive_scan','archive_reader','retain_archives']
        cases=(('candidates','RETAIN_CANDIDATES',3,'VENUE_LEARNING_REMOTE_READBACK_MISMATCH',[]),
               ('reader','RETAIN_ARCHIVE_READER',5,'RESEARCH_CACHE_ORIGIN_CHANGED',['candidate_commit_completed']),
               ('archives','RETAIN_ARCHIVES',6,'VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH',['candidate_commit_completed']))
        for cut,phase,count,reason,writes in cases:
            with self.subTest(cut=cut):
                out=self.run_retention(cut=cut,error=ValueError(reason))
                self.assert_hold(out,phase,reason,retention=True)
                self.assertEqual(out['events'],prefix[:count])
                self.assertEqual(out['writes'],writes)

    def test_actual_retention_hold_does_not_erase_prior_commit_or_claim_rollback(self):
        out=self.run_retention(cut='archives',archive_write_before_error=True,
            error=ValueError('VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH'))
        self.assert_hold(out,'RETAIN_ARCHIVES','VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH',retention=True)
        self.assertEqual(out['writes'],['candidate_commit_completed','source_push_completed'])
        self.assertEqual(out['events'].count('retain_candidates'),1)
        self.assertEqual(out['events'].count('retain_archives'),1)
        self.assertEqual(out['candidate_result']['pointers'],[dict(source_commit='c'*40,artifact_id=123)])
        self.assertEqual(out['report']['retained_candidates'],0)
        for key in ('write_performed','publication_performed','rollback_performed','source_requests'):
            self.assertNotIn(key,out['report'])


    def test_actual_unknown_exceptions_never_export_private_messages_or_class_names(self):
        class PRIVATE_SENTINEL_CLASS(ValueError):pass
        for index,error in enumerate((ValueError('PRIVATE_PATH https://private.invalid/PRIVATE_KEY'),
                                      PRIVATE_SENTINEL_CLASS('OWNER_STATE_KEY_REQUIRED'))):
            with self.subTest(case=index):
                readback=self.run_readback(cut='metadata',error=error)
                retained=self.run_retention(cut='archives',error=error)
                self.assert_hold(readback,'READBACK_METADATA','UNCLASSIFIED_EXCEPTION')
                self.assert_hold(retained,'RETAIN_ARCHIVES','UNCLASSIFIED_EXCEPTION',retention=True)
                for text in (readback['printed'],retained['printed'],json.dumps(retained['persisted'])):
                    for sentinel in ('PRIVATE_PATH','private.invalid','PRIVATE_KEY','PRIVATE_SENTINEL_CLASS'):
                        self.assertNotIn(sentinel,text)

    def test_original_outer_import_and_output_errors_are_not_moved_inside_catches(self):
        with self.assertRaises(ImportError):self.run_readback(outer_import=True)
        with self.assertRaises(ImportError):self.run_retention(outer_import=True)
        with self.assertRaises(FileExistsError):self.run_retention(blocked_output=True)


if __name__=='__main__':unittest.main()
