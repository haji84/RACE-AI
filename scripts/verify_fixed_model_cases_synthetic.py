"""Four authored sports through fixed V2 producer/case/typed-wire boundaries.

No provider source, HTTP, external retention, source authority or formal score.
The test callbacks below are explicit fiction, never an operational default.
"""
from pathlib import Path
import json
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def main():
    if not __debug__:raise RuntimeError('enabled assertions required')
    sys.path.insert(0,str(ROOT))
    from tests.test_fixed_model_case_profiles import v2_fixture,v2_gates,NEW_PIN,PROFILE
    from tests.test_offline_model_run import Clock,MODELS,VERSIONS
    from race_ai.permissioned_model_case import prepare_case,load_case
    from race_ai.model_suite_settlement import audit_model_settlements
    from race_ai.comprehensive_four_sport_models import validate
    records=[]
    with tempfile.TemporaryDirectory(prefix='race32-four-sport-fictional-') as temp,patch('socket.create_connection',side_effect=AssertionError('parent network forbidden')):
        for sport,n in (('boat',6),('keirin',7),('autorace',3),('horse',3)):
            request,raw,policy=v2_fixture(sport,n)
            path=Path(temp)/(sport+'.sqlite')
            prepared=prepare_case(path,request,raw,policy,clock=Clock(),**v2_gates(request))
            assert prepared['status']=='PREPARED_NOT_EXTERNAL_FROZEN'
            loaded=load_case(path,expected_request_sha256=prepared['request_sha256'],private_path_verifier=lambda *a,**kw:True)
            models=loaded['delivery']['research_suite']['models']
            assert list(models)==list(MODELS)
            assert all(m['candidate_count']==n*(n-1)*(n-2) and len(m['ordered_top8'])==min(8,n*(n-1)*(n-2)) for m in models.values())
            audit=audit_model_settlements(request['ledger'],[],[{'race_id':request['race_id'],'delivery':loaded['delivery']}],[],
                expected_model_ids=MODELS,expected_model_versions=VERSIONS,expected_model_source_sha40=NEW_PIN,
                model_contract=PROFILE,validate_snapshot=validate,allow_source=policy.authorize)
            assert all(m['formal_hit_at_8_all'] is None for m in audit['models'].values())
            assert all(m['source_records_preserved']==2 for m in audit['models'].values())
            records.append({'sport':sport,'participants':n,'models':len(models),
                'request_sha256':prepared['request_sha256'],'wire_sha256':loaded['wire_sha256'],
                'complete_candidates_per_model':n*(n-1)*(n-2),'selected_per_model':min(8,n*(n-1)*(n-2))})
    print(json.dumps({'schema':'RACE32_FIXED_CASES_SYNTHETIC_V1','status':'SYNTHETIC_CI_PASS',
        'scope':'SYNTHETIC_ONLY','source_pin':NEW_PIN,'records':records,'real_forecasts':0,
        'real_source_or_external_freeze_or_scores':False,'cloud_or_provider_writes':0},sort_keys=True))


if __name__=='__main__':main()
