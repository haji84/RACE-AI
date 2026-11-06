"""Invented official layouts; no live source, actual predictions or keys."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
 from race_ai import saved_result_sync as M
except ImportError:
 M=None

DAY=date(2030,4,1);URL='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401'
def packet(*,cancel=False,finish=True,refund=False,price='¥1,250',wrong_winner=False):
 headers=''.join(f'<th'+('' if n==1 else ' class="is-thColor2"')+f'><a href="/owpc/pc/race/raceresult?rno={n}&amp;jcd=01&amp;hd=20300401">{n}R</a></th>' for n in range(1,13))
 schedule='<table><thead><tr><th>レース</th>'+headers+'</tr></thead><tbody><tr><td>締切予定時刻</td>'+''.join('<td>11:00</td>' for _ in range(12))+'</tr></tbody></table>'
 content='<div class="title12"><h3 class="title12_title is-type1">レース中止</h3></div>' if cancel else ''
 if finish:
  content+='<table><thead><tr><th>着</th><th>枠</th><th>ボートレーサー</th><th>レースタイム</th></tr></thead><tbody>'
  content+=''.join(f'<tr><td>{"F" if refund and n==6 else n}</td><td class="is-boatColor{n}">{n}</td><td>{4000+n} INVENTED{n}</td><td>1.50.0</td></tr>' for n in range(1,7))+'</tbody></table>'
 combo='' if cancel else '3-2-1' if wrong_winner else '1-2-3'
 price='' if cancel else price
 content+='<table><thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead><tbody><tr><td>3連単</td><td>'+combo+'</td><td>'+price+'</td><td>1</td></tr><tr><td>複勝</td><td>'+('' if cancel else '1')+'</td><td></td><td></td></tr></tbody></table>'
 content+='<table><thead><tr><th>返還</th></tr></thead><tbody><tr><td>'+('<span class="numberSet1_number">6</span>' if refund else '')+'</td></tr></tbody></table>'
 return ('<html><body><div class="contentsFrame1_inner">'+schedule+content+'</div></body></html>').encode()
def receipt(raw):return dict(source_url=URL,captured_at='2030-04-01T03:00:00Z',source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200)

class ModuleTests(unittest.TestCase):
 def test_sync_adapter_exists(self):self.assertIsNotNone(M)

@unittest.skipIf(M is None,'adapter not yet implemented')
class SourceTests(unittest.TestCase):
 def test_explicit_cancellation_heading_is_not_missed_when_css_class_changes(self):
  raw=packet(cancel=True,finish=False);o=M.parse_capture(raw,receipt(raw));self.assertEqual(o['data']['status'],'cancelled');self.assertTrue(o['body_identity_verified'])
  import re
  absent=re.sub(b'<table><thead><tr><th>'+ '勝式'.encode()+b'.*?</table>',b'',raw)
  self.assertEqual(M.parse_capture(absent,receipt(absent))['data']['status'],'cancelled')
 def test_six_finish_identities_and_trifecta_do_not_require_full_start_times_or_other_markets(self):
  for price in ('¥1,250','￥1,250','1,250円'):
   raw=packet(price=price);o=M.parse_capture(raw,receipt(raw));self.assertEqual(o['data']['payouts'][0]['payout_per_100_yen'],1250);self.assertTrue(o['data']['confirmed']);self.assertEqual(len(o['data']['results']),6)
 def test_explicit_returned_boat_is_retained_without_inventing_start_times(self):
  raw=packet(refund=True);o=M.parse_capture(raw,receipt(raw));self.assertEqual(o['data']['refund_boats'],[6]);self.assertIsNone(o['data']['results'][5]['finish'])
 def test_wrong_race_wrong_hash_wrong_winner_or_incomplete_roster_is_rejected(self):
  for raw,edit in [(packet(),lambda r:r.update(source_url=URL.replace('rno=1','rno=2'))),(packet(),lambda r:r.update(source_sha256='0'*64)),(packet(wrong_winner=True),lambda r:None),(packet().replace(b'4006',b'4005'),lambda r:None)]:
   with self.subTest():
    meta=receipt(raw);edit(meta)
    with self.assertRaises(ValueError):M.parse_capture(raw,meta)
 def test_payout_only_or_incidental_cancellation_text_is_not_a_settled_race(self):
  raw=packet(finish=False).replace(b'</div>', '<p>レース中止の可能性があります</p></div>'.encode());o=M.parse_capture(raw,receipt(raw));self.assertEqual(o['status'],'PENDING');self.assertIsNone(o['data'])
 def test_cancellation_cannot_override_populated_finishes_or_paid_winners(self):
  for raw in (packet(cancel=True),packet(cancel=True,finish=False).replace('<td>3連単</td><td></td><td></td>'.encode(),'<td>3連単</td><td>1-2-3</td><td>1250円</td>'.encode())):
   with self.assertRaises(ValueError):M.parse_capture(raw,receipt(raw))
 def test_cancellation_heading_in_an_aside_cannot_cancel_the_selected_result(self):
  raw=packet().replace(b'</div>', '<aside><div class="title12"><h3 class="title12_title is-type1">レース中止</h3></div></aside></div>'.encode())
  self.assertEqual(M.parse_capture(raw,receipt(raw))['data']['status'],'settled')

@unittest.skipIf(M is None,'adapter not yet implemented')
class JournalTests(unittest.TestCase):
 def setUp(self):
  from tests.test_boat_pdca_github_handoff import invented_research_state
  from race_ai.boat_pdca_state import PdcaState
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);path,self.pair=invented_research_state(Path(self.tmp.name));self.state=PdcaState(path);self.addCleanup(self.state.close)
 def test_retaining_observations_preserves_all_pairs_and_existing_result_history(self):
  from tests.test_boat_pdca_state import result
  from race_ai.boat_pdca_projection import project_pdca
  original=project_pdca(self.state);pairs=self.state.db.execute('SELECT * FROM pairs').fetchall();o=result(self.pair);o.update(captured_at='2026-11-06T11:40:00+09:00',status='PENDING',data=None)
  M.retain_batch(self.state,[o]);before=self.state.content_sha256();M.retain_batch(self.state,[o]);self.assertEqual(self.state.content_sha256(),before);view=project_pdca(self.state)
  self.assertEqual(view['records'][0]['result']['status'],'pending');self.assertEqual(len(view['records'][0]['result_observations']),2)
  self.assertEqual(view['records'][0]['prediction'],original['records'][0]['prediction']);self.assertEqual(self.state.db.execute('SELECT * FROM pairs').fetchall(),pairs)
  bad=deepcopy(o);bad['source_sha256']='e'*64
  with self.assertRaises(ValueError):M.retain_batch(self.state,[bad])
 def test_raw_bound60s_reference_never_rewrites_original_or_weakens_strict_scoring(self):
  from race_ai.private_cycle_projection import _observation
  from tests.test_boat_pdca_state import result
  o=result(self.pair);row=dict(race_id=o['race_id'],cutoff_at=o['closed_at'],saved_cutoff_variants=[o['closed_at']],participants=[dict(number=p['lane'],registration_no=p['registration_no']) for p in self.pair['baseline']['snapshot']['participants']])
  from datetime import datetime,timedelta
  o['closed_at']=(datetime.fromisoformat(o['closed_at'])+timedelta(seconds=60)).isoformat()
  with self.assertRaises(ValueError):_observation(o,row)
  with self.assertRaises(ValueError):M.project_observation(o,row,freeze_at=self.pair['generated_at'],raw_bound=False)
  observed=M.project_observation(o,row,freeze_at=self.pair['generated_at'],raw_bound=True)
  self.assertEqual(observed['status'],'final');self.assertEqual(observed['cutoff_reference']['offset_seconds'],60);self.assertFalse(observed['official'])
  with self.assertRaises(ValueError):M.project_observation(o,row,freeze_at=row['cutoff_at'],raw_bound=True)
  o['closed_at']=(datetime.fromisoformat(o['closed_at'])+timedelta(seconds=1)).isoformat()
  with self.assertRaises(ValueError):M.project_observation(o,row,freeze_at=self.pair['generated_at'],raw_bound=True)
 def test_raw_selected_race_cancellation_can_refund_without_six_finish_records(self):
  from tests.test_boat_pdca_state import result
  from datetime import datetime,timedelta
  o=result(self.pair);row=dict(race_id=o['race_id'],cutoff_at=o['closed_at'],saved_cutoff_variants=[o['closed_at']],participants=[dict(number=p['lane'],registration_no=p['registration_no']) for p in self.pair['baseline']['snapshot']['participants']])
  o['closed_at']=(datetime.fromisoformat(o['closed_at'])-timedelta(hours=3)).isoformat();o['data']=dict(status='cancelled',confirmed=True,results=[])
  self.assertEqual(M.project_observation(o,row,freeze_at=self.pair['generated_at'],raw_bound=True)['status'],'void')
 def test_a_conflict_with_a_previous_raw_capture_is_rejected_before_journal_mutation(self):
  raw=packet().replace(b'20300401',b'20261106').replace(b'jcd=01',b'jcd=17')
  meta=dict(source_url=URL.replace('20300401','20261106').replace('jcd=01','jcd=17'),captured_at='2026-11-06T03:30:00Z',source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200)
  M.retain_batch(self.state,[],[dict(raw=raw,receipt=meta)]);before=self.state.content_sha256();o=M.parse_capture(raw,meta);o['source_sha256']='e'*64
  with self.assertRaises(ValueError):M.retain_batch(self.state,[o])
  self.assertEqual(self.state.content_sha256(),before)
 def test_another_race_cannot_borrow_a_retained_raw_hash_and_capture_time_for_clock_binding(self):
  from tests.test_boat_history_comparison import current,NOW
  from race_ai.boat_history_store import HistoryStore,instant
  from race_ai.boat_history_comparison import prepare_pair,freeze_pair
  from race_ai.boat_pdca_projection import project_pdca
  root=Path(self.tmp.name);h=HistoryStore(root/'peer-history.sqlite');snap=current();snap['race_id']='boat:2026-11-06:boatrace-jcd-17:2';pair=prepare_pair(snap,h,NOW);h.close();path=root/'peer.json';freeze_pair(pair,path,clock=lambda:instant(NOW));self.state.retain_pair(path)
  raw=packet().replace(b'20300401',b'20261106').replace(b'jcd=01',b'jcd=17')
  meta=dict(source_url=URL.replace('20300401','20261106').replace('jcd=01','jcd=17'),captured_at='2026-11-06T03:30:00Z',source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200)
  M.retain_batch(self.state,[],[dict(raw=raw,receipt=meta)]);foreign=M.parse_capture(raw,meta);foreign['race_id']=pair['race_id']
  for record in foreign['data']['results']:record['race_id']=pair['race_id']
  M.retain_batch(self.state,[foreign]);view=project_pdca(self.state);other=next(r for r in view['records'] if r['race_id']==pair['race_id'])
  first=next(r for r in view['records'] if r['race_id']==self.pair['race_id']);self.assertEqual(first['result']['status'],'final');self.assertEqual(first['result']['cutoff_reference']['offset_seconds'],60)
  self.assertEqual(other['result']['status'],'unsupported');self.assertEqual(other['result_observation_rejections'][0]['reason'],'RESULT_CUTOFF_MISMATCH')
