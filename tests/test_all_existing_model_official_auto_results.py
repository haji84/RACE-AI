"""Fictional normal-UI AUTO source closure plus actual encrypted admission."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import unittest
import zipfile

from race_ai import all_existing_model_official_results as results
from race_ai.autorace_official_result_adapter import parse_result
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.manual_official_capture import official_rights_ref
from tests import test_autorace_official_result_adapter as fixture

KEY=bytes(range(32))
HEAD='a'*40


def unit_capture():
    raw='<html><body><p>払戻金は100円に対する金額です。</p></body></html>'.encode()
    url='https://autorace.jp/guide/fixture-payout-unit'
    metadata=dict(source_url=url,final_url=url,status=200,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
        fetched_at=(fixture.NOW-timedelta(minutes=20,seconds=1)).isoformat(),
        response_received_at=(fixture.NOW-timedelta(minutes=20)).isoformat(),
        headers={'content-type':'text/html; charset=utf-8'})
    return dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata)


class AutoraceOfficialResultsArchiveTests(unittest.TestCase):
    def setUp(self):
        data=fixture.fixture();self.native=data['frozen'];self.raw=fixture.wire(data['result'])
        self.meta=data['metadata'];self.generated=fixture.NOW;self.now=self.generated+timedelta(seconds=10)
        self.meta['auto_result_archive_context']=dict(schema='RACE_AI_AUTORACE_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1',
            payout_unit_capture=unit_capture())
        self.observation=parse_result(self.raw,self.meta,frozen_native_payload=self.native,now=self.generated,
            source_rights_ref=official_rights_ref('autorace'))
        self.capture=dict(raw_base64=base64.b64encode(self.raw).decode(),metadata=deepcopy(self.meta))

    def payload(self,capture=None,observation=None):
        return results.build_result_payload([self.capture if capture is None else capture],
            [self.observation if observation is None else observation],run_id=42,code_sha=HEAD,
            generated_at=self.generated,day_jst='2030-01-15',frozen_native_payloads=[self.native])

    def read(self,payload):
        cipher=seal_forecasts(payload,run_id='42',round_no=1,key=KEY)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        raw=stream.getvalue()
        metadata=dict(id=801,name='all-existing-official-results-42-1',expired=False,size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(),created_at=(self.generated+timedelta(seconds=2)).isoformat(),
            expires_at=(self.generated+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=HEAD,
                repository_id=1416489937,head_repository_id=1416489937))
        return results.observations_from_official_result_artifact(raw,metadata,now=self.now,
            expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native],key=KEY)

    def test_actual_cipher_binds_normal_ui_request_companion_dom_and_explicit_unit(self):
        payload=self.payload();before=deepcopy(payload)
        results.seal_results(payload,round_no=1,frozen_native_payloads=[self.native],key=KEY)
        admitted=self.read(payload)
        self.assertEqual(admitted['observations'],[self.observation]);self.assertEqual(payload,before)
        self.assertEqual(admitted['summary']['ordinary_settled_result_count'],1)
        proof=admitted['result_source_evidence'][0]
        self.assertEqual(proof['purpose'],'MODEL_LABEL_NORMALIZATION')
        self.assertFalse(proof['provider_permission_confirmed'])
        self.assertEqual({s['kind'] for s in proof['sources']},
            {'MAIN_HTTP','IDENTITY_HTTP','RENDERED_DOM','PAYOUT_UNIT_HTTP'})
        self.assertEqual(results.verify_result_source_evidence(proof,result=self.observation,now=self.now),
            {(s['source_ref'],s['source_rights_ref']) for s in proof['sources']})
        public=json.dumps([admitted['summary'],admitted['receipt']])
        for private in ('auto_result_context','request_body_base64','raw_base64','ordered_top3','roster','21710',self.meta['source_url']):
            self.assertNotIn(private,public)

    def test_supplemental_source_evidence_cannot_change_result_receipt_or_clocks(self):
        admitted=self.read(self.payload());original=admitted['result_source_evidence'][0]
        for kind in ('result','digest','source_clock','source_host','purpose','permission','missing_source'):
            proof=deepcopy(original)
            if kind=='result':proof['result_binding']['source_sha256']='f'*64
            elif kind=='digest':proof['artifact_receipt']['digest']='sha256:'+'f'*64
            elif kind=='source_clock':proof['sources'][-1]['captured_at']=(self.generated+timedelta(seconds=1)).isoformat()
            elif kind=='source_host':proof['sources'][-1]['source_ref']='https://jra.go.jp/guide/unit'
            elif kind=='purpose':proof['purpose']='PROVIDER_PERMISSION'
            elif kind=='permission':proof['provider_permission_confirmed']=True
            else:proof['sources']=[s for s in proof['sources'] if s['kind']!='MAIN_HTTP']
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                results.verify_result_source_evidence(proof,result=self.observation,now=self.now)

    def test_source_closure_cannot_contain_unhashed_unbounded_or_future_capture(self):
        for kind in ('companion_hash','dom_hash','unit_hash','unit_host','companion_extra','dom_extra',
                     'context_extra','unit_schema','dom_future','unit_future','oversize'):
            capture=deepcopy(self.capture);metadata=capture['metadata'];context=metadata['auto_result_context']
            if kind=='companion_hash':context['race_info_capture']['metadata']['source_sha256']='f'*64
            elif kind=='dom_hash':context['rendered_dom_capture']['metadata']['source_sha256']='f'*64
            elif kind=='unit_hash':metadata['auto_result_archive_context']['payout_unit_capture']['metadata']['source_sha256']='f'*64
            elif kind=='unit_host':metadata['auto_result_archive_context']['payout_unit_capture']['metadata']['source_url']='https://jra.go.jp/guide/unit'
            elif kind=='companion_extra':context['race_info_capture']['unsealed']='ignored'
            elif kind=='dom_extra':context['rendered_dom_capture']['metadata']['extra']='ignored'
            elif kind=='context_extra':context['unsealed']='ignored'
            elif kind=='unit_schema':metadata['auto_result_archive_context']['schema']='UNTYPED'
            elif kind=='dom_future':context['rendered_dom_capture']['metadata']['captured_at']=(self.generated+timedelta(seconds=1)).isoformat()
            elif kind=='unit_future':metadata['auto_result_archive_context']['payout_unit_capture']['metadata']['response_received_at']=(self.generated+timedelta(seconds=1)).isoformat()
            else:context['race_info_capture']['raw_base64']=base64.b64encode(b'x'*(2*1024*1024+1)).decode()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.payload(capture)

    def test_unit_proof_is_required_for_normal_labels_and_cannot_be_self_asserted(self):
        for kind in ('missing','minimum_bet_only','false_grant'):
            capture=deepcopy(self.capture);metadata=capture['metadata']
            if kind=='missing':metadata.pop('auto_result_archive_context')
            elif kind=='false_grant':metadata['auto_result_archive_context']['payout_unit_capture']['metadata']['source_rights_ref']='arbitrary'
            else:
                unit=metadata['auto_result_archive_context']['payout_unit_capture'];raw='<p>車券は100円から購入できます。</p>'.encode()
                unit['raw_base64']=base64.b64encode(raw).decode();unit['metadata'].update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.payload(capture)

    def test_pending_observations_remain_unscored_without_a_unit_claim(self):
        data=fixture.fixture();data['result']['body']['raceResult']=[]
        data['result']['body']['refundInfo']['rt3']['list']=[]
        raw=fixture.wire(data['result']);metadata=data['metadata'];metadata.pop('auto_result_archive_context',None)
        metadata.update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
        observation=parse_result(raw,metadata,frozen_native_payload=self.native,now=self.generated,
            source_rights_ref=official_rights_ref('autorace'))
        capture=dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata)
        admitted=self.read(self.payload(capture,observation))
        self.assertEqual(admitted['summary']['pending_result_count'],1)
        self.assertEqual(admitted['summary']['ordinary_settled_result_count'],0)
        self.assertIsNone(admitted['observations'][0]['payout_per_100_yen'])

    def test_unused_auto_frozen_input_cannot_expand_horse_only_archive_bound(self):
        from race_ai.jra_official_result_adapter import parse_result as horse_result
        from tests import test_jra_official_result_adapter as horse
        native=horse.frozen();captures=[];observations=[]
        original=horse.result_html()
        raw=original+b'<!--'+b'x'*(1_900_000-len(original)-7)+b'-->'
        self.assertEqual(len(raw),1_900_000)
        for number in range(9):
            metadata=horse.source_metadata(raw)
            metadata.update(fetched_at=(horse.NOW-timedelta(seconds=30-number, microseconds=1)).isoformat(),
                response_received_at=(horse.NOW-timedelta(seconds=30-number)).isoformat())
            captures.append(dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata))
            observations.append(horse_result(raw,metadata,frozen_native_payload=native,now=horse.NOW,
                source_rights_ref=official_rights_ref('horse')))
        for frozen in ([native],[native,self.native]):
            with self.subTest(unused_auto=len(frozen)==2),self.assertRaisesRegex(ValueError,'TOTAL_CAPTURE_BOUND'):
                results.build_result_payload(captures,observations,run_id=42,code_sha=HEAD,
                    generated_at=horse.NOW,day_jst='2026-11-07',frozen_native_payloads=frozen)


if __name__=='__main__':unittest.main()
