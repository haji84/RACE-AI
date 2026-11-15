"""Saved native forecasts append across days without replacing originals."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai.boat_pdca_state import PdcaState
from race_ai.boat_pdca_projection import project_pdca

class IntakeTests(unittest.TestCase):
 def setUp(self):
  from race_ai import boat_saved_view_intake as M
  self.m=M;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  path,_=invented_research_state(Path(tmp.name));s=PdcaState(path)
  try:self.base=project_pdca(s)
  finally:s.close()
 def test_duplicate_native_archive_is_kept_once_and_original_metadata_is_preserved(self):
  incoming=deepcopy(self.base)
  for r in incoming['records']:
   for p in [r['prediction'],*r['comparison_predictions']]:
    p.update(artifact_id=123,original_json_sha256='a'*64)
  first=self.m.append_views(self.base,[incoming]);second=self.m.append_views(first,[incoming])
  self.assertEqual(first['records'],second['records'])
  self.assertEqual(first['records'][0]['prediction'],self.base['records'][0]['prediction'])
 def test_receipt_match_does_not_hide_changed_saved_tickets(self):
  original=deepcopy(self.base)
  original['records'][0]['prediction'].update(artifact_id=123,original_json_sha256='a'*64)
  incoming=deepcopy(original);incoming['records'][0]['prediction']['ordered_top8'].reverse()
  with self.assertRaises(ValueError):self.m.append_views(original,[incoming])
 def test_dispatch_reuse_keeps_the_already_saved_archive_byte_hash(self):
  original=deepcopy(self.base)
  p=original['records'][0]['prediction'];p.update(artifact_id=123,original_json_sha256='a'*64)
  incoming=deepcopy(original);q=incoming['records'][0]['prediction']
  q.update(dispatch_status='ORIGINAL_REUSED',original_json_sha256='b'*64)
  merged=self.m.append_views(original,[incoming]);self.assertEqual(merged['records'][0]['prediction'],p)
  q['as_of']='2026-11-06T01:00:00Z'
  with self.assertRaises(ValueError):self.m.append_views(original,[incoming])
 def test_new_day_and_names_do_not_change_the_original_anchor(self):
  new=deepcopy(self.base);new['event_date_jst']=None
  r=new['records'][0];r['event_date_jst']='2026-11-07';r['race_id']=r['race_id'].replace('20261106','20261107')
  r['result']=None;r['result_observations']=[];r['result_observation_rejections']=[]
  r['cutoff_at']=r['cutoff_at'].replace('2026-11-06','2026-11-07')
  for p in [r['prediction'],*r['comparison_predictions']]:
   for k in ('as_of','generated_at','persisted_at','cutoff_at','source_captured_at','server_saved_at'):
    if p.get(k):p[k]=p[k].replace('2026-11-06','2026-11-07')
  from race_ai.saved_view_feed import originals_sha,ensure_append_only
  result=self.m.append_views(self.base,[new]);self.assertIsNone(result['event_date_jst'])
  self.assertEqual(result['forecast_base_sha256'],originals_sha(self.base));ensure_append_only(self.base,result)
