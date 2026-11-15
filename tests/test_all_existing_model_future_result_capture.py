"""Authored result purpose/clock boundaries; no source or owner operation."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest

from tests.test_official_issue_transport import FakeGitHub,PARENT
from tests.test_all_existing_model_future_source_once import KEY


class FutureResultOnceTests(unittest.TestCase):
    def api(self):
        from race_ai import all_existing_model_future_result_capture as api
        return api
    def body(self):
        api=self.api();now=datetime(2030,2,3,1,tzinfo=timezone.utc)
        return dict(schema=api.ONCE,purpose=api.PURPOSE,marker_path=api.PATH,state='CONSUMED_BEFORE_DISPATCH',
            target=dict(run_id=42,head_sha='a'*40,run_attempt=1),repository_id=1416489937,pull_request=71,
            issued_at=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat(),execution_day='2030-02-03',
            manifest_sha256='b'*64,forecast_identity_sha256='c'*64,history_sha256='d'*64,
            plan_sha256='e'*64,source_requests_actual=None,source_request_upper_bound=32,
            old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN'),now
    def test_separate_exact_marker_mac_and_create_only_readback(self):
        api=self.api();body,now=self.body();server=FakeGitHub();transport=api.MarkerTransport(server)
        proof=api.reserve(body,KEY,transport,now=now)
        raw=transport.read_file(proof['commit_sha'],api.PATH,1024*1024)
        self.assertEqual(api.validate_marker(raw,body,KEY,now=now)['source_request_upper_bound'],32)
        with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):api.reserve(body,KEY,transport,now=now)
        from race_ai.all_existing_model_future_source_once import PATH as input_path
        with self.assertRaises(ValueError):transport.read_file(PARENT,input_path,1024)
    def test_bad_existing_marker_also_blocks_without_reissue(self):
        api=self.api();body,now=self.body();server=FakeGitHub();server.snapshots[PARENT][api.PATH]=b'unknown'
        server._commit(PARENT,server.snapshots[PARENT])
        with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):
            api.reserve(body,KEY,api.MarkerTransport(server),now=now)
        self.assertTrue(all(method=='GET' for method,_,_ in server.calls))
    def test_expiry_midnight_attempt_and_unknown_truth_are_not_relaxed(self):
        api=self.api();body,now=self.body()
        for change in ('attempt','expiry','old_count','cap','field'):
            value=deepcopy(body)
            if change=='attempt':value['target']['run_attempt']=2
            elif change=='expiry':value['expires_at']=(now+timedelta(days=1)).isoformat()
            elif change=='old_count':value['old_source_requests_actual']=0
            elif change=='cap':value['source_request_upper_bound']=33
            else:value['unreviewed']=True
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_marker(value,KEY)
        raw=api.issue_marker(body,KEY)
        with self.assertRaises(ValueError):api.validate_marker(raw,body,KEY,now=now+timedelta(hours=1))


class FutureResultHistoryJoinTests(unittest.TestCase):
    def fixture(self):
        from race_ai import all_existing_model_future_result_capture as api
        admitted=dict(cases=[]);proof=dict(source_native_bindings=[]);history=dict(bodies={},receipts={})
        for index,sports in enumerate((['autorace','keirin'],['horse']),1):
            stamp='2030-02-02T10:00:00+09:00';cutoff='2030-02-02T12:00:00+09:00'
            pin=dict(id=100+index,digest='sha256:'+'a'*64,run_id=index,head_sha='b'*40)
            receipt=dict(artifact_name=f'all-existing-model-pairs-{index}-{900002 if sports==["horse"] else 900003}',record_sha256=['c'*64])
            proof['source_native_bindings'].append(dict(pin=pin,receipt=receipt,sports=sports))
            body=dict(schema='RACE_AI_JRA_FUTURE_SOURCE_JOURNAL_V1' if sports==['horse'] else api.history_core.JOURNAL,
                workflow_run_id=index,code_sha='b'*40,native_ready=True,once_proof=dict(authenticated=True),fixed_as_of=stamp,
                native_generation=dict(record_sha256=['c'*64],workflow_run_id=index,expected_head_sha='b'*40))
            history['bodies'][index]=body;history['receipts'][index]=dict(artifact_metadata=dict(created_at=stamp))
            for sport in sports:admitted['cases'].append(dict(case=dict(sport=sport),identity=dict(as_of=stamp,race_cutoff_at=cutoff)))
        return api,admitted,proof,history
    def test_own_future_capture_journals_cannot_be_omitted_or_substituted(self):
        api,admitted,proof,history=self.fixture()
        self.assertTrue(api.bind_source_history(admitted,proof,history)['original_future_source_journals_joined'])
        for mutation in ('missing','sha','head','kind','late','asof','once','native','partial'):
            a=deepcopy(admitted);p=deepcopy(proof);h=deepcopy(history)
            if mutation=='missing':h['bodies'].pop(2)
            elif mutation=='sha':h['bodies'][2]['native_generation']['record_sha256']=['f'*64]
            elif mutation=='head':h['bodies'][2]['code_sha']='f'*40
            elif mutation=='kind':p['source_native_bindings'][1]['receipt']['artifact_name']='other-2'
            elif mutation=='late':h['receipts'][2]['artifact_metadata']['created_at']='2030-02-02T11:50:00+09:00'
            elif mutation=='asof':h['bodies'][2]['fixed_as_of']='2030-02-02T10:00:01+09:00'
            elif mutation=='once':h['bodies'][2]['once_proof']=None
            elif mutation=='native':h['bodies'][2]['native_ready']=False
            else:p['source_native_bindings'].pop()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):api.bind_source_history(a,p,h)
    def test_ak_original_expired_once_is_replayed_at_capture_time_six_hours_later(self):
        from race_ai import all_existing_model_future_source_capture as history
        from race_ai import all_existing_model_future_source_once as once
        from scripts import all_existing_model_future_source_capture as wrapper
        from tests.test_all_existing_model_future_source_history import history_fixture,_archive,ENV
        from tests.test_all_existing_model_future_source_history import _pin
        data=history_fixture(include_result=False);item=data['journal_archives'][-1]
        journal,source,_=wrapper.source_archive(item['raw'],item['metadata'],ENV,now=data['now'],key=KEY)
        epoch=history.clock(journal['epoch_started_at']);plan=wrapper._open(source['plan.enc'],ENV,KEY)
        contexts={s:dict(receipt=dict(created_at=(epoch-timedelta(minutes=2)).isoformat()),training=dict(
            training_sha256='b'*64,models={s+'/'+history.LEARNED_ID:dict(native_training=dict(created_at=(epoch-timedelta(days=1)).isoformat()))}))
            for s in history.SPORTS}
        body=once.body(journal['manifest'],dict(ENV,run_attempt=1),contexts,{},plan,now=epoch)
        plan['not_after']=body['expires_at'];body['plan_sha256']=history.digest(plan)
        proof=once.reserve(body,KEY,once.FutureSourceMarkerTransport(FakeGitHub()),now=epoch);cipher=proof.pop('_ciphertext')
        reservation=wrapper._open(source['reservation.enc'],ENV,KEY)
        for value in (journal,reservation):value.update(once_body=body,plan_sha256=history.digest(plan))
        journal['once_proof']=proof
        source.update({'collection.enc':wrapper.seal_forecasts(journal,run_id=str(ENV['run_id']),round_no=history.ROUND,key=KEY),
            'reservation.enc':wrapper.seal_forecasts(reservation,run_id=str(ENV['run_id']),round_no=history.ROUND,key=KEY),
            'plan.enc':wrapper.seal_forecasts(plan,run_id=str(ENV['run_id']),round_no=history.ROUND,key=KEY),'once.enc':cipher})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,raw in source.items():(root/name).write_bytes(raw)
            raw=_archive(root)
        actual=dict(item['metadata'],size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        at=epoch+timedelta(hours=6)
        self.assertGreater(at,history.clock(body['expires_at']))
        verified,_=history._future_epoch(dict(raw=raw,metadata=actual),_pin(actual),now=at,key=KEY)
        self.assertEqual(verified['capture_index'],journal['capture_index'])
        self.assertEqual(verified['source_requests_actual'],4)


if __name__=='__main__':unittest.main()
