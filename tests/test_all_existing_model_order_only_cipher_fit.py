"""Eight authored AUTO cases traverse both real AES archives and native fit."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import unittest
import zipfile
from race_ai.actions_contract import digest
from race_ai import all_existing_model_learning as learning
from race_ai.all_existing_model_intake import records_from_private_artifact
from race_ai.all_existing_model_official_results import build_result_payload,seal_results,observations_from_official_result_artifact
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.autorace_official_sparse_adapter import build_requests
from race_ai.autorace_official_result_adapter import parse_result
from race_ai.boat_venue_learning import seal_candidate
from race_ai.boat_venue_learning_context import _candidate_from_zip
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.manual_official_capture import official_rights_ref
from scripts.all_existing_model_learning import _attach_result_source_evidence,_record_source_refs
from tests import test_autorace_official_sparse_adapter as source
from tests import test_autorace_official_result_adapter as result
from tests import test_all_existing_model_source_packet_freeze as context_fixture

b64=lambda raw:base64.b64encode(raw).decode()
def packed(members):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in members:archive.writestr(name,raw)
    return out.getvalue()

class OrderOnlyCipherFitTests(unittest.TestCase):
    def _admitted_records(self,*,common_dom=False):
        fixture=context_fixture.SourcePacketFreezeTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        context=fixture.context();requests=[];observations=[];captures=[];frozen=[]
        rights=official_rights_ref('autorace')
        for number in range(1,9):
            data=source.fixture();data['race']['body']['raceNo']=number
            data['metadata']['scope']='OPERATOR_SUPPLIED_RESEARCH'
            data['dom']=data['dom'].replace('予選1R'.encode(),f'予選{number}R'.encode())
            data['metadata']['rendered_dom']=dict(byte_count=len(data['dom']),source_sha256=sha256(data['dom']).hexdigest())
            request=source.wire(dict(placeCode=3,raceDate='2030-01-15',raceNo=number));request_sha=sha256(request).hexdigest()
            data['request_bodies']={request_sha:request}
            for index,name in enumerate(('program','race')):
                raw=source.wire(data[name]);data['metadata']['ledger'][index].update(
                    source_sha256=sha256(raw).hexdigest(),byte_count=len(raw),request_body_sha256=request_sha)
            prepared=build_requests(source.wire(data['program']),source.wire(data['race']),data['dom'],data['metadata'],
                now=source.NOW,source_rights_ref=rights,request_bodies=data['request_bodies'])
            self.assertEqual(prepared['state'],'READY');self.assertEqual(len(prepared['requests']),6)
            requests.extend(prepared['requests'])
            native=next(r['native_payload'] for r in prepared['requests'] if r['cell_key']=='autorace/'+ALL_MODELS[0]);frozen.append(native)
            observed=result.fixture();metadata=observed['metadata'];metadata.pop('auto_result_archive_context',None)
            metadata.update(fetched_at=(result.NOW-timedelta(minutes=5)+timedelta(seconds=number-1)).isoformat(),
                response_received_at=(result.NOW-timedelta(minutes=5)+timedelta(seconds=number)).isoformat())
            ctx=metadata['auto_result_context'];req=source.wire(dict(placeCode=3,raceDate='2030-01-15',raceNo=str(number)))
            ctx['request_body_base64']=b64(req);metadata['request_body_sha256']=sha256(req).hexdigest()
            info=ctx['race_info_capture'];body=json.loads(base64.b64decode(info['raw_base64']));body['body']['raceNo']=str(number)
            raw=source.wire(body);info.update(raw_base64=b64(raw),request_body_base64=b64(req))
            info['metadata'].update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),request_body_sha256=sha256(req).hexdigest())
            dom=ctx['rendered_dom_capture'];body=base64.b64decode(dom['raw_base64']).replace(b'1R',str(number).encode()+b'R')
            dom['raw_base64']=b64(body);dom['metadata'].update(byte_count=len(body),source_sha256=sha256(body).hexdigest(),
                final_url=dom['metadata']['final_url'].rsplit('_',1)[0]+'_'+str(number),
                captured_at=(result.NOW-timedelta(minutes=4)+timedelta(seconds=8 if common_dom else 9-number)).isoformat())
            raw=source.wire(observed['result'])
            label=parse_result(raw,metadata,frozen_native_payload=native,now=result.NOW,source_rights_ref=rights,allow_order_only=True)
            observations.append(label);captures.append(dict(raw_base64=b64(raw),metadata=metadata))
        output=fixture.root/'pairs';make_private_pairs(context,requests,output,now=source.NOW,allow_source=lambda *_:True)
        native_raw=packed((folder.name+'/'+name,(folder/name).read_bytes()) for folder in output.iterdir() if folder.is_dir()
            for name in ('learning.enc','learning.json','summary.json'))
        def metadata(raw,identity,name,saved):
            return dict(id=identity,name=name,expired=False,digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
                created_at=saved.isoformat(),expires_at=(result.NOW+timedelta(days=7)).isoformat(),workflow_run=dict(
                    id=42,head_sha=context_fixture.HEAD,repository_id=1416489937,head_repository_id=1416489937))
        native_meta=metadata(native_raw,1100,'all-existing-model-pairs-42-1',source.NOW+timedelta(seconds=2))
        payload=build_result_payload(captures,observations,run_id=42,code_sha=context_fixture.HEAD,generated_at=result.NOW,
            day_jst='2030-01-15',frozen_native_payloads=frozen,allow_order_only=True)
        raw=packed([('results.enc',seal_results(payload,round_no=1,frozen_native_payloads=frozen,allow_order_only=True))])
        actual=metadata(raw,1101,'all-existing-official-results-42-1',result.NOW+timedelta(seconds=2));now=result.NOW+timedelta(seconds=10)
        admitted=observations_from_official_result_artifact(raw,actual,now=now,expected_run_id=42,
            expected_head_sha=context_fixture.HEAD,frozen_native_payloads=frozen,allow_order_only=True)
        records=records_from_private_artifact(native_raw,native_meta,admitted['observations'],now=now,
            expected_run_id=42,expected_head_sha=context_fixture.HEAD)['records']
        records=_attach_result_source_evidence(records,admitted['result_source_evidence'],now=now)
        self.assertEqual(len(records),48)
        for row in records:
            self.assertEqual(row['input_sha256'],digest(row['native_payload']))
            self.assertEqual(row['result'],row['result_observation'])
            self.assertTrue({(s['source_ref'],s['source_rights_ref']) for s in row['result_source_evidence']['sources']}<=_record_source_refs(row))
        return records,now,fixture

    def test_eight_cipher_cases_fit_six_native_cells_restore_and_bind_actual_teacher(self):
        records,now,fixture=self._admitted_records()
        trained=learning.fit(records,now=now,allow_order_only=True,allow_source=lambda *_:True,allow_training=lambda *_:True)
        learning.verify_training(trained);self.assertEqual(len(trained['models']),6)
        self.assertEqual({(m['unique_races'],m['train_races'],m['validation_races']) for m in trained['models'].values()},{(8,6,2)})
        expected_available=(result.NOW-timedelta(minutes=4)+timedelta(seconds=8)).isoformat()
        self.assertEqual(trained['data_available_until'],expected_available)
        for model in trained['models'].values():
            self.assertEqual(set(model['validation_race_ids']),
                {'autorace:2030-01-15:isesaki:1','autorace:2030-01-15:isesaki:2'})
            for line in model['source_lineage']:
                self.assertGreater(learning.ts(line['result_source_available_at']),learning.ts(line['result_captured_at']))
        folder=fixture.root/'trained';seal_candidate(dict(training=trained,excluded=[],summary=dict(state=trained['state'],
            fitted_model_count=6,production_promoted=False,actual_purchases=False,plaintext_published=False)),folder)
        archive=packed((name,(folder/name).read_bytes()) for name in ('learning.enc','learning.json','summary.json'))
        restored=_candidate_from_zip(archive)['training'];learning.verify_training(restored)
        self.assertEqual(restored,trained)
        altered=deepcopy(trained);key=next(iter(altered['models']));model=altered['models'][key];line=model['source_lineage'][0]
        line['result_label']['ordered_top3'][0:2]=list(reversed(line['result_label']['ordered_top3'][0:2]))
        line['result_label_sha256']=digest(line['result_label'])
        model['model_sha256']=digest({k:v for k,v in model.items() if k!='model_sha256'})
        altered['training_sha256']=digest({k:v for k,v in altered.items() if k!='training_sha256'})
        with self.assertRaises(ValueError):learning.verify_training(altered)

    def test_equal_source_closure_availability_cannot_fake_a_chronological_six_two_split(self):
        records,now,_=self._admitted_records(common_dom=True)
        trained=learning.fit(records,now=now,allow_order_only=True,allow_source=lambda *_:True,allow_training=lambda *_:True)
        learning.verify_training(trained)
        self.assertEqual(trained['models'],{})
        self.assertEqual(trained['state'],'NO_FITTED_MODELS')

if __name__=='__main__':unittest.main()
