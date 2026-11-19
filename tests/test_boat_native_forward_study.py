"""Invented native cells and service receipts; no real key or external reads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha256
import base64
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from tests import test_boat_current_pair_eligibility_audit as existing
from race_ai.actions_contract import digest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
CELLS = tuple('boat/'+name for name in (
    'boat-observed-pairwise-factor-v1', 'boat-observed-pairwise-start-v1'))
PATH = ROOT/'scripts/boat_native_forward_study.py'
if PATH.exists():
    loader = importlib.util.spec_from_file_location('native_forward_study_fixture', PATH)
    study = importlib.util.module_from_spec(loader); loader.loader.exec_module(study)
else:
    study = None


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def packed(value):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('boat-national-p1-counts.json', wire(value))
    return stream.getvalue()


class NativeForwardStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        from tests.test_all_existing_model_learning import observed_records
        from tests.test_observed_weight_learning import NOW
        cls.records = observed_records(synthetic=False)
        cls.training = fit(cls.records, now=NOW,
            allow_source=lambda *_:True, allow_training=lambda *_:True)

    def setUp(self):
        changed = patch.object(existing, 'SOURCE', SOURCE)
        changed.start(); self.addCleanup(changed.stop)
        self.case = existing.CurrentPairEligibilityTests(
            'test_real_crypto_counts_are_flat_private_and_still_unqualified')
        self.case.training = deepcopy(self.training)
        self.case.records = deepcopy(self.records)
        self.case.cell = next(iter(self.training['models']))
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        # Create P1 at the input boundary, then use the real producer/AEAD reader.
        from race_ai.all_existing_model_pairs import make_private_pairs
        from race_ai.boat_venue_learning import read_candidate
        seed=existing.pair_fixture.AllExistingModelPrivatePairsTests('runTest');seed.records=self.records
        native=seed.native(1);native['snapshot']['stage']='P1'
        snapshot=native['snapshot'];source=snapshot['sources'][0]['source_id']
        for row in snapshot['participants']:
            row['missing'].pop('exhibition_time_seconds')
            row['features']['exhibition_time_seconds']=dict(value=6.7+row['lane']*.01,
                sample_n=None,source_id=source,transform_id='official_exhibition_time_seconds_v1')
        target=self.case.root/'genuine-p1'
        make_private_pairs(self.case.context,[dict(cell_key=cell,native_payload=deepcopy(native)) for cell in CELLS],
            target,now=existing.FORECAST_NOW,allow_source=lambda *_:True)
        children=[p for p in target.iterdir() if p.is_dir()]
        raw=existing.packed({p.name+'/'+name:(p/name).read_bytes() for p in children
            for name in ('learning.json','learning.enc','summary.json')})
        self.case.payload=read_candidate(children[0])
        self.case.add(800,'all-existing-model-pairs-99-1',raw,
            (existing.FORECAST_NOW+timedelta(seconds=3)).isoformat())
        self.spec = dict(schema='RACE_AI_NATIVE_FORWARD_STUDY_SPEC_V1',
            nonce='a'*64, source_commit=SOURCE, registration_parent_main_commit='c'*40,
            legacy_protocol_blob_sha='073379c12648064305a8b7e03dfc172d2b448f73',
            candidate_training_sha256=self.training['training_sha256'],
            candidate_context_config_sha256='1'*64, runtime_pointer_sha256='2'*64,
            registry_sha256='3'*64, window_days=7, witness_retention_days=30,
            receipt_precision_seconds=1, stage='P1',
            cells={cell:dict(model_id=cell[5:], kind='PROBABILITY',
                arm_versions=dict(baseline='0.1.0-UNTRAINED', learned=None)) for cell in CELLS},
            policy=dict(minimum_matched_races=100, minimum_days=5, minimum_venue_day_blocks=10,
                bootstrap_samples=2000, bootstrap_seed=20261103,
                metrics=['HIT_AT_8', 'MULTICLASS_BRIER', 'LOG_LOSS'],
                multiplicity='ALL_CELLS_AND_ALL_METRICS_NO_BEST_CELL_SELECTION',
                denominator='ALL_REGISTERED_SCHEDULE_RACES_WITH_MISSING_PENDING_SPECIAL_COUNTS',
                analysis='FIXED_WINDOW_END_NO_EARLY_SUPPORT', production_promoted=False))
        self.raw_spec = wire(self.spec)
        self.now = existing.NOW

    def api(self):
        self.assertIsNotNone(study, 'main-only native forward study adapter is missing')

    def resolved(self):
        return study.candidate_bindings(self.spec, self.training)

    def witness(self):
        candidate = self.resolved(); head = 'd'*40; ident = 111; artifact = 222
        summary = study.registration_summary(self.raw_spec, candidate,
            main_commit=head, main_run_id=ident, main_run_attempt=1)
        run = dict(id=ident, head_sha=head, head_branch='main', event='push', run_attempt=1,
            workflow_id=333, path='.github/workflows/boat-owner-national-p1-matrix.yml',
            name='BOAT nationally authenticated P1 matrix (no racing GET)',
            status='completed', conclusion='success', created_at='2030-04-01T08:00:00Z',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        raw = packed(dict(native_forward_study=summary, current_pair_evaluation_minimum_status='UNREGISTERED_HOLD'))
        meta = dict(id=artifact, name='boat-national-p1-model-coverage-111', expired=False,
            size_in_bytes=len(raw), digest='sha256:'+sha256(raw).hexdigest(),
            created_at='2030-04-01T08:02:00Z', expires_at='2030-05-01T08:02:00Z',
            workflow_run=dict(id=ident, head_sha=head, repository_id=1416489937, head_repository_id=1416489937))
        binding = dict(schema='RACE_AI_NATIVE_FORWARD_STUDY_WITNESS_BINDING_V1', status='BOUND',
            nonce=self.spec['nonce'], spec_sha256=sha256(self.raw_spec).hexdigest(),
            spec_git_blob_sha=sha1(f'blob {len(self.raw_spec)}\0'.encode()+self.raw_spec).hexdigest(),
            main_commit=head, main_run_id=ident, main_run_attempt=1, workflow_id=333,
            run_created_at=run['created_at'], report_artifact_id=artifact,
            report_artifact_name=meta['name'], report_artifact_digest=meta['digest'],
            report_artifact_created_at=meta['created_at'], candidate_bindings_sha256=digest(candidate))
        routes = {'actions/runs/111':wire(run), 'git/commits/'+head:wire(dict(sha=head, parents=[dict(sha='c'*40)])),
            'git/commits/'+'c'*40:wire(dict(sha='c'*40,tree=dict(sha='b'*40))),
            'git/trees/'+'b'*40+'?recursive=1':wire(dict(sha='b'*40,truncated=False,tree=[])),
            'actions/runs/111/artifacts?per_page=100':wire(dict(total_count=1, artifacts=[meta])),
            'actions/artifacts/222':wire(meta), 'actions/artifacts/222/zip':raw,
            'contents/audit/state/boat-native-forward-study.json?ref='+head:wire(dict(type='file',
                path='audit/state/boat-native-forward-study.json', encoding='base64', size=len(self.raw_spec),
                sha=binding['spec_git_blob_sha'], content=base64.b64encode(self.raw_spec).decode())),
            'actions/workflows/333/runs?branch=main&head_sha='+head+'&per_page=100':wire(dict(total_count=1, workflow_runs=[run]))}
        return binding, routes

    def packets(self):
        self.assertIn('_study_sink', __import__('inspect').signature(existing.audit.audit_current_pairs).parameters,
            'authenticated private sink is missing')
        packets = []
        self.case.audit(_study_sink=packets.append)
        self.assertEqual(len(packets), 1)
        return packets

    def test_candidate_uses_actual_model_map_exclusion_union_and_missing_learned_version(self):
        self.api(); candidate = self.resolved()
        self.assertEqual(set(candidate['models']), set(CELLS))
        for cell in CELLS:
            model = self.training['models'][cell]
            self.assertEqual(candidate['models'][cell]['model_sha256'], model['model_sha256'])
            self.assertIsNone(candidate['models'][cell]['model_version'])
            self.assertEqual(candidate['excluded_races'][cell], sorted(set(model['train_race_ids']+model['validation_race_ids'])))
        for field in ('candidate_training_sha256', 'stage'):
            changed = deepcopy(self.spec); changed[field] = 'b'*64 if field.endswith('sha256') else 'P0'
            with self.subTest(field=field), self.assertRaises(ValueError):study.candidate_bindings(changed, self.training)
        missing = deepcopy(self.training); missing['models'].pop(CELLS[1])
        with self.assertRaises(ValueError):study.candidate_bindings(self.spec, missing)

    def test_service_witness_binds_real_run_metadata_zip_nonce_and_fixed_origin(self):
        self.api(); binding, routes = self.witness()
        receipt = study.verify_registration_witness(self.raw_spec, binding, candidate=self.resolved(),
            get=routes.__getitem__, now=self.now)
        self.assertEqual(receipt['registered_after'], '2030-04-01T08:02:01+00:00')
        for field, value in [('main_commit','e'*40), ('report_artifact_id',True),
                             ('nonce','e'*64), ('report_artifact_digest','sha256:'+'e'*64)]:
            bad = dict(binding, **{field:value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                study.verify_registration_witness(self.raw_spec,bad,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        for defect in ('expired','zip','foreign_repo','attempt','earlier_success'):
            changed = deepcopy(routes)
            if defect=='expired':
                meta=json.loads(changed['actions/artifacts/222']);meta['expired']=True;changed['actions/artifacts/222']=wire(meta)
            elif defect=='zip':changed['actions/artifacts/222/zip']+=b'changed'
            elif defect in ('foreign_repo','attempt'):
                run=json.loads(changed['actions/runs/111'])
                if defect=='foreign_repo':run['head_repository']['id']=1
                else:run['run_attempt']=2
                changed['actions/runs/111']=wire(run)
            else:
                route=next(k for k in changed if k.startswith('actions/workflows/'))
                run=json.loads(changed['actions/runs/111']);older=dict(run,id=110,created_at='2030-04-01T07:59:00Z')
                changed[route]=wire(dict(total_count=2,workflow_runs=[run,older]))
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=changed.__getitem__,now=self.now)
        with self.assertRaises(ValueError):study.verify_registration_witness(self.raw_spec,binding,
            candidate=self.resolved(),get=routes.__getitem__,now=self.now+timedelta(days=31))

    def test_authenticated_sink_preserves_existing_unqualified_counts_and_private_bodies(self):
        self.api(); before=self.case.audit();packets=self.packets();after=self.case.audit()
        self.assertEqual(before,after)
        self.assertEqual(before['current_pair_evaluation_minimum_status'],'UNREGISTERED_HOLD')
        self.assertEqual(len(packets[0]['records']),2)
        self.assertIn('native_payload',packets[0]['records'][0]['payload'])
        self.assertNotIn('native_payload',wire(before).decode())

    def test_native_brier_uses_full120_and_unchanged_native_plan_scores(self):
        self.api(); packet=self.packets()[0]
        from race_ai.all_existing_model_intake import _legacy_boat
        from race_ai.all_existing_model_pdca import _score
        payload=packet['records'][0]['payload']; observation=_legacy_boat(self.case.settled)
        native={k:observation[k] for k in ('race_id','sport','status','ordered_top3','roster','captured_at',
            'source_sha256','identity_verified','payout_per_100_yen','refund_numbers')}
        before=deepcopy(payload);score=study.score_native_pair(payload,native)
        self.assertEqual(score['native'],_score(payload['pair'],native))
        for arm in ('baseline','learned'):
            ranked=payload['pair'][arm+'_normalized']['ranked']
            expected=sum((r['score']-int(r['combination']==native['ordered_top3']))**2 for r in ranked)
            self.assertAlmostEqual(score[arm]['multiclass_brier'],expected)
        self.assertEqual(payload,before)
        changed=deepcopy(payload);changed['pair']['learned_normalized']['kind']='SELECTION'
        with self.assertRaises(ValueError):study.score_native_pair(changed,native)

    def test_future_only_first_versions_and_candidate_version_or_input_changes_hold(self):
        self.api(); binding,routes=self.witness();packets=self.packets()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        checked=study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets+packets,now=self.now)
        self.assertEqual(checked['public']['matched_races_by_cell'],{cell:1 for cell in CELLS})
        self.assertEqual(checked['public']['repeat_record_count'],2)
        self.assertEqual(checked['public']['evaluation_status'],'WINDOW_OPEN_HOLD')
        old=dict(receipt,registered_after='2030-04-01T08:15:00+00:00')
        excluded=study.analyze_native_cohort(self.spec,old,self.resolved(),packets,now=self.now)
        self.assertEqual(excluded['public']['pre_registration_record_count'],2)
        self.assertEqual(excluded['public']['matched_races_by_cell'],{cell:0 for cell in CELLS})
        for defect in ('version','candidate','input','stage'):
            changed=deepcopy(packets);payload=changed[0]['records'][0]['payload']
            if defect=='version':payload['pair']['learned']['model_version']='invented'
            elif defect=='candidate':payload['pair']['model_sha256']='e'*64
            elif defect=='input':payload['pair']['input_sha256']='e'*64
            else:payload['pair']['stage']='P0'
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                study.analyze_native_cohort(self.spec,receipt,self.resolved(),changed,now=self.now)

    def test_fixed_window_statistical_rule_requires_intervals_beyond_100_5_10(self):
        self.api(); rows=[]
        for day in range(1,6):
            for venue in (1,2):
                for race in range(1,11):
                    rows.append(dict(race_id=f'203004{day:02}-{venue:02}-{race:02}',
                        baseline=dict(hit_at_8=0,multiclass_brier=1.,log_loss=2.),
                        learned=dict(hit_at_8=1,multiclass_brier=.1,log_loss=.2)))
        result=study.evaluate_cell(rows)
        self.assertEqual((result['matched_races'],result['days'],result['venue_day_blocks']),(100,5,10))
        self.assertTrue(result['statistical_rule_satisfied'])
        worse=deepcopy(rows)
        for row in worse:row['learned']['multiclass_brier']=1.1
        self.assertFalse(study.evaluate_cell(worse)['statistical_rule_satisfied'])
        self.assertFalse(study.evaluate_cell(rows[:-1])['statistical_rule_satisfied'])
        from race_ai.boat_ab_cohort import _block_bootstrap
        self.assertEqual(result['delta_hit_at_8_block95'],_block_bootstrap([1]*100,[r['race_id'][:11] for r in rows]))

    def test_registration_report_and_projection_never_leak_private_values(self):
        self.api();summary=study.registration_summary(self.raw_spec,self.resolved(),main_commit='d'*40,main_run_id=111,main_run_attempt=1)
        self.assertNotIn('excluded_races',wire(summary).decode())
        self.assertNotIn('parameters',wire(summary).decode())
        poisoned=dict(summary,private='PRIVATE_FORECAST_SENTINEL https://private.invalid/?token=sentinel')
        with self.assertRaises(ValueError):study.validate_registration_summary(poisoned,self.raw_spec,self.resolved(),
            main_commit='d'*40,main_run_id=111,main_run_attempt=1)

    def test_registered_schedule_keeps_normal_missing_forecasts_outside_matched_metrics(self):
        self.api();binding,routes=self.witness();packets=self.packets()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        pair=packets[0]['records'][0]['payload']['pair'];cutoff=pair['race_cutoff_at']
        packets[0]['schedule']=[dict(race_id=f'20300401-24-{number:02}',cutoff_at=cutoff,
            roster=deepcopy(pair['baseline_normalized']['roster'])) for number in (1,2)]
        extra=deepcopy(self.case.settled);extra['race_id']='20300401-24-02'
        extra['source_url']=extra['source_url'].replace('rno=1&','rno=2&')
        packets[0]['latest'][extra['race_id']]=extra
        checked=study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets,now=self.now)
        public=checked['public']
        self.assertIn('all_registered_normal_race_count',public,'registered missing-forecast denominator is absent')
        self.assertEqual(public['all_registered_normal_race_count'],2)
        self.assertEqual(public['matched_races_by_cell'],{cell:1 for cell in CELLS})
        self.assertEqual(public['missing_forecast_races_by_cell'],{cell:1 for cell in CELLS})
        self.assertFalse(public['official_raw_qualified'])
        self.assertEqual(public['qualifying_g8_count'],0)

    def test_oversized_report_member_is_rejected_before_any_decompression(self):
        self.api();raw=packed(dict(unbounded='x'*(2*1024*1024)))
        self.assertLess(len(raw),study.MAX_REPORT_BYTES)
        with patch.object(zipfile.ZipExtFile,'read',side_effect=AssertionError('oversized member was read')):
            try:study._report(raw)
            except ValueError:pass
            except AssertionError:self.fail('report ZIP decompressed an oversized member before enforcing its bound')
            else:self.fail('oversized report member was admitted')

    def test_missing_registered_schedule_keeps_all_race_denominator_unknown(self):
        self.api();binding,routes=self.witness()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        public=study.analyze_native_cohort(self.spec,receipt,self.resolved(),[],now=self.now)['public']
        self.assertIsNone(public['all_registered_normal_race_count'])
        self.assertEqual(public['missing_forecast_races_by_cell'],{cell:None for cell in CELLS})
        self.assertFalse(public['complete_official_ledger_verified'])

    def test_real_encrypted_unfitted_native_inputs_remain_no_forecast_evidence(self):
        self.api()
        from race_ai.all_existing_model_pairs import make_private_pairs
        seed=existing.pair_fixture.AllExistingModelPrivatePairsTests('runTest');seed.records=self.records
        output=self.case.root/'unfitted-inputs'
        requests=seed.extra_native_requests(1)
        for request in requests:
            native=request['native_payload'];native['scope']='OPERATOR_SUPPLIED_RESEARCH'
            base=native.get('source',native.get('base_source',{}))
            hashes={base.get('program_source_sha256'),base.get('beforeinfo_source_sha256')}
            if 'extra' in native:hashes.add(native['extra']['source_sha256'])
            native['source_evidence']=[dict(source_ref='https://synthetic.invalid/'+h,
                source_rights_ref='INVENTED_FIXTURE_OWNER_ANALYSIS',source_sha256=h) for h in sorted(hashes)]
        make_private_pairs(self.case.context,requests,output,
            now=existing.FORECAST_NOW+timedelta(minutes=3),allow_source=lambda *_:True)
        children=[p for p in output.iterdir() if p.is_dir()]
        raw=existing.packed({p.name+'/'+name:(p/name).read_bytes() for p in children
            for name in ('learning.json','learning.enc','summary.json')})
        self.case.add(801,'all-existing-model-pairs-99-2',raw,
            (existing.FORECAST_NOW+timedelta(minutes=3,seconds=3)).isoformat())
        binding,routes=self.witness();packets=self.packets()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        public=study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets,now=self.now)['public']
        self.assertEqual(public['no_forecast_record_count'],1)
        self.assertEqual(public['matched_races_by_cell'],{cell:1 for cell in CELLS})
        self.assertNotEqual(public['no_forecast_inventory_sha256'],digest([]))
        self.assertNotIn('captured_native_inputs',wire(public).decode())

    def test_aged_private_packets_cannot_bypass_original_native_receipt_expiry(self):
        self.api();binding,routes=self.witness();packets=self.packets()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        before=deepcopy(packets)
        with self.assertRaises(ValueError):study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets,
            now=self.now+timedelta(days=8))
        self.assertEqual(packets,before)

    def test_existing_parent_spec_or_incomplete_parent_tree_cannot_reset_registration(self):
        self.api();binding,routes=self.witness();route='git/trees/'+'b'*40+'?recursive=1'
        for defect in ('already_introduced','truncated'):
            changed=deepcopy(routes);tree=json.loads(changed[route])
            if defect=='already_introduced':tree['tree']=[dict(path=study.SPEC_PATH,mode='100644',type='blob',sha='e'*40)]
            else:tree['truncated']=True
            changed[route]=wire(tree)
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=changed.__getitem__,now=self.now)

    def test_open_window_has_no_public_or_private_support_verdict(self):
        self.api();binding,routes=self.witness();packets=self.packets()
        receipt=study.verify_registration_witness(self.raw_spec,binding,candidate=self.resolved(),get=routes.__getitem__,now=self.now)
        opened=study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets,now=self.now)
        self.assertIsNone(opened['public']['research_statistical_rule_satisfied_cell_count'])
        self.assertTrue(all(row['statistical_rule_satisfied'] is None for row in opened['private']['cells'].values()))
        ended=study._time(receipt['window_ends_at'])+timedelta(seconds=1)
        closed=study.analyze_native_cohort(self.spec,receipt,self.resolved(),packets,now=ended)
        self.assertEqual(closed['public']['research_statistical_rule_satisfied_cell_count'],0)
        self.assertTrue(all(row['statistical_rule_satisfied'] is False for row in closed['private']['cells'].values()))


class NativeForwardRuntimeTests(unittest.TestCase):
    def runtime(self):
        path=ROOT/'scripts/boat_native_forward_study_audit.py'
        self.assertTrue(path.is_file(),'trusted main-only study I/O adapter is missing')
        loader=importlib.util.spec_from_file_location('native_forward_runtime_fixture',path)
        module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
        return module

    def test_readonly_transport_rejects_provider_and_unknown_routes_before_get(self):
        runtime=self.runtime();calls=[]
        reads=runtime.StudyReads(lambda route:calls.append(route) or b'{}')
        for route in ('https://private.invalid/?token=PRIVATE_SENTINEL','actions/runs/111/rerun',
                      'git/refs/heads/main','contents/arbitrary?ref='+'d'*40):
            with self.subTest(route=route),self.assertRaises(ValueError):reads(route)
        self.assertEqual(calls,[])
        self.assertEqual(reads('actions/runs/111'),b'{}')
        self.assertEqual(reads('actions/runs/111'),b'{}')
        self.assertEqual(calls,['actions/runs/111'])

    def test_source_file_pins_are_exact_without_owner_key_access(self):
        runtime=self.runtime()
        raw=(ROOT/'audit/state/boat-native-forward-study.json').read_bytes()
        # CI keeps its separate frozen EFF reader checkout. These four source
        # files are byte-identical at S; isolate HEAD identity from file pinning.
        with patch.object(runtime,'_head',return_value=SOURCE):
            pins=runtime.verify_source_pins(ROOT/'owner-source',raw)
        self.assertEqual(pins['source_commit'],SOURCE)
        self.assertEqual(pins['runtime_pointer_sha256'],sha256((ROOT/'owner-source/audit/state/boat-model-runtime-input.json').read_bytes()).hexdigest())
        spec=study.load_spec(raw);spec['registry_sha256']='e'*64
        with patch.object(runtime,'_head',return_value=SOURCE),self.assertRaises(ValueError):
            runtime.verify_source_pins(ROOT/'owner-source',wire(spec))
        with patch.object(runtime,'_head',return_value='e'*40),self.assertRaises(ValueError):
            runtime.verify_source_pins(ROOT/'owner-source',raw)

    def test_existing_report_hook_is_fail_closed_and_preserves_current_pair_g8_fields(self):
        import textwrap
        from types import SimpleNamespace
        self.runtime()
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertIn('# NATIVE_FORWARD_STUDY_BEGIN',text,'existing report extension is missing')
        block=text.split('# NATIVE_FORWARD_STUDY_BEGIN\n',1)[1].split('# NATIVE_FORWARD_STUDY_END',1)[0]
        before=dict(current_pair_evaluation_minimum_status='UNREGISTERED_HOLD',
            current_pair_official_raw_verified=None,current_pair_qualifying_g8_count=0)
        def private(*args,**kwargs):raise ValueError('PRIVATE_SENTINEL https://private.invalid/?token=sentinel')
        for loader in (private,lambda *_:SimpleNamespace(audit_native_forward_study=private)):
            namespace=dict(report=deepcopy(before),from_exact_file=loader,repo=ROOT/'owner-source',Path=Path,
                gh=private,datetime=datetime,timezone=timezone,os=__import__('os'),pair_private=[])
            exec(textwrap.dedent(block),namespace)
            self.assertTrue(all(namespace['report'][k]==v for k,v in before.items()))
            summary=namespace['report']['native_forward_study']
            self.assertEqual(summary['registration_status'],'HOLD')
            self.assertNotIn('PRIVATE_SENTINEL',wire(summary).decode())
            self.assertNotIn('http',wire(summary).decode())

    def test_untrusted_main_identity_holds_before_any_transport_or_private_restore(self):
        runtime=self.runtime();calls=[]
        def forbidden(route):calls.append(route);raise ValueError('PRIVATE_KEY_SENTINEL https://private.invalid/')
        result=runtime.audit_native_forward_study(ROOT/'owner-source',ROOT,get=forbidden,
            now=datetime(2030,4,1,tzinfo=timezone.utc),main_identity=dict(commit='d'*40,run_id=111,attempt=1,repository='foreign/repo'))
        self.assertEqual(calls,[])
        self.assertEqual(result['registration_status'],'HOLD')
        self.assertNotIn('PRIVATE_',wire(result).decode())
        self.assertNotIn('http',wire(result).decode())
        self.assertEqual(result['source_requests'],0)

    def test_private_restore_uses_the_existing_selected_native_candidate_pointer(self):
        import os,tempfile
        from race_ai import boat_pdca_state,boat_venue_learning_handoff,boat_venue_research_runtime
        runtime=self.runtime();raw=(ROOT/'audit/state/boat-native-forward-study.json').read_bytes();calls=[]
        class BeforePrivateRead(Exception):pass
        def stop(pointer,output,repo,**kwargs):calls.append(pointer);raise BeforePrivateRead()
        with tempfile.TemporaryDirectory(prefix='native-pointer-only-fixture-') as temporary, \
                patch.dict(os.environ,GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',RUNNER_TEMP=temporary), \
                patch.object(boat_pdca_state,'state_key',return_value=existing.KEY), \
                patch.object(boat_venue_learning_handoff,'restore_learning_candidate',side_effect=stop):
            try:runtime._restore_candidate(ROOT/'owner-source',raw)
            except BeforePrivateRead:pass
            except ValueError:self.fail('private restore selected the legacy candidate namespace before authenticated readback')
            else:self.fail('fixture reached a private model read')
        self.assertEqual(calls,[boat_venue_research_runtime.RETAINED_POINTER])


if __name__=='__main__':unittest.main()
