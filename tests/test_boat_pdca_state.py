"""Invented data only: private state, authenticated handoff and result replay."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.test_boat_history_comparison import current,NOW
from tests.test_boat_history_store import archives,DAY
from race_ai.boat_history_store import HistoryStore,instant
from race_ai.boat_history_comparison import prepare_pair,freeze_pair


def result(pair):
    return dict(race_id=pair['race_id'],body_identity_verified=True,status='AVAILABLE',
        closed_at=pair['cutoff_at'],captured_at='2026-11-06T11:10:00+09:00',source_sha256='f'*64,
        data=dict(status='settled',confirmed=True,finish_confirmed=True,refund_boats=[],top3=[6,5,4],
            results=[dict(lane=i,racer_registration_id=str(4000+i),finish_status='FINISHED',finish=7-i) for i in range(1,7)],
            payouts=[dict(bet_type='trifecta',combination=[6,5,4],payout_per_100_yen=1200)]))


def invented_pair(root):
    history=HistoryStore(root/'history.sqlite');raw,proof=archives()
    history.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
    snapshot=current();snapshot['scope']='SYNTHETIC_ONLY'
    pair=prepare_pair(snapshot,history,NOW);history.close()
    path=root/'pair.json';freeze_pair(pair,path,clock=lambda:instant(NOW))
    return pair,path


class PdcaStateTests(unittest.TestCase):
    def test_import_unions_originals_without_replacing_existing_heads_and_is_idempotent(self):
        from race_ai.boat_pdca_state import PdcaState
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pair,path=invented_pair(root)
            target=PdcaState.create(root/'target.sqlite',mode='synthetic')
            source=PdcaState.create(root/'source.sqlite',mode='synthetic')
            target.retain_pair(path);source.retain_pair(path)
            with target.db:target._put('shared.json',b'newer current original')
            with source.db:source._put('shared.json',b'older incoming original');source._put('incoming.json',b'keep')
            source.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')
            target.import_state(source)
            self.assertEqual(target._get(dict(target.db.execute('SELECT name,sha FROM heads'))['shared.json']),b'newer current original')
            self.assertEqual(target.inventory()['result_revisions'],1)
            before=target.inventory();target.import_state(source);self.assertEqual(target.inventory(),before)
            self.assertTrue(target.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')['reused'])
            target.close();source.close()

    def test_import_conflict_rolls_back_and_refuses_mixed_scope(self):
        from race_ai.boat_pdca_state import PdcaState
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pair,path=invented_pair(root)
            a=PdcaState.create(root/'a.sqlite',mode='synthetic');b=PdcaState.create(root/'b.sqlite',mode='synthetic')
            for s in (a,b):s.retain_pair(path)
            a.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')
            changed=result(pair);changed['data']['payouts'][0]['payout_per_100_yen']=999
            b.score(pair['pair_sha256'],changed,'2026-11-06T12:00:00+09:00')
            before=a.inventory()
            with self.assertRaises(ValueError):a.import_state(b)
            self.assertEqual(a.inventory(),before)
            p=PdcaState.create(root/'production.sqlite',mode='production')
            with self.assertRaises(ValueError):a.import_state(p)
            a.close();b.close();p.close()

    def test_encrypted_restore_preserves_pair_history_and_scores_each_result_revision_once(self):
        from race_ai.boat_pdca_state import PdcaState,restore_state
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pair,path=invented_pair(root)
            state=PdcaState.create(root/'state.sqlite',mode='synthetic')
            state.retain_history(root/'history.sqlite',synthetic_fixture=True);state.retain_pair(path)
            first=state.checkpoint(root/'sealed',generation=1)
            state.close()
            restored=restore_state(root/'sealed/state.enc',root/'restored.sqlite',
                expected_sha256=first['cipher_sha256'],expected_scope=first['scope'])
            out=restored.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')
            self.assertFalse(out['reused'])
            self.assertTrue(restored.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')['reused'])
            corrected=result(pair);corrected['captured_at']='2026-11-06T11:20:00+09:00'
            corrected['source_sha256']='e'*64;corrected['data']['payouts'][0]['payout_per_100_yen']=1500
            newer=restored.score(pair['pair_sha256'],corrected,'2026-11-06T12:00:00+09:00')
            self.assertEqual(newer['report']['models'][0]['baseline_received_yen'],1500)
            older=restored.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00')
            self.assertEqual(older['result_revision_sha256'],newer['result_revision_sha256'])
            self.assertEqual(restored.inventory()['result_revisions'],2)
            self.assertEqual(restored.inventory()['scorings'],2)
            recovered=root/'recovered';restored.materialize(recovered)
            self.assertEqual((recovered/'pairs'/f"{pair['pair_sha256']}.json").read_bytes(),path.read_bytes())
            self.assertTrue((recovered/'history.sqlite').is_file())
            restored.close()

    def test_missing_state_and_bad_cipher_or_scope_never_reset_or_create_database(self):
        from race_ai.boat_pdca_state import PdcaState,restore_state
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);missing=root/'missing.sqlite'
            with self.assertRaises(ValueError):PdcaState(missing)
            self.assertFalse(missing.exists())
            state=PdcaState.create(root/'state.sqlite',mode='synthetic')
            proof=state.checkpoint(root/'sealed',generation=1);state.close()
            for sha,scope in [('0'*64,proof['scope']), (proof['cipher_sha256'],dict(proof['scope'],generation=2,previous_cipher_sha256='1'*64))]:
                with self.assertRaises(ValueError):restore_state(root/'sealed/state.enc',missing,expected_sha256=sha,expected_scope=scope)
                self.assertFalse(missing.exists())

    def test_synthetic_export_refuses_real_research_pairs_and_production_requires_owner_key(self):
        from race_ai.boat_pdca_state import PdcaState
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=HistoryStore(root/'history.sqlite');raw,proof=archives()
            history.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
            pair=prepare_pair(current(),history,NOW);history.close()
            p=root/'research.json';freeze_pair(pair,p,clock=lambda:instant(NOW))
            synthetic=PdcaState.create(root/'s.sqlite',mode='synthetic')
            with self.assertRaisesRegex(ValueError,'SYNTHETIC'):synthetic.retain_pair(p)
            synthetic.close()
            production=PdcaState.create(root/'p.sqlite',mode='production')
            with self.assertRaisesRegex(ValueError,'OWNER_STATE_KEY'):production.checkpoint(root/'production',generation=1)
            self.assertFalse((root/'production/state.enc').exists());production.close()

    def test_wrong_key_and_authenticated_scope_change_cannot_create_plaintext(self):
        import base64,json,hashlib
        from race_ai.boat_pdca_state import PdcaState,restore_state
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=PdcaState.create(root/'state.sqlite',mode='synthetic')
            proof=state.checkpoint(root/'sealed',generation=1);state.close()
            cipher=root/'sealed/state.enc';destination=root/'restored.sqlite'
            with self.assertRaises(ValueError):restore_state(cipher,destination,expected_sha256=proof['cipher_sha256'],
                expected_scope=proof['scope'],key=bytes(range(32)))
            self.assertFalse(destination.exists())
            doc=json.loads(cipher.read_text());data=bytearray(base64.b64decode(doc['ciphertext']));data[-1]^=1
            doc['ciphertext']=base64.b64encode(data).decode();tampered=root/'tampered.enc';tampered.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):restore_state(tampered,destination,expected_sha256=hashlib.sha256(tampered.read_bytes()).hexdigest(),
                expected_scope=proof['scope'])
            self.assertFalse(destination.exists())

    def test_same_result_capture_with_different_body_is_rejected(self):
        from race_ai.boat_pdca_state import PdcaState
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pair,path=invented_pair(root)
            state=PdcaState.create(root/'state.sqlite',mode='synthetic');state.retain_pair(path)
            first=result(pair);state.score(pair['pair_sha256'],first,'2026-11-06T12:00:00+09:00')
            other=deepcopy(first);other['data']['payouts'][0]['payout_per_100_yen']=3000
            with self.assertRaisesRegex(ValueError,'CONFLICT'):state.score(pair['pair_sha256'],other,'2026-11-06T12:00:00+09:00')
            self.assertEqual(state.inventory()['result_revisions'],1);state.close()
