"""Invented originals: append-only authenticated live view evolution."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from race_ai.boat_pdca_state import PdcaState
from race_ai.boat_pdca_projection import project_pdca
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai import saved_view_feed as F

class EvolutionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  p,_=invented_research_state(Path(self.tmp.name));self.state_path=p;s=PdcaState(p)
  try:self.base=project_pdca(s)
  finally:s.close()
 def addition(self):
  out=deepcopy(self.base);out['forecast_base_sha256']=F.originals_sha(self.base)
  p=deepcopy(out['records'][0]['prediction']);p.update(model_id='boat-comprehensive-v1',model_version='sparse-test',stage='P1')
  out['records'][0]['comparison_predictions'].append(p);return out
 def test_append_can_add_model_and_enrich_name_without_editing_an_original(self):
  new=self.addition();new['records'][0]['participants'][0]['name']='架空選手一'
  F.ensure_append_only(self.base,new)
  self.assertEqual(len(F.forecast_inventory(new)),len(F.forecast_inventory(self.base))+1)
 def test_removing_or_replacing_an_old_prediction_is_rejected(self):
  for change in ('remove','replace','cutoff'):
   with self.subTest(change=change):
    new=self.addition()
    if change=='remove':new['records'][0]['comparison_predictions'].pop(0)
    elif change=='replace':new['records'][0]['prediction']['ordered_top8']=list(reversed(new['records'][0]['prediction']['ordered_top8']))
    else:new['records'][0]['prediction']['cutoff_at']='2026-11-06T10:58:00+09:00'
    with self.assertRaises(ValueError):F.ensure_append_only(self.base,new)
 def test_authenticated_v4_preserves_original_anchor_and_seals_new_inventory(self):
  new=self.addition();raw=F.encrypt_view(new,b'k'*32,view_id='a'*64,source_sha='b'*64,generation=3,previous='c'*64)
  h,decoded=F.decrypt_view(raw,b'k'*32,view_id='a'*64)
  self.assertEqual(h['schema'],'RACE_AI_SAVED_WEB_VIEW_V4')
  self.assertEqual(h['forecast_sha256'],F.originals_sha(self.base));self.assertEqual(decoded,new)
  self.assertEqual(h['forecast_inventory_sha256'],F.inventory_sha(new))
 def test_site_builder_unifies_saved_views_and_names_with_the_original_anchor(self):
  from race_ai.saved_pages import build_site,_viewer
  root=Path(self.tmp.name);state=self.state_path
  s=PdcaState(state)
  try:pin=s.content_sha256()
  finally:s.close()
  addition=self.addition();addition.pop('forecast_base_sha256')
  report=build_site(state,root/'public',root/'private',expected_source_sha256=pin,extra_views=[addition])
  key,vid=_viewer(root/'private/viewer.json')
  _,view=F.decrypt_view((root/'public'/report['cipher_path']).read_bytes(),key,view_id=vid)
  self.assertEqual(len(F.forecast_inventory(view)),5)
  self.assertEqual(report['forecast_sha256'],F.originals_sha(self.base))

if __name__=='__main__':unittest.main()
