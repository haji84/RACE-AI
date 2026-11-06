"""Explicit owner intake expansion; invented originals, actual fitter/MAC/AES."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
import io,json,os
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.all_existing_model_research import issue_decision,verify_decision
from race_ai.boat_venue_learning import read_candidate
from scripts import all_existing_model_learning as cli
from tests.test_boat_venue_research import personal_data,SOURCE,CONTENT
from tests.test_boat_venue_learning import NOW,POINTER

class DerivedLearningCliTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.dataset=self.root/'dataset.json';self.dataset.write_text(json.dumps(POINTER))
        self.rows,self.observations=personal_data(8)
        env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode())
        env.start();self.addCleanup(env.stop)
    def authenticated(self):return deepcopy((self.rows,self.observations,SOURCE,CONTENT))
    def load(self,derived=False):
        with patch.object(cli,'load_verified_intake',return_value=self.authenticated()) as reader:
            value=cli.load_intake(self.root/'restored','source',self.dataset,now=NOW,derive_observed=derived)
        self.assertIs(reader.call_args.kwargs['authenticate_owner_cipher'],True)
        return value
    def test_default_intake_stays_sixteen_originals_and_new_mode_has_seventy_two_records(self):
        original,binding,_=self.load()
        records,derived,intake=self.load(True)
        self.assertEqual(len(original),16);self.assertEqual(len(records),72)
        self.assertEqual(records[:16],original);self.assertEqual(len({r['model_id'] for r in records}),9)
        self.assertNotEqual(binding['intake_sha256'],derived['intake_sha256'])
        self.assertEqual(binding['source_refs'],derived['source_refs'])
        self.assertEqual(intake['derived_record_count'],56)
        for record in records[16:]:
            proof=record['input_derivation']
            self.assertFalse(proof['derived_payload_saved_before_cutoff'])
            self.assertEqual(record['input_saved_at'],proof['original_input_saved_at'])
            self.assertEqual(proof['derived_at'],NOW.isoformat())
    def test_reexecution_preserves_data_scope_but_records_actual_new_derivation_clock(self):
        first,binding,_=self.load(True)
        later=NOW+timedelta(minutes=5)
        with patch.object(cli,'load_verified_intake',return_value=self.authenticated()):
            second,new,_=cli.load_intake(self.root/'restored','source',self.dataset,now=later,derive_observed=True)
        self.assertEqual(binding['intake_sha256'],new['intake_sha256'])
        self.assertNotEqual(digest(first),digest(second))
        self.assertEqual(second[16]['input_derivation']['derived_at'],later.isoformat())
        changed=deepcopy(second);changed[16]['native_payload']['snapshot']['participants'][0]['identity']='9999'
        self.assertNotEqual(cli._intake_identity(changed),binding['intake_sha256'])
        decision=issue_decision(**binding,now=NOW,expires_at=NOW+timedelta(days=1))
        verify_decision(decision,**new,now=later)

    def test_old_explicit_decision_cannot_silently_admit_derived_records(self):
        _,old,_=self.load();_,expanded,_=self.load(True)
        decision=issue_decision(**old,now=NOW,expires_at=NOW+timedelta(days=1))
        with self.assertRaises(ValueError):verify_decision(decision,**expanded,now=NOW)
    def test_explicit_new_scope_fits_nine_native_cells_and_readbacks_actual_cipher(self):
        decision=self.root/'derived-decision.json';out=self.root/'candidate'
        args=['--restored-dir',str(self.root/'restored'),'--state-input','source',
            '--dataset-input',str(self.dataset),'--derive-from-observed',
            '--owner-research-record',str(decision),'--out-dir',str(out)]
        for command in ('issue-decision','fit'):
            public=io.StringIO()
            with patch.object(cli,'load_verified_intake',return_value=self.authenticated()),redirect_stdout(public):
                code=cli.main([command,*args],now=NOW)
            self.assertEqual(code,0,public.getvalue())
        result=json.loads(public.getvalue());payload=read_candidate(out)
        self.assertTrue(result['encrypted_readback_verified']);self.assertEqual(result['fitted_model_count'],9)
        self.assertEqual(result['missing_or_unfitted_cells'],22)
        self.assertEqual(result['derived_record_count'],56)
        self.assertFalse(result['derived_payloads_saved_before_cutoff'])
        self.assertEqual(len(payload['training']['models']),9)
        self.assertTrue(all((m['train_races'],m['validation_races'])==(6,2) for m in payload['training']['models'].values()))
        self.assertNotIn('weights',public.getvalue());self.assertNotIn('native_payload',public.getvalue())
    def test_special_and_dead_heat_are_excluded_without_a_fabricated_winner(self):
        from race_ai.all_existing_model_intake import _legacy_boat
        original=deepcopy(self.observations[0])
        for state in ('special','dead_heat'):
            changed=deepcopy(original);changed['data'].update(status=state,top3=None,payouts=[])
            self.assertEqual(_legacy_boat(changed)['status'],'special')

if __name__=='__main__':unittest.main()
