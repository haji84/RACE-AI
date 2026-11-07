"""Actual fictional capsule admission keeps capture and generation separate."""
from copy import deepcopy
from datetime import timedelta
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_learning as learning
from tests import test_all_existing_model_intake as fixtures


class NativeGenerationClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.AllExistingModelIntakeTests.setUpClass()

    def setUp(self):
        self.case=fixtures.AllExistingModelIntakeTests(methodName='runTest')
        self.case.records=fixtures.AllExistingModelIntakeTests.records
        self.case.training=fixtures.AllExistingModelIntakeTests.training
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.record=next(r for r in self.case.intake()['records'] if 'observed-' in r['model_id'])

    def test_source_capture_never_substitutes_for_the_authenticated_generation(self):
        before=deepcopy(self.record)
        actual=learning._native_replay_at(self.record,now=self.case.now)
        self.assertEqual(actual,self.record['input_partitions'][0]['generated_at'])
        self.assertNotEqual(actual,self.record['as_of'])
        self.assertEqual(self.record,before)
        lineage=learning._lineage(self.record,now=self.case.now)
        self.assertEqual(lineage['actual_native_generated_at'],actual)
        self.assertEqual(lineage['native_generation_receipt_sha256'],digest(self.record['input_receipt']))
        self.assertEqual(lineage['native_generation_partitions_sha256'],digest(self.record['input_partitions']))

    def test_malformed_conflicting_future_or_late_generation_proofs_stop(self):
        variants=[]
        for kind in ('before_input','after_save','cutoff','future','extra','conflict','digest','repo','unverified'):
            row=deepcopy(self.record);part=row['input_partitions'][0]
            if kind=='before_input':part['generated_at']=(learning.ts(row['as_of'])-timedelta(seconds=1)).isoformat()
            elif kind=='after_save':part['generated_at']=(learning.ts(row['input_saved_at'])+timedelta(seconds=1)).isoformat()
            elif kind=='cutoff':part['generated_at']=row['cutoff_at']
            elif kind=='future':part['generated_at']=(self.case.now+timedelta(seconds=1)).isoformat()
            elif kind=='extra':part['unsupported_time']='invented'
            elif kind=='conflict':
                second=deepcopy(part);second['generated_at']=(learning.ts(part['generated_at'])+timedelta(milliseconds=1)).isoformat()
                row['input_partitions'].append(second)
            elif kind=='digest':row['input_receipt']['digest']='sha256:'+'0'*64
            elif kind=='repo':row['input_receipt']['artifact_metadata']['workflow_run']['repository_id']=1
            else:row['input_receipt']['independent_pre_cutoff_receipt_verified']=False
            variants.append((kind,row))
        for kind,row in variants:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                learning._native_replay_at(row,now=self.case.now)

    def test_no_partitions_keeps_legacy_input_clock_and_lineage_bytes(self):
        from tests.test_all_existing_model_learning import observed_records
        row=observed_records()[0]
        self.assertEqual(learning._native_replay_at(row,now=self.case.now),row['as_of'])
        self.assertNotIn('actual_native_generated_at',learning._lineage(row,now=self.case.now))

    def test_legacy_fitted_artifact_bytes_keep_pre_generation_clock_golden_hashes(self):
        from tests.test_all_existing_model_learning import observed_records
        from tests.test_observed_weight_learning import NOW
        expected={True:'886068e3a3527a87a5609e6f6bebaaa0a37a5ebc38353a7af90aaf392067d882',
            False:'706b0ce243a6b755fc8c87159ec8dff9acb7375cf16a53359c4af20a0e3fcee5'}
        for synthetic,sha in expected.items():
            fitted=learning.fit(observed_records(synthetic=synthetic),now=NOW,
                allow_source=lambda *_:True,allow_training=lambda *_:True)
            with self.subTest(synthetic=synthetic):
                self.assertEqual(fitted['training_sha256'],sha)
                learning.verify_training(fitted)


if __name__=='__main__':unittest.main()
