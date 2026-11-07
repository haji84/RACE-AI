"""Authored KEIRIN normal-UI closure; encrypted reader replay, no real sources."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import unittest
import zipfile
from race_ai import all_existing_model_official_results as results
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.keirin_official_result_adapter import parse_result
from race_ai.manual_official_capture import official_rights_ref
from tests import test_keirin_official_result_adapter as fixture
KEY=bytes(range(32))
HEAD='a'*40

class KeirinOfficialResultsArchiveTests(unittest.TestCase):
    def setUp(self):
        _,self.raw,self.metadata,self.native=fixture.fixture()
        self.now=fixture.NOW+timedelta(seconds=10)
        self.observation=parse_result(self.raw,self.metadata,frozen_native_payload=self.native,
            now=fixture.NOW,source_rights_ref=official_rights_ref('keirin'))
        self.capture=dict(raw_base64=base64.b64encode(self.raw).decode(),metadata=self.metadata)
    def payload(self,capture=None):
        return results.build_result_payload([self.capture if capture is None else capture],[self.observation],
            run_id=42,code_sha=HEAD,generated_at=fixture.NOW,day_jst='2030-01-15',frozen_native_payloads=[self.native])
    def read(self,payload):
        cipher=seal_forecasts(payload,run_id='42',round_no=1,key=KEY);stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        raw=stream.getvalue();metadata=dict(id=901,name='all-existing-official-results-42-1',expired=False,
            size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(fixture.NOW+timedelta(seconds=2)).isoformat(),expires_at=(fixture.NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
        return results.observations_from_official_result_artifact(raw,metadata,now=self.now,
            expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native],key=KEY)
    def test_actual_cipher_replays_full_normal_ui_chain_and_retains_all_source_pairs(self):
        value=self.read(self.payload());self.assertEqual(value['observations'],[self.observation])
        proof=value['result_source_evidence'][0]
        self.assertEqual({s['kind'] for s in proof['sources']},
            {'MAIN_HTTP','IDENTITY_HTTP','RENDERED_DOM','PAYOUT_UNIT_HTTP'})
        self.assertEqual(results.verify_result_source_evidence(proof,result=self.observation,now=self.now),
            {(s['source_ref'],s['source_rights_ref']) for s in proof['sources']})
    def test_nested_source_metadata_and_browser_capture_are_bound_before_replay(self):
        for kind in ('identity_hash','identity_host','identity_future','browser_hash','browser_future',
                     'browser_flag','unit_future','namespace','selector'):
            capture=deepcopy(self.capture);context=capture['metadata']['keirin_result_archive_context']
            if kind=='identity_hash':context['identity_capture']['metadata']['source_sha256']='f'*64
            elif kind=='identity_host':context['identity_capture']['metadata']['source_url']='https://autorace.jp/result'
            elif kind=='identity_future':context['identity_capture']['metadata']['response_received_at']=(fixture.NOW+timedelta(seconds=1)).isoformat()
            elif kind=='browser_hash':context['browser_capture']['metadata']['rendered_dom']['source_sha256']='f'*64
            elif kind=='browser_future':context['browser_capture']['metadata']['captured_at']=(fixture.NOW+timedelta(seconds=1)).isoformat()
            elif kind=='browser_flag':context['browser_capture']['metadata']['undocumented_api_manually_called']=True
            elif kind=='unit_future':context['payout_unit_capture']['metadata']['response_received_at']=(fixture.NOW+timedelta(seconds=1)).isoformat()
            elif kind=='namespace':context['extra']='unsupported'
            else:capture['metadata']['source_url']=capture['metadata']['source_url'].replace('selector-2','selector-3')
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.payload(capture)

if __name__=='__main__':unittest.main()
