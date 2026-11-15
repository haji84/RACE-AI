"""Invented owner decisions and races; never a provider licence claim."""
import base64,copy,os,unittest
from datetime import timedelta
from unittest.mock import patch
from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import MODEL_IDS,WEIGHTS,predict_pair
from race_ai.boat_venue_learning import fit_venue_rows,RESULT_RIGHTS
from tests.test_boat_venue_learning import venue_data,POINTER,NOW

SOURCE=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
 source_commit='a'*40,cipher_path='state/boat-pdca/v1/g000007/state.enc',cipher_sha256='c'*64,
 scope=dict(schema='RACE_AI_BOAT_PDCA_ENCRYPTED_SQLITE_V1',repository_id='1416489937',mode='production',generation=7,previous_cipher_sha256='e'*64))
CONTENT='b'*64
B_RIGHTS='OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104'

def personal_data(n):
 rows,obs=venue_data(n)
 for row in rows:
  snap=row['learning_snapshot']
  for source in snap['sources']:
   if not source['source_id'].startswith('official-venue-grid-'):
    source['source_url']='https://www.boatrace.jp/fictional/'+source['source_id']
    source['source_rights_ref']=B_RIGHTS
  suite=predict_pair(snap,allow_source=lambda *a:True);model=suite['models'][row['model_id']]
  row.update(learning_snapshot_sha256=digest(snap),model_sha256=model['prediction_sha256'],top8=model['ordered_top8'],ranked=[r['combination'] for r in model['candidates']])
 return rows,obs

def refs(rows,obs):
 return sorted({(s['source_url'],s['source_rights_ref']) for r in rows for s in r['learning_snapshot']['sources']}|{(o['source_url'],RESULT_RIGHTS) for o in obs})

class OwnerResearchTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode());self.env.start();self.addCleanup(self.env.stop)
  self.rows,self.obs=personal_data(8)

 def issue(self,**kw):
  try:from race_ai.boat_venue_research import issue_owner_research_decision
  except ModuleNotFoundError:self.fail('scoped owner personal-research decision is missing')
  args=dict(source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,source_refs=refs(self.rows,self.obs),now=NOW,expires_at=NOW+timedelta(days=30));args.update(kw)
  return issue_owner_research_decision(**args)

 def fit(self,record,**kw):
  args=dict(dataset_pointer=POINTER,source_pointer=SOURCE,state_content_sha256=CONTENT,now=NOW,owner_research_record=record);args.update(kw)
  return fit_venue_rows(self.rows,self.obs,**args)

 def test_owner_instruction_fits_existing_families_without_claiming_provider_permission(self):
  record=self.issue();before=copy.deepcopy((self.rows,self.obs,WEIGHTS,record))
  result=self.fit(record);s=result['summary'];t=result['training']
  self.assertEqual(s['state'],'FITTED_SHADOW_ONLY');self.assertEqual(t['unique_races'],8)
  self.assertEqual((t['train_races'],t['validation_races']),(6,2))
  self.assertEqual(set(t['models']),set(MODEL_IDS));self.assertTrue(any(m['coefficients_changed'] for m in t['models'].values()))
  self.assertEqual(s['training_basis'],'OWNER_PERSONAL_RESEARCH');self.assertFalse(s['provider_permission_confirmed'])
  self.assertGreater(s['unapproved_training_sources'],0);self.assertEqual(s['owner_admitted_sources'],s['unapproved_training_sources'])
  self.assertEqual(t['owner_research_decision_sha256'],digest(record));self.assertFalse(t['auto_promoted'])
  self.assertEqual((self.rows,self.obs,WEIGHTS,record),before)
  # All invented inputs are P0: unsupported exhibition weights stay baseline.
  for m in t['models'].values():self.assertEqual(m['weights'][-2:],m['base_weights'][-2:])

 def test_rejects_forged_modified_future_and_expired_decisions_before_optimizer(self):
  good=self.issue();bad=[]
  forged=copy.deepcopy(good);forged['mac']='0'*64;bad.append(forged)
  modified=copy.deepcopy(good);modified['decision']['provider_permission_confirmed']=True;bad.append(modified)
  bad.append(self.issue(now=NOW+timedelta(minutes=1)))
  bad.append(self.issue(now=NOW-timedelta(days=2),expires_at=NOW-timedelta(days=1)))
  with patch('race_ai.boat_venue_learning.fit_from_verified',side_effect=AssertionError('optimizer must not run')):
   for record in bad:
    with self.subTest(record=record['decision']['issued_at']):
     r=self.fit(record);self.assertIsNone(r['training']);self.assertEqual(r['summary']['state'],'HOLD_OWNER_RESEARCH_DECISION')

 def test_full_pointer_dataset_content_and_source_set_are_bound(self):
  good=self.issue();variants=[]
  for name in ('cipher_sha256','source_commit','scope'):
   p=copy.deepcopy(SOURCE)
   if name=='scope':p[name]['generation']=8;p['cipher_path']='state/boat-pdca/v1/g000008/state.enc'
   else:p[name]='f'*(40 if name=='source_commit' else 64)
   variants.append(dict(source_pointer=p))
  variants.append(dict(state_content_sha256='f'*64))
  dp=copy.deepcopy(POINTER);dp['source_commit']='f'*40;variants.append(dict(dataset_pointer=dp))
  with patch('race_ai.boat_venue_learning.fit_from_verified',side_effect=AssertionError('optimizer must not run')):
   for kwargs in variants:
    with self.subTest(kwargs=kwargs):
     r=self.fit(good,**kwargs);self.assertEqual(r['summary']['state'],'HOLD_OWNER_RESEARCH_DECISION');self.assertIsNone(r['training'])
  # A valid MAC for a different exact source corpus is still inadmissible.
  current=refs(self.rows,self.obs)
  for sources in (current[:-1],current+[('https://www.boatrace.jp/fictional/another-source',B_RIGHTS)]):
   r=self.fit(self.issue(source_refs=sources));self.assertEqual(r['summary']['state'],'HOLD_OWNER_RESEARCH_DECISION')

 def test_absent_owner_record_keeps_existing_hold_and_minimum_is_not_lowered(self):
  r=fit_venue_rows(self.rows,self.obs,dataset_pointer=POINTER,now=NOW)
  self.assertEqual(r['summary']['state'],'HOLD_MODEL_TRAINING_PERMISSION')
  self.rows,self.obs=personal_data(7);r=self.fit(self.issue())
  self.assertEqual(r['summary']['state'],'INSUFFICIENT_VERIFIED_RACES');self.assertEqual(r['training']['models'],{})

 def test_wrong_owner_key_rejects_the_decision(self):
  record=self.issue()
  with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()):
   self.assertEqual(self.fit(record)['summary']['state'],'HOLD_OWNER_RESEARCH_DECISION')

 def test_scoped_owner_payload_roundtrips_with_its_private_source_set(self):
  import tempfile
  from pathlib import Path
  from race_ai.boat_venue_learning import seal_candidate,read_candidate
  payload=self.fit(self.issue())
  with tempfile.TemporaryDirectory() as tmp:
   output=Path(tmp)/'owner-candidate';status=seal_candidate(payload,output)
   self.assertTrue(status['encrypted_readback_verified']);self.assertEqual(read_candidate(output),payload)

 def test_personal_record_does_not_admit_an_unreviewed_provider_or_rights_type(self):
  for source in (('https://example.org/unreviewed',B_RIGHTS),('https://www.boatrace.jp/fictional/unreviewed','unreviewed-rights')):
   with self.subTest(source=source),self.assertRaises(ValueError):self.issue(source_refs=refs(self.rows,self.obs)+[source])


class OwnerResearchCliTests(unittest.TestCase):
 setUp=OwnerResearchTests.setUp
 issue=OwnerResearchTests.issue
 def test_existing_learning_cli_verifies_owner_record_then_fits_privately(self):
  import tempfile,json,io,contextlib
  from pathlib import Path
  from scripts.boat_venue_learning import main
  from race_ai.boat_venue_learning import read_candidate
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'record.json').write_text(json.dumps(self.issue()));(root/'dataset.json').write_text(json.dumps(POINTER))
   args=['--restored-dir',str(root/'restored'),'--out-dir',str(root/'candidate'),'--dataset-input',str(root/'dataset.json'),'--owner-research-record',str(root/'record.json')]
   with patch('scripts.boat_venue_learning.load_verified_intake',return_value=(self.rows,self.obs,SOURCE,CONTENT),create=True) as load,contextlib.redirect_stdout(io.StringIO()) as stdout,contextlib.redirect_stderr(io.StringIO()):
    try:rc=main(args,now=NOW)
    except SystemExit:self.fail('learning CLI has no owner research decision route')
   self.assertEqual(rc,0);self.assertEqual(load.call_args.kwargs['authenticate_owner_cipher'],True)
   payload=read_candidate(root/'candidate');self.assertEqual(payload['training']['state'],'FITTED_SHADOW_ONLY')
   self.assertIn('OWNER_PERSONAL_RESEARCH',stdout.getvalue());self.assertNotIn('weights',stdout.getvalue())

 def test_explicit_issuer_creates_bound_record_without_overwriting_or_fitting(self):
  import tempfile,json,io,contextlib
  from pathlib import Path
  try:from scripts.boat_venue_research import main
  except ModuleNotFoundError:self.fail('explicit owner audit-record issuer is missing')
  from race_ai.boat_venue_research import verify_owner_research_decision
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'dataset.json').write_text(json.dumps(POINTER))
   args=['--restored-dir',str(root/'restored'),'--out-file',str(root/'record.json'),'--dataset-input',str(root/'dataset.json')]
   with patch('scripts.boat_venue_research.load_verified_intake',return_value=(self.rows,self.obs,SOURCE,CONTENT)),patch('race_ai.boat_venue_learning.fit_from_verified',side_effect=AssertionError('issuer must not fit')),contextlib.redirect_stdout(io.StringIO()) as stdout:
    self.assertEqual(main(args,now=NOW),0);before=(root/'record.json').read_bytes();self.assertEqual(main(args,now=NOW),2)
   self.assertEqual((root/'record.json').read_bytes(),before);record=json.loads(before)
   self.assertEqual(verify_owner_research_decision(record,source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,source_refs=refs(self.rows,self.obs),now=NOW),digest(record))
   self.assertNotIn('weights',stdout.getvalue());self.assertFalse(record['decision']['provider_permission_confirmed'])
