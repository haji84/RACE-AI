"""Authored rank-only teachers exercise existing objectives, never cash PDCA."""
from copy import deepcopy
from datetime import datetime,timedelta
import unittest
from race_ai import all_existing_model_learning as learning
from race_ai import all_existing_model_registry as registry
from race_ai.actions_contract import digest
from race_ai.manual_official_capture import official_rights_ref
from race_ai.official_order_only_result import SCHEMA,EVALUATION_SCOPE,REASON
from tests.test_all_existing_model_matrix import native_records,NOW
from tests import test_all_existing_model_official_auto_results as auth
HOST={'autorace':'autorace.jp','keirin':'keirin.jp','horse':'www.jra.go.jp'}

class OrderOnlyLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cash=[r for cell in registry.cells() if cell['sport']!='boat'
            for r in native_records(cell['model_id'],cell['sport'])]
        cls.typed=deepcopy(cls.cash)
        for row in cls.typed:
            result=row['result'];published=result['payout_per_100_yen']
            result.update(schema=SCHEMA,status='rank_confirmed',payout_per_100_yen=None,published_payout_yen=published,
                payout_unit_verified=False,evaluation_scope=EVALUATION_SCOPE,reason=REASON,
                closed_at=row['cutoff_at'],source_ref='https://'+HOST[row['sport']]+'/fictional/result',
                source_rights_ref=official_rights_ref(row['sport']))
            row['result_observation']=deepcopy(result)
    def test_explicit_order_mode_fits_all_sixteen_nonboat_cells_with_identical_top3_objectives(self):
        before=deepcopy(self.typed)
        with self.assertRaisesRegex(ValueError,'ORDER_ONLY'):learning.fit(self.typed,now=NOW)
        baseline=learning.fit(self.cash,now=NOW)
        trained=learning.fit(self.typed,now=NOW,allow_order_only=True);learning.verify_training(trained)
        self.assertEqual(self.typed,before);self.assertEqual(len(trained['models']),16)
        self.assertEqual(trained['label_evaluation_scope'],EVALUATION_SCOPE)
        self.assertFalse(trained['monetary_evaluation_available'])
        self.assertEqual({k:v['parameters'] for k,v in baseline['models'].items()},
            {k:v['parameters'] for k,v in trained['models'].items()})
        for model in trained['models'].values():
            self.assertEqual((model['unique_races'],model['train_races'],model['validation_races']),(8,6,2))
            self.assertEqual(model['label_evaluation_scopes'],[EVALUATION_SCOPE])
            for line in model['source_lineage']:
                self.assertEqual(line['result_label']['status'],'rank_confirmed')
                self.assertIsNone(line['result_label']['payout_per_100_yen'])
                self.assertEqual(line['result_label_sha256'],digest(line['result_label']))
        altered=deepcopy(trained);key=next(iter(altered['models']));model=altered['models'][key]
        model['source_lineage'][0]['result_label']['status']='settled'
        model['source_lineage'][0]['result_label_sha256']=digest(model['source_lineage'][0]['result_label'])
        model['model_sha256']=digest({k:v for k,v in model.items() if k!='model_sha256'})
        altered['training_sha256']=digest({k:v for k,v in altered.items() if k!='training_sha256'})
        with self.assertRaises(ValueError):learning.verify_training(altered)
    def test_every_supplemental_normalization_source_requires_training_admission(self):
        fixture=auth.AutoraceOfficialResultsArchiveTests(methodName='runTest');fixture.setUp()
        admitted=fixture.read(fixture.payload());proof=admitted['result_source_evidence'][0]
        payload=deepcopy(fixture.native);payload['scope']='OPERATOR_SUPPLIED_RESEARCH'
        payload['snapshot']['scope']=payload['scope'];mid=registry.cells()[0]['model_id']
        mid=next(c['model_id'] for c in registry.cells() if c['sport']=='autorace' and c['group']=='shared')
        info=registry.identity(mid,'autorace',payload)
        row=dict(model_id=mid,sport='autorace',race_id=info['race_id'],stage=info['stage'],scope=info['scope'],
            as_of=info['as_of'],cutoff_at=info['cutoff_at'],native_payload=payload,input_sha256=digest(payload),
            input_saved_at=(datetime.fromisoformat(info['as_of'])+timedelta(seconds=1)).isoformat(),
            input_receipt={'kind':'AUTHORED_FIXTURE'},result=fixture.observation,
            result_observation=fixture.observation,result_source_evidence=proof)
        original=digest(payload);calls=[]
        def allowed(url,rights,purpose):calls.append((url,rights));return True
        learning._record(row,fixture.now,lambda *_:True,allowed)
        self.assertTrue({(s['source_ref'],s['source_rights_ref']) for s in proof['sources']}<=set(calls))
        guide=next(s['source_ref'] for s in proof['sources'] if s['kind']=='PAYOUT_UNIT_HTTP')
        with self.assertRaisesRegex(ValueError,'TRAINING_PERMISSION'):
            learning._record(row,fixture.now,lambda *_:True,lambda url,*_:url!=guide)
        self.assertEqual(digest(row['native_payload']),original)

    def test_typed_original_label_cannot_disagree_with_the_actual_objective(self):
        row=deepcopy(self.typed[0]);row['result_observation']['ordered_top3']=[2,3,1]
        with self.assertRaisesRegex(ValueError,'ORDER_ONLY_ORIGINAL_LABEL'):
            learning.fit([row],now=NOW,allow_order_only=True)

if __name__=='__main__':unittest.main()
