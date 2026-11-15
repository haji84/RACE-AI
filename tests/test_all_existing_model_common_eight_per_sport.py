"""Authored coherent native cohorts, no real sources, credentials or receipts."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import importlib
import json
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.manual_official_capture import official_rights_ref
from race_ai.observed_p1_connection import RIGHTS as BOAT_RIGHTS
from tests.test_all_existing_model_matrix import native_records
from tests.test_all_existing_model_native_future import requests,extra_requests

FIXTURE_NOW=datetime(2030,2,1,tzinfo=timezone.utc)
SPORTS=('boat','autorace','keirin','horse')
HOST={'boat':'www.boatrace.jp','autorace':'autorace.jp','keirin':'keirin.jp','horse':'www.jra.go.jp'}

def _fixture_sources(value,sport):
    if isinstance(value,dict):
        for child in value.values():_fixture_sources(child,sport)
        if 'source_rights_ref' in value:
            rights=BOAT_RIGHTS if sport=='boat' else official_rights_ref(sport)
            ref=value.get('source_ref',value.get('source_url'))
            if isinstance(ref,str) and (ref.startswith('synthetic:') or sport!='boat'):
                url='https://'+HOST[sport]+'/fixture/source/'+sha256(ref.encode()).hexdigest()
                for key in ('source_ref','source_url'):
                    if key in value:value[key]=url
                value['source_rights_ref']=rights
    elif isinstance(value,list):
        for child in value:_fixture_sources(child,sport)


def _record(mid,sport,payload,index):
    payload=deepcopy(payload);payload['scope']='SYNTHETIC_ONLY'
    if 'scope' in payload.get('snapshot',{}):payload['snapshot']['scope']='SYNTHETIC_ONLY'
    _fixture_sources(payload,sport)
    if registry.group(mid)=='autorace_personal':
        old=payload['registered_roster']['source_ref'];new='https://autorace.jp/fixture/normal-ui'
        payload['snapshot']['race']['source_url']=new
        payload['registered_roster']['source_ref']=new
        for source in payload['source_evidence']:
            if source['source_ref']==old:source['source_ref']=new
        payload['registered_roster']['native_input_sha256']=digest(payload['snapshot'])
    info=registry.identity(mid,sport,payload)
    asof=datetime.fromisoformat(info['as_of']);cutoff=datetime.fromisoformat(info['race_cutoff_at'])
    generated=asof+timedelta(seconds=10);saved=generated+timedelta(seconds=3);ident=1000+SPORTS.index(sport)*100+index
    meta=dict(id=ident,name=f'all-existing-model-pairs-42-{index+1}',expired=False,size_in_bytes=100,
        digest='sha256:'+f'{ident:064x}',created_at=saved.isoformat(),expires_at=(FIXTURE_NOW+timedelta(days=7)).isoformat(),
        workflow_run=dict(id=42,repository_id=1416489937,head_repository_id=1416489937,head_sha='a'*40))
    receipt=dict(artifact_id=ident,artifact_name=meta['name'],digest=meta['digest'],workflow_run_id=42,
        head_sha='a'*40,saved_at=meta['created_at'],independent_pre_cutoff_receipt_verified=True,artifact_metadata=meta)
    label=dict(race_id=info['race_id'],sport=sport,status='settled',ordered_top3=[1,2,3] if index%2 else [3,2,1],
        roster=deepcopy(info['roster']),identity_verified=True,captured_at=(cutoff+timedelta(minutes=1)).isoformat(),
        published_at=None,source_ref='https://'+HOST[sport]+'/fixture/result/'+str(index),
        source_rights_ref='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106' if sport=='boat' else official_rights_ref(sport),
        source_sha256=f'{index+1:064x}',payout_per_100_yen=1230,refund_numbers=[],closed_at=info['race_cutoff_at'],reason='ORDINARY_CONFIRMED')
    if sport!='boat':
        from race_ai.official_order_only_result import SCHEMA,EVALUATION_SCOPE,REASON
        label.update(schema=SCHEMA,status='rank_confirmed',payout_per_100_yen=None,published_payout_yen=1230,
                     payout_unit_verified=False,evaluation_scope=EVALUATION_SCOPE,reason=REASON)
    return dict(model_id=mid,sport=sport,race_id=info['race_id'],stage=info['stage'],scope=info['scope'],
        as_of=info['as_of'],cutoff_at=info['cutoff_at'],native_payload=payload,input_sha256=digest(payload),
        input_saved_at=saved.isoformat(),input_receipt=receipt,input_partitions=[dict(carrier_cell_key=sport+'/'+mid,
            generated_at=generated.isoformat(),training_sha256='b'*64,pair_sha256='c'*64)],
        result=label,result_observation=deepcopy(label))


def common_records(n=8):
    out=[]
    for index in range(n):
        day=f'2030-01-{15+index:02d}'
        for request in requests(day=day)+extra_requests(day=day):
            out.append(_record(request['cell_key'].split('/',1)[1],'boat',request['native_payload'],index))
    for sport in SPORTS[1:]:
        cells=[c for c in registry.cells() if c['sport']==sport]
        personal=next((c for c in cells if c['group']=='autorace_personal'),None)
        base=native_records(personal['model_id'],sport,n=n) if personal else None
        for cell in cells:
            rows=native_records(cell['model_id'],sport,n=n)
            for index,row in enumerate(rows):
                payload=deepcopy(row['native_payload'])
                if personal and cell['group']!='autorace_personal':
                    target=registry.identity(personal['model_id'],sport,base[index]['native_payload']);race=payload['snapshot']['race']
                    race.update(race_id=target['race_id'],as_of=target['as_of'],sales_cutoff_at=target['race_cutoff_at'])
                    for participant in payload['snapshot']['participants']:participant['identity']=target['roster'][str(participant['number'])]
                out.append(_record(cell['model_id'],sport,payload,index))
    return out


def result_closure_proof(row,closure):
    """Authored retained-proof shape; no external artifact authenticity claim."""
    from race_ai.all_existing_model_official_results import SOURCE_EVIDENCE_SCHEMA
    result=row['result'];captured=datetime.fromisoformat(result['captured_at'])
    generated=closure+timedelta(seconds=1);saved=closure+timedelta(seconds=3);sport=row['sport']
    metadata=dict(id=8000,name='all-existing-official-results-42-1',expired=False,size_in_bytes=100,
        digest='sha256:'+'d'*64,created_at=saved.isoformat(),expires_at=(FIXTURE_NOW+timedelta(days=7)).isoformat(),
        workflow_run=dict(id=42,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
    receipt=dict(artifact_id=8000,artifact_name=metadata['name'],digest=metadata['digest'],workflow_run_id=42,head_sha='a'*40,
        saved_at=metadata['created_at'],expires_at=metadata['expires_at'],artifact_metadata=metadata,
        authenticated_encrypted_result_artifact=True,**{name:'d'*64 for name in ('cipher_sha256','original_payload_sha256',
            'original_journal_sha256','capture_index_sha256','frozen_inputs_sha256')})
    sources=[dict(kind='MAIN_HTTP',source_ref=result['source_ref'],source_rights_ref=result['source_rights_ref'],
        source_sha256=result['source_sha256'],captured_at=result['captured_at'])]
    for kind,clock in (('IDENTITY_HTTP',captured-timedelta(seconds=1)),('RENDERED_DOM',closure)):
        sources.append(dict(kind=kind,source_ref='https://'+HOST[sport]+'/fixture/'+kind,
            source_rights_ref=official_rights_ref(sport),source_sha256='d'*64,captured_at=clock.isoformat()))
    return dict(schema=SOURCE_EVIDENCE_SCHEMA,purpose='MODEL_LABEL_NORMALIZATION',
        scope='OWNER_PERSONAL_PRIVATE_FACTUAL_ANALYSIS',provider_permission_confirmed=False,generated_at=generated.isoformat(),
        result_binding={key:deepcopy(result[key]) for key in ('sport','race_id','source_ref','source_rights_ref','source_sha256','captured_at')},
        result_observation_sha256=digest(result),artifact_receipt=receipt,source_closure_sha256='d'*64,sources=sources)


class CommonEightPerSportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rows=common_records(9)
    def select(self,rows=None):
        from scripts import all_existing_model_learning as cli
        self.assertTrue(hasattr(cli,'_select_common_eight_per_sport'),'common-eight selector absent')
        return cli._select_common_eight_per_sport(deepcopy(self.rows if rows is None else rows),now=FIXTURE_NOW)
    def test_complete_earliest_eight_all_thirty_cells_preserve_exact_originals(self):
        before=deepcopy(self.rows);selected,summary=self.select()
        self.assertEqual(len(selected),240);self.assertEqual(self.rows,before)
        self.assertEqual(summary['cohort_counts_by_sport'],{s:8 for s in SPORTS})
        self.assertEqual(summary['required_common_cells'],30);self.assertEqual(summary['record_count'],240)
        self.assertTrue(summary['common_eight_per_sport']);self.assertRegex(summary['common_cohort_sha256'],'^[a-f0-9]{64}$')
        self.assertTrue({digest(r) for r in selected}<={digest(r) for r in self.rows})
        reverse,again=self.select(list(reversed(self.rows)))
        self.assertEqual(selected,reverse);self.assertEqual(summary,again)
    def test_shortage_derived_legacy_or_unproved_inputs_cannot_fill_missing_native_cell(self):
        from race_ai.existing_model_dispatch import _race_key
        for kind in ('shortage','missing','derived','legacy','partitions','receipt','hash','clock'):
            rows=common_records();row=rows[0]
            if kind=='shortage':rows=[r for r in rows if not(r['sport']=='horse' and '2030-01-22' in r['race_id'])]
            elif kind=='missing':rows.pop(0)
            elif kind=='derived':row['input_derivation']={'fake':True}
            elif kind=='legacy':row['observed_row']={'fake':True}
            elif kind=='partitions':row.pop('input_partitions')
            elif kind=='receipt':row['input_receipt']['artifact_metadata']['expired']=True
            elif kind=='hash':row['input_sha256']='f'*64
            else:row['input_partitions'][0]['generated_at']=row['cutoff_at']
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.select(rows)
    def test_newest_generation_and_save_win_and_equal_rank_conflicts_reject(self):
        rows=common_records();new=deepcopy(rows[0]);p=new['input_partitions'][0]
        p['generated_at']=(datetime.fromisoformat(p['generated_at'])+timedelta(seconds=1)).isoformat()
        saved=(datetime.fromisoformat(new['input_saved_at'])+timedelta(seconds=1)).isoformat()
        new['input_saved_at']=new['input_receipt']['saved_at']=new['input_receipt']['artifact_metadata']['created_at']=saved
        rows.append(new);selected,_=self.select(rows)
        self.assertIn(digest(new),{digest(r) for r in selected});self.assertNotIn(digest(rows[0]),{digest(r) for r in selected})
        bad=deepcopy(new);bad['native_payload']['fixture_changed']='conflict';bad['input_sha256']=digest(bad['native_payload'])
        with self.assertRaises(ValueError):self.select(rows+[bad])
    def test_winning_order_and_money_cannot_choose_a_different_cohort(self):
        selected,_=self.select();changed=deepcopy(self.rows)
        for row in changed:
            result=row['result'];winner=result['ordered_top3'];result['ordered_top3']=winner[1:]+winner[:1]
            if row['sport']=='boat':result['payout_per_100_yen']=99990
            else:result['published_payout_yen']=99990
            row['result_observation']=deepcopy(result)
        alternate,_=self.select(changed)
        identity=lambda rows:{(r['sport'],r['model_id'],r['race_id'],r['input_sha256']) for r in rows}
        self.assertEqual(identity(selected),identity(alternate))

    def test_actual_supplemental_closure_changes_selection_without_changing_winning_order(self):
        rows=common_records(9)
        for row in rows:
            if row['sport']=='autorace' and '2030-01-15' in row['race_id']:
                row['result_source_evidence']=result_closure_proof(row,datetime.fromisoformat('2030-01-24T10:01:00+09:00'))
        before=deepcopy(rows);selected,_=self.select(rows)
        auto=[r for r in selected if r['sport']=='autorace']
        self.assertFalse(any('2030-01-15' in r['race_id'] for r in auto))
        self.assertTrue(any('2030-01-23' in r['race_id'] for r in auto))
        self.assertEqual(rows,before)
        # A lone different source closure must not silently produce different
        # train/holdout races for one native model in the common cohort.
        partial=common_records()
        row=next(r for r in partial if r['sport']=='autorace')
        row['result_source_evidence']=result_closure_proof(row,datetime.fromisoformat('2030-01-15T10:03:00+09:00'))
        with self.assertRaisesRegex(ValueError,'SOURCE_CLOSURE_CONFLICT'):self.select(partial)

    def test_conflicting_results_rosters_and_boundary_six_seven_ties_hold(self):
        for kind in ('result','roster','tie'):
            rows=common_records()
            if kind=='result':rows[0]['result']['ordered_top3']=[2,1,3]
            elif kind=='roster':rows[0]['result']['roster']['1']='different'
            else:
                dates={'2030-01-20','2030-01-21'}
                for row in rows:
                    if row['sport']=='horse' and any(day in row['race_id'] for day in dates):
                        row['result']['captured_at']='2030-01-21T10:01:00+09:00'
                        row['result_observation']=deepcopy(row['result'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.select(rows)


class CommonEightCliBoundaryTests(unittest.TestCase):
    def test_new_flag_requires_all_four_flags_and_forbids_derivation_and_explicit_ids(self):
        from scripts import all_existing_model_learning as cli
        from unittest.mock import patch
        arguments=dict(now=FIXTURE_NOW,common_eight_per_sport=True,cohort_size=8,
            full_native_boat_cohort=True,keep_other_sports=True,allow_order_only=True)
        for change in (dict(full_native_boat_cohort=False),dict(keep_other_sports=False),dict(allow_order_only=False),
                       dict(cohort_size=9),dict(cohort_size=True),dict(derive_observed=True),
                       dict(cohort_race_ids=['explicit-race']),dict(common_eight_per_sport=1)):
            with self.subTest(change=change),patch.object(cli,'load_verified_intake',side_effect=AssertionError('badflags read input')):
                with self.assertRaisesRegex(ValueError,'COMMON_EIGHT_EXPLICIT_FLAGS'):
                    cli.load_intake('unused','unused','unused',**dict(arguments,**change))

    def test_opt_in_union_preserves_versions_while_default_union_stays_exact(self):
        from scripts import all_existing_model_learning as cli
        old=common_records()[0];new=deepcopy(old)
        generated=datetime.fromisoformat(new['input_partitions'][0]['generated_at'])+timedelta(seconds=1)
        new['input_partitions'][0]['generated_at']=generated.isoformat()
        saved=(datetime.fromisoformat(new['input_saved_at'])+timedelta(seconds=1)).isoformat()
        new['input_saved_at']=new['input_receipt']['saved_at']=new['input_receipt']['artifact_metadata']['created_at']=saved
        self.assertEqual(cli._merge_native_records([old],[new]),[old])
        self.assertEqual(cli._merge_native_records([old],[new],preserve_native_versions=True),[old,new])
        self.assertEqual(cli._merge_native_records([old],[deepcopy(old)],preserve_native_versions=True),[old])
        changed=deepcopy(new);changed['input_sha256']='f'*64
        with self.assertRaises(ValueError):cli._merge_native_records([old],[changed])

    def test_shortage_in_actual_load_intake_holds_before_owner_issuer(self):
        import base64,io,os,tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        from unittest.mock import patch
        from scripts import all_existing_model_learning as cli
        from tests.test_boat_venue_research import SOURCE,CONTENT
        from tests.test_boat_venue_learning import POINTER
        rows=common_records()[:-1];metadata=dict(id=77,workflow_run=dict(id=42,head_sha='a'*40))
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);dataset=directory/'dataset.json';dataset.write_text(json.dumps(POINTER))
            arguments=['issue-decision','--restored-dir',str(directory),'--dataset-input',str(dataset),
                '--owner-research-record',str(directory/'must-not-exist.json'),'--native-archive-dir','fixture',
                '--full-native-boat-cohort','--keep-other-sports','--allow-order-only','--cohort-size','8','--common-eight-per-sport']
            output=io.StringIO()
            with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode()), \
                    patch.object(cli,'load_verified_intake',return_value=([],[],SOURCE,CONTENT)), \
                    patch.object(cli,'_native_archive',return_value=(b'fictional-private-wire',metadata)), \
                    patch.object(cli,'_reverify_native_metadata'), \
                    patch('race_ai.all_existing_model_intake.records_from_private_artifact',return_value=dict(records=rows,summary=dict(artifact_id=77))), \
                    patch.object(cli,'issue_decision',side_effect=AssertionError('issuer must not run')) as issuer,redirect_stdout(output):
                code=cli.main(arguments,now=FIXTURE_NOW)
            self.assertEqual(code,2);self.assertEqual(issuer.call_count,0)
            self.assertEqual(json.loads(output.getvalue())['reason'],'ALL_MODEL_COMMON_EIGHT_PER_SPORT_INSUFFICIENT_COMPLETE_RACES')
            self.assertFalse((directory/'must-not-exist.json').exists())

    def test_selection_intake_wrapper_is_explicit_and_default_identity_unchanged(self):
        from scripts import all_existing_model_learning as cli
        rows=common_records();selected,summary=cli._select_common_eight_per_sport(rows,now=FIXTURE_NOW)
        self.assertEqual(cli._intake_identity(selected),digest(selected))
        wrapped=cli._intake_identity(selected,common_cohort=summary)
        self.assertNotEqual(wrapped,digest(selected))
        self.assertEqual(wrapped,digest(dict(schema='RACE_AI_COMMON_EIGHT_PER_SPORT_INTAKE_V1',
            record_identity_sha256=digest(selected),common_cohort=summary)))


if __name__=='__main__':unittest.main()
