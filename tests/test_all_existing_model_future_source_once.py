"""Experiment-wide one-shot reservation with a fake GitHub Git server only."""
from copy import deepcopy
from datetime import timedelta
import os
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from race_ai import all_existing_model_future_source_once as once
from race_ai import all_existing_model_future_source_capture as core
from race_ai.all_existing_model_official_issue_transport import GithubIssueTransport
from tests.test_all_existing_model_future_source_capture import manifest_fixture
from tests.test_official_future_source_packet import capture_fixture
from tests.test_official_issue_transport import FakeGitHub,PARENT,PATH as OLD_PATH
from tests.test_all_existing_model_source_packet_freeze import KEY


def fixture():
    manifest=manifest_fixture();now=core.clock(capture_fixture()[1]['completed_at'])
    env=dict(run_id=42,head_sha='a'*40,run_attempt=1)
    contexts={s:dict(receipt=dict(created_at=(now-timedelta(minutes=2)).isoformat()),training=dict(
        training_sha256='b'*64,models={s+'/'+core.LEARNED_ID:dict(native_training=dict(created_at=(now-timedelta(days=1)).isoformat()))}))
        for s in core.SPORTS}
    history=dict(old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')
    plan=core.prepare_capture(manifest,contexts,now=now);plan['available_after']=now.isoformat()
    return once.body(manifest,env,contexts,history,plan,now=now),now


class FutureSourceOnceTests(unittest.TestCase):
    def setUp(self):
        isolated=patch.dict(os.environ,{k:v for k,v in os.environ.items() if k!='NODE_PATH'},clear=True)
        isolated.start();self.addCleanup(isolated.stop)

    def test_create_only_canonical_marker_real_mac_aes_and_exact_immutable_readback(self):
        body,now=fixture();api=FakeGitHub();transport=once.FutureSourceMarkerTransport(api)
        audit=once.reserve(body,KEY,transport,now=now)
        raw=transport.read_file(audit['commit_sha'],once.PATH,1024*1024)
        self.assertEqual(once.validate(raw,body,KEY,now=now)['source_request_upper_bound'],32)
        self.assertEqual(set(api.snapshots[audit['commit_sha']]),{'keep/original.enc',once.PATH})
        self.assertTrue(all(b['force'] is False for m,p,b in api.calls if m=='PATCH'))
        for change in ('head','day','run','case','baseline'):
            changed=deepcopy(body)
            if change=='head':changed['target']['head_sha']='f'*40
            elif change=='day':changed['execution_day']='2030-01-16'
            elif change=='run':changed['target']['run_id']=43
            elif change=='case':changed['cases'][0]['race_no']=2
            else:changed['baseline_artifacts']['autorace']['id']=999
            before=len(api.calls)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):
                once.reserve(changed,KEY,transport,now=now)
            self.assertTrue(all(m=='GET' for m,p,b in api.calls[before:]))

    def test_existing_garbage_expired_or_foreign_marker_is_never_reissued(self):
        body,now=fixture()
        for raw in (b'not-a-marker',once.issue(body,KEY)):
            api=FakeGitHub();api.snapshots[PARENT][once.PATH]=raw;api._commit(PARENT,api.snapshots[PARENT])
            with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):
                once.reserve(body,KEY,once.FutureSourceMarkerTransport(api),now=now+timedelta(days=1))
            self.assertTrue(all(m=='GET' for m,p,b in api.calls))

    def test_legacy_paths_and_new_marker_paths_do_not_expand_each_others_permissions(self):
        api=FakeGitHub();new=once.FutureSourceMarkerTransport(api);old=GithubIssueTransport(api)
        for transport,path in ((new,OLD_PATH),(new,once.PATH+'.new'),(new,'../'+once.PATH),(old,once.PATH)):
            with self.subTest(path=path),self.assertRaises(ValueError):transport.read_file(PARENT,path,1024)
        self.assertEqual(api.calls,[])

    def test_cas_race_or_different_actual_readback_never_returns_dispatch_authority(self):
        body,now=fixture();api=FakeGitHub();api.cas_race=True
        with self.assertRaises(ValueError):once.reserve(body,KEY,once.FutureSourceMarkerTransport(api),now=now)
        api=FakeGitHub();transport=once.FutureSourceMarkerTransport(api);original=transport.publish_capsule
        def corrupt(path,raw,parent):
            commit=original(path,raw,parent);api.blobs.clear();return commit
        transport.publish_capsule=corrupt
        with self.assertRaises(ValueError):once.reserve(body,KEY,transport,now=now)

    def test_mac_scope_actual_attempt_and_capture_day_expiry_are_bound(self):
        body,now=fixture();raw=once.issue(body,KEY)
        for change in ('raw','key','head','expired'):
            changed=deepcopy(body);cipher=raw;key=KEY;at=now
            if change=='raw':cipher=raw[:-1]+bytes([raw[-1]^1])
            elif change=='key':key=bytes(reversed(KEY))
            elif change=='head':changed['target']['head_sha']='b'*40
            else:at=core.clock(body['expires_at'])
            with self.subTest(change=change),self.assertRaises(ValueError):once.validate(cipher,changed,key,now=at)

    def test_existing_canonical_reservation_blocks_wrapper_before_source_or_baseline_reads(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        body,now=fixture();api=FakeGitHub();api.snapshots[PARENT][once.PATH]=b'old-consumed-unknown'
        api._commit(PARENT,api.snapshots[PARENT]);transport=once.FutureSourceMarkerTransport(api)
        with tempfile.TemporaryDirectory() as temporary,patch.object(wrapper,'utc_now',return_value=now),\
            patch.object(wrapper,'state_key',return_value=KEY),patch.object(wrapper.freeze,'_carrier_context') as baseline,\
            patch.object(wrapper,'capture_browser') as provider:
            root=Path(temporary)/'fresh'
            with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):
                wrapper.generate(manifest_fixture(),root,dict(run_id=42,head_sha='a'*40,run_attempt=1),marker_transport=transport)
            self.assertFalse(root.exists());provider.assert_not_called();baseline.assert_not_called()

    def test_issuer_refuses_scope_bound_clock_or_unknown_field_changes(self):
        body,now=fixture()
        for change in ('cap','attempt','day','expiry','old_count','extra','hash'):
            changed=deepcopy(body)
            if change=='cap':changed['source_request_upper_bound']=33
            elif change=='attempt':changed['target']['run_attempt']=2
            elif change=='day':changed['execution_day']='2030-01-16'
            elif change=='expiry':changed['expires_at']=(now+timedelta(days=1)).isoformat()
            elif change=='old_count':changed['old_source_requests_actual']=0
            elif change=='extra':changed['unreviewed_alternative']=True
            else:changed['manifest_sha256']='invalid'
            with self.subTest(change=change),self.assertRaises(ValueError):once.issue(changed,KEY)

    def test_synthetic_carrier_or_baseline_never_reaches_history_or_source_dispatch(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        body,now=fixture()
        for kind in ('carrier','baseline'):
            carrier=dict(training=dict(scope='SYNTHETIC_ONLY' if kind=='carrier' else 'OPERATOR_SUPPLIED_RESEARCH',
                models={str(n):{} for n in range(14)}))
            contexts={s:dict(training=dict(scope='SYNTHETIC_ONLY',models={str(n):{} for n in range(30)})) for s in core.SPORTS}
            with tempfile.TemporaryDirectory() as temporary,patch.object(wrapper,'utc_now',return_value=now),\
                patch.object(wrapper,'state_key',return_value=KEY),patch.object(wrapper.freeze,'_carrier_context',return_value=carrier),\
                patch.object(wrapper.freeze,'_baseline_contexts',return_value=contexts),\
                patch.object(wrapper,'history',side_effect=AssertionError('history should not be reached')) as history,\
                patch.object(wrapper,'capture_browser') as provider:
                with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'REAL_RESEARCH'):
                    wrapper.generate(manifest_fixture(),Path(temporary)/'fresh',dict(run_id=42,head_sha='a'*40,run_attempt=1),
                        marker_transport=once.FutureSourceMarkerTransport(FakeGitHub()))
                history.assert_not_called();provider.assert_not_called()


if __name__=='__main__':unittest.main()
