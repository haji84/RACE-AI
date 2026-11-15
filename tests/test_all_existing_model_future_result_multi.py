"""Synthetic multi-origin RESULT contracts; no live source or owner operation."""
import base64
from copy import deepcopy
import os
import unittest
from unittest.mock import patch
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from race_ai.actions_contract import digest
from tests import test_all_existing_model_native_future_v3 as authored
from tests.test_all_existing_model_thirty_order_pdca_artifacts import full_fixture, EVALUATED
from tests.test_all_existing_model_future_batches import separate_fixture


class FutureResultMultiManifestTests(unittest.TestCase):
    def test_v2_pins_separate_batches_without_changing_v1_or_once_bound(self):
        from race_ai import all_existing_model_future_result_capture as core
        from tests.test_all_existing_model_future_result_capture_cli import fixture
        from tests.test_jra_official_result_adapter import NOW
        old=fixture()[0];value=deepcopy(old)
        value['schema']='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2'
        value['forecast_batches']=[dict(future_artifact=value.pop('forecast_artifact'),
                                       origin_artifact=value.pop('origin_artifact'))]
        self.assertEqual(core.validate_manifest(value,now=NOW),value)
        self.assertEqual(core.validate_manifest(old,now=NOW),old)
        for change in (dict(forecast_batches=[]),dict(forecast_batches=value['forecast_batches']*2),
                       dict(maximum_requests=33),dict(forecast_artifact=old['forecast_artifact'])):
            with self.subTest(change=change),self.assertRaises(ValueError):
                core.validate_manifest(dict(value,**change),now=NOW)
        mixed=deepcopy(value);mixed['cases'][0]['race_id']=mixed['cases'][0]['race_id'].replace('2026-11-07','2026-11-06')
        with self.assertRaisesRegex(ValueError,'CASE_EVENT_DAY'):core.validate_manifest(mixed,now=NOW)

    def test_v2_admission_authenticates_all_separate_originals_and_original_source_archives(self):
        from race_ai import all_existing_model_future_result_capture as core
        from tests.test_all_existing_model_future_result_admission import admission_manifest
        value=deepcopy(separate_fixture(short_horse=True));manifest=admission_manifest(full_fixture())
        manifest['schema']='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2'
        manifest.pop('forecast_artifact');manifest.pop('origin_artifact');manifest['forecast_batches']=value['batches']
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()):
            admitted=core.admit_forecast(manifest,batch_archives=value['archives'],now=EVALUATED,key=authored.KEY)
            proof=core.admit_native_sources(admitted,value['source_archives'],now=EVALUATED,key=authored.KEY)
        self.assertEqual(len(admitted['records']),30)
        self.assertEqual(len(admitted['cases']),3)
        self.assertFalse(admitted['forecast_identity']['atomic_all_thirty_origin'])
        self.assertEqual(len(admitted['forecast_identity']['forecast_batches']),2)
        self.assertTrue(proof['source_input_receipts_verified'])


class FutureResultMultiReplayTests(unittest.TestCase):
    def test_invalid_actual_originals_reject_before_once_history_or_provider(self):
        from scripts import all_existing_model_future_result_capture as wrapper
        from tests.test_all_existing_model_future_result_admission import admission_manifest
        from tests.test_official_issue_transport import FakeGitHub
        for mode in ('late_horse','mixed_candidate','overlap','missing_model','wrong_bytes'):
            value=deepcopy(separate_fixture(short_horse=mode=='late_horse',
                mode=mode if mode in ('mixed_candidate','overlap','missing_model') else 'normal'))
            if mode=='late_horse':value['archives'][0]['origin']['metadata']['created_at']=(authored.NOW+timedelta(minutes=2)).isoformat()
            if mode=='wrong_bytes':value['archives'][0]['future']['raw']=b'changed original'
            manifest=admission_manifest(full_fixture());manifest['schema']=wrapper.core.SCHEMA_V2
            manifest.pop('forecast_artifact');manifest.pop('origin_artifact');manifest['forecast_batches']=value['batches']
            lookup={item['metadata']['id']:item for batch in value['archives'] for item in batch.values()}
            lookup.update({item['metadata']['id']:item for item in value['source_archives']})
            class Originals(wrapper.core.MarkerTransport):
                def archive(self,pin):return deepcopy(lookup[pin['id']])
            server=FakeGitHub();transport=Originals(server)
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temporary,\
                 patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()),\
                 patch.object(wrapper.common,'_node_environment'),\
                 patch.object(wrapper.common,'history',side_effect=AssertionError('invalid originals reached history')):
                env=dict(run_id=62,head_sha='f'*40,run_attempt=1,temp=Path(temporary))
                with self.assertRaises(ValueError):
                    wrapper.generate(manifest,Path(temporary)/'capture',env,marker_transport=transport,
                        clock=lambda:EVALUATED,browser=lambda *_:self.fail('no provider'),opener=lambda *_:self.fail('no provider'))
                self.assertNotIn(wrapper.core.PATH,server.snapshots[transport.head()])
                self.assertTrue(all(call[0]=='GET' for call in server.calls))

    def test_original_zip_bundle_replays_without_transport_and_rejects_changed_original(self):
        from scripts import all_existing_model_future_result_capture as wrapper
        from tests.test_all_existing_model_future_result_admission import admission_manifest
        from race_ai.boat_all_model_store import open_forecasts
        fixture=deepcopy(separate_fixture());manifest=admission_manifest(full_fixture())
        manifest['schema']='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2'
        manifest.pop('forecast_artifact');manifest.pop('origin_artifact');manifest['forecast_batches']=fixture['batches']
        lookup={item['metadata']['id']:item for batch in fixture['archives'] for item in batch.values()}
        lookup.update({item['metadata']['id']:item for item in fixture['source_archives']})
        class Retained:
            def archive(self,pin):return deepcopy(lookup[pin['id']])
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()):
            admitted,proof=wrapper._admit(manifest,now=EVALUATED,key=authored.KEY,transport=Retained())
            self.assertIn('_replay_originals',admitted,'V2 must retain exact original archives before reservation')
            env=dict(run_id=62,head_sha='f'*40)
            members=wrapper.seal_retained_forecasts(admitted,env,authored.KEY)
            journal=dict(manifest=manifest,epoch_started_at=EVALUATED.isoformat(),
                forecast_identity=admitted['forecast_identity'],native_source_proof=dict(proof,
                authenticated_future_source_sports=['autorace','horse','keirin'],original_future_source_journals_joined=True))
            with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('NO_NETWORK')):
                restored,joined=wrapper.replay_retained_forecasts(journal,members,env,
                    now=EVALUATED,key=authored.KEY)
            self.assertEqual(restored['forecast_identity'],admitted['forecast_identity'])
            self.assertEqual(joined,proof)
            for change in ('cipher','index','zip','missing','substitution','extra'):
                wrong=deepcopy(members)
                if change=='cipher':
                    raw=wrong['forecast-original-000.enc']
                    wrong['forecast-original-000.enc']=raw[:-1]+bytes([raw[-1]^1])
                elif change=='index':
                    index=open_forecasts(wrong['forecast-batches.enc'],key=authored.KEY)
                    index['batches'][0]['future']['raw_sha256']='0'*64
                    wrong['forecast-batches.enc']=wrapper._seal(index,env,authored.KEY)
                elif change=='zip':
                    from tests.test_all_existing_model_result_intake import packed
                    original=packed([('fictional.enc',b'changed original ZIP')])
                    cipher=wrapper.originals.seal_forecast_batch_original_zip(original,run_id=62,head_sha='f'*40,key=authored.KEY)
                    wrong['forecast-original-000.enc']=cipher
                    index=open_forecasts(wrong['forecast-batches.enc'],key=authored.KEY)
                    index['batches'][0]['future'].update(raw_size=len(original),raw_sha256=sha256(original).hexdigest(),
                        cipher_sha256=sha256(cipher).hexdigest())
                    wrong['forecast-batches.enc']=wrapper._seal(index,env,authored.KEY)
                elif change=='missing':wrong.pop('forecast-original-000.enc')
                elif change=='substitution':wrong['forecast-original-000.enc']=wrong['forecast-original-001.enc']
                else:wrong['forecast-original-023.enc']=wrong['forecast-original-000.enc']
                with self.subTest(change=change),self.assertRaises(ValueError):
                    wrapper.replay_retained_forecasts(journal,wrong,env,now=EVALUATED,key=authored.KEY)

    def test_actual_encrypted_v2_source_archive_and_recursive_epoch_replay_preserve_each_original(self):
        from scripts import all_existing_model_future_result_capture as wrapper
        from race_ai import all_existing_model_future_source_capture as history_core
        from tests.test_all_existing_model_future_result_admission import admission_manifest
        from tests.test_all_existing_model_future_source_history import _archive,_metadata
        value=deepcopy(separate_fixture());manifest=admission_manifest(full_fixture())
        manifest['schema']=wrapper.core.SCHEMA_V2
        manifest.pop('forecast_artifact');manifest.pop('origin_artifact');manifest['forecast_batches']=value['batches']
        lookup={item['metadata']['id']:item for batch in value['archives'] for item in batch.values()}
        lookup.update({item['metadata']['id']:item for item in value['source_archives']})
        class Retained:
            def archive(self,pin):return deepcopy(lookup[pin['id']])
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()):
            admitted,proof=wrapper._admit(manifest,now=EVALUATED,key=authored.KEY,transport=Retained())
            env=dict(run_id=62,head_sha='f'*40);root=Path(temporary);source=root/'source';source.mkdir(mode=0o700)
            browser=root/'browser';browser.mkdir(mode=0o700)
            plan=wrapper.core.prepare_plan(manifest,admitted,now=EVALUATED,expires_at=EVALUATED+timedelta(hours=1))
            history=dict(old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')
            body=wrapper.core.marker_body(manifest,env|{'run_attempt':1},admitted,history,plan,now=EVALUATED)
            marker=wrapper.core.issue_marker(body,authored.KEY)
            proof.update(authenticated_future_source_sports=['autorace','horse','keirin'],original_future_source_journals_joined=True)
            index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=EVALUATED.isoformat(),
                completed_at=EVALUATED.isoformat(),actual_request_count=0,normal_ui_only=True,manual_api_requests=0,
                responses=[],ledger=[],cases=[],stop_reason='FINISHED')
            (browser/'capture-index.json').write_text(json.dumps(index));(browser/'capture-index.json').chmod(0o600)
            inventory,complete=wrapper.common.inventory(browser,source,env,key=authored.KEY)
            self.assertTrue(complete)
            reservation=dict(schema=wrapper.core.JOURNAL_V2,state='RESERVED',manifest=manifest,manifest_sha256=digest(manifest),
                maximum_requests=32,browser_reserved_upper_bound=30,workflow_run_id=62,code_sha='f'*40,
                epoch_started_at=EVALUATED.isoformat(),forecast_identity=admitted['forecast_identity'],native_source_proof=proof,
                prior_history=history,plan_sha256=digest(plan),once_body=body)
            journal=dict(reservation,state='CAPTURE_RETAINED',completed_at=EVALUATED.isoformat(),
                raw_retention_complete=True,capture_directory_present=True,source_requests_actual=0,capture_inventory=inventory,
                browser_index=index,attempts=[],direct_wire_retention=[],direct_captures=[],observations=[],
                once_proof=dict(wrapper.core.validate_marker(marker,body,authored.KEY,now=EVALUATED),commit_sha='9'*40))
            for name,payload in (('reservation.enc',reservation),('plan.enc',plan),('collection.enc',journal)):
                wrapper._write(source/name,wrapper._seal(payload,env,authored.KEY))
            members=wrapper.seal_retained_forecasts(admitted,env,authored.KEY)
            wrapper._source_capacity(members,(source/'plan.enc').read_bytes(),(source/'reservation.enc').read_bytes(),marker)
            for name,cipher in members.items():wrapper._write(source/name,cipher)
            wrapper._write(source/'once.enc',marker)
            raw=_archive(source);metadata=_metadata(raw,6200,'official-future-result-capture-62',env,EVALUATED+timedelta(seconds=2))
            now=EVALUATED+timedelta(seconds=3)
            restored,_,_=wrapper.source_archive(raw,metadata,env,now=now,key=authored.KEY)
            self.assertEqual(restored['forecast_identity'],admitted['forecast_identity'])
            pin=dict(id=6200,digest=metadata['digest'],run_id=62,head_sha='f'*40)
            epoch,_=history_core._future_epoch(dict(raw=raw,metadata=metadata),pin,now=now,key=authored.KEY)
            self.assertEqual(epoch['schema'],wrapper.core.JOURNAL_V2)
            self.assertEqual(epoch['source_requests_actual'],0)
            (source/'forecast-batches.enc').unlink();missing=_archive(source)
            wrong=dict(metadata,digest='sha256:'+sha256(missing).hexdigest(),size_in_bytes=len(missing))
            with self.assertRaisesRegex(ValueError,'ORIGINAL_BATCH_BUNDLE_REQUIRED'):
                wrapper.source_archive(missing,wrong,env,now=now,key=authored.KEY)


class FutureResultFreshAdmissionClockTests(unittest.TestCase):
    def test_specific_original_envelope_cannot_enter_any_legacy_phase(self):
        from race_ai import boat_private_original_archive as archive
        from tests.test_all_existing_model_result_intake import packed
        seal=getattr(archive,'seal_forecast_batch_original_zip',None)
        self.assertTrue(callable(seal),'specific original envelope is missing')
        raw=packed([('original.enc',b'fictional encrypted original')])
        cipher=seal(raw,run_id=62,head_sha='f'*40,key=authored.KEY)
        self.assertEqual(archive.open_forecast_batch_original_zip(cipher,run_id=62,head_sha='f'*40,key=authored.KEY),raw)
        self.assertNotIn('FORECAST_BATCH_ORIGINAL',archive.KINDS)
        with self.assertRaises(ValueError):archive._open_envelope(cipher,key=authored.KEY)
        with self.assertRaises(ValueError):archive.seal_original_zip(raw,run_id=62,head_sha='f'*40,
            kind='FORECAST_BATCH_ORIGINAL',key=authored.KEY)
        outer=packed([('private-original.enc',cipher)])
        for phase in archive.KINDS:
            metadata=authored.metadata(6201,archive.PREFIXES[phase]+'-62',outer,saved=EVALUATED,run=62,head='f'*40)
            with self.subTest(phase=phase),self.assertRaises(ValueError),archive.open_original_zip(outer,metadata,expected_kind=phase,key=authored.KEY):pass
        for wrong in (dict(run_id=63,head_sha='f'*40),dict(run_id=62,head_sha='e'*40)):
            with self.assertRaises(ValueError):archive.open_forecast_batch_original_zip(cipher,key=authored.KEY,**wrong)

    def test_whole_source_capacity_is_checked_before_any_dispatch(self):
        from scripts import all_existing_model_future_result_capture as wrapper
        wrapper._source_capacity({'forecast-batches.enc':b'index'},b'plan',b'reservation',b'once')
        with patch.object(wrapper,'MAX_ARCHIVE',40*1024*1024),self.assertRaisesRegex(ValueError,'BEFORE_DISPATCH'):
            wrapper._source_capacity({'forecast-batches.enc':b'index'},b'plan',b'reservation',b'once')
    def test_real_utc_is_rechecked_after_admission_before_once_or_provider(self):
        from scripts import all_existing_model_future_result_capture as wrapper
        from tests.test_all_existing_model_future_result_capture_cli import fixture
        from tests.test_all_existing_model_official_result_collect import Clock
        from tests.test_jra_official_result_adapter import NOW
        from tests.test_official_issue_transport import FakeGitHub
        manifest,admitted,_,_,_=fixture();clock=Clock(NOW)
        server=FakeGitHub();transport=wrapper.core.MarkerTransport(server)
        def delayed(*_,**__):
            clock.value+=timedelta(days=1)
            return admitted,{}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()),\
             patch.object(wrapper.common,'_node_environment'),patch.object(wrapper,'_admit',side_effect=delayed),\
             patch.object(wrapper.common,'history',side_effect=AssertionError('expired manifest reached history')):
            env=dict(run_id=62,head_sha='f'*40,run_attempt=1,temp=Path(temporary))
            with self.assertRaisesRegex(ValueError,'MANIFEST_SCHEMA_DAY_OR_BOUND'):
                wrapper.generate(manifest,Path(temporary)/'capture',env,marker_transport=transport,clock=clock.now,
                    browser=lambda *_:self.fail('no provider'),opener=lambda *_:self.fail('no provider'))
            self.assertNotIn(wrapper.core.PATH,server.snapshots[transport.head()])


class FutureResultRecursiveHistoryWiringTests(unittest.TestCase):
    """Real legacy chain plus injected V2 post-auth boundary; not a ZIP claim."""
    def test_recursive_global_history_requires_the_v2_original_source_join(self):
        from race_ai import all_existing_model_future_source_capture as history
        from scripts import all_existing_model_future_result_capture as wrapper
        from tests.test_all_existing_model_future_source_history import history_fixture,_metadata,_pin,_run
        data=history_fixture();started=data['now'];env=dict(run_id=96,head_sha='e'*40)
        raw=b'SYNTHETIC_POST_AUTH_HISTORY_WIRING_ONLY'
        metadata=_metadata(raw,9600,'official-future-result-capture-96',env,started+timedelta(seconds=2));pin=_pin(metadata)
        expected=dict(authenticated_future_source_sports=['autorace','horse','keirin'],original_future_source_journals_joined=True)
        body=dict(schema=wrapper.core.JOURNAL_V2,manifest=dict(schema=wrapper.core.SCHEMA_V2,
            prior_journal_artifacts=deepcopy(data['manifest']['prior_journal_artifacts'])),
            epoch_started_at=started.isoformat(),completed_at=started.isoformat(),native_source_proof=expected)
        data['manifest']['prior_journal_artifacts'].append(pin)
        data['journal_archives'].append(dict(raw=raw,metadata=metadata))
        data['prior_runs'].append(_run(96,'e'*40,started,started+timedelta(seconds=3)))
        data['now']=started+timedelta(hours=1,seconds=4)
        original=history._future_epoch
        def epoch(item,pin,**kwargs):
            return (deepcopy(body),{'collection.enc':raw}) if pin['id']==9600 else original(item,pin,**kwargs)
        with patch.object(history,'_future_epoch',side_effect=epoch),\
             patch.object(wrapper,'replay_retained_forecasts',return_value=({},{})) as replay,\
             patch.object(wrapper.core,'bind_source_history',return_value=deepcopy(expected)) as join:
            result=history.authenticate_future_history(**data)
            self.assertEqual(result['minimum_epoch_interval_seconds'],3600)
            replay.assert_called_once();join.assert_called_once()
            join.return_value=dict(expected,original_future_source_journals_joined=False)
            with self.assertRaisesRegex(ValueError,'FUTURE_RESULT_RECURSIVE_SOURCE_BINDING'):
                history.authenticate_future_history(**data)


if __name__=='__main__':unittest.main()
