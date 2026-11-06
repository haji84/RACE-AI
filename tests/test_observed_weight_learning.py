"""Fictional evidence only; verifies learning and temporal isolation, not accuracy."""
import copy, hashlib, io, json, tempfile, unittest, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import predict_pair, MODEL_IDS, WEIGHTS
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_frozen_day_cycle import observation
from race_ai import frozen_day_cycle as frozen
try:
    from race_ai import observed_weight_learning as learning
except ImportError:
    learning = None

NOW = datetime(2030,4,1,8,tzinfo=timezone.utc)

def dataset(count=20):
    rows=[]; results=[]
    for i in range(count):
        snap=fixture(research=True)
        venue=f'{1+i//12:02d}'; number=i%12+1
        snap.update(race_id=f'boat:2030-04-01:boatrace-jcd-{venue}:{number}',venue='boatrace-jcd-'+venue,
                    as_of=(NOW-timedelta(hours=6)+timedelta(minutes=i)).isoformat(),
                    sales_cutoff_at=(NOW-timedelta(hours=5)+timedelta(minutes=i)).isoformat())
        for source in snap['sources']:
            source['captured_at']=snap['as_of']
            if source['published_at'] is not None: source['published_at']=snap['as_of']
        suite=predict_pair(snap,allow_source=lambda *_:True)
        rid=f'20300401-{venue}-{number:02d}'
        pair=[]
        for mid,m in suite['models'].items():
            pair.append(dict(race_id=rid,sport='boat',stage=snap['stage'],model_id=mid,as_of=snap['as_of'],cutoff_at=snap['sales_cutoff_at'],
                server_saved_at=(frozen.ts(snap['as_of'])+timedelta(seconds=2)).isoformat(),artifact_id=i+1,
                original_json_sha256=digest(suite),model_sha256=m['prediction_sha256'],
                roster={str(p['lane']):p['registration_no'] for p in snap['participants']},
                top8=m['ordered_top8'],ranked=[x['combination'] for x in m['candidates']],calibrated=False,
                learning_snapshot=snap,learning_snapshot_sha256=digest(snap)))
        obs=observation(pair[0]);obs['captured_at']=(frozen.ts(snap['sales_cutoff_at'])+timedelta(minutes=1)).isoformat()
        obs['source_sha256']=hashlib.sha256(str(i).encode()).hexdigest()
        obs['source_url']=f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20300401&jcd={venue}&rno={number}'
        rows+=pair;results.append(obs)
    return rows,results

class LearningTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(learning,'automatic fitting connection missing')
    def test_actual_coefficients_fitted_baseline_unchanged_and_unique_labels(self):
        rows,obs=dataset();before=copy.deepcopy((rows,obs,WEIGHTS))
        out=learning.fit_from_verified(rows,obs,now=NOW)
        self.assertEqual(out['state'],'FITTED_SHADOW_ONLY')
        self.assertEqual(out['unique_races'],20)
        self.assertEqual(out['train_races'],15);self.assertEqual(out['validation_races'],5)
        self.assertFalse(out['auto_promoted']); self.assertFalse(out['accuracy_improvement_proven'])
        self.assertEqual(set(out['models']),set(MODEL_IDS))
        self.assertTrue(any(out['models'][mid]['weights']!=list(WEIGHTS[mid]) for mid in MODEL_IDS))
        self.assertEqual((rows,obs,WEIGHTS),before)
    def test_holdout_labels_never_change_fitted_weights(self):
        rows,obs=dataset();a=learning.fit_from_verified(rows,obs,now=NOW)
        obs2=copy.deepcopy(obs)
        for o in obs2[-5:]:
            win=[6,5,4];o['data']['top3']=win;o['data']['payouts'][0]['combination']=win
        b=learning.fit_from_verified(rows,obs2,now=NOW)
        for mid in MODEL_IDS:self.assertEqual(a['models'][mid]['weights'],b['models'][mid]['weights'])
    def test_future_unconfirmed_refund_and_wrong_roster_excluded(self):
        rows,obs=dataset();obs[0]['captured_at']=(NOW+timedelta(seconds=1)).isoformat()
        obs[1]['data']['refund_boats']=[1];obs[2]['data']['results'][0]['racer_registration_id']='9999'
        obs[3]['status']='PENDING'
        out=learning.fit_from_verified(rows,obs,now=NOW)
        self.assertEqual(out['unique_races'],16)
        self.assertEqual(len(out['excluded_races']),4)
    def test_insufficient_data_is_not_fitted_or_promoted(self):
        rows,obs=dataset(3);out=learning.fit_from_verified(rows,obs,now=NOW)
        self.assertEqual(out['state'],'INSUFFICIENT_VERIFIED_RACES'); self.assertEqual(out['models'],{})
    def test_tampered_snapshot_does_not_become_training_data(self):
        rows,obs=dataset();rows[0]['learning_snapshot']['race_id']='boat:2030-04-01:boatrace-jcd-24:12'
        with self.assertRaises(ValueError):learning.fit_from_verified(rows,obs,now=NOW)
    def test_unobserved_features_remain_original_weights(self):
        rows,obs=dataset()
        for row in rows:
            row['learning_snapshot']=copy.deepcopy(row['learning_snapshot'])
            for p in row['learning_snapshot']['participants']:
                if 'course_mean_finish' in p['features']:del p['features']['course_mean_finish']
                p['missing']['course_mean_finish']='NO_PRIOR_SAMPLES'
            row['learning_snapshot_sha256']=digest(row['learning_snapshot'])
        out=learning.fit_from_verified(rows,obs,now=NOW)
        for mid in MODEL_IDS:self.assertEqual(out['models'][mid]['weights'][3],WEIGHTS[mid][3])
    def future(self):
        snap=fixture(research=True);snap.update(race_id='boat:2030-04-01:boatrace-jcd-24:12',venue='boatrace-jcd-24',
            as_of=(NOW+timedelta(minutes=10)).isoformat(),sales_cutoff_at=(NOW+timedelta(minutes=30)).isoformat())
        for s in snap['sources']:
            s['captured_at']=snap['as_of']
            if s['published_at'] is not None:s['published_at']=snap['as_of']
        return snap,predict_pair(snap,allow_source=lambda *_:True)
    def context(self):
        rows,obs=dataset();model=learning.fit_from_verified(rows,obs,now=NOW)
        return dict(training=model,receipt=dict(id=700,created_at=(NOW+timedelta(seconds=2)).isoformat(),
            name='race-existing-cycle-99',digest='sha256:'+'a'*64,expired=False,
            workflow_run={'id':99,'head_repository_id':1416489937}))
    def test_shadow_requires_frozen_model_before_future_input(self):
        snap,suite=self.future();context=self.context()
        out=learning.make_shadows(snap,suite,context)
        self.assertEqual(len(out),2);self.assertTrue(all(x['variant']=='LEARNED_SHADOW' for x in out))
        self.assertTrue(all(len(x['candidates'])==120 and len(x['ordered_top8'])==8 for x in out))
        context['receipt']['created_at']=snap['as_of']
        with self.assertRaises(ValueError):learning.make_shadows(snap,suite,context)
    def test_training_hash_mutation_rejected(self):
        snap,suite=self.future();context=self.context();context['training']['models'][MODEL_IDS[0]]['weights'][0]+=1
        with self.assertRaises(ValueError):learning.make_shadows(snap,suite,context)
    def test_target_race_training_rejected(self):
        rows,obs=dataset();context=self.context();snap=rows[0]['learning_snapshot']
        with self.assertRaises(ValueError):learning.make_shadows(snap,predict_pair(snap,allow_source=lambda *_:True),context)
    def test_read_p0_reconstructs_bound_snapshot(self):
        from tests.test_frozen_day_cycle import sample
        _,raw,receipt=sample();doc,rows=frozen.read_p0(raw,receipt,expected_day='2030-04-01')
        enriched=learning.attach_snapshots(doc,rows)
        self.assertEqual(digest(enriched[0]['learning_snapshot']),doc['predictions'][0]['snapshot_sha256'])
        self.assertNotIn('learning_snapshot',rows[0])

class ContinuityAndCoverage(unittest.TestCase):
    def test_current_session_does_not_stop_before_hourly_trigger(self):
        from race_ai import repeated_cycle as r
        with tempfile.TemporaryDirectory() as temp:
            start=datetime(2030,4,1,3,57,tzinfo=timezone.utc)
            s=r.start(Path(temp)/'s.json',day='2030-04-01',run_id=99,now=start)
            self.assertIsNone(s['stop_at'])
            self.assertIsNone(s['max_rounds'])
            self.assertIsNone(r.SOURCE_LIMIT)
            self.assertTrue(r.prepare(Path(temp)/'s.json',1,now=start+timedelta(hours=1))['active'])
    def test_ended_races_with_missing_models_are_counted(self):
        self.assertIsNotNone(learning,'coverage implementation missing')
        rows,obs=dataset(2)
        schedule=[dict(race_id=r['race_id'],cutoff_at=r['cutoff_at']) for r in rows[::2]]
        x=learning.coverage_audit(rows,schedule,now=NOW)
        self.assertEqual(x['ended_races'],2);self.assertEqual(x['complete_five_model_p1'],0)
        self.assertEqual(x['missing_p1_model_predictions'],10)
        self.assertFalse(x['zero_misses_proven'])

class LearningWireTests(unittest.TestCase):
    def test_all_rounds_have_credential_context_and_single_concurrency(self):
        import re
        wf=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text()
        rounds=[s for s in re.split(r'(?m)^      - name:',wf)
                if 'uses: ./.github/actions/existing-model-round' in s]
        self.assertEqual(len(rounds),24)
        for s in rounds:self.assertIn("env: {GH_TOKEN: '${{ github.token }}'}",s)
        self.assertIn('  cancel-in-progress: false',wf)
    def test_learned_prediction_can_roundtrip_and_pair_without_inflating_baseline(self):
        self.assertIsNotNone(learning)
        helper=LearningTests();context=helper.context();snap,suite=helper.future()
        # Future synthetic standalone P0 does not make a real forecast receipt.
        shadow=learning.make_shadows(snap,suite,context)
        self.assertEqual({s['model_id'] for s in shadow},set(MODEL_IDS))
        self.assertTrue(all(s['baseline_model_sha256']==suite['models'][s['model_id']]['prediction_sha256'] for s in shadow))
    def test_training_artifact_cannot_cross_into_synthetic_scope(self):
        self.assertIsNotNone(learning)
        helper=LearningTests();context=helper.context();snap,_=helper.future();snap['scope']='SYNTHETIC_ONLY'
        suite=predict_pair(snap)
        with self.assertRaises(ValueError):learning.make_shadows(snap,suite,context)

class TrainingProofTests(unittest.TestCase):
    def test_shadow_training_needs_matching_independently_verified_receipt(self):
        self.assertIsNotNone(learning)
        self.assertTrue(hasattr(learning,'validate_shadow_training'),'independent training-receipt chain missing')
        row=dict(training_artifact_id=700,training_sha256='b'*64,training_receipt_digest='sha256:'+'a'*64)
        with self.assertRaises(ValueError):learning.validate_shadow_training([row],{})
        learning.validate_shadow_training([row],{'700':dict(training_sha256='b'*64,digest='sha256:'+'a'*64)})
        with self.assertRaises(ValueError):learning.validate_shadow_training([row],{'700':dict(training_sha256='c'*64,digest='sha256:'+'a'*64)})
    def test_saved_training_artifact_readback_is_required(self):
        helper=LearningTests();context=helper.context();training=context['training']
        report={'automatic_learning':{'training_sha256':training['training_sha256']}}
        report['report_sha256']=digest(report)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('trained_observed_models.json',json.dumps(training));z.writestr('status.json',json.dumps(report))
        body=raw.getvalue();receipt=context['receipt'];receipt['digest']='sha256:'+hashlib.sha256(body).hexdigest()
        out=learning.context_from_result_archive(body,receipt)
        self.assertEqual(out['training'],training)
        with self.assertRaises(ValueError):learning.context_from_result_archive(body+b'changed',receipt)

class LearnedShadowRoundtrip(unittest.TestCase):
    def test_five_baselines_plus_two_learned_versions_keep_separate_scores(self):
        from tests.test_observed_p1_connection import inputs,archive,bridge
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        b,e,p=inputs();rid='20300401-24-12';b['race_id']=rid;e['race_id']=rid
        at=(NOW+timedelta(minutes=10)).isoformat();before=(NOW+timedelta(minutes=9)).isoformat()
        b['cutoff_at']=(NOW+timedelta(minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat();b['captured_at']=before;e['observed_at']=before
        p.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(),preview_captured_at=before)
        for k in ('program_url','preview_url'):p[k]=p[k].replace('jcd=01','jcd=24').replace('rno=1','rno=12')
        bundle=bridge.build_bundle(b,e,at,**p,owner_reviewed=True);context=LearningTests().context()
        shadows=learning.make_shadows(bundle['snapshot'],bundle['suite'],context)
        doc=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[build_pair(b,at)],
                 additional_official_feature_shadows=[build_live_feature_shadow(b,e,at)],
                 observed_pairwise_p1_bundles=[bundle],learned_pairwise_shadows=shadows)
        raw,meta=archive(doc,saved=(NOW+timedelta(minutes=11)).isoformat())
        parsed,baseline=frozen.read_p1(raw,meta);candidates=learning.read_shadow_rows(parsed,meta,baseline)
        self.assertEqual(len(baseline),5);self.assertEqual(len(candidates),2)
        proof={'700':learning.training_proof(context)};learning.validate_shadow_training(candidates,proof)
        outcome=observation(baseline[3]);outcome['captured_at']=(NOW+timedelta(minutes=40)).isoformat()
        scored=learning.score_shadows(candidates,baseline,[outcome])
        self.assertEqual(scored['paired_forecasts'],2);self.assertFalse(scored['auto_promoted'])
        self.assertEqual(frozen.evaluate(baseline,[outcome])['forecast_count'],5)
        self.assertEqual(learning.merge_shadow_rows(candidates+candidates),candidates)
        # Restore parameters, candidate receipts and outcomes in a later run.
        from race_ai.cycle_recovery import recover,WORKFLOW,BRANCH
        report={'automatic_learning':{'training_sha256':context['training']['training_sha256']}}
        report['report_sha256']=digest(report)
        zbuf=io.BytesIO()
        with zipfile.ZipFile(zbuf,'w') as z:
            z.writestr('status.json',json.dumps(report))
            z.writestr('trained_observed_models.json',json.dumps(context['training']))
            z.writestr('official-result-observations.json','[]')
        result_raw=zbuf.getvalue();training_meta=copy.deepcopy(context['receipt'])
        training_meta['digest']='sha256:'+hashlib.sha256(result_raw).hexdigest()
        # Rebind the fictional receipt before freezing this test's P1 archive.
        context['receipt']=training_meta
        doc['learned_pairwise_shadows']=learning.make_shadows(bundle['snapshot'],bundle['suite'],context)
        raw,meta=archive(doc,saved=(NOW+timedelta(minutes=11)).isoformat())
        records={f'actions/workflows/{WORKFLOW}/runs?per_page=100&page=1':json.dumps({'workflow_runs':[dict(id=99,status='completed',event='push',head_branch=BRANCH,created_at='2030-04-01T01:00:00Z')]}).encode(),
          'actions/runs/99/artifacts?per_page=100':json.dumps({'total_count':2,'artifacts':[meta,training_meta]}).encode(),
          f'actions/artifacts/{meta["id"]}':json.dumps(meta).encode(),f'actions/artifacts/{meta["id"]}/zip':raw,
          'actions/artifacts/700':json.dumps(training_meta).encode(),'actions/artifacts/700/zip':result_raw}
        with tempfile.TemporaryDirectory() as tmp:
            recovered=recover(lambda url:records[url],'2030-04-01',current_run=100,out=Path(tmp),
                              clock=lambda:NOW+timedelta(minutes=20))
            self.assertEqual(len(recovered['rows']),5);self.assertEqual(len(recovered['learning_shadows']),2)
            self.assertEqual(recovered['learning_context']['training']['training_sha256'],context['training']['training_sha256'])
