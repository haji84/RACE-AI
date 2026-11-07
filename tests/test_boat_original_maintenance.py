"""Bounded maintenance against invented API bytes and local encrypted Git."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_boat_private_original_vault_cli as vault_fixture
from tests.test_boat_private_original_vault import NOW, original, wire
from tests.test_boat_original_recovery import closed_run

try:
    M = importlib.import_module('scripts.boat_original_maintenance')
except ModuleNotFoundError:
    M = None


def view(ident=101, run=2):
    return dict(records=[dict(prediction=dict(artifact_id=ident, receipt_run_id=run,
        PRIVATE_NAME='NEVER_PRINT_PRIVATE_PAYLOAD'),comparison_predictions=[])])


class MaintenanceSelectionTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(M, 'bounded original maintenance is absent')

    def test_more_than128_archives_progress_past_cached_ids_on_next_invocation(self):
        rows=[dict(id=1000+i,name=f'boat-national-cutoff-2-cycle-{i+2:02d}') for i in range(130)]
        retained=set()
        first=M.select_native_batch(rows,2,lambda i:i in retained,128)
        self.assertEqual(len(first['selected']),128);self.assertEqual(first['deferred'],2)
        retained.update(first['selected'])
        second=M.select_native_batch(rows,2,lambda i:i in retained,128)
        self.assertEqual(second['selected'],[1128,1129]);self.assertEqual(second['deferred'],0)
        self.assertEqual(second['already_retained'],128)

    def test_source_control_always_includes_cached_continuity_in_same_batch(self):
        rows=[dict(id=801,name='race-cycle-continuity-7'),dict(id=802,name='race-source-control-7')]
        selected=M.select_native_batch(rows,7,lambda i:i==801,2)
        self.assertEqual(selected['selected'],[801,802]);self.assertEqual(selected['new_originals'],1)
        held=M.select_native_batch(rows,7,lambda i:i==801,1)
        self.assertEqual(held['selected'],[]);self.assertEqual(held['deferred'],1)
        with self.assertRaises(ValueError):M.select_native_batch(rows[1:],7,lambda _:False,2)

    def test_staged_continuity_is_shared_once_with_ordinary_control_in_the_same_capture(self):
        rows=[dict(id=801,name='race-cycle-continuity-7'),dict(id=802,name='race-source-control-7')]
        second=M.select_native_batch(rows,7,lambda _:False,1,already_selected=[801])
        self.assertEqual(second['selected'],[802])
        self.assertEqual(second['already_retained'],0,'staged selections became authenticated cached originals')
        self.assertEqual(second['new_originals'],1)

    def test_all_model_native_envelopes_are_targets_and_retained_kinds(self):
        owner=dict(records=[dict(prediction=dict(artifact_id=901,receipt_run_id='42'),comparison_predictions=[])])
        ids,runs=M.targets_from_view(owner)
        self.assertEqual(ids,[901]);self.assertEqual(runs,{42})
        selected=M.select_native_batch([dict(id=901,name='boat-all-model-forecasts-42-r0')],42,lambda _:False)
        self.assertEqual(selected['selected'],[901]);self.assertEqual(selected['new_originals'],1)

    def test_capture_byte_quota_is_reserved_before_any_selected_zip_is_loaded(self):
        rows=[dict(id=1000+i,name=f'boat-national-cutoff-2-cycle-{i+2:02d}') for i in range(3)]
        plan=M.select_native_batch(rows,2,lambda _:False,128,
            byte_limit=512*1024*1024,byte_cost=lambda _:2*160*1024*1024)
        self.assertEqual(plan['selected'],[1000]);self.assertEqual(plan['deferred'],2)
        self.assertEqual(plan['reserved_bytes'],320*1024*1024)

    def test_complete_pagination_is_preserved_and_changed_total_stops(self):
        endpoints={
            'actions/runs/2/artifacts?per_page=100':wire(dict(total_count=101,artifacts=[dict(id=i+1,name='non-native') for i in range(100)])),
            'actions/runs/2/artifacts?per_page=100&page=2':wire(dict(total_count=101,artifacts=[dict(id=101,name='non-native')]))}
        pages,rows=M.read_artifact_pages(2,lambda endpoint:endpoints[endpoint])
        self.assertEqual(len(rows),101);self.assertEqual(pages[0][1],endpoints[pages[0][0]])
        endpoints['actions/runs/2/artifacts?per_page=100&page=2']=wire(dict(total_count=102,artifacts=[dict(id=101,name='non-native')]))
        with self.assertRaises(ValueError):M.read_artifact_pages(2,lambda endpoint:endpoints[endpoint])


class MaintenanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M, 'bounded original maintenance is absent')
        self.fixture=vault_fixture.VaultCliTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.writer,self.reader=self.fixture.writer,self.fixture.reader
        raw,meta=original();self.raw,self.meta=raw,meta
        listed=json.loads(meta)
        self.responses={'actions/artifacts/101':meta,'actions/artifacts/101/zip':raw,'actions/runs/2':closed_run(),
            'actions/runs/2/artifacts?per_page=100':wire(dict(total_count=1,artifacts=[listed]))}
        self.calls=[]

    def get(self, endpoint):self.calls.append(endpoint);return self.responses[endpoint]

    def run_backfill(self, owner_view=None, get=None, **kwargs):
        with patch.dict(os.environ,self.fixture.env,clear=True):
            return M.backfill(owner_view or view(),self.writer.repo,transport=self.writer,
                readback_transport=self.reader,github_get=get or self.get,now=NOW,**kwargs)

    def bounded_fixture(self, native_by_run, retained=(), closed=None):
        """Invented metadata with real signed progress and no expensive ZIPs."""
        retained=set(retained);closures=deepcopy(closed or {});runs_by_id={}
        for run,ids in native_by_run.items():
            for ident in ids:
                runs_by_id[ident]=run
                _,metadata=original(ident=ident,run=run)
                self.responses[f'actions/artifacts/{ident}']=metadata
            info=json.loads(closed_run());info.update(id=run,run_attempt=2)
            self.responses[f'actions/runs/{run}']=wire(info)
            rows=[json.loads(self.responses[f'actions/artifacts/{ident}']) for ident in ids]
            for offset in range(0,max(1,len(rows)),100):
                endpoint=f'actions/runs/{run}/artifacts?per_page=100'+('' if offset==0 else f'&page={offset//100+1}')
                self.responses[endpoint]=wire(dict(total_count=len(rows),artifacts=rows[offset:offset+100]))
        owner=self
        class Reader:
            def __init__(self,*args,**kwargs):self.closures={};self.artifacts=type('Artifacts',(),{'cache':{}})()
            def closed_run_descriptor(self,run):
                if run not in closures:return None
                return dict(state=dict(identity=dict(run_id=run),originals=[dict(artifact_id=i) for i in closures[run]]),
                            capture_plain_bytes=10,capture_cipher_bytes=10)
            def has_closed_run(self,run):return run in closures
            def __call__(self,endpoint):return owner.get(endpoint)
        def lookup(ident,*args,**kwargs):
            return dict(artifact_id=ident,kind='P0') if ident in retained else None
        def descriptor(_git,_parent,locator,_key):
            return dict(header=dict(summary=dict(run_id=runs_by_id[locator['artifact_id']],kind='P0'),
                                    files={'original.zip':dict(size=100)}),cipher_size=120)
        def capture(ids,_repo,parent,*args,**kwargs):
            retained.update(ids)
            return dict(source_commit=parent,locators=[dict(artifact_id=i,kind='P0') for i in ids])
        def closure(raw,_pages,_repo,*,expected_parent,**kwargs):
            run=json.loads(raw)['id'];closures[run]=list(native_by_run[run])
            return dict(source_commit=expected_parent)
        from contextlib import ExitStack
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(M.R,'ArtifactRecovery',Reader))
        stack.enter_context(patch.object(M.R,'retain_closed_run_responses',side_effect=closure))
        stack.enter_context(patch.object(M.V,'lookup_original',side_effect=lookup))
        stack.enter_context(patch.object(M.V,'_batch_entry',side_effect=descriptor))
        stack.enter_context(patch.object(M.VCLI,'_capture',side_effect=capture))
        return retained,closures

    def dedicated_vault(self):
        """Seed only an invented local ref from its complete legacy tree."""
        legacy=self.writer
        dedicated=vault_fixture.LocalGit(legacy.repo,ref=M.V.VAULT_REF)
        dedicated.push(self.fixture.parent,None)
        self.writer=dedicated
        self.reader=vault_fixture.LocalGit(self.reader.repo,ref=M.V.VAULT_REF)
        peer=self.fixture.git('parallel-writer',self.fixture.root/'remote.git')
        peer=vault_fixture.LocalGit(peer.repo,ref=M.V.VAULT_REF)
        return legacy,peer

    def append(self,git,path='parallel/append.enc',body=b'concurrent encrypted fixture'):
        parent=git.head();git.fetch(parent)
        commit=git.commit({path:body},parent);git.push(commit,parent)
        return commit

    def test_dedicated_vault_ignores_a_legacy_source_append_during_slow_capture(self):
        legacy,_=self.dedicated_vault();source=[]
        def during_zip(endpoint):
            if endpoint.endswith('/zip'):
                source.append(self.append(legacy,'source/current.enc'))
            return self.get(endpoint)
        report=self.run_backfill(get=during_zip)
        self.assertTrue(report['complete']);self.assertEqual(legacy.head(),source[0])
        self.assertNotEqual(self.writer.head(),legacy.head())
        self.assertFalse(self.writer.exists(report['source_commit'],'source/current.enc'))
        self.assertIsNotNone(M.V.lookup_original(101,self.writer.repo,transport=self.writer,
            key=vault_fixture.KEY))

    def test_capture_refreshes_a_dedicated_descendant_without_repeating_gets(self):
        _,peer=self.dedicated_vault()
        def during_zip(endpoint):
            if endpoint.endswith('/zip'):self.append(peer)
            return self.get(endpoint)
        report=self.run_backfill(get=during_zip)
        self.assertTrue(report['complete'])
        self.assertEqual(self.writer.read(report['source_commit'],'parallel/append.enc',100),b'concurrent encrypted fixture')
        self.assertTrue(all(self.calls.count(endpoint)==1 for endpoint in self.responses))

    def test_catalog_cas_refresh_uses_the_same_actual_responses(self):
        _,peer=self.dedicated_vault();retain=M.R.retain_closed_run_responses;attempts=[]
        def concurrent(*args,**kwargs):
            attempts.append(kwargs['expected_parent'])
            if len(attempts)==1:self.append(peer)
            return retain(*args,**kwargs)
        with patch.object(M.R,'retain_closed_run_responses',side_effect=concurrent):
            report=self.run_backfill()
        self.assertTrue(report['complete']);self.assertEqual(len(attempts),2)
        self.assertTrue(all(self.calls.count(endpoint)==1 for endpoint in self.responses))

    def test_progress_cas_refresh_preserves_a_concurrent_unrelated_append(self):
        _,peer=self.dedicated_vault();push=self.writer.push;attempts=[]
        def concurrent(commit,parent):
            if self.writer.exists(commit,M.PROGRESS_PATH):
                attempts.append(parent)
                if len(attempts)==1:self.append(peer)
            return push(commit,parent)
        with patch.object(self.writer,'push',side_effect=concurrent):report=self.run_backfill()
        self.assertTrue(report['complete']);self.assertEqual(len(attempts),2)
        self.assertEqual(self.writer.read(report['source_commit'],'parallel/append.enc',100),b'concurrent encrypted fixture')
        self.assertEqual(self.calls.count('actions/artifacts/101/zip'),1)

    def test_another_maintenance_progress_write_during_capture_holds_without_overwrite(self):
        _,peer=self.dedicated_vault();written=[]
        def during_zip(endpoint):
            if endpoint.endswith('/zip'):
                parent=peer.head();peer.fetch(parent)
                state=M._progress(peer,parent,M.V._keys(None)[1]);state['run_after']=77
                raw=M.V._signed(state,M.V._keys(None)[1]);written.append(raw)
                self.append(peer,M.PROGRESS_PATH,raw)
            return self.get(endpoint)
        with self.assertRaisesRegex(ValueError,'^ORIGINAL_MAINTENANCE_PROGRESS_CONCURRENT_UPDATE$'):
            self.run_backfill(get=during_zip)
        head=self.writer.head();self.writer.fetch(head)
        self.assertEqual(self.writer.read(head,M.PROGRESS_PATH,1024*1024),written[0])
        self.assertFalse(self.writer.exists(head,'state/boat-original-recovery/v1/runs/2/latest.json'))

    def test_another_maintenance_progress_write_before_cas_holds_without_retry(self):
        _,peer=self.dedicated_vault();push=self.writer.push;attempts=[];written=[]
        def concurrent(commit,parent):
            if self.writer.exists(commit,M.PROGRESS_PATH):
                attempts.append(parent)
                state=M._progress(peer,parent,M.V._keys(None)[1]);state['run_after']=77
                raw=M.V._signed(state,M.V._keys(None)[1]);written.append(raw)
                self.append(peer,M.PROGRESS_PATH,raw)
            return push(commit,parent)
        with patch.object(self.writer,'push',side_effect=concurrent),self.assertRaisesRegex(
                ValueError,'^ORIGINAL_MAINTENANCE_PROGRESS_CONCURRENT_UPDATE$'):
            self.run_backfill()
        self.assertEqual(len(attempts),1)
        head=self.writer.head();self.writer.fetch(head)
        self.assertEqual(self.writer.read(head,M.PROGRESS_PATH,1024*1024),written[0])

    def test_missing_archive_ref_during_capture_holds(self):
        _,peer=self.dedicated_vault()
        def during_zip(endpoint):
            if endpoint.endswith('/zip'):peer._run(['push',peer.push_url,':refs/heads/'+peer.ref])
            return self.get(endpoint)
        with self.assertRaisesRegex(ValueError,'^VAULT_REF_CONCURRENT_UPDATE_OR_MISSING$'):
            self.run_backfill(get=during_zip)
        self.assertIsNone(self.writer.head())

    def test_divergent_archive_ref_during_capture_holds(self):
        _,peer=self.dedicated_vault()
        def during_zip(endpoint):
            if endpoint.endswith('/zip'):
                divergent=peer.commit({'divergent.enc':b'fixture fork'},None)
                peer._run(['push','--force',peer.push_url,divergent+':refs/heads/'+peer.ref])
            return self.get(endpoint)
        with self.assertRaisesRegex(ValueError,'^VAULT_PARENT_REFRESH_ANCESTRY_UNVERIFIED$'):
            self.run_backfill(get=during_zip)

    def test_unknown_git_denial_and_integrity_failures_are_never_retried(self):
        failures=['STATE_GIT_OPERATION_FAILED','GITHUB_API_READ_HTTP_403_HALT',
                  'ORIGINAL_RECOVERY_CLOSED_RUN_IMMUTABLE_CONFLICT']
        for reason in failures:
            with self.subTest(reason=reason),patch.object(M.R,'retain_closed_run_responses',
                    side_effect=ValueError(reason)) as retain,self.assertRaisesRegex(ValueError,'^'+reason+'$'):
                self.run_backfill()
            self.assertEqual(retain.call_count,1)

    def test_catalog_known_cas_retries_stop_after_three_attempts(self):
        with patch.object(M.R,'retain_closed_run_responses',side_effect=ValueError(
                'ORIGINAL_RECOVERY_CATALOG_REF_CONCURRENT_UPDATE')) as retain,self.assertRaisesRegex(
                ValueError,'^ORIGINAL_RECOVERY_CATALOG_REF_CONCURRENT_UPDATE$'):
            self.run_backfill()
        self.assertEqual(retain.call_count,3)
        self.assertTrue(all(self.calls.count(endpoint)==1 for endpoint in self.responses))

    def test_required_targets_survive_run_and_target_window_rotation(self):
        native={run:[1000+run] for run in range(2,131)}
        retained,closures=self.bounded_fixture(native,closed={run:[] for run in native})
        owner=dict(records=[dict(prediction=dict(artifact_id=ids[0]),comparison_predictions=[])
                            for ids in native.values()])
        reports=[]
        for _ in range(10):
            reports.append(self.run_backfill(owner))
            if reports[-1]['complete']:break
        self.assertEqual(len(retained),129,'a completed target window lost deferred rerun requirements')
        self.assertTrue(reports[-1]['complete'])
        self.assertEqual(sum(report['newly_retained_originals'] for report in reports),129)
        self.assertTrue(all(set(native[run])<=set(closures[run]) for run in native))

    def test_descriptor_limit_preserves_selected_slice_and_eventually_closes_large_run(self):
        cached=list(range(10000,10128));new=list(range(1000,1400))
        retained,_=self.bounded_fixture({2:cached,3:new},retained=cached,closed={2:cached})
        owner=dict(records=[dict(prediction=dict(artifact_id=i),comparison_predictions=[]) for i in cached]+
                           [dict(prediction=dict(receipt_run_id=3),comparison_predictions=[])])
        reports=[]
        for _ in range(6):
            reports.append(self.run_backfill(owner))
            if reports[-1]['complete']:break
        self.assertGreater(reports[0]['newly_retained_originals'],0,'descriptor exhaustion discarded a useful capture slice')
        self.assertEqual(set(new)-retained,set())
        self.assertTrue(reports[-1]['complete'],'cached target scans starved the final native descriptor slice')
        self.assertTrue(all(report['descriptor_lookups']<=512 and report['selected_capture_ids']<=128 for report in reports))

    def test_oversized_cached_run_does_not_starve_another_pending_run(self):
        cached=list(range(1000,1600))
        retained,_=self.bounded_fixture({2:cached,3:[3000]},retained=cached)
        reports=[self.run_backfill(dict(records=[]),run_ids=[2,3]) for _ in range(3)]
        self.assertIn(3000,retained,'a run larger than one descriptor pass starved all later run work')
        self.assertFalse(reports[-1]['complete'])
        self.assertTrue(all(report['descriptor_lookups']<=512 for report in reports))

    def test_growing_target_list_keeps_cursor_and_requires_a_fresh_complete_cycle(self):
        ids=list(range(1000,1130))
        self.bounded_fixture({2:ids},retained=ids,closed={2:ids})
        def owner(selected):return dict(records=[dict(prediction=dict(artifact_id=i),comparison_predictions=[])
                                                for i in selected])
        first=self.run_backfill(owner(ids[:-1]))
        second=self.run_backfill(owner(ids))
        self.assertEqual(first['target_descriptors_checked'],128)
        self.assertEqual(second['target_descriptors_checked'],2,'a growing view restarted its already checked prefix')
        self.assertFalse(second['target_cycle_complete'])
        third=self.run_backfill(owner(ids));fourth=self.run_backfill(owner(ids))
        self.assertFalse(third['complete']);self.assertTrue(fourth['complete'])

    def test_cited_forecasts_across_fifteen_runs_precede_older_uncited_archives(self):
        cited=list(range(10000,10080));supplementary=list(range(1000,1200))
        native={run:[ident for index,ident in enumerate(cited) if index%15==run-2] for run in range(2,17)}
        native[2]=supplementary+native[2]
        retained,_=self.bounded_fixture(native)
        owner=dict(records=[dict(prediction=dict(artifact_id=ident),comparison_predictions=[]) for ident in cited])
        first=self.run_backfill(owner)
        self.assertEqual(set(cited)-retained,set(),'uncited native archives consumed the cited forecast batch')
        self.assertGreaterEqual(len(set(supplementary)&retained),32)
        self.assertEqual(first['runs_scanned'],15)
        self.assertLessEqual(first['selected_capture_ids'],128);self.assertFalse(first['complete'])
        for _ in range(4):
            last=self.run_backfill(owner)
            if last['complete']:break
        self.assertTrue(last['complete']);self.assertEqual(retained,set(cited+supplementary))

    def test_priority_capture_does_not_close_a_run_with_an_unretained_uncited_original(self):
        raw,metadata=original(ident=102,run=2)
        self.responses.update({'actions/artifacts/102':metadata,'actions/artifacts/102/zip':raw,
            'actions/runs/2/artifacts?per_page=100':wire(dict(total_count=2,
                artifacts=[json.loads(self.meta),json.loads(metadata)]))})
        with patch.object(M,'MAX_ARTIFACTS',1),patch.object(M,'MAX_PRIORITY_ARTIFACTS',1),\
             patch.object(M.R,'retain_closed_run_responses',side_effect=AssertionError('uncited original was hidden from closure')):
            report=self.run_backfill()
        self.assertEqual(report['selected_capture_ids'],1)
        self.assertEqual(report['deferred_native_artifacts'],1)
        self.assertEqual(report['closed_runs_retained'],0);self.assertFalse(report['complete'])
        self.assertIsNotNone(M.V.lookup_original(101,self.writer.repo,transport=self.writer,key=vault_fixture.KEY))
        self.assertIsNone(M.V.lookup_original(102,self.writer.repo,transport=self.writer,key=vault_fixture.KEY))

    def test_required_window_over128_preserves_secondary_progress_then_closes(self):
        cited=list(range(10000,10200));supplementary=list(range(1000,1200))
        retained,_=self.bounded_fixture({2:supplementary+cited})
        owner=dict(records=[dict(prediction=dict(artifact_id=ident),comparison_predictions=[]) for ident in cited])
        first=self.run_backfill(owner)
        self.assertEqual(len(set(cited)&retained),96)
        self.assertEqual(len(set(supplementary)&retained),32)
        self.assertFalse(first['target_cycle_complete']);self.assertFalse(first['complete'])
        reports=[first]
        for _ in range(8):
            reports.append(self.run_backfill(owner))
            if reports[-1]['complete']:break
        self.assertEqual(retained,set(cited+supplementary));self.assertTrue(reports[-1]['complete'])
        self.assertTrue(all(report['selected_capture_ids']<=128 and report['descriptor_lookups']<=512 and
                            report['reserved_io_bytes']<=512*1024*1024 for report in reports))

    def test_ordinary_reserve_is_uncited_even_when_cited_ids_sort_first(self):
        cited=list(range(1000,1200));supplementary=list(range(10000,10200))
        retained,_=self.bounded_fixture({2:cited+supplementary})
        owner=dict(records=[dict(prediction=dict(artifact_id=ident),comparison_predictions=[]) for ident in cited])
        report=self.run_backfill(owner)
        self.assertEqual(len(set(cited)&retained),96)
        self.assertEqual(len(set(supplementary)&retained),32,'later cited IDs consumed the ordinary native reserve')
        self.assertEqual(report['priority_capture_ids'],96);self.assertEqual(report['ordinary_capture_ids'],32)

    def test_old_completed_descriptor_progress_revisits_missing_cited_originals_once(self):
        cited=list(range(10000,10080));supplementary=list(range(1000,1200))
        retained,_=self.bounded_fixture({2:supplementary+cited})
        with patch.dict(os.environ,self.fixture.env,clear=True):
            parent=self.writer.head();self.writer.fetch(parent);key=M.V._keys(None)[1]
            state=M._progress(self.writer,parent,key)
            state.pop('priority_policy_version',None)
            state.update(targets_sha256=M.V._sha(M.V._wire(cited)),target_cycle_complete=True,
                         pending_runs=[2],pending_targets={'2':cited})
            self.append(self.writer,M.PROGRESS_PATH,M.V._signed(state,key))
        owner=dict(records=[dict(prediction=dict(artifact_id=ident),comparison_predictions=[]) for ident in cited])
        first=self.run_backfill(owner)
        self.assertEqual(first['target_descriptors_checked'],80)
        self.assertEqual(set(cited)-retained,set())
        second=self.run_backfill(owner)
        self.assertEqual(second['target_descriptors_checked'],0,'the policy migration repeated a completed priority cycle')

    def test_growing_cited_view_still_advances_uncited_native_archives_each_pass(self):
        cited=list(range(10000,11000));supplementary=list(range(1000,1400))
        retained,_=self.bounded_fixture({2:supplementary+cited})
        previous=0
        for count in (200,328,456,584,712):
            owner=dict(records=[dict(prediction=dict(artifact_id=ident),comparison_predictions=[])
                                for ident in cited[:count]])
            report=self.run_backfill(owner)
            ordinary=len(set(supplementary)&retained)
            self.assertGreaterEqual(ordinary-previous,32,'continuous cited growth starved ordinary native progress')
            self.assertLessEqual(report['priority_capture_ids'],96)
            self.assertLessEqual(report['selected_capture_ids'],128)
            self.assertFalse(report['complete']);self.assertFalse(report['full_current_view_readback_verified'])
            previous=ordinary

    def test_actual_capture_closure_and_cached_replay_require_no_live_fallback(self):
        report=self.run_backfill()
        self.assertEqual(report['newly_retained_originals'],1)
        self.assertEqual(report['closed_runs_retained'],1);self.assertTrue(report['complete'])
        self.assertEqual(self.calls.count('actions/artifacts/101'),1)
        self.assertEqual(self.calls.count('actions/runs/2'),1)
        again=self.run_backfill(get=lambda _:self.fail('cached closed run used a live GET'))
        self.assertEqual(again['newly_retained_originals'],0);self.assertTrue(again['complete'])
        self.assertNotIn('PRIVATE_NAME',json.dumps(report));self.assertNotIn('NEVER_PRINT',json.dumps(report))

    def test_cached_descriptor_and_closed_probe_never_restore_each_native_zip(self):
        self.run_backfill()
        with patch.object(M.V,'restore_original',side_effect=AssertionError('unbounded cached ZIP restore')):
            result=self.run_backfill(get=lambda _:self.fail('cached metadata used live API'))
        self.assertTrue(result['complete']);self.assertFalse(result['full_current_view_readback_verified'])

    def test_new_target_from_rerun_is_captured_and_gets_new_attempt_closure(self):
        self.run_backfill()
        raw,metadata=original(ident=102,run=2)
        second=json.loads(closed_run());second['run_attempt']=2
        self.responses.update({'actions/artifacts/102':metadata,'actions/artifacts/102/zip':raw,
            'actions/runs/2':wire(second),'actions/runs/2/artifacts?per_page=100':wire(dict(
                total_count=2,artifacts=[json.loads(self.meta),json.loads(metadata)]))})
        report=self.run_backfill(view(ident=102))
        self.assertEqual(report['newly_retained_originals'],1)
        self.assertEqual(report['closed_runs_retained'],1);self.assertTrue(report['complete'])
        again=self.run_backfill(view(ident=102),get=lambda _:self.fail('latest rerun used live API'))
        self.assertTrue(again['complete'])

    def test_capture_byte_limit_defers_before_zip_request(self):
        with patch.object(M.V,'MAX_BATCH_PLAIN',100):report=self.run_backfill()
        self.assertEqual(report['selected_capture_ids'],0)
        self.assertEqual(report['deferred_native_artifacts'],1);self.assertFalse(report['complete'])
        self.assertNotIn('actions/artifacts/101/zip',self.calls)

    def test_closure_aggregate_quota_is_checked_before_any_native_zip_restore(self):
        with patch.dict(os.environ,self.fixture.env,clear=True):
            M.VCLI._capture([101],self.writer.repo,self.writer.head(),self.writer,self.reader,self.get,NOW)
        with patch.object(M,'_restore_cost',return_value=512*1024*1024+1),\
             patch.object(M.V,'restore_original',side_effect=AssertionError('ZIP read before quota')):
            report=self.run_backfill()
        self.assertEqual(report['closed_runs_retained'],0)
        self.assertEqual(report['byte_deferred_runs'],1);self.assertFalse(report['complete'])

    def test_target_descriptor_cursor_advances_after128_cached_targets_without_zip_reads(self):
        ids=list(range(1000,1129));owner=dict(records=[dict(prediction=dict(artifact_id=i),comparison_predictions=[]) for i in ids])
        class CachedReader:
            def __init__(self,*args,**kwargs):self.closures={};self.artifacts=type('Artifacts',(),{'cache':{}})()
            def closed_run_descriptor(self,run):
                return dict(state=dict(identity=dict(run_id=run),originals=[dict(artifact_id=i) for i in ids]),
                            capture_plain_bytes=10,capture_cipher_bytes=10)
            def has_closed_run(self,run):return True
            def __call__(self,_):raise AssertionError('cached target selected a live read')
        def descriptor(_git,_parent,locator,_key):
            return dict(header=dict(summary=dict(run_id=2,kind='P0'),files={'original.zip':dict(size=100)}),cipher_size=120)
        def locator(ident,*args,**kwargs):return dict(artifact_id=ident,kind='P0')
        with patch.object(M.R,'ArtifactRecovery',CachedReader),patch.object(M.V,'lookup_original',side_effect=locator),\
             patch.object(M.V,'_batch_entry',side_effect=descriptor),patch.object(M.V,'restore_original',side_effect=AssertionError('ZIP read')):
            first=self.run_backfill(owner);second=self.run_backfill(owner)
        self.assertEqual(first['target_descriptors_checked'],128)
        self.assertFalse(first['target_cycle_complete']);self.assertFalse(first['complete'])
        self.assertEqual(second['target_descriptors_checked'],1)
        self.assertTrue(second['target_cycle_complete']);self.assertTrue(second['complete'])

    def test_cached_response_byte_quota_rotates_work_instead_of_repeating_first_run(self):
        verified=[]
        class CachedReader:
            def __init__(self,*args,**kwargs):self.closures={};self.artifacts=type('Artifacts',(),{'cache':{}})()
            def closed_run_descriptor(self,run):
                return dict(state=dict(identity=dict(run_id=run),originals=[]),
                            capture_plain_bytes=150*1024*1024,capture_cipher_bytes=150*1024*1024)
            def has_closed_run(self,run):verified.append(run);return True
            def __call__(self,_):raise AssertionError('cached response used live API')
        owner=dict(records=[dict(prediction=dict(receipt_run_id=i),comparison_predictions=[]) for i in (2,3)])
        with patch.object(M.R,'ArtifactRecovery',CachedReader),patch.object(M.V,'restore_original',side_effect=AssertionError('ZIP read')):
            first=self.run_backfill(owner);second=self.run_backfill(owner)
        self.assertEqual(verified,[2,3])
        self.assertEqual(first['reserved_io_bytes'],300*1024*1024)
        self.assertEqual(second['reserved_io_bytes'],300*1024*1024)
        self.assertFalse(first['complete']);self.assertFalse(second['full_current_view_readback_verified'])

    def test_active_run_can_retain_originals_but_never_claim_closed_or_complete(self):
        self.responses['actions/runs/2']=closed_run(status='in_progress')
        report=self.run_backfill()
        self.assertEqual(report['newly_retained_originals'],1);self.assertEqual(report['closed_runs_retained'],0)
        self.assertEqual(report['active_runs'],1);self.assertFalse(report['complete'])

    def test_run_limit_defers_excess_without_querying_or_claiming_the_later_runs(self):
        owner=dict(records=[dict(prediction=dict(receipt_run_id=i),comparison_predictions=[]) for i in range(2,20)])
        for ident in range(2,20):
            run=json.loads(closed_run(status='in_progress'));run['id']=ident
            self.responses[f'actions/runs/{ident}']=wire(run)
            self.responses[f'actions/runs/{ident}/artifacts?per_page=100']=wire(dict(total_count=0,artifacts=[]))
        report=self.run_backfill(owner)
        self.assertEqual(report['runs_scanned'],16);self.assertEqual(report['deferred_runs'],2)
        self.assertFalse(report['complete']);self.assertNotIn('actions/runs/18',self.calls)
        self.calls.clear();second=self.run_backfill(owner)
        self.assertEqual(second['runs_scanned'],2)
        self.assertIn('actions/runs/18',self.calls);self.assertNotIn('actions/runs/2',self.calls)

    def test_denial_stops_without_zip_retry_or_archive_reselection(self):
        def denied(endpoint):self.calls.append(endpoint);raise RuntimeError('GITHUB_API_READ_HTTP_403_HALT')
        with self.assertRaises(RuntimeError):self.run_backfill(get=denied)
        self.assertEqual(self.calls,['actions/artifacts/101'])
        self.assertEqual(self.writer.head(),self.fixture.parent)

    def test_cli_missing_key_stops_before_view_selection_or_get_and_prints_fixed_counts(self):
        out=io.StringIO();env=dict(self.fixture.env);env.pop('RACE_AI_STATE_KEY')
        with patch.dict(os.environ,env,clear=True),redirect_stdout(out):
            code=M.main(['backfill','--repo-root',str(self.writer.repo),'--output',str(self.fixture.root/'report.json')],
                transport=self.writer,readback_transport=self.reader,github_get=lambda _:self.fail('GET without key'),view_loader=lambda _:self.fail('view without key'),now=NOW)
        self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue())['status'],'BOAT_ORIGINAL_MAINTENANCE_REJECTED')

    def test_direct_backfill_also_requires_actions_owner_context_before_transport(self):
        env=dict(self.fixture.env);env.pop('GITHUB_ACTIONS')
        with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):
            M.backfill(view(),self.writer.repo,transport=self.writer,readback_transport=self.reader,
                github_get=lambda _:self.fail('direct API used a live GET outside Actions'),now=NOW)

    def test_cli_success_writes_only_private_aggregate_counts(self):
        output=self.fixture.root/'maintenance-report.json';printed=io.StringIO()
        with patch.dict(os.environ,self.fixture.env,clear=True),redirect_stdout(printed):
            code=M.main(['backfill','--repo-root',str(self.writer.repo),'--output',str(output),'--artifactID','101'],
                transport=self.writer,readback_transport=self.reader,github_get=self.get,
                view_loader=lambda _:view(),now=NOW)
        self.assertEqual(code,0)
        report=json.loads(printed.getvalue());self.assertEqual(report,json.loads(output.read_bytes()))
        self.assertEqual(output.stat().st_mode&0o777,0o600)
        self.assertNotIn('PRIVATE_NAME',printed.getvalue());self.assertNotIn('NEVER_PRINT',printed.getvalue())

    def test_explicit_run_retains_zero_prediction_archives(self):
        result=self.run_backfill(dict(records=[]),run_ids=[2])
        self.assertEqual(result['newly_retained_originals'],1)
        self.assertEqual(result['closed_runs_retained'],1);self.assertTrue(result['complete'])
        again=self.run_backfill(dict(records=[]),run_ids=[2],get=lambda _:self.fail('explicit closed run used live API'))
        self.assertTrue(again['complete'])

    def test_cli_run_ids_and_exact_checkout_config_merge_without_prediction_rows(self):
        config=self.writer.repo/'audit/state/boat-model-recovery-input.json'
        config.parent.mkdir(parents=True,exist_ok=True)
        config.write_bytes(wire(dict(schema='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1',run_ids=[2])))
        output=self.fixture.root/'explicit-report.json';printed=io.StringIO()
        with patch.dict(os.environ,self.fixture.env,clear=True),redirect_stdout(printed):
            code=M.main(['backfill','--repo-root',str(self.writer.repo),'--output',str(output),
                         '--run-id','2','--run-config','audit/state/boat-model-recovery-input.json'],
                transport=self.writer,readback_transport=self.reader,github_get=self.get,
                view_loader=lambda _:dict(records=[]),now=NOW)
        self.assertEqual(code,0);self.assertTrue(json.loads(printed.getvalue())['complete'])
        self.assertEqual(json.loads(printed.getvalue())['closed_runs_retained'],1)

    def test_invalid_run_config_and_explicit_ids_reject_before_live_get(self):
        config=self.writer.repo/'audit/state/boat-model-recovery-input.json'
        config.parent.mkdir(parents=True,exist_ok=True)
        invalid=[dict(schema='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1',run_ids=[2,2]),
                 dict(schema='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1',run_ids=[True]),
                 dict(schema='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1',run_ids=list(range(1,18))),
                 dict(schema='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1',run_ids=[2],other=True)]
        for value in invalid:
            config.write_bytes(wire(value));printed=io.StringIO()
            with self.subTest(value=value),patch.dict(os.environ,self.fixture.env,clear=True),redirect_stdout(printed):
                code=M.main(['backfill','--repo-root',str(self.writer.repo),'--output',str(self.fixture.root/'invalid-report.json'),
                             '--run-config','audit/state/boat-model-recovery-input.json'],
                    transport=self.writer,readback_transport=self.reader,github_get=lambda _:self.fail('GET before config validation'),
                    view_loader=lambda _:dict(records=[]),now=NOW)
            self.assertEqual(code,2)
        with self.assertRaises(ValueError):self.run_backfill(dict(records=[]),run_ids=[0])


if __name__=='__main__':unittest.main()
