"""Authenticated final checkpoint joins the saved round across executions."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
import os
import unittest
from unittest.mock import patch
from tests.test_boat_pending_round_recovery import fixture,KEY,HEAD,NOW
from tests.test_continuity_checkpoint import session
from tests.test_boat_private_original_vault import packed
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.boat_source_control import build_summary
from race_ai.cycle_recovery import authenticated_source_control
from race_ai.boat_pending_round_recovery import read_final_control,reconcile_restored_state

class CheckpointRecoveryTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        env.start();self.addCleanup(env.stop)
        self.run,self.control,self.responses=fixture()
        state=session(run_id=99,requests_used=88,completed_round=2,prepared_round=3,
            lifetime_requests_base=0,lifetime_requests=88,lifetime_completed_rounds_base=0,
            lifetime_completed_rounds=2,day_start_lifetime_requests=0,source_wait=None)
        cipher=seal_original_zip(packed({'repeat-session.json':state}),run_id=99,head_sha=HEAD,kind='CONTINUITY',key=KEY)
        continuity=packed({'private-original.enc':cipher})
        companion=packed({'source-control.json':json.dumps(build_summary(cipher,run_id=99,head_sha=HEAD,key=KEY))})
        listing=json.loads(self.responses['actions/runs/99/artifacts?per_page=100'])
        for raw,ident,name,at in ((continuity,702,'race-cycle-continuity-99','2030-04-01T02:31:00Z'),
                                  (companion,703,'race-source-control-99','2030-04-01T02:31:01Z')):
            meta=dict(id=ident,name=name,expired=False,created_at=at,expires_at='2030-04-08T02:00:00Z',
                digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
                workflow_run=dict(id=99,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
            self.responses[f'actions/artifacts/{ident}']=json.dumps(meta).encode()
            self.responses[f'actions/artifacts/{ident}/zip']=raw
            listing['artifacts'].append(meta)
            if ident==702:self.original=(raw,meta)
        listing['total_count']=len(listing['artifacts'])
        self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(listing).encode()
        self.responses['actions/runs/99']=json.dumps(self.run).encode()
        self.get=lambda p:self.responses[p]
        self.state=dict(day_jst='2030-04-01',source_control=authenticated_source_control(*self.original),rows=[])

    def test_public_companion_and_decrypted_checkpoint_agree_before_round_repair(self):
        public=read_final_control(self.get,self.run)
        self.assertEqual(public['prepared_round'],3)
        before=deepcopy((self.responses,self.state))
        restored,pending=reconcile_restored_state(self.state,self.get,now=NOW)
        self.assertEqual(restored['source_control']['completed_round'],3)
        self.assertIsNone(restored['source_control']['prepared_round'])
        self.assertEqual(restored['source_control']['lifetime_requests'],88)
        self.assertEqual(pending['verified']['original_artifact_ids'],[123,701])
        self.assertEqual((self.responses,self.state),before)

    def test_actual_checkpoint_cipher_tamper_stops_recovery(self):
        self.responses['actions/artifacts/702/zip']+=b'tamper'
        with self.assertRaises(ValueError):reconcile_restored_state(self.state,self.get,now=NOW)

    def test_decrypted_control_mismatch_stops_even_when_public_companion_valid(self):
        self.state['source_control']['lifetime_requests']=87
        with self.assertRaises(ValueError):reconcile_restored_state(self.state,self.get,now=NOW)

if __name__=='__main__':unittest.main()
