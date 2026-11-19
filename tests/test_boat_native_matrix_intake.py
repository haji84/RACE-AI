"""Real-shaped invented AES originals cross the existing main/owner boundary."""
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OWNER=Path(os.environ.get('RACE_AI_TEST_OWNER_SOURCE',ROOT/'owner-source'))
if str(OWNER) not in sys.path:sys.path.insert(0,str(OWNER))
import race_ai
for folder in (OWNER/'race_ai',OWNER/'pr64-reference/race_ai',OWNER/'pr72-reference/race_ai'):
    if str(folder) not in race_ai.__path__:race_ai.__path__.append(str(folder))
import tests
if str(OWNER/'tests') not in tests.__path__:tests.__path__.append(str(OWNER/'tests'))
import scripts
if str(OWNER/'scripts') not in scripts.__path__:scripts.__path__.append(str(OWNER/'scripts'))
from scripts import boat_owner_evidence_audit as audit
from scripts.boat_owner_national_p1_matrix import saved_view_coverage


class OfficialNativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(audit,'native_official_schedule',None)),
                        'native coverage must use the authenticated first P0 official B ledger')

    def official(self):
        from tests.test_boat_seller_official_source import fixture
        from race_ai.boat_seller_inputs import official_b_cards_source
        raw,document,receipt=fixture()
        now=datetime.fromisoformat('2030-01-15T06:30:00+09:00')
        program=official_b_cards_source(raw,document,receipt,day='2030-01-15',as_of=now)
        return document,receipt,program,now

    def test_only_raw_bound_first_p0_creates_four_field_official_ledger(self):
        document,receipt,program,now=self.official();before=deepcopy((document,receipt,program))
        ledger=audit.native_official_schedule(document,receipt,program,now=now)
        self.assertEqual(len(ledger),8)
        self.assertEqual(ledger[0],dict(race_id='20300115-17-01',cutoff_at='2030-01-15T10:01:00+09:00',
            schedule_captured_at='2030-01-15T05:00:00+09:00',source_sha256=document['source_sha256']))
        self.assertEqual((document,receipt,program),before)
        for fake in (None,True,{'verified':True},dict(program,raw=b'not-official-B')):
            with self.subTest(fake=type(fake).__name__),self.assertRaises(ValueError):
                audit.native_official_schedule(document,receipt,fake,now=now)
        changed=deepcopy(document);changed['schedule'][0]['cutoff_at']='2030-01-15T10:02:00+09:00'
        with self.assertRaises(ValueError):audit.native_official_schedule(changed,receipt,program,now=now)

    def test_missing_authenticated_context_never_uses_view_cutoffs_as_ledger(self):
        view=dict(records=[dict(race_id='20300401-24-12',cutoff_at='2030-04-01T17:30:00+09:00',
                               prediction={'PRIVATE_FORECAST':'unchanged'})])
        before=deepcopy(view)
        for context in ({},{'status':'HOLD_OFFICIAL_B_SOURCE_UNAVAILABLE'}):
            output,counts=audit.hydrate_native_matrix_view(view,context,now=datetime(2030,4,2,tzinfo=timezone.utc))
            self.assertEqual(output,view)
            self.assertEqual(counts['status'],'HOLD_NATIVE_OFFICIAL_CONTEXT')
            self.assertEqual(counts['native_pre_cutoff_qualified'],0)
        self.assertEqual(view,before)

    def test_actual_aes_native_originals_use_raw_bound_ledger_and_keep_legacy_models_held(self):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        from race_ai.observed_p1_connection import build_bundle
        from race_ai.boat_private_original_archive import seal_original_zip
        from race_ai.frozen_day_cycle import read_p1
        from race_ai.private_cycle_projection import project_state
        from race_ai.actions_contract import digest
        from race_ai.saved_view_feed import forecast_inventory
        from tests.test_observed_p1_connection import inputs,archive
        document,receipt,program,_=self.official()
        base,extra,proof=inputs();rid='20300115-17-01'
        captured='2030-01-15T09:49:00+09:00';generated='2030-01-15T09:50:00+09:00'
        now=datetime.fromisoformat('2030-01-15T09:52:00+09:00')
        base.update(race_id=rid,cutoff_at='2030-01-15T10:01:00+09:00',captured_at=captured)
        extra.update(race_id=rid,observed_at=captured)
        for field in ('program_url','preview_url'):
            proof[field]=proof[field].replace('20300401','20300115').replace('jcd=01','jcd=17')
        proof.update(program_captured_at='2030-01-15T09:48:00+09:00',preview_captured_at=captured)
        native=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
                    paired_forecasts=[build_pair(base,generated)],
                    additional_official_feature_shadows=[build_live_feature_shadow(base,extra,generated)],
                    observed_pairwise_p1_bundles=[build_bundle(base,extra,generated,**proof,owner_reviewed=True)])
        raw,metadata=archive(native,saved='2030-01-15T09:51:00+09:00')
        metadata['workflow_run'].update(repository_id=1416489937,head_sha='a'*40)
        key=bytes(range(32))  # Explicit public invented fixture, never real owner state.
        cipher=seal_original_zip(raw,run_id=99,head_sha='a'*40,kind='P1',key=key)
        wrapped=io.BytesIO()
        with zipfile.ZipFile(wrapped,'w') as z:z.writestr('private-original.enc',cipher)
        raw=wrapped.getvalue();metadata['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(key).decode()}):
            _,rows=read_p1(raw,metadata)
            state=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst='2030-01-15',
                       rows=rows,receipts=[metadata],observations=[],complete=False)
            state['state_sha256']=digest(state)
            view=project_state(state,dataset_status='SYNTHETIC_ONLY');before=deepcopy(view)
            context=dict(status='AUTHENTICATED_OWNER_NATIVE_CONTEXT',first_p0_document=document,
                         first_p0_receipt=receipt,official_program=program,
                         official_schedule=audit.native_official_schedule(document,receipt,program,now=now),
                         p1_originals=[(raw,metadata)])
            hydrated,counts=audit.hydrate_native_matrix_view(view,context,now=now)
        self.assertEqual(view,before)
        self.assertEqual(forecast_inventory(view),forecast_inventory(hydrated))
        from race_ai import boat_saved_prediction_evidence as native_reader
        if not callable(getattr(native_reader,'native_coverage_evidence',None)):
            self.assertEqual(counts['status'],'HOLD_NATIVE_READER_UNAVAILABLE')
            self.assertEqual(counts['native_pre_cutoff_qualified'],0)
        else:
            self.assertEqual(counts['status'],'AUTHENTICATED_NATIVE_COVERAGE')
            self.assertEqual(counts['native_pre_cutoff_qualified'],2)
            self.assertEqual(counts['native_pre_cutoff_held'],3)
            ids=[p['model_id'] for p in [view['records'][0]['prediction'],*view['records'][0]['comparison_predictions']]]
            result=saved_view_coverage(hydrated,day='2030-01-15',model_ids=ids,scheduled_races=8,
                                       official_schedule=context['official_schedule'],now=now)
            self.assertEqual(result['p1_qualified_unique_slots'],2)
            self.assertEqual(result['missing_p1_model_slots'],38)
            # At 09:52, only the 10:08 race is more than 15 minutes away.
            self.assertEqual(result['missing_by_time'],{'NOT_DUE':5,'PRE_CUTOFF_PENDING':33,'DEADLINE_MISSED':0})

    def test_old_owner_reader_remains_explicit_hold_without_source_or_pin_substitution(self):
        from types import ModuleType
        old=ModuleType('race_ai.boat_saved_prediction_evidence')
        old.hydrate_prediction_evidence=lambda *_args,**_kw:self.fail('old reader cannot receive new coverage input')
        view=dict(records=[]);context=dict(status='AUTHENTICATED_OWNER_NATIVE_CONTEXT')
        with patch.dict(sys.modules,{'race_ai.boat_saved_prediction_evidence':old}):
            output,counts=audit.hydrate_native_matrix_view(view,context,now=datetime.now(timezone.utc))
        self.assertEqual(output,view)
        self.assertEqual(counts,dict(status='HOLD_NATIVE_READER_UNAVAILABLE',native_pre_cutoff_qualified=0))

    def test_existing_workflow_passes_actual_private_context_to_native_hydration(self):
        import ast,textwrap
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        stage=text.split("python - <<'PY_ALL_MODEL'\n",1)[1].split('\n          PY_ALL_MODEL',1)[0]
        code=ast.parse(textwrap.dedent(stage))
        calls=[n for n in ast.walk(code) if isinstance(n,ast.Call)]
        bindings=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='inspect_run']
        self.assertEqual(len(bindings),1)
        self.assertTrue(any(k.arg=='private_native' and isinstance(k.value,ast.Name) for k in bindings[0].keywords))
        hydrators=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='hydrate_native_matrix_view']
        self.assertEqual(len(hydrators),1)
        self.assertEqual(hydrators[0].args[1].id,'native_context')


if __name__=='__main__':unittest.main()
