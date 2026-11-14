"""Controller source-union tests; ciphertext/source replay has separate suites."""
from copy import deepcopy
import json
import unittest
from race_ai.actions_contract import digest
from scripts import all_existing_model_learning as cli
from tests import test_all_existing_model_official_auto_results as auth
from tests import test_all_existing_model_learning_ci as ci_fixtures

class OrderOnlyCliScopeTests(unittest.TestCase):
    def test_authenticated_supplemental_sources_join_without_changing_native_bytes(self):
        fixture=auth.AutoraceOfficialResultsArchiveTests(methodName='runTest');fixture.setUp()
        admitted=fixture.read(fixture.payload());original=fixture.observation
        row=dict(sport='autorace',race_id=original['race_id'],result=deepcopy(original),
            result_observation=deepcopy(original),native_payload=deepcopy(fixture.native))
        before=deepcopy(row)
        records=cli._attach_result_source_evidence([row],admitted['result_source_evidence'],now=fixture.now)
        self.assertEqual(row,before);self.assertEqual(records[0]['native_payload'],before['native_payload'])
        self.assertEqual(records[0]['result_source_evidence'],admitted['result_source_evidence'][0])
        sources=cli._record_source_refs(records[0])
        self.assertTrue({(s['source_ref'],s['source_rights_ref']) for s in
            admitted['result_source_evidence'][0]['sources']}<=sources)
        altered=deepcopy(admitted['result_source_evidence']);altered[0]['result_observation_sha256']='f'*64
        with self.assertRaises(ValueError):cli._attach_result_source_evidence([row],altered,now=fixture.now)
    def test_ci_v4_explicitly_selects_order_only_full_native_and_other_sports(self):
        fixture=ci_fixtures.ExistingModelLearningCiTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        document=deepcopy(fixture.manifest)
        document.update(schema='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V4',full_native_boat_cohort=True,
            keep_other_sports=True,allow_order_only=True)
        seen=[]
        def fit(arguments,*,now):
            seen.extend(arguments);print(json.dumps(dict(state='FITTED_SHADOW_ONLY',fitted_model_count=20)));return 0
        code,_,_=fixture.invoke(document,fit=fit)
        self.assertEqual(code,0)
        for arg in ('--full-native-boat-cohort','--keep-other-sports','--allow-order-only'):self.assertIn(arg,seen)
        self.assertNotIn('--derive-from-observed',seen)
        for field in ('allow_order_only','keep_other_sports'):
            changed=deepcopy(document);changed[field]=False
            code,_,_=fixture.invoke(changed,fit=fit)
            self.assertEqual(code,2)

if __name__=='__main__':unittest.main()
