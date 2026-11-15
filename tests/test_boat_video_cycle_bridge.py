"""Invented archives and results: operational wiring, never real-video accuracy."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import cycle_recovery as recovery
from race_ai import observed_weight_learning as learning
from race_ai import frozen_day_cycle as frozen
from race_ai.boat_observed_pairwise_models import MODEL_IDS
from tests.test_boat_video_learning import controlled_inputs
from tests.test_boat_video_learning import reseal_context
from tests.test_video_existing_hooks import target_bundle, target_video
from tests.test_observed_weight_learning import NOW
from tests import test_observed_weight_learning as observed_fixtures
from tests.test_observed_p1_connection import archive
from tests.test_frozen_day_cycle import observation
from tests.test_frozen_day_cycle import sample


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def zipped(member, body):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        bundle.writestr(member, body)
    return stream.getvalue()


class InventedAPI:
    """An explicit in-memory authenticated API stand-in, not an actual receipt."""
    def __init__(self):
        self.records, self.calls = {}, []

    def get(self, path):
        self.calls.append(path)
        return self.records[path]

    def add(self, context, *, ident, saved, run=None):
        run = run or 9000 + ident
        raw = zipped('video-contexts.json', wire(dict(
            schema='RACE_AI_BOAT_VIDEO_CONTEXT_ARCHIVE_V1', contexts=[context])))
        meta = dict(id=ident, name=f'race-video-context-{run}', expired=False,
            created_at=saved, size_in_bytes=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest(),
            workflow_run=dict(id=run, head_repository_id=1416489937,
                              head_branch=recovery.BRANCH, head_sha='a' * 40))
        producer = dict(id=run, workflow_id=recovery.WORKFLOW, head_sha='a' * 40,
            head_branch=recovery.BRANCH, event='push', status='completed',
            created_at=(frozen.ts(saved)-timedelta(minutes=10)).isoformat(),
            repository=dict(id=1416489937), head_repository=dict(id=1416489937))
        self.records[f'actions/artifacts/{ident}'] = wire(meta)
        self.records[f'actions/artifacts/{ident}/zip'] = raw
        self.records[f'actions/runs/{run}'] = wire(producer)
        return dict(video_context=deepcopy(context), receipt=deepcopy(meta))


def module(test):
    try:
        return importlib.import_module('race_ai.boat_video_archive')
    except ModuleNotFoundError:
        test.fail('independent archived video-context reader is not connected')


class VideoArchiveTests(unittest.TestCase):
    def setUp(self):
        self.api = InventedAPI()
        self.rows, _, self.contexts, _ = controlled_inputs(1)
        self.snapshot = self.rows[0]['learning_snapshot']
        initial = next(iter(self.contexts.values()))
        self.envelope = self.api.add(initial['video_context'], ident=1000,
                                      saved=initial['receipt']['created_at'])

    def reader(self):
        return module(self).VideoContextArchiveReader(self.api.get,
            clock=lambda: NOW+timedelta(hours=1))

    def test_independent_api_run_and_zip_read_bind_exact_context_and_are_cached(self):
        reader = self.reader()
        reader.load([1000])
        before = deepcopy(self.envelope)
        self.assertEqual(reader.select(self.snapshot), self.envelope)
        proof = reader.verify(self.envelope['receipt'],
            self.envelope['video_context']['context_sha256'], self.snapshot['as_of'])
        self.assertEqual(proof, dict(context_sha256=before['video_context']['context_sha256'],
            **{k: before['receipt'][k] for k in ('id', 'digest', 'created_at')}))
        self.assertEqual(reader.artifact_ids, [1000])
        self.assertEqual(len(self.api.calls), 3)
        self.assertEqual(self.envelope, before)

    def test_foreign_producer_workflow_head_and_metadata_are_rejected(self):
        for target, field, bad in (
            ('run', 'workflow_id', 123), ('run', 'head_branch', 'main'),
            ('run', 'head_sha', 'b'*40), ('run', 'event', 'pull_request'),
            ('run', 'head_repository', {'id': 999}), ('run', 'repository', {'id': 999}),
            ('run', 'id', 999), ('run', 'status', 'queued'),
            ('meta', 'expired', True), ('meta', 'name', 'other-context-10000'),
            ('meta', 'id', 999), ('meta', 'digest', 'sha256:'+'b'*64)):
            api = deepcopy(self.api)
            path = 'actions/runs/10000' if target == 'run' else 'actions/artifacts/1000'
            item = json.loads(api.records[path]); item[field] = bad; api.records[path] = wire(item)
            with self.subTest(target=target, field=field), self.assertRaisesRegex(ValueError,
                    'BOAT_VIDEO_ARCHIVE_REJECTED'):
                module(self).VideoContextArchiveReader(api.get,
                    clock=lambda: NOW+timedelta(hours=1)).load([1000])

    def test_declared_archive_size_is_bounded_before_requesting_zip_bytes(self):
        for declared in ('MISSING',None,0,-1,True,1.5,32*1024*1024+1):
            api=deepcopy(self.api)
            meta=json.loads(api.records['actions/artifacts/1000'])
            if declared=='MISSING':meta.pop('size_in_bytes')
            else:meta['size_in_bytes']=declared
            api.records['actions/artifacts/1000']=wire(meta)
            with self.subTest(declared=declared),self.assertRaisesRegex(ValueError,
                    'BOAT_VIDEO_ARCHIVE_REJECTED'):
                module(self).VideoContextArchiveReader(api.get,
                    clock=lambda:NOW+timedelta(hours=1)).load([1000])
            self.assertNotIn('actions/artifacts/1000/zip',api.calls)

    def test_altered_bytes_duplicate_json_and_duplicate_members_are_rejected(self):
        for change in ('bytes', 'duplicate_json', 'duplicate_member'):
            api = deepcopy(self.api)
            raw = api.records['actions/artifacts/1000/zip']
            if change == 'bytes':
                raw += b'changed'
            elif change == 'duplicate_json':
                raw = zipped('video-contexts.json', b'{"schema":"a","schema":"b","contexts":[]}')
            else:
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as bundle:
                    bundle.writestr('video-contexts.json', '{}')
                    bundle.writestr('video-contexts.json', '{}')
                raw = stream.getvalue()
            api.records['actions/artifacts/1000/zip'] = raw
            if change != 'bytes':
                meta = json.loads(api.records['actions/artifacts/1000'])
                meta['digest'] = 'sha256:'+hashlib.sha256(raw).hexdigest()
                api.records['actions/artifacts/1000'] = wire(meta)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,
                    'BOAT_VIDEO_ARCHIVE_REJECTED'):
                module(self).VideoContextArchiveReader(api.get,
                    clock=lambda: NOW+timedelta(hours=1)).load([1000])

    def test_embedded_receipt_assertions_wrong_hash_and_late_input_are_rejected(self):
        for change in ('digest', 'created_at', 'wrong_context', 'not_available', 'future_input'):
            reader = self.reader()
            receipt = deepcopy(self.envelope['receipt'])
            context_sha = self.envelope['video_context']['context_sha256']
            as_of = self.snapshot['as_of']
            if change == 'digest': receipt['digest'] = 'sha256:'+'b'*64
            if change == 'created_at': receipt['created_at'] = self.snapshot['as_of']
            if change == 'wrong_context': context_sha = 'b'*64
            if change == 'not_available': as_of = receipt['created_at']
            if change == 'future_input': as_of = (NOW+timedelta(days=1)).isoformat()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,
                    'BOAT_VIDEO_ARCHIVE_REJECTED'):
                reader.verify(receipt, context_sha, as_of)

    def test_source_context_saved_after_cutoff_cannot_be_loaded(self):
        api = InventedAPI()
        api.add(self.envelope['video_context'], ident=1000,
                saved=self.envelope['video_context']['cutoff_at'])
        with self.assertRaisesRegex(ValueError, 'BOAT_VIDEO_ARCHIVE_REJECTED'):
            module(self).VideoContextArchiveReader(api.get,
                clock=lambda: NOW+timedelta(hours=1)).load([1000])

    def test_whole_second_receipt_resolution_preserves_fractional_context_time(self):
        api=InventedAPI()
        context=deepcopy(self.envelope['video_context'])
        saved=self.envelope['receipt']['created_at']
        context['as_of']=(frozen.ts(saved)+timedelta(microseconds=500000)).isoformat()
        reseal_context(context)
        envelope=api.add(context,ident=1000,saved=saved)
        reader=module(self).VideoContextArchiveReader(api.get,clock=lambda:NOW+timedelta(hours=1))
        reader.load([1000])
        self.assertEqual(reader.verify(envelope['receipt'],context['context_sha256'],
            self.snapshot['as_of'])['context_sha256'],context['context_sha256'])

    def test_foreign_model_snapshot_cannot_replace_existing_family_fit_input(self):
        reader=self.reader();reader.load([1000])
        foreign=deepcopy(self.rows[0]);foreign.update(model_id='unrelated',
            as_of=(frozen.ts(self.snapshot['as_of'])+timedelta(minutes=1)).isoformat(),stage='P0')
        foreign['learning_snapshot']['stage']='P0'
        self.assertEqual(reader.contexts_for_rows(self.rows+[foreign]),
                         {self.rows[0]['race_id']:self.envelope})

    def test_selection_binds_roster_cutoff_and_receipt_interval_without_post_input_leakage(self):
        reader = self.reader(); reader.load([1000])
        for change in ('roster', 'cutoff', 'p0', 'early'):
            snap = deepcopy(self.snapshot)
            if change == 'roster': snap['participants'][0]['registration_no'] = '9999'
            if change == 'cutoff': snap['sales_cutoff_at'] = (frozen.ts(snap['sales_cutoff_at'])+timedelta(seconds=1)).isoformat()
            if change == 'p0': snap['stage'] = 'P0'
            if change == 'early': snap['as_of'] = self.envelope['receipt']['created_at']
            with self.subTest(change=change): self.assertIsNone(reader.select(snap))
        self.assertEqual(reader.contexts_for_rows(self.rows), self.contexts | {
            self.rows[0]['race_id']: self.envelope})

    def test_newer_missing_context_does_not_hide_an_available_comparable_context(self):
        missing=deepcopy(self.envelope['video_context'])
        missing['as_of']=(frozen.ts(missing['as_of'])+timedelta(seconds=1)).isoformat()
        for participant in missing['participants']:
            for cell in participant['feature_cells'].values():
                cell.update(value=None,status='MISSING',missing_reason='UNAVAILABLE')
        missing.update(eligible_for_research=False,missing_reasons=['UNAVAILABLE'])
        reseal_context(missing)
        self.api.add(missing,ident=1001,
            saved=(frozen.ts(self.envelope['receipt']['created_at'])+timedelta(seconds=2)).isoformat())
        reader=self.reader();reader.load([1000,1001])
        self.assertEqual(reader.select(self.snapshot),self.envelope)


class VideoCycleWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training_rows, cls.training_results, cls.initial_contexts, _ = controlled_inputs()

    def material(self):
        reader_module = module(self)
        api = InventedAPI()
        for envelope in self.initial_contexts.values():
            api.add(envelope['video_context'], ident=envelope['receipt']['id'],
                    saved=envelope['receipt']['created_at'])
        reader = reader_module.VideoContextArchiveReader(api.get,
            clock=lambda: NOW+timedelta(hours=1))
        reader.load([e['receipt']['id'] for e in self.initial_contexts.values()])
        contexts = reader.contexts_for_rows(self.training_rows)
        training = learning.fit_from_verified(self.training_rows, self.training_results, now=NOW,
            video_contexts=contexts, video_receipt_verifier=reader.verify)
        self.assertEqual(training['state'], 'FITTED_VIDEO_EXPERIMENTAL')
        base, extra, bundle = target_bundle()
        target, _ = target_video(next(iter(contexts.values())), bundle['snapshot'])
        api.add(target['video_context'], ident=2000, saved=target['receipt']['created_at'])
        reader.load([2000])
        return api, reader, training, base, extra, bundle

    def test_actual_existing_math_frozen_p1_recovery_and_official_result_pairing(self):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        api, reader, training, base, extra, bundle = self.material()
        report = dict(day_jst='2030-04-01', automatic_learning={'training_sha256': training['training_sha256']})
        learning.seal(report, 'report_sha256')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as saved:
            saved.writestr('status.json', wire(report))
            saved.writestr('trained_observed_models.json', wire(training))
            saved.writestr('official-result-observations.json', '[]')
        raw_training = stream.getvalue()
        training_meta = dict(id=700, name='race-existing-cycle-99', expired=False,
            created_at=(NOW+timedelta(seconds=2)).isoformat(),
            digest='sha256:'+hashlib.sha256(raw_training).hexdigest(),
            workflow_run=dict(id=99, head_repository_id=1416489937))
        model_context = learning.context_from_result_archive(raw_training, training_meta)
        target_context = reader.select(bundle['snapshot'])
        before = deepcopy((bundle, training, target_context))
        shadows = learning.make_shadows(bundle['snapshot'], bundle['suite'], model_context,
            video_context=target_context, video_receipt_verifier=reader.verify)
        self.assertEqual({s['model_id'] for s in shadows}, set(MODEL_IDS))
        self.assertTrue(all(s['variant']=='LEARNED_VIDEO_EXPERIMENTAL' and
                            s['production_eligible'] is False for s in shadows))
        document = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
            paired_forecasts=[build_pair(base, bundle['snapshot']['as_of'])],
            additional_official_feature_shadows=[build_live_feature_shadow(base, extra, bundle['snapshot']['as_of'])],
            observed_pairwise_p1_bundles=[bundle], learned_pairwise_shadows=shadows)
        raw, meta = archive(document, saved=(NOW+timedelta(minutes=11)).isoformat())
        api.records.update({
            f'actions/workflows/{recovery.WORKFLOW}/runs?per_page=100&page=1':wire({'workflow_runs':[
                dict(id=99,status='completed',event='push',head_branch=recovery.BRANCH,
                     created_at='2030-04-01T01:00:00Z')]}),
            'actions/runs/99/artifacts?per_page=100':wire({'total_count':2,'artifacts':[meta,training_meta]}),
            'actions/artifacts/123':wire(meta),'actions/artifacts/123/zip':raw,
            'actions/artifacts/700':wire(training_meta),'actions/artifacts/700/zip':raw_training})
        original_bytes = deepcopy(api.records)
        with tempfile.TemporaryDirectory() as temp:
            restored = recovery.recover(api.get,'2030-04-01',current_run=100,out=Path(temp),
                clock=lambda: NOW+timedelta(hours=1))
            self.assertEqual((Path(temp)/'original-123.zip').read_bytes(), raw)
        self.assertEqual(len(restored['rows']),5)
        self.assertEqual(len(restored['learning_shadows']),2)
        self.assertEqual(restored['video_context_artifact_ids'],list(range(1000,1012))+[2000])
        outcome = observation(restored['rows'][3])
        outcome['captured_at'] = (NOW+timedelta(minutes=40)).isoformat()
        score = learning.score_shadows(restored['learning_shadows'], restored['rows'], [outcome])
        self.assertEqual(score['paired_forecasts'],2)
        self.assertFalse(score['accuracy_improvement_proven'])
        self.assertEqual(frozen.evaluate(restored['rows'],[outcome])['forecast_count'],5)
        self.assertEqual(api.records, original_bytes)
        self.assertEqual((bundle, training, target_context), before)
        # Losing optional video bytes must not discard five authenticated
        # baseline originals or claim that the two video rows were recovered.
        unavailable=deepcopy(api.records)
        unavailable.pop('actions/artifacts/2000/zip')
        with tempfile.TemporaryDirectory() as temp:
            baselines=recovery.recover(unavailable.__getitem__,'2030-04-01',current_run=100,
                out=Path(temp),clock=lambda:NOW+timedelta(hours=1))
            self.assertEqual((Path(temp)/'original-123.zip').read_bytes(),raw)
        self.assertEqual(len(baselines['rows']),5)
        self.assertEqual(baselines['learning_shadows'],[])
        self.assertEqual(baselines['video_shadow_rejections'],[dict(
            forecast_artifact_id=123,rejected_shadows=2,reason='VIDEO_SHADOW_REPLAY_REJECTED')])
        # Authentication of the original baseline ZIP stays mandatory even
        # when optional video is unavailable.
        unavailable['actions/artifacts/123/zip']=raw+b'changed'
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):
            recovery.recover(unavailable.__getitem__,'2030-04-01',current_run=100,
                out=Path(temp),clock=lambda:NOW+timedelta(hours=1))

    def test_forecast_runner_passes_authenticated_context_to_existing_math(self):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        api, reader, training, _, _, bundle = self.material()
        context = dict(training=training, receipt=dict(id=700,expired=False,
            created_at=(NOW+timedelta(seconds=2)).isoformat(),digest='sha256:'+'a'*64,
            workflow_run={'head_repository_id':1416489937}))
        result = dict(observed_pairwise_p1_bundles=[bundle])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'cycle_recovery_output').mkdir()
            index = root/'index.json'; index.write_text('{"entries":[]}')
            output = root/'out'; output.mkdir()
            state = dict(index_entries=[],learning_context=context)
            with patch.object(runner,'ROOT',root), patch.object(runner,'load_state',return_value=state), \
                 patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',output), \
                 patch.object(pilot,'run',return_value=result), \
                 patch.object(runner,'datetime') as clock, \
                 patch.object(learning,'make_shadows',wraps=learning.make_shadows) as math:
                clock.now.return_value=NOW+timedelta(minutes=10)
                runner.forecast('2030-04-01',video_reader=reader)
            saved=json.loads((output/'national.json').read_text())
        self.assertEqual(len(saved['learned_pairwise_shadows']),2)
        self.assertEqual(saved['video_context_artifact_ids'],reader.artifact_ids)
        self.assertTrue(callable(math.call_args.kwargs['video_receipt_verifier']))
        self.assertEqual(math.call_args.kwargs['video_context'],reader.select(bundle['snapshot']))

    def test_existing_audit_fits_authenticated_history_and_reports_only_source_ids(self):
        from scripts import github_existing_cycle as runner
        api,reader,_,_,_,_=self.material()
        schedule=[dict(race_id=row['race_id'],cutoff_at=row['cutoff_at'])
                  for row in self.training_rows[::2]]
        first_doc=dict(schedule=schedule,skipped=[])
        restored=dict(rows=[],receipts=[],excluded_repeats=[],observations=self.training_results,
            scanned_runs=[],learning_shadows=[],training_proofs={},history_proofs={},learning_context=None)
        original_rows=deepcopy(self.training_rows)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cycle_recovery_output').mkdir()
            with patch.object(runner,'ROOT',root),patch.object(runner,'original',
                    return_value=(first_doc,self.training_rows,{'id':1},b'original')),\
                 patch.object(runner,'load_state',return_value=restored),\
                 patch.object(runner,'observe_due_results',return_value=(self.training_results,[],0)),\
                 patch.object(runner,'datetime') as clock,\
                 patch.object(learning,'fit_from_verified',wraps=learning.fit_from_verified) as fitting:
                clock.now.return_value=NOW
                runner.audit('2030-04-01',None,video_reader=reader)
            report=json.loads((root/'existing_cycle_output/status.json').read_text())
            trained=json.loads((root/'existing_cycle_output/trained_observed_models.json').read_text())
            self.assertEqual((root/'existing_cycle_output/first-p0-original.zip').read_bytes(),b'original')
        self.assertEqual(trained['state'],'FITTED_VIDEO_EXPERIMENTAL')
        self.assertEqual(trained['video_admitted_races'],12)
        self.assertEqual(report['video_context_artifact_ids'],reader.artifact_ids)
        self.assertNotIn('video_contexts',report)
        self.assertTrue(callable(fitting.call_args_list[0].kwargs['video_receipt_verifier']))
        self.assertEqual(self.training_rows,original_rows)

    def test_default_no_video_forecast_bytes_and_no_extra_api_reads_are_unchanged(self):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        _,_,bundle=target_bundle()
        context=observed_fixtures.LearningTests().context()
        expected=dict(observed_pairwise_p1_bundles=[bundle],
            learned_pairwise_shadows=learning.make_shadows(bundle['snapshot'],bundle['suite'],context),
            learning_failures=[])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cycle_recovery_output').mkdir()
            index=root/'index.json';index.write_text('{"entries":[]}')
            output=root/'out';output.mkdir()
            state=dict(index_entries=[],learning_context=context)
            with patch.object(runner,'ROOT',root),patch.object(runner,'load_state',return_value=state),\
                 patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',output),\
                 patch.object(pilot,'run',return_value={'observed_pairwise_p1_bundles':[bundle]}),\
                 patch.object(runner,'gh',side_effect=AssertionError('unexpected extra API read')),\
                 patch.object(runner,'datetime') as clock:
                clock.now.return_value=NOW+timedelta(minutes=10)
                runner.forecast('2030-04-01')
            actual=(output/'national.json').read_bytes()
        self.assertEqual(actual,json.dumps(expected,ensure_ascii=False,sort_keys=True,
                                          separators=(',',':')).encode())

    def test_optional_rejected_archive_preserves_baseline_and_does_not_leak_exception(self):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        _,_,bundle=target_bundle()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cycle_recovery_output').mkdir()
            index=root/'index.json';index.write_text('{"entries":[]}')
            output=root/'out';output.mkdir()
            state=dict(index_entries=[],learning_context=None)
            events=[]
            def denied(_):
                events.append('optional-source-read')
                raise ValueError('/private/original/media-and-credentials')
            def baseline(**_):
                events.append('fresh-baseline')
                return {'observed_pairwise_p1_bundles':[bundle]}
            with patch.object(runner,'ROOT',root),patch.object(runner,'load_state',return_value=state),\
                 patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',output),\
                 patch.object(pilot,'run',side_effect=baseline),patch.object(runner,'gh',side_effect=denied):
                runner.forecast('2030-04-01',video_context_artifacts=[9999])
            body=(output/'national.json').read_text();saved=json.loads(body)
        self.assertEqual(saved['observed_pairwise_p1_bundles'],json.loads(json.dumps([bundle])))
        self.assertEqual(events,['optional-source-read','fresh-baseline'])
        self.assertEqual(saved['learning_failures'],[{'reason':'BOAT_VIDEO_ARCHIVE_REJECTED'}])
        self.assertNotIn('/private',body)

    def test_cli_accepts_source_handles_without_replacing_the_trusted_reader(self):
        from scripts import github_existing_cycle as runner
        with patch.object(sys,'argv',['github_existing_cycle.py','forecast',
                '--video-context-artifact','1000','--video-context-artifact','1001']),\
             patch.object(runner,'event_day',return_value='2030-04-01'),\
             patch.object(runner,'forecast') as forecast:
            runner.main()
        forecast.assert_called_once_with('2030-04-01',video_context_artifacts=[1000,1001])

    def test_restore_rejected_optional_source_continues_baselines_and_records_safe_reason(self):
        from scripts import github_existing_cycle as runner
        _,raw,meta=sample()
        document,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01')
        failed_reader=module(self).VideoContextArchiveReader(
            lambda _:(_ for _ in ()).throw(ValueError('/private/token/source')),
            clock=lambda:NOW+timedelta(hours=1))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cycle_recovery_output').mkdir()
            with patch.object(runner,'ROOT',root),patch.object(runner,'original',
                    return_value=(document,rows,meta,raw)),\
                 patch.dict('os.environ',{'GITHUB_RUN_ID':'100'}),\
                 patch.object(runner,'recover',return_value={'rows':rows}) as recover:
                runner.restore('2030-04-01',video_context_artifacts=[9999],video_reader=failed_reader)
            restored=json.loads((root/'cycle_recovery_output/continuity.json').read_text())
            self.assertEqual((root/'boat_all_day_output/forecasts.json').read_bytes(),
                             zipfile.ZipFile(io.BytesIO(raw)).read('forecasts.json'))
        recover.assert_called_once()
        self.assertEqual(restored['rows'],json.loads(json.dumps(rows)))
        self.assertEqual(restored['video_context_rejections'],[{'reason':'BOAT_VIDEO_ARCHIVE_REJECTED'}])
        self.assertNotIn('/private',json.dumps(restored))

    def test_restore_keeps_verified_handles_when_a_different_optional_source_fails(self):
        from scripts import github_existing_cycle as runner
        api,reader,_,_,_,_=self.material()
        _,raw,meta=sample();document,rows=frozen.read_p0(raw,meta,expected_day='2030-04-01')
        good_handles=reader.artifact_ids
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cycle_recovery_output').mkdir()
            with patch.object(runner,'ROOT',root),patch.object(runner,'original',
                    return_value=(document,rows,meta,raw)),\
                 patch.dict('os.environ',{'GITHUB_RUN_ID':'100'}),\
                 patch.object(runner,'recover',return_value={'rows':rows}):
                runner.restore('2030-04-01',video_context_artifacts=[9999],video_reader=reader)
            restored=json.loads((root/'cycle_recovery_output/continuity.json').read_text())
        self.assertEqual(restored['video_context_artifact_ids'],good_handles)
        self.assertNotIn(9999,restored['video_context_artifact_ids'])
        self.assertEqual(restored['video_context_rejections'],[{'reason':'BOAT_VIDEO_ARCHIVE_REJECTED'}])


class SourceHandleContinuityTests(unittest.TestCase):
    def result_api(self, handles):
        report=dict(day_jst='2030-04-01',automatic_learning={'state':'INSUFFICIENT_VIDEO_SUPPORT'},
                    video_context_artifact_ids=handles)
        learning.seal(report,'report_sha256')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as bundle:
            bundle.writestr('status.json',wire(report))
            bundle.writestr('official-result-observations.json','[]')
        raw=stream.getvalue()
        meta=dict(id=700,name='race-existing-cycle-99',expired=False,
            created_at=(NOW+timedelta(seconds=2)).isoformat(),
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            workflow_run={'id':99,'head_repository_id':1416489937})
        records={
            f'actions/workflows/{recovery.WORKFLOW}/runs?per_page=100&page=1':wire({'workflow_runs':[
                dict(id=99,status='completed',event='push',head_branch=recovery.BRANCH,
                     created_at='2030-04-01T01:00:00Z')]}),
            'actions/runs/99/artifacts?per_page=100':wire({'total_count':1,'artifacts':[meta]}),
            'actions/artifacts/700':wire(meta),'actions/artifacts/700/zip':raw}
        return records

    def test_source_handles_survive_insufficient_fit_but_are_not_authentication(self):
        records=self.result_api([1234])
        with tempfile.TemporaryDirectory() as temp:
            restored=recovery.recover(records.__getitem__,'2030-04-01',current_run=100,
                out=Path(temp),clock=lambda:NOW+timedelta(hours=1))
        self.assertEqual(restored['video_context_artifact_ids'],[1234])
        self.assertEqual(restored['learning_shadows'],[])
        self.assertIsNone(restored['learning_context'])
        # The authenticated parent only retained a handle; an actual source
        # API/bytes read is still mandatory before it can become model input.
        reader=module(self).VideoContextArchiveReader(records.__getitem__,
            clock=lambda:NOW+timedelta(hours=1))
        with self.assertRaisesRegex(ValueError,'BOAT_VIDEO_ARCHIVE_REJECTED'):
            reader.load(restored['video_context_artifact_ids'])

    def test_malformed_handle_claim_cannot_corrupt_continuity(self):
        for handles in ([True],[1,1],[[1]],'1234'):
            with self.subTest(handles=handles), tempfile.TemporaryDirectory() as temp,\
                 self.assertRaisesRegex(ValueError,'BOAT_VIDEO_ARCHIVE_REJECTED'):
                recovery.recover(self.result_api(handles).__getitem__,'2030-04-01',current_run=100,
                    out=Path(temp),clock=lambda:NOW+timedelta(hours=1))

    def test_video_rejection_does_not_hide_nonvideo_candidate_integrity_failure(self):
        document={'learned_pairwise_shadows':[
            {'schema':'RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1'},
            {'schema':learning.SCHEMA_SHADOW,'prediction_sha256':'b'*64}]}
        with self.assertRaises(ValueError):
            module(self).read_optional_video_shadows(document,{'id':123},[],
                receipt_verifier=lambda *_:None)

    def test_missing_video_training_parent_is_reported_but_nonvideo_parent_stays_strict(self):
        ordinary=dict(variant='LEARNED_SHADOW',training_artifact_id=700,
            training_sha256='a'*64,training_receipt_digest='sha256:'+'b'*64)
        video=dict(variant='LEARNED_VIDEO_EXPERIMENTAL',artifact_id=123,
            training_artifact_id=701,training_sha256='c'*64,
            training_receipt_digest='sha256:'+'d'*64)
        proofs={'700':dict(training_sha256='a'*64,digest='sha256:'+'b'*64)}
        accepted,rejected=module(self).validate_optional_video_training([ordinary,video],proofs)
        self.assertEqual(accepted,[ordinary])
        self.assertEqual(rejected,[dict(forecast_artifact_id=123,rejected_shadows=1,
            reason='VIDEO_SHADOW_TRAINING_RECEIPT_REJECTED')])
        with self.assertRaises(ValueError):
            module(self).validate_optional_video_training([ordinary,video],{})


if __name__ == '__main__':
    unittest.main()
