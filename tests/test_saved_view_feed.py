"""Invented display data; no live HTTP or owner secrets."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from race_ai.boat_pdca_projection import project_pdca
from race_ai.boat_pdca_recipient import receiver_document
from race_ai.boat_pdca_state import PdcaState
from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_boat_pdca_state import result
try:
 from race_ai import saved_view_feed as F
except ImportError:
 F=None

class FeedTests(unittest.TestCase):
 def test_feed_exists(self):self.assertIsNotNone(F,'automatic saved result feed is missing')
 def test_display_runs_do_not_look_like_source_writers_or_source_checkpoints(self):
  from unittest.mock import patch
  from race_ai.github_continuous_supervisor import GitHubCLI,WORKFLOW,BRANCH
  source=dict(id=11,workflow_id=WORKFLOW,head_branch=BRANCH,event='push',display_title='existing source',head_commit={'message':'existing source'})
  display={**source,'id':12,'display_title':'saved-view: publish','head_commit':{'message':'saved-view: publish'}}
  api=GitHubCLI()
  with patch.object(api,'api',side_effect=lambda path:{'workflow_runs':[display,source]}):
   self.assertEqual([r['id'] for r in api.active_runs()],[11])
   self.assertEqual(api.latest_run()['id'],11)
 def test_display_only_prior_run_does_not_block_source_recovery(self):
  import json
  from race_ai.cycle_recovery import _previous_runs,BRANCH
  display=dict(id=12,created_at='2030-04-01T03:00:00Z',head_branch=BRANCH,event='push',status='in_progress',display_title='saved-view: publish',head_commit={'message':'saved-view: publish'})
  self.assertEqual(list(_previous_runs(lambda _:json.dumps({'workflow_runs':[display]}).encode(),current_run=13)),[])
 def test_display_mode_matches_github_case_insensitive_prefix(self):
  from race_ai.saved_view_run import display_only_run
  self.assertTrue(display_only_run(dict(event='push',display_title='Saved-View: publish',head_commit={'message':'SAVED-VIEW: publish'})))
  self.assertFalse(display_only_run(dict(event='push',display_title='saved-view: publish',head_commit={'message':'normal source'})))

@unittest.skipIf(F is None,'not yet implemented')
class ProjectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  path,self.pair=invented_research_state(Path(self.tmp.name));state=PdcaState(path)
  try:self.view=project_pdca(state)
  finally:state.close()
  self.key=b'x'*32;self.root=bytes(range(32))
  self.receiver=receiver_document(key=self.root,run_id='123',source_head='a'*40)
 def test_bootstrap_delivers_only_display_key_to_existing_root_recipient(self):
  pin=F.originals_sha(self.view);seed=F.seal_bootstrap(self.key,'b'*64,'c'*64,'d'*40,pin,self.receiver)
  opened=F.open_bootstrap(seed,key=self.root)
  self.assertEqual(opened['key'],self.key);self.assertEqual(opened['forecast_sha256'],pin)
  self.assertNotIn(self.key,seed);self.assertNotIn(self.root,seed)
  with self.assertRaises(ValueError):F.open_bootstrap(seed,key=bytes(reversed(range(32))))
  with self.assertRaises(ValueError):F.open_bootstrap(seed.replace(b'RACE_AI_SAVED_VIEW_BOOTSTRAP_V1',b'RACE_AI_BOAT_OWNER_TRANSFER_V2'),key=self.root)
 def test_updates_results_but_keeps_every_original_and_does_not_mutate_input(self):
  old=deepcopy(self.view);o=result(self.pair);o['captured_at']='2026-11-06T11:40:00+09:00'
  new=F.update_view(self.view,[o],synced_at='2026-11-06T03:00:00Z')
  self.assertEqual(self.view,old);self.assertEqual(F.originals_sha(new),F.originals_sha(old))
  self.assertEqual(new['records'][0]['result']['status'],'final')
  pending=deepcopy(o);pending.update(captured_at='2026-11-06T12:00:00+09:00',status='PENDING',data=None)
  newer=F.update_view(new,[pending],synced_at='2026-11-06T03:10:00Z')
  self.assertEqual(newer['records'][0]['result']['status'],'pending')
  self.assertEqual(len(newer['records'][0]['result_observations']),3)
  conflict=deepcopy(o);conflict['source_sha256']='e'*64
  with self.assertRaises(ValueError):F.update_view(new,[conflict],synced_at='2026-11-06T03:10:00Z')
 def test_feed_authenticates_generation_parent_and_forecasts(self):
  raw=F.encrypt_view(self.view,self.key,view_id='b'*64,source_sha='c'*64,generation=1,previous='d'*64)
  header,view=F.decrypt_view(raw,self.key,view_id='b'*64)
  self.assertEqual(view,self.view);self.assertEqual(header['generation'],1)
  self.assertEqual(header['forecast_sha256'],F.originals_sha(self.view))
  with self.assertRaises(ValueError):F.decrypt_view(raw.replace(b'"generation":1',b'"generation":2'),self.key,view_id='b'*64)
  with self.assertRaises(ValueError):F.decrypt_view(raw,self.key,view_id='e'*64)
 def test_original_v1_display_can_initialize_the_feed(self):
  import json,base64
  from cryptography.hazmat.primitives.ciphers.aead import AESGCM
  from race_ai.boat_history_store import wire
  from race_ai.boat_pdca_state import sha
  h=dict(schema='RACE_AI_SAVED_WEB_VIEW_V1',source_content_sha256='a'*64);nonce=b'n'*12
  raw=wire(dict(header=h,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(AESGCM(self.key).encrypt(nonce,wire(self.view).encode(),wire(h).encode())).decode())).encode()
  self.assertEqual(F.decrypt_view(raw,self.key,view_id=sha(raw))[1],self.view)
 def test_private_capture_is_retained_outside_uploaded_artifact_tree(self):
  from tests.test_saved_result_sync import packet,receipt
  folder=Path(self.tmp.name)/'captures';raw=packet();meta=receipt(raw)
  F.retain_capture(folder,raw,meta);F.retain_capture(folder,raw,meta)
  captures=F.load_captures(folder)
  self.assertEqual(captures,[(raw,meta)])
  self.assertTrue(all(not p.stat().st_mode&0o077 for p in folder.iterdir()))
 def test_unsupported_cached_layout_is_reviewable_and_irrelevant_capture_is_ignored(self):
  from race_ai.boat_pdca_state import sha
  rid=self.view['records'][0]['race_id'];raw=b'<html>invented unsupported layout</html>'
  url=f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}'
  receipt=dict(source_url=url,captured_at='2026-11-06T03:00:00Z',source_sha256=sha(raw),http_status=200)
  view=F.update_view(self.view,[],captures=[(raw,receipt)],synced_at='2026-11-06T03:01:00Z')
  self.assertEqual(view['records'][0]['result']['status'],'unsupported')
  self.assertEqual(F.originals_sha(view),F.originals_sha(self.view))
  receipt['source_url']=url.replace('jcd='+rid[9:11],'jcd=24')
  ignored=F.update_view(self.view,[],captures=[(raw,receipt)],synced_at='2026-11-06T03:01:00Z')
  self.assertEqual(ignored['records'],self.view['records'])
 def test_fixed_feed_branch_and_compare_and_swap(self):
  class Git:
   ref='main'
   def head(self):return None
  with self.assertRaises(ValueError):F.publish_view(Git(),{},self.view,parent=None,previous='a'*64,generation=0)
 def test_native_start_metadata_survives_raw_binding_and_next_runner_replay(self):
  from tests.test_saved_result_sync import packet
  from race_ai.saved_result_sync import parse_capture
  from race_ai.boat_pdca_state import sha
  rid=self.view['records'][0]['race_id'];raw=packet().replace(b'20300401',rid[:8].encode()).replace(b'jcd=01',('jcd='+rid[9:11]).encode())
  receipt=dict(source_url=f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd={rid[9:11]}&hd={rid[:8]}',captured_at='2026-11-06T03:00:00Z',source_sha256=sha(raw),http_status=200)
  native=parse_capture(raw,receipt);native['data']['results'][0]['actual_st']=0.15
  first=F.update_view(self.view,[native],captures=[(raw,receipt)],synced_at='2026-11-06T03:01:00Z')
  replay=F.update_view(first,[native],captures=[],synced_at='2026-11-06T03:02:00Z')
  self.assertEqual(first['records'][0]['result'],replay['records'][0]['result'])
  self.assertIn(native,first['records'][0]['result_observations'])

if __name__=='__main__':unittest.main()
