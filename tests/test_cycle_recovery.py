import copy,hashlib,io,json,unittest,zipfile
from datetime import datetime,timezone
try:
 from race_ai import cycle_recovery as r
except ImportError:
 r=None
from tests.test_frozen_day_cycle import sample,observation
from race_ai.frozen_day_cycle import read_p0

class RecoveryTests(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(r,'cycle recovery is not connected')
 def test_result_archive_is_authenticated_bounded_and_day_scoped(self):
  _,z,m=sample();_,rows=read_p0(z,m,expected_day='2030-04-01');o=observation(rows[0]);b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as f:f.writestr('official-result-observations.json',json.dumps([o]))
  raw=b.getvalue();meta={'id':8,'expired':False,'name':'race-existing-cycle-9','digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'workflow_run':{'id':9,'head_repository_id':1416489937}}
  self.assertEqual(r.result_archive(raw,meta,'2030-04-01'),[o])
  with self.assertRaises(ValueError):r.result_archive(raw+b'bad',meta,'2030-04-01')
  with self.assertRaises(ValueError):r.result_archive(raw,meta,'2030-04-02')
 def test_pending_new_races_before_settled_recheck_and_budget(self):
  _,z,m=sample();_,rows=read_p0(z,m,expected_day='2030-04-01');x=rows[0];y=copy.deepcopy(x);y['race_id']='20300401-01-02'
  obs=observation(x);now=datetime.fromisoformat('2030-04-01T02:20:00+00:00')
  self.assertEqual([v['race_id'] for v in r.due_rows([x,y],[obs],now,limit=1)],[y['race_id']])
  self.assertEqual(r.due_rows([x],[obs],now),[])
 def test_poll_cooldown_and_ended_only(self):
  _,z,m=sample();_,rows=read_p0(z,m,expected_day='2030-04-01');x=rows[0];now=datetime.fromisoformat('2030-04-01T02:10:10+00:00')
  obs=observation(x);obs['status']='NOT_AVAILABLE';obs['data']=None
  self.assertEqual(r.due_rows([x],[obs],now),[])
  self.assertEqual(r.due_rows([x],[],datetime.fromisoformat('2030-04-01T01:50:00+00:00')),[])
 def test_run_page_selection_rejects_missing_pagination_and_old_day(self):
  calls=[]
  def fake(path):
   calls.append(path)
   return json.dumps({'workflow_runs':[{'id':8,'created_at':'2030-04-01T00:00:00Z','head_branch':r.BRANCH,'status':'completed','event':'push'}, {'id':9,'created_at':'2030-04-01T01:00:00Z','head_branch':r.BRANCH,'status':'in_progress','event':'push'}]}).encode()
  selected=r.day_runs(fake,'2030-04-01',current_run=9)
  self.assertEqual([v['id'] for v in selected],[8]);self.assertEqual(len(calls),1)
 def test_unresolved_previous_run_stops_before_any_prediction(self):
  def fake(path):return json.dumps({'workflow_runs':[{'id':8,'created_at':'2030-04-01T00:00:00Z','head_branch':r.BRANCH,'status':'in_progress','event':'push'}]}).encode()
  with self.assertRaisesRegex(ValueError,'UNRESOLVED'):r.day_runs(fake,'2030-04-01',current_run=9)


class EmptyAttemptTests(unittest.TestCase):
 def archive(self,doc):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('forecasts.json',json.dumps(doc))
  raw=b.getvalue();m={'id':10,'expired':False,'created_at':'2030-04-01T01:00:00Z','name':'boat-p0-existing-9','digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'workflow_run':{'id':9,'head_repository_id':1416489937}}
  return raw,m
 def test_legacy_empty_attempt_is_not_a_forecast(self):
  doc=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst='2030-04-01',predictions=[],actual_purchases=False,state='SOURCE_OR_MODEL_BLOCKED',reason='source parse failed')
  raw,meta=self.archive(doc)
  parsed,rows=r.p0_original_or_empty(raw,meta,'2030-04-01')
  self.assertEqual(parsed,doc);self.assertEqual(rows,[])
  with self.assertRaises(ValueError):r.p0_original_or_empty(raw+b'x',meta,'2030-04-01')
 def test_nonzero_declaration_or_any_predictions_cannot_be_silently_dropped(self):
  doc=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst='2030-04-01',predictions=[],actual_purchases=False,state='SOURCE_OR_MODEL_BLOCKED',race_count=2)
  raw,m=self.archive(doc)
  with self.assertRaises(ValueError):r.p0_original_or_empty(raw,m,'2030-04-01')
  doc['race_count']=None;doc['predictions']=[{}];raw,m=self.archive(doc)
  with self.assertRaises(ValueError):r.p0_original_or_empty(raw,m,'2030-04-01')
