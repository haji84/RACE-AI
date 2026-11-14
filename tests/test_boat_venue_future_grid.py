"""Prospective grid admission uses fictional clocks/keys and no source I/O."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from tests.test_boat_all_model_inputs import official_inputs, ASOF
from tests import test_boat_venue_feature_adapter as venue_fixture

try:
    grid = importlib.import_module('race_ai.boat_venue_future_grid')
except ModuleNotFoundError:
    grid = None


class FutureGridTests(unittest.TestCase):
    # Keep only this class's tests: reused fixture builders create encrypted
    # SQLite with the existing test-only owner key, never an operator key.
    def setUp(self):
        venue_fixture.VenueFeatureTests.setUp(self)
        self.assertIsNotNone(grid, 'explicit prospective grid admission is absent')
        self.folder, self.pointer, _ = self.dataset(partial=True)
        self.log = b'fictional reviewed full grid verification\n'
        self.run = dict(id=42370578793, workflow_id=392270247,
            path='.github/workflows/forecast-audit-ui.yml', event='pull_request',
            head_sha='b569f3c0248c51092a24db1995d5418c2f1e18e4',
            head_branch='feat/four-sport-forecast-audit-view-20261022', run_attempt=1,
            actor=dict(id=173585154, login='haji84'), triggering_actor=dict(id=173585154, login='haji84'),
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            pull_requests=[dict(number=71, head=dict(sha='f'*40))])
        self.job = dict(id=128397771646, run_id=self.run['id'], run_attempt=1,
            head_sha=self.run['head_sha'], name='Independently restore encrypted all-racer SQLite',
            status='completed', conclusion='success', started_at='2026-11-07T12:01:11Z',
            completed_at='2026-11-07T12:04:44Z', steps=[dict(number=n, name=name,
                status='completed', conclusion='success', started_at='2026-11-07T12:01:13Z',
                completed_at='2026-11-07T12:04:41Z') for n, name in (
                    (2, 'Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683'),
                    (7, 'Authenticate, decrypt, verify SQLite and lookup every racer'),
                    (10, 'Restore pinned full-period monthly generations and verify every original hash'),
                    (11, 'Restore encrypted venue grid and verify all racer and course cells'))])
        self.jobs = dict(total_count=1, jobs=[self.job])
        self.projection = dict(schema='RACE_AI_REVIEWED_BOAT_GRID_READBACK_METADATA_V1',
            run={k:deepcopy(v) for k,v in self.run.items() if k!='pull_requests'},
            job={k:deepcopy(v) for k,v in self.job.items() if k!='steps'},
            required_steps=deepcopy(self.job['steps']))
        self.projection['run']['pull_request_numbers']=[71]
        self.metadata_sha = digest(self.projection)
        self.log_sha = hashlib.sha256(self.log).hexdigest()
        for name, value in (('DATASET_SHA', self.pointer['dataset_sha256']),
                            ('DATASET_COMMIT', self.pointer['source_commit']),
                            ('METADATA_SHA', self.metadata_sha), ('LOG_SHA', self.log_sha)):
            p=patch.object(grid, name, value);p.start();self.addCleanup(p.stop)
        self.manifest=dict(schema='RACE_AI_PROSPECTIVE_BOAT_VENUE_GRID_INPUT_V1',
            dataset_pointer=deepcopy(self.pointer), observed_only=True,
            course_feature_policy='EXPLICIT_REPLACE_SUPPORTED_COURSE_FIELDS_RETAIN_PRIOR_V1',
            readback=dict(run_id=self.run['id'], run_attempt=1, job_id=self.job['id'],
                head_sha=self.run['head_sha'], metadata_sha256=self.metadata_sha, log_sha256=self.log_sha))

    dataset=venue_fixture.VenueFeatureTests.dataset
    collection=venue_fixture.VenueFeatureTests.collection

    def verify(self, **changes):
        args=dict(manifest=self.manifest, run=self.run, jobs=self.jobs, log=self.log,
            now=datetime.fromisoformat('2030-01-14T00:00:00+00:00'))
        args.update(changes)
        return grid.verify_readback(**args)

    def capability(self, **changes):
        from tests.test_boat_pdca_recipient import OWNER
        record=grid.seal_capability(self.manifest, self.verify(), self.folder,
            available_at='2030-01-02T00:00:00Z', verified_at='2030-01-14T00:00:00Z',
            run_id='42', head_sha='a'*40, round_no=1, key=OWNER)
        record.update(changes)
        return grid.open_capability(record, run_id='42', head_sha='a'*40, round_no=1, key=OWNER)

    def test_job_success_without_exact_step_or_log_cannot_admit_the_grid(self):
        proof=self.verify()
        self.assertEqual(proof['completed_at'], '2026-11-07T12:04:44Z')
        self.assertEqual(proof['metadata_sha256'], self.metadata_sha)
        for mutate in (lambda r,j:j['jobs'][0]['steps'][-1].update(conclusion='skipped'),
                       lambda r,j:j['jobs'][0]['steps'].pop(),
                       lambda r,j:r['actor'].update(id=1),
                       lambda r,j:r.update(head_sha='f'*40),
                       lambda r,j:j['jobs'][0].update(run_attempt=2)):
            run,jobs=deepcopy(self.run),deepcopy(self.jobs);mutate(run,jobs)
            with self.assertRaises(ValueError):self.verify(run=run,jobs=jobs)
        with self.assertRaises(ValueError):self.verify(log=self.log+b'HOLD')

    def test_moved_embedded_pr_head_does_not_replace_immutable_run_head(self):
        self.assertEqual(self.verify()['metadata_sha256'], self.metadata_sha)
        run=deepcopy(self.run);run['pull_requests'][0]['head']['sha']='0'*40
        self.assertEqual(self.verify(run=run)['metadata_sha256'], self.metadata_sha)

    def test_preparation_requires_ready_verified_bytes_before_issuing_capability(self):
        self.assertTrue(callable(getattr(grid,'prepare_capability',None)), 'pre-source preparation is absent')
        from tests.test_boat_pdca_recipient import OWNER
        calls=[]
        responses={f'actions/runs/{self.run["id"]}/attempts/1':self.run,
            f'actions/runs/{self.run["id"]}/attempts/1/jobs?per_page=100':self.jobs,
            f'actions/jobs/{self.job["id"]}/logs':self.log}
        def fetch(path):
            calls.append(path);value=responses[path]
            return value if isinstance(value,bytes) else json.dumps(value).encode()
        ready=dict(status='ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED',plaintext_published=False,
            verified_cells=63432,known_racers=2643,venues=24,source_days=7963)
        for report in (dict(status='HOLD_OWNER_STATE_KEY_MISSING',verified_cells=0),ready):
            with patch('race_ai.boat_venue_dataset.readback_dataset',return_value=report):
                options=dict(gh=fetch, clock=lambda:datetime.fromisoformat('2030-01-14T00:00:00+00:00'),
                    run_id='42',head_sha='a'*40,round_no=1,key=OWNER)
                if report is ready:
                    record=grid.prepare_capability(self.manifest,self.folder,self.root,**options)
                    cap=grid.open_capability(record,run_id='42',head_sha='a'*40,round_no=1,key=OWNER)
                    grid.require_before_source(cap,ASOF)
                else:
                    with self.assertRaises(ValueError):
                        grid.prepare_capability(self.manifest,self.folder,self.root,**options)
        self.assertTrue(all(path in responses for path in calls))

    def test_capability_rejects_tamper_wrong_round_and_source_before_preload(self):
        from tests.test_boat_pdca_recipient import OWNER
        cap=self.capability()
        grid.require_before_source(cap, ASOF)
        for at in ('2030-01-14T00:00:00Z','2030-01-13T23:59:59Z',
                   '2026-11-07T12:04:45Z','2030-01-02T00:00:00Z'):
            with self.assertRaises(ValueError):grid.require_before_source(cap,at)
        record=deepcopy(cap.record);record['data']['round_no']=2
        with self.assertRaises(ValueError):
            grid.open_capability(record,run_id='42',head_sha='a'*40,round_no=1,key=OWNER)

    def test_server_seconds_precision_requires_strictly_later_source(self):
        from tests.test_boat_pdca_recipient import OWNER
        record=grid.seal_capability(self.manifest,self.verify(),self.folder,
            available_at='2026-11-07T11:00:00Z',verified_at='2026-11-07T12:04:44.500000Z',
            run_id='42',head_sha='a'*40,round_no=1,key=OWNER)
        cap=grid.open_capability(record,run_id='42',head_sha='a'*40,round_no=1,key=OWNER)
        with self.assertRaises(ValueError):grid.require_before_source(cap,'2026-11-07T12:04:45Z')
        grid.require_before_source(cap,'2026-11-07T12:04:45.000001Z')

    def test_native_copy_records_exact_period_and_replacements_without_retiming(self):
        from race_ai.boat_all_model_inputs import build_native_inputs
        p,b=official_inputs();old=build_native_inputs(p,b,as_of=ASOF)
        original=deepcopy(old)
        new=grid.enrich_native_inputs(old,self.capability(),source_as_of=ASOF)
        self.assertEqual(old,original)
        self.assertEqual(new['as_of'],ASOF)
        self.assertEqual(new['native_inputs']['boat_observed']['snapshot']['as_of'],ASOF)
        observed=new['native_inputs']['boat_observed']['snapshot']['participants'][0]
        self.assertAlmostEqual(observed['features']['course_mean_st']['value'],.12)
        shared=new['native_inputs']['shared']['snapshot']['participants'][0]
        self.assertAlmostEqual(shared['features']['local_course_history']['value'],.88)
        self.assertEqual(shared['features']['local_course_history']['sample_n'],2)
        for kind in ('boat_ab','boat_clite'):
            before=deepcopy(original['native_inputs'][kind]);after=deepcopy(new['native_inputs'][kind])
            after.pop('prospective_grid_evidence');self.assertEqual(after,before)
        evidence=new['prospective_grid_evidence']
        self.assertEqual(evidence['original_native_inputs_sha256'],digest(original['native_inputs']))
        self.assertFalse(evidence['venue_evidence']['4001']['profile']['history_completeness'])
        self.assertEqual(evidence['venue_evidence']['4001']['period_end'],'2026-11-04')
        self.assertEqual(evidence['venue_evidence']['4001']['current_frame'],1)
        self.assertEqual(evidence['new_native_as_of'],ASOF)
        from race_ai import all_existing_model_registry as registry
        for cell in registry.active_cells():
            if cell['sport']=='boat' and cell['group'] in new['native_inputs']:
                registry.validate_payload(cell['model_id'],'boat',new['native_inputs'][cell['group']],
                    at=ASOF,allow_source=lambda *args:True)

    def test_fresh_builder_accepts_only_explicit_capability_and_old_flow_is_exact(self):
        from race_ai.boat_all_model_inputs import build_native_inputs
        p,b=official_inputs();original=deepcopy((p,b))
        expected=build_native_inputs(p,b,as_of=ASOF)
        self.assertIn('prospective_grid',__import__('inspect').signature(build_native_inputs).parameters,
            'fresh native boundary has no explicit prospective input')
        self.assertEqual(build_native_inputs(p,b,as_of=ASOF,prospective_grid=None),expected)
        new=build_native_inputs(p,b,as_of=ASOF,prospective_grid=self.capability())
        self.assertIn('prospective_grid_evidence',new)
        self.assertEqual((p,b),original)
        with self.assertRaises(ValueError):
            build_native_inputs(p,b,as_of=ASOF,prospective_grid=dict(unverified=True))

    def test_engine_freezes_new_research_inputs_and_preserves_baseline_original(self):
        from race_ai import boat_all_model_cycle as engine
        from tests.test_boat_all_model_cycle import (AllModelCycleTests, source_context,
            native_baseline, receipt, fitted_ranker, NOW)
        self.fitted=fitted_ranker();runtime=AllModelCycleTests.runtime(self,fitted=True)
        ctx=source_context();document=native_baseline(ctx);original=deepcopy(document)
        self.assertIn('prospective_grid',__import__('inspect').signature(engine.forecast_round).parameters,
            'new capture is not connected to the admitted grid')
        result=engine.forecast_round([ctx],runtime,now=NOW,baseline_document=document,
            baseline_receipt=receipt(document,saved='2030-04-01T18:00:05+09:00'),
            prospective_grid=self.capability())
        self.assertEqual(document,original)
        self.assertEqual(result['summary']['reused_baseline_forecasts'],0)
        capsules=engine.verify_native_input_capsules(result)
        self.assertTrue(capsules[0]['native_inputs'])
        for native in capsules[0]['native_inputs'].values():
            self.assertEqual(native['prospective_grid_evidence']['original_source_as_of'],ctx['as_of'])
        self.assertEqual(result['current_inputs'][0]['as_of'],ctx['as_of'])

    def test_mixed_native_capture_clocks_hold_without_retiming_original_inputs(self):
        from race_ai import all_existing_model_registry as registry
        from race_ai.boat_history_store import HistoryStore
        from race_ai.boat_all_model_inputs import build_native_inputs
        from race_ai.four_sport_learning import LEARNED_ID
        from tests.test_boat_pdca_history_inputs import retain_days
        from tests.test_all_existing_model_native_future import training
        history=HistoryStore(self.root/'fresh-history.sqlite');self.addCleanup(history.close);retain_days(history)
        p,b=official_inputs(lanes=(1,2,3,4,5,6))
        model=training(14)['models']['boat/'+LEARNED_ID]['native_training']
        native=build_native_inputs(p,b,as_of=ASOF,fitted_model=model,prospective_grid=self.capability(),
            history_context=dict(history_store=history,history_identity_verified=True,owner_reviewed=True))['native_inputs']
        requests=[dict(cell_key=c['cell_key'],native_payload=deepcopy(native[c['group']]))
            for c in registry.active_cells() if c['sport']=='boat']
        self.assertEqual(len(requests),14)
        original=deepcopy(requests)
        # Native source families retain the real preview-capture clock while
        # snapshot families retain the later build clock. The strict consumer
        # must HOLD this complete set instead of rewriting either original.
        clocks={registry.identity(row['cell_key'][5:],'boat',row['native_payload'])['as_of'] for row in requests}
        self.assertEqual(clocks,{'2030-01-15T09:00:00+09:00',ASOF})
        for request in requests:
            self.assertEqual(request['native_payload']['prospective_grid_evidence']['dataset_pointer'],self.pointer)
        with self.assertRaisesRegex(ValueError,'CARRIER_ORIGINAL_CLOCK'):
            grid.prospective_requests(requests,now=datetime.fromisoformat(ASOF))
        from scripts import github_existing_cycle as worker
        out=self.root/'prospective-pairs'
        with self.assertRaisesRegex(ValueError,'CARRIER_ORIGINAL_CLOCK'):
            worker._prospective_carrier_pairs({},requests,out,now=datetime.fromisoformat(ASOF))
        self.assertFalse(out.exists())
        self.assertEqual(requests,original)

    def test_original_preview_capture_as_master_admits_all_fourteen_without_retiming_facts(self):
        from race_ai import all_existing_model_registry as registry
        from race_ai.boat_history_store import HistoryStore
        from race_ai.boat_all_model_inputs import build_native_inputs
        from race_ai.four_sport_learning import LEARNED_ID
        from tests.test_boat_pdca_history_inputs import retain_days
        from tests.test_all_existing_model_native_future import training
        history=HistoryStore(self.root/'fresh-history.sqlite');self.addCleanup(history.close);retain_days(history)
        p,b=official_inputs(lanes=(1,2,3,4,5,6));original=deepcopy((p,b))
        model=training(14)['models']['boat/'+LEARNED_ID]['native_training']
        master=b['captured_at']
        native=build_native_inputs(p,b,as_of=master,fitted_model=model,prospective_grid=self.capability(),
            history_context=dict(history_store=history,history_identity_verified=True,owner_reviewed=True))['native_inputs']
        requests=[dict(cell_key=c['cell_key'],native_payload=deepcopy(native[c['group']]))
            for c in registry.active_cells() if c['sport']=='boat']
        self.assertEqual(len(requests),14)
        self.assertEqual({registry.identity(row['cell_key'][5:],'boat',row['native_payload'])['as_of']
                          for row in requests},{'2030-01-15T09:00:00+09:00'})
        selected=grid.prospective_requests(requests,now=datetime.fromisoformat(ASOF))
        self.assertEqual(selected,requests)
        self.assertEqual((p,b),original)
        for request in selected:
            self.assertEqual(request['native_payload']['prospective_grid_evidence']['original_source_as_of'],master)
        from scripts import github_existing_cycle as worker
        from race_ai.all_existing_model_pairs import verify_private_record
        from race_ai.boat_venue_learning import read_candidate
        trained=training(14)
        receipt=dict(id=700,name='all-existing-model-learning-7-1',expired=False,size_in_bytes=100,
            digest='sha256:'+'a'*64,created_at=trained['created_at'],expires_at='2030-02-01T00:00:00Z',
            workflow_run=dict(id=7,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
        out=self.root/'prospective-pairs'
        summary=worker._prospective_carrier_pairs(dict(context=dict(training=trained,receipt=receipt)),
            selected,out,now=datetime.fromisoformat(ASOF))
        self.assertTrue(summary['prospective_grid_carrier'])
        self.assertEqual(summary['captured_native_input_count'],14)
        records=[read_candidate(path) for path in out.iterdir() if path.is_dir()]
        for record in records:verify_private_record(record)
        saved=[cap for record in records for cap in record.get('captured_native_inputs',[])]
        self.assertEqual({cap['cell_key']:cap['native_payload'] for cap in saved},
            {row['cell_key']:row['native_payload'] for row in selected})
