"""Saved result recovery uses invented API responses and real archive readers."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import io
import json
import os
import unittest
from unittest.mock import patch

from race_ai import saved_view_feed as F
from race_ai.private_cycle_projection import project_state
from tests.test_frozen_day_cycle import observation
from tests.test_private_cycle_projection import saved_state, seal
from tests.test_private_original_archive_readers import encrypted, packed, KEY, HEAD

try:
    R = importlib.import_module('race_ai.boat_saved_result_recovery')
except ModuleNotFoundError:
    R = None

DAY = '2030-04-01'
CLOCK = datetime(2030, 4, 1, 8, tzinfo=timezone.utc)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def run_response(ident=42):
    return dict(id=ident, workflow_id=405276784,
        head_branch='feat/four-sport-forecast-audit-view-20261022', event='push', head_sha=HEAD,
        status='completed', created_at='2030-04-01T00:00:00Z', updated_at='2030-04-01T04:00:00Z',
        repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))


class Responses:
    def __init__(self, artifacts=(), *, archived=False):
        self.calls = []; self.bodies = {}; self.restored = set(); self.archived = archived
        rows = {}
        for raw, meta in artifacts:
            ident = meta['id']; run = meta['workflow_run']['id']
            rows.setdefault(run, []).append(deepcopy(meta))
            self.bodies[f'actions/artifacts/{ident}'] = wire(meta)
            self.bodies[f'actions/artifacts/{ident}/zip'] = raw
        if not rows: rows[42] = []
        for run, listing in rows.items():
            self.bodies[f'actions/runs/{run}'] = wire(run_response(run))
            self.set_listing(run, listing)

    def set_listing(self, run, rows):
        for page in range(1, max(1, (len(rows)+99)//100)+1):
            suffix = '' if page == 1 else f'&page={page}'
            self.bodies[f'actions/runs/{run}/artifacts?per_page=100{suffix}'] = wire(
                dict(total_count=len(rows), artifacts=rows[(page-1)*100:page*100]))

    def __call__(self, path):
        self.calls.append(path)
        raw = self.bodies[path]
        if isinstance(raw, Exception): raise raw
        if path.startswith('actions/artifacts/') and not path.endswith('/zip'):
            self.restored.add(int(path.rsplit('/', 1)[1]))
        return raw

    def archived_artifact_pages(self, run):
        raise AssertionError('availability inventory must not hydrate unselected ZIPs')

    def is_archived(self, ident):
        return self.archived and ident in self.restored


class SavedResultRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state, _ = saved_state()
        second = deepcopy(state['rows'])
        for row in second: row['race_id'] = '20300401-01-02'
        state['rows'].extend(second); seal(state)
        cls.view = project_state(state, dataset_status='SYNTHETIC_ONLY')
        cls.observations = [observation(state['rows'][0]), observation(second[0])]
        cls.observations[1]['source_url'] = cls.observations[1]['source_url'].replace('rno=1', 'rno=2')
        # A V4 display can already contain another day. Its originals and result
        # journal must survive recovery of the explicitly supplied newer run.
        old = deepcopy(cls.view['records'][0])
        old.update(race_id='20300331-01-01', event_date_jst='2030-03-31')
        cls.view['records'].insert(0, old)

    def setUp(self):
        self.assertIsNotNone(R, 'saved result archive recovery is missing')

    def artifact(self, ident=701, round_no=1, *, items=None, day=DAY, run=42, cipher=False):
        items = deepcopy(self.observations if items is None else items)
        raw = packed({'official-result-observations.json': wire(items),
                      'status.json': wire(dict(day_jst=day))})
        suffix = '' if round_no == 1 else f'-cycle-{round_no:02d}'
        meta = dict(id=ident, name=f'race-existing-cycle-{run}{suffix}', expired=False,
            size_in_bytes=len(raw), digest='sha256:'+sha256(raw).hexdigest(),
            created_at='2030-04-01T03:00:00Z', expires_at='2030-04-08T03:00:00Z',
            workflow_run=dict(id=run, repository_id=1416489937,
                              head_repository_id=1416489937, head_sha=HEAD))
        return encrypted(raw, meta, 'RESULT') if cipher else (raw, meta)

    def recover(self, get, *, view=None, **kwargs):
        return R.recover_saved_results(deepcopy(self.view) if view is None else view, get,
            run_ids=kwargs.pop('run_ids', [42]), key=kwargs.pop('key', KEY),
            now=kwargs.pop('now', CLOCK), **kwargs)

    def test_approved_production_dispatch_recovers_results_without_changing_forecasts(self):
        get = Responses([self.artifact(cipher=True)])
        info = dict(run_response(), head_branch='production/boat-p0-p1-20261111',
                    event='workflow_dispatch')
        get.bodies['actions/runs/42'] = wire(info)
        before = deepcopy(self.view)
        result, counts = self.recover(get, view=before)
        self.assertEqual(counts['appended_observations'], 2)
        self.assertEqual(counts['archives_verified'], 1)
        self.assertEqual(counts['source_requests'], 0)
        self.assertEqual(F.forecast_inventory(result), F.forecast_inventory(before))
        self.assertEqual(F.originals_sha(result), F.originals_sha(before))
        self.assertTrue(all(row['result']['status'] == 'final' for row in result['records'][1:]))

    def test_production_dispatch_without_result_archive_preserves_the_exact_view(self):
        get = Responses()
        info = dict(run_response(), head_branch='production/boat-p0-p1-20261111',
                    event='workflow_dispatch')
        get.bodies['actions/runs/42'] = wire(info)
        before = deepcopy(self.view); original = wire(before)
        result, counts = self.recover(get, view=before)
        self.assertIs(result, before)
        self.assertEqual(wire(result), original)
        self.assertEqual(counts['runs_scanned'], 1)
        self.assertEqual(counts['archives_verified'], 0)
        self.assertEqual(counts['appended_observations'], 0)
        self.assertEqual(counts['source_requests'], 0)

    def test_unauthorized_owner_identity_stops_before_artifact_access(self):
        approved = dict(run_response(), head_branch='production/boat-p0-p1-20261111',
                        event='workflow_dispatch')
        mutations = [dict(event=event) for event in ('push', 'pull_request', None)]
        mutations += [dict(head_branch='main'), dict(workflow_id=1),
                      dict(workflow_id=float(405276784))]
        for field in ('repository', 'head_repository'):
            mutations += [{field: dict(id=1, full_name='haji84/RACE-AI')},
                          {field: dict(id=1416489937, full_name='someone/RACE-AI')}]
        mutations += [dict(head_branch='feat/four-sport-forecast-audit-view-20261022', event=event)
                      for event in ('pull_request', None)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                get = Responses([self.artifact()])
                get.bodies['actions/runs/42'] = wire(dict(approved, **mutation))
                with self.assertRaisesRegex(ValueError, 'SAVED_RESULT_RECOVERY_WORKFLOW_IDENTITY_INVALID'):
                    self.recover(get)
                self.assertEqual(get.calls, ['actions/runs/42'])

    def test_legacy_source_events_remain_readable(self):
        for event in ('push', 'workflow_dispatch'):
            with self.subTest(event=event):
                get = Responses([self.artifact()])
                get.bodies['actions/runs/42'] = wire(dict(run_response(), event=event))
                _, counts = self.recover(get)
                self.assertEqual(counts['appended_observations'], 2)

    def test_production_result_artifact_must_match_the_source_sha(self):
        raw, meta = self.artifact(); get = Responses([(raw, meta)])
        info = dict(run_response(), head_branch='production/boat-p0-p1-20261111',
                    event='workflow_dispatch')
        get.bodies['actions/runs/42'] = wire(info)
        meta['workflow_run']['head_sha'] = 'b'*40
        get.bodies['actions/artifacts/701'] = wire(meta)
        with self.assertRaisesRegex(ValueError, 'SAVED_RESULT_RECOVERY_ARTIFACT_RUN_HEAD_INVALID'):
            self.recover(get)
        self.assertNotIn('actions/artifacts/701/zip', get.calls)

    def test_two_saved_results_merge_newer_day_without_models_sources_or_original_changes(self):
        old = deepcopy(self.view); get = Responses([self.artifact()]); stdout = io.StringIO()
        revision = dict(result_revision_sha256='c'*64, observed_at='2030-04-01T02:00:00Z',
                        native_fixture_revision={'original_bytes_sha256': 'd'*64})
        old['records'][1]['result_revisions'] = [revision]
        before = deepcopy(old)
        with patch('urllib.request.urlopen', side_effect=AssertionError('source HTTP')), \
             patch('race_ai.frozen_day_cycle.settle', side_effect=AssertionError('formal settlement')), \
             redirect_stdout(stdout):
            new, counts = self.recover(get, view=old)
        self.assertEqual(old, before); self.assertEqual(new['records'][0], old['records'][0])
        self.assertEqual(F.forecast_inventory(new), F.forecast_inventory(old))
        self.assertEqual(F.originals_sha(new), F.originals_sha(old))
        self.assertTrue(all(row['result']['status'] == 'final' for row in new['records'][1:]))
        self.assertEqual(counts['appended_observations'], 2)
        self.assertEqual(counts['updated_races'], 2); self.assertEqual(counts['archives_verified'], 1)
        self.assertEqual(counts['source_requests'], 0); self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(new['records'][1]['result_revisions'], [revision])
        self.assertEqual(new['records'][2]['result_revisions'], [])
        self.assertNotIn('20300401', wire(counts).decode())

    def test_only_latest_valid_round_is_read_even_when_earlier_archive_was_created_later(self):
        earlier = self.artifact(701)
        changed = deepcopy(self.observations)
        changed[0]['source_sha256'] = 'e'*64
        changed[0]['captured_at'] = '2030-04-01T02:20:00Z'
        changed[0]['data']['payouts'][0]['payout_per_100_yen'] = 2500
        later = self.artifact(702, 18, items=[*self.observations, changed[0]])
        earlier[1]['created_at'] = '2030-04-01T03:30:00Z'
        get = Responses([later, earlier]); new, counts = self.recover(get)
        self.assertEqual(new['records'][1]['result']['payout_yen_per_100'], 2500)
        self.assertEqual(len(new['records'][1]['result_observations']), 2)
        self.assertEqual(counts['matched_result_archives'], 2)
        self.assertIn('actions/artifacts/702/zip', get.calls)
        self.assertNotIn('actions/artifacts/701', get.calls)

    def test_duplicate_replay_does_not_advance_sync_or_change_original_inventory(self):
        artifact = self.artifact(); first, _ = self.recover(Responses([artifact]))
        before = wire(first)
        again, counts = self.recover(Responses([artifact]), view=first,
            now=datetime(2030, 4, 1, 9, tzinfo=timezone.utc))
        self.assertIs(again, first); self.assertEqual(wire(again), before)
        self.assertEqual(counts['appended_observations'], 0)
        self.assertEqual(counts['duplicate_observations'], 2)
        self.assertEqual(F.forecast_inventory(first), F.forecast_inventory(again))

    def test_newer_pending_is_retained_and_empty_latest_archive_waits_without_older_fallback(self):
        pending = deepcopy(self.observations[0])
        pending.update(status='PENDING', data=None, captured_at='2030-04-01T02:20:00Z')
        artifact = self.artifact(items=[self.observations[0], pending])
        new, _ = self.recover(Responses([artifact]))
        self.assertEqual(new['records'][1]['result']['status'], 'pending')
        self.assertEqual(new['records'][1]['result']['winning_combinations'], [])
        get = Responses([self.artifact(), self.artifact(702, 18, items=[])])
        unchanged, counts = self.recover(get, view=new)
        self.assertIs(unchanged, new)
        self.assertEqual(counts['status'], 'UNCHANGED')
        self.assertEqual(counts['empty_verified_journals'], 1)
        self.assertEqual(counts['appended_observations'], 0)
        self.assertNotIn('actions/artifacts/701', get.calls)

    def test_verified_preclose_empty_result_preserves_new_physical_p1_and_known_results(self):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        from race_ai.frozen_day_cycle import read_p1
        from tests.test_observed_p1_connection import inputs, archive, AT
        base, extra, _ = inputs(); base['race_id'] = extra['race_id'] = '20300401-01-03'
        native = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
                      paired_forecasts=[build_pair(base, AT)],
                      additional_official_feature_shadows=[build_live_feature_shadow(base, extra, AT)])
        raw, receipt = archive(native)
        _, rows = read_p1(raw, receipt)
        state, _ = saved_state(); state.update(rows=rows, receipts=[receipt]); seal(state)
        p1 = project_state(state, dataset_status='SYNTHETIC_ONLY')
        known, _ = self.recover(Responses([self.artifact()]))
        known['records'].extend(p1['records'])
        before = wire(known); inventory = F.forecast_inventory(known)
        empty = self.artifact(702, 18, items=[])
        empty[1]['created_at'] = '2030-04-01T01:42:00Z'
        self.assertLess(datetime.fromisoformat(empty[1]['created_at'].replace('Z', '+00:00')),
                        datetime.fromisoformat(rows[0]['cutoff_at']))
        get = Responses([self.artifact(), empty])
        result, counts = self.recover(get, view=known)
        self.assertIs(result, known); self.assertEqual(wire(result), before)
        self.assertEqual(F.forecast_inventory(result), inventory)
        self.assertEqual(result['records'][-1]['prediction']['stage'], 'P1')
        self.assertEqual(result['records'][-1]['prediction']['artifact_id'], receipt['id'])
        self.assertEqual(result['records'][1]['result']['status'], 'final')
        self.assertIsNone(result['records'][-1]['result'])
        self.assertEqual(counts['status'], 'UNCHANGED')
        self.assertEqual(counts['archives_verified'], 1)
        self.assertEqual(counts['empty_verified_journals'], 1)
        self.assertEqual(counts['appended_observations'], 0)
        self.assertNotIn('actions/artifacts/701', get.calls)

    def test_empty_latest_journal_does_not_discard_other_runs_results_in_either_order(self):
        for empty_run, populated_run in ((42, 43), (43, 42)):
            with self.subTest(empty_run=empty_run):
                empty = self.artifact(702, 18, run=empty_run, items=[])
                older = self.artifact(703, run=empty_run)
                populated = self.artifact(704, run=populated_run)
                get = Responses([empty, older, populated])
                result, counts = self.recover(get, run_ids=[43, 42])
                self.assertEqual(counts['archives_verified'], 2)
                self.assertEqual(counts['empty_verified_journals'], 1)
                self.assertEqual(counts['appended_observations'], 2)
                self.assertEqual(counts['status'], 'UPDATED')
                self.assertTrue(all(row['result']['status'] == 'final' for row in result['records'][1:]))
                self.assertNotIn('actions/artifacts/703', get.calls)

    def test_missing_or_malformed_journal_still_holds_without_older_fallback(self):
        for members in ({'status.json': wire(dict(day_jst=DAY))},
                        {'official-result-observations.json': b'null', 'status.json': wire(dict(day_jst=DAY))},
                        {'official-result-observations.json': b'not JSON', 'status.json': wire(dict(day_jst=DAY))}):
            with self.subTest(members=list(members)):
                _, meta = self.artifact(702, 18, items=[])
                raw = packed(members)
                meta.update(size_in_bytes=len(raw), digest='sha256:'+sha256(raw).hexdigest())
                get = Responses([self.artifact(), (raw, meta)])
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_PAYLOAD'): self.recover(get)
                self.assertNotIn('actions/artifacts/701', get.calls)

    def test_actual_history_chunk_boundary_defers_atomically_and_preserves_passed_in_view(self):
        from race_ai import saved_view_history as H
        for index, margin in ((1, 128), (0, 8)):
            with self.subTest(padded_row=index):
                base = deepcopy(self.view); row = base['records'][index]
                row['review_padding'] = ''
                head = {key: value for key, value in base.items() if key != 'records'}
                head.update(event_date_jst=row['event_date_jst'], forecast_base_sha256=F.forecast_anchor(base))
                row['review_padding'] = 'x'*(H.MAX_CHUNK_PLAIN-margin-len(wire(dict(head, records=[])))-len(wire(row)))
                H.encrypt_day_chunks(base, KEY, view_id='a'*64)
                candidate = F.update_view(base, self.observations, synced_at=CLOCK.isoformat())
                with self.assertRaisesRegex(ValueError, 'HISTORY_RACE_CHUNK_BOUND'):
                    H.encrypt_day_chunks(candidate, KEY, view_id='a'*64)
                before = wire(base); inventory = F.forecast_inventory(base)
                result, counts = self.recover(Responses([self.artifact()]), view=base)
                self.assertTrue(result is base, 'bounded recovery must return the input object')
                self.assertEqual(sha256(wire(result)).hexdigest(), sha256(before).hexdigest())
                self.assertEqual(F.forecast_inventory(result), inventory)
                self.assertEqual(counts['status'], 'DEFERRED')
                self.assertEqual(counts['deferred_observations'], 2)
                self.assertEqual(counts['appended_observations'], 0)
                self.assertEqual(counts['updated_races'], 0)
                self.assertEqual(counts['archives_verified'], 1)
                H.encrypt_day_chunks(result, KEY, view_id='a'*64)

    def test_output_view_bound_defers_results_and_preserves_known_results_and_originals(self):
        base, _ = self.recover(Responses([self.artifact()]))
        newer = deepcopy(self.observations[0])
        newer.update(captured_at='2030-04-01T02:20:00Z', source_sha256='e'*64)
        limit = len(wire(base)) + 1
        before = wire(base)
        with patch.object(R, 'MAX_VIEW_BYTES', limit):
            result, counts = self.recover(Responses([self.artifact(items=[newer])]), view=base)
        self.assertIs(result, base); self.assertEqual(wire(result), before)
        self.assertEqual(counts['status'], 'DEFERRED')
        self.assertEqual(counts['deferred_observations'], 1)
        self.assertEqual(counts['appended_observations'], 0)
        self.assertEqual(result['records'][1]['result']['status'], 'final')

    def test_expired_listings_use_exact_archived_metadata_only_after_restore(self):
        artifact = self.artifact(cipher=True); get = Responses([artifact], archived=True)
        listed = deepcopy(artifact[1]); listed['expired'] = True
        get.set_listing(42, [listed])
        with patch.dict(os.environ, {}, clear=True):
            new, counts = self.recover(get, now=datetime(2031, 4, 1, tzinfo=timezone.utc))
        self.assertEqual(counts['archived_artifacts'], 1)
        self.assertEqual(new['records'][1]['result']['status'], 'final')
        self.assertIs(json.loads(get.bodies['actions/artifacts/701'])['expired'], False)
        self.assertIs(json.loads(get.bodies['actions/runs/42/artifacts?per_page=100'])['artifacts'][0]['expired'], True)
        class DynamicProxy:
            def __init__(self, target): self.target = target
            def __call__(self, path): return self.target(path)
            def __getattr__(self, name): return lambda *_: True
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            self.recover(DynamicProxy(Responses([artifact])), now=datetime(2031, 4, 1, tzinfo=timezone.utc))

    def test_size_and_total_budget_preflight_precedes_metadata_hydration(self):
        for sizes in ([32*1024*1024+1], [23*1024*1024]*3):
            with self.subTest(sizes=sizes):
                artifacts = [self.artifact(701+i, run=42+i) for i in range(len(sizes))]
                for artifact, size in zip(artifacts, sizes): artifact[1]['size_in_bytes'] = size
                get = Responses(artifacts)
                with self.assertRaisesRegex(ValueError, 'BOUND'):
                    self.recover(get, run_ids=list(range(42, 42+len(sizes))))
                self.assertFalse(any(path.startswith('actions/artifacts/') for path in get.calls))

    def test_complete_pages_select_latest_on_second_page_and_never_use_availability_hook(self):
        earlier, latest = self.artifact(), self.artifact(702, 24)
        rows = [deepcopy(earlier[1])] + [dict(id=800+i, name='unrelated') for i in range(99)] + [deepcopy(latest[1])]
        get = Responses([earlier, latest]); get.set_listing(42, rows)
        new, counts = self.recover(get)
        self.assertEqual(counts['listed_artifacts'], 101)
        self.assertEqual(counts['appended_observations'], 2)
        self.assertIn('actions/runs/42/artifacts?per_page=100&page=2', get.calls)
        self.assertNotIn('actions/artifacts/701', get.calls)
        del get.bodies['actions/runs/42/artifacts?per_page=100&page=2']
        with self.assertRaises(KeyError): self.recover(get)

    def test_integrity_identity_day_and_denial_never_fall_back(self):
        base = self.artifact()
        for kind in ('sha', 'run', 'head', 'repository', 'day', 'expired', '403'):
            with self.subTest(kind=kind):
                raw, meta = deepcopy(base); get = Responses([(raw, meta)])
                if kind == 'sha': get.bodies['actions/artifacts/701/zip'] += b'tamper'
                elif kind in ('run', 'head', 'repository'):
                    key, value = {'run': ('id', 99), 'head': ('head_sha', 'b'*40),
                                  'repository': ('repository_id', 123)}[kind]
                    meta['workflow_run'][key] = value
                    get.bodies['actions/artifacts/701'] = wire(meta)
                elif kind == 'day':
                    artifact = self.artifact(day='2030-04-02'); get = Responses([artifact])
                elif kind == 'expired':
                    meta['expired'] = True; get.bodies['actions/artifacts/701'] = wire(meta)
                else: get.bodies['actions/artifacts/701'] = PermissionError('HTTP 403')
                with self.assertRaises((ValueError, PermissionError)): self.recover(get)
                self.assertFalse(any('/workflows/' in path or 'boatrace' in path for path in get.calls))
        self.assertEqual(self.view['records'][1]['result_observations'], [])

    def test_foreign_day_is_fully_verified_before_scope_filter_and_conflicts_hold(self):
        out = deepcopy(self.observations[0]); out['race_id'] = '20300402-01-01'
        foreign = self.artifact(items=[out], day='2030-04-02')
        new, counts = self.recover(Responses([foreign]))
        self.assertEqual(new, self.view)
        self.assertEqual(counts['archives_verified'], 1)
        self.assertEqual(counts['out_of_scope_observations'], 1)
        raw, meta = foreign; get = Responses([(raw+b'bad', meta)])
        with self.assertRaises(ValueError): self.recover(get)
        changed = deepcopy(self.observations[0]); changed['source_sha256'] = 'e'*64
        first, _ = self.recover(Responses([self.artifact()]))
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):
            self.recover(Responses([self.artifact(items=[changed])]), view=first)
        changed['captured_at'] = '2030-04-01T02:20:00Z'
        one = self.artifact(items=[changed]); other = self.artifact(702, run=43, items=[dict(changed, source_sha256='d'*64)])
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):
            self.recover(Responses([one, other]), run_ids=[42, 43])

    def test_raw_proof_scope_is_not_invented_and_latest_rejection_remains_visible(self):
        first, _ = self.recover(Responses([self.artifact()]))
        later = deepcopy(self.observations[0])
        later.update(captured_at='2030-04-01T02:20:00Z', closed_at='2030-04-01T01:46:00Z')
        later['source_sha256'] = 'd'*64
        new, _ = self.recover(Responses([self.artifact(items=[later])]), view=first)
        row = new['records'][1]
        self.assertEqual(row['result']['status'], 'unsupported')
        self.assertEqual(row['result_observation_rejections'][0]['reason'], 'RESULT_CUTOFF_MISMATCH')
        self.assertNotIn('cutoff_reference', row['result'])
        self.assertEqual(row['result_observations'][-1], later)
        again, _ = self.recover(Responses([self.artifact(items=[later])]), view=new)
        self.assertEqual(again, new)

    def test_invalid_run_scope_branch_round_or_duplicate_identity_stops_before_archive_read(self):
        for runs in ([0], [True], list(range(1, 18)), ['42']):
            with self.subTest(runs=runs):
                get = Responses([self.artifact()])
                with self.assertRaises(ValueError): self.recover(get, run_ids=runs)
                self.assertEqual(get.calls, [])
        for field, bad in [('workflow_id', 1), ('head_branch', 'main'), ('head_sha', 'not-a-head')]:
            get = Responses([self.artifact()]); run = run_response(); run[field] = bad
            get.bodies['actions/runs/42'] = wire(run)
            with self.assertRaises(ValueError): self.recover(get)
            self.assertFalse(any(path.startswith('actions/artifacts/') for path in get.calls))
        for name in ('race-existing-cycle-42-cycle-01', 'race-existing-cycle-42-cycle-25'):
            artifact = self.artifact(); artifact[1]['name'] = name; get = Responses([artifact])
            with self.assertRaisesRegex(ValueError, 'ROUND'): self.recover(get)
            self.assertFalse(any(path.startswith('actions/artifacts/') for path in get.calls))
        duplicate = self.artifact(702)
        with self.assertRaisesRegex(ValueError, 'ROUND'):
            self.recover(Responses([self.artifact(), duplicate]))

    def test_metadata_page_count_and_json_bounds_stop_without_fallback(self):
        get = Responses([self.artifact()])
        endpoint = 'actions/runs/42/artifacts?per_page=100'
        for response in (dict(total_count=12801, artifacts=[]), dict(total_count=2, artifacts=[self.artifact()[1]])):
            get.bodies[endpoint] = wire(response)
            with self.assertRaises(ValueError): self.recover(get)
        get = Responses([self.artifact()]); get.bodies['actions/artifacts/701'] = b' '*(128*1024+1)
        with self.assertRaisesRegex(ValueError, 'BOUND'): self.recover(get)
        self.assertNotIn('actions/artifacts/701/zip', get.calls)

    def test_observation_and_live_receipt_clocks_and_encrypted_key_are_bound(self):
        future = deepcopy(self.observations[0]); future['captured_at'] = '2030-04-01T03:00:02Z'
        get = Responses([self.artifact(items=[future])])
        with self.assertRaisesRegex(ValueError, 'CAPTURE_CLOCK'): self.recover(get)
        get = Responses([self.artifact(cipher=True)])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'ARCHIVE_PAYLOAD'):
                self.recover(get, key=bytes(reversed(KEY)))
        get = Responses([self.artifact()])
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            self.recover(get, now=datetime(2031, 4, 1, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError, 'AWARE_CLOCK'):
            self.recover(get, now=datetime(2030, 4, 1))

    def test_current_run_can_be_in_progress_and_absence_is_unchanged_without_fake_results(self):
        get = Responses([self.artifact()]); run = run_response(); run['status'] = 'in_progress'
        get.bodies['actions/runs/42'] = wire(run)
        new, _ = self.recover(get)
        self.assertEqual(new['records'][1]['result']['status'], 'final')
        unchanged, counts = self.recover(Responses())
        self.assertEqual(unchanged, self.view); self.assertNotIn('results_synced_at', unchanged)
        self.assertEqual(counts['archives_verified'], 0)


if __name__ == '__main__': unittest.main()
