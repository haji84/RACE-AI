"""Private live-site context and fail-closed browser admission, using inventions."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import boat_saved_site_context as C

NOW=datetime(2030,4,1,0,0,tzinfo=timezone.utc)
BOOTSTRAP=dict(key=b'x'*32,view_id='a'*64)


def invented_view():
    def p(model,cutoff,generated='2030-03-31T23:50:00Z'):
        return dict(stage='P1',model_id=model,native_dispatch_prediction=True,
            external_receipt_verified=True,eligible_pre_cutoff=True,cutoff_at=cutoff,
            generated_at=generated,as_of=generated,persisted_at=generated)
    def row(number,prediction,*,day='2030-04-01',status='pending',comparisons=()):
        return dict(sport='boat',race_id=day.replace('-','')+'-01-'+str(number).zfill(2),
            event_date_jst=day,prediction=prediction,comparison_predictions=list(comparisons),
            result=dict(status=status))
    first=p('invented-one','2030-04-01T00:10:00Z')
    later=p('invented-two','2030-04-01T00:20:00Z')
    past=p('invented-one','2030-03-31T23:40:00Z','2030-03-31T23:30:00Z')
    return dict(records=[row(1,None,comparisons=[first]),row(2,later),row(3,past,status='final'),
                         row(1,None,day='2030-03-31',status='void')])


def native_p0_view():
    """Use the same native reader/projection as actual first-P0 recovery."""
    from race_ai.actions_contract import digest
    from race_ai.boat_saved_view_intake import project_native_state
    from race_ai.frozen_day_cycle import read_p0
    from tests.test_frozen_day_cycle import sample
    _,raw,receipt=sample()
    receipt['workflow_run'].update(repository_id=1416489937,head_sha='b'*40)
    document,rows=read_p0(raw,receipt,expected_day='2030-04-01')
    documents=[dict(artifact_id=receipt['id'],member_name='forecasts.json',
                    member_sha256=rows[0]['original_json_sha256'],document=document)]
    state=dict(schema='RACE_AI_PRIVATE_ARTIFACT_READBACK_V1',day_jst='2030-04-01',
        rows=rows,receipts=[receipt],observations=[],original_documents=documents,
        complete=False,coverage_scope='EXPLICIT_ARTIFACTS_ONLY',excluded_repeats=[])
    state['state_sha256']=digest(state)
    return project_native_state(state,documents=documents)


def original_report(view):
    prediction=view['records'][0]['prediction']
    return dict(status='FIRST_P0_RECONCILED',original_id=prediction['artifact_id'],
        json_sha256=prediction['original_json_sha256'],source_sha=prediction['source_code_commit'],
        day_jst=view['records'][0]['event_date_jst'])


class ContextTests(unittest.TestCase):
    def test_expected_original_filters_native_and_model_switch_probes_without_shifting_indices(self):
        view=native_p0_view();expected=original_report(view);row=view['records'][0]
        originals=[row['prediction'],*row['comparison_predictions']]
        others=deepcopy(originals)
        for prediction in others:
            prediction.update(artifact_id=999,original_json_sha256='c'*64,source_code_commit='d'*40)
        row['prediction']=others[0];row['comparison_predictions']=[*others[1:],*originals]
        context=C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0',expected_original=expected)
        self.assertEqual(context['native_probe']['index'],2)
        self.assertEqual(context['native_probe']['artifact_id'],expected['original_id'])
        self.assertEqual([choice['index'] for choice in context['model_switch_probe']['choices']],[2,3])
        self.assertEqual(context['native_group_count'],2)
        self.assertEqual(context['expected_original'],{key:expected[key] for key in
            ('original_id','json_sha256','source_sha','day_jst')})
        row['prediction']=others[0];row['comparison_predictions']=others[1:]
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_EXPECTED_ORIGINAL_MISSING'):
            C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0',expected_original=expected)

    def test_expected_original_report_requires_reconciliation_status_and_exact_typed_identity(self):
        view=native_p0_view();expected=original_report(view)
        for field,value in (('status','FIRST_P0_RECONCILIATION_REJECTED'),('original_id',True),
                            ('json_sha256','bad'),('source_sha','bad'),('day_jst','2030-04-02')):
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'SAVED_SITE_EXPECTED_ORIGINAL_INVALID'):
                C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0',
                    expected_original=dict(expected,**{field:value}))
        context=C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0',
            expected_original=dict(expected,status='HOLD_OFFICIAL_RESULTS_INCOMPLETE'))
        self.assertEqual(context['expected_original']['original_id'],expected['original_id'])

    def test_native_recovered_p0_does_not_satisfy_default_p1(self):
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_NATIVE_P1_REQUIRED'):
            C.build_context(BOOTSTRAP,native_p0_view(),12,now=NOW+timedelta(hours=2))

    def test_explicit_p0_uses_real_native_receipt_without_inventing_dispatch_flags_or_generation(self):
        view=native_p0_view();before=deepcopy(view)
        prediction=view['records'][0]['prediction']
        self.assertNotIn('native_dispatch_prediction',prediction)
        self.assertNotIn('eligible_pre_cutoff',prediction)
        self.assertIsNone(prediction['generated_at'])
        context=C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0')
        self.assertEqual(view,before)
        self.assertEqual(context['stage'],'P0')
        self.assertEqual(context['native_group_count'],2)
        self.assertEqual(context['native_p0_groups'],2)
        self.assertNotIn('native_p1_groups',context)
        probe=context['native_probe']
        self.assertEqual(probe['stage'],'P0')
        self.assertEqual(probe['model_id'],prediction['model_id'])
        self.assertEqual(probe['tickets_sha256'],hashlib.sha256(
            json.dumps(prediction['ordered_top8'],separators=(',',':')).encode()).hexdigest())

    def test_p0_receipt_stage_and_native_hash_bindings_cannot_be_bypassed(self):
        for field,value,reason in (
            ('external_receipt_verified',False,'NATIVE_P0_REQUIRED'),
            ('eligible_pre_cutoff',False,'NATIVE_P0_REQUIRED'),
            ('stage','P1','NATIVE_P0_REQUIRED'),
            ('prediction_sha256','f'*64,'NATIVE_P0_IDENTITY_INVALID'),
            ('original_json_sha256',None,'NATIVE_P0_IDENTITY_INVALID'),
            ('source_code_commit',None,'NATIVE_P0_IDENTITY_INVALID'),
            ('artifact_id',0,'NATIVE_P0_IDENTITY_INVALID'),
        ):
            view=native_p0_view()
            for row in view['records']:
                for prediction in [row['prediction'],*row['comparison_predictions']]:
                    prediction[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'SAVED_SITE_'+reason):
                C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0')

    def test_p0_originals_require_saved_precutoff_times_and_never_fabricate_missing_fields(self):
        for field in ('as_of','persisted_at','generated_at'):
            view=native_p0_view();prediction=view['records'][0]['prediction']
            prediction[field]=prediction['cutoff_at']
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'SAVED_SITE_ORIGINAL_CLOCK_INVALID'):
                C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0')
        view=native_p0_view();prediction=view['records'][0]['prediction']
        prediction['server_saved_at']='2030-04-01T01:42:59Z'
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_ORIGINAL_CLOCK_INVALID'):
            C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),stage='P0')
        # Optional provider/input metadata stays optional in the native contract.
        view=native_p0_view()
        for row in view['records']:
            for prediction in [row['prediction'],*row['comparison_predictions']]:
                prediction['source_sha256']=None;prediction['input_sha256']=None
        self.assertEqual(C.build_context(BOOTSTRAP,view,12,now=NOW+timedelta(hours=2),
            stage='P0')['native_group_count'],2)

    def test_native_stage_is_explicitly_limited_to_p0_or_p1(self):
        for stage in ('P2','UNKNOWN',None):
            with self.subTest(stage=stage),self.assertRaisesRegex(ValueError,'SAVED_SITE_STAGE_INVALID'):
                C.build_context(BOOTSTRAP,invented_view(),12,now=NOW,stage=stage)

    def test_model_switch_probe_binds_distinct_models_to_their_stored_ticket_hashes(self):
        view=invented_view();row=view['records'][0];first=row['comparison_predictions'][0];first['ordered_top8']=[[1,2,3],[1,3,2]];row['cutoff_at']=first['cutoff_at']
        peer=deepcopy(first);peer.update(model_id='invented-peer',ordered_top8=[[2,1,3]]);row['comparison_predictions'].append(peer)
        before=deepcopy(view);context=C.build_context(BOOTSTRAP,view,12,now=NOW)
        probe=context.get('model_switch_probe');self.assertIsNotNone(probe)
        self.assertEqual([p['model_id'] for p in probe['choices']],['invented-one','invented-peer'])
        self.assertEqual(probe['choices'][0]['tickets_sha256'],hashlib.sha256(b'[[1,2,3],[1,3,2]]').hexdigest())
        self.assertEqual(probe['choices'][1]['index'],1);self.assertEqual(view,before)

    def test_live_beforeinfo_probe_is_private_and_keeps_the_original_view_unchanged(self):
        from tests.test_racer_beforeinfo import preview_view,html,AT
        from race_ai.racer_intraday import IntradayState
        from race_ai.racer_beforeinfo import collect_beforeinfo,project_beforeinfo
        view=invented_view();row=preview_view()['records'][0];row['prediction']=deepcopy(view['records'][0]['comparison_predictions'][0]);row['prediction']['cutoff_at']=row['cutoff_at'];view['records'].append(row)
        state=IntradayState();collect_beforeinfo(state,[row],now=AT,fetch=lambda u:(html(),AT.isoformat()),max_requests=4);row['live_boat_observation']=project_beforeinfo(row,state,now=AT)
        before=deepcopy(view);context=C.build_context(BOOTSTRAP,view,12,now=AT)
        self.assertEqual(context['live_beforeinfo_races'],1)
        self.assertEqual(context['live_beforeinfo_probe'],dict(race_id='20300401-12-12',cutoff_at='2030-04-01T20:30:00+09:00'))
        self.assertEqual(view,before)

    def test_explicit_saved_day_after_midnight_keeps_the_actual_clock(self):
        later=NOW+timedelta(days=1)
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_CURRENT_DAY_REQUIRED'):C.build_context(BOOTSTRAP,invented_view(),12,now=later)
        context=C.build_context(BOOTSTRAP,invented_view(),12,now=later,event_day='2030-04-01')
        self.assertEqual(context['day'],'2030-04-01');self.assertIsNone(context['future_native']);self.assertEqual(context['minimum_results'],1)
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_FUTURE_NATIVE_REQUIRED'):C.build_context(BOOTSTRAP,invented_view(),12,now=later,event_day='2030-04-01',require_future=True)
    def test_uses_real_clocks_filtered_option_indices_and_latest_future_cutoff(self):
        view=invented_view();before=deepcopy(view)
        context=C.build_context(BOOTSTRAP,view,12,now=NOW,require_future=True)
        self.assertEqual(view,before);self.assertEqual(context['native_p1_groups'],2)
        self.assertEqual(context['minimum_results'],1);self.assertEqual(context['old_completed'],1)
        self.assertEqual(context['old_day'],'2030-03-31')
        self.assertEqual(context['day_races'],3)
        self.assertEqual(len(context['native_groups']),2)
        self.assertEqual(context['native_probe']['index'],0)
        self.assertEqual(context['future_native']['race_id'],'20300401-01-02')
        self.assertEqual(context['future_native']['index'],0)
        self.assertEqual(base64.urlsafe_b64decode(context['owner_url'].split('.')[-1]+'='),BOOTSTRAP['key'])

    def test_retired_primary_does_not_shift_native_picker_indices(self):
        view=invented_view()
        for row in view['records'][:2]:
            active=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]
            seller=deepcopy(active[0]);seller.update(model_id='seller-shadow-v1-20261104',stage='P0')
            row['prediction']=seller;row['comparison_predictions']=active
        before=deepcopy(view)
        context=C.build_context(BOOTSTRAP,view,12,now=NOW,require_future=True)
        self.assertEqual(context['native_probe']['index'],0)
        self.assertEqual(context['future_native']['index'],0)
        self.assertEqual(context['native_p1_groups'],2)
        self.assertEqual(view,before)

    def test_absent_future_is_not_promoted_into_a_pre_cutoff_display_receipt(self):
        context=C.build_context(BOOTSTRAP,invented_view(),12,now=NOW+timedelta(hours=1))
        self.assertIsNone(context['future_native'])
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_FUTURE_NATIVE_REQUIRED'):
            C.build_context(BOOTSTRAP,invented_view(),12,now=NOW+timedelta(hours=1),require_future=True)

    def test_explicit_previous_day_uses_real_current_clock_without_claiming_current_coverage(self):
        view=invented_view();before=deepcopy(view);next_day=NOW+timedelta(days=1)
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_CURRENT_DAY_REQUIRED'):
            C.build_context(BOOTSTRAP,view,12,now=next_day)
        context=C.build_context(BOOTSTRAP,view,12,now=next_day,event_day='2030-04-01')
        self.assertEqual(context['day'],'2030-04-01')
        self.assertEqual(context['current_day'],'2030-04-02')
        self.assertEqual(context['date_scope'],'HISTORICAL_DAY')
        self.assertEqual(context['minimum_results'],1);self.assertIsNone(context['future_native'])
        self.assertEqual(view,before)
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_FUTURE_NATIVE_REQUIRED'):
            C.build_context(BOOTSTRAP,view,12,now=next_day,event_day='2030-04-01',require_future=True)

    def test_invalid_or_future_target_day_is_rejected(self):
        for day in ('2030-02-30','2030-04-02','20300401'):
            with self.subTest(day=day),self.assertRaisesRegex(ValueError,'SAVED_SITE_EVENT_DAY_INVALID'):
                C.build_context(BOOTSTRAP,invented_view(),12,now=NOW,event_day=day)

    def test_missing_receipts_late_originals_and_future_generation_hold(self):
        view=invented_view()
        for row in view['records']:
            for p in [row.get('prediction'),*row.get('comparison_predictions',[])]:
                if p:p['external_receipt_verified']=False
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_NATIVE_P1_REQUIRED'):
            C.build_context(BOOTSTRAP,view,12,now=NOW)
        view=invented_view();p=view['records'][1]['prediction'];p['persisted_at']=p['cutoff_at']
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_ORIGINAL_CLOCK_INVALID'):
            C.build_context(BOOTSTRAP,view,12,now=NOW)
        view=invented_view();view['records'][0]['comparison_predictions'][0]['generated_at']='2030-04-01T00:01:00Z'
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_FUTURE_ORIGINAL_CLOCK_INVALID'):
            C.build_context(BOOTSTRAP,view,12,now=NOW)


class CLITests(unittest.TestCase):
    def execute(self,*,outside=False,failure=None,history=False,day=None,now=NOW,stage=None,expected_report=None):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'audit/state';state.mkdir(parents=True)
            raw=b'invented-bootstrap'
            (state/'boat-saved-view-input.json').write_text(json.dumps(dict(
                schema='RACE_AI_SAVED_VIEW_INPUT_V1',bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest())))
            target=root/('outside' if outside else '')/'boat-saved-site-context.json'
            git=SimpleNamespace(_saved_history_context=dict(index=dict(days={
                '2030-03-31':{},'2030-04-01':{}})) if history else None)
            view=native_p0_view() if stage=='P0' else invented_view();current=dict(records=view['records'][:-1])
            old=dict(records=view['records'][-1:])
            values=[('b'*40,'c'*64,12,current),('b'*40,'c'*64,12,old)] if history else [('b'*40,'c'*64,12,view)]
            output=io.StringIO()
            expected_path=root/'reconcile-counts.json'
            if expected_report is not None:expected_path.write_text(json.dumps(expected_report))
            with patch.object(C,'ROOT',root),patch.object(C.VCLI,'_environment',return_value=root),\
                 patch.object(C.CLI,'git_auth'),patch.object(C.CLI.F,'open_bootstrap',
                    return_value=BOOTSTRAP,side_effect=failure),\
                 patch.object(C.CLI.F,'FeedRepository',return_value=git),\
                 patch.object(C.CLI.F,'current_view',side_effect=values) as read,\
                 patch.dict(os.environ,RUNNER_TEMP=folder),redirect_stdout(output):
                code=C.main(['--output',str(target),*(['--day',day] if day is not None else []),
                             *(['--stage',stage] if stage is not None else []),
                             *(['--expected-original-report',str(expected_path)] if expected_report is not None else [])],now=now)
            context=json.loads(target.read_text()) if target.exists() else None
            mode=stat.S_IMODE(target.stat().st_mode) if target.exists() else None
            return code,output.getvalue(),context,mode,read.call_args_list

    def test_actions_context_is_private_and_stdout_contains_only_counts(self):
        code,output,context,mode,calls=self.execute()
        self.assertEqual(code,0);self.assertEqual(mode,0o600)
        self.assertNotIn(context['owner_url'],output);self.assertNotIn('#saved=',output)
        report=json.loads(output);self.assertEqual(report['native_p1_groups'],2)
        self.assertFalse(report['plaintext_published']);self.assertEqual(len(calls),1)

    def test_explicit_p0_cli_counts_are_never_labeled_as_p1(self):
        expected=original_report(native_p0_view())
        code,output,context,mode,_=self.execute(stage='P0',now=NOW+timedelta(hours=2),expected_report=expected)
        self.assertEqual(code,0);self.assertEqual(mode,0o600)
        report=json.loads(output)
        self.assertEqual(report['stage'],'P0');self.assertEqual(report['native_group_count'],2)
        self.assertEqual(report['native_p0_groups'],2);self.assertNotIn('native_p1_groups',report)
        self.assertEqual(context['stage'],'P0');self.assertNotIn(context['owner_url'],output)
        self.assertEqual(context['expected_original']['original_id'],expected['original_id'])

    def test_history_context_reads_an_existing_prior_day_without_publishing(self):
        code,_,context,_,calls=self.execute(history=True)
        self.assertEqual(code,0);self.assertEqual(context['old_completed'],1)
        self.assertEqual(calls[1].kwargs,dict(day='2030-03-31'))

    def test_explicit_day_selects_its_history_and_earlier_day_once_after_midnight(self):
        code,_,context,_,calls=self.execute(history=True,day='2030-04-01',now=NOW+timedelta(days=1))
        self.assertEqual(code,0);self.assertEqual(context['day_races'],3)
        self.assertEqual(context['current_day'],'2030-04-02')
        self.assertEqual(calls[0].kwargs,dict(day='2030-04-01'))
        self.assertEqual(calls[1].kwargs,dict(day='2030-03-31'))

    def test_public_output_and_private_exception_text_are_rejected_without_leak(self):
        code,output,context,_,calls=self.execute(outside=True)
        self.assertEqual(code,2);self.assertIsNone(context);self.assertEqual(calls,[])
        self.assertIn('SAVED_SITE_PRIVATE_OUTPUT_REQUIRED',output)
        code,output,context,_,_=self.execute(failure=RuntimeError('private-owner-url-and-key-fixture'))
        self.assertEqual(code,2);self.assertIsNone(context)
        self.assertNotIn('private-owner-url-and-key-fixture',output)

    def test_non_actions_environment_stops_before_reading_live_state(self):
        output=io.StringIO()
        with patch.dict(os.environ,{},clear=True),patch.object(C.CLI.F,'current_view') as read,\
             redirect_stdout(output):
            self.assertEqual(C.main(['--output','/tmp/boat-saved-site-context.json'],now=NOW),2)
        read.assert_not_called()


@unittest.skipUnless(shutil.which('node'),'Node is unavailable')
class BrowserAdmissionTests(unittest.TestCase):
    def test_pagination_native_identity_and_request_privacy_contracts(self):
        script=Path(C.__file__).resolve().parents[1]/'tests/saved_site_check.test.cjs'
        result=subprocess.run(['node','--test',str(script)],text=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_foreign_hosts_queries_and_invalid_fragments_hold_before_browser_start(self):
        context=C.build_context(BOOTSTRAP,invented_view(),12,now=NOW)
        script=Path(C.__file__).with_name('boat_saved_site_check.cjs')
        program="const c=require(process.argv[1]);const fs=require('node:fs');try{c.validate(JSON.parse(fs.readFileSync(0,'utf8')));}catch{process.exitCode=2;}"
        examples=[(context,0)]
        for url in (context['owner_url'].replace('haji84.github.io','example.invalid'),
                    context['owner_url'].replace('/RACE-AI/','/RACE-AI/?key=fixture'),
                    context['owner_url'].replace('#saved=','#unknown=')):
            examples.append((dict(context,owner_url=url),2))
        for value,expected in examples:
            with self.subTest(expected=expected):
                result=subprocess.run(['node','-e',program,str(script)],input=json.dumps(value),
                    text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
                self.assertEqual(result.returncode,expected)
                self.assertEqual(result.stdout,'');self.assertEqual(result.stderr,'')


if __name__=='__main__':unittest.main()
