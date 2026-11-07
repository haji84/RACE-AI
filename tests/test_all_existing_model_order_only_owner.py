"""Explicit order-only owner intent; old owner records retain their bytes."""
import base64
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch
from race_ai import all_existing_model_research as research
from race_ai.actions_contract import digest
from race_ai.official_order_only_result import EVALUATION_SCOPE
from tests import test_all_existing_model_crypto as owner_fixtures

class OrderOnlyOwnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=owner_fixtures.AllModelOwnerDecisionTests(methodName='runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.args=self.fixture.arguments()
    def issue(self,**changes):
        arguments=dict(self.args,**changes)
        return research.issue_decision(**arguments,expires_at=arguments['now']+timedelta(days=30))
    def test_new_owner_schema_and_purpose_explicitly_bind_label_scope_and_every_source(self):
        arguments=dict(self.args,label_evaluation_scope=EVALUATION_SCOPE)
        record=self.issue(label_evaluation_scope=EVALUATION_SCOPE)
        self.assertEqual(record['schema'],'RACE_AI_ALL_EXISTING_MODEL_OWNER_PERSONAL_RESEARCH_V2')
        self.assertEqual(record['decision']['purpose'],'EXISTING_ALL_FAMILIES_ORDER_ONLY_SHADOW_FIT')
        self.assertEqual(record['decision']['label_evaluation_scope'],EVALUATION_SCOPE)
        self.assertEqual(research.verify_decision(record,**arguments),digest(record))
        for changed in (dict(self.args),dict(arguments,label_evaluation_scope='CASH'),
                        dict(arguments,intake_sha256='f'*64),
                        dict(arguments,source_refs=self.args['source_refs']+[('https://autorace.jp/guide/unit',
                            'OWNER_PERSONAL_OFFICIAL_AUTORACE_FACTUAL_ANALYSIS_20261107')])):
            with self.subTest(change=changed),self.assertRaises(ValueError):research.verify_decision(record,**changed)
        legacy=self.issue()
        with self.assertRaises(ValueError):research.verify_decision(legacy,**arguments)
    def test_legacy_owner_record_has_no_new_fields_and_keeps_golden_bytes(self):
        with patch.dict('os.environ',RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode()):
            record=self.issue()
        self.assertEqual(record['schema'],research.SCHEMA)
        self.assertNotIn('label_evaluation_scope',record['decision'])
        self.assertEqual(digest(record),'a918bc9321513edd8fcbf2093fd2bde2d5fee6b4b15b6fa33a84965c5e3f90ae')

if __name__=='__main__':unittest.main()
