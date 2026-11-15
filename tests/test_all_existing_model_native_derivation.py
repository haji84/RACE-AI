"""Fictional encrypted P1 originals; newly derived bytes have today's clock."""
from copy import deepcopy
from datetime import timedelta
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_derivation as derivation
from race_ai.all_existing_model_learning import fit
from race_ai.boat_observed_pairwise_models import FEATURE_TRANSFORMS,MODEL_IDS as OBSERVED
from race_ai import all_existing_model_pairs as pairs
from race_ai.all_existing_model_intake import records_from_private_artifact
from tests import test_all_existing_model_pairs as fixtures
from tests.test_all_existing_model_learning import observed_records
from tests.test_all_existing_model_derivation import originals,NOW


class NativeObservedDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training=fit(observed_records(),now=fixtures.NOW)

    def setUp(self):
        fixture=fixtures.AllExistingModelPrivatePairsTests(methodName='runTest')
        fixture.records=observed_records();fixture.training=self.training
        fixture.cell=next(iter(self.training['models']));fixture.setUp()
        self.addCleanup(fixture.doCleanups);self.fixture=fixture
        native=fixture.native();snapshot=native['snapshot'];snapshot['stage']='P1'
        source=snapshot['sources'][0]['source_id']
        for entrant in snapshot['participants']:
            for name,value in (('exhibition_time_seconds',6.71+entrant['lane']*.01),
                               ('exhibition_start_seconds',.10+entrant['lane']*.01)):
                entrant['missing'].pop(name,None)
                entrant['features'][name]=dict(value=value,sample_n=None,source_id=source,
                    transform_id=FEATURE_TRANSFORMS[name])
        requests=[dict(cell_key='boat/'+mid,native_payload=deepcopy(native)) for mid in OBSERVED]
        pairs.make_private_pairs(fixture.context,requests,fixture.root/'pairs',now=fixtures.FORECAST_NOW,
                                 allow_source=lambda *_:True)
        raw,_=fixture.archive();metadata=fixture.metadata(raw)
        result=fixture.observation(source_ref='https://www.boatrace.jp/fixture-result',
            source_rights_ref='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106',published_at=None)
        self.now=fixtures.FORECAST_NOW+timedelta(hours=1)
        self.originals=records_from_private_artifact(raw,metadata,[result],now=self.now,
            expected_run_id=99,expected_head_sha=fixtures.HEAD)['records']

    def derive(self,records=None,now=None):
        return derivation.derive_records(self.originals if records is None else records,
            now=now or self.now,include_groups=('shared','shared_learned','boat_full'))

    def test_actual_authenticated_native_capsules_derive_seven_cells_with_v2_proof(self):
        before=deepcopy(self.originals);rows=self.derive()
        self.assertEqual(len(rows),7);self.assertEqual(self.originals,before)
        for row in rows:
            proof=row['input_derivation'];original=proof['original_record']
            self.assertEqual(proof['schema'],'RACE_AI_EXISTING_MODEL_INPUT_DERIVATION_V2')
            self.assertEqual(proof['derived_at'],self.now.isoformat())
            self.assertFalse(proof['historical_native_payload_bytes'])
            self.assertFalse(proof['derived_payload_saved_before_cutoff'])
            self.assertEqual(proof['original_input_receipt_sha256'],digest(original['input_receipt']))
            self.assertEqual(proof['original_snapshot_sha256'],digest(original['native_payload']['snapshot']))
            self.assertEqual(row['input_saved_at'],original['input_saved_at'])
            self.assertEqual(row['as_of'],original['as_of']);self.assertEqual(row['stage'],'P1')
            self.assertTrue(derivation.verify_derivation(row,now=self.now,
                allow_source=lambda *_:True,allow_training=lambda *_:True))
            snapshot=row['native_payload']['snapshot']
            if 'entrants' in snapshot:
                self.assertTrue(all(set(p['features'])=={'ability_rating','motor_rating',
                    'exhibition_time_seconds','exhibition_start_seconds'} for p in snapshot['entrants']))
            else:
                self.assertTrue(all('stamina' in p['missing'] for p in snapshot['participants']))
        self.assertEqual(rows,self.derive(list(reversed(self.originals))))

    def test_rehashed_receipt_native_result_or_false_history_claim_cannot_pass_replay(self):
        baseline=self.derive()[0]
        for kind in ('input','receipt','result','saved','claim','future'):
            row=deepcopy(baseline);proof=row['input_derivation'];original=proof['original_record']
            if kind=='input':
                original['native_payload']['snapshot']['participants'][0]['registration_no']='9999'
                original['input_sha256']=digest(original['native_payload'])
            elif kind=='receipt':original['input_receipt']['artifact_id']=999
            elif kind=='result':original['result']['ordered_top3']=list(reversed(original['result']['ordered_top3']))
            elif kind=='saved':original['input_saved_at']=original['cutoff_at']
            elif kind=='claim':proof['historical_native_payload_bytes']=True
            else:proof['derived_at']=(self.now+timedelta(seconds=1)).isoformat()
            proof['original_record_sha256']=digest(original)
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                derivation.verify_derivation(row,now=self.now,allow_source=lambda *_:True,
                                             allow_training=lambda *_:True)

    def test_legacy_v1_records_and_scope_hashes_remain_exact(self):
        from scripts.all_existing_model_learning import _intake_identity
        goldens={'P0':('2f3b066a9d5d2c9906c0c928e75cb6db43d034b2972b099de8cc90378902d1ef',
                       '82102f591f41b37ab070ac2ff7333298a185211b92592f48d0ed6f4e550c8215'),
                 'P1':('fab66b097f25fd53fbf3a9c706cd832f47e4aed502dde18e04e6193b9faf7bbf',
                       'a3849829804f76a58c60d6c66e24f51edae7f84d9a65e26352f0e46c77889750')}
        for stage,(payload_sha,scope_sha) in goldens.items():
            rows=derivation.derive_records(originals(stage),now=NOW,
                include_groups=('shared','shared_learned','boat_full'))
            self.assertEqual(digest(rows),payload_sha);self.assertEqual(_intake_identity(rows),scope_sha)


if __name__=='__main__':unittest.main()
