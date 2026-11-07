"""Invented bound inputs/labels only; no real learning permission claim."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch
from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import predict_pair,MODEL_IDS,WEIGHTS
from race_ai.boat_venue_feature_adapter import RIGHTS
from tests.test_observed_weight_learning import dataset,NOW

SHA='d'*64
POINTER=dict(schema='RACE_AI_BOAT_VENUE_DATASET_INPUT_V1',status='READY',repository_id='1416489937',
 source_commit='b'*40,dataset_sha256=SHA,dataset_path='state/boat-venue-history/v1/datasets/'+SHA+'/dataset.json')

def venue_data(n=20):
    rows,obs=dataset(n);out=[]
    for r in rows:
        r=deepcopy(r);s=r['learning_snapshot'];sid='official-venue-grid-'+SHA[:16]
        s['sources'].append(dict(source_id=sid,source_url='https://raw.githubusercontent.com/haji84/RACE-AI/'+POINTER['source_commit']+'/'+POINTER['dataset_path'],source_sha256=SHA,source_rights_ref=RIGHTS,published_at=None,captured_at=s['as_of'],evidence_basis='CAPTURED_BY_CLAIM'))
        for p in s['participants']:
            for name in ('course_mean_finish','course_mean_st'):
                if name in p['features']:p['features'][name]['source_id']=sid
        suite=predict_pair(s,allow_source=lambda *a:True);m=suite['models'][r['model_id']]
        r.update(learning_snapshot_sha256=digest(s),model_sha256=m['prediction_sha256'],original_json_sha256=digest(suite),top8=m['ordered_top8'],ranked=[v['combination'] for v in m['candidates']])
        out.append(r)
    return out,obs

class VenueLearningTests(unittest.TestCase):
    def fit(self,rows,obs,**kw):
        try:from race_ai.boat_venue_learning import fit_venue_rows
        except ModuleNotFoundError:self.fail('venue observations are not connected to the existing fitter')
        return fit_venue_rows(rows,obs,dataset_pointer=POINTER,now=NOW,**kw)

    def test_connects_existing_equations_and_preserves_baseline_and_inputs(self):
        rows,obs=venue_data();before=deepcopy((rows,obs,WEIGHTS))
        r=self.fit(rows,obs,allow_training=lambda *a:True)
        self.assertEqual(r['summary']['state'],'FITTED_SHADOW_ONLY')
        self.assertEqual(r['summary']['eligible_venue_races'],20)
        self.assertEqual(set(r['training']['models']),set(MODEL_IDS))
        self.assertTrue(any(m['coefficients_changed'] for m in r['training']['models'].values()))
        self.assertEqual((rows,obs,WEIGHTS),before)
        self.assertFalse(r['training']['auto_promoted'])

    def test_analysis_permission_does_not_admit_training_or_call_optimizer(self):
        rows,obs=venue_data()
        with patch('race_ai.boat_venue_learning.fit_from_verified',side_effect=AssertionError('must not fit')):
            r=self.fit(rows,obs,allow_training=lambda u,r,p:p=='analysis')
        self.assertEqual(r['summary']['state'],'HOLD_MODEL_TRAINING_PERMISSION')
        self.assertIsNone(r['training'])
        self.assertGreater(r['summary']['unapproved_training_sources'],0)

    def test_current_grid_does_not_backfill_old_frozen_rows(self):
        rows,obs=dataset(20);before=deepcopy(rows)
        r=self.fit(rows,obs,allow_training=lambda *a:True)
        self.assertEqual(r['summary']['eligible_venue_races'],0)
        self.assertIsNone(r['training']);self.assertEqual(rows,before)

    def test_later_nonvenue_input_is_not_replaced_by_older_venue_input(self):
        rows,obs=venue_data();later,_=dataset(20)
        for r in later:
            s=r['learning_snapshot'];s['stage']='P1';r['stage']='P1';s['as_of']=(NOW-timedelta(hours=6)+timedelta(minutes=21+int(r['artifact_id']))).isoformat();r['as_of']=s['as_of']
            from race_ai.boat_observed_pairwise_models import FEATURE_TRANSFORMS
            p=s['participants'][0];p['missing'].pop('exhibition_time_seconds',None)
            p['features']['exhibition_time_seconds']=dict(value=6.8,sample_n=None,source_id='fixture-program',transform_id=FEATURE_TRANSFORMS['exhibition_time_seconds'])
            r['server_saved_at']=(NOW-timedelta(hours=6)+timedelta(minutes=22+int(r['artifact_id']))).isoformat()
            suite=predict_pair(s,allow_source=lambda *a:True);m=suite['models'][r['model_id']]
            r.update(learning_snapshot_sha256=digest(s),model_sha256=m['prediction_sha256'],top8=m['ordered_top8'],ranked=[v['combination'] for v in m['candidates']])
        r=self.fit(rows+later,obs,allow_training=lambda *a:True)
        self.assertEqual(r['summary']['eligible_venue_races'],0)

    def test_does_not_count_two_models_as_two_labels_or_lower_minimum(self):
        rows,obs=venue_data(7);r=self.fit(rows,obs,allow_training=lambda *a:True)
        self.assertEqual(r['summary']['eligible_venue_races'],7)
        self.assertEqual(r['summary']['minimum_fit_races'],8)
        self.assertEqual(r['summary']['state'],'INSUFFICIENT_VERIFIED_RACES')
        self.assertEqual(r['training']['models'],{})

    def test_holdout_labels_do_not_fit_weights(self):
        rows,obs=venue_data();a=self.fit(rows,obs,allow_training=lambda *a:True);changed=deepcopy(obs)
        for o in changed[-5:]:o['data']['top3']=[6,5,4];o['data']['payouts'][0]['combination']=[6,5,4]
        b=self.fit(rows,changed,allow_training=lambda *a:True)
        self.assertEqual([m['weights'] for m in a['training']['models'].values()],[m['weights'] for m in b['training']['models'].values()])

    def test_bad_pin_future_capture_and_tampered_snapshot_are_rejected(self):
        rows,obs=venue_data()
        for kind in ('pin','future','tamper'):
            rs=deepcopy(rows)
            if kind=='pin':rs[0]['learning_snapshot']['sources'][-1]['source_sha256']='c'*64
            elif kind=='future':rs[0]['learning_snapshot']['sources'][-1]['captured_at']=NOW.isoformat()
            else:rs[0]['learning_snapshot']['participants'][0]['features']['course_mean_st']['value']=.9
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.fit(rs,obs,allow_training=lambda *a:True)

    def test_authenticated_policy_keeps_training_distinct_from_analysis_and_expiry(self):
        from tests.test_permissioned_source_delivery import policy_doc,KEY,AT,SRC,gate
        p=gate(policy_doc(purposes=['analysis','model_training']))
        self.assertTrue(p.authorize(SRC,'fictional-permission-1','model_training'))
        self.assertFalse(gate().authorize(SRC,'fictional-permission-1','model_training'))
        with self.assertRaises(ValueError):gate(policy_doc(purposes=['model_training'],expiry='2030-01-14T00:00:00+09:00'))

    def test_encrypted_candidate_roundtrip_preserves_training_and_detects_tampering(self):
        import os,base64,tempfile
        from pathlib import Path
        from race_ai.boat_venue_learning import seal_candidate,read_candidate
        rows,obs=venue_data();payload=self.fit(rows,obs,allow_training=lambda *a:True)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()):
            root=Path(tmp)/'candidate';r=seal_candidate(payload,root)
            self.assertEqual(read_candidate(root),payload);self.assertFalse(r['plaintext_published'])
            self.assertNotIn(b'FITTED_SHADOW_ONLY',(root/'learning.enc').read_bytes())
            with self.assertRaises(ValueError):seal_candidate(payload,root)
            (root/'learning.enc').write_bytes((root/'learning.enc').read_bytes()+b'bad')
            with self.assertRaises(ValueError):read_candidate(root)

class JournalLearningTests(unittest.TestCase):
    def test_external_receipt_bridge_keeps_git_receipts_distinct_from_artifact_ids(self):
        import tempfile
        from pathlib import Path
        from tests import test_boat_history_prospective as fixture
        from race_ai.boat_pdca_state import PdcaState
        from race_ai.boat_history_store import wire
        from tests.test_boat_pdca_state import result
        from race_ai.boat_venue_learning import rows_from_journal
        f=fixture.ProspectiveHistoryTests();f.setUp()
        try:
            state=PdcaState.create(f.root/'learning-journal.sqlite',mode='production');self.addCleanup(state.close)
            state.retain_pair(f.path);obs=result(f.pair);state.score(f.pair['pair_sha256'],obs,'2026-11-06T12:00:00+09:00')
            with state.db:state._put('prospective-admissions/'+f.pair['pair_sha256']+'.json',wire(f.admit()).encode())
            state.materialize(f.root/'learning-source');before=state.content_sha256()
            rows,observations=rows_from_journal(state,f.root/'learning-source',now='2026-11-06T12:00:00+09:00',_fetch=f.fetch)
            self.assertEqual(len(rows),2);self.assertEqual(len(observations),1)
            self.assertTrue(all(r['artifact_id'] is None and r['input_receipt']['run_id']==9001 for r in rows))
            self.assertEqual(rows[0]['server_saved_at'],f.run['created_at'])
            self.assertEqual(state.content_sha256(),before)
            f.run['created_at']='2026-11-06T03:00:00Z'
            with self.assertRaises(ValueError):rows_from_journal(state,f.root/'learning-source',now='2026-11-06T12:00:00+09:00',_fetch=f.fetch)
        finally:f.doCleanups()

class LearningCliTests(unittest.TestCase):
    def test_missing_owner_key_holds_without_reading_or_fetching(self):
        import os,contextlib,io,tempfile
        from scripts.boat_venue_learning import main
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,RACE_AI_STATE_KEY=''),patch('race_ai.boat_venue_learning.rows_from_journal',side_effect=AssertionError('no fetch')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--restored-dir','/missing','--out-dir',tmp+'/candidate']),0)
        self.assertIn('HOLD_OWNER_STATE_KEY_MISSING',out.getvalue())

    def test_cli_connects_encrypted_candidate_to_existing_future_shadow_contract(self):
        import os,base64,tempfile,json,hmac,hashlib,contextlib,io
        from pathlib import Path
        from race_ai.boat_pdca_state import PdcaState
        from race_ai.permissioned_source_delivery import POLICY_SCHEMA
        from race_ai.boat_venue_learning import read_candidate,RESULT_RIGHTS
        from race_ai.observed_weight_learning import make_shadows
        from scripts.boat_venue_learning import main
        from tests.test_observed_weight_learning import LearningTests
        rows,obs=venue_data();review_key='fictional independent reviewer key only for synthetic tests'
        sources={(s['source_url'],s['source_rights_ref']) for r in rows for s in r['learning_snapshot']['sources']}
        sources.update((o['source_url'],RESULT_RIGHTS) for o in obs)
        grants=[dict(source_ref=u,rights_ref=r,transport_url=u,purposes=['model_training'],evidence_url='https://example.org/fictional-training-rights',reviewer='FICTIONAL',checked_at='2030-01-01T00:00:00Z',expires_at='2030-05-01T00:00:00Z',max_bytes=2000000,max_requests=1,max_cost_jpy=0) for u,r in sources]
        policy=dict(authority='SYNTHETIC_ONLY',grants=grants)
        document=dict(schema=POLICY_SCHEMA,policy=policy,signature=hmac.new(review_key.encode(),digest(policy).encode(),hashlib.sha256).hexdigest())
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode(),RACE_AI_SOURCE_REVIEW_KEY=review_key):
            root=Path(tmp);restored=root/'restored';restored.mkdir(mode=0o700)
            s=PdcaState.create(restored/'state.sqlite',mode='production');ident=s.content_sha256();s.close()
            state_pointer=dict(source_commit='a'*40)
            (root/'state.json').write_text(json.dumps(state_pointer));(root/'dataset.json').write_text(json.dumps(POINTER));(root/'policy.json').write_text(json.dumps(document))
            (restored/'production-readback-status.json').write_text(json.dumps(dict(production_schema_readback_verified=True,source_commit='a'*40,state_content_sha256=ident)))
            args=['--restored-dir',str(restored),'--out-dir',str(root/'candidate'),'--state-input',str(root/'state.json'),'--dataset-input',str(root/'dataset.json'),'--permission-policy',str(root/'policy.json')]
            with patch('scripts.boat_venue_learning.rows_from_journal',return_value=(rows,obs)),contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main(args,now=NOW),0)
            self.assertNotIn('weights',stdout.getvalue());self.assertNotIn('learning_snapshot',stdout.getvalue())
            trained=read_candidate(root/'candidate')['training'];fixture=LearningTests();snap,suite=fixture.future();receipt=fixture.context()['receipt']
            self.assertEqual(len(make_shadows(snap,suite,dict(training=trained,receipt=receipt))),2)
            # A changed readback identity must stop before another fitting run.
            state_pointer['source_commit']='b'*40;(root/'state.json').write_text(json.dumps(state_pointer))
            with contextlib.redirect_stdout(io.StringIO()) as error:self.assertEqual(main(args,now=NOW),2)
            self.assertIn('VENUE_LEARNING_READBACK_BINDING',error.getvalue())
            # An expired signed review is an explicit, persisted rights HOLD.
            state_pointer['source_commit']='a'*40;(root/'state.json').write_text(json.dumps(state_pointer))
            for g in document['policy']['grants']:g['expires_at']='2030-03-01T00:00:00Z'
            document['signature']=hmac.new(review_key.encode(),digest(document['policy']).encode(),hashlib.sha256).hexdigest()
            (root/'policy.json').write_text(json.dumps(document));args[3]=str(root/'held-candidate')
            with patch('scripts.boat_venue_learning.rows_from_journal',return_value=(rows,obs)),patch('race_ai.boat_venue_learning.fit_from_verified',side_effect=AssertionError('no optimizer')),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args,now=NOW),0)
            held=read_candidate(root/'held-candidate')
            self.assertIsNone(held['training']);self.assertEqual(held['summary']['state'],'HOLD_MODEL_TRAINING_PERMISSION')
            self.assertEqual(held['summary']['permission_review_reason'],'SOURCE_GRANT_NOT_CURRENTLY_EFFECTIVE')
