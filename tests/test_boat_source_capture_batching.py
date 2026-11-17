"""Already-fetched invented responses, fixture key and memory Git only."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V
from race_ai import saved_view_feed as F
from scripts import boat_private_original_vault as cli
from tests.test_boat_private_original_vault import HEAD, KEY, NOW
from tests.test_boat_private_original_vault_private_pairs import MemoryRemote, MemoryVault


def capture(folder, number, **changes):
    raw = ('invented original HTTP response version ' + str(number)).encode()
    receipt = dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
        captured_at=(NOW-timedelta(hours=1)+timedelta(microseconds=number)).isoformat(),
        source_sha256=sha256(raw).hexdigest(), http_status=200)
    receipt.update(changes)
    F.retain_capture(folder, raw, receipt)
    return raw, V._wire(receipt)+b'\n'


class CaptureBatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.folder = self.root/'captures'
        self.repo = self.root/'repository'; self.repo.mkdir(mode=0o700)
        self.remote = MemoryRemote(); self.writer = MemoryVault(self.remote, self.repo)
        self.reader = MemoryVault(self.remote, self.root/'reader')
        self.env = dict(RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),
                        GITHUB_RUN_ID='4242', GITHUB_SHA=HEAD)

    def command(self, args):
        output = io.StringIO()
        with patch.dict(os.environ, self.env), patch.object(cli, '_environment', return_value=self.repo), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no source GET')), \
             redirect_stdout(output):
            code = cli.main([*args, '--repo-root', str(self.repo)],
                transport=self.writer, readback_transport=self.reader, now=NOW)
        return code, json.loads(output.getvalue())

    def retain(self, **kwargs):
        return self.command(['retain-captures', '--capture-dir', str(self.folder),
                             '--expected-parent', 'current', *kwargs.get('extra', [])])

    def restore_report(self, report, *, target=None):
        path = self.root/'report-input.json'
        path.write_bytes(V._wire(report)); path.chmod(0o600)
        target = target or self.root/'restored'
        return self.command(['restore-captures', '--locator', str(path), '--output-dir', str(target)])

    def test_241_valid_originals_round_trip_in_two_bounded_bundles(self):
        originals = [capture(self.folder, n) for n in range(241)]
        code, report = self.retain()
        self.assertEqual(code, 0, 'All 241 originals must survive; 240 is a per-bundle bound.')
        self.assertEqual(report['retained_captures'], 241)
        self.assertIs(report['complete'], True)
        self.assertEqual(len(report['locators']), 2)
        restored = []
        for locator in report['locators']:
            pairs = V.restore_capture_bundle(locator, self.repo, key=KEY, transport=self.reader)['captures']
            self.assertLessEqual(len(pairs), 240); restored.extend(pairs)
        self.assertCountEqual(restored, originals)
        report_file = self.root/'receipt.json'; report_file.write_bytes(V._wire(report)); report_file.chmod(0o600)
        target = self.root/'restored'
        code, proof = self.command(['restore-captures', '--locator', str(report_file), '--output-dir', str(target)])
        self.assertEqual(code, 0)
        self.assertEqual(proof['captures'], 241)
        actual = [(p.read_bytes(), p.with_suffix('.json').read_bytes()) for p in target.rglob('capture-*.raw')]
        self.assertCountEqual(actual, originals)
        self.assertTrue(all(not p.stat().st_mode & 0o077 for p in target.rglob('*')))

    def test_single_bundle_keeps_legacy_receipt_file_order_report_and_flat_restore(self):
        pairs = [capture(self.folder, n) for n in range(4)]
        code, report = self.retain(); self.assertEqual(code, 0)
        self.assertEqual(set(report), {'status','source_commit','retained_captures','locator','plaintext_published'})
        saved = V.restore_capture_bundle(report['locator'], self.repo, key=KEY, transport=self.reader)
        self.assertEqual(saved['captures'], cli._capture_files(self.folder, self.repo))
        code, proof = self.restore_report(report)
        self.assertEqual(code, 0); self.assertEqual(proof['captures'], 4)
        self.assertEqual(len(list((self.root/'restored').glob('capture-*.raw'))), 4)
        self.assertCountEqual(saved['captures'], pairs)
        with self.assertRaisesRegex(ValueError, 'CAPTURE_COUNT_INVALID'):
            V._capture_record([pairs[0]]*241, run_id=4242, head_sha=HEAD, now=NOW)

    def test_chronological_append_reuses_full_legacy_group_and_never_rewrites_old_tail(self):
        for n in range(240):capture(self.folder, n)
        first_code, first = self.retain(); self.assertEqual(first_code, 0)
        capture(self.folder, 240)
        code, second = self.retain(); self.assertEqual(code, 0)
        self.assertEqual(second['locators'][0], first['locator'])
        prefix, old_tail = second['locators']
        capture(self.folder, 241)
        code, third = self.retain(); self.assertEqual(code, 0)
        self.assertEqual({k:v for k,v in third['locators'][0].items() if k!='source_commit'},
                         {k:v for k,v in prefix.items() if k!='source_commit'})
        self.assertNotEqual(third['locators'][1]['entry_sha256'], old_tail['entry_sha256'])
        self.assertEqual(len(V.restore_capture_bundle(old_tail, self.repo, key=KEY, transport=self.reader)['captures']), 1)
        before = deepcopy(self.remote.objects); code, same = self.retain()
        self.assertEqual(code, 0); self.assertEqual(same['bundle_inventory_sha256'], third['bundle_inventory_sha256'])
        self.assertEqual(same['source_commit'], third['source_commit']); self.assertEqual(self.remote.objects, before)

    def test_invalid_last_url_hash_clock_or_offset_duplicate_refuses_before_any_git_write(self):
        for n in range(240):capture(self.folder, n)
        before = deepcopy(self.remote.objects); head = self.remote.current
        defects = ({'source_url':'https://example.invalid/private'}, {'captured_at':(NOW+timedelta(seconds=1)).isoformat()},
                   {'captured_at':(NOW-timedelta(hours=1)).isoformat().replace('+00:00','Z')}, {})
        for index, changes in enumerate(defects):
            with self.subTest(defect=index):
                raw, metadata = capture(self.folder, 240, **changes)
                if index == 3:
                    path = self.folder/(sha256(raw).hexdigest()+'.html'); path.write_bytes(raw+b'changed')
                with patch.object(self.writer, 'commit', side_effect=AssertionError('Git write before full preflight')) as write:
                    code, _ = self.retain()
                self.assertEqual(code, 2); write.assert_not_called()
                self.assertEqual(self.remote.current, head); self.assertEqual(self.remote.objects, before)
                (self.folder/(V._sha(V._wire(V._json(metadata)))+'.json')).unlink()
                (self.folder/(sha256(raw).hexdigest()+'.html')).unlink()

    def test_materialization_rechecks_all_file_identity_before_that_group_is_published(self):
        from race_ai import boat_source_capture_files as C
        originals = [capture(self.folder, n) for n in range(241)]
        original = C.CaptureInventory.materialize
        def mutate(inventory, group):
            body = self.folder/(V._sha(originals[0][0])+'.html')
            body.write_bytes(originals[0][0][::-1])
            return original(inventory, group)
        head = self.remote.current
        with patch.object(C.CaptureInventory, 'materialize', new=mutate):code, report = self.retain()
        self.assertEqual(code, 2); self.assertEqual(self.remote.current, head)
        self.assertIs(report['complete'], False); self.assertEqual(report['retained_captures'], 0)

    def test_late_mutation_and_partial_publication_return_hold_with_verified_prefix(self):
        pairs = [capture(self.folder, n) for n in range(241)]
        real = V.retain_capture_bundle; calls = []
        def retain(*args, **kwargs):
            locator = real(*args, **kwargs); calls.append(locator)
            if len(calls) == 1:(self.folder/(V._sha(pairs[-1][0])+'.html')).write_bytes(b'late tamper')
            return locator
        with patch.object(V, 'retain_capture_bundle', side_effect=retain):code, report = self.retain()
        self.assertEqual(code, 2); self.assertEqual(report['status'], 'SOURCE_CAPTURES_RETENTION_HOLD')
        self.assertIs(report['complete'], False); self.assertEqual(report['retained_captures'], 240)
        self.assertEqual(report['locators'], calls)
        self.assertEqual(len(V.restore_capture_bundle(calls[0], self.repo, key=KEY, transport=self.reader)['captures']), 240)
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertFalse((self.root/'restored').exists())

    def test_git_failure_acknowledges_only_verified_prefix_and_sanitizes_exception(self):
        for n in range(241):capture(self.folder, n)
        real = self.writer.push; pushes = []
        private = 'fake-private-key https://example.invalid/private-body'
        def push(commit, parent):
            pushes.append(commit)
            if len(pushes) == 2:raise RuntimeError(private)
            return real(commit, parent)
        output = self.root/'partial.json'
        with patch.object(self.writer, 'push', side_effect=push):
            code, report = self.retain(extra=['--output', str(output)])
        self.assertEqual(code, 2); self.assertEqual(report['retained_captures'], 240)
        self.assertEqual(report['reason'], 'VAULT_OPERATION_FAILED'); self.assertIs(report['complete'], False)
        self.assertEqual(len(report['locators']), 1); self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(private, json.dumps(report)); self.assertEqual(self.remote.current, report['source_commit'])

    def test_failed_readback_never_acknowledges_that_commit_and_retry_preserves_it(self):
        for n in range(241):capture(self.folder,n)
        real = V._verify_restored_records; calls = []
        def verify(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValueError('VAULT_REMOTE_ORIGINAL_READBACK_MISMATCH')
            return real(*args,**kwargs)
        with patch.object(V,'_verify_restored_records',side_effect=verify):code, report = self.retain()
        self.assertEqual(code,2); self.assertIs(report['complete'],False)
        self.assertEqual(report['retained_captures'],240)
        self.assertNotEqual(report['source_commit'],self.remote.current)
        before = deepcopy(self.remote.objects)
        code, recovered = self.retain(); self.assertEqual(code,0)
        self.assertIs(recovered['complete'],True); self.assertEqual(recovered['retained_captures'],241)
        self.assertEqual(self.remote.objects,before)

    def test_final_append_after_genuine_readback_holds_and_keeps_all_verified_locators(self):
        originals = [capture(self.folder,n) for n in range(241)]
        real = V.retain_capture_bundle; locators = []
        def retain(*args,**kwargs):
            locator = real(*args,**kwargs); locators.append(locator)
            if len(locators)==2:capture(self.folder,241)
            return locator
        with patch.object(V,'retain_capture_bundle',side_effect=retain):code, report = self.retain()
        self.assertEqual(code,2); self.assertIs(report['complete'],False)
        self.assertEqual(report['status'],'SOURCE_CAPTURES_RETENTION_HOLD')
        self.assertEqual(report['reason'],'VAULT_PRIVATE_INPUT_CHANGED')
        self.assertEqual(report['retained_captures'],241); self.assertEqual(report['locators'],locators)
        self.assertEqual(len(list(self.folder.glob('*.json'))),242)
        restored = [pair for locator in locators for pair in
            V.restore_capture_bundle(locator,self.repo,key=KEY,transport=self.reader)['captures']]
        self.assertCountEqual(restored,originals)

    def test_restore_rejects_count_boolean_hash_locator_and_incomplete_report_tampering(self):
        for n in range(241):capture(self.folder, n)
        code, original = self.retain(); self.assertEqual(code, 0)
        changes = [dict(retained_captures=240), dict(retained_captures=True), dict(complete=False),
                   dict(bundle_capture_counts=[True,240]), dict(bundle_inventory_sha256=['a'*64,'b'*64]),
                   dict(source_commit='b'*40)]
        for changeset in changes:
            report = dict(original, **changeset)
            with self.subTest(field=tuple(changeset)):
                code, _ = self.restore_report(report); self.assertEqual(code, 2)
                self.assertFalse((self.root/'restored').exists())
        report = deepcopy(original); report['locators'][-1]['entry_sha256'] = 'e'*64
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertFalse((self.root/'restored').exists())

    def test_restore_bad_last_cipher_wrong_key_and_existing_output_leave_no_partial_target(self):
        for n in range(241):capture(self.folder, n)
        code, report = self.retain(); self.assertEqual(code, 0)
        locator = report['locators'][-1]; tree = self.remote.objects[locator['source_commit']]
        batch = V._json(tree[locator['batch_path']]); chunk = batch['state']['entries'][0]['chunks'][0]['path']
        saved = tree[chunk]; tree[chunk] = saved[:-1]+bytes([saved[-1]^1])
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertFalse((self.root/'restored').exists())
        self.assertFalse(list(self.root.glob('.boat-capture-restore-*')))
        tree[chunk] = saved
        self.env['RACE_AI_STATE_KEY'] = base64.b64encode(bytes(reversed(KEY))).decode()
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertFalse((self.root/'restored').exists())
        self.env['RACE_AI_STATE_KEY'] = base64.b64encode(KEY).decode()
        target = self.root/'restored'; target.mkdir(mode=0o700); marker = target/'keep'; marker.write_bytes(b'keep original')
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertEqual(marker.read_bytes(), b'keep original')

    def test_restore_rejects_genuine_cross_bundle_duplicate_and_final_target_race(self):
        from race_ai import boat_source_capture_files as C
        first = capture(self.folder, 1)
        second = capture(self.folder, 2, captured_at=V._json(first[1])['captured_at'].replace('+00:00','Z'))
        a = V.retain_capture_bundle([first], self.repo, run_id=4242, head_sha=HEAD,
            expected_parent=self.remote.current, key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        b = V.retain_capture_bundle([second], self.repo, run_id=4242, head_sha=HEAD,
            expected_parent=a['source_commit'], key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        report = cli._capture_set_report([a,b],[1,1],[C.bundle_inventory([first]),C.bundle_inventory([second])],2,complete=True)
        code, _ = self.restore_report(report); self.assertEqual(code, 2)
        self.assertFalse((self.root/'restored').exists())
        # A new target created just before exposure must never be replaced.
        (self.folder/(V._sha(V._wire(V._json(second[1])))+'.json')).unlink()
        code, small = self.retain(); self.assertEqual(code, 0)
        expose = cli._expose_private_directory
        def race(stage, folder, repo):
            folder.mkdir(mode=0o700); (folder/'keep').write_bytes(b'other writer')
            return expose(stage, folder, repo)
        with patch.object(cli, '_expose_private_directory', side_effect=race):code, _ = self.restore_report(small)
        self.assertEqual(code, 2); self.assertEqual((self.root/'restored/keep').read_bytes(), b'other writer')


class CaptureFeedTests(unittest.TestCase):
    setUp = CaptureBatchingTests.setUp

    def view(self):
        from race_ai.boat_pdca_projection import project_pdca
        from race_ai.boat_pdca_state import PdcaState
        from tests.test_boat_pdca_github_handoff import invented_research_state
        path, pair = invented_research_state(self.root)
        state = PdcaState(path)
        try:return project_pdca(state), pair
        finally:state.close()

    def run_feed(self, view, items=()):
        from scripts import boat_saved_view_feed as feed
        from scripts import boat_original_maintenance as maintenance
        from types import SimpleNamespace
        config = self.repo/'audit/state'; config.mkdir(parents=True, exist_ok=True)
        raw = b'invented bootstrap fixture'
        (config/'boat-saved-view-input.json').write_bytes(V._wire(dict(
            schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(raw).decode(),
            bootstrap_sha256=V._sha(raw), catchup_artifact_id=1, catchup_sha256='a'*64)))
        # Production chooses this fixed runner-private capture folder.
        self.folder.rename(self.root/'boat-saved-view-captures')
        output = io.StringIO(); actual_update = F.update_view
        with patch.object(feed,'ROOT',self.repo), patch.object(feed,'git_auth'), \
             patch.object(F,'open_bootstrap',return_value={}), \
             patch.object(F,'FeedRepository',return_value=SimpleNamespace(_saved_history_context=None)), \
             patch.object(F,'current_view',return_value=('b'*40,'c'*64,12,view)), \
             patch.object(feed,'intake_saved_models',side_effect=lambda value,**_:deepcopy(value)), \
             patch.object(feed,'observations',return_value=list(items)), \
             patch.object(F,'load_captures',side_effect=AssertionError('unbounded raw list forbidden')), \
             patch.object(F,'update_view',wraps=actual_update) as update, \
             patch.object(F,'publish_view',return_value={'status':'ENCRYPTED_VIEW_PUBLISHED'}) as publish, \
             patch.object(maintenance,'protect_new_forecast_originals',return_value={'complete':True}) as protect, \
             patch.object(feed,'datetime') as clock, \
             patch.dict(os.environ,dict(RUNNER_TEMP=str(self.root),RACE_AI_ORIGINAL_VAULT_ENABLED='true')), \
             patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('source GET forbidden')), \
             redirect_stdout(output):
            clock.now.return_value = NOW
            code = feed.main(['--result-artifact','1'])
        return code, update, publish, protect, output.getvalue()

    def test_feed_241_single_stream_is_identical_to_one_legacy_replay_with_all_revisions(self):
        view, _ = self.view(); before = deepcopy(view); rid = view['records'][0]['race_id']
        url = f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}'
        pairs = [capture(self.folder,n,source_url=url) for n in range(241)]
        expected = F.update_view(view,[],captures=[(raw,V._json(meta)) for raw,meta in sorted(pairs,
            key=lambda pair:V._sha(V._wire(V._json(pair[1]))))],synced_at=NOW.isoformat())
        code, update, publish, protect, _ = self.run_feed(view)
        self.assertEqual(code, 0); update.assert_called_once(); publish.assert_called_once(); protect.assert_called_once()
        self.assertNotIsInstance(update.call_args.kwargs['captures'], (list,tuple))
        self.assertEqual(publish.call_args.args[2],expected); self.assertEqual(view,before)
        self.assertEqual(len(expected['records'][0]['result_observations']),
                         len(view['records'][0]['result_observations'])+241)

    def test_late_capture_conflict_keeps_previous_feed_and_prevents_all_publication(self):
        from tests.test_boat_pdca_state import result
        view, pair = self.view(); before = deepcopy(view); rid = view['records'][0]['race_id']
        url = f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}'
        for n in range(241):_, last = capture(self.folder,n,source_url=url)
        conflict = result(pair); conflict.update(captured_at=V._json(last)['captured_at'], source_sha256='e'*64)
        code, update, publish, protect, output = self.run_feed(view,[conflict])
        self.assertEqual(code,2); update.assert_called_once(); publish.assert_not_called(); protect.assert_not_called()
        self.assertEqual(view,before); self.assertIn('ENCRYPTED_VIEW_REJECTED',output)
        self.assertIn('FEED_OPERATION_FAILED',output)  # Existing fixed public whitelist.

    def test_invalid_241st_irrelevant_capture_still_preflights_before_feed_or_protection(self):
        view, _ = self.view(); before = deepcopy(view)
        for n in range(240):capture(self.folder,n)
        capture(self.folder,240,source_url='https://example.invalid/unapproved')
        code, update, publish, protect, _ = self.run_feed(view)
        self.assertEqual(code,2); update.assert_not_called(); publish.assert_not_called(); protect.assert_not_called()
        self.assertEqual(view,before)

    def test_feed_physical_view_bound_stops_projection_before_unbounded_accumulation(self):
        view, _ = self.view(); rid = view['records'][0]['race_id']
        url = f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}'
        for n in range(241):capture(self.folder,n,source_url=url)
        with patch.object(F,'MAX_VIEW',1024):code, update, publish, protect, output = self.run_feed(view)
        self.assertEqual(code,2); update.assert_called_once(); publish.assert_not_called(); protect.assert_not_called()
        self.assertIn('FEED_CAPTURE_OBSERVATIONS_BOUND',output)


if __name__ == '__main__':
    unittest.main()
