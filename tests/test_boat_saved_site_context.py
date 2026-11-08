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


class ContextTests(unittest.TestCase):
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
        self.assertEqual(context['native_p1_races'],3)
        self.assertEqual(context['future_native_races'],2)
        self.assertEqual(context['latest_native_cutoff_lead_seconds'],1200)
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
    def execute(self,*,outside=False,failure=None,history=False,day=None,now=NOW,require_future=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'audit/state';state.mkdir(parents=True)
            raw=b'invented-bootstrap'
            (state/'boat-saved-view-input.json').write_text(json.dumps(dict(
                schema='RACE_AI_SAVED_VIEW_INPUT_V1',bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest())))
            target=root/('outside' if outside else '')/'boat-saved-site-context.json'
            git=SimpleNamespace(_saved_history_context=dict(index=dict(days={
                '2030-03-31':{},'2030-04-01':{}})) if history else None)
            view=invented_view();current=dict(records=view['records'][:-1])
            old=dict(records=view['records'][-1:])
            values=[('b'*40,'c'*64,12,current),('b'*40,'c'*64,12,old)] if history else [('b'*40,'c'*64,12,view)]
            output=io.StringIO()
            with patch.object(C,'ROOT',root),patch.object(C.VCLI,'_environment',return_value=root),\
                 patch.object(C.CLI,'git_auth'),patch.object(C.CLI.F,'open_bootstrap',
                    return_value=BOOTSTRAP,side_effect=failure),\
                 patch.object(C.CLI.F,'FeedRepository',return_value=git),\
                 patch.object(C.CLI.F,'current_view',side_effect=values) as read,\
                 patch.dict(os.environ,RUNNER_TEMP=folder),redirect_stdout(output):
                code=C.main(['--output',str(target),*(['--day',day] if day is not None else []),*(['--require-future'] if require_future else [])],now=now)
            context=json.loads(target.read_text()) if target.exists() else None
            mode=stat.S_IMODE(target.stat().st_mode) if target.exists() else None
            return code,output.getvalue(),context,mode,read.call_args_list

    def test_actions_context_is_private_and_stdout_contains_only_counts(self):
        code,output,context,mode,calls=self.execute()
        self.assertEqual(code,0);self.assertEqual(mode,0o600)
        self.assertNotIn(context['owner_url'],output);self.assertNotIn('#saved=',output)
        report=json.loads(output);self.assertEqual(report['native_p1_groups'],2)
        self.assertFalse(report['plaintext_published']);self.assertEqual(len(calls),1)

    def test_missing_future_reports_counts_without_creating_or_leaking_private_context(self):
        code,output,context,_,_=self.execute(now=NOW+timedelta(hours=1),require_future=True)
        self.assertEqual(code,2);self.assertIsNone(context);report=json.loads(output)
        self.assertEqual(report['reason'],'SAVED_SITE_FUTURE_NATIVE_REQUIRED')
        self.assertEqual(report['native_p1_races'],3);self.assertEqual(report['future_native_races'],0)
        self.assertEqual(report['latest_native_cutoff_lead_seconds'],-2400)
        self.assertNotIn('owner_url',report);self.assertNotIn('#saved=',output)
        self.assertNotIn(base64.urlsafe_b64encode(BOOTSTRAP['key']).decode().rstrip('='),output)

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
