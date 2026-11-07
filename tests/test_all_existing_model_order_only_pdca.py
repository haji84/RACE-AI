"""Invented native/RESULT artifacts; real fixture crypto, no provider or real key."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import importlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_official_results as results
from race_ai.all_existing_model_learning import fit
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.boat_venue_learning import seal_candidate,read_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.official_order_only_result import EVALUATION_SCOPE
from race_ai.manual_official_capture import official_rights_ref
from tests.test_all_existing_model_matrix import _shift_dates
from tests import test_all_existing_model_order_only_auth as auth_fixtures

KEY=bytes(range(32))
NATIVE_HEAD='a'*40
RESULT_HEAD='b'*40
PDCA_HEAD='c'*40
FORECAST_AT=datetime.fromisoformat('2030-01-15T09:16:00+09:00')
EVALUATED_AT=datetime.fromisoformat('2030-01-15T13:00:10+09:00')


def archive(root):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(root.rglob('*')):
            if path.is_file():zipped.writestr(str(path.relative_to(root)),path.read_bytes())
    return output.getvalue()


def metadata(raw,ident,name,run,head,saved):
    return dict(id=ident,name=name,expired=False,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
        created_at=saved.isoformat(),expires_at=(EVALUATED_AT+timedelta(days=7)).isoformat(),
        workflow_run=dict(id=run,head_sha=head,repository_id=1416489937,head_repository_id=1416489937))


@lru_cache(maxsize=1)
def templates():
    fixture=auth_fixtures.OrderOnlyAuthenticatedResultsTests(methodName='runTest')
    values={}
    for sport in ('autorace','keirin'):
        raw,metadata,native,now,label=fixture.case(sport);native=deepcopy(native)
        native['scope']=native['snapshot']['scope']='SYNTHETIC_ONLY'
        values[sport]=(raw,metadata,native,now,label)
    return values


@lru_cache(maxsize=1)
def training():
    records=[]
    for sport,(_raw,_meta,native,_now,label) in templates().items():
        for day in range(1,9):
            payload=_shift_dates(deepcopy(native),day-15);result=_shift_dates(deepcopy(label),day-15)
            def fixed_rights(value):
                if isinstance(value,dict):
                    if 'source_rights_ref' in value:value['source_rights_ref']=official_rights_ref(sport)
                    for child in value.values():fixed_rights(child)
                elif isinstance(value,list):
                    for child in value:fixed_rights(child)
            fixed_rights(payload);fixed_rights(result)
            info=registry.identity(ALL_MODELS[0],sport,payload)
            records.append(dict(model_id=ALL_MODELS[0],sport=sport,race_id=info['race_id'],scope=info['scope'],
                stage=info['stage'],as_of=info['as_of'],cutoff_at=info['cutoff_at'],native_payload=payload,
                input_sha256=digest(payload),input_saved_at=(datetime.fromisoformat(info['as_of'])+timedelta(seconds=1)).isoformat(),
                result=result,result_observation=deepcopy(result)))
    return fit(records,now=datetime(2030,1,10,tzinfo=timezone.utc),allow_source=lambda *_:True,
               allow_training=lambda *_:True,allow_order_only=True)


class OrderOnlyPrivatePDCATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.training=training()
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_order_only_pdca'),'explicit rank-only PDCA absent')
        return importlib.import_module('race_ai.all_existing_model_order_only_pdca')
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='invented-order-pdca-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.out=self.root/'pdca'
        environment=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment.start();self.addCleanup(environment.stop)
        candidate=self.root/'candidate';seal_candidate(dict(training=deepcopy(self.training),excluded=[],summary=dict(state='FICTIONAL_FIT')),candidate)
        raw=archive(candidate)
        actual=metadata(raw,700,'all-existing-model-learning-7-1',7,NATIVE_HEAD,datetime(2030,1,10,0,0,2,tzinfo=timezone.utc))
        self.context=context_from_encrypted_artifact(raw,700,now=FORECAST_AT,_fetch=lambda _:actual)
        self.requests=[dict(cell_key=sport+'/'+ALL_MODELS[0],native_payload=deepcopy(value[2])) for sport,value in templates().items()]
        self.native_raw,self.native_meta=self.native_archive(self.requests,'pairs',800,1)
        self.captures=[dict(raw_base64=base64.b64encode(value[0]).decode(),metadata=deepcopy(value[1])) for value in templates().values()]
        self.labels=[deepcopy(value[4]) for value in templates().values()]
        self.result_raw,self.result_meta=self.result_archive()
    def native_archive(self,requests,name,ident,round_no):
        root=self.root/name;make_private_pairs(self.context,requests,root,now=FORECAST_AT,allow_source=lambda *_:True)
        (root/'summary.json').unlink();raw=archive(root)
        return raw,metadata(raw,ident,f'all-existing-model-pairs-99-{round_no}',99,NATIVE_HEAD,FORECAST_AT+timedelta(seconds=3))
    def result_archive(self,*,generated=None,saved=None):
        generated=generated or EVALUATED_AT-timedelta(seconds=10)
        payload=results.build_result_payload(self.captures,self.labels,run_id=101,code_sha=RESULT_HEAD,
            generated_at=generated,day_jst='2030-01-15',frozen_native_payloads=[r['native_payload'] for r in self.requests],allow_order_only=True)
        cipher=seal_forecasts(payload,run_id='101',round_no=1,key=KEY)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as zipped:zipped.writestr('results.enc',cipher)
        raw=output.getvalue()
        return raw,metadata(raw,900,'all-existing-official-results-101-1',101,RESULT_HEAD,saved or generated+timedelta(seconds=2))
    def score(self,**changes):
        options=dict(now=EVALUATED_AT,expected_native_run_id=99,expected_native_head_sha=NATIVE_HEAD,
            expected_result_run_id=101,expected_result_head_sha=RESULT_HEAD)
        options.update(changes)
        return self.module().score_order_only_pairs_artifacts(self.native_raw,self.native_meta,self.result_raw,self.result_meta,self.out,**options)
    def payloads(self):return [read_candidate(path) for path in self.out.iterdir() if path.is_dir()]
    def assert_no_economics(self,value):
        forbidden={'stake_yen','payout_yen','refund_yen','net_yen','roi','profit','return_rate','recovery_rate'}
        def visit(item):
            if isinstance(item,dict):
                self.assertFalse(forbidden&item.keys())
                for child in item.values():visit(child)
            elif isinstance(item,list):
                for child in item:visit(child)
        visit(value)
    def test_actual_two_archive_admission_scores_original_nineteen_fields_then_replays_ciphertext(self):
        before=deepcopy((self.requests,self.labels,self.native_meta,self.result_meta))
        summary=self.score();self.assertEqual(summary['paired_forecasts'],2)
        self.assertEqual(summary['evaluation_scope'],EVALUATION_SCOPE);self.assertFalse(summary['monetary_evaluation_available'])
        self.assertFalse(summary['independent_pdca_artifact_receipt_verified']);self.assert_no_economics(summary)
        payloads=self.payloads();self.assertEqual(len(payloads),2)
        for payload in payloads:
            self.assertTrue(self.module().verify_private_order_only_pdca(payload));self.assertIsNone(payload['training'])
            label=payload['observation'];self.assertEqual(len(label),19);self.assertEqual(label['status'],'rank_confirmed')
            self.assertFalse(label['payout_unit_verified']);self.assertIsNone(label['payout_per_100_yen'])
            self.assertEqual(payload['result_observation_sha256'],digest(label));self.assert_no_economics(payload['score'])
            pair=payload['private_forecast']['pair'];winner=label['ordered_top3']
            for arm in ('baseline','learned'):
                ranked=pair[arm+'_normalized']['ranked'];rank=next(i for i,row in enumerate(ranked,1) if row['combination']==winner)
                probability=ranked[rank-1]['score'];score=payload['score'][arm]
                self.assertEqual(score['winner_rank'],rank);self.assertEqual(score['winner_probability'],probability)
                self.assertAlmostEqual(score['log_loss'],-math.log(max(probability,1e-15)))
            self.assertEqual(payload['source_result']['artifact_id'],900)
        self.assertEqual((self.requests,self.labels,self.native_meta,self.result_meta),before)
        raw=archive(self.out);actual=metadata(raw,1000,'all-existing-model-order-only-pdca-111-1',111,PDCA_HEAD,EVALUATED_AT+timedelta(seconds=2))
        checked=self.module().verify_order_only_pdca_artifact(raw,actual,now=EVALUATED_AT+timedelta(seconds=3),
            expected_run_id=111,expected_head_sha=PDCA_HEAD)
        self.assertTrue(checked['independent_pdca_artifact_receipt_verified']);self.assertEqual(checked['paired_forecasts'],2)
        self.assert_no_economics(checked)
    def test_native_and_result_authentication_fail_closed_before_output(self):
        for kind in ('native_digest','result_digest','native_head','result_head'):
            original_native=deepcopy(self.native_meta);original_result=deepcopy(self.result_meta)
            if kind=='native_digest':self.native_meta['digest']='sha256:'+'f'*64
            elif kind=='result_digest':self.result_meta['digest']='sha256:'+'f'*64
            elif kind=='native_head':self.native_meta['workflow_run']['head_sha']='f'*40
            else:self.result_meta['workflow_run']['head_sha']='f'*40
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.score()
            self.assertFalse(self.out.exists());self.native_meta=original_native;self.result_meta=original_result
    def test_exact_cutoff_result_proof_and_score_tampering_cannot_restore(self):
        self.score();original=self.payloads()[0]
        for kind in ('cutoff','label','proof','score','scope'):
            payload=deepcopy(original)
            if kind=='cutoff':payload['observation']['closed_at']=(datetime.fromisoformat(payload['observation']['closed_at'])+timedelta(seconds=1)).isoformat()
            elif kind=='label':payload['observation']['ordered_top3']=[1,2,3]
            elif kind=='proof':payload['result_source_evidence']['sources'].pop()
            elif kind=='score':payload['score']['baseline']['log_loss']+=1
            else:payload['summary']['evaluation_scope']='CASH'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.module().verify_private_order_only_pdca(payload)
    def test_full_day_result_needs_authenticated_other_native_inputs_and_never_scores_input_only(self):
        self.native_raw,self.native_meta=self.native_archive(self.requests[:1],'only-auto',801,2)
        with self.assertRaises(ValueError):self.score()
        self.assertFalse(self.out.exists())
        extra=dict(self.requests[1],cell_key='keirin/'+ALL_MODELS[1])
        raw,actual=self.native_archive([extra],'keirin-input-only',802,3)
        summary=self.score(additional_native_artifacts=[dict(raw=raw,metadata=actual,expected_run_id=99,expected_head_sha=NATIVE_HEAD)])
        self.assertEqual(summary['paired_forecasts'],1);self.assertEqual(summary['partition_count'],1)
        self.assertEqual(summary['unmatched_order_only_results'],1)
    def test_missing_teacher_is_unscored_and_source_only_inputs_never_make_losses(self):
        self.labels=self.labels[:1];self.captures=self.captures[:1]
        self.result_raw,self.result_meta=self.result_archive()
        report=self.score();self.assertEqual(report['paired_forecasts'],1)
        pending=next(p for p in self.payloads() if p['observation'] is None)
        self.assertEqual(pending['score'],dict(state='NO_ORDER_ONLY_TEACHER',paired=False))
        cell=pending['private_forecast']['cell_key'];board=report['scoreboard'][cell]
        self.assertEqual(board['paired_forecasts'],0);self.assertIsNone(board['baseline']['mean_log_loss'])
        self.out=self.root/'no-forecasts'
        source_only=[dict(r,cell_key=r['cell_key'].split('/',1)[0]+'/'+ALL_MODELS[1]) for r in self.requests]
        self.native_raw,self.native_meta=self.native_archive(source_only,'source-only',803,4)
        report=self.score();self.assertEqual(report['partition_count'],0);self.assertEqual(report['paired_forecasts'],0)
        self.assertEqual(report['state'],'ORDER_ONLY_FROZEN_NATIVE_INPUTS_NO_FORECASTS')
        self.assertEqual(list(self.out.iterdir()),[]);self.assert_no_economics(report)

    def test_missing_published_money_is_preserved_and_cash_results_stay_outside_scope(self):
        from race_ai.autorace_official_result_adapter import parse_result
        raw=json.loads(base64.b64decode(self.captures[0]['raw_base64']))
        raw['body']['refundInfo']['rt3']['list'][0]['refund']=None
        body=json.dumps(raw,separators=(',',':')).encode();capture=self.captures[0]
        capture['raw_base64']=base64.b64encode(body).decode()
        capture['metadata'].update(source_sha256=sha256(body).hexdigest(),byte_count=len(body))
        self.labels[0]=parse_result(body,capture['metadata'],frozen_native_payload=self.requests[0]['native_payload'],
            now=EVALUATED_AT,source_rights_ref=official_rights_ref('autorace'),allow_order_only=True)
        self.assertIsNone(self.labels[0]['published_payout_yen'])
        self.result_raw,self.result_meta=self.result_archive();self.score()
        payload=next(p for p in self.payloads() if p['observation']['sport']=='autorace')
        self.assertIsNone(payload['observation']['published_payout_yen'])
        self.assertIsNone(payload['observation']['payout_per_100_yen']);self.assert_no_economics(payload['score'])
        # The same parser's explicitly unit-verified cash label is not silently
        # converted to the rank-only schema or used for monetary calculations.
        from tests import test_autorace_official_result_adapter as auto
        data=auto.fixture();cash=auto.parse_result if hasattr(auto,'parse_result') else parse_result
        cash_label=cash(auto.wire(data['result']),data['metadata'],frozen_native_payload=self.requests[0]['native_payload'],
            now=EVALUATED_AT,source_rights_ref=official_rights_ref('autorace'))
        self.captures[0]=dict(raw_base64=base64.b64encode(auto.wire(data['result'])).decode(),metadata=data['metadata'])
        self.labels[0]=cash_label;self.out=self.root/'cash-outside'
        self.result_raw,self.result_meta=self.result_archive();report=self.score()
        self.assertEqual(report['paired_forecasts'],1)
        held=next(p for p in self.payloads() if p['private_forecast']['pair']['sport']=='autorace')
        self.assertIsNone(held['observation']);self.assertEqual(report['outside_order_only_result_state_counts'],{'settled':1})
        self.assert_no_economics(report)

    def test_source_only_summary_keeps_evaluation_clock_when_server_save_is_second_precision(self):
        from race_ai.keirin_official_result_adapter import parse_result
        capture=self.captures[1]
        actual=capture['metadata'];actual['response_received_at']=(EVALUATED_AT-timedelta(seconds=10,microseconds=500000)).isoformat()
        actual['fetched_at']=(EVALUATED_AT-timedelta(seconds=11,microseconds=500000)).isoformat()
        browser=actual['keirin_result_archive_context']['browser_capture']['metadata']
        browser['captured_at']=(EVALUATED_AT-timedelta(seconds=10,microseconds=250000)).isoformat()
        browser['ledger'][1].update(request_started_at=actual['fetched_at'],response_received_at=actual['response_received_at'],
            body_captured_at=actual['response_received_at'])
        self.labels[1]=parse_result(base64.b64decode(capture['raw_base64']),capture['metadata'],
            frozen_native_payload=self.requests[1]['native_payload'],now=EVALUATED_AT,
            source_rights_ref=official_rights_ref('keirin'),allow_order_only=True)
        self.result_raw,self.result_meta=self.result_archive(generated=EVALUATED_AT-timedelta(seconds=10,microseconds=100000),
            saved=EVALUATED_AT-timedelta(seconds=11))
        source_only=[dict(r,cell_key=r['cell_key'].split('/',1)[0]+'/'+ALL_MODELS[1]) for r in self.requests]
        self.native_raw,self.native_meta=self.native_archive(source_only,'source-only-precision',804,5)
        report=self.score();self.assertEqual(report['partition_count'],0)
        self.assertEqual(report['order_only_result_count'],2)
        admitted=results.observations_from_official_result_artifact(self.result_raw,self.result_meta,now=EVALUATED_AT,
            expected_run_id=101,expected_head_sha=RESULT_HEAD,
            frozen_native_payloads=[r['native_payload'] for r in self.requests],allow_order_only=True)
        context=dict(receipt=admitted['receipt'],observations=admitted['observations'],
            source_evidence=admitted['result_source_evidence'],observations_sha256=digest(admitted['observations']))
        with self.assertRaisesRegex(ValueError,'RESULT_GENERATION_AFTER_EVALUATION'):
            self.module()._typed_results(context,EVALUATED_AT-timedelta(seconds=10,microseconds=300000))

    def test_actual_pdca_remote_identity_expiry_partial_layout_and_mixed_parts_reject(self):
        self.score();raw=archive(self.out)
        actual=metadata(raw,1000,'all-existing-model-order-only-pdca-111-1',111,PDCA_HEAD,EVALUATED_AT+timedelta(seconds=2))
        for kind in ('digest','run','head','expired','size_type','save_before_score'):
            changed=deepcopy(actual)
            if kind=='digest':changed['digest']='sha256:'+'f'*64
            elif kind=='run':changed['workflow_run']['id']=112
            elif kind=='head':changed['workflow_run']['head_sha']='f'*40
            elif kind=='expired':changed['expires_at']=EVALUATED_AT.isoformat()
            elif kind=='size_type':changed['size_in_bytes']=float(changed['size_in_bytes'])
            else:changed['created_at']=(EVALUATED_AT-timedelta(seconds=2)).isoformat()
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.module().verify_order_only_pdca_artifact(raw,changed,now=EVALUATED_AT+timedelta(seconds=3),
                    expected_run_id=111,expected_head_sha=PDCA_HEAD)
        partial=self.root/'partial';partial.mkdir(mode=0o700)
        import shutil
        folder=next(p for p in self.out.iterdir() if p.is_dir());shutil.copytree(folder,partial/folder.name)
        encoded=archive(partial);changed=metadata(encoded,1001,actual['name'],111,PDCA_HEAD,EVALUATED_AT+timedelta(seconds=2))
        with self.assertRaisesRegex(ValueError,'COMPLETE_FORECAST_SET'):
            self.module().verify_order_only_pdca_artifact(encoded,changed,now=EVALUATED_AT+timedelta(seconds=3),
                expected_run_id=111,expected_head_sha=PDCA_HEAD)

    def test_legacy_cash_pdca_still_refuses_original_or_projected_rank_only(self):
        from race_ai.all_existing_model_pdca import _observation,RESULT_FIELDS
        for label in self.labels:
            pair=dict(sport=label['sport'],race_id=label['race_id'],cutoff_at=label['closed_at'],
                baseline_normalized=dict(roster=label['roster']),learned_normalized=dict(roster=label['roster']))
            for value in (label,{key:label[key] for key in RESULT_FIELDS}):
                with self.assertRaises(ValueError):_observation(value,pair,EVALUATED_AT)


class NativeRankOnlyPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_all_existing_model_pdca_abstention import NativeSellerAbstentionTests
        NativeSellerAbstentionTests.setUpClass();cls.native=NativeSellerAbstentionTests(methodName='runTest')
    def test_actual_native_selection_abstention_and_three_five_variants_have_no_economics(self):
        from race_ai import all_existing_model_order_only_pdca as pdca
        baseline=self.native.normalized(self.native.baseline,1);learned=self.native.normalized(self.native.learned,1)
        observed=dict(ordered_top3=learned['top'][0],roster=learned['roster'])
        before=deepcopy((baseline,learned,observed))
        score=pdca._score(dict(baseline_normalized=baseline,learned_normalized=learned),observed)
        self.assertFalse(score['paired']);self.assertIsNone(score['baseline']['hit'])
        self.assertIsNone(score['baseline']['log_loss']);self.assertIsNone(score['learned']['winner_probability'])
        self.assertEqual(score['primary_native_plan'],'five')
        self.assertEqual({key:value['learned']['ticket_count'] for key,value in score['native_plan_variants'].items()},dict(three=3,five=5))
        self.assertEqual((baseline,learned,observed),before)
        OrderOnlyPrivatePDCATests.assert_no_economics(self,score)
        row=dict(forecast_record_sha256='a'*64,result_observation_sha256='b'*64,score=score)
        board=pdca._board([row]);self.assertEqual(board['paired_forecasts'],0)
        self.assertEqual(board['baseline']['abstained_forecasts'],1);self.assertEqual(board['learned']['coverage'],1.)
        self.assertIsNone(board['learned']['mean_log_loss']);OrderOnlyPrivatePDCATests.assert_no_economics(self,board)


if __name__=='__main__':unittest.main()
