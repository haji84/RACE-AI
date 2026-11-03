"""Four sports, original whole wire, retained prerequisite, fictional HTTP only."""
from pathlib import Path
import base64
import json
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def main():
    if not __debug__:raise RuntimeError('enabled assertions required')
    sys.path.insert(0,str(ROOT))
    from tests.test_fixed_model_case_profiles import v2_fixture,v2_gates,NEW_PIN
    from tests.test_offline_model_run import Clock,MODELS
    from tests.test_retained_case_submission_integration import reserve,handoff,admit,dispatch,rows
    from tests.test_permissioned_case_submission import RecordingTransport,gates
    from race_ai.permissioned_model_case import prepare_case,load_case
    records=[]
    with tempfile.TemporaryDirectory(prefix='race33-four-sport-fictional-cli-') as temp,patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
        for sport,n in (('boat',6),('keirin',7),('autorace',3),('horse',3)):
            request,raw,policy=v2_fixture(sport,n)
            original,attempt=Path(temp)/(sport+'-case.sqlite'),Path(temp)/(sport+'-attempt.sqlite')
            seal=prepare_case(original,request,raw,policy,clock=Clock(),**v2_gates(request))
            reserved=reserve(attempt,original,request,seal)
            material=handoff(original,seal,reserved,request)
            admitted=admit(attempt,original,seal,reserved,material)
            assert admitted['retention_request_sha256']==material['request_sha256']
            assert rows(attempt,'submission_intents')==0 and rows(attempt,'submission_retention')==1
            transport=RecordingTransport()
            result=dispatch(attempt,original,seal,reserved,transport)
            assert tuple(m['model_id'] for m in result['models'])==MODELS
            assert all(m['normal_acknowledged'] for m in result['models']) and not result['dispatch_barrier']
            assert [m for _,m,_ in transport.calls]==['PUT','GET']*4
            loaded=load_case(original,expected_request_sha256=seal['request_sha256'],private_path_verifier=gates()['private_path_verifier'])
            assert loaded['request']['schema']=='RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2' and loaded['request']['model_source_sha40']==NEW_PIN
            assert loaded['wire']==material['wire']
            put_bytes=[base64.b64decode(json.loads(data)['content'],validate=True) for _,method,data in transport.calls if method=='PUT']
            assert put_bytes==[json.dumps(p['anchor'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()+b'\n' for p in loaded['plans']]
            records.append(dict(sport=sport,models=len(result['models']),
                whole_wire_sha256=loaded['wire_sha256'],reservation_sha256=reserved['reservation_sha256'],
                retention_request_sha256=admitted['retention_request_sha256'],
                retention_admission_sha256=admitted['retention_admission_sha256'],
                fictional_puts=4,fictional_gets=4))
    print(json.dumps(dict(schema='RACE33_RETAINED_CASE_SYNTHETIC_V1',status='SYNTHETIC_CI_PASS',
        scope='SYNTHETIC_ONLY',source_pin=NEW_PIN,records=records,real_forecasts=0,
        real_storage_receipts_or_source_rights=False,provider_or_cloud_writes=0),sort_keys=True))


if __name__=='__main__':main()
